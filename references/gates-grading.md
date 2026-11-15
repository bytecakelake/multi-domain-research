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

## 모순(contradictions) 일괄 해소

adversary wave가 끝나면 **verdict가 `stands`(반증 실패)인 challenge도** claim마다 `contradictions` 행을 만듭니다 — "그 주장에 반증을 시도한 이력이 있다"는 사실 자체가 공개 대상이기 때문이며, weakened/inconclusive만 모순이 아닙니다. 그래서 반증 8건 중 7건이 `stands`로 끝나도 수십 건의 `open` contradiction이 한꺼번에 쌓일 수 있습니다. 하나씩 사유를 다시 쓰지 말고, `challenges.verdict`로 일괄 분류해 해소하십시오:

```python
import duckdb
con = duckdb.connect('<run>/ledger.sqlite', read_only=True)
verdicts = dict(con.execute("SELECT claim_id, verdict FROM challenges").fetchall())
conts = con.execute("SELECT id, claim_id FROM contradictions WHERE status='open'").fetchall()
# stands -> resolved(반증 자료를 못 찾아 주장 유지), weakened/inconclusive -> disclosed(약화·불확정, deliverable에 공개)
```
이렇게 만든 `(id, status, reason)` 목록을 `rlab resolve --id X.... --status resolved|disclosed --note "..."`로 터미널 배치 호출하십시오(호출이 많으면 위 '단발 CLI 호출' 타임아웃 주의사항을 따라 여러 번에 나눠 돌리고 `gate contradictions`로 남은 건수를 확인합니다).
