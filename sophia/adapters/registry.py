"""Tracked-projects 레지스트리 — 사람이 '이건 내 프로젝트다' 수동 등록.

auto-import 는 추측일 뿐이다(사용량 top cwd ≠ 내가 관리하는 프로젝트 — 실증에서 드러남).
사람이 명시적으로 cwd 를 track 하면 그게 포트폴리오의 진실이 된다. SOPHIA 원칙과 일치:
매니저는 후보를 잘 설명하고, 어느 게 '내 프로젝트'인지는 본부장이 정한다.

작은 JSON 파일(~/.sophia/tracked.json)에 영속. note 로 '이게 뭐였는지'를 사람이 적어둘 수 있다.
"""
from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from pathlib import Path

DEFAULT_PATH = Path.home() / ".sophia" / "tracked.json"


@dataclass
class Tracked:
    cwd: str
    note: str = ""          # 사람이 적는 한 줄(이게 뭐였는지)
    added_at: str = ""      # 호출자가 채워 넣음(여기선 시간 안 만든다 — 결정성)


@dataclass
class Registry:
    items: list[Tracked] = field(default_factory=list)

    def cwds(self) -> list[str]:
        return [t.cwd for t in self.items]

    def is_tracked(self, cwd: str) -> bool:
        return any(t.cwd == cwd for t in self.items)

    def track(self, cwd: str, note: str = "", added_at: str = "") -> bool:
        """등록. 이미 있으면 note 갱신하고 False, 새로 추가하면 True."""
        for t in self.items:
            if t.cwd == cwd:
                if note:
                    t.note = note
                return False
        self.items.append(Tracked(cwd=cwd, note=note, added_at=added_at))
        return True

    def untrack(self, cwd: str) -> bool:
        """해제. 있었으면 True."""
        before = len(self.items)
        self.items = [t for t in self.items if t.cwd != cwd]
        return len(self.items) != before

    def save(self, path: str | Path = DEFAULT_PATH) -> None:
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            json.dumps({"items": [asdict(t) for t in self.items]},
                       ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

    @classmethod
    def load(cls, path: str | Path = DEFAULT_PATH) -> "Registry":
        path = Path(path)
        if not path.exists():
            return cls()
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            return cls(items=[Tracked(**d) for d in data.get("items", [])])
        except Exception:
            return cls()  # 손상된 레지스트리로 죽지 않는다
