"""Claude Code 어댑터 — `claude -p` 를 비대화형으로 띄우고 stream-json 을 파싱.

백엔드 의존 코드는 이 파일에 격리된다. Codex 어댑터는 같은 포트를 구현해 옆에 둔다.

주의(리뷰 반영):
- stdout/stderr 를 communicate() 로 동시에 배수한다. 한쪽만 읽으면 OS 파이프 버퍼(~64KB)가
  차서 자식이 write 에서 블록 → deadlock 으로 6h 루프가 통째로 멈춘다.
- 기본 타임아웃은 6h 가 아니라 30분. 한 일꾼이 전체 예산을 삼키지 못하게.
- start_new_session 으로 새 프로세스 그룹을 만들고, 타임아웃 시 그룹 전체를 죽인다.
  claude(Node)는 MCP 서버 등 손자 프로세스를 띄우므로 부모만 kill 하면 고아가 남는다.
- spec.isolation=True 이고 base_repo 가 git repo 면 git worktree 로 격리 cwd 를 만들어
  거기서 실행한다(병렬 전제 파일 충돌 방지). base_repo 가 없으면 격리는 no-op.
"""
from __future__ import annotations

import asyncio
import json
import os
import shutil
import signal

from ...ports.worker import Capabilities, WorkerBackend, WorkResult, WorkSpec
from ..artifacts import artifacts_from_tool_uses
from ..isolation import worktree

DEFAULT_TIMEOUT_S = 30 * 60  # 일꾼 1건당 상한. 전체 6h 예산보다 훨씬 작게.


class ClaudeCodeBackend(WorkerBackend):
    def __init__(
        self,
        claude_bin: str = "claude",
        extra_args: list[str] | None = None,
        timeout_s: float = DEFAULT_TIMEOUT_S,
        base_repo: str | None = None,
        read_only: bool = False,
        cwd: str | None = None,
    ) -> None:
        self.claude_bin = claude_bin
        self.extra_args = extra_args or []
        self.timeout_s = timeout_s
        self.base_repo = base_repo  # git repo 면 worktree 격리 가능
        # cwd: 워커를 이 디렉토리에서 돌린다(포트폴리오가 프로젝트별로 다르게 줄 때).
        # isolation worktree 가 잡히면 그쪽이 우선. None 이면 프로세스 cwd 상속.
        self.cwd = cwd
        # read_only: 워커를 '계획 모드 + MCP 미로드'로 펜싱한다.
        #  - --permission-mode plan: 파일 쓰기/편집/실행 차단(읽고 분석·계획만)
        #  - --strict-mcp-config(+--mcp-config 없음): MCP 서버 0개 → 외부 부작용 차단
        # 라이브에서 cwd 격리가 MCP 부작용(예: 노션 페이지 생성)을 못 막은 걸 보고 추가.
        # 이 모드면 '실제 프로젝트 cwd'에서 돌려도 안전 → 고품질 분석 + 부작용 0.
        self.read_only = read_only

    def capabilities(self) -> Capabilities:
        return Capabilities(
            worktree_isolation=bool(self.base_repo),  # base_repo 있을 때만 격리 가능
            structured_output=True,
            max_context_tokens=200_000,
            streaming=True,
        )

    async def run(self, spec: WorkSpec) -> WorkResult:
        if shutil.which(self.claude_bin) is None:
            return WorkResult(summary=f"'{self.claude_bin}' 실행파일을 찾을 수 없음", ok=False)

        argv = self._build_argv(spec)
        # isolation=True 면 git worktree 로 격리 cwd 확보(불가 시 None=격리 안 함)
        repo = self.base_repo if spec.isolation else None
        async with worktree(repo, spec.premise_id or "task") as wt_cwd:
            run_cwd = wt_cwd or self.cwd  # worktree 격리 우선, 없으면 지정 cwd, 둘 다 없으면 상속
            try:
                proc = await asyncio.create_subprocess_exec(
                    *argv,
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.PIPE,
                    start_new_session=True,  # 새 프로세스 그룹 → 손자까지 한 번에 정리
                    cwd=run_cwd,  # None 이면 현재 cwd
                )
            except Exception as e:  # spawn 실패 → 루프가 죽지 않게 안전 반환
                return WorkResult(summary=f"claude 실행 실패: {e}", ok=False)

            try:
                stdout, stderr = await asyncio.wait_for(
                    proc.communicate(), timeout=self.timeout_s
                )
            except (asyncio.TimeoutError, TimeoutError):
                await self._terminate_group(proc)
                return WorkResult(summary=f"타임아웃 {self.timeout_s}s 초과", ok=False)

        events = self._parse_stream(stdout)
        return self._parse(events, proc.returncode, stderr)

    @staticmethod
    async def _terminate_group(proc) -> None:
        """프로세스 그룹 전체를 SIGKILL 하고 회수한다(고아 손자 방지)."""
        try:
            os.killpg(os.getpgid(proc.pid), signal.SIGKILL)
        except (ProcessLookupError, PermissionError):
            proc.kill()  # 그룹 kill 불가 시 직접 자식만
        except Exception:
            pass
        try:
            await asyncio.wait_for(proc.wait(), timeout=5)  # 좀비 reap
        except Exception:
            pass

    def _build_argv(self, spec: WorkSpec) -> list[str]:
        argv = [
            self.claude_bin, "-p", self._compose_prompt(spec),
            "--output-format", "stream-json", "--verbose",
        ]
        if self.read_only:  # 계획 모드 + MCP 미로드 = 파일·외부 부작용 차단
            argv += ["--permission-mode", "plan", "--strict-mcp-config"]
        argv += self.extra_args
        return argv

    def _compose_prompt(self, spec: WorkSpec) -> str:
        if spec.context:
            return f"{spec.context}\n\n---\n\n{spec.instruction}"
        return spec.instruction

    @staticmethod
    def _parse_stream(stdout: bytes) -> list[dict]:
        events: list[dict] = []
        for raw in stdout.splitlines():
            line = raw.decode("utf-8", "replace").strip()
            if not line:
                continue
            try:
                events.append(json.loads(line))
            except json.JSONDecodeError:
                continue  # 비-JSON 라인 무시
        return events

    def _parse(
        self, events: list[dict], returncode: int | None, stderr: bytes = b""
    ) -> WorkResult:
        # stream-json: type=="result" 가 최종. 없으면 assistant 텍스트로 폴백.
        result_text = ""
        is_error = False
        assistant_text: list[str] = []
        tool_uses: list[dict] = []
        for ev in events:
            t = ev.get("type")
            if t == "result":
                result_text = ev.get("result", "") or result_text
                is_error = bool(ev.get("is_error", False))
            elif t == "assistant":
                # message.content 의 text/tool_use 블록 수집
                msg = ev.get("message", {})
                for block in msg.get("content", []) or []:
                    if not isinstance(block, dict):
                        continue
                    if block.get("type") == "text":
                        assistant_text.append(block.get("text", ""))
                    elif block.get("type") == "tool_use":
                        tool_uses.append(block)

        summary = result_text or "".join(assistant_text)
        if not summary:
            err = stderr.decode("utf-8", "replace").strip()
            summary = f"(no result) {err[:200]}" if err else "(no result)"
        ok = (returncode == 0) and not is_error
        return WorkResult(
            summary=summary, ok=ok, artifacts=artifacts_from_tool_uses(tool_uses)
        )
