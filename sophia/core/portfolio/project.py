"""Project — SOPHIA 가 동시에 들고 있는 '하나의 프로젝트' 단위.

기존 Scheduler 는 '한 목표'를 처리한다. Portfolio 는 N개 Project 를 들고 각각을
독립적으로 추적한다. Project 는 그 프로젝트의 '상태'만 들고 있다 — 세부 작업 기록은
각자의 handoff.json 에. (SOPHIA 는 내용이 아니라 상태를 본다 = 관리자다움)

blockers: 사람 결정이 필요한 항목. 즉시 보내지 않고 여기 쌓였다가 주기적 다이제스트로
한 번에 올라간다(자잘한 간섭 회피).
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class Blocker:
    """사람 결정이 필요한 항목. leverage = 결정의 파급/중요도(정렬 키)."""
    project_id: str
    question: str
    leverage: int = 1          # 높을수록 먼저 다이제스트 상단
    context: str = ""


@dataclass
class Project:
    id: str
    goal: str
    org: str = ""              # 어느 본부/조직 (당신의 10개 조직)
    status: str = "active"     # active | blocked | done
    cycles_done: int = 0       # 이 프로젝트에 쓴 사이클 수
    last_progress_tick: int = 0  # 마지막으로 전진한 portfolio 틱 (정체 감지용)
    handoff_path: str = ""     # 이 프로젝트 전용 핸드오프
    pending_requests: list[str] = field(default_factory=list)
    speculative_requests: list[str] = field(default_factory=list)
    blockers: list[Blocker] = field(default_factory=list)
    meta: dict[str, Any] = field(default_factory=dict)

    def is_active(self) -> bool:
        return self.status == "active"

    def staleness(self, now_tick: int) -> int:
        """마지막 전진 이후 경과한 틱 수. 클수록 '잊힌' 프로젝트."""
        return now_tick - self.last_progress_tick


def should_skip_blocked(
    n_open_blockers: int, blocked_mtime: float, latest_session_mtime: float
) -> bool:
    """막힌 프로젝트를 이번 라운드에 건너뛸지(워커 재실행 안 함).

    철학: 부분의 막힘은 우회한다 — 사람 결정 대기 중인 프로젝트의 병목은 SOPHIA 가 아니라
    사람이다. 그래서 '세상이 움직일'(사람이 그 프로젝트를 다시 건드릴) 때까지 워커를 다시
    던지지 않는다. answer 를 타이핑받는 게 아니라 세션 mtime 으로 감지한다.

    열린 blocker 가 없으면 돌린다. 있어도 사람이 막힌 뒤로 세션을 건드렸으면(mtime↑) 돌린다.
    """
    if n_open_blockers <= 0:
        return False
    return latest_session_mtime <= blocked_mtime


def project_mode(
    n_open_blockers: int, blocked_mtime: float, groundwork_mtime: float,
    latest_session_mtime: float, is_active: bool = False,
) -> str:
    """라운드마다 그 프로젝트의 행동: 'active' | 'progress' | 'groundwork' | 'quiet'.

    - active    : 사람이 *지금* 작업 중(최근 사용) → SOPHIA 비켜줌(defer). 충돌 방지 +
                  "낮=인간, 밤=AI": 당신이 손 떼면 그때 집는다.
    - progress  : 안 막혔거나 사람이 건드림(세상이 움직임) → 진전 + 결정 목록 replace(청소).
    - groundwork: 막힘 + 미접촉 + 이 block 에 아직 밑작업 안 함 → 한 번 알아서 밑작업.
    - quiet     : 막힘 + 미접촉 + 이미 밑작업함 → 조용히 대기($0, 또 안 파헤침).
    """
    if is_active:           # 당신이 지금 그 안에 있다 → 무조건 비켜줌
        return "active"
    if n_open_blockers <= 0:
        return "progress"
    if latest_session_mtime > blocked_mtime:   # 사람이 건드림 → 진전(replace)
        return "progress"
    if groundwork_mtime > 0 and groundwork_mtime >= blocked_mtime:  # 이미 밑작업함
        return "quiet"
    return "groundwork"                          # 막힘, 아직 밑작업 안 함 → 한 번
