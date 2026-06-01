"""기존 클로드 세션을 스캔해 SOPHIA Project 후보로 보여준다(읽기 전용).

  python3 scripts/import_sessions.py              # 빠른 표(첫 지시 = goal)
  python3 scripts/import_sessions.py --rank usage --top 5
  python3 scripts/import_sessions.py --explain --top 6   # 세션 요약(목적/활동/종류)

--explain 은 각 세션을 작은 모델(haiku)로 요약 — '무엇을 위해 무슨 일을 하던 세션인지'
+ active/one_off 판정. 첫 지시만으론 못 알아보는 프로젝트를 식별하기 위함.
순수 읽기. ~/.claude/projects 를 변형하지 않는다.
"""
from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sophia.adapters.sessions import (  # noqa: E402
    group_by_cwd,
    import_described,
    import_projects,
)


def _short(s: str, n: int) -> str:
    s = (s or "").replace("\n", " ").strip()
    return s if len(s) <= n else s[: n - 1] + "…"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--rank", choices=["recency", "usage"], default="usage")
    ap.add_argument("--top", type=int, default=None)
    ap.add_argument("--min-msgs", type=int, default=2)
    ap.add_argument("--explain", action="store_true", help="세션 요약(목적/활동/종류)")
    args = ap.parse_args()

    groups = group_by_cwd()
    print(f"스캔: {len(groups)}개 작업 디렉토리(cwd)에서 세션 발견\n")

    if args.explain:
        from sophia.adapters.thinker.claude_cli import ClaudeCliThinker
        print(f"세션 요약 중(haiku, top={args.top or '전체'})… 잠시 걸립니다.\n")
        projects = asyncio.run(import_described(
            ClaudeCliThinker(), rank=args.rank, top=args.top, min_user_msgs=args.min_msgs))
        for i, p in enumerate(projects, 1):
            m = p.meta
            tag = {"active": "●활성", "one_off": "○일회성", "unknown": "?미상"}.get(m["kind"], "?")
            print(f"{i:>2}. [{tag}] {p.id}  ({m['n_sessions']}세션·{m['total_user_msgs']}msg)")
            print(f"      목적: {_short(m['purpose'], 70)}")
            print(f"      활동: {_short(m['activity'], 70)}")
            print(f"      cwd:  {m['cwd']}")
        n_active = sum(1 for p in projects if p.meta["kind"] == "active")
        n_one = sum(1 for p in projects if p.meta["kind"] == "one_off")
        n_unk = len(projects) - n_active - n_one
        print(f"\n→ active {n_active} / one_off {n_one} / 미상 {n_unk}.")
        print("  kind 는 '힌트'일 뿐 자동 필터가 아니다 — 활동 많은 잡동사니 폴더(홈·Desktop)도")
        print("  active 로 잡힐 수 있다. 어느 게 '내 프로젝트'인지는 사람이 고른다(SOPHIA 원칙).")
        print("  고른 cwd 로:  python3 scripts/portfolio_multi.py --cwd <A> --cwd <B> ...")
        return 0

    projects = import_projects(rank=args.rank, top=args.top, min_user_msgs=args.min_msgs)
    print(f"임포트 후보 {len(projects)}개 (rank={args.rank}"
          + (f", top={args.top}" if args.top else "") + "):\n")
    print(f"{'#':>2}  {'사용량':>5}  {'세션':>3}  {'프로젝트':<22}  goal(첫 지시)")
    print("-" * 100)
    for i, p in enumerate(projects, 1):
        m = p.meta
        print(f"{i:>2}  {m['total_user_msgs']:>5}  {m['n_sessions']:>3}  "
              f"{_short(p.id, 22):<22}  {_short(p.goal, 44)}")
    print()
    print("cwd 전체 경로:")
    for p in projects:
        print(f"  [{p.id}] {p.meta['cwd']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
