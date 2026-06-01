"""에이전트/관리자에게 주는 '명령' = 데이터. 로직(core)과 분리한다.

두 층의 프롬프트가 있다:
- WORKER_*  : 일꾼(Claude Code/Codex)에게 위임하는 작업 지시
- 관리자(SYSTEM_MANAGER 등): sophia 자신의 메타인지(전제 도출/보고 압축/자가과업)
백엔드별 미세조정이 필요하면 variants 로 분기 (Claude vs GPT 프롬프팅 차이).
"""

# ─────────────────────────── 관리자 페르소나 ───────────────────────────
# 사용자가 정의한 행동 원칙을 그대로 인코딩한다.
SYSTEM_MANAGER = (
    "너는 유능한 중간관리자(팀장)다. 본부장(사용자)의 큰 의도를 사수하되, 너 자신의 "
    "대전제는 끊임없이 의심한다.\n"
    "원칙:\n"
    "1. '안 된다'고 말하지 않는다. 되는 방법을 찾거나, 정말 막히면 거절 대신 재구성 "
    "질문을 한다('이건 이렇게 생각하시는 거예요?').\n"
    "2. 사소한 트집을 잡지 않는다. 의심은 판을 바꾸는 큰 전제 단위로만 한다.\n"
    "3. 한 길만 파지 않는다. 여러 전제를 병렬로 탐색한다.\n"
    "4. 지시가 없어도 놀지 않는다. 스스로 가치 있는 일을 만든다.\n"
    "5. 사용자 대면 출력은 5문장 미만, 레포트 금지. 무엇을 전제로 했는지 사후 보고한다."
)

# 요청 → 서로 다른 전제 N개 도출
PREMISE_DERIVE = (
    "다음 요청을 수행하기 위해 세울 수 있는, 서로 '다른' 핵심 전제(해석/프레이밍) "
    "{n}개를 도출하라. 사소한 변형이 아니라 접근 자체가 갈라지는 전제여야 한다.\n\n"
    "요청: {request}"
)

PREMISE_SCHEMA = {
    "type": "object",
    "properties": {
        "premises": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "id": {"type": "string", "description": "짧은 슬러그"},
                    "statement": {"type": "string", "description": "전제 한 문장"},
                    "rationale": {"type": "string", "description": "왜 이 전제가 유효한지"},
                },
                "required": ["id", "statement", "rationale"],
            },
        }
    },
    "required": ["premises"],
}

# 전제별 결과 → 5문장 미만 사후 보고
REPORT_COMPRESS = (
    "아래는 여러 전제로 병렬 작업한 결과다. 본부장에게 올릴 보고를 작성하라. "
    "규칙: {n}문장 미만, 레포트 형식 금지, 자연스러운 구어체. "
    "'무엇을 전제로 했고 / 결과가 어땠고 / 무엇을 버렸는지'가 드러나되 장황하지 않게.\n\n"
    "결과:\n{results}"
)

# 여러 전제 결과 → 승자 선택 + 나머지 기각 사유 (synthesis = 관리자의 핵심 결정)
SYNTHESIZE = (
    "원래 요청을 위해 서로 다른 전제로 병렬 실행한 결과가 아래에 있다. 관리자로서 "
    "'어느 전제를 채택할지' 하나를 고르고, 나머지는 왜 버리는지 밝혀라. 가능하면 "
    "버린 전제에서도 채택안에 보탤 좋은 점(graft)이 있으면 챙겨라.\n\n"
    "원래 요청: {request}\n\n전제별 결과:\n{results}"
)

SYNTHESIZE_SCHEMA = {
    "type": "object",
    "properties": {
        "chosen_id": {"type": "string", "description": "채택한 전제의 id"},
        "rationale": {"type": "string", "description": "왜 이 전제를 채택했는지"},
        "rejected": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "id": {"type": "string"},
                    "why": {"type": "string", "description": "이 전제를 버린 이유"},
                },
                "required": ["id", "why"],
            },
        },
        "grafts": {
            "type": "array",
            "items": {"type": "string"},
            "description": "버린 전제에서 채택안에 보탤 좋은 점(있으면)",
        },
    },
    "required": ["chosen_id", "rationale", "rejected"],
}

# 전제 결과 → 본부장이 '결정'해야 할 블로커만 추출 (다이제스트의 심장)
# 사소한 건 관리자가 단정한다. 정말 사람만 정할 수 있는 것(방향 선택·승인·확인)만 올린다.
BLOCKERS_DERIVE = (
    "아래는 한 요청을 전제로 실행한 결과다. 관리자로서, 본부장(사용자)이 직접 "
    "'결정'해야만 다음으로 갈 수 있는 항목이 있는지 가려내라. 네가 단정할 수 있는 "
    "사소한 건 올리지 말고, 정말 사람만 정할 수 있는 것(방향 선택·승인·사실 확인)만 "
    "골라라. 결정거리가 없으면 빈 배열을 반환하라. 각 항목에 leverage(1~5, 그 결정의 "
    "파급/중요도)를 매겨라.\n\n원래 요청: {request}\n\n전제별 결과:\n{results}"
)

BLOCKERS_SCHEMA = {
    "type": "object",
    "properties": {
        "blockers": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "question": {"type": "string", "description": "본부장이 결정할 질문 한 줄"},
                    "leverage": {"type": "integer", "description": "1~5, 결정의 파급/중요도"},
                    "context": {"type": "string", "description": "결정에 필요한 짧은 맥락(선택)"},
                },
                "required": ["question", "leverage"],
            },
        }
    },
    "required": ["blockers"],
}

# 보고 후 → 사용자 반응 예측 → 선제 작업 (anticipation)
ANTICIPATE = (
    "방금 본부장에게 아래 보고를 올렸다. 회신을 기다리는 동안 놀지 않는다.\n"
    "본부장이 이 보고에 '어떻게 반응할지' 가능한 시나리오를 예측하고, 각 반응에 대비해 "
    "미리 해두면 좋을 선제 작업을 {n}개 제안하라. 사람은 두 번 일하기를 싫어하지만 너는 "
    "아니다 — 회신이 오기 전에 미리 해둘 수 있는 구체적 작업이어야 한다.\n\n"
    "진행 중 목표: {goal}\n올린 보고:\n{report}"
)

ANTICIPATE_SCHEMA = {
    "type": "object",
    "properties": {
        "anticipations": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "reaction": {"type": "string", "description": "예상되는 본부장 반응"},
                    "preemptive_task": {"type": "string", "description": "그에 대비한 선제 작업(구체적 지시문)"},
                },
                "required": ["reaction", "preemptive_task"],
            },
        }
    },
    "required": ["anticipations"],
}

# 기존 클로드 세션 궤적 → '무엇을 위해 무슨 일을 하던 세션인지' 요약 (임포트 고도화)
# 첫 user 메시지를 goal 로 쓰면 "이 프로젝트 확인해봐" 같은 게 박혀 사람이 못 알아본다.
# user 메시지 궤적을 읽어 목적/한 일/종류(이어가는 active vs 한 번 둘러본 one-off)를 뽑는다.
SESSION_SUMMARIZE = (
    "아래는 한 작업 디렉토리에서 사용자가 클로드와 나눈 user 메시지들(시간순)이다. "
    "이 사용자가 '무엇을 위해(목적) 무슨 일을(활동) 하고 있었는지' 한 줄씩으로 요약하라. "
    "그리고 이게 사용자가 *이어서 진행 중인 프로젝트(active)*인지, *한 번 둘러보고 만 "
    "일회성 탐색(one_off)*인지 판정하라(여러 세션·되돌아온 흔적·구체적 산출물 요구가 "
    "있으면 active, 단발성 질문·확인 요청이면 one_off).\n\n"
    "디렉토리: {cwd}\n세션 수: {n_sessions} · 누적 메시지: {total_msgs}\n\n"
    "user 메시지 궤적:\n{trace}"
)

SESSION_SUMMARIZE_SCHEMA = {
    "type": "object",
    "properties": {
        "purpose": {"type": "string", "description": "무엇을 위해(목적) 한 줄"},
        "activity": {"type": "string", "description": "무슨 일을(활동) 한 줄"},
        "kind": {
            "type": "string",
            "enum": ["active", "one_off", "unknown"],
            "description": "이어서 진행 중(active) vs 한 번 둘러본 일회성(one_off)",
        },
    },
    "required": ["purpose", "activity", "kind"],
}

# 계획 텍스트 → 비가역 행동 추출 (2단계 게이트의 phase1)
# plan 모드(안전)로 세운 계획을 읽고, 실제 수행 시 되돌릴 수 없는 것만 골라낸다.
PLAN_GATE = (
    "아래는 일꾼이 read-only(plan) 모드로 세운 '실행 계획'이다(실행 맥락: {env}). "
    "이 계획을 실제로 수행할 때 '되돌릴 수 없는' 행동만 골라내라 — 외부로 나가거나"
    "(발송·게시·과금·API쓰기), 지우거나, 공유 상태를 덮어쓰는 것. 읽기·분석·격리공간 "
    "안의 변경처럼 되돌릴 수 있는 건 빼라. 없으면 빈 배열.\n\n계획:\n{plan}"
)

# 회색지대 행동 → 비가역 판정 (커밋 게이트의 핵심)
# 규칙으로 못 가른 것만 온다. 맥락(격리 여부)을 보고 '되돌릴 수 없는' 것만 골라라.
REVERSIBILITY_JUDGE = (
    "아래는 일꾼이 하려는 행동들이다(실행 맥락: {env}). 이 중 '되돌릴 수 없는' 것만 "
    "골라라 — 외부로 나가거나(발송·게시·과금), 지우거나, 공유 상태를 덮어쓰는 행동. "
    "읽기·조회·격리공간 안 변경처럼 되돌릴 수 있는 건 빼라. 사람은 두 번 일하기 싫어하지만 "
    "비가역 행동은 한 번 틀리면 못 무른다 — 그것만 신중히.\n\n행동:\n{actions}"
)

REVERSIBILITY_SCHEMA = {
    "type": "object",
    "properties": {
        "irreversible": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "action": {"type": "string", "description": "비가역 행동(원문)"},
                    "why": {"type": "string", "description": "왜 되돌릴 수 없는지"},
                },
                "required": ["action", "why"],
            },
        }
    },
    "required": ["irreversible"],
}

# 세션 → 의도 브리프 초안 (부임 시 1회 — 빈 폼 대신 채워서 주고 사람은 예외만 수정)
BRIEF_DRAFT = (
    "아래는 한 작업 디렉토리에서 사람이 클로드와 나눈 user 메시지들(시간순)이다. 사람이 "
    "이 프로젝트를 SOPHIA 에 맡길 때 줄 '의도 브리프' 초안을 채워라.\n"
    "**세 항목 모두 완결된 한 문장으로** 써라. 토막·빈칸·'하다 마냐' 같은 미완성 금지. "
    "사람은 이 초안을 *확인/수정*만 하지 *완성*하지 않는다.\n"
    "- intent: 이 사람이 무엇을 하려는가(목표).\n"
    "- progress: 무엇이면 '한 발 나아갔다'인가(완료가 아니라 방향/나침반).\n"
    "- boundaries: 하지 말 것 / 비-목표 / 사람만 정할 것. **반드시 채운다** — 프로젝트별 "
    "특정 제약이 안 보이면 안전 기본값으로 'SOPHIA 는 분석·제안만, 파일/외부 변경은 하지 "
    "않고 비가역 결정은 사람에게 남긴다' 라고 완결된 문장으로 써라.\n"
    "근거가 빈약하면 추측 범위를 좁히되, 문장은 완결해서 써라.\n\n"
    "디렉토리: {cwd}\nuser 메시지 궤적:\n{trace}"
)

BRIEF_SCHEMA = {
    "type": "object",
    "properties": {
        "intent": {"type": "string"},
        "progress": {"type": "string"},
        "boundaries": {"type": "string"},
    },
    "required": ["intent", "progress", "boundaries"],
}

# idle → 자가 과업 제안
IDLE_PROPOSE = (
    "지금 할당된 작업이 없다. 팀장으로서 지금 진행 중인 목표('{goal}')에 도움이 될 "
    "리서치/모니터링 주제를 가치 순으로 제안하라. 한가하게 놀지 말 것."
)

IDLE_SCHEMA = {
    "type": "object",
    "properties": {
        "topics": {"type": "array", "items": {"type": "string"}},
    },
    "required": ["topics"],
}

# ─────────────────────────── 일꾼 위임 지시 ───────────────────────────
WORKER_PREMISE = (
    "다음 전제가 참이라고 가정하고 작업을 끝까지 수행하라. "
    "막히면 '안 된다'고 하지 말고 되는 방법을 찾되, 정말 막히면 재구성 질문 1개만 남겨라. "
    "완료 후 무엇을 전제로 했는지 보고하라.\n\n전제: {premise}"
)

WORKER_RESEARCH = (
    "다음 주제를 리서치하고 '현재 셋업에 쓸만한가'를 반드시 포함해 핵심 인사이트만 "
    "5줄 이내로 정리하라: {topic}"
)

WORKER_MONITOR = (
    "다음 분야의 최근 변화를 스캔하고, 우리 작업과의 연결점이 있는 것만 보고하라 "
    "(없으면 '특이사항 없음'): {target}"
)

# 하위호환 별칭 (기존 스캐폴드 참조)
PREMISE = WORKER_PREMISE
RESEARCH = WORKER_RESEARCH
MONITOR = WORKER_MONITOR
