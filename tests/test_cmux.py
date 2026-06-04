"""cmux 탭 이름 추출 — 사람 rename 우선, 자동(✳)/경로 폴백/제외."""
import json
from sophia.adapters.cmux import cwd_titles


def _store(tmp_path, tabs):
    p = tmp_path / "s.json"
    p.write_text(json.dumps({"windows": [{"tabManager": {"tabs": tabs}}]}, ensure_ascii=False),
                 encoding="utf-8")
    return p


def test_prefers_human_rename_over_auto(tmp_path):
    # 같은 cwd 에 자동(✳)과 사람 rename 둘 다 → 사람 것
    p = _store(tmp_path, [
        {"directory": "/a", "title": "✳ Review repository"},
        {"directory": "/a", "title": "내 로그인 작업"},
    ])
    assert cwd_titles(p)["/a"] == "내 로그인 작업"


def test_strips_glyph_when_only_auto(tmp_path):
    p = _store(tmp_path, [{"directory": "/b", "title": "✳ 데이터아키텍트"}])
    assert cwd_titles(p)["/b"] == "데이터아키텍트"


def test_drops_path_titles(tmp_path):
    # 제목이 그냥 경로/디렉토리명이면(rename 안 함) 버림
    p = _store(tmp_path, [{"directory": "/x/cloudbtl", "title": "~/x/cloudbtl"},
                          {"directory": "/y/foo", "title": "foo"}])
    assert cwd_titles(p) == {}


def test_missing_store_returns_empty(tmp_path):
    assert cwd_titles(tmp_path / "nope.json") == {}
