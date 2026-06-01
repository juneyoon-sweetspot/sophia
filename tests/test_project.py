"""막힌 프로젝트 skip 판정 — 사람이 건드리면(세상이 움직이면) 재실행."""
from sophia.core.portfolio.project import should_skip_blocked


def test_no_blockers_never_skips():
    assert should_skip_blocked(0, blocked_mtime=999, latest_session_mtime=1) is False


def test_blocked_and_untouched_skips():
    # 막혔고(blocker 2) 사람이 그 뒤로 세션 안 건드림(mtime 그대로) → skip
    assert should_skip_blocked(2, blocked_mtime=100.0, latest_session_mtime=100.0) is True
    assert should_skip_blocked(2, blocked_mtime=100.0, latest_session_mtime=80.0) is True


def test_world_moved_reruns():
    # 막혔어도 사람이 그 프로젝트를 다시 건드림(mtime↑) → 재실행
    assert should_skip_blocked(2, blocked_mtime=100.0, latest_session_mtime=150.0) is False
