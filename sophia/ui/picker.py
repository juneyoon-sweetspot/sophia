"""세션 피커 — '내 프로젝트'를 사람이 직접 고르는 인터랙티브 화면.

경로를 손으로 타이핑하는 대신, 요약된 후보 리스트에서 ↑↓ 보고 space 로 토글한다.
로직(PickerState/순수 함수)과 curses(얇게)를 분리 — 로직은 단위 테스트로 검증.

키: ↑↓ 이동 · space track 토글 · e 선택 항목 요약(haiku) · s 저장·종료 · q 취소
  python3 -m sophia track     (또는 sophia track)
"""
from __future__ import annotations

from dataclasses import dataclass, field

from ..adapters.registry import Registry
from ..adapters.sessions import CwdGroup, group_by_cwd


@dataclass
class Row:
    group: CwdGroup
    tracked: bool = False
    purpose: str = ""        # e 로 요약하면 채워짐
    activity: str = ""
    kind: str = ""           # active | one_off | unknown(요약 전 빈값)

    @property
    def cwd(self) -> str:
        return self.group.cwd

    @property
    def label(self) -> str:
        if self.purpose:  # e 로 요약했으면 그게 최우선
            return self.purpose + (f" — {self.activity}" if self.activity else "")
        # 요약 전엔 클로드 세션 제목(사람이 보는 rename 이름) → 없으면 첫 지시
        return self.group.latest.title or self.group.latest.first_user_text


@dataclass
class PickerState:
    rows: list[Row] = field(default_factory=list)
    selected: int = 0

    def move(self, delta: int) -> None:
        if self.rows:
            self.selected = max(0, min(len(self.rows) - 1, self.selected + delta))

    def toggle(self) -> None:
        if self.rows:
            self.rows[self.selected].tracked = not self.rows[self.selected].tracked

    def current(self) -> Row | None:
        return self.rows[self.selected] if self.rows else None

    def tracked_cwds(self) -> list[str]:
        return [r.cwd for r in self.rows if r.tracked]

    def n_tracked(self) -> int:
        return sum(1 for r in self.rows if r.tracked)


def build_state(groups: list[CwdGroup], registry: Registry) -> PickerState:
    """후보 그룹 + 기존 레지스트리 → 피커 상태. 이미 tracked 면 체크 표시."""
    rows = [Row(group=g, tracked=registry.is_tracked(g.cwd)) for g in groups]
    return PickerState(rows=rows)


def _short(s: str, n: int) -> str:
    s = (s or "").replace("\n", " ").strip()
    return s if len(s) <= n else s[: n - 1] + "…"


def render_rows(state: PickerState, width: int = 100) -> list[str]:
    """순수 렌더 — 각 행을 문자열로. (curses 없이 테스트 가능)"""
    out: list[str] = []
    kindmark = {"active": "●", "one_off": "○", "unknown": "·", "": "·"}
    for i, r in enumerate(state.rows):
        cur = "▶" if i == state.selected else " "
        chk = "[✓]" if r.tracked else "[ ]"
        k = kindmark.get(r.kind, "·")
        name = _short(r.cwd.rsplit("/", 1)[-1] or r.cwd, 20)
        meta = f"{r.group.total_user_msgs:>4}msg"
        out.append(f"{cur} {chk} {k} {name:<20} {meta}  {_short(r.label, max(10, width - 44))}")
    return out


def _wrap(s: str, width: int) -> list[str]:
    """공백 기준 단순 줄바꿈(순수). CJK 폭은 근사 — 충분히 읽힌다."""
    s = (s or "").replace("\n", " ").strip()
    if not s:
        return []
    out, line = [], ""
    for word in s.split(" "):
        if line and len(line) + 1 + len(word) > width:
            out.append(line)
            line = word
        else:
            line = f"{line} {word}".strip()
    if line:
        out.append(line)
    return out


def render_detail(state: PickerState, width: int = 80) -> list[str]:
    """선택 항목의 '자세히 보기' 패널(순수). 제목·목적·활동·종류 + 최근 지시 몇 개."""
    r = state.current()
    if r is None:
        return ["(후보 없음)"]
    g = r.group
    kindname = {"active": "활성", "one_off": "일회성", "unknown": "미상", "": "미요약"}
    lines = [f"📁 {g.cwd}"]
    if g.latest.title:
        lines.append(f"제목: {g.latest.title}")
    lines.append(f"종류: {kindname.get(r.kind, '미요약')} · {g.n_sessions}세션 · {g.total_user_msgs}msg"
                 + ("  [✓ tracked]" if r.tracked else ""))
    if r.purpose:
        lines += [f"목적: {x}" for x in _wrap(r.purpose, width - 4)]
        if r.activity:
            lines += [f"활동: {x}" for x in _wrap(r.activity, width - 4)]
    else:
        lines.append("(e 를 누르면 haiku 로 목적/활동 요약)")
    # 최근 사람 지시 몇 개 — LLM 없이도 '뭐였는지' 알아보게.
    recent = [t for t in (g.latest.user_trace or [])][-3:]
    if recent:
        lines.append("최근 지시:")
        for t in recent:
            lines += [f"  · {x}" for x in _wrap(t, width - 6)[:2]]  # 지시당 최대 2줄
    return lines


def reconcile(state: PickerState, registry: Registry) -> Registry:
    """피커 선택을 레지스트리에 반영(체크된 건 track, 해제된 건 untrack). 저장은 호출자."""
    chosen = set(state.tracked_cwds())
    for r in state.rows:
        if r.tracked:
            registry.track(r.cwd, note=r.purpose or "")
    # 피커에 보였는데 체크 해제된 cwd 는 레지스트리에서도 뺀다.
    for cwd in [t.cwd for t in list(registry.items)]:
        if any(row.cwd == cwd for row in state.rows) and cwd not in chosen:
            registry.untrack(cwd)
    return registry


# ─────────────────────────── curses 껍데기 ───────────────────────────

def _summarize_current(state: PickerState, thinker) -> None:
    import asyncio

    from ..adapters.sessions import summarize_session
    r = state.current()
    if r is None:
        return
    s = asyncio.run(summarize_session(r.group.latest, thinker, group=r.group))
    r.purpose, r.activity, r.kind = s.get("purpose", ""), s.get("activity", ""), s.get("kind", "")


def _loop(stdscr, state: PickerState, thinker) -> bool:
    import curses

    curses.curs_set(0)
    stdscr.keypad(True)
    msg = "↑↓ 이동 · space 선택 · e 요약 · s 저장 · q 취소"
    saved = False

    def put(y, x, s, attr=0):
        # 마지막 줄/우하단 코너에 폭 전부를 쓰면 curses 가 ERR 을 던진다. w-1 로 자르고 삼킴.
        h, w = stdscr.getmaxyx()
        try:
            stdscr.addnstr(y, x, s, max(0, w - 1 - x), attr)
        except curses.error:
            pass

    while True:
        stdscr.erase()
        h, w = stdscr.getmaxyx()
        detail_h = min(11, max(4, h // 3))
        list_h = max(1, h - detail_h - 3)        # header + 구분선 + status 제외
        put(0, 0, f" 내 프로젝트 고르기 ({state.n_tracked()} 선택) — {msg}".ljust(w),
            curses.A_REVERSE)
        # 리스트(선택이 안 보이면 스크롤)
        rows = render_rows(state, w - 2)
        top = max(0, min(state.selected - list_h + 1, len(rows) - list_h)) if len(rows) > list_h else 0
        for i in range(top, min(len(rows), top + list_h)):
            attr = curses.A_BOLD if i == state.selected else curses.A_NORMAL
            put(1 + (i - top), 0, rows[i], attr)
        # 구분선 + 상세 패널
        sep = h - detail_h - 1
        put(sep, 0, "─" * (w - 1))
        for j, line in enumerate(render_detail(state, w - 2)):
            if sep + 1 + j >= h - 1:
                break
            put(sep + 1 + j, 0, line)
        put(h - 1, 0, msg.ljust(w), curses.A_REVERSE)
        stdscr.refresh()
        ch = stdscr.getch()
        if ch in (ord("q"), ord("Q")):
            break
        elif ch in (curses.KEY_UP, ord("k")):
            state.move(-1)
        elif ch in (curses.KEY_DOWN, ord("j")):
            state.move(1)
        elif ch == ord(" "):
            state.toggle()
        elif ch in (ord("e"), ord("E")):
            put(h - 1, 0, " 요약 중(haiku)…", curses.A_REVERSE)
            stdscr.refresh()
            try:
                _summarize_current(state, thinker)
            except Exception:
                pass
        elif ch in (ord("s"), ord("S")):
            saved = True
            break
    return saved


def main() -> None:
    import curses

    groups = group_by_cwd()  # SOPHIA 자기세션 자동 제외(exclude_sophia 기본 on)
    # 사용량 많은 순, 잡동사니 홈/데스크톱은 뒤로(여전히 보이되 아래).
    groups.sort(key=lambda g: g.total_user_msgs, reverse=True)
    reg = Registry.load()
    state = build_state(groups, reg)
    if not state.rows:
        print("후보 세션이 없습니다.")
        return
    from ..adapters.thinker.claude_cli import ClaudeCliThinker
    saved = curses.wrapper(_loop, state, ClaudeCliThinker())
    if saved:
        from ..adapters.registry import DEFAULT_PATH
        reconcile(state, reg)
        reg.save()
        print(f"저장됨: {len(reg.items)}개 프로젝트 tracked → {DEFAULT_PATH}")
        for t in reg.items:
            print(f"  • {t.cwd}" + (f" — {t.note}" if t.note else ""))
    else:
        print("취소됨(저장 안 함).")


if __name__ == "__main__":
    main()
