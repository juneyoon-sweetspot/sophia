"""Pacing — '사람이 따라올 수 있는 만큼만 앞서간다'.

SOPHIA 는 completion gate 가 없어 안 멈춘다. 그래서 사람 없는 동안 결정거리·미검증
산출을 무한정 쌓는 폭주를 막을 브레이크가 필요하다. 그 신호는 '시간'이 아니라
**미검토 백로그** — 마지막 사람 접촉 이후 SOPHIA 가 내놓은, 사람의 눈/결정을 기다리는
산출물의 가중합. 막힌 것(blocker·commit_gate)은 무겁게, 미비준 산출(decision·report·
speculative)은 가볍게. 백로그가 클수록 추가 산출의 한계가치는 낮고 위험(잘못된 전제 위
복리)은 크다 → 그때 자율 엔진을 늦춘다.

핵심 단서(반론 반영): 늦추는 건 *자율 탐색*(분기·예측·투기)뿐. 사람이 실제로 요청한
일은 절대 늦추지 않는다 — 안 그러면 시간 많을 때 가장 적게 하는 꼴.
"""
from __future__ import annotations

from dataclasses import dataclass

GATED_WEIGHT = 1.0      # blocker/commit_gate — 사람 없이는 진행 불가(무거움)
UNRATIFIED_WEIGHT = 0.25  # decision/report/speculative — 미비준(가벼움)


def snapshot_counts(blockers=0, commit_gates=0, decisions=0, reports=0, speculative=0) -> dict:
    return {
        "blockers": blockers, "commit_gates": commit_gates,
        "decisions": decisions, "reports": reports, "speculative": speculative,
    }


def backlog_score(counts: dict, baseline: dict | None = None) -> float:
    """현재 카운트 − 마지막 접촉 시점 베이스라인 = 그 사이 쌓인 미검토 백로그.

    baseline 이 없으면(첫 가동) 0 베이스라인. 음수는 0 으로(사람이 비운 경우).
    """
    base = baseline or {}

    def d(k: str) -> int:
        return max(0, int(counts.get(k, 0)) - int(base.get(k, 0)))

    gated = d("blockers") + d("commit_gates")
    unratified = d("decisions") + d("reports") + d("speculative")
    return GATED_WEIGHT * gated + UNRATIFIED_WEIGHT * unratified


@dataclass
class Pace:
    premise_count: int        # 자율 분기 폭(백로그↑ → ↓, 최소 1)
    anticipation_width: int   # 예측 선제작업 수(백로그↑ → 0)
    max_speculative: int      # 누적 투기 상한(백로그↑ → 반감)
    idle_multiplier: float    # 라운드 간격 배수(지수 backoff)


def pace_for(
    backlog: float,
    *,
    base_premise: int = 3,
    base_anticipation: int = 2,
    base_speculative: int = 20,
) -> Pace:
    """미검토 백로그 → 자율 엔진 페이스. 백로그 0 = 풀가동, 커질수록 잦아듦(지수).

    곡선: premise/anticipation 은 백로그 4 부근에서 최소(1/0)로, speculative 는 반감기 4,
    idle 간격은 백로그 3마다 2배(32배 상한). 점근적으로 거의 정지에 수렴하되 0 은 아님.
    """
    b = max(0.0, backlog)
    premise = max(1, round(base_premise - b / 2))
    anticipation = max(0, round(base_anticipation - b / 2))
    speculative = max(0, round(base_speculative * (0.5 ** (b / 4))))
    idle_multiplier = min(32.0, 2.0 ** (b / 3))
    return Pace(premise, anticipation, speculative, idle_multiplier)
