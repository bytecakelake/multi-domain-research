# Retro: 라이브러리로 환류하는 방식과 한계

## 무엇이 저장되는가 (`<lab home>/registry.sqlite`, `workflows/`)

- `workflows`: id(`name-vN`), parent(리네지), domain/direction 라벨, traits, spec 경로.
- `runs`: run_id, workflow_id, metrics(JSON), `score`(사용자 0-5, 선택), `proxy`(프로세스 지표 0-1).
- `lessons`: `lesson`(사람이 쓴 교훈) 및 `mutation`(규칙 기반 변이 제안), 태그=mode·domain·direction·사용자 태그.

## 다음 forge가 쓰는 방식

`forge`/`wf match`는 저장 workflow들과 traits 거리를 계산하고(동률이면 fitness 높은 것 우선), 거리 ≤0.25인 후보가 없으면 `novel`로 표시해 workflow-critic를 켭니다. 매칭된 workflow의 교훈과 같은 mode·domain·direction 태그의 교훈이 정보로 출력됩니다. **자동으로 workflow를 고치지는 않습니다.** 부모가 제안을 읽고 `forge --fork <id> --set/--add/--drop`으로 새 버전을 만듭니다.

## fitness는 무엇인가 (정직하게)

- `score`(사용자 평가)가 있으면 `score/5`, 없으면 `proxy`를 사용하고 평균합니다.
- `proxy` = 0.35×(게이트 통과 비율; waived는 0.5) + 0.25×(주장 지지 점수: supported 1, partial 0.6, contested 0.3) + 0.2×(1−5×거부율) + 0.2×(1−재작업률). **결과의 진실성이 아니라 실행 프로세스의 건전성 지표입니다.** run이 적을 때는 순위를 결정하는 근거로 쓰지 마십시오(유사도가 같은데 점수가 다른 두 후보를 고를 때의 타이브레이커 정도).
- 정확도·비용 절감 같은 효과는 실측 전에 주장하지 마십시오. 비용은 현재 task 수·재작업률만 기록합니다(토큰·금액은 기록하지 않음).

## 변이 제안 규칙 (`runtime.suggestions`)

coverage 실패 → scout 레인 추가/max_waves ↑ · kappa 실패 → label_defs·batch_size↓·overlap_frac↑ · saturation 미달 → max_waves↑ · independence 실패 → source-audit 추가 · challenge 미완 → adversary batch↓ · 거부율>10% → 계약 보강·모델↑ · 재작업률>30% → 해당 role 라우팅↑ · contested 존재 → rival-hypotheses·bias-audit 추가.

## 교훈 작성 기준

일회성 사실이 아니라 **재사용 가능한 규칙 + 왜**를 한 줄로(예: "커뮤니티 레인은 tier 4로만 쓰고 coverage 세에서 제외: 홍보글 재인용이 독립 출처로 집계되었음"). `--tag`로 domain/direction 외 태그를 다면 다른 workflow에서도 매칭됩니다. 재사용 가능한 절차 개선은 이 스킬(`SKILL.md`·`references/`)에 반영하고, run 상태는 원장에 남깁니다.
