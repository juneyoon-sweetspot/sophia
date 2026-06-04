#!/bin/bash
# SOPHIA 세션-안 자율 루프 — 인증된 터미널에서 돌린다.
#
# 왜 이게 필요한가: 무인 launchd 는 claude 로그인 토큰(login keychain 의
# 'Claude Code-credentials')에 접근하려다 GUI 프롬프트에 막혀 hang 한다. 그래서
# claude 가 이미 로그인된 '세션 안'에서 돌리는 게 현실적 자율 방법이다(keychain 닿음).
#
# 실행 방법(셋 중 하나):
#   bash scripts/run-loop.sh                              # 포그라운드(이 터미널 떠있는 동안)
#   nohup bash scripts/run-loop.sh >> ~/.sophia/loop.log 2>&1 &   # 터미널 닫아도 유지(로그아웃 전까지)
#   (cmux/tmux 패널에서 띄워두고 그 세션 유지)
#
# 환경변수: SOPHIA_INTERVAL_S(기본 10800=3h), SOPHIA_MAX_WEEK_PCT(기본 60)
# 종료: Ctrl-C  ·  로그/다이제스트: ~/.sophia/
set -u
DIR="$(cd "$(dirname "$0")/.." && pwd)"
INTERVAL="${SOPHIA_INTERVAL_S:-10800}"
MAXWEEK="${SOPHIA_MAX_WEEK_PCT:-60}"

# 이 세션에서 claude 가 실제 인증돼 있는지 먼저 확인(아니면 헛돌므로 즉시 중단).
if ! claude -p "ok" --output-format json --model haiku >/dev/null 2>&1; then
  echo "✗ 이 세션에서 claude 인증이 안 됩니다."
  echo "  'claude' 가 로그인된 터미널(예: 평소 쓰는 cmux/Terminal)에서 실행하세요."
  echo "  확인:  claude -p \"ok\""
  exit 1
fi

echo "▶ SOPHIA 세션-안 루프 시작 — ${INTERVAL}s 간격 · 주간 ${MAXWEEK}% 상한 · Ctrl-C 종료"
while true; do
  echo "=== 라운드 $(date '+%Y-%m-%d %H:%M') ==="
  python3 "$DIR/scripts/daily.py" --stamp "$(date +%FT%H:%M)" --max-week-pct "$MAXWEEK" \
    || echo "(라운드 실패 — 다음으로)"
  echo "--- 다음 라운드까지 ${INTERVAL}s 대기 ---"
  sleep "$INTERVAL"
done
