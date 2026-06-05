"""하루 다이제스트 러너 — '하루 동안 닻 내린 일을 quota 예산 한도껏 계속'.

모델(사용자 정의):
 - 사람 응답주기 ≈ 하루. 그 하루 안에는 SOPHIA 가 계속 일한다(막혔다고 침묵 X).
 - 단 '이상한 짓' 금지 — 전부 브리프(intent/progress/boundaries)에 닻 내린 일만.
 - 막힌 결정은 *다시 묻지 않고* 우회 → 어느 결정이 나든 도움될 '결정-독립 밑작업'.
 - throttle 목표 = '침묵'이 아니라 '하루 quota 예산'(주간%의 day_budget_pp). 다 쓰면 그제야 대기.
 - 하루 단위 리셋(ledger 날짜 바뀌면 예산 베이스라인 새로).

cron/launchd 가 하루에 여러 번 호출 → 예산 남으면 일하고, 소진되면 결정 목록만 보고.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import sys
import time
from datetime import date
from pathlib import Path

ACTIVE_WINDOW_S = 3600   # 최근 1시간 내 사용 = '활성'(당신이 작업 중) → SOPHIA 비켜줌

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
from sophia.core.manager.pacing import daily_budget_state  # noqa: E402
from sophia.core.portfolio.digest import build_digest  # noqa: E402
from sophia.core.portfolio.portfolio import Portfolio  # noqa: E402
from sophia.core.portfolio.project import Blocker, Project, project_mode  # noqa: E402
from sophia.core.state.handoff import Handoff  # noqa: E402

DIGEST_DIR = Path.home() / ".sophia" / "digests"
HANDOFF_DIR = Path.home() / ".sophia" / "handoffs"
BUDGET_LEDGER = Path.home() / ".sophia" / "day-budget.json"
AUTO_PICK_N = 3   # 선택 없을 때 자동으로 굴릴 최근 프로젝트 수
# 잡동사니(홈·데스크톱·다운로드)는 자동선택에서 제외 — '프로젝트'가 아님.
_JUNK = {str(Path.home()), str(Path.home() / "Desktop"), str(Path.home() / "Downloads")}

# 진행 가능(안 막혔거나 사람이 건드림): 진전 기준을 향해 한 스텝.
READONLY_REQUEST = (
    "지금은 분석만 한다(읽기 전용): 실제 파일을 읽어 현재 어디까지 왔는지 추정하고, "
    "'진전 기준'을 향해 다음 한 스텝을 제안하라. 경계를 넘지 말고, 사람만 정할 수 있는 "
    "결정이 있으면 재구성 질문으로 남겨라.\n\n"
    "목표(intent): {intent}\n진전 기준(progress): {progress}\n경계(boundaries): {boundaries}\n"
    "사람의 마지막 지시: {last}"
)

# 막힘(사람 결정 대기 + 미접촉): 그 결정을 다시 묻지 말고 결정-독립 밑작업으로 우회.
GROUNDWORK_REQUEST = (
    "이 프로젝트는 사람 결정 대기 중이다(아래 미결). 그 결정을 *다시 묻지 마라*. 대신 "
    "어느 결정이 나든 도움될 '결정-독립적' 밑작업을 한 스텝 하라 — 사실 수집·정리·리서치·"
    "준비. 읽기 전용, 경계를 절대 넘지 마라. 정말 새로 사람만 정할 게 생기면 1개만 남겨라.\n\n"
    "목표(intent): {intent}\n진전 기준(progress): {progress}\n경계(boundaries): {boundaries}\n"
    "미결(다시 묻지 말 것): {open}"
)


def _build_notifier(stamp: str):
    email = EmailNotifier.from_env()
    file = FileNotifier(DIGEST_DIR, stamp=stamp)
    channels = [c for c in (email, file) if c]
    if not email:
        print("ⓘ 이메일 미설정 → 파일로만(폴백). gmail_setup.py 로 메일 켜기.")
    return MultiNotifier(*channels) if channels else StdoutNotifier()


def _load_handoff(path: str) -> Handoff | None:
    try:
        if Path(path).exists():
            return Handoff.load(path)
    except Exception:
        pass
    return None


def _project_for(t) -> Project | None:
    ps = import_projects(only_cwds={t.cwd}, min_user_msgs=1, handoff_dir=HANDOFF_DIR)
    if not ps:
        return None
    p = ps[0]
    p.goal = t.intent or t.note or Path(t.cwd).name
    p.meta["progress"] = t.progress or "(미지정)"
    p.meta["boundaries"] = t.boundaries or "(없음)"
    prior = _load_handoff(p.handoff_path)
    p.meta["blocked_mtime"] = getattr(prior, "blocked_mtime", 0.0)
    p.meta["groundwork_mtime"] = getattr(prior, "groundwork_mtime", 0.0)
    p.blockers = [
        Blocker(project_id=p.id, question=b.get("question", ""),
                leverage=int(b.get("leverage", 1) or 1), context=b.get("context", ""))
        for b in (getattr(prior, "blockers", []) or []) if b.get("question")
    ]
    return p


def _factory(p: Project):
    return Scheduler(
        backend=ClaudeCodeBackend(read_only=True, cwd=p.meta["cwd"]),
        director=Director(goal=p.goal), thinker=ClaudeCliThinker(),
        goal=p.goal, session_id=p.id, handoff_path=p.handoff_path,
        premise_count=1, max_cycles=1, surface_blockers=True, resume=True,
        pending_requests=[p.meta["request"]],
    )


def _daily_start_pct(current_week_pct: float, today: str) -> float:
    """하루 예산 베이스라인(오늘 시작 시점 주간%). 날짜 바뀌면 리셋."""
    try:
        d = json.loads(BUDGET_LEDGER.read_text(encoding="utf-8"))
        if d.get("date") == today:
            return float(d.get("start_pct", current_week_pct))
    except Exception:
        pass
    try:
        BUDGET_LEDGER.parent.mkdir(parents=True, exist_ok=True)
        BUDGET_LEDGER.write_text(
            json.dumps({"date": today, "start_pct": current_week_pct}), encoding="utf-8")
    except Exception:
        pass
    return current_week_pct


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--stamp", default="")
    ap.add_argument("--daily-pct", type=float, default=20.0,
                    help="하루 quota 예산(주간%% 증가분 상한). 다 쓰면 대기.")
    ap.add_argument("--max-week-pct", type=int, default=None, help="절대 주간%% 상한(하드 천장)")
    args = ap.parse_args()

    reg = Registry.load()
    items = reg.items
    auto = False
    if not items:
        # 선택 없음 → SOPHIA 가 알아서 최근 프로젝트 몇 개 고른다(잡동사니 제외). 명시 선택이
        # 생기면 그게 우선. ephemeral — 레지스트리엔 안 쓴다(사용자가 안 고른 거라).
        auto = True
        from sophia.adapters.registry import Tracked
        cands = import_projects(rank="recency", top=AUTO_PICK_N,
                                exclude_cwds=_JUNK, min_user_msgs=2)
        items = [Tracked(cwd=c.meta["cwd"]) for c in cands]
        if items:
            print(f"ⓘ 선택 없음 → 최근 프로젝트 {len(items)}개 자동 선택: "
                  + ", ".join(Path(t.cwd).name for t in items))
    projects = [pr for t in items if (pr := _project_for(t))]
    if not projects:
        print("굴릴 프로젝트 없음(선택도, 자동선택 후보도 없음). `python3 -m sophia track`.")
        return 1

    # quota + 하루 예산
    from sophia.adapters.usage import read_usage
    u = read_usage()
    over_budget = False
    if u.ok:
        start = _daily_start_pct(float(u.week_pct or 0), date.today().isoformat())
        used, remaining, exhausted = daily_budget_state(u.week_pct, start, args.daily_pct)
        print(f"📊 세션 {u.session_pct}% · 주간 {u.week_pct}% (mode={u.mode}) · "
              f"오늘 {used:.0f}/{args.daily_pct:.0f}pp 사용(남음 {remaining:.0f}pp)")
        over_budget = exhausted or (
            args.max_week_pct is not None and (u.week_pct or 0) >= args.max_week_pct)
    else:
        print(f"📊 사용량 읽기 실패(예산 게이트 생략). mode={u.mode}")

    from sophia.adapters import telemetry
    telemetry.reset()

    if over_budget:
        # 예산 소진/하드천장: 아무것도 돌리지 않음(결정도 안 비움). 결정 목록만 보고.
        print("⛔ 오늘 quota 예산 소진 → 워커 대기. 결정 목록만 보고(다음 날/관여 시 재개).")
        digest = build_digest(projects, now_tick=0)
        _build_notifier(args.stamp).send("[SOPHIA 다이제스트]", digest)
        print("\n" + digest)
        return 0

    # 모드 결정: active(당신 작업 중→비켜줌) / progress / groundwork / quiet.
    now = time.time()
    for p in projects:
        is_active = (now - p.meta["mtime"]) < ACTIVE_WINDOW_S
        mode = project_mode(len(p.blockers), p.meta["blocked_mtime"],
                            p.meta["groundwork_mtime"], p.meta["mtime"], is_active=is_active)
        p.meta["mode"] = mode
        if mode == "active":
            continue   # 당신이 지금 작업 중 → request 안 만듦(run_list 제외), 디스트엔 나열
        if mode == "progress":
            # ⒜ replace: 사람이 만졌으니 옛 결정 비우고 fresh 가 새로 정의(stale 청소).
            p.blockers = []
            ho = _load_handoff(p.handoff_path)
            if ho is not None:
                ho.blockers = []
                try:
                    ho.save(p.handoff_path)
                except OSError:
                    pass
            p.meta["request"] = READONLY_REQUEST.format(
                intent=p.goal, progress=p.meta["progress"], boundaries=p.meta["boundaries"],
                last=(p.pending_requests or [""])[0])
        elif mode == "groundwork":
            p.meta["request"] = GROUNDWORK_REQUEST.format(
                intent=p.goal, progress=p.meta["progress"], boundaries=p.meta["boundaries"],
                open="; ".join(b.question for b in p.blockers)[:300] or "(없음)")

    run_list = [p for p in projects if p.meta["mode"] in ("progress", "groundwork")]
    quiet = [p for p in projects if p.meta["mode"] == "quiet"]
    active = [p for p in projects if p.meta["mode"] == "active"]
    pr = sum(1 for p in run_list if p.meta["mode"] == "progress")
    print(f"하루 라운드 — 진전 {pr} · 밑작업 {len(run_list)-pr} · "
          f"조용 {len(quiet)} · 작업중(비켜줌) {len(active)}")
    for p in run_list:
        print(f"  {'▶진전' if p.meta['mode']=='progress' else '↳밑작업'} [{p.id}] {p.goal[:44]}")
    for p in active:
        print(f"  🟢작업중 [{p.id}] — 당신이 작업 중이라 비켜줌(손 떼면 재개)")
    for p in quiet:
        print(f"  ·조용 [{p.id}] 결정 대기 {len(p.blockers)}건 — 만지면 재개")

    if run_list:
        pf = Portfolio(projects=run_list, scheduler_factory=_factory,
                       notifier=None, digest_interval=len(run_list), max_ticks=len(run_list))
        asyncio.run(pf.run())
        for p in run_list:
            ho = _load_handoff(p.handoff_path)
            if ho is None:
                continue
            if p.blockers:  # 막힌 시점 스탬프 + 밑작업 여부 표시(다음 라운드 판정)
                ho.blocked_mtime = p.meta["mtime"]
                ho.groundwork_mtime = p.meta["mtime"] if p.meta["mode"] == "groundwork" else 0.0
                try:
                    ho.save(p.handoff_path)
                except OSError:
                    pass
    usd, calls = telemetry.snapshot()

    digest = build_digest(projects, now_tick=0)
    _build_notifier(args.stamp).send("[SOPHIA 다이제스트]", digest)
    print("\n" + digest)
    print(f"\n💰 이 라운드: ${usd:.3f} ({calls} claude 호출) · 파일 {DIGEST_DIR}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
