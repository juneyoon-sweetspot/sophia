"""적응형 라운드 간격 계산기 — run-loop.sh 가 매 라운드 후 호출.

stdout 에는 다음 라운드까지 대기할 정수 초 한 줄만 출력한다(run-loop 가 sleep 인자로 씀).
모든 진단/경고는 stderr 전용(run-loop 의 `2>/dev/null` 로 버려짐).

결정 트리:
  1. is_away()==False        → SOPHIA_INTERVAL_S       [낮 모드 — 기존 고정 간격 보존]
  2. pace-state.json 없음/손상 → SOPHIA_INTERVAL_S       [cold-start fallback]
     date != today           → SOPHIA_INTERVAL_S       [stale]
     timestamp + 3600 < now  → SOPHIA_INTERVAL_S       [watchdog kill 후 stale 방어]
  3. exhausted==True         → SOPHIA_DAY_INTERVAL_S   [예산 소진 — 길게 쉼]
  4. pp_per_round = EMA(last_round_pp, SOPHIA_PP_PER_ROUND)
  5. next_interval_s(remaining_pp, pp_per_round, ...)

main() 전체를 try/except 로 감싸 예외 시 sys.exit(1) → run-loop 가 fallback 으로 처리.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time as _time
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sophia.core.manager.adaptive_interval import next_interval_s, update_pp_estimate  # noqa: E402
from sophia.core.manager.presence import is_away  # noqa: E402

DEFAULT_PACE_STATE = Path.home() / ".sophia" / "pace-state.json"
STALE_AFTER_S = 3600   # pace-state 가 이 초보다 오래되면 신뢰 안 함(watchdog kill 방어)


def _env_int(name: str, default: int) -> int:
    try:
        return int(float(os.environ.get(name, default)))
    except (TypeError, ValueError):
        return default


def _env_float(name: str, default: float) -> float:
    try:
        return float(os.environ.get(name, default))
    except (TypeError, ValueError):
        return default


def _emit(value: int) -> int:
    print(int(value))
    return 0


def main(pace_state_path=None, away_root=None, _now=None) -> int:
    now = _time.time() if _now is None else _now
    fallback = _env_int("SOPHIA_INTERVAL_S", 10800)
    away_threshold = _env_float("SOPHIA_AWAY_THRESHOLD_S", 3600.0)
    day_interval = _env_int("SOPHIA_DAY_INTERVAL_S", 7200)
    night_end_h = _env_int("SOPHIA_NIGHT_END_H", 9)
    pp_per_round = _env_float("SOPHIA_PP_PER_ROUND", 4.0)

    # 1. 사용자가 활동 중이면 기존 고정 간격 그대로(SOPHIA 비켜줌).
    if not is_away(threshold_s=away_threshold, root=away_root, _now=now):
        print("interval: 사용자 활동 감지 → 고정 간격 유지", file=sys.stderr)
        return _emit(fallback)

    # 2. pace-state.json 읽기 — 없거나 손상이면 cold-start fallback.
    path = Path(pace_state_path) if pace_state_path is not None else DEFAULT_PACE_STATE
    try:
        state = json.loads(Path(path).read_text(encoding="utf-8"))
    except Exception:
        print("interval: pace-state 없음/손상 → fallback", file=sys.stderr)
        return _emit(fallback)

    if state.get("date") != date.today().isoformat():
        print("interval: pace-state 가 오늘 것이 아님(stale) → fallback", file=sys.stderr)
        return _emit(fallback)

    ts = state.get("timestamp")
    if not isinstance(ts, (int, float)) or ts + STALE_AFTER_S < now:
        print("interval: pace-state timestamp stale → fallback", file=sys.stderr)
        return _emit(fallback)

    # 3. 예산 소진 → 길게 쉼.
    if state.get("exhausted"):
        print("interval: 예산 소진 → day interval", file=sys.stderr)
        return _emit(day_interval)

    # 4. pp_per_round EMA 보정(실측 last_round_pp 있으면).
    last_round_pp = state.get("last_round_pp")
    pp_per_round = update_pp_estimate(pp_per_round, last_round_pp)

    # 5. 남은 예산을 야간 종료까지 고루 펴서 간격 계산.
    remaining = state.get("remaining_pp")
    try:
        remaining = float(remaining)
    except (TypeError, ValueError):
        print("interval: remaining_pp 파싱 실패 → fallback", file=sys.stderr)
        return _emit(fallback)

    interval = next_interval_s(
        remaining_pp=remaining,
        pp_per_round=pp_per_round,
        night_end_h=night_end_h,
        max_s=day_interval,
        _now=now,
    )
    print(f"interval: remaining={remaining}pp pp/round={pp_per_round:.2f} → {interval}s",
          file=sys.stderr)
    return _emit(interval)


def _cli() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--daily-pct", type=float, default=None)   # run-loop 호환(현재 미사용)
    ap.parse_known_args()
    return main()


if __name__ == "__main__":
    try:
        raise SystemExit(_cli())
    except SystemExit:
        raise
    except Exception as e:  # noqa: BLE001
        print(f"interval: 예외 → fallback (exit 1): {e}", file=sys.stderr)
        sys.exit(1)
