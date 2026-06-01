"""Claude Code 세션 임포터 — ~/.claude/projects 트랜스크립트를 SOPHIA Project 로.

기존 클로드 세션을 '들고 와서 관리'하는 브리지. 단, 세션을 *이어가는* 게 아니다.
각 작업 디렉토리(cwd)의 가장 최근 세션에서 '의도(goal)'와 마지막 진행점을 추출해
Portfolio 가 전진시킬 Project 로 만든다 — 즉 세션 인계가 아니라 '의도 추출 후 재구동'.

설계:
- cwd 는 디렉토리명 인코딩(`-Users-...`)이 아니라 jsonl 안의 `cwd` 필드에서 읽는다
  (디렉토리명은 경로 구분자/하이픈이 뭉개져 복원이 손실적이다).
- 한 cwd 에 세션이 여러 개면 *가장 최근* 세션을 그 프로젝트의 대표로 본다
  (그 디렉토리에서 '지금 진행 중인 작업 줄기').
- 슬래시 커맨드/시스템 캡션/로컬 stdout 같은 노이즈 user 라인은 goal 후보에서 거른다.
- 순수 읽기. 트랜스크립트를 변형하지 않는다.
"""
from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from pathlib import Path

from ..core.portfolio.project import Project

DEFAULT_ROOT = Path.home() / ".claude" / "projects"

# goal/의도로 쓰기엔 노이즈인 user 라인 프리픽스(슬래시커맨드·하네스 주입·로컬 출력).
_NOISE_PREFIXES = ("<", "[Request interrupted", "Caveat:", "/")


@dataclass
class SessionInfo:
    """한 세션 트랜스크립트에서 뽑은 요약(임포트 판단/표시용)."""
    cwd: str
    session_id: str
    first_user_text: str
    last_user_text: str
    mtime: float
    n_user_msgs: int


def _user_texts(path: Path):
    """트랜스크립트에서 (cwd, 실질 user 텍스트)를 순서대로 흘린다. 노이즈는 건너뜀."""
    try:
        fh = path.open(encoding="utf-8")
    except OSError:
        return
    with fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            try:
                d = json.loads(line)
            except json.JSONDecodeError:
                continue
            if d.get("type") != "user":
                continue
            content = d.get("message", {}).get("content")
            if isinstance(content, str):
                txt = content
            elif isinstance(content, list):
                txt = " ".join(
                    b.get("text", "")
                    for b in content
                    if isinstance(b, dict) and b.get("type") == "text"
                )
            else:
                txt = ""
            txt = txt.strip()
            if not txt or txt.startswith(_NOISE_PREFIXES):
                continue
            yield d.get("cwd"), txt


def read_session(path: str | Path) -> SessionInfo | None:
    """한 세션 jsonl → SessionInfo. 실질 user 메시지가 하나도 없으면 None."""
    path = Path(path)
    cwd = ""
    first = last = None
    n = 0
    for c, txt in _user_texts(path):
        n += 1
        if not cwd and c:
            cwd = c
        if first is None:
            first = txt
        last = txt
    if first is None:
        return None
    try:
        mtime = os.stat(path).st_mtime
    except OSError:
        mtime = 0.0
    return SessionInfo(
        cwd=cwd, session_id=path.stem, first_user_text=first,
        last_user_text=last or first, mtime=mtime, n_user_msgs=n,
    )


def scan_sessions(root: str | Path = DEFAULT_ROOT) -> list[SessionInfo]:
    """projects 루트 아래 모든 세션을 읽어 SessionInfo 리스트(최신순)로."""
    root = Path(root)
    out: list[SessionInfo] = []
    if not root.exists():
        return out
    for jf in root.rglob("*.jsonl"):
        si = read_session(jf)
        if si is not None:
            out.append(si)
    out.sort(key=lambda s: s.mtime, reverse=True)
    return out


def _slug(cwd: str) -> str:
    """cwd → 짧은 프로젝트 id (마지막 경로 조각)."""
    base = cwd.rstrip("/").rsplit("/", 1)[-1] or "root"
    return base


@dataclass
class CwdGroup:
    """한 cwd 로 묶인 세션들의 집계. latest 가 goal 의 대표."""
    cwd: str
    latest: SessionInfo
    n_sessions: int = 0
    total_user_msgs: int = 0  # 그 cwd 에서 누적된 작업량(사용량 랭킹 키)


def group_by_cwd(
    root: str | Path = DEFAULT_ROOT,
    *,
    exclude_cwds: set[str] | None = None,
) -> list[CwdGroup]:
    """모든 세션을 cwd 별로 묶어 집계. cwd 당 최신 세션 + 누적 사용량."""
    exclude = exclude_cwds or set()
    groups: dict[str, CwdGroup] = {}
    for si in scan_sessions(root):
        if not si.cwd or si.cwd in exclude:
            continue
        g = groups.get(si.cwd)
        if g is None:
            groups[si.cwd] = CwdGroup(
                cwd=si.cwd, latest=si, n_sessions=1, total_user_msgs=si.n_user_msgs
            )
        else:
            g.n_sessions += 1
            g.total_user_msgs += si.n_user_msgs
            if si.mtime > g.latest.mtime:  # scan 은 최신순이라 보통 첫 게 latest
                g.latest = si
    return list(groups.values())


def import_projects(
    root: str | Path = DEFAULT_ROOT,
    *,
    min_user_msgs: int = 2,
    exclude_cwds: set[str] | None = None,
    handoff_dir: str | Path = "/tmp/sophia_sessions",
    rank: str = "recency",     # "recency"(최신순) | "usage"(누적 사용량순)
    top: int | None = None,    # 상위 N 개만 (예: 사용량 top 5)
    only_cwds: set[str] | None = None,  # 주면 이 cwd 들만 임포트(사용자 선택)
) -> list[Project]:
    """세션들을 cwd 별로 묶어 Project 리스트로. cwd 당 가장 최근 세션이 goal 대표.

    min_user_msgs: 누적 user 메시지가 이보다 적은(=잡담/일회성) cwd 는 건너뛴다.
    exclude_cwds: 임포트에서 뺄 cwd 절대경로 집합(잡동사니 Desktop/Downloads 등).
    only_cwds:    주면 *이 cwd 들만* (사용자가 전체 스캔에서 고른 경우).
    rank:         "recency"=최신 작업 우선, "usage"=누적 작업량 우선.
    top:          상위 N 개만 가져온다(예: 사용량 top 5).
    handoff_dir:  프로젝트별 handoff.json 을 둘 디렉토리(cwd 당 1파일, 충돌 방지).
    """
    groups = group_by_cwd(root, exclude_cwds=exclude_cwds)
    if only_cwds is not None:
        groups = [g for g in groups if g.cwd in only_cwds]
    groups = [g for g in groups if g.total_user_msgs >= min_user_msgs]

    key = (lambda g: g.total_user_msgs) if rank == "usage" else (lambda g: g.latest.mtime)
    groups.sort(key=key, reverse=True)
    if top is not None:
        groups = groups[:top]

    handoff_dir = Path(handoff_dir)
    handoff_dir.mkdir(parents=True, exist_ok=True)  # 없으면 핸드오프 저장이 조용히 실패
    projects: list[Project] = []
    for g in groups:
        si = g.latest
        pid = _slug(g.cwd)
        projects.append(
            Project(
                id=pid,
                goal=si.first_user_text,
                handoff_path=str(handoff_dir / f"{pid}.json"),
                # '이어가기'의 자연스러운 지점 = 사람이 마지막으로 시킨 것.
                pending_requests=[si.last_user_text],
                meta={
                    "cwd": g.cwd,
                    "last_session": si.session_id,
                    "n_sessions": g.n_sessions,
                    "total_user_msgs": g.total_user_msgs,
                    "mtime": si.mtime,
                },
            )
        )
    return projects
