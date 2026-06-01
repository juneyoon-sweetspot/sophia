# SOPHIA

> 개떡같이 말해도 찰떡같이 알아듣는 사람이 일을 잘한다.
> 그런데 에이전트가 찰떡같이 알아듣고 **자기 맘대로 해버리면**, 그 결과를 해독하는 인지 부하가
> 고스란히 사람에게 돌아온다. 그러면 "잘 알아들은 것"과 "맘대로 한 것"이 구별되지 않는다.

SOPHIA는 사람의 모호한 의도와 일하는 에이전트 사이에 놓인 **번역층**이다.
거친 한 줄(개떡)을 *여러 갈래의 분명한 전제(찰떡)*로 번역해 일꾼에게 끝까지 시키고,
일꾼의 날것 산출을 **5문장**으로 응축해 돌려준다. 핵심은 두 동작의 결합이다 —
**찰떡같이 실행하되, 무엇을 어떻게 번역했는지 사후에 보고한다.** 번역 로그가 없으면
아무리 잘 해도 그냥 "맘대로 한 것"이 되기 때문이다.

---

## 왜 이게 필요한가

에이전트와 일할 때 진짜 시간이 드는 건 코딩이 아니다. **뭘 할지 합의하고, 분기마다
결정해주고, 결과를 확인해주는 대화**다. 실제 구현은 1시간이면 끝나는데 그 옆에 붙어
앉아 "이건 어떻게 할까요?"에 답하는 데 하루가 녹는다.

그리고 에이전트는 **자기 자신을 메타인지하는 데서 체계적으로 틀린다.** 대표적으로 시간
산출 — "트랙1 구축 1주일, 이건 3일"처럼 *인간 기준*으로 잡는다. 정작 에이전트가 하면
3시간에 끝날 일인데. 자기 능력·속도·완료 판정을 스스로 정확히 못 본다.

→ 그래서 일꾼을 더 똑똑하게 만드는 것으로는 안 된다. **일에 연루되지 않은, 완전히
바깥에 선 층**이 필요하다. 그게 SOPHIA다. SOPHIA는 일꾼이 자기 일에 갇혀 못 보는 것
— 거친 지시의 진짜 의도, 실제로 한 일, 무엇을 전제했는지 — 을 바깥에서 통과시킨다.

## 무엇을 안 하는가 (게으름은 설계다)

SOPHIA는 직접 일하지 않는다. 시시콜콜 지시하지도 않는다. 좋은 중간관리자처럼,
**최소한으로 개입하고 빠진다.**

- 거친 요청이 와도 **되묻지 않고** 합리적 전제를 *단정해서* 끝까지 실행시킨다.
  (자잘한 모호함마다 되묻는 것이야말로 사람에게 "프롬프트로 가르치게" 만드는 짓이다.)
- 정말 막혔을 때만 거절 대신 **재구성 질문 하나**를 남긴다. 반문은 주된 동작이 아니라
  마지막 수단이다.
- 사람에게 가는 출력은 **5문장 미만, 레포트 금지.** 인지 부하를 최소 대역폭으로 묶는다.
- 일을 다 마친 뒤 **"저는 이걸 전제로 진행했습니다"**로 사후 보고한다.

> 한 줄: **SOPHIA는 단정하고, 실행시키고, 무엇을 전제했는지 사후에 말한다.**

## 설계 원칙 (전부 `prompts/templates.py`에 인코딩됨)

1. **품질은 프롬프트의 함수가 아니다.** 사용자가 어떻게 말하든 정확히 분해하고 의도를
   파악한다. 잘 쓴 프롬프트라야 잘 나온다면, 그건 에이전트가 자기 일을 사용자에게
   외주 준 것이다.
2. **번역을 소통한다.** 개떡을 무슨 찰떡으로 바꿨는지 보고하지 않으면 "맘대로"가 된다.
   5문장 보고의 정체는 요약이 아니라 **번역 로그**다.
3. **지엽으로 전체를 부정하지 않는다.** 부분의 막힘은 부분에서 우회한다. 의심은 판을
   바꾸는 큰 전제 단위로만.
4. **한 길만 파지 않는다.** 한 요청을 *서로 다른 전제*로 갈라 병렬로 시도한다(전제공간
   탐색 — 해법공간이 아니라).
5. **지시가 없어도 멈추지 않는다.** idle은 정지가 아니라 일감 생성 트리거다.

## 포트폴리오 모드 — 본부장의 비서 (개발자 에이전트와 갈리는 지점)

개발자 에이전트는 **태스크 하나**를 받아 즉시 반응한다. SOPHIA는 **당신의 모든
프로젝트**를 동시에 들고, 대표↔본부장처럼 일한다:

- **여러 프로젝트를 동시에** 운영한다(`Portfolio`). 각 프로젝트는 자기 목표·핸드오프·
  블로커를 가지며, SOPHIA는 *내용*이 아니라 *상태*(정체/블로커)만 들고 있다.
- **정체 우선 스케줄링** — 가장 오래 안 건드린 프로젝트를 먼저 전진시킨다. "장기적으로
  잊는" 문제를 구조가 막는다.
- **주기적 단일 다이제스트** — 결정 필요(블로커)를 즉시 보내지 않고 쌓아뒀다가, 주기마다
  (원온원 주기) **leverage 순으로 정렬한 한 통**으로 올린다. 그 사이엔 침묵.
- 그래서 본부장은 자잘한 알림에 시달리지 않고, **한 통을 받아 결정만** 하면 된다.

> 개발자 에이전트: 태스크 단위 · 즉시 반응 · 한 번에 하나
> SOPHIA: 포트폴리오 단위 · 주기적 다이제스트 · 동시에 N개

## 어떻게 도는가

```
사람 ──"개떡" 한 줄──▶ [SOPHIA: 번역층] ──"찰떡" 전제 N개──▶ 일꾼(Claude Code/Codex)
  ▲                          │                                     │ (격리 worktree에서 병렬)
  └──── 5문장 번역·결과 보고 ◀─┴──── 날것 산출 응축 ◀───────────────┘
                              +  지시 없을 때: 리서치·모니터링 일감 자가 생성
```

1. **번역(in)** — 거친 요청을 작은 모델(thinker)이 *접근이 갈라지는* 전제 N개로 분해.
   (`core/manager/premise.py` · `derive_premises`)
2. **위임(do)** — 전제마다 독립 일꾼에게 "이 전제가 참이라 가정하고 끝까지 하라"고
   병렬 실행. 각 일꾼은 격리된 git worktree에서 돌아 서로의 파일을 안 건드린다.
   (`dispatch_parallel` · `adapters/isolation.py`)
3. **응축(out)** — 날것 결과를 5문장 미만으로 압축하고, 무엇을 전제하고 무엇을
   버렸는지를 보고. (`core/manager/reporter.py`)
4. **기억(persist)** — 결정·버린 전제·산출 파일·보고를 `handoff.json`에 영속화.
   재시작하면 같은 목표의 핸드오프를 읽어 **이어간다**. (`core/state/handoff.py`)
5. **자율(loop)** — 위를 6시간까지 무인으로 반복. 일감이 없으면 director가 만든다.
   (`core/loop/scheduler.py`)

## 구조 (포트 & 어댑터)

core는 **세 개의 포트만** 본다 — 누가 일하는지, 무엇으로 생각하는지, 어디서 기억을
끌어오는지 모른 채. 그래서 백엔드는 어댑터 교체만으로 갈린다(실제로 claude↔codex가
core 변경 0으로 교체됨).

```
sophia/
  ports/
    worker.py        ── WorkerBackend  (일꾼 위임의 seam)
    thinker.py       ── Thinker        (관리자 메타인지 = 작은 모델)
    retriever.py     ── Retriever      (임베딩 기반 가산 retrieval)
  adapters/
    claude_code/     ── `claude -p` 호출·stream-json 파싱        (실제 CLI 라이브 검증)
    codex/           ── `codex exec` 호출·JSONL+최종메시지 파싱   (실제 CLI 라이브 검증)
    thinker/         ── claude_cli(pip 불필요·기본) / anthropic(SDK) / fake(오프라인)
    isolation.py     ── git worktree 격리 (병렬 전제 cwd 충돌 방지)
    artifacts.py     ── tool_use(Write/Edit) → 건드린 파일 추출
    fake_worker.py   ── 오프라인 일꾼
    retriever/       ── noop / embedding(multilingual-e5 + numpy)
  core/
    manager/director.py   ── 방향 설정 + idle 시 자가 과업 생성
    manager/premise.py    ── 전제 N개 도출 → 병렬 디스패치
    manager/reporter.py   ── 5문장 보고 게이트
    state/handoff.py      ── 핸드오프 스키마 + 결과 흡수 + resume
    loop/scheduler.py     ── 6h 무인 롱런 루프
  prompts/templates.py    ── "명령 = 데이터" (행동 원칙을 로직과 분리)
```

## 실행

### 설치 (claude 와 같은 방식 — 환경변수 0개)

**한 줄 설치** (macOS·Linux, zsh·bash 무관 — `| bash` 라 셸과 독립):

```bash
curl -fsSL https://raw.githubusercontent.com/nthns-lab/sophia/main/install.sh | bash
```

또는 레포에서 직접:

```bash
git clone https://github.com/nthns-lab/sophia && cd sophia
./install.sh          # ~/.local/share/sophia 설치 + ~/.local/bin/sophia 런처
```

설치 후 어디서나:

```bash
sophia --goal "무언가를 만든다"     # 오프라인 데모 (키 불필요)
sophia tui                          # 포트폴리오 대시보드 (TUI)
sophia --real --goal "..."          # 실제 claude 일꾼에 위임
# 제거: sophia 가 깐 것 되돌리기 →  ./install.sh --uninstall
```

pip·node 불필요(순수 표준 라이브러리, python3 3.11+ 만). claude/codex CLI 가 PATH 에
있으면 `--real` 로 실제 위임이 켜진다(추가 설정 없음). macOS 는 `~/.local/bin` 이 기본
PATH 에 없을 수 있는데, 그럴 때 install.sh 가 쓰는 셸(zsh/bash)에 맞춰 안내한다.

> Homebrew(`brew install`) 배포는 수요가 생기면 tap 으로 추가 예정 — 지금은 위
> curl 한 줄로 충분하다.

### 개발 중 실행 (레포에서 직접)

```bash
cd ~/projects/sophia

# 오프라인 데모 (키·claude 불필요) — 번역→병렬위임→5문장보고→핸드오프 저장
python3 -m sophia --goal "무언가를 만든다"

# 테스트 / 종단 스모크 (pip·pytest 없는 환경용 무의존 러너)
python3 scripts/run_tests.py
python3 scripts/smoke.py

# 실제 동작 — claude CLI 가 PATH에 인증돼 있으면 pip 없이 바로 됨 (라이브 검증)
python3 -m sophia --real --backend claude --goal "..."
python3 -m sophia --real --backend codex  --goal "..."   # 같은 포트, 백엔드만 교체

# git repo 를 주면 전제별 worktree 격리가 켜진다 / 재시작 이어가기
python3 -m sophia --real --base-repo /path/to/git/repo --goal "..."
python3 -m sophia --real --resume --goal "..."           # 같은 goal 의 handoff.json 이어받기
```

`--thinker` 로 관리자 메타인지 백엔드를 고른다: 기본 `claude-cli`(pip 불필요),
`anthropic`(SDK, `pip install -e ".[thinker]"`), `auto`(anthropic 우선·실패 시 폴백).

## 상태 — 검증된 것과 안 된 것

**동작하는 코어 + 125개 테스트 통과.** 정직하게 경계를 적는다.

검증됨:
- `--real` 전체 경로가 pip 없이 end-to-end로 돈다 (claude-cli thinker → 전제 도출 →
  실제 claude 일꾼 → 5문장 보고 → handoff done).
- 실제 claude 세션 라이브 데모: 격리 worktree에서 `fizzbuzz.py`를 실제 생성,
  artifacts에 정확히 포착, base repo 오염 0, 5문장 보고가 handoff에 영속.
- claude↔codex 어댑터가 core 변경 없이 교체(포트 경계 증명, 둘 다 실제 CLI 검증).
- resume: 크래시-재시작 시 같은 목표의 기록·미완료 큐 복원 (E2E 검증).
- anticipation: 보고 후 반응 예측→선제 작업 실행→큐 소진까지 실제 claude 로 한 사이클 fired.
- 리소스 거버너: 세마포어가 부하 기준으로 동시 실행 수를 실제로 묶음(단위 검증).
- 포트폴리오: 3개 프로젝트를 정체 우선으로 동시 운영하고 블로커를 leverage 순 단일
  다이제스트로 발행하는 전체 흐름 검증(오프라인). 한 프로젝트 실패가 포트폴리오를 안 죽임.
- synthesis: 여러 전제 갈래 중 승자 하나를 근거와 함께 채택하고 나머지를 기각·graft.
  실제 claude 로 라이브 검증(cache-aside vs write-through → cache-aside 채택).
- **세션 임포터**(`adapters/sessions.py`): `~/.claude/projects` 트랜스크립트를 읽어
  cwd 별로 묶고 의도(goal)·이어갈 지점을 추출해 Project 로 만든다(읽기 전용, 단위 검증).
- **포트폴리오 라이브 1개 주행**: 임포트 → 포트폴리오 → 실제 claude → 5문장 보고 →
  다이제스트 경로를 실제 claude 로 end-to-end 확인(`scripts/portfolio_live.py`, 1개 프로젝트).
- **blocker 표면화**(`manager/blockers.py`): 라이브 주행에서 *워커가 ok=True 로 성공해도
  보고에 결정 요청을 남기면 다이제스트 '결정' 칸이 비는* 버그를 발견 → 매니저 레벨에서
  결정 필요 항목만 추출해 `handoff.blockers`→`project.blockers`→다이제스트로 배선(단위 검증).

아직 라이브로 **검증 안 됨 / 한계** (과신 금지):
- **포트폴리오 라이브 — N개 동시** 미검증(1개 주행까지만). blocker 표면화는 단위 검증까지만
  (라이브 재검증은 MCP 부작용 차단 후로 미룸 — 아래). 또한 blocker 는 틱마다 *누적*되지만
  한 번 raised 되면 자동 *해소/제거* 되지 않는다(사람이 처리해도 큐에 남음 — 후속 과제).
- **샌드박스 cwd 가 MCP 를 격리하지 못함**: 라이브 1개 주행에서 워커가 '읽기 전용' 지시를
  무시하고 붙어있던 MCP 로 외부 부작용(노션 페이지 생성)을 냈다. cwd 격리는 파일시스템만
  막는다 — MCP 경계는 별도 차단(툴 allowlist/--mcp 제거) 필요. 라이브 dogfood 전 선결 과제.
- **anticipation 품질** — 메커니즘은 라이브로 돌지만 toy goal 로만 확인(내용 빈약 가능).
- 6시간 무인 실행, SMTP 실전송, codex artifacts 추출, EmbeddingRetriever(pip 없음) — 미검증.

## 다음

- **MCP 경계 차단** — 워커 부작용을 cwd 가 못 막는다. 툴 allowlist/권한모드로 펜싱 후 라이브 재개.
- 포트폴리오 라이브 — N개 프로젝트 동시(현재 1개까지). blocker 표면화 라이브 재검증(MCP 차단 후).
- anticipation 품질·6시간 무인 주행·SMTP 실전송·codex artifacts·EmbeddingRetriever

---

<details>
<summary>개발 로그: 적대적 리뷰 반영 (5차원 워크플로우 · 18 confirmed)</summary>

- **[high] stderr deadlock 수정**: stdout/stderr 동시 배수(`communicate()`)로 6h 루프 멈춤 제거.
- 일꾼 기본 타임아웃 6h→30분 (한 일꾼이 전체 예산 독식 방지).
- start_new_session + killpg: 타임아웃 시 손자 프로세스(MCP 등)까지 그룹 정리, 좀비 reap.
- capabilities `worktree_isolation` 을 base_repo 유무로 정직화(미구현 True 광고 제거).
- stream-json 파싱: result 이벤트 없으면 assistant 텍스트 폴백.
- director: monitor 라운드로빈 + cooldown(무한반복/스핀 방지), replenish 중복제거·큐 상한.
- handoff: 리스트 상한(`max_items`)으로 6h 무한증가 방지.
- reporter: 한국어(마침표 뒤 공백 없음) + 글자수 이중 게이트.
- scheduler: report 콜백 예외 격리 + per-cycle 데드라인(`asyncio.wait_for`, 실시간 테스트로 검증).

</details>
