# 02. 데이터베이스 스키마

SQLite `app.db` — 17개 테이블, 7,678행 (개발 완료 시점).

## DIM (기준 정보, 5개)

### dim_party (984)
거래처 마스터 — 병원·대리점·공급사
- PK: `code` (C0001~C9999)
- `name`, `biz_no`, `category`, `active`, `first_seen`, `last_seen`

### dim_product (10)
제품 — Cloud Care Life, Saintview PACS, Vision Maker, Ai Echo Care, AI CXR/MMG, CR 장비, 유지보수, 출장서비스, 기타
- PK: `code` (P001~P999)

### dim_employee (56)
- PK: `code` (사번 — IV_X 또는 E000X)
- `hire_date`, `resign_date`, `active`, `pension_enrolled`

### dim_account (21)
계정과목 — 4101 제품매출, 4102 상품매출, 5101 원재료비 등

### dim_department (5)
연구개발 / 영업 / 서비스 / 관리 / 어플리케이션

## FACT (트랜잭션, 9개)

### fact_sale (5,409)
매출 트랜잭션
- `txn_date`, `year`, `month`, `quarter`, `half`
- `party_code` → dim_party
- `product_code` → dim_product
- `supply`, `vat`, `total`
- `sale_type` (정기/신규/일회성/기타)
- `source_file`, `source_sheet`, `source_row` (변조 감지용)

### fact_purchase (2,221)
매입 트랜잭션 — fact_sale와 동일 구조

### fact_payroll (616)
급여 — period (YYYY-MM), employee_code, basic, meal, car, gross_pay, deductions, net_pay

### fact_expense (311), fact_receivable (133), fact_loan (128), fact_rental (49), fact_severance (550), fact_reading (0)

## 마스터 (3개)

### master_contract (299)
- PK: `id` (K-YYYY-XXXX)
- start_date, end_date, contract_amount, unpaid_amount, status (진행/만료/해지)

### master_loan (25)
차입금 마스터 — 은행/개인/사채/임원
- institution, current_balance, interest_rate, end_date

### master_product_mapping (13)
품명 → 제품코드 자동 매핑 룰
- pattern (정규식), product_code, priority

## 운영·AI·자가발전 (6개)

### file_registry (505)
추적 파일 메타
- `path` (절대), `rel_path`, `mtime`, `size_bytes`, `sha256`
- `domain` (매핑된 도메인), `is_latest_for_domain`
- `status`: new/changed/processed/error/unmapped

### sync_run / sync_run_detail
동기화 실행 이력 — 매 sync 1행
- files_processed, files_errored, rows_added, rows_removed
- status: success/partial/failed/rolled_back

### document (85)
인증서·특허·공증·납세증명 등
- name, doc_type, issuer, issue_date, expiry_date, file_path

### knowledge_chunk (1,321)
RAG 청크 메타 (실제 임베딩은 FAISS)
- source_type: party/product/contract/document/sale_monthly 등
- content, token_count, embedding_status, vector_id

### chat_history
모든 챗 Q&A 이력
- query, intent, response_summary, model_used
- tokens_input, tokens_output, elapsed_ms
- user_feedback (good/bad), is_indexed

### integrity_check
무결성 검증 결과 — 매 sync 후 행 추가
- run_id, table_name, metric, before_value, after_value, delta_pct
- status: ok/warning/critical/rolled_back

### unmapped_file_review
LLM 자동 분류 검토 대기열
- file_name, suggested_domain, confidence, llm_reasoning
- status: pending/approved/rejected/auto_processed

## 인덱스

```sql
CREATE INDEX ix_fact_sale_year ON fact_sale(year);
CREATE INDEX ix_fact_sale_month ON fact_sale(month);
CREATE INDEX ix_fact_sale_txn_date ON fact_sale(txn_date);
CREATE INDEX ix_fact_sale_party_code ON fact_sale(party_code);
CREATE INDEX ix_dim_party_name ON dim_party(name);
CREATE INDEX ix_file_registry_path ON file_registry(path);
-- (모든 외래키와 자주 조회되는 컬럼)
```

## 외래키 무결성

SQLite는 기본적으로 FK 검증 OFF. SQLAlchemy ORM 레벨에서 관계 정의되어 있음:
```python
party_code: Mapped[Optional[str]] = mapped_column(String(10), ForeignKey("dim_party.code"))
```

데이터 정합성:
- party_code는 NULL 허용 (거래처 미매칭 가능)
- 매칭된 경우는 dim_party.code 존재 보장
