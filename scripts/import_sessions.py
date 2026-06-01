"""기존 클로드 세션을 스캔해 SOPHIA Project 후보로 보여준다(읽기 전용).

  python3 scripts/import_sessions.py              # 사용량 top + 전체 표
  python3 scripts/import_sessions.py --rank usage --top 5

순수 읽기. ~/.claude/projects 를 변형하지 않는다.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sophia.adapters.sessions import group_by_cwd, import_projects  # noqa: E402


def _short(s: str, n: int) -> str:
    s = (s or "").replace("\n", " ").strip()
    return s if len(s) <= n else s[: n - 1] + "…"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--rank", choices=["recency", "usage"], default="usage")
    ap.add_argument("--top", type=int, default=None)
    ap.add_argument("--min-msgs", type=int, default=2)
    args = ap.parse_args()

    groups = group_by_cwd()
    print(f"스캔: {len(groups)}개 작업 디렉토리(cwd)에서 세션 발견\n")

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
