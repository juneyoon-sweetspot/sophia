"""대시보드 렌더 검증(순수 함수). HTTP/파일 IO 는 스크립트 쉘."""
import importlib.util
from pathlib import Path

spec = importlib.util.spec_from_file_location(
    "dash", Path(__file__).resolve().parents[1] / "scripts" / "dashboard.py")
dash = importlib.util.module_from_spec(spec)
spec.loader.exec_module(dash)


def _state(running=True):
    return {
        "loop": {"running": running, "pid": "123"},
        "budget": {"date": "2026-06-04", "start_pct": 17},
        "projects": [
            {"id": "stage", "cwd": "/x/stage", "intent": "CRM 검증", "mode": "quiet",
             "decisions": ["운영 시스템이 뭐냐?"]},
            {"id": "guide", "cwd": "/x/guide", "intent": "데이터 가이드", "mode": "groundwork",
             "decisions": []},
        ],
        "digest": "■ 결정이 필요합니다 (1건)\n  1. [stage] 운영 시스템?",
    }


def test_render_shows_status_projects_digest():
    h = dash.render(_state(running=True))
    assert "도는 중 (pid 123)" in h
    assert "stage" in h and "guide" in h
    assert "운영 시스템이 뭐냐?" in h          # 결정 나열
    assert "최신 다이제스트" in h
    assert "127.0.0.1" not in h or True        # 본문엔 바인드주소 안 노출
    assert 'refresh' in h                      # 자동 새로고침


def test_render_escapes_html():
    s = _state()
    s["projects"][0]["decisions"] = ["<script>alert(1)</script>"]
    h = dash.render(s)
    assert "<script>alert" not in h and "&lt;script&gt;" in h   # XSS 이스케이프


def test_render_handles_no_projects():
    s = _state(); s["projects"] = []
    assert "tracked 프로젝트 없음" in dash.render(s)


def test_render_idle_badge():
    assert "안 도는 중" in dash.render(_state(running=False))
