"""usage 파서 검증 — 실제 /usage 스크랩 샘플 기반(PTY 드라이버는 라이브 전용)."""
import json

from sophia.adapters.usage import detect_mode, parse_usage

# 실제 PTY 스크랩에서 나온 패널(공백 구조 그대로 닮게).
SAMPLE = """
Session
Total cost: $0.0000
Usage: 0 input, 0 output, 0 cache read, 0 cache write
Current session
██▌ 5% used
Resets 2am (Asia/Seoul)
Current week (all models)
███████ 14% used
Resets Jun 7 at 2pm (Asia/Seoul)
What's contributing to your limits usage?
82% of your usage came from sessions active for 8+ hours
"""


def test_parse_session_and_week():
    u = parse_usage(SAMPLE, mode="subscription")
    assert u.ok is True
    assert u.session_pct == 5
    assert u.week_pct == 14
    assert u.mode == "subscription"


def test_parse_handles_squished_text():
    # ANSI 제거 후 공백이 다 죽은 형태도 잡아야 한다.
    squished = "Currentsession██▌5%usedResets2amCurrentweek(allmodels)██12%usedResets"
    u = parse_usage(squished)
    assert u.session_pct == 5 and u.week_pct == 12


def test_parse_empty_returns_not_ok():
    u = parse_usage("아무 관련 없는 텍스트")
    assert u.ok is False and u.session_pct is None and u.week_pct is None


def _no_api_key():
    """ANTHROPIC_API_KEY 를 잠시 비우고 원복하는 컨텍스트."""
    import contextlib
    import os

    @contextlib.contextmanager
    def ctx():
        saved = os.environ.pop("ANTHROPIC_API_KEY", None)
        try:
            yield
        finally:
            if saved is not None:
                os.environ["ANTHROPIC_API_KEY"] = saved
    return ctx()


def test_detect_mode_api_key():
    import os
    saved = os.environ.get("ANTHROPIC_API_KEY")
    os.environ["ANTHROPIC_API_KEY"] = "sk-xxx"
    try:
        assert detect_mode() == "api"
    finally:
        if saved is None:
            os.environ.pop("ANTHROPIC_API_KEY", None)
        else:
            os.environ["ANTHROPIC_API_KEY"] = saved


def test_detect_mode_subscription(tmp_path):
    (tmp_path / ".claude.json").write_text(
        json.dumps({"oauthAccount": {"emailAddress": "x@y.z"}}), encoding="utf-8")
    with _no_api_key():
        assert detect_mode(home=tmp_path) == "subscription"


def test_detect_mode_unknown(tmp_path):
    with _no_api_key():
        assert detect_mode(home=tmp_path) == "unknown"
