"""의도 브리프 검증 — 초안 생성 + 레지스트리 라운드트립(신/구 호환)."""
import asyncio
import json

from sophia.adapters.registry import Registry, Tracked
from sophia.adapters.sessions import SessionInfo, draft_brief
from sophia.adapters.thinker.fake import FakeThinker


def _si():
    return SessionInfo(cwd="/p", session_id="s", first_user_text="RAG 만들래",
                       last_user_text="임베딩 골라", mtime=1.0, n_user_msgs=2,
                       user_trace=["RAG 만들래", "임베딩 골라"])


def test_draft_brief_parses():
    th = FakeThinker(script=[{"intent": "사내 RAG 구축",
                              "progress": "임베딩 선정+인덱싱 파이프라인 동작",
                              "boundaries": "프로덕션 배포는 하지 말 것"}])
    b = asyncio.run(draft_brief(_si(), th))
    assert b["intent"] == "사내 RAG 구축"
    assert "임베딩" in b["progress"]
    assert "배포" in b["boundaries"]


def test_draft_brief_falls_back_on_error():
    class Boom(FakeThinker):
        async def think(self, *a, **k):
            raise RuntimeError("x")
    b = asyncio.run(draft_brief(_si(), Boom()))
    assert b["intent"].startswith("RAG 만들래") and b["progress"] == ""


def test_registry_brief_roundtrip(tmp_path):
    p = tmp_path / "t.json"
    r = Registry()
    r.track("/a")
    r.items[0].intent = "목표 A"
    r.items[0].progress = "이러면 진전"
    r.items[0].boundaries = "이건 금지"
    r.save(p)
    r2 = Registry.load(p)
    assert r2.items[0].intent == "목표 A"
    assert r2.items[0].progress == "이러면 진전"
    assert r2.items[0].has_brief()


def test_registry_loads_old_file_without_brief_fields(tmp_path):
    # 구버전 tracked.json(브리프 필드 없음)도 로드돼야 한다(기본값).
    p = tmp_path / "old.json"
    p.write_text(json.dumps({"items": [{"cwd": "/x", "note": "메모"}]}), encoding="utf-8")
    r = Registry.load(p)
    assert r.items[0].cwd == "/x" and r.items[0].intent == "" and not r.items[0].has_brief()


def test_registry_load_ignores_unknown_keys(tmp_path):
    # 미래 키가 섞여도 죽지 않고 무시(레지스트리 안 날아감).
    p = tmp_path / "future.json"
    p.write_text(json.dumps({"items": [{"cwd": "/x", "future_field": 1}]}), encoding="utf-8")
    r = Registry.load(p)
    assert r.items and r.items[0].cwd == "/x"


def test_brief_md_roundtrip():
    # scripts/brief.py 의 마크다운 직렬화/파싱이 왕복하는지(로직만).
    import importlib.util
    from pathlib import Path
    spec = importlib.util.spec_from_file_location(
        "brief_script", Path(__file__).resolve().parents[1] / "scripts" / "brief.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)

    reg = Registry()
    reg.track("/proj/one")
    reg.items[0].intent = "원래 의도"
    md = mod._to_md(reg)
    # 사람이 intent 한 줄 고침
    md = md.replace("intent: 원래 의도", "intent: 고친 의도")
    mod._from_md(md, reg)
    assert reg.items[0].intent == "고친 의도"
