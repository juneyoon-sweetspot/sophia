"""하루 다이제스트 러너 — tracked 프로젝트를 한 라운드 전진시키고 '한 통'을 보낸다.

설계(라운드마다 무엇이 바뀌나):
 - tracked 레지스트리(사람이 고른 cwd)만 본다. 자동 추측 아님.
 - 라운드마다 각 cwd 의 '최신 *사람* 세션'을 재임포트한다(SOPHIA 자기세션 제외) →
   사이에 사람이 한 작업이 반영됨. 사람이 안 건드린 프로젝트는 그대로(재나그 안 함).
 - goal 은 cwd 별로 *고정*(레지스트리 메모) → resume 가 라운드 간 결정거리를 누적.
 - 워커는 read_only(plan+strict-mcp) → 파일·MCP 부작용 0.
 - 다이제스트는 MultiNotifier: 이메일(주) + 파일(폴백). 이메일 죽어도 파일은 남는다.

cron/launchd 로 몇 시간마다 1회 호출하는 걸 권장(견고). 누적은 resume 가 담당.
  source ~/.sophia/mail.env   # gmail_setup.py 가 만든 것
  python3 scripts/daily.py [--stamp 2026-06-01T09:00]
"""
from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sophia.adapters.claude_code.adapter import ClaudeCodeBackend  # noqa: E402
from sophia.adapters.notifier.email_smtp import EmailNotifier  # noqa: E402
from sophia.adapters.notifier.file_notifier import FileNotifier  # noqa: E402
from sophia.adapters.notifier.multi import MultiNotifier  # noqa: E402
from sophia.adapters.notifier.stdout import StdoutNotifier  # noqa: E402
from sophia.adapters.registry import Registry  # noqa: E402
from sophia.adapters.sessions import import_projects  # noqa: E402
from sophia.adapters.thinker.claude_cli import ClaudeCliThinker  # noqa: E402
from sophia.core.loop.scheduler import Scheduler  # noqa: E402
from sophia.core.manager.director import Director  # noqa: E402
from sophia.core.portfolio.digest import build_digest  # noqa: E402
from sophia.core.portfolio.portfolio import Portfolio  # noqa: E402
from sophia.core.portfolio.project import Blocker, Project, should_skip_blocked  # noqa: E402
from sophia.core.state.handoff import Handoff  # noqa: E402

DIGEST_DIR = Path.home() / ".sophia" / "digests"
HANDOFF_DIR = Path.home() / ".sophia" / "handoffs"

READONLY_REQUEST = (
    "지금은 분석만 한다(읽기 전용): 실제 파일을 읽어 현재 어디까지 왔는지 추정하고, "
    "'진전 기준'을 향해 다음 한 스텝을 제안하라. 경계를 넘지 말고, 사람만 정할 수 있는 "
    "결정이 있으면 재구성 질문으로 남겨라.\n\n"
    "목표(intent): {intent}\n진전 기준(progress): {progress}\n경계(boundaries): {boundaries}\n"
    "사람의 마지막 지시: {last}"
)


def _build_notifier(stamp: str):
    email = EmailNotifier.from_env()  # ~/.sophia/mail.env 를 source 했으면 잡힘
    file = FileNotifier(DIGEST_DIR, stamp=stamp)
    channels = [c for c in (email, file) if c]
    if not email:
        print("ⓘ 이메일 미설정 → 파일로만(폴백). gmail_setup.py 로 메일 켜기.")
    return MultiNotifier(*channels) if channels else StdoutNotifier()


def _project_for(t) -> Project | None:
    # 그 cwd 의 최신 '사람' 세션만 재임포트(SOPHIA 자기세션 자동 제외).
    ps = import_projects(only_cwds={t.cwd}, min_user_msgs=1,
                         handoff_dir=HANDOFF_DIR)
    if not ps:
        return None
    p = ps[0]
    # 의도 브리프(있으면)를 나침반으로. goal 은 고정(intent) → resume 가 누적.
    p.goal = t.intent or t.note or Path(t.cwd).name
    p.meta["progress"] = t.progress
    p.meta["boundaries"] = t.boundaries
    # 기존 핸드오프의 미결 blocker + 막힌 시점 mtime 을 불러온다(디스트 나열 + skip 판정용).
    prior = _load_handoff(p.handoff_path)
    p.meta["blocked_mtime"] = getattr(prior, "blocked_mtime", 0.0)
    p.blockers = [
        Blocker(project_id=p.id, question=b.get("question", ""),
                leverage=int(b.get("leverage", 1) or 1), context=b.get("context", ""))
        for b in (getattr(prior, "blockers", []) or []) if b.get("question")
    ]
    return p


def _load_handoff(path: str) -> Handoff | None:
    try:
        if Path(path).exists():
            return Handoff.load(path)
    except Exception:
        pass
    return None


def _factory(p: Project):
    last = (p.pending_requests or [""])[0]
    req = READONLY_REQUEST.format(
        intent=p.goal, progress=p.meta.get("progress", "") or "(미지정)",
        boundaries=p.meta.get("boundaries", "") or "(없음)", last=last,
    )
    return Scheduler(
        backend=ClaudeCodeBackend(read_only=True, cwd=p.meta["cwd"]),
        director=Director(goal=p.goal),
        thinker=ClaudeCliThinker(),
        goal=p.goal,
        session_id=p.id,
        handoff_path=p.handoff_path,
        premise_count=1,
        max_cycles=1,
        surface_blockers=True,
        resume=True,                      # 라운드 간 결정거리 누적
        pending_requests=[req],
    )


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--stamp", default="", help="다이제스트 타임스탬프(로그용)")
    ap.add_argument("--max-week-pct", type=int, default=None,
                    help="주간 quota 사용률이 이 %% 이상이면 이번 라운드 건너뜀(자율작업 정지)")
    args = ap.parse_args()

    reg = Registry.load()
    if not reg.items:
        print("등록된 프로젝트 없음. `python3 scripts/track.py add <cwd> \"메모\"` 로 등록.")
        return 1

    projects = [pr for t in reg.items if (pr := _project_for(t))]
    if not projects:
        print("tracked cwd 에서 사람 세션을 못 찾음(전부 SOPHIA 세션이거나 비어있음).")
        return 1

    # quota 확인(구독이면 세션/주간 %, API면 모드만). /usage PTY 스크랩.
    from sophia.adapters.usage import read_usage
    u = read_usage()
    if u.ok:
        print(f"📊 사용량: 세션 {u.session_pct}% · 주간 {u.week_pct}% (mode={u.mode})")
        if args.max_week_pct is not None and (u.week_pct or 0) >= args.max_week_pct:
            print(f"⛔ 주간 {u.week_pct}% ≥ 상한 {args.max_week_pct}% → 이번 라운드 건너뜀.")
            return 0
    else:
        print(f"📊 사용량 읽기 실패(무시하고 진행). mode={u.mode}")

    # run vs wait: 막혀 있고 사람이 그 뒤로 안 건드린 프로젝트는 워커 재실행 안 함(quota·재나그 방지).
    run, wait = [], []
    for p in projects:
        if should_skip_blocked(len(p.blockers), p.meta["blocked_mtime"], p.meta["mtime"]):
            p.status = "blocked"
            wait.append(p)
        else:
            run.append(p)

    print(f"하루 라운드 — tracked {len(projects)}개: 주행 {len(run)} · 대기(당신 차례) {len(wait)}")
    for p in run:
        print(f"  ▶ [{p.id}] {p.goal[:50]}")
    for p in wait:
        print(f"  ⏸ [{p.id}] 결정 대기 {len(p.blockers)}건 — 당신이 건드리면 재개")

    from sophia.adapters import telemetry
    telemetry.reset()
    if run:
        # 막힌 것 빼고 진행 가능한 것만 실제 워커 주행. (digest 내부발행 안 쓰고 아래서 합쳐 발행)
        pf = Portfolio(projects=run, scheduler_factory=_factory,
                       notifier=None, digest_interval=len(run), max_ticks=len(run))
        asyncio.run(pf.run())
        # 새로 막힌 프로젝트는 막힌 시점 mtime 을 핸드오프에 스탬프(다음 라운드 skip 기준).
        for p in run:
            if p.blockers:
                ho = _load_handoff(p.handoff_path)
                if ho is not None:
                    ho.blocked_mtime = p.meta["mtime"]
                    try:
                        ho.save(p.handoff_path)
                    except OSError:
                        pass
    usd, calls = telemetry.snapshot()

    # 최종 단일 다이제스트 = 진행분 + 대기분의 미결 결정 전부(나열은 하되 재도출 안 함).
    digest = build_digest(run + wait, now_tick=0)
    notifier = _build_notifier(args.stamp)
    notifier.send("[SOPHIA 다이제스트]", digest)
    print("\n" + digest)
    print(f"\n💰 이 라운드: ${usd:.3f} ({calls} claude 호출) · 파일 {DIGEST_DIR}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
