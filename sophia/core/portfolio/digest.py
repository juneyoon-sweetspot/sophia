"""Digest — 여러 프로젝트의 상태·블로커를 '한 통'으로 모은다.

SOPHIA 의 보고 모델: 매 작업마다 사람을 건드리지 않는다. 블로커를 쌓아뒀다가
주기적으로(원온원 주기) leverage 순 단일 다이제스트로 올린다. 그 사이엔 침묵.

다이제스트는 본부장이 '주의를 가장 적게 쓰고' 결정할 수 있게 정렬·압축된다:
 1) 결정 필요(블로커) — leverage 내림차순. 이게 사람이 볼 핵심.
 2) 정체된 프로젝트 — staleness 높은 것(잊힌 것 표면화).
 3) 진행 요약 — 각 프로젝트 한 줄.
"""
from __future__ import annotations

from pathlib import Path

from .critic import classify_blocker
from .project import Project


def build_digest(
    projects: list[Project],
    now_tick: int,
    stale_threshold: int = 14,
    apply_critic: bool = True,
) -> str:
    """프로젝트 리스트 → 사람이 읽을 단일 다이제스트 텍스트.

    stale_threshold: 이 틱 이상 안 건드린 프로젝트를 '정체'로 표면화(기본 14 = 2주).
    apply_critic: True 면 critic gate 로 해석질문 제외/코드용어 표시(기본 True, backward compatible).
    """
    lines: list[str] = []

    # 1) 결정 필요 — 모든 블로커를 leverage 순으로 (이게 다이제스트의 심장)
    blockers = [(p, b) for p in projects for b in p.blockers]
    blockers.sort(key=lambda pb: pb[1].leverage, reverse=True)

    rendered = []
    excluded_count = 0
    for p, b in blockers:
        if apply_critic:
            label = classify_blocker(b.question)  # 내부에 try/except 있음
        else:
            label = "ok"
        if label == "excluded":
            excluded_count += 1
        else:
            rendered.append((p, b, label))

    if rendered:
        suffix = f", {excluded_count}건 자동처리" if excluded_count else ""
        lines.append(f"■ 결정이 필요합니다 ({len(rendered)}건{suffix})")
        for i, (p, b, label) in enumerate(rendered, 1):
            cwd = p.meta.get("cwd", "")
            cwd_label = f" ({Path(cwd).name})" if cwd else ""
            tag = f"[{p.org}/{p.id}]" if p.org else f"[{p.id}]"
            goal_snip = f" {p.goal[:30]}" if p.goal else ""
            prefix = "[⚠기술용어] " if label == "flagged" else ""
            lines.append(f"  {i}. {tag}{goal_snip}{cwd_label}")
            lines.append(f"     ↳ {prefix}{b.question}")
    elif excluded_count:
        # rendered=0, excluded>0 — 모든 블로커가 자동처리됨
        lines.append(f"■ 결정이 필요한 항목 없음 ({excluded_count}건 자동처리)")
    else:
        lines.append("■ 결정이 필요한 항목 없음")

    # 2) 정체 — 오래 안 건드린 active 프로젝트
    stale = [p for p in projects if p.is_active() and p.staleness(now_tick) >= stale_threshold]
    if stale:
        lines.append("")
        lines.append(f"■ 정체된 프로젝트 ({len(stale)}건 — {stale_threshold}틱 이상)")
        for p in stale:
            tag = f"[{p.org}/{p.id}]" if p.org else f"[{p.id}]"
            lines.append(f"  - {tag} {p.goal[:50]} (마지막 진행 {p.staleness(now_tick)}틱 전)")

    # 3) 진행 요약 — 프로젝트별 한 줄
    lines.append("")
    lines.append(f"■ 전체 현황 ({len(projects)}개 프로젝트)")
    for p in projects:
        tag = f"[{p.org}/{p.id}]" if p.org else f"[{p.id}]"
        bl = f" · 결정대기 {len(p.blockers)}" if p.blockers else ""
        goal_snip = f" {p.goal[:30]} |" if p.goal else ""
        lines.append(f"  - {tag}{goal_snip} {p.status} · {p.cycles_done}사이클{bl}")

    return "\n".join(lines)
