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
    이름 우선순위: 세션 제목(/rename 또는 aiTitle) > 첫 지시."""
    now = time.time()
    out = []
    for g in sorted(group_by_cwd(), key=lambda x: x.latest.mtime, reverse=True)[:limit]:
        si = g.latest
        out.append({
            "cwd": g.cwd, "id": Path(g.cwd).name,
            "active": (now - si.mtime) < ACTIVE_WINDOW_S,
            "tracked": g.cwd in tracked_cwds,
            "label": si.title or si.first_user_text, "msgs": g.total_user_msgs,
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
            "goal": t.intent,   # 편집용 raw 목표(비었으면 자동초안/제목 폴백)
            "mode": mode, "decisions": [b.get("question", "") for b in blockers],
        })
    return {
        "loop": _loop_state(), "budget": _budget_state(),
        "projects": projects, "digest": _latest_digest(),
        "candidates": _candidates(tracked_cwds),
    }


def _handle_track(selected: set) -> None:
    """체크된 세션 track / 보였는데 해제된 건 untrack. 새로 선택된 건 목표 자동초안."""
    reg = Registry.load()
    titles = {c["cwd"]: c["label"] for c in _candidates(set(reg.cwds()))}
    shown = set(titles)
    for cwd in selected:
        reg.track(cwd, note=(titles.get(cwd, "") or "")[:80])
    for cwd in list(reg.cwds()):
        if cwd in shown and cwd not in selected:
            reg.untrack(cwd)
    reg.save()
    _draft_missing_goals(reg)


def _handle_goal(cwd: str, intent: str) -> None:
    """카드에서 편집한 목표 한 줄을 레지스트리 intent 에 저장(워커 방향)."""
    reg = Registry.load()
    if not any(t.cwd == cwd for t in reg.items):
        reg.track(cwd)
    for t in reg.items:
        if t.cwd == cwd:
            t.intent = (intent or "").strip()
    reg.save()


def _draft_missing_goals(reg: Registry) -> None:
    """목표(intent) 빈 tracked 프로젝트에 한 줄 자동초안(brief). 세션이 빈약하면 빈약."""
    todo = [t for t in reg.items if not t.intent]
    if not todo:
        return
    import asyncio
    from sophia.adapters.sessions import draft_brief
    from sophia.adapters.thinker.claude_cli import ClaudeCliThinker
    latest = {g.cwd: g.latest for g in group_by_cwd()}
    th = ClaudeCliThinker()
    for t in todo:
        si = latest.get(t.cwd)
        if not si:
            continue
        try:
            b = asyncio.run(draft_brief(si, th))
            t.intent = b.get("intent", "") or t.note
            t.progress = t.progress or b.get("progress", "")
            t.boundaries = t.boundaries or b.get("boundaries", "")
        except Exception:
            pass
    reg.save()


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
          <form method="post" action="/goal" class="goalf">
            <input type="hidden" name="cwd" value="{e(p['cwd'])}">
            <input name="intent" value="{e(p['goal'])}" placeholder="목표 한 줄 (비우면 자동 추론)">
            <button>저장</button>
          </form>
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
.goalf{{display:flex;gap:4px;margin:4px 0}} .goalf input{{flex:1;font-size:12px;padding:4px}}
.goalf button{{margin:0;padding:4px 8px;font-size:11px}}
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
            from urllib.parse import parse_qs
            n = int(self.headers.get("Content-Length", 0))
            form = parse_qs(self.rfile.read(n).decode("utf-8"))
            try:
                if self.path == "/track":
                    _handle_track(set(form.get("cwd", [])))
                elif self.path == "/goal":
                    _handle_goal(form.get("cwd", [""])[0], form.get("intent", [""])[0])
                else:
                    self.send_response(404); self.end_headers(); return
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
