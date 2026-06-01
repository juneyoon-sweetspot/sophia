"""2단계 커밋 게이트 검증 — 가역은 자유, 비가역만 멈춰 승인, 승인 밖 행동은 차단."""
import asyncio

from sophia.adapters.thinker.fake import FakeThinker
from sophia.core.manager.gate import (
    actions_from_result,
    execute_approved,
    extract_irreversible,
    plan_and_gate,
)
from sophia.ports.worker import Capabilities, WorkerBackend, WorkResult, WorkSpec


class ScriptedBackend(WorkerBackend):
    """run() 호출마다 큐에서 WorkResult 를 꺼내 돌려준다(phase1/phase3 구분용)."""
    def __init__(self, results):
        self.results = list(results)
        self.calls = []

    def capabilities(self):
        return Capabilities()

    async def run(self, spec):
        self.calls.append(spec)
        return self.results.pop(0)


def _spec(isolation=False):
    return WorkSpec(instruction="x", isolation=isolation)


# ---------- phase1: plan → gate 산출 ----------

def test_plan_clear_when_no_irreversible():
    backend = ScriptedBackend([WorkResult(summary="파일 몇 개 읽고 분석만 함")])
    th = FakeThinker(script=[{"irreversible": []}])
    out = asyncio.run(plan_and_gate(backend, _spec(), th))
    assert out.status == "clear" and out.gates == []


def test_plan_held_when_irreversible_present():
    backend = ScriptedBackend([WorkResult(summary="메일 발송 + prod.yaml 덮어쓰기 예정")])
    th = FakeThinker(script=[{"irreversible": [
        {"action": "메일 발송", "why": "외부로 나가 못 무름"},
        {"action": "prod.yaml 덮어쓰기", "why": "공유 설정 변경"},
    ]}])
    out = asyncio.run(plan_and_gate(backend, _spec(), th))
    assert out.status == "held"
    assert [g["action"] for g in out.gates] == ["메일 발송", "prod.yaml 덮어쓰기"]


def test_extract_failure_defaults_to_held():
    class Boom(FakeThinker):
        async def think(self, *a, **k):
            raise RuntimeError("x")
    gates = asyncio.run(extract_irreversible("어떤 계획", Boom(), isolated=False))
    assert len(gates) == 1 and "실패" in gates[0]["action"]   # 못 읽으면 자동커밋 금지


# ---------- phase3: 실행 + 사후 가드 ----------

def test_execute_clean_when_actions_approved():
    # 실제 한 일: prod.yaml Edit(비가역) — 근데 승인됨 → violation 없음.
    res = WorkResult(summary="했음", artifacts=[
        {"path": "prod.yaml", "status": "modified", "tool": "Edit"}])
    backend = ScriptedBackend([res])
    th = FakeThinker(script=[])  # Edit 은 규칙으로 비가역 판정(thinker 불필요)
    out = asyncio.run(execute_approved(backend, _spec(), ["Edit: prod.yaml"], th))
    assert out.ok is True and out.violations == []


def test_execute_blocks_unapproved_irreversible():
    # 핵심 보증: 승인은 a.txt 만 했는데 실행이 prod.yaml(비가역)을 건드림 → 차단.
    res = WorkResult(summary="했음", artifacts=[
        {"path": "a.txt", "status": "modified", "tool": "Edit"},
        {"path": "prod.yaml", "status": "modified", "tool": "Edit"}])
    backend = ScriptedBackend([res])
    th = FakeThinker(script=[])
    out = asyncio.run(execute_approved(backend, _spec(), ["Edit: a.txt"], th))
    assert out.ok is False
    assert any("prod.yaml" in v["action"] for v in out.violations)
    assert not any("a.txt" in v["action"] for v in out.violations)  # 승인된 건 위반 아님


def test_isolated_edits_never_violate():
    # 격리 worktree 면 Edit 도 가역 → 승인 안 해도 위반 아님(자유 작업).
    res = WorkResult(summary="했음", artifacts=[
        {"path": "anything.py", "status": "modified", "tool": "Edit"}])
    backend = ScriptedBackend([res])
    th = FakeThinker(script=[])
    out = asyncio.run(execute_approved(backend, _spec(isolation=True), [], th))
    assert out.ok is True and out.violations == []


def test_actions_from_result_reads_artifacts():
    res = WorkResult(summary="s", artifacts=[{"path": "x.py", "status": "created", "tool": "Write"}])
    assert actions_from_result(res) == [{"tool": "Write", "target": "x.py"}]
