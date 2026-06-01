"""Portfolio — SOPHIA 의 '본부장 비서' 층. 여러 프로젝트를 동시에 들고 돌린다.

기존 Scheduler 는 '한 목표'를 처리한다. Portfolio 는 그 위에 얇게 얹혀:
 - N개 Project 를 들고
 - 매 틱 '정체 우선'으로 한 프로젝트를 골라 한 스텝 전진시키고
 - 블로커를 즉시 보내지 않고 쌓아뒀다가
 - 주기적으로(digest_interval) leverage 순 단일 다이제스트를 notifier 로 한 번에 올린다.

안티패턴 회피: Portfolio 도 직접 일하지 않는다. scheduler_factory 로 받은
Scheduler(=위임 엔진)에게 한 스텝을 시키고, 결과의 '상태'만 Project 에 반영한다.

scheduler_factory(project) -> Scheduler 를 주입받아 '어떻게 한 스텝 도는지'를
분리한다(테스트는 fake factory 로). Scheduler 는 max_cycles=1 로 한 스텝만 돈다.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Awaitable, Callable

from ...ports.notifier import Notifier
from ..loop.scheduler import Scheduler
from .digest import build_digest
from .project import Blocker, Project


@dataclass
class Portfolio:
    projects: list[Project]
    scheduler_factory: Callable[[Project], Scheduler]
    notifier: Notifier | None = None
    digest_interval: int = 14      # 이 틱마다 다이제스트 1회 (기본 2주치)
    stale_threshold: int = 14      # 다이제스트에서 '정체'로 표면화할 기준
    max_ticks: int | None = None   # 안전/테스트 상한. None 이면 active 없을 때까지

    _tick: int = 0
    digests: list[str] = field(default_factory=list)  # 발행 이력(테스트·열람)

    def pick(self) -> Project | None:
        """다음에 전진시킬 프로젝트. 정체 우선(가장 오래 안 건드린 active)."""
        active = [p for p in self.projects if p.is_active()]
        if not active:
            return None
        return max(active, key=lambda p: p.staleness(self._tick))

    async def run(self) -> list[str]:
        """포트폴리오를 돌린다. 발행된 다이제스트 리스트를 반환."""
        while self.max_ticks is None or self._tick < self.max_ticks:
            proj = self.pick()
            if proj is None:
                break  # 모든 프로젝트 done

            self._tick += 1
            await self._advance(proj)

            # 주기마다 단일 다이제스트 발행
            if self._tick % self.digest_interval == 0:
                self._emit_digest()

        # 끝에 한 번 더(남은 블로커 flush)
        self._emit_digest()
        return self.digests

    async def step(self) -> bool:
        """한 틱만 전진(TUI 's' 키용). 전진했으면 True, 모두 done 이면 False.

        run() 과 달리 한 스텝만 돌고 멈춘다 — 사람이 화면에서 한 박자씩 보게.
        digest_interval 에 걸리면 다이제스트도 발행한다.
        """
        proj = self.pick()
        if proj is None:
            return False
        self._tick += 1
        await self._advance(proj)
        if self._tick % self.digest_interval == 0:
            self._emit_digest()
        return True

    async def _advance(self, proj: Project) -> None:
        """프로젝트 한 스텝 전진. Scheduler 에 위임하고 상태만 반영."""
        sched = self.scheduler_factory(proj)
        try:
            ho = await sched.run(report=lambda _m: None)  # 보고는 버퍼링(다이제스트로)
        except Exception:
            return  # 한 프로젝트 실패가 포트폴리오를 죽이지 않는다

        proj.cycles_done += 1
        proj.last_progress_tick = self._tick
        # Scheduler 결과의 '상태'만 흡수 (내용 아님 — 세부는 handoff 에)
        proj.pending_requests = list(getattr(sched, "pending_requests", []))
        proj.speculative_requests = list(getattr(sched, "speculative_requests", []))
        # 매니저가 추출한 결정 필요 항목 → project.blockers (다이제스트의 '결정' 칸).
        # 이게 없으면 라이브 다이제스트의 결정 칸이 영원히 빈다(이 PR 이 메우는 구멍).
        # 핵심: '교체'가 아니라 '누적'이다. 실제 포트폴리오는 digest_interval(기본 14) 동안
        # 여러 틱을 돌고, blocker 는 사람이 다이제스트에서 처리할 때까지 쌓여야 한다. 매 advance
        # 마다 교체하면 일찍 뜬 결정이 디지스트 전에 증발한다. question 텍스트로 중복만 거른다.
        # (raised 된 blocker 의 '해소/제거' 라이프사이클은 후속 과제 — 여기선 누적만.)
        seen = {b.question for b in proj.blockers}
        for b in getattr(ho, "blockers", []) or []:
            q = b.get("question", "")
            if q and q not in seen:
                seen.add(q)
                proj.blockers.append(
                    Blocker(
                        project_id=proj.id,
                        question=q,
                        leverage=int(b.get("leverage", 1) or 1),
                        context=b.get("context", ""),
                    )
                )
        if getattr(ho, "status", None) == "done" and not proj.pending_requests:
            proj.status = "done"

    def _emit_digest(self) -> None:
        digest = build_digest(self.projects, self._tick, self.stale_threshold)
        self.digests.append(digest)
        if self.notifier is not None:
            try:
                self.notifier.send(self._digest_subject(), digest)
            except Exception:
                pass

    def _digest_subject(self) -> str:
        n = len([p for p in self.projects if p.is_active()])
        return f"[SOPHIA 다이제스트] 진행 {n}개 · tick {self._tick}"
