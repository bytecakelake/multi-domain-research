# Crew: 역할·라우팅·계약·수신증

## 역할

| role | 하는 일 | 원칙 |
|---|---|---|
| Scout | 출처 후보만(본문 추출 금지) | 레인별 병렬, 이미 수집한 URL과 겹치면 제외 |
| Collector | 원문을 텍스트로 저장 + sources 행 | 변형 금지, PII 표시, 표 데이터는 `kind=dataset` |
| Extractor A/B | 코드북 기반 근거 추출 | **A와 B는 서로 다른 모델 계열**, 서로의 결과·가설을 모름 |
| DataAnalyst | DuckDB SQL로 정량 질문 계산, 재실행 가능한 SQL 근거 | `rlab sql --hash`로 결과 해시를 만든 뒤 제출 |
| Analyst | **근거 ID만** 보고 주장 작성 | 원문 전체 열람 금지(확증 편향 차단) |
| Adversary | 반증: 틀렸다면 있어야 할 자료를 먼저 정의하고 찾음 | **Analyst와 다른 계열**, 못 찾았음도 결과 |
| Auditor | 출처 풀·원장의 편향·독립성 감사 | 통계 중심 |
| Critic / Reviewer | workflow 비판 / 산출물 문장↔근거 대응 검토 | 부모와 다른 시각(권장: 다른 계열) |
| Parent | 분해·판정·산출물 작성·종합 | 인용·SQL·receipt 기계 검증은 `load`가 수행 |

## 라우팅

`assets/routing.json`은 role→option 후보 목록이며 **활성 여부의 증거가 아닙니다**. 매 run `next --available "<현재 delegate_task option 이름들>"`로 실제 활성 목록과 대조하십시오(없으면 `option`이 비고 사유가 출력됩니다. 존재하지 않는 이름으로 조용히 대체하지 마십시오). 승격은 실패 원인이 모델 한계로 확정된 뒤 `retry --option`으로만 합니다. 실제로 실행된 모델은 `subagent-orchestration` 스킬의 manifest 확인 절차로 검증합니다.

## 계약(contract) 해부

`next`가 task마다 `tasks/<T>/contract.md`와 `tasks/<T>/input/*`를 생성합니다. 계약서는 자급적입니다: 목표, brief 요약, 질문 트리, 입력(절대경로+sha), 방법 지침, 출력 파일 하나, 행 스키마와 예시, 필수 절차(begin → 작성 → check), 금지 항목. `delegate_task`로는 **포인터만** 보냅니다(부모 토큰 절약; 자식은 같은 파일시스템에서 계약서를 읽습니다). 자식이 파일을 읽지 못하는 환경이면 `next --full`로 전문을 페이로드에 넣으십시오.

**디스패치 상태와 ASCII 페이로드(E2)**: `next --dispatch`는 task를 `ready`(페이로드에 실렸을 뿐 위임 미확인)로 바꾸고 `dispatch_emitted` 이벤트와 `staging/dispatch_NNN.json`을 남깁니다(`tasks.dispatched`는 비워 둡니다). `ready` task는 다시 내보내지 않고 `next`가 `[EMITTED, NOT CONFIRMED]`로 나열하며, `max_parallel`·`max_per_option` 계산에는 진행 중으로 셉니다. `delegate_task`를 실제로 호출한 뒤 `rlab dispatched --payload dispatch_NNN.json`(또는 `--task T` 반복)으로 `ready → dispatched`를 확정합니다(자식의 `begin`도 확정합니다; 이미 dispatched/returned는 조용히 통과, 다른 상태가 하나라도 있으면 전체 거부). 위임하지 않기로 했다면 `rlab unready --payload ...`(또는 `--task`)로 `ready → planned`로 되돌립니다(attempts·receipt 불변, `dispatch_cancelled` 이벤트; `retry`는 위임했는데 실패한 시도에 씁니다: `ready` 상태에서 `retry`하면 위임된 것으로 기록되므로 위임 시점의 402처럼 자식이 `begin`하지 못한 실패도 결제 중단 판정에 포함됩니다). 페이로드의 `goal`/`context`는 task id·블록·역할·`contract.md` 절대경로만 담은 **ASCII 고정 문장**이므로 손으로 다시 쓰지 말고 `next`가 출력한 JSON을 그대로 전달하십시오(한글 목적·목표는 `contract.md`와 페이로드 `meta`에만 있고 `meta`는 `delegate_task`로 보내지 않습니다). 전문이 필요하면 `next --full`. run id와 `RLAB_HOME` 경로가 ASCII여야 이 보장이 성립하며, 아니면 `next`가 stderr에 경고합니다. `--dispatch` 없는 `next`는 `dispatch_dryrun.json`에만 씁니다.

## 수신증(receipt)과 기계 검증

1. 자식이 `begin --task T` 실행 → `receipt = sha256(run_key | task | input_sha)[:12]`(run_key는 원장에만 있어 추측 불가).
2. 자식의 유일한 출력 `staging/out/T.jsonl`의 첫 줄 `{"_meta":{"task","receipt","n_rows"}}`.
3. 자식이 `check`로 드라이런(커밋 없이 거부 사유를 행 번호와 함께 출력) → `CHECK OK`까지 수정.
4. 부모가 `load`: receipt·n_rows 확인 → 행별 스키마·인용 원문 일치·SQL 재실행 해시·코드북 라벨·ctype 상한·근거 존재 검사. 거부율 ≤ `max_reject_rate`(5%)면 커밋, 초과면 전체 롤백(`status=failed`, 거부 사유는 `rejects` 테이블).
5. `--accept-rejects`는 거부 행을 버리고 나머지만 커밋합니다(사례를 limitations에 기록). `--force-unproven`은 receipt가 없는 출력을 부모가 무증명으로 받는 예외이며 task notes에 `unproven`이 남습니다.

## 실패 분류

**빈 결과**: 자식이 의도적으로 0행을 보고할 때는 meta에 `"n_rows":0,"empty":true,"blocker":"사유"`를 씁니다(그렇지 않은 빈 파일은 `no valid rows`로 실패). blocker는 task notes에 남습니다. **재위임 불가 환경**에서는 부모가 계약서를 순서대로(begin→작성→check→load) 직접 수행할 수 있으나 독립 모델 검토가 아니므로 limitations에 기록합니다. `--available ""`(빈 목록)는 '활성 option 없음'으로 처리되어 option이 비워집니다. claims·evidence 등 블록에 섭인 findings는 `{"kind":"findings","type":"evidence_gap",...}` 형태입니다.

| 증상 | 원인 분류 | 조치 |
|---|---|---|
| PROOF FAILED | 실행 없이 지어냈거나 파일이 잘림 | `retry`; 반복되면 해당 role 모델 상향 |
| 거부율 초과: `not found verbatim` 다수 | 모델이 인용을 재구성 | 계약에 "원문 그대로 복사" 강조, batch 축소, 필요 시 상위 모델 |
| `label not in codebook` | 코드북 불명확 | questions의 `labels`/`label_defs` 보강 후 새 task |
| `ctype not allowed` | 방향 상한 위반 | 방향을 바꾸지 말고 주장 유형을 낮추도록 지시 |
| 도구·권한·네트워크 오류 | 환경 | 환경 수정 또는 blocker 보고(모델 승격으로 숨기지 않음) |

재시도는 원인 수정 1회 후 재평가가 기본입니다. 같은 구조적 실패가 반복되면 중단하고 계약을 고치거나 승격하십시오.

**자동 분류·동시성·중단(E3)**: `retry`는 사유(`--note`, 없으면 이전 notes)를 패턴으로만 분류해 retry 이벤트에 `failure_class/failure_kind/class_source`로 남기고, 분류가 확실할 때만 notes 앞에 `[env:billing]` 같은 태그를 붙입니다(원문은 변경하지 않음). 분류: `env`(billing=HTTP 402·크레딧 소진, rate_limit=HTTP 429·usage limit, auth=HTTP 401, network=timeout·5xx) / `output`(rejected·proof — 텍스트만으로는 계약 결함인지 모델 한계인지 모름) / `unknown`(태그 없음). `env`는 모델 실패로 세지 않으며 승격 근거가 아닙니다. 사람이 원인을 확정했으면 `retry --cause env|contract|model`이 패턴보다 우선합니다. `next`는 option별 동시 실행(ready+dispatched+returned)을 `params.max_per_option`(기본 3)으로 제한하고, 한도에 걸린 task는 planned로 남아 `capped`(CLI에는 슬롯 대기 목록)로 보고됩니다(option이 없는 task는 제한 없음, `max_parallel`은 별도로 유지). 같은 (block, wave)의 미검증 task가 2개 이상이고 모두 마지막 retry가 같은 option의 `env/billing`이면 meta `halt`가 설정되어 `next`가 dispatch를 내지 않고 `[HALT]`를 출력합니다(단일 task·429·401은 중단하지 않음). 사용자가 충전 또는 다른 provider를 선택한 뒤 `rlab resume --reason "..."`로 해제합니다(`resume` 이벤트 기록, 활성 halt가 없으면 오류).

## 보안 한계 (정직한 범위)

- receipt는 **실행 없이 지어낸 출력**을 걸러내는 장치입니다. 같은 파일시스템을 쓰는 악의적 자식이 `ledger.sqlite`에서 run_key를 읽으면 위조할 수 있습니다. 즉 사고 방지용이지 적대적 통제가 아닙니다. 인용·SQL 검증은 위조 여부와 무관하게 독립적으로 동작합니다.
- 자식 제공 `path`는 `staging/incoming/` 아래로만 허용됩니다(비밀 파일을 원장에 끌어오는 것 차단). 부모의 `source add`만 임의 경로를 수용합니다.
- 심각한 보안 통제가 필요한 조사는 run 디렉터리를 자식에게 공유하지 않는 별도 격리(도커·복사본 작업공간)가 필요합니다.
