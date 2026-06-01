"""실증테스트 — N개 실제 프로젝트를 동시 운영하고 '한 통의 다이제스트'를 받는다.

SOPHIA 의 핵심 주장 검증용: "본부장은 자잘한 알림에 시달리지 않고, leverage 순으로
정렬된 한 통을 받아 결정만 하면 된다." 이게 실제로 성립하는지 본다.

안전: 모든 워커 read_only(plan + strict-mcp) → 실제 cwd 에서 돌려도 파일·MCP 부작용 0.
각 워커는 자기 프로젝트 cwd 에서 돈다(전역 chdir 아님 — 어댑터 cwd 주입).

  python3 scripts/portfolio_multi.py --cwd /A --cwd /B --cwd /C
  python3 scripts/portfolio_multi.py --top 4   # 사용량 top (홈/잡동사니 제외)
"""
from __future__ import annotations

import argparse
import asyncio
import json
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

# 잡동사니(홈·다운로드 등) 기본 제외 — 실제 프로젝트만 실증.
DEFAULT_EXCLUDE = {"/Users/juneyoon", "/Users/juneyoon/Downloads", "/Users/juneyoon/Desktop"}

READONLY_REQUEST = (
    "아래는 한 프로젝트에서 사람이 마지막으로 남긴 지시다. 지금은 분석만 한다(읽기 전용): "
    "실제 파일을 읽어 현재 어디까지 왔는지 추정하고, 다음 한 스텝을 제안하라. "
    "사람만 정할 수 있는 결정(방향 선택·승인·사실 확인)이 있으면 재구성 질문으로 남겨라.\n\n"
    "프로젝트 목표: {goal}\n사람의 마지막 지시: {last}"
)


def _factory(p):
    req = READONLY_REQUEST.format(goal=p.goal, last=(p.pending_requests or [""])[0])
    return Scheduler(
        backend=ClaudeCodeBackend(read_only=True, cwd=p.meta["cwd"]),  # 부작용 0 + 자기 cwd
        director=Director(goal=p.goal),
        thinker=ClaudeCliThinker(),
        goal=p.goal,
        session_id=p.id,
        handoff_path=p.handoff_path,
        premise_count=1,
        max_cycles=1,
        surface_blockers=True,
        pending_requests=[req],
    )


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--cwd", action="append", default=[], help="프로젝트 cwd(여러 번)")
    ap.add_argument("--top", type=int, default=None, help="사용량 top N(홈/잡동사니 제외)")
    args = ap.parse_args()

    if args.cwd:
        projects = import_projects(only_cwds=set(args.cwd), min_user_msgs=1)
    else:
        projects = import_projects(rank="usage", top=args.top or 4,
                                   exclude_cwds=DEFAULT_EXCLUDE, min_user_msgs=2)
    # cwd 가 실제로 존재하는 것만(삭제된 디렉토리 방어)
    projects = [p for p in projects if Path(p.meta["cwd"]).is_dir()]
    if not projects:
        print("✗ 임포트할 실제 프로젝트가 없음")
        return 1

    print(f"실증테스트 — {len(projects)}개 프로젝트 동시 운영 (전부 read_only):\n")
    for p in projects:
        print(f"  [{p.id}] {p.meta['cwd']}  · goal: {p.goal[:50]}")
    print(f"\n  → 실제 claude {len(projects)}회 + thinker 호출. 수 분 소요. 부작용 0.\n")

    pf = Portfolio(
        projects=projects,
        scheduler_factory=_factory,
        notifier=StdoutNotifier(),
        digest_interval=len(projects),   # 모두 1스텝 돈 뒤 '한 통' 발행
        max_ticks=len(projects),
    )
    print("=== 주행 시작 ===\n")
    digests = asyncio.run(pf.run())

    print("\n" + "=" * 70)
    print("=== 최종 단일 다이제스트 (본부장이 받는 '한 통') ===")
    print("=" * 70)
    print(digests[-1] if digests else "(없음)")

    print("\n=== 평가용: 프로젝트별 워커 보고 ===")
    for p in projects:
        try:
            ho = json.load(open(p.handoff_path))
            rep = ho.get("reports", [{}])
            txt = rep[-1].get("text", "") if rep else ""
            print(f"\n[{p.id}] (blockers {len(p.blockers)})")
            print("  보고:", txt[:300])
            for b in p.blockers:
                print(f"  · 결정[lev{b.leverage}]: {b.question}")
        except Exception as e:
            print(f"[{p.id}] handoff 읽기 실패: {e}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
