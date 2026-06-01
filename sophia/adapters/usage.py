"""Usage 리더 — Claude Code 의 /usage 패널을 긁어 '실제 세션/주간 사용 %'를 얻는다.

headless `claude -p "/usage"` 는 숫자를 안 준다(한 문장만). 그래서 인터랙티브 세션을
PTY 로 띄워 /usage 를 보내고 렌더된 화면을 스크랩한다. 그 자체는 모델 호출이 아니라
quota 를 거의 안 먹는다(세션 usage 0).

순수 파서(parse_usage)와 PTY 드라이버(read_usage)를 분리 — 파서는 단위 검증,
PTY 부분은 라이브 검증(실제 claude 필요, 포맷/타이밍에 취약).
"""
from __future__ import annotations

import os
import re
from dataclasses import dataclass
from pathlib import Path


@dataclass
class Usage:
    ok: bool
    mode: str                      # "subscription" | "api" | "unknown"
    session_pct: int | None = None
    week_pct: int | None = None
    raw: str = ""


def detect_mode(home: str | Path | None = None) -> str:
    """API 키 vs 구독 인증 판별. /usage 단위($ vs %)를 고르는 데 쓴다."""
    if os.environ.get("ANTHROPIC_API_KEY"):
        return "api"
    p = Path(home or Path.home()) / ".claude.json"
    try:
        import json
        d = json.loads(p.read_text(encoding="utf-8"))
        if d.get("oauthAccount"):
            return "subscription"
    except Exception:
        pass
    return "unknown"


def parse_usage(text: str, mode: str = "unknown") -> Usage:
    """/usage 스크랩 텍스트 → 세션/주간 %. 공백을 모두 죽이고 'N%used' 앵커로 잡는다."""
    low = re.sub(r"\s+", "", text.lower())

    def pct(anchor: str) -> int | None:
        m = re.search(anchor + r".*?(\d+)%used", low)
        return int(m.group(1)) if m else None

    session = pct("currentsession")
    week = pct("currentweek")
    ok = session is not None or week is not None
    return Usage(ok=ok, mode=mode, session_pct=session, week_pct=week, raw=text)


def read_usage(
    claude_bin: str = "claude",
    *, boot_s: float = 8.0, panel_s: float = 7.0,
) -> Usage:
    """인터랙티브 claude 를 PTY 로 띄워 /usage 를 스크랩 → Usage. 실패 시 ok=False.

    라이브 전용(실제 claude CLI 필요). 포맷/타이밍 취약 — 빈손이면 호출자가 재시도.
    """
    import pty
    import select
    import signal
    import subprocess
    import time

    mode = detect_mode()
    try:
        master, slave = os.openpty()
    except OSError:
        return Usage(ok=False, mode=mode)
    os.set_blocking(master, False)
    try:
        proc = subprocess.Popen(
            [claude_bin], stdin=slave, stdout=slave, stderr=slave,
            preexec_fn=os.setsid, close_fds=True,
        )
    except Exception:
        os.close(master); os.close(slave)
        return Usage(ok=False, mode=mode)
    os.close(slave)
    buf = bytearray()

    def pump(secs: float) -> None:
        end = time.monotonic() + secs
        while time.monotonic() < end:
            r, _, _ = select.select([master], [], [], 0.3)
            if r:
                try:
                    buf.extend(os.read(master, 65536))
                except OSError:
                    break

    try:
        pump(boot_s)
        os.write(master, b"/usage\r")
        pump(panel_s)
    except OSError:
        pass
    finally:
        try:
            os.killpg(os.getpgid(proc.pid), signal.SIGKILL)
        except Exception:
            pass
        try:
            os.close(master)
        except OSError:
            pass

    text = buf.decode("utf-8", "replace")
    text = re.sub(r"\x1b\[[0-9;?]*[a-zA-Z]", "", text)
    text = re.sub(r"\x1b\][^\x07]*\x07", "", text)
    text = re.sub(r"\x1b[=>]", "", text)
    text = re.sub(r"[\x00-\x08\x0b-\x1f]", "", text)
    return parse_usage(text, mode)
