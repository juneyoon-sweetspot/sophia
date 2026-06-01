"""FileNotifier — 다이제스트를 파일에 영속. 이메일의 '폴백' 채널.

이메일이 실패해도(SMTP 오류·오프라인) 다이제스트는 디스크에 남아야 한다. 사람이
"파일은 메일의 폴백"이라 한 그 역할. 날짜별 .md 로 append 한다(하루치가 한 파일에).
"""
from __future__ import annotations

from pathlib import Path

from ...ports.notifier import Notifier


class FileNotifier(Notifier):
    def __init__(self, path: str | Path, stamp: str = "") -> None:
        # path 가 디렉토리면 그 안에 sophia-digest.md, 파일이면 그 파일에 append.
        self.path = Path(path)
        self.stamp = stamp  # 호출자가 타임스탬프 주입(여기선 시간 안 만든다 — 결정성)

    def _target(self) -> Path:
        if self.path.suffix:  # 파일 경로
            return self.path
        return self.path / "sophia-digest.md"  # 디렉토리 → 기본 파일명

    def send(self, subject: str, body: str) -> bool:
        try:
            t = self._target()
            t.parent.mkdir(parents=True, exist_ok=True)
            head = f"\n\n## {subject}" + (f"  ·  {self.stamp}" if self.stamp else "") + "\n\n"
            with t.open("a", encoding="utf-8") as f:
                f.write(head + body + "\n")
            return True
        except Exception:
            return False  # 폴백 채널도 루프를 죽이지 않는다
