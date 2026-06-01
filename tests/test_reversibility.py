"""가역성 판단 검증 — '정확히 어디서부터 비가역인가'.

원칙: 가역 공간은 자유 탐색, 비가역 커밋만 게이트. 규칙으로 명백한 건 빠르게,
회색지대만 thinker. 같은 도구라도 맥락(격리)에 따라 가역성이 갈린다.
"""
import asyncio

from sophia.adapters.thinker.fake import FakeThinker
from sophia.core.manager.reversibility import classify_action, classify_commits


# ---------- 규칙 기반 분류 (도구 × 맥락) ----------

def test_read_tools_reversible():
    assert classify_action("Read") == "reversible"
    assert classify_action("Grep") == "reversible"
    assert classify_action("WebFetch") == "reversible"


def test_edit_depends_on_isolation():
    # 같은 Edit 이라도 격리 worktree 면 가역, 실제 트리면 비가역.
    assert classify_action("Edit", isolated=False) == "irreversible"
    assert classify_action("Edit", isolated=True) == "reversible"
    assert classify_action("Write", isolated=True) == "reversible"


def test_bash_by_command():
    assert classify_action("Bash", command="ls -la") == "reversible"
    assert classify_action("Bash", command="git status") == "reversible"
    assert classify_action("Bash", command="rm -rf build") == "irreversible"
    assert classify_action("Bash", command="git push origin main") == "irreversible"
    assert classify_action("Bash", command="curl -X POST https://api/x -d '{}'") == "irreversible"
    assert classify_action("Bash", command="some_unknown_tool --weird") == "ambiguous"


def test_mcp_by_verb():
    assert classify_action("mcp__slack__send_message") == "irreversible"
    assert classify_action("mcp__notion__create_page") == "irreversible"
    assert classify_action("mcp__sweetspot__get_waiting_stats") == "reversible"
    assert classify_action("mcp__db__query") == "reversible"
    assert classify_action("mcp__weird__frobnicate") == "ambiguous"


# ---------- classify_commits: 게이트 목록 ----------

def test_commits_rules_only_no_thinker_needed():
    th = FakeThinker(script=[])  # 회색지대 없으면 thinker 안 부름
    actions = [
        {"tool": "Read", "target": "a.py"},
        {"tool": "Edit", "target": "prod.yaml"},          # 실제 트리 → 비가역
        {"tool": "Bash", "command": "git push"},           # 비가역
        {"tool": "mcp__gmail__send", "target": "메일"},     # 비가역
    ]
    gates = asyncio.run(classify_commits(actions, th, isolated=False))
    labels = [g["action"] for g in gates]
    assert any("Edit" in x for x in labels)
    assert any("git push" in x for x in labels)
    assert any("send" in x for x in labels)
    assert not any("Read" in x for x in labels)            # 읽기는 게이트 아님
    assert len(th.calls) == 0                              # 회색지대 0 → thinker 미호출


def test_commits_isolated_edits_not_gated():
    th = FakeThinker(script=[])
    actions = [{"tool": "Edit", "target": "x.py"}, {"tool": "Write", "target": "y.py"}]
    gates = asyncio.run(classify_commits(actions, th, isolated=True))
    assert gates == []                                     # 격리 → 전부 가역 → 게이트 0


def test_commits_ambiguous_goes_to_thinker():
    th = FakeThinker(script=[{"irreversible": [
        {"action": "Bash: make release", "why": "릴리스 산출이라 못 무름"},
    ]}])
    actions = [{"tool": "Bash", "command": "make release"}]  # 규칙 미매칭 → 회색지대
    gates = asyncio.run(classify_commits(actions, th, isolated=False))
    assert gates == [{"action": "Bash: make release", "why": "릴리스 산출이라 못 무름"}]
    assert len(th.calls) == 1


def test_commits_thinker_error_defaults_to_gate():
    class Boom(FakeThinker):
        async def think(self, *a, **k):
            raise RuntimeError("x")
    actions = [{"tool": "Bash", "command": "frobnicate --x"}]  # 회색지대
    gates = asyncio.run(classify_commits(actions, Boom(), isolated=False))
    # 안전쪽: 판정 실패한 회색지대는 게이트로(놓치는 것보다 한 번 묻는 게 낫다).
    assert len(gates) == 1 and "frobnicate" in gates[0]["action"]
