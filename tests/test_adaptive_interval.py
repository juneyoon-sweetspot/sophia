"""적응형 간격 순수 함수 검증 — 전부 _now 주입, 외부 I/O 없음."""
from datetime import datetime

from sophia.core.manager.adaptive_interval import next_interval_s, night_end_ts


def _at(hour: int, minute: int = 0) -> float:
    """로컬 기준 2026-06-07 hour:minute 의 epoch."""
    return datetime(2026, 6, 7, hour, minute, 0).timestamp()


def test_zero_remaining_returns_max_s():
    assert next_interval_s(0.0, max_s=7200, _now=_at(2)) == 7200


def test_negative_remaining_returns_max_s():
    assert next_interval_s(-5.0, max_s=7200, _now=_at(2)) == 7200


def test_night_end_ts_always_in_future():
    for h in (0, 6, 8, 9, 12, 18, 23):
        now = _at(h)
        assert night_end_ts(9, _now=now) > now


def test_night_end_ts_within_24h():
    for h in (0, 6, 9, 10, 18, 23):
        now = _at(h)
        delta = night_end_ts(9, _now=now) - now
        assert 0 < delta <= 86400


def test_interval_clamped_to_min_s():
    # 07:00 → 09:00 까지 7200s. 예산 1000pp / 4pp = 250 라운드 → 매우 짧음 → min_s.
    out = next_interval_s(1000.0, pp_per_round=4.0, min_s=1800, max_s=7200, _now=_at(7))
    assert out == 1800


def test_interval_clamped_to_max_s():
    # 09:30 → 다음날 09:00(~23.5h). 4pp / 4pp = 1 라운드 → 간격 거대 → max_s 로 클램프.
    out = next_interval_s(4.0, pp_per_round=4.0, min_s=1800, max_s=7200, _now=_at(9, 30))
    assert out == 7200


def test_even_distribution():
    # 07:00→09:00 = 7200s, 8pp / 4pp_per_round = 2 라운드 → 7200/2 = 3600s.
    out = next_interval_s(8.0, pp_per_round=4.0, min_s=1800, max_s=7200, _now=_at(7))
    assert out == 3600


def test_past_night_end_returns_max_s():
    # 09:00 막 지남 → 오늘 밤 창 없음 → 다음 09:00 까지 멀어 max_s 로 대기.
    out = next_interval_s(4.0, pp_per_round=4.0, min_s=1800, max_s=7200, _now=_at(9, 1))
    assert out == 7200