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
import time
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


ACTIVE_WINDOW_S = 3600  # 최근 1시간 내 사용 = 활성(당신이 작업 중)


def _candidates(tracked_cwds: set, limit: int = 30) -> list:
    """로컬 모든 사람 세션 → cwd별 묶어 최근순. 활성배지·tracked여부·이름.
    이름 우선순위: cmux 탭 이름(사람이 단 것) > aiTitle > 첫 지시."""
    from sophia.adapters.cmux import cwd_titles
    cmux = cwd_titles()
    now = time.time()
    out = []
    for g in sorted(group_by_cwd(), key=lambda x: x.latest.mtime, reverse=True)[:limit]:
        si = g.latest
        out.append({
            "cwd": g.cwd, "id": Path(g.cwd).name,
            "active": (now - si.mtime) < ACTIVE_WINDOW_S,
            "tracked": g.cwd in tracked_cwds,
            "label": cmux.get(g.cwd) or si.title or si.first_user_text,
            "msgs": g.total_user_msgs,
        })
    return out


def gather() -> dict:
    reg = Registry.load()
    tracked_cwds = set(reg.cwds())
    latest_mtime = {g.cwd: g.latest.mtime for g in group_by_cwd()}
    projects = []
    for t in reg.items:
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
        "candidates": _candidates(tracked_cwds),
    }


def render(state: dict) -> str:
    e = html.escape
    loop = state["loop"]
    badge = ("🟢 도는 중 (pid %s)" % loop["pid"]) if loop["running"] else "⚪ 안 도는 중"
    b = state["budget"]
    budget_line = (f"오늘({e(str(b.get('date','')))}) 시작 주간 {b.get('start_pct','?')}%"
                   if b else "예산 정보 없음")
    # 세션 브라우저(최근순 · 활성배지 · 체크선택 → SOPHIA 가 굴릴 집합)
    srows = []
    for c in state.get("candidates", []):
        dot = "🟢" if c["active"] else "·"
        chk = "checked" if c["tracked"] else ""
        note = " <span class=act>작업중</span>" if c["active"] else ""
        srows.append(
            f'<label class="srow"><input type="checkbox" name="cwd" value="{e(c["cwd"])}" {chk}>'
            f' {dot} <b>{e(c["id"])}</b>{note} <span class="lbl">{e((c["label"] or "")[:64])}</span>'
            f' <span class="msgs">{c["msgs"]}msg</span></label>')
    browser = (f'<form method="post" action="/track"><div class="srows">{"".join(srows)}</div>'
               f'<button>선택 저장 — SOPHIA 는 이것만 굴림(🟢 작업중은 비켜줌)</button></form>'
               if srows else "<p>세션 없음</p>")

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
.srows{{display:flex;flex-direction:column;gap:2px;margin:8px 0;max-height:280px;overflow:auto}}
.srow{{display:flex;gap:8px;align-items:center;padding:4px 6px;border-radius:6px}}
.srow:hover{{background:#f4f7ff}} .lbl{{color:#666;font-size:12px;flex:1;overflow:hidden;
white-space:nowrap;text-overflow:ellipsis}} .msgs{{color:#aaa;font-size:11px}}
.act{{color:#0a0;font-size:11px}} button{{margin-top:8px;padding:6px 12px;cursor:pointer}}
h2{{font-size:15px;margin-top:24px}}
</style></head><body>
<header><h1>SOPHIA</h1><span>{e(badge)}</span><span class="sub">· {e(budget_line)} · 30s 자동새로고침</span></header>
<h2>🗂 세션 — 이어서 할 것 고르기 (🟢=지금 작업중)</h2>
{browser}
<h2>📂 SOPHIA 가 맡은 프로젝트</h2>
<div class="grid">{''.join(cards) or '<p>아직 선택 안 함 — 위에서 고르세요</p>'}</div>
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

        def do_POST(self):
            if self.path != "/track":
                self.send_response(404); self.end_headers(); return
            try:
                from urllib.parse import parse_qs
                n = int(self.headers.get("Content-Length", 0))
                selected = set(parse_qs(self.rfile.read(n).decode("utf-8")).get("cwd", []))
                reg = Registry.load()
                cands = _candidates(set(reg.cwds()))
                titles = {c["cwd"]: (c["label"] or "") for c in cands}
                shown = set(titles)
                for cwd in selected:                       # 체크된 것 track(제목을 note 로)
                    reg.track(cwd, note=titles.get(cwd, "")[:80])
                for cwd in list(reg.cwds()):               # 보였는데 체크 해제 → untrack
                    if cwd in shown and cwd not in selected:
                        reg.untrack(cwd)
                reg.save()
            except Exception:
                pass
            self.send_response(303); self.send_header("Location", "/"); self.end_headers()

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
