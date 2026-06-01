"""Reversibility — '정확히 어디서부터 되돌릴 수 없는가'를 판단한다.

SOPHIA 원칙(정제됨): 모호함에 멈추지 않는다. 되돌릴 수 있는 공간(read-only 탐색,
격리 worktree)에선 포크해서 끝까지 가고, *되돌릴 수 없는 커밋 경계에서만* 멈춰
사람에게 게이트를 건다. 질문 빈도는 '모호함의 양'이 아니라 '비가역 행동의 수'에 비례한다.

핵심: 같은 도구라도 맥락에 따라 가역성이 갈린다 — 격리 worktree 안의 Edit 은 버리면
그만이라 가역, 실제 트리의 Edit 은 비가역. 그래서 판단은 (도구 × 맥락)이다.

명백한 건 규칙으로 빠르게 가르고(thinker 비용 0), 회색지대만 thinker 가 맥락으로 판정.
"""
from __future__ import annotations

from ...ports.thinker import Thinker
from ...prompts import templates

# 명백히 가역 — 자유 탐색(읽기/검색/계획). 포크해도 공짜.
REVERSIBLE_TOOLS = {
    "Read", "Grep", "Glob", "LS", "NotebookRead",
    "WebFetch", "WebSearch", "TodoWrite",
}

# 파괴적 Bash 패턴(비가역 신호) / 안전 Bash 패턴(가역 신호)
_BASH_IRREVERSIBLE = (
    "rm ", "rm -", "mv ", "git push", "git commit", "gh ", "curl -x post", "curl -x put",
    "curl -x delete", "-d '", "--data", "deploy", "npm publish", "pip install",
    "npm install", "drop ", "delete from", "truncate", "> ", ">>", "kill ", "shutdown",
    "chmod", "chown", "scp ", "rsync",
)
_BASH_REVERSIBLE = (
    "ls", "cat ", "grep", "find ", "git status", "git log", "git diff", "git show",
    "echo ", "pwd", "head ", "tail ", "wc ", "which ", "stat ", "python -m compileall",
)

# MCP 도구 동사 휴리스틱(이름 기반): 읽기 동사 = 가역, 변경/발신 동사 = 비가역.
_MCP_READ_VERBS = ("get", "list", "search", "query", "read", "fetch", "describe", "show")
_MCP_WRITE_VERBS = ("send", "create", "post", "update", "delete", "publish", "write",
                    "add", "remove", "set", "upload", "merge", "close", "comment")


def classify_action(tool: str, *, isolated: bool = False, command: str = "") -> str:
    """한 행동 → "reversible" | "irreversible" | "ambiguous". 규칙 빠른 길.

    isolated: 격리 worktree 등 '버릴 수 있는' 곳에서 일어나면 파일 변경도 가역.
    command: Bash 의 실제 명령(가역/파괴 패턴 매칭용).
    """
    if tool in REVERSIBLE_TOOLS:
        return "reversible"

    if tool in ("Write", "Edit", "NotebookEdit"):
        # 같은 Edit 이라도 격리 worktree 면 버리면 그만 → 가역.
        return "reversible" if isolated else "irreversible"

    if tool == "Bash":
        c = command.lower().strip()
        if any(p in c for p in _BASH_IRREVERSIBLE):
            return "irreversible"
        if any(c.startswith(p) or f" {p}" in c for p in _BASH_REVERSIBLE):
            return "reversible"
        return "ambiguous"

    if tool.startswith("mcp__"):
        name = tool.lower()
        if any(v in name for v in _MCP_WRITE_VERBS):
            return "irreversible"   # 외부 시스템 변경/발신
        if any(v in name for v in _MCP_READ_VERBS):
            return "reversible"
        return "ambiguous"          # 모르는 MCP → 신중히(thinker 판정)

    return "ambiguous"


async def classify_commits(
    actions: list[dict], thinker: Thinker, *, isolated: bool = False
) -> list[dict]:
    """행동 목록 → 게이트가 필요한 '비가역' 행동만. 규칙 우선, 회색지대만 thinker.

    actions: [{tool, command?, target?}] 형태(워커 계획/툴유즈에서 추출).
    반환: [{action, why}] — 커밋 직전에 사람에게 올릴 게이트 항목.
    규칙으로 비가역 확정된 것 + thinker 가 비가역이라 판정한 회색지대.
    """
    gates: list[dict] = []
    ambiguous: list[dict] = []
    for a in actions:
        verdict = classify_action(
            a.get("tool", ""), isolated=isolated, command=a.get("command", "")
        )
        if verdict == "irreversible":
            gates.append({"action": _label(a), "why": "규칙상 비가역(외부/덮어쓰기/삭제)"})
        elif verdict == "ambiguous":
            ambiguous.append(a)

    if ambiguous:
        try:
            judged = await _judge_ambiguous(ambiguous, thinker, isolated)
        except Exception:
            # thinker 실패 시 안전쪽(회색지대는 비가역으로 간주 → 게이트)으로.
            judged = [{"action": _label(a), "why": "판정 실패 — 안전상 게이트"} for a in ambiguous]
        gates.extend(judged)
    return gates


def _label(a: dict) -> str:
    t = a.get("tool", "?")
    detail = a.get("command") or a.get("target") or ""
    return f"{t}: {detail}".strip().rstrip(":") if detail else t


async def _judge_ambiguous(actions: list[dict], thinker: Thinker, isolated: bool) -> list[dict]:
    block = "\n".join(f"- {_label(a)}" for a in actions)
    out = await thinker.think(
        templates.REVERSIBILITY_JUDGE.format(
            env=("격리됨(버릴 수 있음)" if isolated else "실제 환경"), actions=block
        ),
        system=templates.SYSTEM_MANAGER,
        schema=templates.REVERSIBILITY_SCHEMA,
    )
    items = out.get("irreversible", []) if isinstance(out, dict) else []
    res = []
    for it in items:
        if isinstance(it, dict) and (it.get("action") or "").strip():
            res.append({"action": it["action"].strip(), "why": (it.get("why") or "").strip()})
    return res
