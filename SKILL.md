---
name: multi-domain-research
description: Forge domain-fit research workflows on a local data lake.
version: 1.0.0
author: BCL, Hermes Agent
license: Apache-2.0
platforms: [linux, macos, windows]
metadata:
  hermes:
    tags: [Research, Workflow, Subagents, DuckDB, SQLite, Parquet]
    related_skills: [subagent-orchestration, grounded-citations]
---

# Multi-domain research lab (Forge · Lab · Crew · Retro)

연구 도메인과 연구 방향을 **특성(traits)으로 서술**하면, 그에 맞는 workflow를 블록 카탈로그에서 **합성해 라이브러리에 저장**하고, 그 workflow를 로컬 데이터 인프라(SQLite 원장 + Parquet + DuckDB) 위에서 서브에이전트 웨이브로 실행한 뒤, 결과를 라이브러리에 환류합니다. 모든 자식 출력은 파일로만 받고, 부모가 인용·SQL·수신증(receipt)을 기계 검증한 뒤에만 원장에 적재합니다. 엔진은 `scripts/rlab.py`(CLI)이며 `$RLAB`로 표기합니다.

## When to Use

- 여러 출처를 넘나드는 심층 조사(기술·시장·정책·학술·인물 고증·사건 등)으로, 문장 단위로 근거 추적이 필요할 때.
- 정해진 절차가 아니라 **도메인·방향에 맞춘 새 workflow**가 필요할 때(도메인이 생소해도 traits로 서술 가능).
- 서브에이전트 병렬 수집·추출·반증과 정량 분석(SQL)을 한 원장에서 함께 다룰 때.
- **쓰지 말 것:** 단일 조회·요약, 한 파일 읽기, 이미 확정된 사실의 형식 변환, 코드 구현·디버깅(직접 도구 사용).

## Prerequisites

- 샌드박스에서 스킬 폴더는 읽기 전용 `/hermes-home/skills/research/multi-domain-research`로 보입니다(`skill_view`의 호스트 경로와 다릅니다). 산출물은 스킬 폴더가 아니라 **lab home**(`$RLAB_HOME`, 기본 `/workspace/research-lab`)에 쌓입니다.
- `write_file`/`read_file`/`patch` 도구는 Hermes 호스트 작업공간(`workspace.*`) 기준으로 경로를 풉니다. docker 백엔드에서 `/workspace/research-lab/...` 같은 lab-home 경로에 쓰면 "OUTSIDE the active workspace"로 경고합니다. **신규 파일 생성**(intake/traits/questions 등)은 이 경고가 뜨면 호스트 쪽 다른 디렉터리에 떨어져 `rlab`이 못 찾을 수 있으므로 `terminal`의 `cat > ... << 'EOF'`(heredoc)로 docker 안에서 직접 쓰십시오. **기존 파일을 고치는 `patch`**(예: brief.md에 §8 포인터 추가)는 같은 경고가 떠도 실제로는 docker 쪽 파일에 올바르게 반영되는 경우가 있었습니다(find-and-replace가 파일 내용 기준으로 동작하기 때문으로 보임) — 그래도 경고를 신뢰하지 말고 `write_file`/`patch`로 lab home 파일을 쓴 뒤에는 매번 `terminal`에서 `cat`으로 실제 반영 여부를 확인하십시오.
- duckdb가 설치된 파이썬 필요(이 상자의 기본: `/workspace/.envs/tools/bin/python`). 없으면 `doctor`가 설치 명령을 출력합니다. 표준 라이브러리 SQLite만으로도 forge·원장·게이트는 동작하고, `lake`·`sql`·데이터셋·SQL 근거만 duckdb를 요구합니다.
- `delegate_task`의 **현재 활성 option 목록**(라우팅 표의 이름이 지금도 유효한지 매 run 확인). 동시 실행 자식 수 상한은 사용자 설정(현재 4)입니다.

```bash
PY=/workspace/.envs/tools/bin/python
SK=/hermes-home/skills/research/multi-domain-research
$PY $SK/scripts/rlab.py setup        # lab home + /workspace/.envs/bin/rlab 래퍼 생성 + doctor
RLAB=/workspace/.envs/bin/rlab       # 이후 이것만 사용(로그인 쉘은 PATH에서 .envs/bin을 빼므로 절대경로)
```

## Quick Reference

```bash
$RLAB forge --traits t.json --name <slug> [--fork WF] [--add B] [--drop B] [--set k=v|block.k=v]   # 합성+저장
$RLAB wf list | wf show <id> | wf match --traits t.json                                          # 라이브러리
$RLAB init --workflow <id> --run-id R [--brief b.md --questions q.jsonl]                          # run 생성
$RLAB questions --run R --file q.jsonl                                                           # 질문 트리 적재
$RLAB next --run R --dispatch --available "A,B,..."        # 엔진 전진 + delegate_task 페이로드
$RLAB load --run R --task T --file <staging/out/T.jsonl>  # 검증+적재(트랜잭션)   [자식용: begin / check]
$RLAB gate --run R [name] | status | report | waive --gate G --reason ".." | reopen --block B
$RLAB sql --run R --recipe coverage | "SELECT ..." [--hash]     # DuckDB 읽기 전용 SQL, recipes: `$RLAB recipes`
$RLAB source add|set|drop ... | retry --task T | resolve --id X0001 --status resolved|disclosed
$RLAB done --run R --block B        # PARENT ACTIONS(부모가 직접 수행한 블록, 예: access-broker)를 완료로 표시해 다음 블록 잠금을 풉니다
$RLAB retro --run R [--score 0-5] --lesson "..."        # 적합도·교훈·변이 제안을 라이브러리에 환류
```

## Procedure

전체 여정: **P0 Setup → P1 Traits → P2 Forge → P3 Run 시작 → P4 구동 루프 → P5 분석·반증 판정 → P6 산출물 → P7 Retro**. 각 단계 시작·끝에 현재 단계와 다음 단계를 사용자에게 알리십시오.

**P0 Setup.** `setup`/`doctor`를 실행하십시오. 완료: `RESULT OK`.

**P1 Traits (도메인·방향 서술).** 먼저 요청 문구를 한 줄로 되풀이해 해석을 확정하십시오. 금융·법률처럼 용어가 비슷한데 뜻이 갈리는 도메인(예: 해외 *원화결제*[DCC] vs *외화결제*[환전수수료])은 사용자가 정정하면 이미 forge한 workflow의 domain/direction/brief/질문이 모두 틀어지므로, 용어가 모호하면 forge 전에 해석을 한 문장으로 확인하십시오. 정정을 받으면 run 생성 전이라면 잘못 저장된 workflow 파일(`workflows/<id>.json|md`)을 지우고 정정한 traits로 다시 `forge`하며, 라벨만 바뀐 경우에도 brief·questions를 새로 씁니다. `references/trait-rubric.md`의 판정 질문으로 traits JSON을 작성하십시오(`assets/traits.example.json` 참고). 값마다 근거 한 줄을 남기고, 불확실하면 비용이 큰 쪽(stakes·noise 상향)으로 판단하십시오. 완료: 모든 trait가 허용 값이고 mode(방향)가 하나로 정해집니다.

**P2 Forge.** 먼저 `wf match`로 유사 저장 workflow를 찾습니다(거리 ≤0.25이면 `--fork`로 변이, 그 외에는 새로 합성). `forge` 출력의 블록·레인·예산 추정·탈락 사유·라이브러리 교훈을 읽고, 질문에 비해 과하거나 빠진 곳이 있으면 `--add/--drop/--set`으로 보정하십시오(블록 정의·확장은 `references/blocks-and-forge.md`). 저장 전에 `forge --no-save`로 미리보기하고, 사용자에게 구성 요약과 선택지(그대로 / 경량화(이중 코딩→단일 등) / 직접 수정)를 비용·잃는 것과 함께 제시하십시오. 사용자가 '설명 요청'을 고르면 블록별 역할(설계·수집·차단·추출·분석·검증·마무리), 탈락 블록과 사유, 선택지별 trade-off를 풀어 쓰고 권고안을 밝힌 뒤 다시 승인을 받습니다. 완료: workflow가 `lab home/workflows/<id>.json|md`로 저장되고 사용자가 구성(블록·예상 task 수)을 승인합니다. traits(access·volume 등)나 범위가 크게 바뀌면 `--fork`로 새 workflow를 만들고 새 run으로 옮깁니다(fork 함정과 새 세션 인수인계 방법은 `references/blocks-and-forge.md`의 'fork 운영'). 사용자가 무중단 완주를 명시했으면 구성·탈락 블록·예산 트리밍을 기록하고 진행하되, 위험이 커지는 변경(고위험 블록 트리밍 등)은 따로 확인합니다.

**P3 Run 시작.** `templates/brief.md`를 채워(`{{`가 남아 있으면 intake 미완) `init`하고, `questions.jsonl`을 작성합니다: 최상위 질문 7개 이하, 질문마다 `kind`(yesno|compare|measure|trend|rank|describe|explain|forecast)와 판정 가능한 `labels`(코드북), 해석적 질문은 `label_defs`까지(성격·인물 질문의 라벨은 이론에서 도출하고, 초안은 서로 다른 계열 서브에이전트 검토와 공개 사건 시험 코딩을 거쳐 확정: `references/personality-frameworks.md`의 '코드북 작성·검토 절차'). 완료: `status`에서 intake·qtree가 complete.

**P4 구동 루프 (P4~P7을 `next`가 순서대로 안내합니다).** 게이트가 막으면 우회(waive)보다 원인을 먼저 읽습니다. 주장 강도가 문제면 `rlab downgrade`, 모순이 남으면 원문을 읽고 `rlab resolve --status disclosed`로 사유와 함께 공개합니다. 수집·추출·분석·반증이 끝나면 `next`가 PARENT ACTIONS로 `synthesize`를 띄우고(→ P5·P6 수행), 그다음 `retro`를 띄웁니다(→ P7). `ALL DONE`은 P6·P7까지 끝난 뒤에만 나옵니다. 모두 끝날 때까지 반복합니다.
1. `next --dispatch --available "<현재 option 목록>"` — 엔진이 준비된 task를 만들고 `delegate_task tasks` JSON을 출력합니다(계약서 전문은 파일, 페이로드는 포인터).
2. 그 JSON을 그대로 `delegate_task(tasks=[...])`에 넣습니다(동시 최대 4). `option`이 비어 있으면(`none of [...] is available`) `references/crew-contracts.md`의 tier로 현재 활성 option 중에서 골라 각 task에 직접 `option`을 추가합니다. 같은 `--available` 목록을 매 `next`에 반복해 넘기면 후보가 있는 role은 `option`이 자동 채워집니다. 디스패치 후에는 응답을 끝내고 완료 알림을 기다리며(폴링 금지), 알림이 오면 task별 `load` → `next --dispatch` 순으로 진행합니다. 레인 간 중복 후보는 `load`가 dup으로 걸러 주므로 정상입니다.
   - **`goal`을 손으로 다시 타이핑하지 마십시오(예외 없음, task 1개짜리 디스패치도 포함):** addendum 포인터를 넣거나 context를 압축하려고 task를 재구성할 때 — 심지어 한 번에 task가 1개뿐이라 "그냥 짧게 쓰면 되지" 싶을 때도 — `goal` 필드는 절대 직접 쓰지 말고, 매번 `/workspace/.envs/tools/bin/python3 -c "import json; d=json.load(open('<dispatch_NNN.json 경로>')); [print(t['goal']) for t in d['tasks']]"`를 먼저 실행해 그 출력을 그대로 복사-붙여넣으십시오. 이 추출 호출을 생략하고 기억이나 요약으로 goal을 적으면 `"없음"`·빈 문자열 같은 자리채움이 새어 들어가 자식이 빈 요청으로 즉시 실패하고 `stop`+재디스패치가 필요합니다(한 세션 안에서 같은 실수가 두 번 반복된 적 있음 — 규칙을 읽은 것과 매번 실행하는 것은 다릅니다). 같은 이유로 한국어 등 비ASCII를 담을 때 `\uXXXX` 이스케이프를 손으로 계산하지 말고 평문 UTF-8 문자열을 그대로 파라미터에 적으십시오 — 오타 없이도 조용한 mojibake(`입력`→`입륥`)가 날 수 있습니다.
   - **workflow-critic findings 처리:** `load` 후 findings를 직접 읽고 block/warn/info별로 수용·기각·한계 공개를 정해 `reports/critic_dispositions.md`에 기록합니다. 설계 보강은 workflow.json을 고치지 않고 run 디렉터리의 `addendum.md`(수집 경계·출처 역할·독립성 정의·질문별 코딩 규칙·부모 후속 조치)로 씁니다. 계약서에는 brief가 1400자까지만 요약 포함되므로, brief 끝에 §8 포인터를 덧붙이고 **디스패치 payload의 `context`에 `addendum.md` 절대경로와 '충돌 시 부록의 금지·제한 우선'을 직접 추가**하십시오. block finding은 조치 확인 전 해당 단계로 진행하지 않습니다. 인물·창작 조사 규칙은 `references/person-profile-research.md`.
3. PARENT ACTIONS(부모 전용 블록)는 직접 수행합니다. 로그인·멤버십 출처는 부모만 접근합니다. 접근이 필요한 출처가 없으면(access-broker 등) 수행할 일이 없다는 사실 자체가 조치이며, 그래도 `done --run R --block <block>`으로 완료 표시를 해야 `status`가 active에서 complete로 넘어가고 하위 블록이 잠금 해제됩니다(표시하지 않으면 `next`가 같은 블록을 계속 PARENT ACTIONS로 다시 띄웁니다).
4. 자식이 끝나면 task마다 `load --task T --file staging/out/T.jsonl`. **`VERIFIED`만 완료입니다**(자식의 "완료했습니다"는 증거가 아닙니다). `FAILED`/`PROOF FAILED`면 원인을 분류(계약 누락→brief 수정, 도구 오류→환경 수정, 모델 한계→`retry --option` 승격) 후 `retry`.
5. `[BLOCKED]`는 해결하거나 `waive --reason`(사유는 limitations에 자동 기록)합니다.
완료: `next`가 `ALL DONE`을 출력합니다. 실행된 모델 확인은 `subagent-orchestration` 스킬의 manifest 절차를 따릅니다.

**P5 분석·반증 판정.** 루프 중 `gate`·`sql --recipe coverage|origin_share|agreement|saturation|claims|contradictions`로 진단합니다. 미해결 모순은 `resolve --status resolved|disclosed`로 처리하고, coverage/saturation soft gate 실패는 엔진이 scout를 max_waves까지 자동 재개방합니다. 임의 SQL 분석은 `sql`(읽기 전용) 또는 `lake/parquet/*.parquet`을 polars·duckdb로 직접 엽니다(`references/data-lab.md`).

**P6 산출물.** `reports/deliverable.md`에 사실 문장마다 `[K0001]`을 붙이고, 확인되지 않은 것은 '미확인'으로 남기며, 해결되지 않은 모순과 `## Limitations`를 포함합니다(`report`가 limitations 초안을 자동 생성). 완료: `citation`·`contradictions` 게이트 pass. `citation`은 구조 검사(인용 id 존재·Limitations 절)일 뿐이므로 `uncited_lines`와 문장↔주장의 의미 대응은 직접 검토하고 결과를 limitations에 남깁니다(stakes=high는 qa-review가 독립 검토).

**P7 Retro.** `retro --score <사용자 평가 0-5, 없으면 생략> --lesson "..."`. 점수가 없으면 대리 지표(proxy)만 기록되며 이것은 품질이 아니라 프로세스 건전성입니다(`references/retro-learning.md`). 완료: `registry.sqlite`에 run·교훈·변이 제안이 기록되고 다음 `forge`에 나타납니다.

## Pitfalls

- 자식은 `begin`이 출력한 receipt를 meta에 넣어야 합니다. 추측·재사용한 receipt·잘린 파일(n_rows 불일치)는 `PROOF FAILED`입니다. 실행 없이 결과를 지어낸 자식을 걸러내는 장치입니다.
- 채팅으로 결과를 받지 마십시오. 출력은 계약의 JSONL 파일 하나뿐입니다.
- 인용은 정규화(NFKC·공백·곡선 따옴표) 후 원문의 **연속 부분 문자열**이어야 합니다. 줄임표·번역·요약 인용은 거부됩니다. 모델이 번역해 쓴 인용이 거부되면 원문 언어 그대로 인용하도록 계약을 보강하십시오. 원문이 raw HTML(수집·반증 단계에서 `curl`로 직접 받은 페이지 등)이면, 화면에 이어 보이는 문장이라도 사이에 태그가 끼어 있으면 연속 부분 문자열이 아니라서 거부됩니다(`quote not found verbatim`). 이 거부는 그 인용을 참조하는 challenges/claims 행까지 `unknown evidence id`로 연쇄 거부시킵니다. 계약에 "HTML 태그로 끊긴 문장을 하나의 인용으로 잇지 말고, 태그 안에 온전히 들어있는 연속 텍스트만 인용하라"를 추가해 예방하고, 이미 난 거부는 `load --accept-rejects`로 해당 행(과 그걸 참조하는 행)만 떨어뜨려 나머지를 커밋한 뒤 사례를 limitations에 기록하십시오(재작업보다 저렴하며, 다른 유효한 판정에는 영향이 없습니다).
- 행의 `kind`는 canonical 행 종류(candidates|sources|evidence|claims|challenges|findings)일 때만 파서 선택자입니다. findings 전용 블록은 분류값(`missing_lane` 등)을 `kind`에, claims·evidence와 섞인 블록은 `{"kind":"findings","type":"분류"}`로 씁니다.
- 의도적 0행(후보 없음·질문에 맞는 데이터 없음)은 meta에 `"n_rows":0,"empty":true,"blocker":"사유"`를 써야 통과합니다. 그냥 빈 파일은 실패로 처리합니다.
- `delegate_task`를 쓸 수 없는 환경이면 부모가 계약서를 순서대로 직접 수행할 수 있습니다. 이때는 독립 모델 검토가 아니므로(특히 이중 코딩·반증) 이 사실을 limitations에 기록하십시오.
- `init` 때 brief·질문·workflow는 task마다 `tasks/<T>/input/`에 **스냅샷**으로 복사됩니다. 디스패치 전에 brief를 고쳤다면 planned 상태 task의 `input/brief.md` 사본을 새 brief로 교체하고 `contract.md`에 표시된 해시도 맞추십시오(원장의 `input_sha`는 생성 시 값 그대로이며 이후 검증에 쓰이지 않습니다). 이미 디스패치한 task는 옛 brief를 봅니다. 허가·금지 같은 민감 조건을 바꿀 때는 `grep -rn`으로 run 디렉터리 전체의 옛 값을 찾아 남은 사본이 없는지 확인하십시오.
- 실행 중인 run의 `workflow.json`을 고치지 마십시오. 구조 변경(블록 추가·삭제)은 `forge --fork` → 새 run이고, 운영 규칙 보강은 `addendum.md` + dispatch context(P4 참고)로 합니다.
- `raw/`는 불변입니다(덮어쓰면 인용 검증과 해시가 깨집니다). 원문은 로컬 연구용 저장이며 산출물에는 짧은 인용만 싣습니다.
- 비공개 신상(본명·주소·가족·학교·직장)은 수집·저장하지 마십시오. 수집자가 `pii:true`로 표시한 출처는 추출에서 자동 제외되며 `source drop`/`set --pii clear`로 부모가 처리합니다. 단 collect는 원문을 먼저 저장하므로 사후 차단만으로는 부족합니다: 수집 계약에 금지 범주를 미리 명시하고 해당 **줄을 통째로 삭제한 뒤** 저장하게 하며(남은 줄은 원문 그대로라 인용 검증 유지), 추출 전에 부모가 `raw/`를 grep으로 재검사합니다.
- 샌드박스는 호스트 `.env`를 의도적으로 가립니다. 외부 API 키가 필요하면 읽으려 하지 말고 사용자에게 `docker_forward_env`로 변수 이름을 넘겨 달라고 요청하며(사용자가 호스트에서 설정), 쿠키는 사용자가 내보낸 youtube.com 항목 파일을 run 전용 secrets 경로에 두게 합니다. 어느 쪽이든 값은 채팅에 받지 않고 부모만 사용합니다. 전사 비용·제한은 `references/external-stt.md`. 호스트에서 설정할 정확한 명령은 두 단계다: ① `hermes config set <VAR_NAME> "<값>"`(값은 자동으로 `.env`로 분리 저장, config.yaml에는 안 남음) ② `hermes config set terminal.docker_forward_env '["<VAR_NAME>", ...기존항목...]'`(기존 배열을 덮어쓰므로 먼저 `hermes config get terminal.docker_forward_env`로 현재값을 확인해 합칠 것). 전달 뒤에는 세션 쪽에서 `env | grep <VAR_NAME>`과 길이만 확인하고(값 자체는 echo하지 않음) 가능하면 무해한 호출 1건으로 실제 연동까지 검증한다.
- `access` trait이 gated이고 brief가 자격증명을 부모만 쓰게 제한하면, access-broker 1회 실행으로 끝나는 게 아니라 **그 자격증명이 필요한 모든 acquire 단계(특히 collect)가 부모 전담**이어야 한다. scout(웹 탐색)는 자격증명 없이 후보 식별자(핸들·URL)만 찾게 하고, 실제 인증 조회(API 호출)는 부모가 PARENT ACTION으로 수행해 `rlab source add`로 등록한 뒤에야 extract 단계 서브에이전트가 그 등록된 자료를 읽게 하라. 이걸 놓치면 Collector 서브에이전트가 가지지도 않은 자격증명으로 수집을 시도하다 실패하거나, 금지된 자격증명 전달이 필요해진다.
- 질문 중 일부가 **개체(entity)별이 아니라 플랫폼/환경 전체에 공통으로 적용되는 질문**(예: "이 플랫폼 자체 ToS가 재사용과 상충하는가")이면, 매 개체마다 서브에이전트가 반복 조사하게 하지 말고 부모가 **한 번만** PARENT ACTION으로 조사해 고정 판정을 내리고 그 결과를 addendum에 적어 모든 개체의 해당 질문에 공통 적용하라(단 개체별 예외 조건—예: 비공개 계정이면 판정이 달라짐—은 분기 규칙으로 addendum에 함께 명시). 플랫폼 성격의 질문을 개체 수만큼 중복 조사하면 예산을 낭비하고 서로 다른 답이 나올 위험도 생긴다.
- 사용자에게 승인을 요청하는 계획·목록은 응답 안에서 **파일 링크(MEDIA)와 경로**로 직접 제시하십시오(문서 위치를 되묻게 하지 않기). 승인 대상이 이론 설계서뿐이면 구체 목록과 칸별 검증표를 먼저 만들어 함께 보여 줍니다(`references/personality-frameworks.md`의 '승인용 구체 목록').
- 모델 다수결은 사실 확인이 아닙니다. 신뢰도(κ)는 코딩 일관성 지표일 뿐이고 주장 상태는 독립 출처 수로 판정됩니다.
- `waive`는 비용을 아끼는 수단이 아니라 위험 수용 기록입니다. 사유를 구체적으로 쓰고 산출물 limitations에 옮기십시오.
- 도구가 분석을 잡아먹지 마십시오. 시간은 P5·P6(판정과 집필)에 배분하고 인프라 튜닝에 쓰지 마십시오.
- 수 분 이상 걸릴 수 있는 명령(전사·다운로드·화자 분리·재시도)은 처음부터 `background=true`로 돌리십시오. 포그라운드로 돌리면 도구 제한에 걸려 SIGKILL(137)로 죽고 출력이 잘려 성공·실패를 알 수 없게 됩니다. 그래서 스크립트는 항상 재개 가능(이미 저장된 결과 건너뛰기)해야 하고, 죽은 뒤에는 로그가 아니라 **저장된 파일 수**로 상태를 판단합니다.
- 진행률·속도를 보고할 때는 먼저 프로세스 생존과 마지막 저장 파일의 mtime이 현재 시각과 가까운지부터 확인하고(로그 줄은 교착 뒤에도 남아 있습니다), 보고는 완료/전체(비율), 최근 N분 평균 속도(오디오시간/분·배속·건/분), 실패 수, 이번 단계 비용과 누적(상한 대비), 남은 시간 추정 순으로 실측값만 적습니다. 자기 코드 결함으로 시간을 잃었으면 원인·영향·조치를 숨기지 말고 그대로 보고합니다.
- 사용자가 "한계를 극복할 아이디어"를 물으면 아이디어 나열 전에 현재 데이터로 각 방안의 효과를 시험(규칙 완화는 변형 실행, 대안 자료원은 규모 집계)해 한계별 표(방안·효과·비용·사용자 부담)와 권고 순서로 제시하고, 극복할 수 없는 한계는 Limitations 대상이라고 말합니다. 병목이 규칙인지 자료 공급인지부터 가리십시오(`references/person-profile-research.md` 13항).
- 백그라운드 작업은 샤드·재시도·보조 시험마다 완료 알림을 켜면 알림마다 응답 턴이 생깁니다. 알림은 단계를 끝내는 집계 작업에만 걸고, 이미 반영한 작업의 알림에는 "반영됨·변동 없음"만 한두 문장으로 답하십시오.

- **전문 도메인 검토 루프는 이미 문서·별도 스킬로 운영 중입니다.** 비전문 승인자는 제시된 안을 그대로 승인하기 쉬우므로, 승인을 묻기 전에 서로 다른 계열 고성능 서브에이전트의 검토→개정→재검토를 거치게 합니다. 코드북 단계의 절차는 `references/codebook-iteration-lessons.md`와 `codebook-revision-validation-loop` 스킬이 이미 담고 있고 사용자가 작동을 확인했습니다. 엔진 블록(expertise trait, adjudicate/panel, 서브에이전트 synthesize)으로 다시 구현하지 마십시오(구현했다가 사용자 지시로 롤백했고 기존 루프와 중복됩니다). 코드북 외 단계(분석·합성)에도 필요한지는 사용자 확인 후에만 확장하십시오. 별개 피드백으로, 저가 부모 모델(Sonnet급·Terra급)이 질문 설계·모순 해소·강도 판정·집필까지 전담하면 품질이 떨어졌습니다. 부모는 지휘·검증에 두고 판단 작업은 고성능 서브에이전트에 맡기십시오.
- **수집 제한(저장 금지·텍스트와 메타데이터만 등)은 사용자 지시나 법적 근거가 있을 때만 brief에 넣으십시오.** 에이전트 재량으로 "프라이버시 보호" 명목의 자료 유형 축소를 기본값으로 걸면, 이미지·음성이 있어야 판정되는 질문(유머 여부·순도 등)이 개체당 텍스트 1건 표본으로 판정되어 재분기·재작업 비용이 듭니다. 제한마다 출처(user|legal|agent)·근거·약해지는 질문을 brief §5에 적고, 근거 없는 agent 제한은 걸지 말고 사용자에게 한 줄로 확인하십시오. 질문마다 판정에 필요한 자료 유형과 개체당 최소 표본 수를 qtree에서 정하고, 제한이 이를 무력화하면 `workflow-critic` 단계에서 짚습니다. 실제 PII(비공개 신상, 작성자 식별 정보)와 로그인 자료의 규칙은 별개로 유지합니다. 원본을 저장하지 않아야 하면 일시 열람 후 설명 텍스트만 저장(파생물만 보관)하는 방식으로 분석은 그대로 합니다.
- 같은 모델(예: M-Terra-Balanced)로 4개를 동시에 돌리면 `HTTP 429 new-account-rpm`(모델당 분당 20회)이 날 수 있습니다. 계약·모델 한계가 아닌 환경 오류이므로 `retry --task T --option <다른 계열 모델>` 후 재디스패치하고, 이후 웨이브는 동시 수를 2~3개로 줄이거나 한도가 느슨한 모델(M-Haiku-Balanced)로 보내십시오. 재시도 전 시도의 잔여물(`staging/incoming/<T>/`, `T.attemptN.jsonl`)은 남으니 새 `begin` receipt로 출력을 다시 쓰게 하십시오.
- `HTTP 402`(billing/credits exhausted)는 `429`(분당 호출 수 제한)와 다른 범주입니다: 429는 대기·분산으로 풀리는 일시적 혼잡이지만 402는 그 provider·모델 계정의 크레딧이 실제로 바닥난 것이라 같은 provider 뒤의 다른 모델로 바꿔도 재발하고 대기해도 안 풀립니다. 한 웨이브에서 동시 디스패치한 task 전부가 동일 모델로 402를 내면 즉시 재시도를 멈추고(`retry --task T`로 planned 되돌리기만 하고 재디스패치 보류), 사용자에게 "크레딧 충전 vs 다른 provider/모델로 전환" 중 선택을 물으십시오. 사용자가 충전을 기다리기로 하면 run은 그대로 두고(workflow·brief·질문은 보존됨) 중단 사실만 보고하고, 재개 신호를 받은 뒤에만 `next --dispatch`를 다시 돌립니다. 모델/provider를 바꿔 재시도했는데도 **다른** 모델이 수 초~십여 초 안에 또 402를 내면 그건 특정 모델이 아니라 **계정 전체(OpenRouter 등) 결제 문제**입니다 — 두 번째로 다른 provider로 더 바꿔보지 말고 바로 멈춰서 사용자에게 결제 상태를 물으십시오. 반대로 `HTTP 401`(`invalidated oauth token`, 특히 ChatGPT/Codex 구독 로그인)은 크레딧이 아니라 **그 provider 로그인 세션이 끊긴 것**이라 대기해도 재시도해도 안 풀립니다 — 그 task만 다른 provider/모델로 돌리고, 사용자에게 재로그인(`hermes auth add <provider> --type oauth`)이 필요할 수 있다고만 알리고 계속 진행하십시오(세션 전체를 막지 않음). 사용자가 유료 API가 아니라 구독제(예: ChatGPT Plus/Pro) 계정으로 전환했다고 알리면, 이후 402는 '쿼터 소진 → 리셋 대기'일 뿐이므로 리셋될 때까지 매번 보고하지 말고 조용히 재시도 간격을 두십시오. 같은 구독 계정이 `HTTP 429`(`usage limit reached ... resets in Xh`, rpm 혼잡 문구가 아니라 리셋 시각이 박혀 있는 형태)를 내는 경우도 성격은 402와 같은 **계정 단위 쿼터 소진**입니다 — 다만 리셋까지 1~2시간 걸리는 일이 흔하므로, 리셋을 기다리는 대신 바로 `retry --task T`로 planned 되돌린 뒤 **다른 provider 계열의 모델**(ChatGPT/Codex 계열이 막혔으면 Anthropic·DeepSeek 등 다른 option)로 재디스패치하면 대기 없이 즉시 풀립니다. 같은 task를 같은 구독 provider의 다른 모델로만 바꾸면 똑같이 막히므로, 반드시 provider 계열 자체를 바꾸십시오.
- 데이터셋 레인에 표 데이터가 없으면 `data-analyze`는 0건으로 자동 확장됩니다(정상). 공식 약관 기반 수치 비교는 extract→compare-matrix가 맡습니다.
- `next --dispatch`는 payload를 출력하는 순간 task를 `dispatched`로 표시합니다. 실제로 delegate하지 않고 미뤘다면 `retry --task T`로 planned로 되돌린 뒤 다시 `next`를 실행하십시오. 출력되는 payload는 계약서 전문이라 매우 길므로 `grep -v '^\[{'`로 가리고, `delegate_task`에는 계약서 경로만 가리키는 짧은 goal/context를 직접 넣어도 됩니다.
- **어떤 도구 호출이든** 문자열 파라미터에 한국어 등 비ASCII 텍스트를 넣을 때 `\uXXXX` 유니코드 이스케이프를 손으로 타이핑하지 마십시오(`delegate_task`의 `context`/`goal`뿐 아니라 `memory`/`context_notes`의 `content`·`old_text` 등 JSON 문자열을 받는 모든 파라미터에서 재발함). 오타가 나면 `delegate_task`처럼 전체 배치가 `Invalid \uXXXX escape`로 거부되지만, 오타가 **없어도** 손으로 계산한 코드포인트가 틀리면 거부 없이 그대로 통과해 `입력`→`입륥`처럼 조용히 다른 글자(mojibake)로 전달되거나(`memory patch`처럼 거부 자체가 없는 도구는 `old_text`가 저장된 원문과 바이트 단위로 안 맞아 "No entry matched"로 계속 실패), 거부되지 않았다고 맞았다는 보장이 없습니다. 평문 UTF-8 문자열을 그대로 파라미터에 적으십시오(도구가 JSON 인코딩을 처리합니다). `memory patch`가 "No entry matched"로 실패하면 바로 재시도하지 말고 에러의 `closest_entries`에 돌려주는 실제 저장된 원문을 그대로 복사해 `old_text`로 쓰십시오. 또한 `next --dispatch`가 낸 payload의 `goal`/`context`를 요약·축약해 손으로 다시 쓰지 말고, 짧게 줄이려면 `context`만 포인터 문장으로 압축하고 **`goal`은 payload의 원문 그대로 복사**하십시오 — goal을 임의로 다시 쓰면(예: 빈 문자열이나 "없음")  task 목적이 사라진 채 디스패치되어 자식이 빈 요청으로 즉시 실패하고 재작업이 필요합니다.
- `delegate_task`의 option 이름만 보고 provider를 추측하지 마십시오(이름 유사성은 provider와 무관). F 계열 중 `F-Sol-*`·`F-Sonnet-*`, M 계열 중 `M-Terra-*`·`M-Haiku-Quick`만 openai-codex/anthropic에 직결되고, `M-Haiku-Balanced`를 포함한 나머지 전부(F-DeepSeek/GLM/Qwen, M-DeepSeekPro, M-Qwen-Lite, L-GLM-Extract, Free-Nemotron, MM-*)는 OpenRouter 경유입니다(`M-Haiku-Balanced`도 `anthropic/claude-haiku-5.5`를 OpenRouter로 호출 — "Haiku=anthropic 직결"로 짐작하면 틀립니다). OpenRouter 크레딧 소진으로 특정 provider만 피해야 하는 상황이면, 실제 provider는 `/hermes-home/config.yaml`의 `delegation.backends.model_map.options[].provider` 필드를 직접 grep해 확인하고, 이름에서 유추하지 마십시오. 매번 손으로 대조하지 말고 바로 실행 가능한 한 줄을 써라: `grep -A2 "name: " /hermes-home/config.yaml | grep -B2 "provider: openai-codex\|provider: anthropic" | grep "name:"` 로 non-OpenRouter option 이름만 뽑아 `--available`에 넣으십시오(반대로 OpenRouter만 피하지 않고 완전히 배제해야 하면 이 결과가 바로 안전 목록입니다).
- scout 레인이 질문·brief에 명시된 **특정 후보 개체 목록**(브랜드·사이트 이름 등)과 무관하게 일반적인 주제 관련 문서(뉴스·판례·범용 FAQ)만 반환하면 coverage 게이트가 반복 실패해 scout가 계속 재개방됩니다. wave 2 이상의 scout task context에 "이전 wave에서 못 찾은 대상 개체 목록을 나열하고 그 개체 **자신의** 1차 문서(공식 정책·API 안내 등)를 찾아라"를 직접 추가하십시오 — 레인의 일반 안내문만으로는 모델이 범위를 좁히지 못합니다.
- 감사 findings의 `origin_merge`(block)는 같은 발행사 문서가 origin_group으로 쪼개져 독립 출처 수가 부풀려졌다는 뜻입니다. 추출 전에 부모가 `rlab source --id S --origin <통합그룹> set`으로 통합하십시오. 경량 workflow에서 adversary를 뺐다면 `challenge` 게이트 fail은 waive+limitations 대상입니다. 이 함정은 "같은 발행사가 쪼갠 문서"뿐 아니라 **부모 스스로가 만든 파생 문서**(예: 다른 run의 판정을 승계해 옮겨적은 메모, 여러 출처를 요약한 공통판정 메모)에도 똑같이 적용됩니다 — 원본과 그 원본을 요약·승계한 부모 메모를 등록할 때는 source-audit이 지적하기 전에 처음부터 같은 origin_group으로 등록하십시오. 등록 후 고치면 되지만, 처음부터 맞추면 한 턴을 아낍니다.
- scout를 `--drop`하고 부모가 후보/출처를 `rlab source add`로 직접 시드하는 fork(비전 분석·재평가 재작업 등)에서는, **이미 `next --dispatch`로 생성된 task의 `input/sources.jsonl`(또는 `candidates.jsonl`)이 시드 이전 시점의 스냅샷(흔히 0건)으로 굳어 있을 수 있습니다** — source-audit·extract-single 자식이 "입력이 비어 있다"는 빈 결과를 내는 원인입니다. `retry --task T`는 상태만 planned로 되돌릴 뿐 스냅샷을 재생성하지 않으므로, `rlab sql --recipe`나 직접 쿼리로 현재 ledger의 sources를 뽑아 **`tasks/<T>/input/sources.jsonl`을 수동으로 덮어쓴 뒤** 재시도·재디스패치하십시오(형식은 다른 run의 `tasks/*/input/sources.jsonl`을 참고 — 줄마다 순수 JSON 객체 하나, 줄번호나 구분자를 넣지 마십시오. `read_file`의 `N|내용` 표시는 도구 자체의 줄번호 표기일 뿐 파일에 저장된 문자가 아닙니다). 비전 분석(이미지 근거)을 텍스트 파이프라인에 통합하는 절차와 함께 `references/blocks-and-forge.md`의 '비전 근거 통합' 절을 참고하십시오.
- 수집 원문이 U+FFFD로 깨지면(예: m.hanacard.co.kr은 EUC-KR) 부모가 `curl` 후 `decode('euc-kr')`로 복구해 `staging/incoming/parent/`에 저장하고 `rlab source --file --url --title --tier --stance --origin --as-of add`로 새 출처를 등록한 뒤 `reopen --block extract-single`로 추출 wave 2를 돌리십시오. 깨진 출처를 그냥 두면 대표 후보 하나가 비교에서 빠집니다.
- `reopen` 이후에도 기존 분석 task의 `tasks/T/input/evidence.jsonl`은 갱신되지 않습니다. 새 근거(`is_null=0`)를 `ledger.sqlite`의 evidence+sources에서 같은 필드 형식으로 만들어 해당 질문 task 입력에 직접 추가한 뒤 디스패치하십시오(null 행은 원래 입력에서 제외됩니다).
- P6에서 부모가 직접 `deliverable.md`를 집필할 때 entity×Q 비교표를 claim 텍스트의 키워드(`"tier1"`, `"exclude"` 등) 단순 포함 여부로 분류하지 마십시오. `compare-matrix` 블록은 여러 개체를 한 문장에서 같이 언급하는 교차비교 claim(예: "A·B의 high 리스크... tier1 제외가 유지된다")을 만들며, 그 안에 다른 개체 이름이나 "tier1" 문자열이 섞여 있어 대상 개체를 혼동하게 됩니다. 개체별 최종 판정은 `SELECT id, text FROM claims WHERE question_id='Q7' AND text LIKE '<entity>%'`처럼 **그 개체 이름으로 시작하는** 전용 claim(주로 `block='compare-matrix'`)만 근거로 삼고, 교차비교 claim은 '비고'로만 인용하십시오.
- 수십~수백 개의 `resolve`/`source set` 같은 단발 CLI 호출을 쉘 for-루프로 돌리면 파이썬 기동 오버헤드(호출당 ~1-2초)가 쌓여 foreground 180초 타임아웃에 걸립니다. 타임아웃이 나도 루프 자체는 죽지 않고 이미 처리된 건은 상태가 바뀌어 있으므로, 같은 명령으로 다시 호출해 `gate`로 남은 건수를 확인하고 모자란 만큼 재실행하십시오(한 번에 다 끝내려 timeout_s를 무리하게 올리기보다 여러 호출로 쪼개는 쪽이 안전합니다).
- 자식이 제출한 JSONL의 `_meta` 첫 줄이 bash heredoc(`cat > f << EOF ... EOF`) 안에서 `$RECEIPT` 같은 셸 변수와 한글 텍스트(예: blocker 사유)를 함께 보간할 때, 내용 자체는 `cat`으로 봐도 정상처럼 보이는데 `check`가 `PROOF FAILED: missing _meta line`을 내는 경우가 있습니다(원인: 셸의 다국어 로케일·따옴표 처리가 바이트를 조용히 바꿀 수 있음, ASCII만 넣으면 같은 템플릿이 통과함으로 확인됨). 부모가 직접 JSONL 출력을 작성할 때(0행 처리, collect 대행 등) 한글이 들어가는 줄이 하나라도 있으면 heredoc 대신 `write_file` 도구로 파일 전체를 써서 이 문제를 피하십시오 — heredoc은 ASCII-only 내용에만 쓰십시오.
- adversary나 source-audit가 부모가 이미 수집한 API 사실(예: 특정 계정의 현재 게시물 수)에 대해 "웹검색 스니펫에서는 다른 값이 보인다"며 의문을 제기하면, 그 스니펫의 시점은 불명확하므로 스니펫을 바로 믿고 수치를 뒤집지 말고 **부모가 같은 API를 다시 직접 호출해 재확인**하십시오. API가 최초 수집값을 재확인하면 "조회 실패"가 아니라 "그 사이 콘텐츠가 실제로 사라짐/리셋됨"으로 결론을 정정하고, 이 결론을 `reports/`에 남겨 서브에이전트의 의문 제기를 근거 있게 종결하십시오.
- 스킬 파일 편집은 `skill_manage` 퍼지 패치뿐이라 인자가 조용히 지워질 수 있습니다. 편집 직후 컴파일과 `selftest.py`로 확인하고, 되돌릴 때는 `/hermes-home/skills/.curator_ledger.jsonl`의 전/후 sha256과 `/hermes-home/.curator_backups/blobs/<sha>` 원본을 기준으로 역패치한 뒤 파일별 해시를 대조하십시오. 자가개선(다른 세션의 큐레이터 편집)과 원본을 비교할 때도 같은 원장·blob을 쓰되 `evidence.session_id`로 자기 세션 편집을 제외하고 파일별로 줄 단위 diff를 집계하십시오(엔진·카탈로그가 바뀌었는지, 문서만 바뀌었는지를 먼저 봅니다). 스킬에 "반영되지 않았다"고 보고하기 전에 `grep -rn`으로 다른 스킬·references 전체를 검색하십시오(같은 기능이 별도 스킬에 있을 수 있습니다).
- 사용자가 한 run에 적용한 운영 정책 결정(예: 법적/윤리적 위험을 알고 수용하기로 한 결정)을 관련 run의 질문 판정에 "참고하라"고 지시하면, addendum.md에 그 결정을 **별도 절(§0 등)로 분리**해 "이 결정은 위험 수용 선택일 뿐이며 권리·적법성 판정 자체를 바꾸지 않는다"를 명시하십시오. 수집 수단 허용 여부(플랫폼이 우리 수단을 허용하는가)와 권리 사슬 판정(원저작자 권리가 유지되는가)은 서로 다른 축이므로, 하나의 정책 결정 맥락을 모든 질문에 뭉뚱그려 적용하면 서로 다른 질문의 판정이 오염됩니다. 어떤 질문에 영향을 주고 어떤 질문에는 주지 않는지 한 문장씩 못박아 디스패치 context에 포함시키십시오.
- 이전 세션(들)에서 이어지는 run의 현황을 사용자에게 보고·요약할 때는 `session_search`로 찾은 채팅 로그만 근거로 삼지 마십시오. 채팅 로그는 그 시점의 중간 상태일 뿐이고, 이후 세션에서 `rlab status`/`gate`로 실제 완료 여부가 바뀌었거나 `reports/deliverable.md`·프로젝트 로컬 노트 파일(`docs/*-local-notes.md` 등)에 최종 결론(제외/보류/완료 확정 등)이 이미 기록되어 있을 수 있습니다. 보고 전에 반드시 `$RLAB status`/`gate`로 현재 블록·게이트 상태를, `cat`으로 deliverable.md와 로컬 노트 파일을 직접 읽어 교차확인한 다음에 요약하십시오(채팅만 보고 상태를 단정하지 마십시오).
- robots.txt는 크롤러 관례 안내일 뿐이고, 대형 플랫폼일수록 서비스이용약관(ToS) 본문에 robots.txt와 무관하게 "데이터 스크레이핑"을 명시적으로 금지하는 별도 조항(예: Content Licensing/AI-Scraping Terms)을 두는 경우가 흔합니다. Q2(수집수단 허용여부)나 접근가능성 판정에서는, 공식 API 문서만 확인하고 실제로 쓸 접근 경로(웹페이지 직접 열람·RSS 등 API를 거치지 않는 우회 경로)의 ToS를 따로 안 보고 넘어가지 마십시오 — 실제로 데이터를 가져오는 그 경로 자체의 robots.txt와 ToS 본문을 둘 다 확인해야 "문제없음" 판정이 성립합니다.
- "접근권한 확보"·"권리 사슬 확인"과 "콘텐츠가 실제로 조사 목적에 맞는가"는 서로 다른 독립된 축입니다. 접근·권리 판정이 끝났다고 후보를 바로 확정하지 말고, 실측 샘플(실제로 긁어온 원문 일부)을 사람이 읽어 목적 적합성(예: "유머글 소싱"인데 실제로는 정치·시사 등 범용 인기글 집계인 경우)을 따로 확인하십시오. 채널·사이트 이름이나 소개문구("베스트 게시물 모아보기" 등)만 보고 목적에 맞다고 가정하면, 접근·권리가 전부 깨끗해도 막상 쓸 수 없는 후보를 다 조사한 뒤에야 걸러내는 식으로 시간을 낭비합니다.
- `forge --fork ... --drop <block>`로 블록을 뺐는데 그 블록이 **다른 블록의 `on_fail` 매핑**(`assets/blocks.json`의 `on_fail: {"coverage": "scout", ...}`)에서 재개방 대상으로 참조되고 있으면, 저장된 run의 `workflow.json`에 그 죽은 참조가 그대로 남아 soft gate 실패 시 `status`/`next`가 `bstate(run, tgt)["waves"]`에서 `TypeError: 'NoneType' object is not subscriptable`로 **크래시**합니다(드랍한 블록 이름이 에러 트레이스에 안 보여 원인 파악이 어려움). 조치: 크래시 전에 미리, 또는 크래시 직후 `grep -n '"on_fail"' <run>/workflow.json`으로 드랍한 블록을 가리키는 on_fail을 찾아 그 블록의 `"on_fail": {}`로 패치하십시오(구조 변경이 아니라 버그 수정이므로 "실행 중인 workflow.json 금지" 원칙의 예외입니다). scout를 자주 드랍하는 재평가용 fork(비전 분석 재판정 등)에서 특히 잘 터집니다.
- extract-single 자식이 **여러 개체(계정 등)가 섞인 단일 소스 문서**(예: 15개 계정 관찰노트 한 파일)를 받으면, 하나의 evidence 행에 `entity=null`로 두고 계정별 판정을 `note` 필드에 세미콜론으로 패킹해 제출하는 경우가 있습니다(check는 통과). 이 상태로 그대로 넘어가면 다음 단계(analyze-claims)가 패킹된 note를 다시 풀어내지 못하고 claim을 1~2건만 만듭니다. 새로 디스패치하는 wave라면 context에 "note 필드에 계정별 판정이 패킹되어 있으면 파싱해 계정당 별도 claim/evidence 행을 만들라"를 명시하면 즉시 해결됩니다. 문제는 **이미 `VERIFIED`로 커밋된 task**입니다 — `begin --task`가 정확히 `"ERROR: T#### is already verified"`로 거부해 재작업이 원천 불가능합니다. 이때는 부모가 해당 evidence의 `note`를 직접 파싱해 `claims`+`claim_evidence` 테이블에 누락 계정의 claim을 SQL로 직접 INSERT해 보완하되(기존 claim 행의 컬럼 구성을 그대로 모사), 이는 **독립 서브에이전트 코딩이 아니라 부모의 재서술**임을 addendum과 deliverable의 Limitations에 반드시 명시하십시오. 이 수동 INSERT는 두 가지를 반드시 같이 하지 않으면 뒤에서 터집니다: ① ID는 `run.nid("K")`(= `meta` 테이블의 `ctr:K` 카운터, `max(claims.id)`가 아님)가 발급하므로, 수동 INSERT 직후 `UPDATE meta SET v=<삽입한 최대 번호> WHERE k='ctr:K'`로 카운터를 올려두지 않으면 **다음에 정상 디스패치되는 analyze-claims/compare-matrix 자식**이 옛 카운터값으로 ID를 받아 `UNIQUE constraint failed: claims.id`를 내며 `check`가 실패합니다(원인이 한참 뒤의 자식 출력에서 터져 추적이 어려움 — 수동 INSERT를 했다면 즉시 카운터부터 맞추십시오). ② `claims.strength`는 enum(`weak|moderate|strong`)만 허용되며 `ctype` 값(`interpretation` 등)을 넣으면 insert 자체는 성공하지만 이후 `rlab status`/`next`가 `expand_block`의 `STRENGTH_ORDER[c["strength"]]`에서 `KeyError`로 **엔진 전체가 크래시**합니다. 수동 INSERT 전에 `SELECT DISTINCT strength FROM claims`로 허용값을 확인하고 그 집합 안에서만 쓰십시오.
- 여러 사이트가 **동일한 표준 ToS 템플릿**(한국 커뮤니티에서 흔한 "...영리목적으로 이용하거나 제3자에게 이용하게 하여서는 안됨" 같은 문구)을 그대로 돌려쓰는 경우, 한 조항의 문법적 모호성("영리목적으로"가 뒤의 "제3자에게 이용하게 하는 것"까지 수식하는지)은 그 템플릿을 쓰는 사이트들 전체에 동일하게 적용됩니다. 이때 템플릿을 쓰는 사이트 중 한 곳이 별도 공지·FAQ에서 같은 금지를 더 명시적인 말(예: "영리 또는 비영리 목적으로... 제3자에게 제공하지 않습니다")로 풀어놓았다면, 그 명시적 문구를 **같은 템플릿을 쓰는 다른 사이트들의 모호성 해소 근거로도** 쓸 수 있습니다 — 사이트별로 따로 법률 자문을 구하는 것보다 비용이 훨씬 적게 들고, 표준 조항의 통상적 해석(제3자 이용 금지는 영리·비영리 불문)을 교차 확인하는 효과가 있습니다.

## Verification

- `$RLAB doctor` → `RESULT OK`; `python $SK/scripts/selftest.py` → `SELFTEST PASS`(합성 데이터 end-to-end, 부정 경로 포함).
- run 종료 시: `next`가 `ALL DONE`, `gate`에 미승인 fail 없음(waive는 사유와 함께 limitations에 기재), `report`의 limitations 절이 산출물에 반영됨.
- 산출물의 모든 사실 문장이 `[K....]` → `claim_evidence` → `evidence.quote` → `raw/S....txt`로 역추적되는지 `sql`로 표본 확인(SQL 근거는 quote가 아니라 `sql`+`result_sha`를 재실행해 확인).
- `retro` 후 `wf list`에서 해당 workflow의 runs·fitness가 갱신됨.

## Files

- `scripts/rlab.py` + `scripts/rlab_core/` — forge, library, runtime, ingest, gates, lake, cli
- `assets/blocks.json` — 블록 카탈로그(실행 단계의 정의·조건·게이트) · `assets/routing.json` — 역할→option 후보 · `assets/traits.example.json`
- `templates/brief.md` · `templates/questions.example.jsonl`
- `references/trait-rubric.md` — 도메인·방향 traits 판정표 · `references/blocks-and-forge.md` — 블록·합성 규칙·확장
- `references/crew-contracts.md` — 역할·라우팅·계약·수신증·실패 분류 · `references/data-lab.md` — 원장·lake·SQL
- `references/gates-grading.md` — 증거 등급·주장 상태·게이트 · `references/retro-learning.md` — 환류·적합도·한계 · `references/playbooks.md` — 실제 forge 결과 예시
- `references/person-profile-research.md` — 인물·페르소나 고증(창작용) 운영 규칙: 시작 확인, 질문 설계, 수집 경계, 채널·댓글·멤버십 코퍼스, 표집 함정, 합성 전 점검
- `references/local-asr-farm.md` — 로컬 GPU ASR(Qwen3-ASR + vLLM 서버) 기동법·함정(무작위 초기화 로드, FlashInfer, ffmpeg 세그폴트, 엔진 정체와 감독기)과 pyannote 화자 분리(GPU 배타·OOM·라벨 과분할)
- `references/codebook-iteration-lessons.md` — 코드북 개정 루프(서브에이전트 승인 심사 운영, 보정·예시, 단서-행동 대비 설계, 마스킹·감사, 패스 분리, 운영 산출물[계약서·검증기·묶음 생성기] 구현 검증, 보류 표본[고정 N·층별 부모 기준·가림 패킷·manifest] 검증 설계)
- `references/personality-frameworks.md` — 성격 연구 프레임워크 기반 표집 단위·청중 조건·코드북 설계·검토·재시험 · `references/external-stt.md` — 외부 STT 후보 선정·ZDR·제한·계약 시험·비용 계산·키 취급
