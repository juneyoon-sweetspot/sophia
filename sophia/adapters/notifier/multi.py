"""MultiNotifier — 여러 채널로 팬아웃. 이메일 주채널 + 파일 폴백 조합용.

send() 는 모든 자식에 보내고, '하나라도 성공하면 True'. 이메일이 죽어도 파일이
받으면 다이제스트는 보존된다. 한 채널의 예외가 다른 채널을 막지 않는다.
"""
from __future__ import annotations

from ...ports.notifier import Notifier


class MultiNotifier(Notifier):
    def __init__(self, *children: Notifier) -> None:
        self.children = [c for c in children if c is not None]

    def send(self, subject: str, body: str) -> bool:
        ok = False
        for c in self.children:
            try:
                ok = c.send(subject, body) or ok
            except Exception:
                pass  # 한 채널 실패가 나머지를 막지 않는다
        return ok
