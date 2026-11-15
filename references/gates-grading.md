# 증거 등급·주장 상태·게이트

## 출처 tier

1 = 원본·1차(원자료·당사자 직접 산출물·공식 일차 기록) · 2 = 권위 2차(심사 논문·공식 문서·편집 통제 있는 보도) · 3 = 파생·집계(위키·요약·재인용) · 4 = 의견·커뮤니티. **같은 원천을 재인용한 글은 `origin_group`이 같아야 합니다**(독립성은 origin_group 개수로 세며, source-audit가 오류를 잡습니다). 위키·커뮤니티는 '누가 그렇게 본다'는 증거이며 사실로 승격하려면 1차 자료가 필요합니다.

## 주장 상태(자동 재계산)

| 상태 | 조건 (min_independent = 2, stakes=high면 3) |
|---|---|
| supported | 지지 근거의 독립 origin_group ≥ min_independent 그리고 최고 tier ≤ 2 |
| partial | (최고 tier ≤ 2 이고 근거 1개 이상) 또는 (tier 무관 독립 원천 ≥ min_independent) |
| weak | 지지 근거는 있으나 위 조건 미충족 |
| contested | 미해결(open) 모순이 있음(반증자가 찾은 반대 근거 또는 분석자가 연결한 counter_evidence) |
| unsupported | 유효한 지지 근거 없음 |

확정 불가 상태를 산출물에서 삭제하지 마십시오. 라벨(확인/부분/미확인/반박)로 남깁니다. ctype 상한: strong은 fact·measurement만.

## 게이트

| gate | 실패 조건 | 기본 임계 | 흔한 처방 |
|---|---|---|---|
| receipts | proof_failed task 존재 | 0 | retry |
| reject_rate | 블록 누적 거부율 초과 | 5% | 계약·batch 조정 |
| kappa | 이중 코딩 겹침 단위(출처×질문)의 Cohen κ 미달. 단위 5개 미만이면 `na`(유도 불가) | 0.6 (high 0.7) | label_defs 보강, 재코딩 1회, 그래도 미달이면 해당 질문 판정을 분석에서 제외 |
| coverage | 최상위 질문의 독립 origin_group < min_independent 또는 tier ≤2 근거 없음(하위 질문 근거 포함) | 2 (high 3) | soft: scout 자동 재개방(max_waves까지) |
| saturation | 최근 window개 출처가 도입한 신규 코드(질문·라벨·엔티티)가 임계 초과 | ≤1 / 5개 | soft: scout 재개방 |
| independence | 최대 origin_group의 근거 점유율 초과(근거 6개 미만이면 na) | 50% (noise high 40%) | soft: counter-view·source-audit 보강 |
| claim_support | strong인데 supported가 아닌 주장, 또는 주장 0개 | 0 | 근거 보강(새 analyst wave) 또는 `rlab downgrade --claim K.... --strength moderate --reason "..."`(부모 전용, 강도를 낮추는 것만 허용, 사유는 claim scope·감사 로그에 남음). `waive`로 덮지 마십시오 |
| challenge | 강도 ≥ moderate 주장 중 반증 기록이 없는 것 | 100% | adversary 추가 task |
| contradictions | moderate 이상 주장에 open 모순 | 0 | `resolve --status resolved|disclosed` (사유 필수) |
| citation | deliverable이 없거나, 존재하지 않는 `[K....]` 인용, 인용 0개, Limitations 절 없음(제목 줄에 `Limitations`·`한계`·`제한` 중 하나가 있으면 인정 — `## 3. 한계`, `## 4. 연구의 한계와 제언` 등 번호·한국어 제목 허용). **구조 검사만 합니다**(문장별 인용 여부·의미 일치는 보증하지 않음; `uncited_lines`는 정보용) | — | 산출물 수정, 문장↔주장 수동 검토 |
| pii | pii_status=flagged 출처 존재 | 0 | `source drop` / `set --pii clear` |

hard 게이트는 블록 완료를 막고, soft는 재개방 또는 limitations 기록으로 끝납니다. `waive`는 모든 게이트에 대해 가능하지만 항상 `report`의 limitations에 나타납니다. 임계는 workflow `params`이며 `--set`으로 바꿉니다. 기본값은 경험적 출발점이고 많은 run으로 보정된 값이 아닙니다.

## 모순(contradictions) 해소

challenge verdict가 `weakened`/`refuted`일 때만 `refutes` 링크와 open contradiction이 생깁니다. `stands`/`inconclusive`는 모순을 만들지 않으며, 참조한 evidence id는 challenge note 끝의 `[rlab challenge-context v1] {"evidence_ids": [...]}` 줄에 보존되고 `inconclusive`는 limitations에 나타납니다. 따라서 verdict별 일괄 분류(claim_id→verdict 사전)는 쓰지 마십시오(claim당 challenge가 여러 건이면 덮어씁니다). open 모순은 `rlab resolve --id X.... --status resolved|disclosed --note "..."`로 하나씩 해소하며, 원래 provenance note는 유지되고 사유는 `contradiction_resolved` 이벤트로 기록됩니다.
