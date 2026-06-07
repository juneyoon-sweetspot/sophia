#!/bin/bash
# SOPHIA 밤샘 루프 — "켜두고 퇴근하면 밤새 돈다". 인간=낮, AI=밤(같은 로그인 세션).
#
# 왜 launchd 가 아니라 이건가: 무인 launchd 는 claude 로그인 토큰(login keychain)에
# 접근하려다 GUI 프롬프트에 막혀 hang 한다. 이 루프는 '당신이 로그인한 세션' 안에서 돌아
# keychain 이 닿는다. 컴이 켜져 있고 로그인돼 있으면 자리 비워도(밤새) 돈다.
#
# 시작(터미널 닫아도 유지):
#   nohup bash scripts/run-loop.sh start >> ~/.sophia/loop.log 2>&1 &
#   bash scripts/run-loop.sh start          # 포그라운드(이 터미널 동안)
# 중지/상태:
#   bash scripts/run-loop.sh stop
#   bash scripts/run-loop.sh status
#
# 전제(유저 책임): 컴 안 꺼짐(잠자기 끄기/caffeinate) · 로그인 유지 · keychain 잠금 안 됨.
#   재부팅·로그아웃하면 멈춤 → 다시 'start'.
# 환경변수: SOPHIA_INTERVAL_S(기본 10800=3h, adaptive fallback) · SOPHIA_DAILY_PCT(기본 20) ·
#           SOPHIA_MAX_WEEK_PCT(기본 60) · SOPHIA_AWAY_THRESHOLD_S(기본 3600) ·
#           SOPHIA_NIGHT_END_H(기본 9) · SOPHIA_PP_PER_ROUND(기본 4.0) · SOPHIA_DAY_INTERVAL_S(기본 7200)
set -u
DIR="$(cd "$(dirname "$0")/.." && pwd)"
PIDFILE="$HOME/.sophia/loop.pid"
INTERVAL="${SOPHIA_INTERVAL_S:-10800}"
DAILY="${SOPHIA_DAILY_PCT:-20}"
MAXWEEK="${SOPHIA_MAX_WEEK_PCT:-60}"
ROUND_TIMEOUT="${SOPHIA_ROUND_TIMEOUT_S:-1200}"   # 한 라운드 상한(stall 방어) 기본 20분
mkdir -p "$HOME/.sophia"

# 한 라운드를 watchdog 으로 감싸 실행 — stall(예: /usage PTY 멈춤)해도 밤 전체가 안 얼게.
_run_round() {
  python3 "$DIR/scripts/daily.py" --stamp "$(date +%FT%H:%M)" \
    --daily-pct "$DAILY" --max-week-pct "$MAXWEEK" &
  local rpid=$! waited=0
  while kill -0 "$rpid" 2>/dev/null; do
    if [ "$waited" -ge "$ROUND_TIMEOUT" ]; then
      echo "(라운드 ${ROUND_TIMEOUT}s 초과 → 강제 종료, 다음으로)"
      kill -9 "$rpid" 2>/dev/null
      pkill -9 -f -- "--strict-mcp-config" 2>/dev/null   # 멈춘 SOPHIA read_only 워커 정리
      break
    fi
    sleep 10; waited=$((waited+10))
  done
}

cmd="${1:-start}"

_running() { [ -f "$PIDFILE" ] && kill -0 "$(cat "$PIDFILE" 2>/dev/null)" 2>/dev/null; }

case "$cmd" in
  stop)
    if _running; then kill "$(cat "$PIDFILE")" && echo "중지됨 (pid $(cat "$PIDFILE"))"; rm -f "$PIDFILE"
    else echo "도는 루프 없음"; rm -f "$PIDFILE"; fi
    exit 0 ;;
  status)
    if _running; then echo "도는 중 (pid $(cat "$PIDFILE")) · 간격 adaptive (fallback ${INTERVAL}s) · 예산 ${DAILY}pp/일"
    else echo "안 도는 중"; fi
    exit 0 ;;
  start) : ;;
  *) echo "사용: run-loop.sh [start|stop|status]"; exit 1 ;;
esac

# 단일 인스턴스 — 이미 돌면 거절(밤새 중복 실행 = quota 2배 방지).
if _running; then echo "✗ 이미 도는 중 (pid $(cat "$PIDFILE")). 'stop' 후 재시작."; exit 1; fi

# 이 세션에서 claude 인증 확인(아니면 밤새 헛돔 → 즉시 중단).
if ! claude -p "ok" --output-format json --model haiku >/dev/null 2>&1; then
  echo "✗ 이 세션에서 claude 인증 안 됨. 'claude' 로그인된 터미널에서 실행하세요(claude -p \"ok\" 로 확인)."
  exit 1
fi

echo $$ > "$PIDFILE"
trap 'rm -f "$PIDFILE"; echo "루프 종료 $(date)"; exit 0' INT TERM

echo "▶ SOPHIA 밤샘 루프 시작 (pid $$) — ${INTERVAL}s 간격 · 하루 ${DAILY}pp 예산 · 주간 ${MAXWEEK}% 천장"
echo "  전제: 컴 안 꺼짐 + 로그인 유지. stop: run-loop.sh stop"
while _running; do   # PIDFILE 사라지면(stop) 루프 종료
  echo "=== 라운드 $(date '+%m-%d %H:%M') ==="
  _run_round
  # 다음 간격은 적응형(자리 비움 + 남은 예산÷남은 야간)으로 산정. 실패/오염 시 고정 간격 폴백.
  NEXT_S=$(python3 "$DIR/scripts/interval.py" --daily-pct "$DAILY" 2>/dev/null || echo "$INTERVAL")
  [[ "$NEXT_S" =~ ^[0-9]+$ ]] || NEXT_S="$INTERVAL"   # stdout 오염 방어
  echo "--- 다음 라운드까지 ${NEXT_S}s 대기 (adaptive) ---"
  sleep "$NEXT_S"
done
rm -f "$PIDFILE"
