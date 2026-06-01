import asyncio

from sophia.adapters.claude_code.adapter import ClaudeCodeBackend
from sophia.ports.worker import WorkSpec


def test_missing_binary_returns_not_ok():
    backend = ClaudeCodeBackend(claude_bin="definitely_not_a_real_binary_xyz")
    res = asyncio.run(backend.run(WorkSpec(instruction="hi")))
    assert res.ok is False
    assert "찾을 수 없음" in res.summary


def test_parse_reads_result_event():
    backend = ClaudeCodeBackend()
    events = [
        {"type": "system", "subtype": "init"},
        {"type": "result", "result": "최종 답", "is_error": False},
    ]
    res = backend._parse(events, returncode=0)
    assert res.ok and res.summary == "최종 답"


def test_parse_flags_error_event():
    backend = ClaudeCodeBackend()
    res = backend._parse([{"type": "result", "result": "x", "is_error": True}], returncode=0)
    assert res.ok is False


def test_parse_extracts_artifacts_from_tool_use():
    backend = ClaudeCodeBackend()
    events = [
        {"type": "assistant", "message": {"content": [
            {"type": "text", "text": "만들었어요"},
            {"type": "tool_use", "name": "Write", "input": {"file_path": "/out/a.txt"}},
        ]}},
        {"type": "result", "result": "완료", "is_error": False},
    ]
    res = backend._parse(events, returncode=0)
    assert res.summary == "완료"
    assert res.artifacts == [{"path": "/out/a.txt", "status": "created", "tool": "Write"}]


def test_parse_falls_back_to_assistant_text():
    # result 이벤트가 없을 때 assistant 텍스트 블록으로 폴백
    backend = ClaudeCodeBackend()
    events = [
        {"type": "assistant", "message": {"content": [
            {"type": "text", "text": "부분 "},
            {"type": "text", "text": "응답"},
        ]}},
    ]
    res = backend._parse(events, returncode=0)
    assert res.summary == "부분 응답"


def test_parse_stream_skips_non_json_lines():
    backend = ClaudeCodeBackend()
    raw = b'{"type":"system"}\nnot-json-noise\n{"type":"result","result":"R"}\n'
    events = backend._parse_stream(raw)
    assert events == [{"type": "system"}, {"type": "result", "result": "R"}]


def test_default_timeout_is_not_six_hours():
    # 한 일꾼이 6h 전체 예산을 삼키지 못하도록 기본 타임아웃은 작아야 한다
    assert ClaudeCodeBackend().timeout_s <= 60 * 60


def test_read_only_fences_plan_and_strict_mcp():
    # read_only=True 면 plan 모드 + MCP 미로드 플래그가 argv 에 들어가야 한다
    argv = ClaudeCodeBackend(read_only=True)._build_argv(WorkSpec(instruction="hi"))
    assert "--permission-mode" in argv and argv[argv.index("--permission-mode") + 1] == "plan"
    assert "--strict-mcp-config" in argv


def test_default_is_not_read_only():
    # 기본은 펜스 없음(하위호환). 부작용 차단은 명시적 opt-in.
    argv = ClaudeCodeBackend()._build_argv(WorkSpec(instruction="hi"))
    assert "--permission-mode" not in argv and "--strict-mcp-config" not in argv


def test_parse_captures_cost_into_telemetry():
    from sophia.adapters import telemetry
    telemetry.reset()
    backend = ClaudeCodeBackend()
    backend._parse([{"type": "result", "result": "ok", "total_cost_usd": 0.42}], returncode=0)
    usd, calls = telemetry.snapshot()
    assert round(usd, 2) == 0.42 and calls == 1
    telemetry.reset()


def test_telemetry_add_ignores_nonpositive():
    from sophia.adapters import telemetry
    telemetry.reset()
    telemetry.add(None); telemetry.add(0); telemetry.add(-1); telemetry.add(0.1)
    usd, calls = telemetry.snapshot()
    assert round(usd, 2) == 0.10 and calls == 1
    telemetry.reset()
