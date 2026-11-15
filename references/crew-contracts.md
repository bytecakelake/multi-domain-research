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

## 보안 한계 (정직한 범위)

- receipt는 **실행 없이 지어낸 출력**을 걸러내는 장치입니다. 같은 파일시스템을 쓰는 악의적 자식이 `ledger.sqlite`에서 run_key를 읽으면 위조할 수 있습니다. 즉 사고 방지용이지 적대적 통제가 아닙니다. 인용·SQL 검증은 위조 여부와 무관하게 독립적으로 동작합니다.
- 자식 제공 `path`는 `staging/incoming/` 아래로만 허용됩니다(비밀 파일을 원장에 끌어오는 것 차단). 부모의 `source add`만 임의 경로를 수용합니다.
- 심각한 보안 통제가 필요한 조사는 run 디렉터리를 자식에게 공유하지 않는 별도 격리(도커·복사본 작업공간)가 필요합니다.
