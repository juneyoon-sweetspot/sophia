"""의도 브리프 — tracked 프로젝트마다 SOPHIA 가 초안(의도/진전/경계)을 쓰고, 사람은 수정.

  python3 scripts/brief.py --show     # 초안만 보기(에디터 안 열음)
  python3 scripts/brief.py            # 초안 → $EDITOR 로 열어 수정 → tracked.json 저장
  python3 scripts/brief.py --redraft  # 이미 브리프 있어도 다시 초안

빈 폼이 아니라 '채워진 3줄'을 주고, 사람은 틀린 줄만 고친다(주의력 절약).
"""
from __future__ import annotations

import argparse
import asyncio
import os
import subprocess
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sophia.adapters.registry import Registry  # noqa: E402
from sophia.adapters.sessions import draft_brief, group_by_cwd  # noqa: E402


def _latest_by_cwd():
    return {g.cwd: g.latest for g in group_by_cwd()}


async def _draft_all(reg: Registry, redraft: bool):
    from sophia.adapters.thinker.claude_cli import ClaudeCliThinker
    thinker = ClaudeCliThinker()
    latest = _latest_by_cwd()
    todo = [t for t in reg.items if redraft or not t.has_brief()]
    if not todo:
        return
    print(f"초안 작성 중(haiku, {len(todo)}개)…")
    drafts = await asyncio.gather(*(
        draft_brief(latest[t.cwd], thinker) if t.cwd in latest
        else _empty() for t in todo
    ))
    for t, d in zip(todo, drafts):
        t.intent, t.progress, t.boundaries = d["intent"], d["progress"], d["boundaries"]


async def _empty():
    return {"intent": "", "progress": "", "boundaries": ""}


def _to_md(reg: Registry) -> str:
    lines = ["# 의도 브리프 (틀린 줄만 고치고 저장하세요)\n"]
    for t in reg.items:
        lines += [
            f"## {t.cwd}",
            f"intent: {t.intent}",
            f"progress: {t.progress}",
            f"boundaries: {t.boundaries}",
            "",
        ]
    return "\n".join(lines)


def _from_md(text: str, reg: Registry) -> None:
    by_cwd = {t.cwd: t for t in reg.items}
    cur = None
    for line in text.splitlines():
        if line.startswith("## "):
            cur = by_cwd.get(line[3:].strip())
        elif cur is not None and ":" in line:
            k, _, v = line.partition(":")
            k = k.strip().lower()
            if k in ("intent", "progress", "boundaries"):
                setattr(cur, k, v.strip())


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--show", action="store_true", help="초안만 출력(에디터 안 열음)")
    ap.add_argument("--redraft", action="store_true", help="이미 브리프 있어도 재초안")
    ap.add_argument("--save", action="store_true", help="에디터 없이 초안을 바로 저장")
    args = ap.parse_args()

    reg = Registry.load()
    if not reg.items:
        print("tracked 프로젝트 없음. 먼저 `python3 -m sophia track`.")
        return 1

    asyncio.run(_draft_all(reg, args.redraft))
    md = _to_md(reg)

    if args.show:
        print(md)
        print("(--show: 저장 안 함. 에디터로 수정하려면 --show 빼고 실행)")
        return 0

    if args.save:
        reg.save()
        from sophia.adapters.registry import DEFAULT_PATH
        print(f"초안 그대로 저장 → {DEFAULT_PATH}")
        for t in reg.items:
            print(f"  [{Path(t.cwd).name}] {t.intent[:55]}")
        return 0

    # 초안을 $EDITOR 로 열어 사람이 예외만 수정 → 다시 읽어 저장.
    editor = os.environ.get("EDITOR", "nano")
    with tempfile.NamedTemporaryFile("w+", suffix=".md", delete=False, encoding="utf-8") as f:
        f.write(md)
        tmp = f.name
    try:
        subprocess.call([editor, tmp])
        edited = Path(tmp).read_text(encoding="utf-8")
    finally:
        os.unlink(tmp)
    _from_md(edited, reg)
    reg.save()
    from sophia.adapters.registry import DEFAULT_PATH
    print(f"저장됨 → {DEFAULT_PATH}")
    for t in reg.items:
        print(f"  [{Path(t.cwd).name}] intent: {t.intent[:60]}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
