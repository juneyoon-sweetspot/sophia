"""critic.classify_blocker + digest critic gate 검증 (순수 stdlib, 부작용 0)."""
from sophia.core.portfolio.critic import classify_blocker
from sophia.core.portfolio.digest import build_digest
from sophia.core.portfolio.project import Blocker, Project


def test_ok_questions_pass():
    assert classify_blocker("카카오 계정을 써야 하나요?") == "ok"
    assert classify_blocker("이 프로젝트 대상이 맞나요?") == "ok"
    assert classify_blocker("어떤 팀에 승인을 받아야 하나요?") == "ok"  # 오탐 방지
    assert classify_blocker("tick1 결정거리") == "ok"
    assert classify_blocker("높음") == "ok"
    assert classify_blocker("낮음") == "ok"


def test_code_terms_flagged():
    assert classify_blocker("build.py 수정해야 하나요?") == "flagged"
    assert classify_blocker("manager.get() 호출이 맞나요?") == "flagged"
    assert classify_blocker("/home/user/project/config.json을 바꿔도 되나요?") == "flagged"


def test_interpretation_excluded():
    assert classify_blocker("어떤 접근법이 맞나요?") == "excluded"
    assert classify_blocker("어떻게 구현할지 정해주세요") == "excluded"  # C2
    assert classify_blocker("어떻게 실현할지 모르겠다") == "excluded"  # C2
    assert classify_blocker("어느 방향으로 접근할까요?") == "excluded"  # C1
    assert classify_blocker("어느 시점에 결정해야 할까요?") == "excluded"  # C1
    assert classify_blocker("무엇부터 시작할지 정해주세요") == "excluded"
    assert classify_blocker("어디서부터 시작할지 알려주세요") == "excluded"


def test_empty_safe():
    assert classify_blocker("") == "ok"
    assert classify_blocker("   ") == "ok"


def test_all_excluded_c3():
    """rendered=0, excluded>0 케이스: '결정이 필요한 항목 없음' 포함 확인."""
    p = Project(id="x", goal="목표", blockers=[
        Blocker("x", "어떤 방법으로 구현할까요?", leverage=3)
    ])
    d = build_digest([p], now_tick=0, apply_critic=True)
    assert "결정이 필요한 항목 없음" in d
    assert "자동처리" in d
    assert "어떤 방법으로 구현할까요?" not in d  # excluded


def test_critic_false_fallback():
    """apply_critic=False: excluded 대상도 그대로 출력."""
    p = Project(id="x", goal="목표", blockers=[
        Blocker("x", "어떤 방법으로 구현할까요?", leverage=3)
    ])
    d = build_digest([p], now_tick=0, apply_critic=False)
    assert "어떤 방법으로 구현할까요?" in d

def test_a_or_b_interpretation_excluded():
    # 핵심 케이스
    assert classify_blocker("이 분석의 대상이 mystaff 전체냐 SOPHIA 하나냐?") == "excluded"
    assert classify_blocker("API를 REST로 할지 GraphQL로 할지") == "excluded"   # ~ㄹ지 ~ㄹ지
    assert classify_blocker("기능을 A모듈에 넣을지 B모듈에 넣을지") == "excluded"
    # 기존 오탐 방지 유지
    assert classify_blocker("어떤 팀에 승인을 받아야 하나요?") == "ok"


def test_new_extensions_flagged():
    assert classify_blocker("Code.gs 파일을 수정해야 하나요?") == "flagged"
    assert classify_blocker("main.go 어디에 추가할지?") == "flagged"
    assert classify_blocker("Service.java를 바꿔야 하나요?") == "flagged"
    assert classify_blocker("lib.rs에 트레이트를 추가할지?") == "flagged"
