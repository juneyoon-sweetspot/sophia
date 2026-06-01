"""내 프로젝트를 수동 등록/해제/조회 — 포트폴리오의 진실은 사람이 정한다.

  python3 scripts/track.py list                         # 등록된 것 보기
  python3 scripts/track.py add /path/to/proj "메모"      # 등록
  python3 scripts/track.py rm  /path/to/proj            # 해제
  python3 scripts/track.py suggest --explain --top 8     # 후보 요약 보고 고르기
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sophia.adapters.registry import Registry  # noqa: E402


def main() -> int:
    args = sys.argv[1:]
    cmd = args[0] if args else "list"
    reg = Registry.load()

    if cmd == "list":
        if not reg.items:
            print("등록된 프로젝트 없음. `track.py add <cwd> \"메모\"` 로 등록.")
            return 0
        print(f"등록된 프로젝트 {len(reg.items)}개:")
        for t in reg.items:
            print(f"  • {t.cwd}" + (f"  — {t.note}" if t.note else ""))
        return 0

    if cmd == "add":
        if len(args) < 2:
            print("사용: track.py add <cwd> [메모]")
            return 1
        cwd = str(Path(args[1]).expanduser())
        note = args[2] if len(args) > 2 else ""
        if not Path(cwd).is_dir():
            print(f"⚠ 경로가 디렉토리가 아님(그래도 등록): {cwd}")
        added = reg.track(cwd, note=note)
        reg.save()
        print(("등록됨: " if added else "이미 있음(메모 갱신): ") + cwd)
        return 0

    if cmd in ("rm", "remove", "untrack"):
        if len(args) < 2:
            print("사용: track.py rm <cwd>")
            return 1
        cwd = str(Path(args[1]).expanduser())
        print(("해제됨: " if reg.untrack(cwd) else "등록돼있지 않음: ") + cwd)
        reg.save()
        return 0

    if cmd == "suggest":
        # 후보를 요약과 함께 보여주고, 사람이 add 로 고르게 한다(자동 등록 안 함).
        from import_sessions import main as suggest_main  # 같은 scripts 폴더
        sys.argv = ["import_sessions.py", *args[1:]]
        return suggest_main()

    print(__doc__)
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
