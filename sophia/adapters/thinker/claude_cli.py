"""ClaudeCliThinker — pip 없이 `claude` CLI 로 관리자 메타인지를 돌린다.

왜 존재하나: AnthropicThinker 는 pip-설치형 `anthropic` SDK 를 요구한다. claude CLI 가
이미 PATH 에 인증돼 있는 환경(이 머신 포함)에서는 SDK 없이도 같은 작은-모델 추론을
CLI 로 할 수 있다. 이게 없으면 `--real` 진입점이 ModuleNotFoundError 로 즉사한다.

견고성은 claude_code 어댑터와 동일 패턴: communicate() 동시 배수(파이프 deadlock 방지),
start_new_session+killpg(손자 정리), 타임아웃. schema 가 오면 프롬프트로 JSON 을 강제하고
result 의 ```json 펜스를 벗겨 파싱한다(실패 시 관대한 폴백).
"""
from __future__ import annotations

import asyncio
import json
import os
import re
import shutil
import signal
from typing import Any

from ...ports.thinker import Thinker

DEFAULT_MODEL = "haiku"  # 관리자 메타인지는 작고 싸게


class ClaudeCliThinker(Thinker):
    def __init__(
        self,
        claude_bin: str = "claude",
        model: str = DEFAULT_MODEL,
        default_system: str = "",
        timeout_s: float = 5 * 60,
    ) -> None:
        self.claude_bin = claude_bin
        self.model = model
        self.default_system = default_system
        self.timeout_s = timeout_s

    async def think(
        self, prompt: str, *, system: str = "", schema: dict[str, Any] | None = None
    ) -> Any:
        if shutil.which(self.claude_bin) is None:
            raise RuntimeError(f"'{self.claude_bin}' 실행파일을 찾을 수 없음")

        sys_prompt = system or self.default_system
        full_prompt = self._compose(prompt, schema)

        argv = [
            self.claude_bin, "-p", full_prompt,
            "--output-format", "json",
            "--model", self.model,
        ]
        if sys_prompt:
            argv += ["--append-system-prompt", sys_prompt]

        result_text = await self._invoke(argv)
        if schema is not None:
            return self._extract_json(result_text)
        return result_text

    # ── 내부 ──
    @staticmethod
    def _compose(prompt: str, schema: dict[str, Any] | None) -> str:
        if schema is None:
            return prompt
        # 스키마를 힌트로 주고 JSON 만 출력하도록 강제(도구 강제가 CLI 엔 없으므로 프롬프트로).
        return (
            f"{prompt}\n\n"
            f"아래 JSON 스키마에 정확히 맞는 JSON 객체 하나만 출력하라. "
            f"설명·코드펜스·앞뒤 텍스트 없이 순수 JSON 만:\n"
            f"{json.dumps(schema, ensure_ascii=False)}"
        )

    async def _invoke(self, argv: list[str]) -> str:
        try:
            proc = await asyncio.create_subprocess_exec(
                *argv,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                start_new_session=True,
            )
        except Exception as e:
            raise RuntimeError(f"claude 실행 실패: {e}") from e

        try:
            stdout, stderr = await asyncio.wait_for(
                proc.communicate(), timeout=self.timeout_s
            )
        except (asyncio.TimeoutError, TimeoutError) as e:
            await self._terminate_group(proc)
            raise RuntimeError(f"thinker 타임아웃 {self.timeout_s}s 초과") from e

        if proc.returncode != 0:
            err = stderr.decode("utf-8", "replace").strip()
            raise RuntimeError(f"claude 비정상 종료(rc={proc.returncode}): {err[:200]}")

        return self._result_from_envelope(stdout)

    @staticmethod
    def _result_from_envelope(stdout: bytes) -> str:
        """claude --output-format json 봉투에서 result 문자열 추출."""
        text = stdout.decode("utf-8", "replace").strip()
        try:
            env = json.loads(text)
            if isinstance(env, dict) and "result" in env:
                if env.get("is_error"):
                    raise RuntimeError(f"claude is_error: {env.get('result')}")
                from .. import telemetry  # 비용 합산(있으면)
                telemetry.add(env.get("total_cost_usd"))
                return env.get("result") or ""
        except json.JSONDecodeError:
            pass
        return text  # 봉투가 아니면 원문 그대로(폴백)

    @staticmethod
    def _extract_json(result_text: str) -> Any:
        """result 에서 JSON 추출: ```json 펜스 제거 → 객체 구간 파싱."""
        s = result_text.strip()
        # ```json ... ``` 또는 ``` ... ``` 펜스 제거
        fence = re.search(r"```(?:json)?\s*(.*?)```", s, re.DOTALL)
        if fence:
            s = fence.group(1).strip()
        try:
            return json.loads(s)
        except json.JSONDecodeError:
            pass
        # 첫 { ... 마지막 } 구간만 떼어 재시도(앞뒤 설명 섞인 경우)
        start, end = s.find("{"), s.rfind("}")
        if start != -1 and end > start:
            try:
                return json.loads(s[start : end + 1])
            except json.JSONDecodeError:
                pass
        raise RuntimeError(f"thinker 구조화 응답 파싱 실패: {result_text[:200]}")

    @staticmethod
    async def _terminate_group(proc) -> None:
        try:
            os.killpg(os.getpgid(proc.pid), signal.SIGKILL)
        except (ProcessLookupError, PermissionError):
            proc.kill()
        except Exception:
            pass
        try:
            await asyncio.wait_for(proc.wait(), timeout=5)
        except Exception:
            pass
