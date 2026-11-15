# Traits 판정표: 도메인·방향을 숫자가 아니라 성질로 서술하기

forge는 "어떤 도메인인가"가 아니라 **이 조사가 어떤 성질을 가졌는가**로 블록을 고릅니다. 도메인이 생소해도 아래 질문에 답할 수 있으면 workflow가 나옵니다. `domain`·`direction` 문자열은 자유 라벨(라이브러리 검색·교훈 태그용)이며 블록 선택에는 쓰이지 않습니다.

## 필드

| trait | 값 | 판정 질문 |
|---|---|---|
| `mode` (방향) | explore, describe, compare, explain, evaluate, verify, forecast, design | 결과물이 *지형도* / *현상 서술* / *대안 비교* / *인과 설명* / *좋고 나쁨 판정* / *사실 검증* / *미래 예측* / *설계안* 중 무엇인가? 하나만 고릅니다. |
| `modality` | web, academic, social, tabular, code, media, legal, human_subject, local (복수) | 근거가 어느 종류의 자료에 있는가? 각각 수집 레인이 하나씩 생깁니다. `tabular`는 quant와 SQL 분석 레인을 켭니다. `local`은 사용자가 이미 가진 파일·내부 자료만 쓰는 조사(웹 탐색 없음)입니다. |
| `verifiability` | checkable, mixed, interpretive | 정답이 외부에 존재하는가(checkable), 해석이 판정을 좌우하는가(interpretive)? interpretive면 블라인드 이중 코딩과 κ가 켜집니다. |
| `stakes` | low, med, high | 잘못된 결론의 비용이 시간 손실(low) / 금전·평판 손실(med) / 복구 불가·안전·법적(high)인가? high면 평론가 검토·경쟁 가설·독립 QA·κ 0.7·독립 출처 3개가 적용됩니다. |
| `volume` | small(~20개 출처), medium(~80), large(~250) | 목표 출처 규모. 예산 추정·배치 크기·포화 윈도우·재개방 한도에 쓰입니다. |
| `volatility` | static, slow, fast | 정답이 얼마나 빨리 냡는가? fast면 신선도 기간(90일)이 반증 계약에 들어갑니다. |
| `noise` | low, med, high | 홍보·조작·재인용 증폭·SEO 스팸이 얼마나 섞여 있는가? med 이상이면 출처 감사·편향 감사·반증이 켜집니다. |
| `ethics` | none, personal_data, sensitive, safety_critical | 개인정보·민감정보·안전 문제가 걸려 있는가? personal_data 이상이면 privacy-gate가 켜집니다. |
| `access` | open, mixed, gated | 로그인·멤버십 출처가 필요한가? mixed/gated면 부모 전용 access-broker가 켜집니다(자식에게 자격증명을 주지 않음). |
| `quant` | true/false (생략 시 tabular 여부) | 숫자·표 데이터를 계산해야 답이 나오는 질문이 있는가? |
| `temporal` | true/false | 시간 순서·변화 시점이 답의 핵심인가? 켜면 timeline-build가 추가됩니다. |
| `budget_tasks` | 정수 또는 null | 서브에이전트 task 상한. 초과 추정이면 덜 중요한 블록부터 트리밍하고 경고합니다. |

## 방향(mode)이 정하는 추론 상한

허용 claim 유형(`allowed_ctypes`)이 한계를 정하고 적재 단계에서 자동 거부됩니다. `strong` 강도는 fact/measurement만 가능합니다.

| mode | 허용 ctype | 방향이 켜는 블록 |
|---|---|---|
| explore, describe | fact, measurement, interpretation | (기본만) · 포화 재개방 |
| compare | + inference | compare-matrix, counter-view 레인 |
| explain | + inference | rival-hypotheses, adversary, 이중 코딩, counter-view |
| evaluate | + inference | compare-matrix, adversary, 이중 코딩, counter-view |
| verify | fact, measurement, inference | rival-hypotheses, adversary, counter-view (포화 게이트 없음) |
| forecast | + forecast | base-rates |
| design | fact, measurement, interpretation, inference | (기본만) |

## 새 도메인을 만났을 때(7질문)

사용자에게 묻거나 brief에서 추론하십시오. 모르면 추측하지 말고 비용이 큰 쪽으로 두고 근거를 적습니다.
1. 결과물은 무엇이고 누가 어떤 결정에 쓰는가? (→ mode, stakes)
2. 근거는 어떤 자료 형태에 있는가? (→ modality, quant)
3. 정답이 외부에 존재하는가, 해석인가? (→ verifiability)
4. 가장 신뢰할 수 있는 출처 1순위는 무엇이고 얼마나 쉽게 얻는가? (→ access, tier 사다리, coverage 기준)
5. 이 분야의 함정은 무엇인가? 홍보·재인용·편향·생존자 편향 (→ noise, counter-view)
6. 정답이 얼마나 빨리 변하는가? (→ volatility, temporal)
7. 다루면 안 되는 정보는 무엇인가? (→ ethics, brief의 금지 범위)

판정 후 한 줄 근거를 traits 파일 옆(또는 brief)에 남기면 retro 때 잘못 잡은 trait를 찾을 수 있습니다.
