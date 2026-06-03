"""막힌 프로젝트 행동 판정 — 진전/밑작업/조용."""
from sophia.core.portfolio.project import project_mode, should_skip_blocked


def test_no_blockers_never_skips():
    assert should_skip_blocked(0, blocked_mtime=999, latest_session_mtime=1) is False


def test_blocked_and_untouched_skips():
    # 막혔고(blocker 2) 사람이 그 뒤로 세션 안 건드림(mtime 그대로) → skip
    assert should_skip_blocked(2, blocked_mtime=100.0, latest_session_mtime=100.0) is True
    assert should_skip_blocked(2, blocked_mtime=100.0, latest_session_mtime=80.0) is True


def test_world_moved_reruns():
    # 막혔어도 사람이 그 프로젝트를 다시 건드림(mtime↑) → 재실행
    assert should_skip_blocked(2, blocked_mtime=100.0, latest_session_mtime=150.0) is False


# ---------- project_mode: 진전 / 밑작업 / 조용 ----------

def test_mode_progress_when_not_blocked():
    assert project_mode(0, 0, 0, 100) == "progress"


def test_mode_progress_when_touched():
    # 막혔어도 사람이 건드림(latest>blocked) → 진전(replace)
    assert project_mode(3, blocked_mtime=100, groundwork_mtime=100, latest_session_mtime=150) == "progress"


def test_mode_groundwork_first_time():
    # 막힘 + 미접촉 + 아직 밑작업 안 함(gw=0) → 한 번 밑작업
    assert project_mode(3, blocked_mtime=100, groundwork_mtime=0, latest_session_mtime=100) == "groundwork"


def test_mode_quiet_after_groundwork():
    # 막힘 + 미접촉 + 이미 밑작업함(gw==blocked) → 조용
    assert project_mode(3, blocked_mtime=100, groundwork_mtime=100, latest_session_mtime=100) == "quiet"


def test_mode_cycle_progress_resets_groundwork():
    # 사람이 건드린 뒤(새 block, gw 리셋되면) 다시 밑작업 한 번 가능
    # (daily 가 progress 후 gw=0 으로 스탬프 → 다음 막히면 groundwork)
    assert project_mode(2, blocked_mtime=200, groundwork_mtime=0, latest_session_mtime=200) == "groundwork"
