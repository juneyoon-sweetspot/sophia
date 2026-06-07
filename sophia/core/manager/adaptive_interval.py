"""적응형 간격 계산 — 남은 예산 ÷ 남은 야간 시간 = 다음 라운드까지 대기 초.

고정 3h 간격 대신, 남은 일일 예산(pp)을 야간 종료(기본 09:00)까지 고르게 펴 바른다.
예산이 많고 밤이 짧으면 자주(min_s 하한), 예산이 적고 밤이 길면 드물게(max_s 상한).

전부 순수 함수 + `_now` 주입 → 시스템 시계 없이 테스트 가능.
"""
from __future__ import annotations

import time as _time
from datetime import datetime


def night_end_ts(night_end_h: int = 9, _now=None) -> float:
    """다음 night_end_h:00:00 로컬 epoch. 이미 지났으면 내일 같은 시각(+86400)."""
    now = _time.time() if _now is None else _now
    dt = datetime.fromtimestamp(now)
    end = dt.replace(hour=night_end_h, minute=0, second=0, microsecond=0)
    end_ts = end.timestamp()
    if end_ts <= now:
        end_ts += 86400.0
    return end_ts


def _clamp(v: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, v))


def next_interval_s(
    remaining_pp: float,
    pp_per_round: float = 4.0,
    night_end_h: int = 9,
    min_s: int = 1800,
    max_s: int = 7200,
    _now=None,
) -> int:
    """남은 예산을 야간 종료까지 고루 펴서 다음 간격(초)을 정한다.

    remaining_pp <= 0 → max_s(예산 소진, 최대한 쉼).
    야간 종료가 지났으면 → max_s(내일 밤까지 느긋이).
    그 외엔 (남은 초 / 남은 라운드 수)를 [min_s, max_s]로 클램프.
    """
    if remaining_pp <= 0:
        return max_s
    now = _time.time() if _now is None else _now
    secs_to_end = night_end_ts(night_end_h, _now=now) - now
    if secs_to_end <= 0:
        return max_s
    rounds = remaining_pp / max(1e-9, pp_per_round)
    interval = secs_to_end / max(1.0, rounds)
    return int(_clamp(interval, min_s, max_s))


def update_pp_estimate(prev: float, actual: float, alpha: float = 0.3) -> float:
    """pp_per_round EMA 갱신 — 실측(actual)을 alpha 비중으로 반영.

    actual 이 비정상(<=0)이면 갱신 없이 prev 유지(노이즈 방어).
    """
    if actual is None or actual <= 0:
        return prev
    return (1.0 - alpha) * prev + alpha * actual
