"""세션 임포터 검증 — 합성 ~/.claude/projects fixture (실제 디스크/claude 무관)."""
import json

from sophia.adapters.sessions import (
    group_by_cwd,
    import_projects,
    read_session,
    scan_sessions,
)


def _write_session(root, dirname, sid, cwd, user_texts, mtime=None):
    """user 메시지 시퀀스로 한 세션 jsonl 을 만든다. assistant 라인도 섞는다."""
    d = root / dirname
    d.mkdir(parents=True, exist_ok=True)
    f = d / f"{sid}.jsonl"
    lines = []
    for t in user_texts:
        lines.append({"type": "user", "cwd": cwd, "message": {"role": "user", "content": t}})
        lines.append({"type": "assistant", "message": {"role": "assistant", "content": "ok"}})
    f.write_text("\n".join(json.dumps(x, ensure_ascii=False) for x in lines), encoding="utf-8")
    if mtime is not None:
        import os
        os.utime(f, (mtime, mtime))
    return f


def test_read_session_extracts_and_skips_noise(tmp_path):
    f = _write_session(
        tmp_path, "-proj", "s1", "/home/me/proj",
        ["<command>/clear</command>", "/resume", "진짜 첫 지시", "그다음", "Caveat: ..."],
    )
    si = read_session(f)
    assert si.cwd == "/home/me/proj"
    assert si.first_user_text == "진짜 첫 지시"      # 슬래시/캡션 스킵
    assert si.last_user_text == "그다음"             # Caveat 도 스킵
    assert si.n_user_msgs == 2


def test_read_session_none_when_only_noise(tmp_path):
    f = _write_session(tmp_path, "-x", "s", "/c", ["/help", "<x>"])
    assert read_session(f) is None


def test_scan_sorts_recent_first(tmp_path):
    _write_session(tmp_path, "-a", "s1", "/a", ["오래된"], mtime=1000)
    _write_session(tmp_path, "-b", "s2", "/b", ["최신"], mtime=2000)
    out = scan_sessions(tmp_path)
    assert [s.cwd for s in out] == ["/b", "/a"]


def test_group_by_cwd_aggregates_usage(tmp_path):
    _write_session(tmp_path, "-p", "s1", "/p", ["a", "b"], mtime=1000)
    _write_session(tmp_path, "-p", "s2", "/p", ["c", "d", "e"], mtime=2000)  # 최신
    groups = group_by_cwd(tmp_path)
    assert len(groups) == 1
    g = groups[0]
    assert g.n_sessions == 2
    assert g.total_user_msgs == 5
    assert g.latest.session_id == "s2"          # 최신이 대표
    assert g.latest.first_user_text == "c"      # goal 은 최신 세션의 첫 지시


def test_import_rank_usage_vs_recency(tmp_path):
    # busy: 사용량 많지만 오래됨 / fresh: 사용량 적지만 최신
    _write_session(tmp_path, "-busy", "s", "/busy", ["1", "2", "3", "4"], mtime=1000)
    _write_session(tmp_path, "-fresh", "s", "/fresh", ["1", "2"], mtime=5000)
    by_usage = import_projects(tmp_path, rank="usage")
    by_recency = import_projects(tmp_path, rank="recency")
    assert by_usage[0].meta["cwd"] == "/busy"
    assert by_recency[0].meta["cwd"] == "/fresh"


def test_import_top_and_min_msgs(tmp_path):
    _write_session(tmp_path, "-big", "s", "/big", ["1", "2", "3"], mtime=3000)
    _write_session(tmp_path, "-mid", "s", "/mid", ["1", "2"], mtime=2000)
    _write_session(tmp_path, "-tiny", "s", "/tiny", ["1"], mtime=1000)  # min_user_msgs=2 로 제외
    ps = import_projects(tmp_path, rank="usage", top=2, min_user_msgs=2)
    assert [p.meta["cwd"] for p in ps] == ["/big", "/mid"]


def test_import_only_cwds_and_handoff_path(tmp_path):
    _write_session(tmp_path, "-a", "s", "/a", ["ga", "x"])
    _write_session(tmp_path, "-b", "s", "/b", ["gb", "y"])
    hd = tmp_path / "ho"
    ps = import_projects(tmp_path, only_cwds={"/b"}, handoff_dir=hd, min_user_msgs=1)
    assert len(ps) == 1
    p = ps[0]
    assert p.meta["cwd"] == "/b"
    assert p.goal == "gb"                       # 첫 지시
    assert p.pending_requests == ["y"]          # 마지막 지시 = 이어갈 지점
    assert p.handoff_path == str(hd / "b.json")
    assert hd.exists()                          # handoff_dir 가 생성됨(조용한 저장실패 방지)
