"""cmux 세션 이름 — 사람이 cmux 에서 단/보는 탭 이름을 cwd 별로 읽는다(best-effort).

claude jsonl 의 aiTitle 은 '자동 제목'이라, 사람이 cmux 탭에 직접 단 이름과 다르다.
cmux 는 세션 스토어(session-com.cmuxterm.app.json)의 windows→tabs 에 터미널 탭마다
directory(=cwd) + title(=화면에 보이는 이름)을 둔다. 그 cwd→title 을 뽑아 쓴다.

cmux 가 없거나 포맷이 바뀌면 빈 dict 반환(호출자는 aiTitle 로 폴백). 순수 읽기.
"""
from __future__ import annotations

import json
import re
from pathlib import Path

DEFAULT_STORE = Path.home() / "Library" / "Application Support" / "cmux" / "session-com.cmuxterm.app.json"

# 제목 앞 상태 글리프(✳ 자동제목 · ⠀-⣿ 브레일 스피너 · •·) 제거 → 사람이 읽는 이름만.
_GLYPH = re.compile(r"^[\s✳⠀-⣿•·▸▹◦◌]+")


def _clean(title: str) -> str:
    return _GLYPH.sub("", title or "").strip()


def cwd_titles(store: str | Path = DEFAULT_STORE) -> dict[str, str]:
    """{cwd 절대경로: cmux 탭 이름}. 사람이 직접 단 이름(✳/스피너 없는 raw 제목)을 우선,
    없으면 자동 제목(✳ aiTitle)을 정리해 사용. 경로형/빈 제목은 버림. cmux 없으면 {}."""
    store = Path(store)
    try:
        data = json.loads(store.read_text(encoding="utf-8"))
    except Exception:
        return {}

    # cwd -> (is_human, name). is_human(✳/스피너 없음=사람 rename)이 우선.
    best: dict[str, tuple[bool, str]] = {}

    def walk(o):
        if isinstance(o, dict):
            d, t = o.get("directory"), o.get("title")
            if d and isinstance(t, str):
                cwd = str(Path(str(d)).expanduser())
                is_human = (_GLYPH.match(t) is None)   # 앞 글리프 없음 = 사람이 단 이름
                name = _clean(t)
                # 경로/디렉토리명/빈 것은 rename 아님 → 버림
                bad = (not name or name in (str(d), cwd, Path(cwd).name)
                       or name.startswith(("~", "/")) or len(name) <= 1)
                if not bad:
                    cur = best.get(cwd)
                    if cur is None or (is_human and not cur[0]):  # 사람 이름이 자동을 이김
                        best[cwd] = (is_human, name)
            for v in o.values():
                walk(v)
        elif isinstance(o, list):
            for v in o:
                walk(v)

    walk(data)
    return {cwd: name for cwd, (_h, name) in best.items()}
