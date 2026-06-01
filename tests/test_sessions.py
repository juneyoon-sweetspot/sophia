"""세션 임포터 검증 — 합성 ~/.claude/projects fixture (실제 디스크/claude 무관)."""
import asyncio
import json

from sophia.adapters.sessions import (
    group_by_cwd,
    import_described,
    import_projects,
    read_session,
    scan_sessions,
    summarize_session,
)
from sophia.adapters.thinker.fake import FakeThinker


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


# ---------- 고도화 임포트(세션 요약) ----------

def test_read_session_collects_user_trace(tmp_path):
    f = _write_session(tmp_path, "-p", "s", "/p", ["첫째", "둘째", "셋째"])
    si = read_session(f)
    assert si.user_trace == ["첫째", "둘째", "셋째"]
    assert si.path.endswith("s.jsonl")


def test_read_session_picks_up_ai_title(tmp_path):
    d = tmp_path / "-p"
    d.mkdir()
    f = d / "s.jsonl"
    lines = [
        {"type": "user", "cwd": "/p", "message": {"role": "user", "content": "리포 리뷰해"}},
        {"type": "ai-title", "sessionId": "s", "aiTitle": "Review repository"},
        {"type": "assistant", "message": {"role": "assistant", "content": "ok"}},
    ]
    f.write_text("\n".join(json.dumps(x, ensure_ascii=False) for x in lines), encoding="utf-8")
    si = read_session(f)
    assert si.title == "Review repository"        # 클로드 세션 제목 수집
    assert si.first_user_text == "리포 리뷰해"      # 제목 라인은 user 텍스트에 안 섞임
    assert si.n_user_msgs == 1


def test_summarize_session_parses(tmp_path):
    f = _write_session(tmp_path, "-p", "s", "/p", ["RAG 만들래", "임베딩 뭐 쓰지"])
    si = read_session(f)
    th = FakeThinker(script=[{"purpose": "사내 RAG 구축", "activity": "임베딩 선택 중",
                              "kind": "active"}])
    s = asyncio.run(summarize_session(si, th))
    assert s == {"purpose": "사내 RAG 구축", "activity": "임베딩 선택 중", "kind": "active"}


def test_summarize_session_thinker_error_falls_back(tmp_path):
    f = _write_session(tmp_path, "-p", "s", "/p", ["뭔가 첫 지시", "그담"])
    si = read_session(f)

    class Boom(FakeThinker):
        async def think(self, *a, **k):
            raise RuntimeError("boom")
    s = asyncio.run(summarize_session(si, Boom()))
    assert s["kind"] == "unknown" and s["purpose"].startswith("뭔가 첫 지시")


def test_import_described_sets_goal_and_drops_one_off(tmp_path):
    _write_session(tmp_path, "-act", "s", "/act", ["진행 프로젝트", "계속"], mtime=2000)
    _write_session(tmp_path, "-oneoff", "s", "/oneoff", ["이 레포 확인해봐"], mtime=1000)
    # FakeThinker script 는 호출 순서대로 — 정렬(recency)상 /act 먼저, /oneoff 다음.
    th = FakeThinker(script=[
        {"purpose": "활성 작업", "activity": "구현 중", "kind": "active"},
        {"purpose": "한 번 봄", "activity": "리뷰", "kind": "one_off"},
    ])
    ps = asyncio.run(import_described(
        th, tmp_path, rank="recency", min_user_msgs=1, drop_one_off=True,
        handoff_dir=tmp_path / "ho"))
    assert [p.meta["cwd"] for p in ps] == ["/act"]      # one_off 제외됨
    assert ps[0].goal == "활성 작업 — 구현 중"             # goal = 목적 — 활동
    assert ps[0].meta["kind"] == "active"
