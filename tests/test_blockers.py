"""블로커 추출 + 라이브 다이제스트 구멍 메우기 검증 (fake, 결정론적·부작용 0).

라이브 주행에서 드러난 버그: 워커가 ok=True 로 성공해도 보고에 '결정 요청'을 남기는데
discarded 로도 안 잡히고 project.blockers 도 안 채워져 다이제스트 '결정' 칸이 영원히 빔.
여기선 그 경로를 fake 로 재현해 수정이 메우는지 본다(실제 claude 재호출 없이).
"""
import asyncio

from sophia.adapters.fake_worker import FakeWorkerBackend
from sophia.adapters.notifier.fake import FakeNotifier
from sophia.adapters.thinker.fake import FakeThinker
from sophia.core.loop.scheduler import Scheduler
from sophia.core.manager.blockers import derive_blockers
from sophia.core.manager.director import Director
from sophia.core.manager.premise import Premise, PremiseOutcome
from sophia.core.portfolio.portfolio import Portfolio
from sophia.core.portfolio.project import Project
from sophia.ports.worker import WorkResult

from .conftest import noop_sleep, zero_clock


def _outcome(pid="A", ok=True, summary="이게 맞는지 확인 필요"):
    return PremiseOutcome(
        premise=Premise(id=pid, statement="접근A"),
        result=WorkResult(summary=summary, ok=ok),
    )


# ---------- derive_blockers (매니저 스텝) ----------

def test_derive_blockers_parses_and_clamps():
    th = FakeThinker(script=[{"blockers": [
        {"question": "구글이냐 카카오냐?", "leverage": 9, "context": "OAuth"},
        {"question": "", "leverage": 2},          # 빈 질문 → 버림
        {"question": "테마 승인?", "leverage": 0},   # leverage 클램프 → 1
    ]}])
    bs = asyncio.run(derive_blockers("로그인 개편", [_outcome()], th))
    assert [b["question"] for b in bs] == ["구글이냐 카카오냐?", "테마 승인?"]
    assert bs[0]["leverage"] == 5      # 9 → 5 클램프
    assert bs[1]["leverage"] == 1      # 0 → 1 클램프


def test_derive_blockers_empty_when_no_decision():
    th = FakeThinker(script=[{"blockers": []}])
    assert asyncio.run(derive_blockers("뭔가", [_outcome()], th)) == []


def test_derive_blockers_thinker_error_safe():
    class Boom(FakeThinker):
        async def think(self, *a, **k):
            raise RuntimeError("thinker 폭발")
    assert asyncio.run(derive_blockers("뭔가", [_outcome()], Boom())) == []


def test_derive_blockers_uses_raw_summary_not_compressed_report():
    """질문은 raw outcome summary 에서 와야 한다(압축 보고가 아니라)."""
    th = FakeThinker(script=[{"blockers": [{"question": "q", "leverage": 1}]}])
    asyncio.run(derive_blockers("req", [_outcome(summary="원본 요약-XYZ")], th))
    assert "원본 요약-XYZ" in th.calls[0]["prompt"]


# ---------- scheduler 배선 ----------

def _sched(thinker, **kw):
    return Scheduler(
        backend=FakeWorkerBackend(), director=Director(goal="g"), thinker=thinker,
        goal="g", handoff_path="/tmp/sophia_blockers_test.json", max_cycles=1,
        clock=zero_clock, sleep=noop_sleep, premise_count=1,
        pending_requests=["요청"], **kw,
    )


def test_scheduler_surface_blockers_writes_handoff():
    th = FakeThinker(script=[
        {"premises": [{"id": "A", "statement": "접근A", "rationale": "r"}]},  # derive_premises
        "보고",                                                                # to_premise_report
        {"blockers": [{"question": "방향 정해주세요", "leverage": 4}]},          # derive_blockers
    ])
    ho = asyncio.run(_sched(th, surface_blockers=True).run(report=lambda _m: None))
    assert [b["question"] for b in ho.blockers] == ["방향 정해주세요"]
    assert "방향 정해주세요" in ho.open_questions    # 줄곧 비어있던 필드도 채워짐


def test_scheduler_off_by_default_no_blockers():
    th = FakeThinker(script=[
        {"premises": [{"id": "A", "statement": "접근A", "rationale": "r"}]},
        "보고",
    ])
    th2 = th  # 같은 인스턴스 추적
    ho = asyncio.run(_sched(th2).run(report=lambda _m: None))  # surface_blockers=False
    assert ho.blockers == []
    # derive_blockers 가 호출되지 않았어야 한다(스크립트 2개만 소비).
    assert len(th2.script) == 0 and len(th2.calls) == 2


def test_blockers_survive_handoff_roundtrip(tmp_path):
    from sophia.core.state.handoff import Handoff
    p = str(tmp_path / "h.json")
    ho = Handoff(session_id="s", goal="g")
    ho.blockers = [{"question": "q", "leverage": 3, "context": "c"}]
    ho.save(p)
    assert Handoff.load(p).blockers == [{"question": "q", "leverage": 3, "context": "c"}]


# ---------- portfolio → 다이제스트 (구멍 메우기) ----------

def test_portfolio_surfaces_blockers_into_digest(tmp_path):
    """수정의 핵심: 라이브에서 빈 다이제스트 '결정' 칸이 이제 채워진다."""
    def factory(proj):
        th = FakeThinker(script=[
            {"premises": [{"id": "A", "statement": "접근A", "rationale": "r"}]},
            "한 스텝 진행",
            {"blockers": [{"question": "이 프로젝트 대상이 맞나요?", "leverage": 5}]},
        ])
        return Scheduler(
            backend=FakeWorkerBackend(), director=Director(goal=proj.goal), thinker=th,
            goal=proj.goal, handoff_path=str(tmp_path / f"{proj.id}.json"),
            max_cycles=1, clock=zero_clock, sleep=noop_sleep, premise_count=1,
            surface_blockers=True, pending_requests=list(proj.pending_requests),
        )

    notifier = FakeNotifier()
    proj = Project(id="ax", goal="목표", pending_requests=["요청"])
    pf = Portfolio(projects=[proj], scheduler_factory=factory,
                   notifier=notifier, digest_interval=1, max_ticks=1)
    digests = asyncio.run(pf.run())

    # project.blockers 가 채워졌고
    assert [b.question for b in proj.blockers] == ["이 프로젝트 대상이 맞나요?"]
    assert proj.blockers[0].leverage == 5
    # 다이제스트 '결정 필요' 칸에 실제로 떴다(라이브 버그가 메워짐).
    assert any("결정이 필요합니다" in d and "이 프로젝트 대상이 맞나요?" in d for d in digests)


def test_blocker_persists_across_ticks_until_digest(tmp_path):
    """멀티틱 누적: tick1 에 뜬 blocker 가 tick2(없음)에 지워지지 않고 살아남아야 한다.

    실제 포트폴리오는 digest_interval(기본 14) 동안 여러 틱을 돈다. blocker 를 매 advance
    마다 '교체'하면 tick1 결정이 디지스트 전에 증발한다 — 고치려던 버그가 멀티틱으로 이동.
    """
    def factory(proj):
        # 다음 요청이 r1 이면 blocker 를 올리고, r2 면 안 올린다.
        nxt = (proj.pending_requests or [""])[0]
        script = [
            {"premises": [{"id": "A", "statement": "접근A", "rationale": "r"}]},
            "진행",
        ]
        if nxt == "r1":
            script.append({"blockers": [{"question": "tick1 결정거리", "leverage": 5}]})
        else:
            script.append({"blockers": []})
        return Scheduler(
            backend=FakeWorkerBackend(), director=Director(goal=proj.goal),
            thinker=FakeThinker(script=script),
            goal=proj.goal, handoff_path=str(tmp_path / f"{proj.id}.json"),
            max_cycles=1, clock=zero_clock, sleep=noop_sleep, premise_count=1,
            surface_blockers=True, pending_requests=list(proj.pending_requests),
        )

    # r1, r2 두 요청 → 2틱에 걸쳐 처리(tick1 blocker, tick2 없음).
    proj = Project(id="ax", goal="목표", pending_requests=["r1", "r2"])
    pf = Portfolio(projects=[proj], scheduler_factory=factory,
                   digest_interval=2, max_ticks=2)
    digests = asyncio.run(pf.run())

    # tick1 의 결정거리가 끝까지 살아 다이제스트에 떠야 한다.
    assert [b.question for b in proj.blockers] == ["tick1 결정거리"]
    assert any("tick1 결정거리" in d for d in digests)
