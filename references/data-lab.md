# Data Lab: 원장·Parquet·DuckDB

## run 트리 (`<lab home>/runs/<run_id>/`, `init --root`로 프로젝트 폴더 지정 가능)

```
brief.md  workflow.json  ledger.sqlite        # 원장(쓰기 진실), 트랜잭션으로만 변경
raw/          S0001.txt (정규 텍스트, 불변)  S0001.orig.html ...
staging/      incoming/<task>/ (수집자 저장)  out/<task>.jsonl (자식 출력)  dispatch_NNN.json
tasks/<T>/    contract.md  input/*
lake/         analysis.duckdb  parquet/<table>.parquet  datasets/<name>.parquet  .rev
reports/      deliverable.md  status.md  retro.json
```

원칙: **SQLite는 쓰기**, **DuckDB·Parquet는 분석(읽기 전용, 언제든 재생성 가능)**. lake는 원장 `rev`가 바뀌면 `sql` 실행 시 자동 재빌드됩니다(`lake build`로 수동 가능).

## 원장 테이블

`questions`(id,parent,kind,labels,label_defs) · `candidates`(scout 결과, status new/assigned/collected/unreached) · `sources`(tier 1-4, stance, origin_group, lane, as_of, pii_status, seq, status active/dropped) · `chunks`(원문 조각, substring 검색) · `datasets`(표 데이터 프로파일) · `evidence`(quote|sql, label, polarity, entity/attribute/value_num/unit/as_of, coder, is_null) · `claims`(ctype, strength, scope, falsifier, status…) · `claim_evidence`(supports|refutes) · `challenges` · `contradictions`(open|resolved|disclosed) · `findings` · `tasks`(status, receipt, attempts, rows_*) · `block_state` · `rejects` · `waivers` · `events`(감사 로그).

편의 뷰: `v_evidence`(evidence+출처 tier/stance/origin_group/lane/url), `v_claims`(+지지·반박·반증 수). 데이터셋은 **이름 그대로 테이블**로 로드됩니다(예: `SELECT engine, avg(ms) FROM bench GROUP BY 1`).

## SQL

- `rlab sql --run R "SELECT ..."` / `--recipe coverage|source_mix|origin_share|saturation|agreement|claims|entity_matrix|timeline|contradictions|tasks|rejects` / `--format json|csv` / `--limit N` / `--hash`.
- 읽기 전용 가드: 단일 문, SELECT/WITH/DESCRIBE/SHOW/PIVOT/SUMMARIZE/FROM만, `read_*`·`copy`·`attach`·`pragma` 등 차단, DuckDB `enable_external_access=false`. 더 넓은 작업(학습·시각화)은 `lake/parquet/*.parquet`를 polars·duckdb로 직접 열어 별도 스크립트로 수행하고, 결과를 신규 근거로 남기려면 SQL 근거(아래)로 재현 가능하게 만드십시오.
- **SQL 근거**: DataAnalyst가 `sql`+`result_sha`(`--hash`가 출력, 행 순서 무관·소수 6자리 반올림 기준)를 제출하면 `load`가 데이터셋에 재실행해 해시가 다르면 거부합니다. 데이터셋은 등록 시 DuckDB로 Parquet 변환·프로파일(행·열·null·표본) 생성, 프로파일은 출처 텍스트(`raw/S*.txt`)로도 저장됩니다.

## 엔진 변경을 기존 run 원장으로 평가하기

- 실제 `runs/*/ledger.sqlite`는 열어 두지 말고 읽기 전용 URI로 연결해 사본을 만든 뒤 사본에만 질의하십시오: `sqlite3.connect(f'file:{src}?mode=ro', uri=True).backup(dst_conn)`. 평가가 끝나면 사본을 지웁니다(연구 자료가 들어 있음).
- 변경 전 동작이 만든 행을 변경 후 규칙으로 분류할 때, 출처 표기(`contradictions.note` 등)가 과거 `resolve --note`에 덮여 있으면 행 단위 귀속이 불가능합니다. 이때는 claim 단위로 보수적으로 분류하십시오(그 claim의 챌린지가 모두 `stands`/`inconclusive`면 "새 규칙에서는 생성되지 않음", weakened/refuted가 하나라도 있으면 "판별 불가, 제외", 챌린지 없는 행은 분석가 기원으로 영향 없음). 수치에는 정의를 함께 적고 이전에 보고한 다른 정의의 수치와 섞어 비교하지 마십시오.
- 순방향 수정은 과거 행을 바꾸지 않습니다. 원장 이관은 별도 설계 없이 하지 마십시오.

## 불변식

- **역추적 경로**: quote 근거는 `[K] → claim_evidence → evidence.quote → raw/S*.txt`(원문 부분 문자열), SQL 근거는 `[K] → claim_evidence → evidence.sql/result_sha → datasets/<name>.parquet`(재실행 해시). SQL 근거의 quote 필드는 재현 문자열이며 raw 텍스트의 부분 문자열이 아닙니다.
- 증거의 `quote`는 적재 시점에 `raw/S*.txt`에서 검증되었고 `raw`는 바꾸지 않는다 → 날짜·해시로 언제든 재검증 가능.
- 주장 상태는 저장값이 아니라 `claim_evidence`·`sources`·`contradictions`에서 재계산됩니다(`source set/drop`, `resolve` 후 자동).
- `source drop`: 해당 출처의 evidence·chunks·연결을 제거하고 원문 파일을 비웁니다(PII 차단용, 되돌리지 않음).
