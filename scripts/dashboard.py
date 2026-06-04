"""SOPHIA 진행상황 대시보드 — localhost 에서 '지금 상태'를 본다(읽기 전용).

run-loop 이 쓰는 파일(~/.sophia/handoffs, digests, loop.pid, day-budget)을 읽어 렌더만 한다.
순수 stdlib(http.server) · pip 0 · 127.0.0.1 만 바인드(외부 노출 없음) · 30초 자동 새로고침.

  python3 scripts/dashboard.py            # http://127.0.0.1:8787
  python3 scripts/dashboard.py --port 9000
"""
from __future__ import annotations

import argparse
import html
import json
import sys
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sophia.adapters.registry import Registry  # noqa: E402
from sophia.adapters.sessions import group_by_cwd  # noqa: E402
from sophia.core.portfolio.project import project_mode  # noqa: E402
from sophia.core.state.handoff import Handoff  # noqa: E402

SOPHIA = Path.home() / ".sophia"
HANDOFF_DIR = SOPHIA / "handoffs"

_MODE_LABEL = {"progress": "▶ 진전", "groundwork": "↳ 밑작업", "quiet": "· 조용(당신 차례)"}


def _loop_state() -> dict:
    pid = (SOPHIA / "loop.pid").read_text(encoding="utf-8").strip() if (SOPHIA / "loop.pid").exists() else ""
    running = False
    if pid:
        try:
            import os
            os.kill(int(pid), 0)
            running = True
        except Exception:
            running = False
    return {"running": running, "pid": pid}


def _budget_state() -> dict:
    p = SOPHIA / "day-budget.json"
    if not p.exists():
        return {}
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _latest_digest() -> str:
    p = SOPHIA / "digests" / "sophia-digest.md"
    if not p.exists():
        return "(아직 다이제스트 없음)"
    text = p.read_text(encoding="utf-8")
    idx = text.rfind("## [SOPHIA")  # 마지막 다이제스트 블록만
    return text[idx:].strip() if idx != -1 else text[-2000:]


def gather() -> dict:
    latest_mtime = {g.cwd: g.latest.mtime for g in group_by_cwd()}
    projects = []
    for t in Registry.load().items:
        nm = Path(t.cwd).name
        hp = HANDOFF_DIR / f"{nm}.json"
        ho = Handoff.load(hp) if hp.exists() else None
        blockers = (getattr(ho, "blockers", []) or []) if ho else []
        mode = project_mode(
            len(blockers), getattr(ho, "blocked_mtime", 0.0),
            getattr(ho, "groundwork_mtime", 0.0), latest_mtime.get(t.cwd, 0.0),
        )
        projects.append({
            "id": nm, "cwd": t.cwd, "intent": t.intent or t.note or nm,
            "mode": mode, "decisions": [b.get("question", "") for b in blockers],
        })
    return {
        "loop": _loop_state(), "budget": _budget_state(),
        "projects": projects, "digest": _latest_digest(),
    }


def render(state: dict) -> str:
    e = html.escape
    loop = state["loop"]
    badge = ("🟢 도는 중 (pid %s)" % loop["pid"]) if loop["running"] else "⚪ 안 도는 중"
    b = state["budget"]
    budget_line = (f"오늘({e(str(b.get('date','')))}) 시작 주간 {b.get('start_pct','?')}%"
                   if b else "예산 정보 없음")
    cards = []
    for p in state["projects"]:
        decs = "".join(f"<li>{e(q)}</li>" for q in p["decisions"]) or "<li>(없음)</li>"
        cards.append(f"""
        <div class="card">
          <div class="m">{e(_MODE_LABEL.get(p['mode'], p['mode']))}</div>
          <h3>{e(p['id'])} <span class="n">결정 {len(p['decisions'])}</span></h3>
          <div class="i">{e(p['intent'][:90])}</div>
          <ul>{decs}</ul>
        </div>""")
    return f"""<!doctype html><html lang="ko"><head><meta charset="utf-8">
<meta http-equiv="refresh" content="30"><title>SOPHIA</title>
<style>
body{{font:14px/1.5 -apple-system,sans-serif;max-width:900px;margin:24px auto;padding:0 16px;color:#222}}
header{{display:flex;gap:16px;align-items:baseline;border-bottom:1px solid #eee;padding-bottom:8px}}
h1{{font-size:18px;margin:0}} .sub{{color:#888}}
.grid{{display:grid;grid-template-columns:1fr 1fr;gap:12px;margin:16px 0}}
.card{{border:1px solid #e3e3e3;border-radius:8px;padding:12px}}
.card h3{{margin:4px 0;font-size:15px}} .n{{color:#c00;font-weight:normal;font-size:12px}}
.m{{font-size:12px;color:#06c}} .i{{color:#666;font-size:12px;margin-bottom:6px}}
.card ul{{margin:4px 0 0;padding-left:18px}} .card li{{font-size:12px;margin:2px 0}}
pre{{background:#f7f7f7;border-radius:8px;padding:12px;white-space:pre-wrap;font-size:12px}}
</style></head><body>
<header><h1>SOPHIA</h1><span>{e(badge)}</span><span class="sub">· {e(budget_line)} · 30s 자동새로고침</span></header>
<div class="grid">{''.join(cards) or '<p>tracked 프로젝트 없음 — python3 -m sophia track</p>'}</div>
<h2 style="font-size:15px">📬 최신 다이제스트(한 통)</h2>
<pre>{e(state['digest'])}</pre>
</body></html>"""


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, default=8787)
    args = ap.parse_args()

    from http.server import BaseHTTPRequestHandler, HTTPServer

    class H(BaseHTTPRequestHandler):
        def do_GET(self):
            try:
                body = render(gather()).encode("utf-8")
                self.send_response(200)
                self.send_header("Content-Type", "text/html; charset=utf-8")
                self.end_headers()
                self.wfile.write(body)
            except Exception as ex:  # 렌더 실패해도 서버 안 죽게
                self.send_response(500); self.end_headers()
                self.wfile.write(f"error: {ex}".encode("utf-8"))

        def log_message(self, *a):
            pass  # 조용히

    srv = HTTPServer(("127.0.0.1", args.port), H)  # 로컬만 — 외부 노출 없음
    print(f"SOPHIA 대시보드 → http://127.0.0.1:{args.port}  (Ctrl-C 종료)")
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        pass
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
