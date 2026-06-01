"""아주 얇은 비용 텔레메트리 — claude 호출의 total_cost_usd 를 프로세스 단위로 합산.

claude -p 응답 봉투(stream-json result / json envelope)에 total_cost_usd 가 온다. 이걸
어댑터가 add() 로 흘려 모으면, 러너가 끝에 한 라운드 실비용을 찍을 수 있다. 비용을
추측 아니라 측정하기 위함(전역 누적이지만 텔레메트리 용도로 단순함이 우선).
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass
class _Cost:
    usd: float = 0.0
    calls: int = 0


COST = _Cost()


def add(usd) -> None:
    if isinstance(usd, (int, float)) and usd > 0:
        COST.usd += float(usd)
        COST.calls += 1


def reset() -> None:
    COST.usd = 0.0
    COST.calls = 0


def snapshot() -> tuple[float, int]:
    return COST.usd, COST.calls
