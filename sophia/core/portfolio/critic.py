"""Critic — 다이제스트에 올리기 전 단일 blocker question 을 분류한다.

순수 함수 모듈. `re` + `typing` stdlib only. digest.py 와 독립.

목적: 프롬프트(BLOCKERS_DERIVE) 가 1차로 막지 못한 두 종류의 잡음을 방어한다.
 - 코드용어·파일명 도배 → flagged ([⚠기술용어] prefix)
 - AI 가 정해야 할 해석/범위/접근법 질문을 사람에게 떠넘김 → excluded (표시 안 함)

예외 시 항상 'ok' 로 폴백한다(safe default = 표시하는 방향).
"""
import re
from typing import Literal

# 코드 냄새 패턴: 파일확장자, 메서드호출, 절대경로
_CODE_PATTERN = re.compile(
    r'\b\w+\.(py|ts|js|json|yaml|yml|sh|md|sql|html|css|env)\b'
    r'|\.\w+\('
    r'|/[\w/\-.]+/[\w\-.]+',
    re.IGNORECASE,
)

# 해석/범위 질문 패턴 (AI 가 정해야 할 것을 사람에게 떠넘기는 패턴)
# 주의: '어떤 팀에 승인을' 같은 합법적 블로커와 구분하기 위해
#       '어떤' 단독이 아닌 '어떤 + 접근법 명사' 복합 패턴으로 한정
_INTERP_PATTERN = re.compile(
    r'어떤\s*(방법|방식|전략|접근법?|순서|식으로)'
    r'|어떻게\s*(접근|처리|구현|실현|구성|시작|진행|할지)'
    r'|어디서?부터'
    r'|무엇부터'
    r'|어느\s*(방향|시점|단계|순서)'
    r'|how\s+to\b'
    r'|which\s+(approach|method|strategy)\b',
    re.IGNORECASE,
)

CriticLabel = Literal["ok", "flagged", "excluded"]


def classify_blocker(question: str) -> CriticLabel:
    """단일 blocker question 분류.

    ok       → 다이제스트에 그대로 표시
    flagged  → [⚠기술용어] prefix 붙여 표시 (코드용어 감지)
    excluded → 표시하지 않음 (해석/범위 질문)

    예외 시 항상 'ok' 반환 (safe default = 표시하는 방향).
    판정 우선순위: excluded > flagged > ok
    """
    if not question or not question.strip():
        return "ok"
    try:
        if _INTERP_PATTERN.search(question):
            return "excluded"
        if _CODE_PATTERN.search(question):
            return "flagged"
    except Exception:
        return "ok"
    return "ok"
