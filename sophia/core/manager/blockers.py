"""Blockers — 전제 결과에서 '본부장이 결정해야 할 것'만 매니저 레벨에서 추출.

왜 매니저 레벨인가(라이브에서 드러난 것):
 - 워커가 ok=True 로 성공해도, 보고 안에 "이게 맞는지 확인해 주세요" 같은 결정 요청을
   자연어로 남긴다. 성공/실패(decisions/discarded)만으론 이 신호가 안 잡힌다.
 - 그래서 worker 출력 스키마를 강제(취약)하는 대신, synthesize/anticipate 와 같은
   결을 따라 관리자(thinker)가 *결과 전체를 보고* 사람만 정할 수 있는 것만 골라낸다.
   사소한 건 관리자가 단정하고 올리지 않는다(SOPHIA 의 '게으름은 설계다').

반환은 [{question, leverage, context}] 리스트. 결정거리가 없으면 빈 리스트.
thinker 오류/이상 응답은 빈 리스트로 안전 폴백(6h 루프를 죽이지 않는다).
"""
from __future__ import annotations

from ...ports.thinker import Thinker
from ...prompts import templates
from .premise import PremiseOutcome


async def derive_blockers(
    request: str, outcomes: list[PremiseOutcome], thinker: Thinker
) -> list[dict]:
    """전제 결과 → 본부장 결정 필요 항목만. raw summary 를 근거로 준다(압축 전).

    5문장 보고가 아니라 outcomes 의 원본 summary 를 넘긴다 — 보고 압축에 질문이
    살아남는다는 보장이 없기 때문(라이브에서 이번엔 살아남았지만 운에 기대지 않는다).
    """
    block = "\n".join(
        f"- 전제[{o.premise.id}] {o.premise.statement} "
        f"({'완료' if o.result.ok else '실패'}): {o.result.summary}"
        for o in outcomes
    )
    try:
        out = await thinker.think(
            templates.BLOCKERS_DERIVE.format(request=request, results=block),
            system=templates.SYSTEM_MANAGER,
            schema=templates.BLOCKERS_SCHEMA,
        )
        raw = out.get("blockers", []) if isinstance(out, dict) else []
    except Exception:
        return []

    cleaned: list[dict] = []
    for b in raw:
        if not isinstance(b, dict):
            continue
        q = (b.get("question") or "").strip()
        if not q:
            continue
        try:
            lev = int(b.get("leverage", 1) or 1)
        except (TypeError, ValueError):
            lev = 1
        cleaned.append({
            "question": q,
            "leverage": max(1, min(5, lev)),  # 1~5 로 클램프
            "context": (b.get("context") or "").strip(),
        })
    return cleaned
