"""페이싱 검증 — 미검토 백로그 → 자율 엔진 감속. 사람 요청은 안 늦춤."""
from sophia.adapters.fake_worker import FakeWorkerBackend
from sophia.adapters.thinker.fake import FakeThinker
from sophia.core.loop.scheduler import Scheduler
from sophia.core.manager.director import Director
from sophia.core.manager.pacing import (
    backlog_score,
    pace_for,
    quota_pressure,
    snapshot_counts,
)
from sophia.core.state.handoff import Handoff


# ---------- 순수: 백로그 점수 ----------

def test_backlog_zero_at_baseline():
    c = snapshot_counts(blockers=3, decisions=5)
    assert backlog_score(c, c) == 0.0            # 현재=베이스라인 → 0


def test_backlog_weights_gated_heavier():
    base = snapshot_counts()
    # 막힌 것 2개(가중 1.0) + 미비준 4개(가중 0.25)
    c = snapshot_counts(blockers=1, commit_gates=1, decisions=2, reports=2)
    assert backlog_score(c, base) == 2 * 1.0 + 4 * 0.25


def test_backlog_floors_at_zero():
    base = snapshot_counts(decisions=10)
    c = snapshot_counts(decisions=3)             # 베이스라인보다 적어도 음수 안 됨
    assert backlog_score(c, base) == 0.0


# ---------- 순수: 페이스 곡선 ----------

def test_pace_full_at_zero_backlog():
    p = pace_for(0, base_premise=3, base_anticipation=2, base_speculative=20)
    assert p.premise_count == 3 and p.anticipation_width == 2
    assert p.max_speculative == 20 and p.idle_multiplier == 1.0


def test_pace_throttles_as_backlog_grows():
    low = pace_for(2, base_premise=3, base_anticipation=2, base_speculative=20)
    high = pace_for(10, base_premise=3, base_anticipation=2, base_speculative=20)
    assert high.premise_count <= low.premise_count
    assert high.premise_count >= 1                       # 최소 1(완전 정지 아님)
    assert high.anticipation_width == 0                  # 예측은 멈춤
    assert high.max_speculative < low.max_speculative    # 투기 반감
    assert high.idle_multiplier > low.idle_multiplier    # 간격 늘어남


def test_pace_idle_multiplier_capped():
    assert pace_for(1000).idle_multiplier <= 32.0        # 폭주 방지 상한


# ---------- scheduler 배선 ----------

def _sched(pace):
    return Scheduler(
        backend=FakeWorkerBackend(), director=Director(goal="g"), thinker=FakeThinker(),
        goal="g", premise_count=3, anticipation_width=2, max_speculative=20, pace=pace,
    )


def test_scheduler_pace_off_is_full_gas():
    ho = Handoff(session_id="s", goal="g")
    ho.blockers = [{"q": i} for i in range(8)]           # 백로그 높아도
    p = _sched(pace=False)._pace(ho)
    assert p.premise_count == 3 and p.idle_multiplier == 1.0  # off 면 불변


def test_scheduler_pace_on_throttles_with_backlog():
    s = _sched(pace=True)
    ho = Handoff(session_id="s", goal="g")
    ho.blockers = [{"q": i} for i in range(8)]           # 베이스라인 0 → 백로그 8
    p = s._pace(ho)
    assert p.premise_count < 3 and p.idle_multiplier > 1.0


# ---------- quota 압력 ----------

def test_quota_pressure_zero_when_far_below_cap():
    assert quota_pressure(20, 80) == 0.0       # 80 의 70%(56) 미만 → 압력 0
    assert quota_pressure(None, 80) == 0.0     # 못 읽음 → 0
    assert quota_pressure(50, None) == 0.0     # cap 없음 → 0


def test_quota_pressure_rises_near_and_over_cap():
    near = quota_pressure(70, 80)              # cap 의 70~100% 구간
    at = quota_pressure(80, 80)                # cap 도달
    over = quota_pressure(95, 80)              # 초과
    assert 0 < near < at < over
    assert at >= 7.0                           # cap 에서 강한 throttle(≈8)


def test_scheduler_quota_throttles_even_with_zero_backlog():
    s = Scheduler(
        backend=FakeWorkerBackend(), director=Director(goal="g"), thinker=FakeThinker(),
        goal="g", premise_count=3, anticipation_width=2, max_speculative=20,
        pace=True, quota_cap_pct=80,
    )
    ho = Handoff(session_id="s", goal="g")     # 백로그 0
    s._week_pct = 80                            # 근데 quota 가 cap
    p = s._pace(ho)
    assert p.premise_count < 3 and p.idle_multiplier > 1.0   # quota 만으로도 throttle


def test_scheduler_usage_reader_caches_week_pct():
    calls = []
    s = Scheduler(
        backend=FakeWorkerBackend(), director=Director(goal="g"), thinker=FakeThinker(),
        goal="g", pace=True, usage_reader=lambda: (calls.append(1), 42)[1],
        usage_refresh_cycles=20,
    )
    s._refresh_usage(1)                         # 첫 사이클 → 읽음
    assert s._week_pct == 42 and len(calls) == 1
    s._refresh_usage(2)                         # 갱신 주기 아님 → 안 읽음
    assert len(calls) == 1


def test_reset_baseline_zeroes_backlog():
    s = _sched(pace=True)
    ho = Handoff(session_id="s", goal="g")
    ho.blockers = [{"q": i} for i in range(8)]
    s._reset_baseline(ho)                                # 사람 접촉 = 리셋
    assert backlog_score(s._counts(ho), ho.ack_baseline) == 0.0
    assert s._pace(ho).premise_count == 3                # 다시 풀가동
