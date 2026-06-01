"""Gmail 다이제스트 채널 초기화 — 설정 → 테스트 메일 실발송 → 도착 확인.

Gmail 은 일반 비밀번호로 SMTP 로그인이 안 된다. 2단계 인증을 켜고 '앱 비밀번호'(16자)를
발급해야 한다:  Google 계정 → 보안 → 2단계 인증 → 앱 비밀번호.

  python3 scripts/gmail_setup.py --user me@gmail.com --to me@gmail.com --app-password "abcd efgh ijkl mnop"

성공하면 ~/.sophia/mail.env 에 설정을 저장한다(앱 비밀번호 포함 — 본인 머신 전용).
이후 러너가 이걸 읽어 SOPHIA_SMTP_* 로 쓴다. 테스트 메일이 안 오면 설정이 틀린 것.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sophia.adapters.notifier.email_smtp import EmailNotifier  # noqa: E402

ENV_PATH = Path.home() / ".sophia" / "mail.env"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--user", required=True, help="Gmail 주소(SMTP 로그인)")
    ap.add_argument("--to", required=True, help="다이제스트 받을 주소")
    ap.add_argument("--app-password", required=True, help="Gmail 앱 비밀번호(16자)")
    ap.add_argument("--host", default="smtp.gmail.com")
    ap.add_argument("--port", default="587")
    args = ap.parse_args()

    pw = args.app_password.replace(" ", "")  # 앱 비번은 공백 무시
    notifier = EmailNotifier(
        host=args.host, port=args.port, user=args.user, password=pw,
        mail_from=args.user, mail_to=args.to,
    )
    print(f"테스트 메일 발송 시도: {args.user} → {args.to} via {args.host}:{args.port} …")
    ok = notifier.send(
        "[SOPHIA] 채널 초기화 테스트",
        "이 메일이 보이면 Gmail 다이제스트 채널이 정상입니다.\n"
        "이후 SOPHIA 가 하루 다이제스트를 이 주소로 보냅니다.",
    )
    if not ok:
        print("✗ 발송 실패. 점검:")
        print("  - 앱 비밀번호(일반 비번 아님)인지, 2단계 인증 켜졌는지")
        print("  - 주소/포트(smtp.gmail.com:587) 오타")
        return 1

    ENV_PATH.parent.mkdir(parents=True, exist_ok=True)
    ENV_PATH.write_text(
        "\n".join([
            f"export SOPHIA_SMTP_HOST={args.host}",
            f"export SOPHIA_SMTP_PORT={args.port}",
            f"export SOPHIA_SMTP_USER={args.user}",
            f"export SOPHIA_SMTP_PASS={pw}",
            f"export SOPHIA_MAIL_FROM={args.user}",
            f"export SOPHIA_MAIL_TO={args.to}",
            "",
        ]),
        encoding="utf-8",
    )
    print(f"✓ 발송 성공. 받은편지함 확인하세요. 설정 저장: {ENV_PATH}")
    print(f"  러너 실행 전:  source {ENV_PATH}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
