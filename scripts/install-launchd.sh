#!/bin/bash
# SOPHIA 하루 주행을 launchd 로 등록 — 매일 09/13/17시(로컬)에 daily.py 1라운드.
# read_only + --max-week-pct 안전 가드. mail.env 가 있으면 메일, 없으면 파일로 폴백.
#
#   bash scripts/install-launchd.sh            # 설치 + 로드
#   bash scripts/install-launchd.sh --uninstall
set -e

PLIST="$HOME/Library/LaunchAgents/com.sophia.daily.plist"

if [ "$1" = "--uninstall" ]; then
  launchctl unload "$PLIST" 2>/dev/null || true
  rm -f "$PLIST"
  echo "제거됨: $PLIST"
  exit 0
fi

PY="$(command -v python3)"
REPO="$(cd "$(dirname "$0")/.." && pwd)"
LOG="$HOME/.sophia/daily.log"
MAXWEEK="${SOPHIA_MAX_WEEK_PCT:-60}"   # 주간 quota 이 % 이상이면 라운드 스킵
mkdir -p "$HOME/.sophia" "$HOME/Library/LaunchAgents"

[ -z "$PY" ] && { echo "✗ python3 를 못 찾음"; exit 1; }

CMD="source \"$HOME/.sophia/mail.env\" 2>/dev/null; \"$PY\" \"$REPO/scripts/daily.py\" --stamp \"\$(date +%FT%H:%M)\" --max-week-pct $MAXWEEK >> \"$LOG\" 2>&1"
# plist 는 XML — &, <, > 를 이스케이프해야 valid (CMD 에 >>, 2>&1, & 가 들어감).
CMD_XML="$(printf '%s' "$CMD" | sed 's/&/\&amp;/g; s/</\&lt;/g; s/>/\&gt;/g')"

cat > "$PLIST" <<PLIST_EOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key><string>com.sophia.daily</string>
  <key>ProgramArguments</key>
  <array>
    <string>/bin/bash</string>
    <string>-lc</string>
    <string>$CMD_XML</string>
  </array>
  <key>StartCalendarInterval</key>
  <array>
    <dict><key>Hour</key><integer>9</integer><key>Minute</key><integer>0</integer></dict>
    <dict><key>Hour</key><integer>13</integer><key>Minute</key><integer>0</integer></dict>
    <dict><key>Hour</key><integer>17</integer><key>Minute</key><integer>0</integer></dict>
  </array>
  <key>StandardOutPath</key><string>$LOG</string>
  <key>StandardErrorPath</key><string>$LOG</string>
  <key>RunAtLoad</key><false/>
</dict>
</plist>
PLIST_EOF

launchctl unload "$PLIST" 2>/dev/null || true
launchctl load "$PLIST"
echo "설치됨: $PLIST"
echo "  실행: 매일 09/13/17시 · 주간 quota ${MAXWEEK}% 상한 · 로그 $LOG"
echo "  지금 한 번 테스트:  launchctl start com.sophia.daily  (그 뒤 tail -f $LOG)"
echo "  제거:  bash scripts/install-launchd.sh --uninstall"
