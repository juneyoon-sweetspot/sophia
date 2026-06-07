import asyncio

from sophia.adapters.fake_worker import FakeWorkerBackend
from sophia.adapters.notifier.fake import FakeNotifier
from sophia.adapters.thinker.fake import FakeThinker
from sophia.core.loop.scheduler import Scheduler
from sophia.core.manager.director import Director
from sophia.core.portfolio.digest import build_digest
from sophia.core.portfolio.portfolio import Portfolio
from sophia.core.portfolio.project import Blocker, Project

from .conftest import noop_sleep, zero_clock


def _factory(tmp_path):
    """프로젝트를 한 스텝(max_cycles=1) 도는 Scheduler 를 만든다."""
    def make(proj: Project) -> Scheduler:
        thinker = FakeThinker(script=[
            {"premises": [{"id": "a", "statement": "A", "rationale": "r"}]}, "보고",
        ])
        return Scheduler(
            backend=FakeWorkerBackend(), director=Director(goal=proj.goal),
            thinker=thinker, goal=proj.goal,
            handoff_path=str(tmp_path / f"{proj.id}.json"),
            max_cycles=1, clock=zero_clock, sleep=noop_sleep,
            pending_requests=list(proj.pending_requests),
        )
    return make


# ---------- digest ----------

def test_digest_sorts_blockers_by_leverage():
    ps = [
        Project(id="a", goal="ga", blockers=[Blocker("a", "낮음", leverage=1)]),
        Project(id="b", goal="gb", blockers=[Blocker("b", "높음", leverage=5)]),
    ]
    d = build_digest(ps, now_tick=0)
    # leverage 높은 게 먼저(1번)
    assert d.index("높음") < d.index("낮음")


def test_digest_surfaces_stale_projects():
    ps = [Project(id="old", goal="잊힌프로젝트", last_progress_tick=0)]
    d = build_digest(ps, now_tick=20, stale_threshold=14)
    assert "정체된 프로젝트" in d and "잊힌프로젝트" in d


def test_digest_no_blockers_message():
    d = build_digest([Project(id="a", goal="g")], now_tick=0)
    assert "결정이 필요한 항목 없음" in d

def test_digest_shows_goal_and_cwd():
    p = Project(id="x", goal="목표설명", blockers=[Blocker("x", "결정질문", leverage=1)],
                meta={"cwd": "/home/user/myproject"})
    d = build_digest([p], now_tick=0)
    assert "목표설명" in d
    assert "myproject" in d


def test_digest_without_cwd_no_error():
    p = Project(id="x", goal="목표", blockers=[Blocker("x", "질문", leverage=1)])
    d = build_digest([p], now_tick=0)  # meta={}
    assert "질문" in d


# ---------- portfolio scheduling ----------

def test_pick_prefers_most_stale():
    pf = Portfolio(
        projects=[
            Project(id="fresh", goal="g", last_progress_tick=5),
            Project(id="stale", goal="g", last_progress_tick=0),
        ],
        scheduler_factory=lambda p: None,
    )
    pf._tick = 10
    assert pf.pick().id == "stale"      # 가장 오래 안 건드린 것


def test_pick_skips_done():
    pf = Portfolio(
        projects=[
            Project(id="done", goal="g", status="done", last_progress_tick=0),
            Project(id="active", goal="g", last_progress_tick=3),
        ],
        scheduler_factory=lambda p: None,
    )
    pf._tick = 10
    assert pf.pick().id == "active"


def test_advance_updates_project_state(tmp_path):
    proj = Project(id="p1", goal="목표", pending_requests=["요청"])
    pf = Portfolio(projects=[proj], scheduler_factory=_factory(tmp_path), max_ticks=1)
    asyncio.run(pf.run())
    assert proj.cycles_done == 1
    assert proj.last_progress_tick == 1
    assert proj.status == "done"          # 요청 소진 → done
    assert proj.pending_requests == []


def test_run_advances_all_until_done(tmp_path):
    projs = [Project(id=f"p{i}", goal=f"g{i}", pending_requests=["요청"]) for i in range(3)]
    pf = Portfolio(projects=projs, scheduler_factory=_factory(tmp_path), max_ticks=10)
    asyncio.run(pf.run())
    assert all(p.status == "done" for p in projs)
    assert all(p.cycles_done == 1 for p in projs)


# ---------- digest emission ----------

def test_digest_emitted_on_interval(tmp_path):
    notifier = FakeNotifier()
    projs = [Project(id=f"p{i}", goal="g", pending_requests=["요청"]) for i in range(5)]
    pf = Portfolio(
        projects=projs, scheduler_factory=_factory(tmp_path),
        notifier=notifier, digest_interval=2, max_ticks=10,
    )
    digests = asyncio.run(pf.run())
    # 5 프로젝트 각 1스텝 = 5틱. interval=2 → tick 2,4 에서 발행 + 끝에 1회 = 최소 3
    assert len(digests) >= 3
    assert len(notifier.sent) == len(digests)        # 전부 notifier 로 감
    assert all(m["subject"].startswith("[SOPHIA 다이제스트]") for m in notifier.sent)


def test_failing_project_does_not_kill_portfolio(tmp_path):
    def bad_factory(proj):
        class Boom(Scheduler):
            async def run(self, report=print):
                raise RuntimeError("프로젝트 폭발")
        return Boom(
            backend=FakeWorkerBackend(), director=Director(goal=proj.goal),
            thinker=FakeThinker(), goal=proj.goal,
            handoff_path=str(tmp_path / "x.json"), max_cycles=1,
            clock=zero_clock, sleep=noop_sleep,
        )

    # 하나는 터지고, 진행이 안 되면 staleness 가 계속 커져 무한 pick 됨 → max_ticks 로 차단
    proj = Project(id="boom", goal="g", pending_requests=["요청"])
    pf = Portfolio(projects=[proj], scheduler_factory=bad_factory, max_ticks=3)
    digests = asyncio.run(pf.run())       # 예외 안 터지고 정상 반환
    assert isinstance(digests, list)
    assert proj.cycles_done == 0          # 전진 못 함(실패)


def test_digest_marks_stale_blocker():
    """blocked_mtime이 25h 전이면 경과 마커가 붙는다."""
    old_ts = 1000.0   # 고정값 (now_ts=25h 뒤로 주입)
    now = old_ts + 25 * 3600
    p = Project(
        id="x", goal="테스트 프로젝트",
        blockers=[Blocker("x", "결정이 필요한 질문", leverage=3)],
        meta={"blocked_mtime": old_ts},
    )
    d = build_digest([p], now_tick=0, now_ts=now)
    assert "전 차단" in d
    assert "결정이 필요한 질문" in d   # 질문 자체는 출력 유지


def test_digest_no_stale_marker_when_no_blocked_mtime():
    """blocked_mtime=0이면 (데이터 없음) 마커 없음."""
    p = Project(id="x", goal="목표", blockers=[Blocker("x", "질문", leverage=1)])
    # blocked_mtime 없이, 아주 미래의 now_ts 주입해도 마커 없어야 함
    d = build_digest([p], now_tick=0, now_ts=9_999_999_999.0)
    assert "전 차단" not in d
    assert "질문" in d
