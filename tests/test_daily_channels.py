"""하루 실사용 부품 검증 — 레지스트리·파일/멀티 notifier·SOPHIA 자기세션 제외."""
import json

from sophia.adapters.notifier.fake import FakeNotifier
from sophia.adapters.notifier.file_notifier import FileNotifier
from sophia.adapters.notifier.multi import MultiNotifier
from sophia.adapters.registry import Registry, Tracked
from sophia.adapters.sessions import is_sophia_session, scan_sessions


# ---------- tracked 레지스트리 (수동 등록) ----------

def test_registry_track_untrack_roundtrip(tmp_path):
    p = tmp_path / "tracked.json"
    r = Registry()
    assert r.track("/A", note="내 프로젝트") is True
    assert r.track("/A", note="갱신") is False        # 중복 → note 갱신, False
    assert r.items[0].note == "갱신"
    assert r.track("/B") is True
    r.save(p)

    r2 = Registry.load(p)
    assert r2.cwds() == ["/A", "/B"]
    assert r2.is_tracked("/A") and not r2.is_tracked("/C")
    assert r2.untrack("/A") is True and r2.untrack("/A") is False
    assert r2.cwds() == ["/B"]


def test_registry_load_missing_is_empty(tmp_path):
    assert Registry.load(tmp_path / "nope.json").items == []


def test_registry_load_corrupt_is_empty(tmp_path):
    p = tmp_path / "bad.json"
    p.write_text("{ broken", encoding="utf-8")
    assert Registry.load(p).items == []


# ---------- FileNotifier (폴백 채널) ----------

def test_file_notifier_appends_to_dir(tmp_path):
    n = FileNotifier(tmp_path, stamp="2026-06-01")
    assert n.send("제목1", "본문1") and n.send("제목2", "본문2")
    text = (tmp_path / "sophia-digest.md").read_text(encoding="utf-8")
    assert "제목1" in text and "본문1" in text and "제목2" in text
    assert "2026-06-01" in text                       # stamp 기록


def test_file_notifier_explicit_file(tmp_path):
    f = tmp_path / "out.md"
    FileNotifier(f).send("S", "B")
    assert f.read_text(encoding="utf-8").count("S") == 1


# ---------- MultiNotifier (메일 주채널 + 파일 폴백) ----------

def test_multi_fans_out_and_survives_one_failure():
    good = FakeNotifier()

    class Boom(FakeNotifier):
        def send(self, subject, body):
            raise RuntimeError("메일 죽음")

    multi = MultiNotifier(Boom(), good)
    assert multi.send("제목", "본문") is True          # 하나(파일) 성공 → True
    assert good.sent == [{"subject": "제목", "body": "본문"}]


def test_multi_all_fail_returns_false():
    class Boom(FakeNotifier):
        def send(self, subject, body):
            raise RuntimeError("x")
    assert MultiNotifier(Boom(), Boom()).send("s", "b") is False


# ---------- SOPHIA 자기세션 제외 (재임포트 오염 차단) ----------

def test_is_sophia_session_detects_own_prompts():
    assert is_sophia_session("다음 전제가 참이라고 가정하고 작업을 끝까지 수행하라...")
    assert is_sophia_session("아래는 한 요청을 전제로 실행한 결과다. 관리자로서...")
    assert is_sophia_session("아래는 한 프로젝트에서 사람이 마지막으로 남긴 지시다...")
    assert not is_sophia_session("vivi님 미팅록 들고와봐")


def test_scan_excludes_sophia_sessions(tmp_path):
    import os
    d = tmp_path / "-proj"
    d.mkdir()
    # 사람 세션
    (d / "human.jsonl").write_text(json.dumps(
        {"type": "user", "cwd": "/proj", "message": {"role": "user", "content": "진짜 내 지시"}},
        ensure_ascii=False), encoding="utf-8")
    # SOPHIA 가 남긴 세션
    (d / "sophia.jsonl").write_text(json.dumps(
        {"type": "user", "cwd": "/proj",
         "message": {"role": "user", "content": "다음 전제가 참이라고 가정하고 ..."}},
        ensure_ascii=False), encoding="utf-8")

    kept = scan_sessions(tmp_path)                    # 기본 exclude_sophia=True
    assert [s.first_user_text for s in kept] == ["진짜 내 지시"]
    both = scan_sessions(tmp_path, exclude_sophia=False)
    assert len(both) == 2


def test_scan_excludes_subagent_sessions(tmp_path):
    # 서브에이전트 세션(agent-*.jsonl / subagents/)은 사람 세션으로 안 잡혀야 한다.
    d = tmp_path / "-proj"
    (d / "subagents").mkdir(parents=True)
    (d / "human.jsonl").write_text(json.dumps(
        {"type": "user", "cwd": "/proj", "message": {"role": "user", "content": "진짜 지시"}},
        ensure_ascii=False), encoding="utf-8")
    (d / "agent-aa11.jsonl").write_text(json.dumps(   # 워커 서브에이전트(영어, 한국어마커 안 걸림)
        {"type": "user", "cwd": "/proj",
         "message": {"role": "user", "content": "Explore two directories ..."}},
        ensure_ascii=False), encoding="utf-8")
    (d / "subagents" / "sub.jsonl").write_text(json.dumps(
        {"type": "user", "cwd": "/proj", "message": {"role": "user", "content": "subagent work"}},
        ensure_ascii=False), encoding="utf-8")
    kept = scan_sessions(tmp_path)
    assert [s.first_user_text for s in kept] == ["진짜 지시"]   # 서브에이전트 둘 다 제외
