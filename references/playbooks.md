# Playbooks: 실제 forge 결과 예시

아래는 `rlab forge`가 낸 실제 구성입니다(라이브러리가 비어 있는 상태, `novel=true`; 추정 task 수는 출처 규모·질문 5개 가정의 계획용 값). 같은 도메인이어도 방향이 달라지면 workflow가 달라집니다. 모든 값은 출발점이며 P1의 판정을 대신하지 않습니다.

| 사례 | 핵심 traits | 블록 구성(실행 순서) | 추정 |
|---|---|---|---|
| **인물 고증 · describe** | modality=media+social+web, interpretive, stakes=low, noise=med, ethics=personal_data, access=mixed, temporal | intake, qtree, workflow-critic, access-broker, scout, collect, source-audit, **privacy-gate**, **extract-dual**, analyze-claims, timeline-build, adversary, bias-audit, synthesize, retro | ~47 |
| **OSS 기술 · compare** | web+code+tabular, checkable, stakes=med, volatility=fast, quant | intake, qtree, workflow-critic, scout, collect, **extract-single**, **data-analyze**, analyze-claims, **compare-matrix**, adversary, synthesize, retro | ~40 |
| **정책 · explain (고위험)** | legal+academic+web, mixed, stakes=high, noise=high, volume=large, temporal | intake, qtree, workflow-critic, scout, collect, source-audit, extract-dual, analyze-claims, timeline-build, **rival-hypotheses**, adversary, bias-audit, synthesize, **qa-review**, retro | ~121 |
| **시장 · forecast** | web+tabular, checkable, stakes=med, volume=small, volatility=fast | intake, qtree, workflow-critic, scout, collect, extract-single, data-analyze, analyze-claims, **base-rates**, adversary, synthesize, retro | ~22 |

해석:
- 인물 고증은 사실 검증보다 *인식·서술 일관성*이 핵심이므로 이중 코딩(κ)과 편향 감사가 중심이고, 비공개 신상 차단(privacy-gate)이 필수입니다. 로그인·멤버십 출처는 부모만 다룹니다.
- OSS 비교는 정답이 외부에 있어 단일 코더 + 기계 검증으로 충분하고, 벤치마크는 데이터셋으로 들여와 SQL 재현 근거로 남깁니다. 비교 행렬이 산출물의 핵심입니다.
- 고위험 정책 해석은 경쟁 가설과 독립 QA까지 켜지고 비용이 크게 오릅니다. `budget_tasks`로 상한을 주면 일부 블록이 트리밍되지만 보고되므로 사용자가 위험을 수용할지 결정합니다.
- 시장 예측은 base-rates가 시작점이고 예측 주장(ctype=forecast)은 moderate 이하로만 허용됩니다.

실제로 재현하려면 `assets/traits.example.json`을 복사해 값을 바꾸고 `forge --no-save`로 미리보기 하십시오.
