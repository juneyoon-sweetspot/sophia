"""엔트리포인트 — 조각들을 와이어링. `python -m sophia [--real]`.

기본은 오프라인(fake) 데모: API 키/claude 없이 전체 흐름을 보여준다.
--real 은 ClaudeCodeBackend + AnthropicThinker 로 실제 동작.
"""
from __future__ import annotations

import argparse
import asyncio
import sys

from .core.loop.scheduler import Scheduler
from .core.manager.director import Director


def build_offline(goal: str) -> Scheduler:
    from .adapters.fake_worker import FakeWorkerBackend
    from .adapters.thinker.fake import FakeThinker

    thinker = FakeThinker(
        script=[
            {  # 전제 3개
                "premises": [
                    {"id": "A", "statement": f"{goal} — 최소 기능부터", "rationale": "빠른 검증"},
                    {"id": "B", "statement": f"{goal} — 안정성 우선", "rationale": "롱런 신뢰성"},
                    {"id": "C", "statement": f"{goal} — 확장성 우선", "rationale": "멀티 백엔드"},
                ]
            },
            "세 전제(최소기능/안정성/확장성)로 병렬 진행했고 모두 모의 완료, 확장성안만 보류 후보입니다.",
        ]
    )
    director = Director(goal=goal, monitor_targets=["LLM 컨텍스트 엔지니어링"])
    return Scheduler(
        backend=FakeWorkerBackend(),
        director=director,
        thinker=thinker,
        goal=goal,
        session_id="offline-demo",
        handoff_path="handoff.json",
        max_runtime_s=3600,
        max_cycles=1,  # 데모는 요청 1건만 — 결정론적(스크립트 소진 후 fake 에코 방지)
        idle_sleep_s=0.05,
        pending_requests=[goal],
    )


def _build_thinker(name: str):
    """thinker 선택. 'claude-cli'(기본)는 pip 없이 claude CLI 로 돈다.
    'anthropic'은 SDK 필요. 'auto'는 anthropic 우선·실패 시 claude-cli 폴백."""
    if name == "anthropic":
        from .adapters.thinker.anthropic_thinker import AnthropicThinker
        return AnthropicThinker()
    if name == "auto":
        try:
            from .adapters.thinker.anthropic_thinker import AnthropicThinker
            return AnthropicThinker()
        except Exception:
            from .adapters.thinker.claude_cli import ClaudeCliThinker
            return ClaudeCliThinker()
    from .adapters.thinker.claude_cli import ClaudeCliThinker
    return ClaudeCliThinker()


def _build_notifier():
    """이메일 설정이 있으면 EmailNotifier, 없으면 StdoutNotifier 로 폴백."""
    from .adapters.notifier.email_smtp import EmailNotifier
    from .adapters.notifier.stdout import StdoutNotifier

    return EmailNotifier.from_env() or StdoutNotifier()


def build_real(goal: str, backend_name: str = "claude", thinker_name: str = "claude-cli",
               resume: bool = False, base_repo: str | None = None,
               anticipate: bool = False) -> Scheduler:
    # base_repo 가 git repo 면 전제별 worktree 격리가 engage(병렬 전제 cwd 충돌 방지).
    if backend_name == "codex":
        from .adapters.codex.adapter import CodexBackend

        backend = CodexBackend(base_repo=base_repo)
    else:
        from .adapters.claude_code.adapter import ClaudeCodeBackend

        backend = ClaudeCodeBackend(base_repo=base_repo)

    from .adapters.resource.system import SystemResourceGovernor

    director = Director(goal=goal, monitor_targets=["LLM 컨텍스트 엔지니어링"])
    return Scheduler(
        backend=backend,
        director=director,
        thinker=_build_thinker(thinker_name),
        goal=goal,
        session_id="run",
        # resume 시엔 caller 큐를 비워 이전 handoff 의 미완료 큐를 복원하게 한다.
        pending_requests=[] if resume else [goal],
        resume=resume,
        governor=SystemResourceGovernor(),   # 하드웨어 부하로 동시성 조절
        notifier=_build_notifier(),          # 이메일(설정 시) / stdout 폴백
        anticipate=anticipate,               # 보고 후 반응 예측 → 선제 작업
    )


WELCOME = """\
SOPHIA — a manager-layer agent harness.

You give one goal. SOPHIA splits it into several premises, delegates each to a
real coding agent (Claude Code / Codex) in parallel, picks a winner, and reports
back in 5 sentences — so you manage, not micromanage.

QUICK START
  sophia demo                 Run an offline demo (no API key, no claude needed)
  sophia tui                  Open the portfolio dashboard (TUI)
  sophia track                Pick which of your past sessions to manage (interactive)
  sophia run "<your goal>"    Delegate a real goal to claude/codex workers
  sophia --help               Full options

EXAMPLES
  sophia run "add a caching layer to this project"
  sophia run "build a TODO cli" --base-repo .   # isolate workers in git worktrees
  sophia run "..." --anticipate                 # keep working while you reply
  sophia run "..." --resume                     # continue a previous session

Real delegation (`run`) needs the `claude` CLI on your PATH. The demo/tui do not.
"""


def _run_scheduler(args) -> None:
    sched = (build_real(args.goal, args.backend, args.thinker, args.resume,
                        args.base_repo, args.anticipate)
             if args.real else build_offline(args.goal))
    ho = asyncio.run(sched.run())
    print(f"\n[handoff] status={ho.status} decisions={len(ho.decisions)} "
          f"discarded={len(ho.discarded)}")


def main() -> None:
    argv = sys.argv[1:]

    # 인자 없이 `sophia` → 환영 + 빠른 시작 (예전엔 데모가 곧장 돌아 혼란스러웠음)
    if not argv:
        print(WELCOME)
        return

    # 서브커맨드: tui / demo / run / track
    cmd = argv[0]
    if cmd == "tui":
        from .ui.tui import main as tui_main
        tui_main()
        return
    if cmd == "track":
        # 인터랙티브 피커로 '내 프로젝트' 고르기(경로 타이핑 없이 토글).
        from .ui.picker import main as picker_main
        picker_main()
        return
    if cmd == "demo":
        print("• Running offline demo (no API key needed)…\n")
        _run_scheduler(_parse_args(["--goal", "Build something useful"]))
        return
    if cmd == "run":
        # `sophia run "<goal>" [opts]` — goal 을 위치인자로 받는 친절한 형태
        rest = argv[1:]
        goal = None
        if rest and not rest[0].startswith("-"):
            goal, rest = rest[0], rest[1:]
        a = _parse_args(["--real", *rest] + (["--goal", goal] if goal else []))
        if not goal:
            print("✗ Usage: sophia run \"<your goal>\" [--base-repo .] [--anticipate]")
            return
        _run_scheduler(a)
        return

    # 그 외엔 기존 플래그 파서 (sophia --real --goal ... 등 하위호환)
    _run_scheduler(_parse_args(argv))


def _parse_args(argv):
    ap = argparse.ArgumentParser(
        prog="sophia",
        description="SOPHIA — manager-layer agent harness. "
                    "Run `sophia` with no args for a quick start.",
        epilog="Examples:\n"
               "  sophia demo\n"
               "  sophia run \"add a caching layer\" --base-repo .\n"
               "  sophia tui\n",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    ap.add_argument("--real", action="store_true",
                    help="delegate to a real worker backend (needs claude/codex on PATH)")
    ap.add_argument("--backend", choices=["claude", "codex"], default="claude",
                    help="worker backend when --real (same port, swap freely)")
    ap.add_argument("--thinker", choices=["claude-cli", "anthropic", "auto"],
                    default="claude-cli",
                    help="manager-thinking backend. claude-cli=no pip (default)")
    ap.add_argument("--goal", default="Build something useful",
                    help="the goal to pursue")
    ap.add_argument("--resume", action="store_true",
                    help="continue a previous session (same goal's handoff.json)")
    ap.add_argument("--base-repo", default=None,
                    help="git repo path; isolates parallel premises in worktrees")
    ap.add_argument("--anticipate", action="store_true",
                    help="after reporting, predict your reaction and pre-do likely work")
    return ap.parse_args(argv)


if __name__ == "__main__":
    main()
