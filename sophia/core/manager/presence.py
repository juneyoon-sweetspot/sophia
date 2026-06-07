"""사용자 부재 감지 — '사람이 지금 키보드 앞에 있나'를 세션 mtime 으로 추정.

밤샘 루프가 적응형 간격을 정할 때 쓴다. 사용자가 활동 중이면(최근 세션 mtime 이
가깝다) SOPHIA 는 비켜줘야 하고, 자리를 비웠으면 예산을 야간에 고루 펴 바른다.

데이터 소스는 `sessions.scan_sessions(exclude_sophia=True)` — SOPHIA 자신이 띄운
세션을 빼야 '내가 방금 돌았다'는 사실을 '사람이 활동 중'으로 오인하지 않는다(B2).
이는 daily.py 의 ACTIVE_WINDOW_S 판정과 같은 데이터 소스다(일관성).
"""
from __future__ import annotations

import time as _time

from sophia.adapters.sessions import scan_sessions

# ACTIVE_WINDOW_S(daily.py)와 동일해야 한다 — 두 곳이 다른 '활성' 판단을 내리면 안 됨.
AWAY_THRESHOLD_S = 3600


def last_user_activity_s(root=None, _now=None) -> float:
    """사용자 세션(SOPHIA 제외) 중 가장 최근 mtime 까지 경과 초.

    세션이 하나도 없으면 float('inf') — 사람이 없다고 보수적으로 처리(밤새 돌리기).
    """
    now = _time.time() if _now is None else _now
    kwargs = {"exclude_sophia": True}
    if root is not None:
        kwargs["root"] = root
    sessions = scan_sessions(**kwargs)
    newest = max((si.mtime for si in sessions), default=None)
    if newest is None:
        return float("inf")
    return now - newest


def is_away(threshold_s: float = AWAY_THRESHOLD_S, root=None, _now=None) -> bool:
    """마지막 사용자 활동이 threshold_s 보다 오래됐으면 True(자리 비움)."""
    return last_user_activity_s(root=root, _now=_now) > threshold_s
