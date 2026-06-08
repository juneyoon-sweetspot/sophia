"""세션 피커 순수 로직 검증 (curses 없이)."""
from sophia.adapters.registry import Registry
from sophia.adapters.sessions import CwdGroup, SessionInfo
from sophia.ui.picker import (
    PickerState,
    build_state,
    reconcile,
    render_detail,
    render_rows,
)


def _group(cwd, first="첫 지시", total=10, title=""):
    si = SessionInfo(cwd=cwd, session_id="s", first_user_text=first,
                     last_user_text="끝", mtime=1.0, n_user_msgs=total, title=title)
    return CwdGroup(cwd=cwd, latest=si, representative=si, n_sessions=1, total_user_msgs=total)


def _state(*cwds):
    return build_state([_group(c) for c in cwds], Registry())


def test_build_state_marks_existing_tracked():
    reg = Registry()
    reg.track("/b")
    st = build_state([_group("/a"), _group("/b")], reg)
    assert [r.tracked for r in st.rows] == [False, True]


def test_move_clamps():
    st = _state("/a", "/b", "/c")
    st.move(-1)
    assert st.selected == 0
    st.move(5)
    assert st.selected == 2


def test_toggle_and_tracked_cwds():
    st = _state("/a", "/b", "/c")
    st.toggle()                 # /a
    st.move(2)
    st.toggle()                 # /c
    assert st.tracked_cwds() == ["/a", "/c"]
    assert st.n_tracked() == 2


def test_render_marks_selection_check_and_kind():
    st = _state("/proj/alpha", "/proj/beta")
    st.toggle()                 # alpha tracked
    st.rows[0].kind = "active"
    lines = render_rows(st, width=100)
    assert lines[0].startswith("▶ [✓] ●")    # 선택+체크+active
    assert lines[1].startswith("  [ ] ·")    # 미선택+미체크+미요약


def test_render_uses_summary_when_present():
    st = _state("/p")
    st.rows[0].purpose, st.rows[0].activity = "RAG 구축", "임베딩 선택"
    assert "RAG 구축 — 임베딩 선택" in render_rows(st)[0]


def test_label_prefers_claude_title_over_first_msg():
    # 요약 전엔 클로드 세션 제목(rename 이름)을 보여준다.
    st = build_state([_group("/p", first="이 레포 확인해봐", title="Review repository")],
                     Registry())
    assert st.rows[0].label == "Review repository"
    # 요약하면 요약이 이긴다.
    st.rows[0].purpose = "사내 RAG"
    assert st.rows[0].label == "사내 RAG"


def test_render_detail_shows_title_and_recent_before_summary():
    g = _group("/proj/x", first="첫 지시", title="Review repository")
    g.latest.user_trace = ["첫 지시", "두번째", "마지막 지시"]
    st = build_state([g], Registry())
    lines = render_detail(st, 80)
    blob = "\n".join(lines)
    assert "/proj/x" in blob                       # cwd
    assert "Review repository" in blob             # 제목
    assert "최근 지시:" in blob and "마지막 지시" in blob  # 최근 지시(LLM 없이)
    assert "e 를 누르면" in blob                     # 미요약 안내


def test_render_detail_shows_summary_when_present():
    st = build_state([_group("/p")], Registry())
    st.rows[0].purpose, st.rows[0].activity, st.rows[0].kind = "RAG 구축", "임베딩 비교", "active"
    blob = "\n".join(render_detail(st, 80))
    assert "목적: RAG 구축" in blob and "활동: 임베딩 비교" in blob
    assert "활성" in blob                            # kind 한글 표기


def test_reconcile_tracks_checked_and_untracks_unchecked():
    reg = Registry()
    reg.track("/old")           # 이전에 tracked 였는데
    st = build_state([_group("/old"), _group("/new")], reg)
    # /old 는 체크 해제, /new 는 체크
    st.rows[0].tracked = False
    st.rows[1].tracked = True
    reconcile(st, reg)
    assert reg.cwds() == ["/new"]   # old 빠지고 new 들어옴
