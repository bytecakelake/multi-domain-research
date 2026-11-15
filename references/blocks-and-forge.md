# 블록 카탈로그와 합성 규칙

workflow = traits에서 선택된 **블록의 DAG**. 정의는 `assets/blocks.json`, 합성 코드는 `scripts/rlab_core/forge.py`.

## 블록

| 블록 | phase | role | fanout | 포함 조건(when) |
|---|---|---|---|---|
| intake, qtree | design | Parent | single | 항상 |
| workflow-critic | design | Critic | single | stakes=high 또는 라이브러리에 유사 workflow가 없음(novel) |
| access-broker | acquire | Parent | single | access∈{mixed,gated} |
| scout | acquire | Scout | per_lane | 항상 (max_waves 3, small이면 2) |
| collect | acquire | Collector | candidate_batch | 항상 |
| source-audit | acquire | Auditor | single | noise≥med 또는 stakes=high |
| privacy-gate | acquire | Parent | single | ethics≥personal_data |
| extract-dual | extract | Extractor | source_batch (A/B 블라인드) | verifiability=interpretive 또는 stakes=high 또는 mode∈{evaluate,explain} |
| extract-single | extract | Extractor | source_batch | 위의 여집합 |
| data-analyze | analyze | DataAnalyst | per_data_question | quant (질문 kind∈measure,compare,trend,rank) |
| analyze-claims | analyze | Analyst | per_question | 항상 (근거 ID만 보고 주장 작성) |
| compare-matrix | analyze | Analyst | single | mode∈{compare,evaluate} |
| timeline-build | analyze | Analyst | single | temporal |
| rival-hypotheses | analyze | Analyst | per_question | mode∈{explain,verify} 또는 stakes=high |
| base-rates | analyze | Analyst | single | mode=forecast |
| adversary | challenge | Adversary | claim_batch | stakes≥med 또는 noise≥med 또는 mode∈{verify,explain,evaluate} |
| bias-audit | challenge | Auditor | single | verifiability=interpretive 또는 noise≥med |
| synthesize | synthesize | Parent | single | 항상 (citation·contradictions 게이트) |
| qa-review | synthesize | Reviewer | single | stakes=high |
| retro | learn | Parent | single | 항상 |

core 블록(intake, qtree, analyze-claims, synthesize, retro)은 `--drop` 할 수 없습니다. `extract-*`가 하나도 없으면 forge가 실패합니다.

## 합성 순서

1. `norm_traits`: 누락 값에 기본값, 열거 값 검증, quant↔tabular 일치.
2. 라이브러리 매칭(`distance`): mode 0.30, modality(Jaccard) 0.15, verifiability·stakes·quant 각 0.10, 나머지 0.05. `≤0.25`이면 유사(→ fork 권장), 아니면 novel.
3. 블록 선택: 각 블록의 `when` 술어를 평가 + `--add/--drop` 적용. 탈락 사유는 spec의 `excluded`에 기록.
4. 의존성 해석: `needs`의 `extract-*` 같은 와일드카드는 선택된 블록으로 치환, 선택되지 않은 선행은 조용히 생략. 순환이면 실패.
5. 파라미터 파생(`derive_params`): lanes, batch_size(6|10), overlap_frac(0.15|0.25), kappa_min(0.6|0.7), min_independent(2|3), max_origin_share(0.5|0.4), saturation window(5|8), freshness_days, allowed_ctypes.
6. 예산 트리밍(`budget_tasks`): qa-review → bias-audit → rival-hypotheses → workflow-critic → source-audit → timeline-build → compare-matrix 순으로 제거(`--add`된 것은 유지). **트리밍은 위험 감수이므로 사용자에게 탈락된 블록을 보고하십시오.**
7. saturation 게이트는 volume=small 또는 mode=verify에서 제거.
8. `--set key=value`(JSON 값): 전역 파라미터(`kappa_min=0.8`) 또는 블록 파라미터(`scout.max_waves=1`, `extract-dual.batch_size=4`).

추정치(`estimate.dispatch_tasks`)는 계획용이며 실측이 아닙니다(출처 수·질문 수 가정이 spec에 기록됨).

## fanout 의미

- `per_lane`: 레인마다 1 task · `candidate_batch`: 신규 후보를 batch로 묶음 · `source_batch`: 아직 추출 안 된 정상(pii clear) 출처를 batch로 묶음(dual이면 겹치는 출처는 A·B 둘 다, 나머지는 A/B 교차 배정; 겹침은 출처 id 해시로 결정적).
- `per_question`: 근거(또는 주장)가 있는 최상위 질문마다 1 task, 근거 수가 바뀌면 새 task가 생김 · `claim_batch`: 미반증 주장을 강도순으로 묶음 · `per_data_question`: 데이터셋이 있고 kind∈measure|compare|trend|rank인 질문.
- 모든 fanout은 **데이터 기반 지연 확장**이라 재개방(새 wave)에서 새 입력만 처리합니다.

## 블록 추가·수정(카탈로그 확장)

`assets/blocks.json`에 항목을 추가합니다. 필드: `id, phase, role, fanout, kind(candidates|sources|evidence|claims|challenges|findings), needs[], when, gates[], soft_gates[], on_fail{gate:block}, params{}, purpose, goal, guide`. `when` 문법: `"always"` | `{"t":trait, eq|ne|in|has|gte|lte: v}` | `{"all":[..]}` | `{"any":[..]}` | `{"not":..}` (`gte/lte`는 trait의 순서 척도: stakes, noise, ethics, volume, volatility, verifiability, access). 새 role이면 `assets/routing.json`에 후보를 추가하십시오. 새 수집 행 종류가 필요하면 `ingest.py`에 adder를 추가해야 합니다(스키마 힌트는 `runtime.SCHEMA_HINTS`). 변경 후 `selftest.py`를 실행하십시오. **카탈로그를 고치면 이미 저장된 workflow는 영향을 받지 않습니다**(spec가 블록 정의를 복사해 둔다).

## fork 운영 (범위·접근·규모가 바뀔 때)

`--fork <id>` 전에 `ls workflows/<id>.json`으로 해당 파일이 실제로 디스크에 있는지 먼저 확인하십시오. `wf match`/`wf list`는 레지스트리(sqlite) 인덱스만 읽으므로, 이전에 보관을 그만둔(아카이브·삭제) 된 workflow도 distance 계산에 계속 나타납니다. 이 상태에서 `--fork`하면 레지스트리는 살아있고 파일만 없어 `FileNotFoundError`로 즉시 죽습니다. 파일이 없으면 포기하고 `forge`로 새로 합성하십시오(해당 workflow와 거리가 가까워도 대안이 없으면 자연스러운 일입니다).

실행 중인 run의 workflow는 고칠 수 없으므로 traits를 갱신한 JSON으로 `forge --traits t2.json --fork <parent> --name <new>`를 씁니다.
- fork는 `novel=false`라 **`workflow-critic`이 빠집니다**(포함 조건이 novel 또는 stakes=high). 규모·접근 방식이 바뀐 설계는 재검토가 필요하므로 `--add workflow-critic`으로 되살리십시오. `access`를 mixed/gated로 올리면 `access-broker`(부모 전용)가 자동으로 붙습니다.
- `--set questions_est=<실제 최상위 질문 수>`로 질문 수 가정(기본 5)을 맞추고, `forge --no-save`로 추정 task 수를 확인한 뒤 저장하십시오. 사용자가 말한 목표 규모(task 수)와 추정이 다르면 차이를 보고합니다.
- 새 run에는 이전 run의 후보·처분표·addendum이 **자동으로 넘어오지 않습니다**. 필요한 것은 복사하십시오: addendum·`critic_dispositions.md`는 파일 복사, scout 후보는 `ledger.sqlite`의 `candidates` 테이블을 JSONL로 내보내 `reports/`에 두고 새 scout의 seeds·부모 `source add` 참고용으로 씁니다. 옛 run은 수정하지 않습니다.

### 새 세션에서 run을 이어가겠다고 할 때 (fork 여부 무관)
사용자가 "새 세션에서 실행, 기존 세션은 유지"를 요구하면 현재 세션에서는 workflow 저장·`init`(P3까지)·입력 준비만 하고 **실행(`next`)은 하지 않습니다.** lab home에 인수인계 문서(`handoff-<run>.md`: 상태, 사용자 결정, 권장 순서, 주의점, 변경 이력)를 쓰고, 새 세션에 붙여넣을 시작 프롬프트를 채팅에 제시하십시오. 멤버십·쿠키 같은 허가는 문서에 사실로 적되, 프롬프트에는 **사용자 본인의 허가 문장**으로 넣어 새 세션이 사용자에게서 직접 받은 허가로 처리하게 합니다. 허가 조건이 바뀌면 brief·task 사본·인수인계 문서·프롬프트를 모두 같이 고치고 변경 이력을 남기십시오.

이 패턴은 fork 전용이 아니라 **이미 init된 run을 P4 중간(예: workflow-critic·access-broker 대기)에서 멈추고 다음 세션에 넘길 때도 그대로 적용**됩니다. 이때 인수인계 문서에는 추가로: (a) 직전 run의 결론 중 이번 run의 특정 질문 판정 기준으로 쓰일 구체 데이터(예: 비교 대상 목록·판정표)를 본문에 직접 인용해 다음 세션이 다시 찾지 않게 하고, (b) 사용자가 승인한 운영 정책이 이번 run의 어떤 질문에는 적용되고 어떤 질문과는 **별개 축**인지 한 문장으로 구분해 적습니다(예: "위험 수용 결정"은 플랫폼 ToS 준수 여부 판정과는 무관하지만 권리 귀속 판정의 맥락 설명에는 영향). 다음 세션은 이 구분을 addendum.md에 그대로 옮겨 적어 서브에이전트가 두 질문을 혼동하지 않게 합니다.

### 부모 직접 시드 패턴 (scout를 빼고 고정 후보로 재평가할 때)

이전 run에서 이미 확정된 후보 목록을 재평가만 하려면(발굴 범위는 그대로, 판정 방식만 보강), `--drop scout`으로 재발굴을 막고 부모가 `rlab source add`로 후보·출처를 직접 심습니다. 이때 **반드시** 아래 순서를 지키십시오 — 순서를 어기면 source-audit·extract-single이 빈 입력으로 끝납니다:
1. `init`으로 run을 만든 직후 `next --dispatch`를 한 번 돌리면 workflow-critic·source-audit 같은 task가 먼저 생성됩니다. 이 시점의 `tasks/<T>/input/sources.jsonl`은 **아직 출처가 없으므로 비어 있습니다.**
2. 출처를 다 심기 전에 생성된 task는 `retry --task T`로 planned에 되돌려도 입력 스냅샷이 자동으로 다시 만들어지지 않습니다. 부모가 `ledger.sqlite`의 `sources` 테이블을 직접 쿼리해 JSONL로 만들고 `tasks/<T>/input/sources.jsonl`을 수동으로 덮어쓴 뒤에 재디스패치하십시오(스키마는 기존 run의 `tasks/*/input/sources.jsonl` 아무 파일이나 참고 — `id,kind,title,url,tier,stance,origin_group,lane,as_of,n_chars,text_path,sha256_12` 키의 JSON 한 줄당 한 객체이며, `read_file`이 보여주는 `N|` 줄번호는 표시용일 뿐 실제 파일에는 없습니다).
3. 순서를 뒤집어 **출처를 전부 심은 뒤에** `next --dispatch`를 돌리면 이 수동 작업이 필요 없습니다. 이미 task가 생성된 뒤라면 2번 방법으로 복구하십시오.
4. `--drop scout` 자체가 `status`·`next`를 **크래시**시킬 수 있습니다: `extract-single`(그리고 다른 블록)의 `on_fail`은 `{"coverage": "scout", "saturation": "scout"}`처럼 soft gate 실패 시 재개방할 대상을 정적으로 `scout`로 못박아 두는데, scout를 drop하면 그 블록이 run의 block 목록에 없어 `bstate(run, "scout")`가 `None`을 반환하고 엔진이 `TypeError: 'NoneType' object is not subscriptable`로 죽습니다(`status`·`next` 둘 다 영향받음 — 이 run은 완전히 멈춥니다). 증상이 나오면 run의 `workflow.json`에서 drop한 블록을 가리키는 `on_fail` 항목을 찾아(`grep -n '"scout"' workflow.json`) 해당 블록의 `on_fail`을 `{}`로 고치십시오. 이는 구조 변경(블록 추가·삭제)이 아니라 drop이 남긴 댕글링 참조를 없애는 버그 수정이므로 "실행 중인 run의 workflow.json을 고치지 마십시오" 규칙의 예외입니다. 수정 후 soft gate는 그냥 실패로 기록되고 limitations에 남습니다(재개방 없이 진행 가능).

### 비전(이미지) 근거를 텍스트 파이프라인에 통합하는 패턴

모달리티에 `media`를 추가하면 forge가 `media-transcripts` 레인을 자동으로 엽니다. 이미지 자체를 서브에이전트에게 주지 말고(원본 미디어 저장 금지 원칙과 충돌하고, 인용 검증이 텍스트 연속부분문자열 기준이라 이미지와 맞지 않음) 다음 순서로 통합하십시오:
1. 부모가 이미지 URL을 직접 열람(`vision_analyze`)하고, 계정·게시물 단위로 관찰 내용을 **서술형 텍스트 문서**("비전 관찰노트")로 작성합니다.
2. 이 문서를 `rlab source add`로 **일반 텍스트 출처**처럼 등록합니다(origin은 `parent_vision_analysis` 등으로 통일 — 관찰자가 부모 1인이므로 계정마다 origin을 쪼개 독립 출처처럼 꾸미지 마십시오).
3. extract-single·analyze-claims는 이 문서를 다른 텍스트 출처와 똑같이 읽고 인용·추출합니다 — 비전 모델이나 이미지 전달 없이 기존 인용 검증 구조를 그대로 쓸 수 있습니다.
4. 어떤 게시물의 어느 이미지 URL을 몇 장 열람했는지는 별도 "표본 명세" 문서(`parent://sample_manifest` 같은 origin)로 같이 등록해, 추출·분석 단계가 표본 범위(계정당 N장)를 근거 강도 판단에 반영하게 하십시오. 미디어가 0장인 개체는 "증거 없음"이 아니라 "확인불가"로 구분해야 합니다(없는 콘텐츠로 단정하지 말 것).
5. 비전 관찰노트가 **여러 개체(계정 등)를 한 문서에 묶어** 서술하면(예: 15개 계정을 한 파일에 섹션별로 기록), extract-single은 evidence 스키마가 행당 quote/entity 하나뿐이라 모든 개체의 판정을 **evidence 1행의 `note` 필드에 세미콜론으로 익어넣는** 경향이 있습니다(quote·entity는 처음 한 개체 것만 채워지고 나머지 14개는 note 텍스트 속에만 존재). 그 결과 `per_question` analyze-claims가 패킷된 note를 다시 풀어내지 못하고 claim을 1~2건만 만뒭니다. **새로 디스패치할 wave라면** delegate_task의 `context`에 "note 필드에 개체별 판정이 패킷되어 있으면 파싱해 개체당 별도 claim/evidence 행을 만들라"를 명시하면 즉시 해결됩니다(본 workflow에서 실제로 활용한 문구). 문제는 **이미 `VERIFIED`로 커밋된 task**입니다 — 이 경우의 복구 절차(부모 직접 INSERT, nid 카운터 전진, strength enum 제약)는 SKILL.md Pitfalls의 해당 절을 참조하십시오.

## 저장되는 spec (`workflows/<name>-vN.json|md`)

`traits, params, blocks[](needs 해석됨, why 포함), excluded[], estimate, overrides{add,drop,set}, warnings, novel, parent, forged`. fork는 parent의 overrides를 상속하고 새 버전을 만듭니다(리네지 추적).