"""라이브 포트폴리오 1개 주행 — 기존 클로드 세션 임포트 → 실제 claude 워커.

안전(개선판): 워커를 read_only(--permission-mode plan + --strict-mcp-config)로 펜싱한다.
 - plan 모드: 파일 쓰기/편집/실행 차단(읽고 분석·계획만)
 - strict-mcp-config: MCP 서버 0개 로드 → 외부 부작용(노션 등) 차단
이 펜스 덕에 '실제 프로젝트 cwd'에서 돌려도 안전하다 — 워커가 진짜 파일·맥락을 읽어
고품질 분석을 내되, 아무것도 못 바꾼다. (이전엔 빈 샌드박스라 워커가 엉뚱한 프로젝트를
환각하고 MCP 로 노션 페이지를 만들었다 — cwd 격리는 MCP 를 못 막기 때문.)

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

READONLY_REQUEST = (
    "아래는 한 프로젝트에서 사람이 마지막으로 남긴 지시다. 지금은 분석만 한다(읽기 전용): "
    "현재 작업이 어디까지 왔는지 실제 파일을 읽어 추정하고, 다음 한 스텝이 무엇인지 제안하라. "
    "막히거나 사람 결정이 필요하면 재구성 질문 1개를 남겨라.\n\n"
    "프로젝트 목표: {goal}\n사람의 마지막 지시: {last}"
)


def _factory(p):
    req = READONLY_REQUEST.format(goal=p.goal, last=(p.pending_requests or [""])[0])
    return Scheduler(
        backend=ClaudeCodeBackend(read_only=True),    # plan + strict-mcp = 부작용 0
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

    real_cwd = p.meta["cwd"]
    if not Path(real_cwd).is_dir():
        print(f"✗ cwd 가 존재하지 않음: {real_cwd}")
        return 1
    os.chdir(real_cwd)  # 실제 프로젝트에서 — read_only(plan+strict-mcp)로 안전
    print(f"워커 cwd = {real_cwd} (read_only: 쓰기·MCP 차단)\n")

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
