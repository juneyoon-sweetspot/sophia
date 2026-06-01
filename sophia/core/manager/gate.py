"""커밋 게이트 — 2단계 워커: 가역 공간은 자유, 비가역 커밋만 멈춰 승인받는다.

흐름(advisor 반영):
 phase1 plan: 안전한 plan 모드(read_only+strict-mcp)로 '계획'만 뽑는다. 부작용 0.
 extract:     계획 텍스트를 thinker 가 읽어 '되돌릴 수 없는 행동'만 게이트로 추출.
              (permission_denials 방식은 폐기 — 그건 시도=실행이라 게이트 전에 부작용 발생.)
 결정:        게이트 없음 → clear(실행해도 안전). 있음 → held(사람 승인 대기).
 phase3 exec: 승인된 행동에만 묶어 실행하고, *실제로 한 일을 재분류해* 승인 안 된
              비가역 행동이 끼었으면 violation 으로 차단한다(게이트가 허울이 안 되게).

이 모듈은 상태머신·바인딩·검증을 담는다. 6h 루프/daily 의 '라운드를 넘는 승인'(계획을
다이제스트로 올리고 다음 라운드에 실행)으로의 배선은 호출자 몫.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from ...ports.thinker import Thinker
from ...ports.worker import WorkerBackend, WorkResult, WorkSpec
from ...prompts import templates
from .reversibility import classify_commits


@dataclass
class GateOutcome:
    status: str                      # "clear" | "held"
    plan: str                        # phase1 계획 텍스트
    gates: list[dict] = field(default_factory=list)  # [{action, why}] 승인 필요한 비가역


@dataclass
class ExecOutcome:
    result: WorkResult
    violations: list[dict] = field(default_factory=list)  # 승인 안 된 비가역 행동
    ok: bool = True                  # violations 없으면 True


async def extract_irreversible(plan: str, thinker: Thinker, *, isolated: bool = False) -> list[dict]:
    """계획 텍스트 → 비가역 행동 [{action, why}]. 추출 실패 시 안전쪽(검토 게이트 1개)."""
    try:
        out = await thinker.think(
            templates.PLAN_GATE.format(
                env=("격리됨(버릴 수 있음)" if isolated else "실제 환경"), plan=plan
            ),
            system=templates.SYSTEM_MANAGER,
            schema=templates.REVERSIBILITY_SCHEMA,
        )
        items = out.get("irreversible", []) if isinstance(out, dict) else []
    except Exception:
        # 계획을 못 읽으면 비가역 유무를 모른다 → 자동 커밋 금지(검토 요청).
        return [{"action": "(계획 분석 실패)", "why": "계획을 판독 못 함 — 사람 검토 필요"}]
    gates = []
    for it in items:
        if isinstance(it, dict) and (it.get("action") or "").strip():
            gates.append({"action": it["action"].strip(), "why": (it.get("why") or "").strip()})
    return gates


async def plan_and_gate(backend: WorkerBackend, spec: WorkSpec, thinker: Thinker) -> GateOutcome:
    """Phase 1 — 안전한 plan 으로 계획을 뽑고 비가역 게이트를 산출.

    주의: backend 는 read_only(plan+strict-mcp) 여야 한다(호출자 보장). 그래야 계획만
    나오고 부작용이 없다.
    """
    plan_res = await backend.run(spec)
    plan = plan_res.summary or ""
    gates = await extract_irreversible(plan, thinker, isolated=spec.isolation)
    return GateOutcome(status="held" if gates else "clear", plan=plan, gates=gates)


def _norm(s: str) -> str:
    return " ".join((s or "").lower().split())


def actions_from_result(res: WorkResult) -> list[dict]:
    """실행 결과에서 '실제로 한 행동'을 뽑는다(검증용).

    현재 artifacts 는 Write/Edit 파일변경만 포착(adapters/artifacts.py 한계). Bash/MCP
    커밋까지 완전 포착은 후속(전체 tool_use 캡처). 그래서 검증은 파일변경 기준 부분적.
    """
    out = []
    for a in res.artifacts or []:
        out.append({"tool": a.get("tool", "Edit"), "target": a.get("path", "")})
    return out


async def execute_approved(
    backend: WorkerBackend, spec: WorkSpec, approved: list[str], thinker: Thinker
) -> ExecOutcome:
    """Phase 3 — 실행 후 '실제 한 일'을 재분류해 승인 안 된 비가역 행동을 차단.

    호출자는 spec 을 승인 집합으로 좁혀야 한다(allowedTools/지시문). 이 함수는 사후
    가드: 실제 한 행동 중 비가역인데 approved 에 없는 게 있으면 violation 으로 표시.
    """
    res = await backend.run(spec)
    did = actions_from_result(res)
    post_gates = await classify_commits(did, thinker, isolated=spec.isolation)
    approved_set = {_norm(a) for a in approved}
    violations = [g for g in post_gates if _norm(g["action"]) not in approved_set]
    return ExecOutcome(result=res, violations=violations, ok=not violations)
