"""세션 핸드오프 — 콜드패스에서 1회 증류 → 다음 세션의 안정 prefix.

활성 세션(핫패스)에서는 건드리지 않는다. 세션 경계/주기적으로만 저장.
일꾼 WorkResult 도 같은 모양(decisions/artifacts)이라 변환 없이 흡수된다.
"""
from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field, fields
from pathlib import Path
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from ..manager.premise import PremiseOutcome


@dataclass
class Decision:
    id: str
    statement: str
    why: str = ""
    scope: str = "durable"  # durable | session
    supersedes: str | None = None


@dataclass
class Handoff:
    session_id: str
    summary: str = ""
    goal: str = ""
    status: str = "in_progress"  # in_progress | blocked | done
    next_action: str = ""
    decisions: list[Decision] = field(default_factory=list)
    constraints: list[str] = field(default_factory=list)
    artifacts: list[dict[str, Any]] = field(default_factory=list)
    open_questions: list[str] = field(default_factory=list)
    glossary: dict[str, str] = field(default_factory=dict)
    discarded: list[dict[str, str]] = field(default_factory=list)
    # 사용자 대면 5문장 보고의 영속 기록. 6h 후 돌아온 사용자가 "무엇을 전제로
    # 했는지"를 실제로 읽을 수 있게 한다(stdout 휘발 방지). [{at, text}]
    reports: list[dict[str, Any]] = field(default_factory=list)
    # 아직 처리 못 한 요청 큐. 재시작(resume) 시 이어가기 위해 저장한다.
    pending_requests: list[str] = field(default_factory=list)
    # 예측(anticipation)으로 만든 선제 작업 큐. resume 시 이어가기 위해 저장.
    speculative_requests: list[str] = field(default_factory=list)
    # synthesis 기록: 어느 전제를 왜 채택/기각했는지. [{request, chosen, rationale, rejected, grafts}]
    syntheses: list[dict[str, Any]] = field(default_factory=list)
    # 본부장이 결정해야 할 항목(매니저가 추출). [{question, leverage, context}]
    # Portfolio 가 이걸 읽어 project.blockers → 단일 다이제스트의 '결정 필요' 칸을 채운다.
    blockers: list[dict[str, Any]] = field(default_factory=list)
    # 실행 전 승인이 필요한 비가역 커밋(2단계 게이트 phase1 산출). [{action, why}]
    # held 상태로 사람 승인을 기다린다. 승인 전엔 실행 안 함.
    commit_gates: list[dict[str, Any]] = field(default_factory=list)
    # 6h 무인 실행에서 무한증가(메모리 누수) 방지용 상한. 오래된 것부터 버린다.
    max_items: int = 500

    def add_report(self, text: str, at: float | None = None) -> None:
        """사용자 대면 보고를 영속 기록에 추가."""
        self.reports.append({"at": at, "text": text})
        self.reports = self.reports[-self.max_items:]

    def absorb(self, outcomes: "list[PremiseOutcome]") -> None:
        """전제 결과를 흡수: 성공→decisions, 실패→discarded(재시도 방지), artifacts 누적."""
        for o in outcomes:
            if o.result.ok:
                self.decisions.append(
                    Decision(
                        id=o.premise.id,
                        statement=o.premise.statement,
                        why=o.result.summary,
                    )
                )
            else:
                self.discarded.append(
                    {"what": o.premise.statement, "why": o.result.summary}
                )
            self.artifacts.extend(o.result.artifacts)
        self._cap()

    def absorb_with_synthesis(self, request, outcomes, syn) -> None:
        """synthesis 적용 흡수: 채택안만 decision, 기각안은 synthesis 사유로 discarded.

        그냥 absorb() 가 '성공한 전제 전부'를 decision 으로 남기는 것과 달리,
        여기선 '관리자가 고른 하나'만 결정으로 남고 나머지는 이유와 함께 버려진다.
        실패한 전제는 그대로 discarded. artifacts 는 traceability 위해 전부 누적.
        """
        ok = {o.premise.id: o for o in outcomes if o.result.ok}
        reject_why = {r["id"]: r.get("why", "") for r in syn.rejected}
        for o in outcomes:
            if not o.result.ok:
                self.discarded.append(
                    {"what": o.premise.statement, "why": o.result.summary}
                )
            elif o.premise.id == syn.chosen_id:
                self.decisions.append(
                    Decision(id=o.premise.id, statement=o.premise.statement,
                             why=syn.rationale or o.result.summary)
                )
            else:
                self.discarded.append(
                    {"what": o.premise.statement,
                     "why": reject_why.get(o.premise.id, "synthesis 에서 미채택")}
                )
            self.artifacts.extend(o.result.artifacts)
        self.syntheses.append({
            "request": request,
            "chosen": syn.chosen_id,
            "rationale": syn.rationale,
            "rejected": syn.rejected,
            "grafts": syn.grafts,
        })
        self._cap()

    def _cap(self) -> None:
        """리스트가 상한을 넘으면 가장 오래된 항목부터 잘라낸다."""
        if self.max_items and self.max_items > 0:
            self.decisions = self.decisions[-self.max_items:]
            self.discarded = self.discarded[-self.max_items:]
            self.artifacts = self.artifacts[-self.max_items:]
            self.reports = self.reports[-self.max_items:]
            self.syntheses = self.syntheses[-self.max_items:]
            self.blockers = self.blockers[-self.max_items:]
            self.commit_gates = self.commit_gates[-self.max_items:]

    def save(self, path: str | Path) -> None:
        Path(path).write_text(
            json.dumps(asdict(self), ensure_ascii=False, indent=2), encoding="utf-8"
        )

    @classmethod
    def load(cls, path: str | Path) -> "Handoff":
        data = json.loads(Path(path).read_text(encoding="utf-8"))
        data["decisions"] = [Decision(**d) for d in data.get("decisions", [])]
        # 스키마 진화에 견고하게: 알 수 없는 키는 버린다(구/신 버전 호환).
        known = {f.name for f in fields(cls)}
        data = {k: v for k, v in data.items() if k in known}
        return cls(**data)
