"""라이브 포트폴리오 1개 주행 — 기존 클로드 세션 임포트 → 실제 claude 워커.

안전: 워커는 빈 샌드박스 cwd(/tmp/sophia_live)에서 돌고, 지시는 '분석만, 파일 수정
금지'다. 실제 프로젝트 파일은 건드리지 않는다. (헤드리스 claude -p 는 기본 권한에서
편집을 자동 거부하기도 하지만, 샌드박스 cwd + 읽기전용 지시로 이중으로 막는다.)

목적: 임포터 → 포트폴리오 → 실제 claude → 5문장 보고 → 다이제스트 경로를 라이브로
검증하고, 다이제스트의 '결정 필요' 칸이 라이브에서 어떻게 나오는지(빈-다이제스트 버그)
직접 관찰한다.

  python3 scripts/portfolio_live.py --cwd /Users/juneyoon/Desktop/AX-Partners
"""
from __future__ import annotations

import argparse
import asyncio
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sophia.adapters.claude_code.adapter import ClaudeCodeBackend  # noqa: E402
from sophia.adapters.notifier.stdout import StdoutNotifier  # noqa: E402
from sophia.adapters.sessions import import_projects  # noqa: E402
from sophia.adapters.thinker.claude_cli import ClaudeCliThinker  # noqa: E402
from sophia.core.loop.scheduler import Scheduler  # noqa: E402
from sophia.core.manager.director import Director  # noqa: E402
from sophia.core.portfolio.portfolio import Portfolio  # noqa: E402

SANDBOX = "/tmp/sophia_live"

READONLY_REQUEST = (
    "아래는 한 프로젝트에서 사람이 마지막으로 남긴 지시다. 지금은 분석만 한다: "
    "현재 작업이 어디까지 왔는지 추정하고, 다음 한 스텝이 무엇인지 제안하라. "
    "절대 파일을 생성·수정하지 마라(읽기 전용). 막히면 사람에게 물을 재구성 질문 1개를 남겨라.\n\n"
    "프로젝트 목표: {goal}\n사람의 마지막 지시: {last}"
)


def _factory(p):
    req = READONLY_REQUEST.format(goal=p.goal, last=(p.pending_requests or [""])[0])
    return Scheduler(
        backend=ClaudeCodeBackend(base_repo=None),   # 샌드박스 cwd 상속(아래 chdir)
        director=Director(goal=p.goal),
        thinker=ClaudeCliThinker(),
        goal=p.goal,
        session_id=p.id,
        handoff_path=p.handoff_path,                  # 프로젝트별(충돌 방지)
        premise_count=1,                              # 라이브는 싸게: 전제 1개
        max_cycles=1,                                 # 한 스텝만
        surface_blockers=True,                        # 결정 필요 항목 → 다이제스트
        pending_requests=[req],
    )


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--cwd", required=True, help="임포트할 프로젝트의 실제 cwd")
    args = ap.parse_args()

    projects = import_projects(only_cwds={args.cwd}, min_user_msgs=1)
    if not projects:
        print(f"✗ {args.cwd} 에서 임포트할 세션을 못 찾음")
        return 1
    p = projects[0]
    print(f"임포트: [{p.id}] {p.meta['cwd']}")
    print(f"  goal: {p.goal[:70]}")
    print(f"  마지막 지시: {p.pending_requests[0][:70]}")
    print(f"  세션 {p.meta['n_sessions']}개 · 누적 {p.meta['total_user_msgs']} 메시지\n")

    Path(SANDBOX).mkdir(parents=True, exist_ok=True)
    os.chdir(SANDBOX)  # 워커가 빈 샌드박스에서 돌게(실파일 격리)
    print(f"워커 샌드박스 cwd = {SANDBOX} (실파일 격리)\n")

    pf = Portfolio(
        projects=[p],
        scheduler_factory=_factory,
        notifier=StdoutNotifier(),
        digest_interval=1,   # 1틱마다 다이제스트(여기선 1개라 바로 봄)
        max_ticks=1,
    )
    print("=== 라이브 주행 시작 (실제 claude 호출 — 1~2분 걸릴 수 있음) ===\n")
    digests = asyncio.run(pf.run())

    print("\n=== 다이제스트 ===")
    print(digests[-1] if digests else "(다이제스트 없음)")
    print("\n=== 워커가 실제로 반환한 것 (handoff) ===")
    try:
        import json
        ho = json.load(open(p.handoff_path))
        print(f"  status={ho['status']} decisions={len(ho['decisions'])} discarded={len(ho['discarded'])}")
        for r in ho.get("reports", []):
            print("  ─ 5문장 보고:", r["text"][:500])
        for dec in ho.get("decisions", []):
            print(f"  ─ decision[{dec['id']}]:", dec["why"][:500])
        for dc in ho.get("discarded", []):
            print("  ─ discarded:", str(dc)[:400])
    except Exception as e:
        print("  (handoff 읽기 실패:", e, ")")

    print("\n=== 관찰 포인트 ===")
    print(f"  project.blockers = {p.blockers}  ← 라이브에서 이게 비면 다이제스트 '결정' 칸도 빔")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
