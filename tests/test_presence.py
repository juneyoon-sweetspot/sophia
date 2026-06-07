"""사용자 부재 감지 검증 — 세션 mtime → 경과 초 → away 여부.

scan_sessions 를 가짜로 교체해 파일시스템 미접근. SOPHIA 제외 필터가 호출되는지도 확인.
"""
from sophia.core.manager import presence
from sophia.core.manager.presence import (
    AWAY_THRESHOLD_S,
    is_away,
    last_user_activity_s,
)


class _Sess:
    """presence 는 mtime 만 본다 — 최소 스텁."""

    def __init__(self, mtime: float):
        self.mtime = mtime


def _install(sessions, capture=None):
    def fake(root=None, *, exclude_sophia=True):
        if capture is not None:
            capture["exclude_sophia"] = exclude_sophia
            capture["root"] = root
        return list(sessions)

    presence.scan_sessions = fake


def test_no_sessions_returns_inf():
    _install([])
    assert last_user_activity_s(_now=1000.0) == float("inf")


def test_single_session_mtime_correct():
    _install([_Sess(900.0)])
    assert last_user_activity_s(_now=1000.0) == 100.0


def test_picks_newest_of_multiple():
    _install([_Sess(500.0), _Sess(950.0), _Sess(700.0)])
    assert last_user_activity_s(_now=1000.0) == 50.0


def test_ignores_sophia_sessions():
    cap = {}
    _install([_Sess(900.0)], capture=cap)
    last_user_activity_s(_now=1000.0)
    assert cap["exclude_sophia"] is True


def test_is_away_true_when_exceeds():
    _install([_Sess(0.0)])  # 아주 오래된 세션
    assert is_away(threshold_s=3600, _now=10000.0) is True


def test_is_away_false_when_recent():
    _install([_Sess(9000.0)])  # 1000s 전 = threshold 미만
    assert is_away(threshold_s=3600, _now=10000.0) is False


def test_threshold_matches_active_window():
    # daily.py 의 ACTIVE_WINDOW_S(3600)와 동일해야 한다.
    assert AWAY_THRESHOLD_S == 3600


def test_is_away_false_when_no_sessions():
    # 세션 없음 → float('inf') > threshold → 보수적으로 자리 비움(True).
    _install([])
    assert is_away(threshold_s=3600, _now=10000.0) is True
