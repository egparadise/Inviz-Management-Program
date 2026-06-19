---
name: inviz-business-query
description: 인비즈 회사 데이터에 대한 비즈니스 질문에 답한다. 매출/매입/계약/거래처/차입금/문서 관련 자연어 질의를 받아 SQLite·RAG·LLM을 조합해 정확한 답변 + 출처 + 페이지 링크 제공.
---

인비즈 경영관리 데이터에 대한 자연어 질문에 답하는 표준 절차.

## 호출 흐름

1. **빠른 매칭** — 키워드가 명확하면 즉시 SQL 응답 (~5ms)
2. **모호하면 RAG** — 벡터 DB에서 관련 청크 retrieval
3. **LLM 답변** — 컨텍스트 + 질문 → 자연어 답변
4. **출처 인용** — [자료 1], [자료 2] 형식 + 페이지 URL

## 키워드 → 도메인 매핑 (fast match)

| 키워드 | 의도 | DB 테이블 |
|---|---|---|
| 매출, 판매 | search_sale | fact_sale |
| 매입, 구매, 원가 | search_purchase | fact_purchase |
| 거래처, 병원, 회사명 | search_party | dim_party |
| 계약, 약정 | search_contract | master_contract |
| 인증서, 특허, 공증, 사업자등록증, 납세증명 | search_document | document |
| 차입금, 대출, 은행 | search_loan | master_loan |
| 급여, 인건비 | search_payroll | fact_payroll |
| 직원, 사원 | search_employee | dim_employee |
| KPI, 현황, 요약 | kpi | (다중 집계) |

## 기간 키워드 자동 변환

- "이번 달" → from = 이번달 1일, to = 말일
- "지난 달" → 전월 1일~말일
- "이번 분기" → Q1/Q2/Q3/Q4 시작~끝
- "올해" / "당해" → year = 현재 연도
- "최근 N일" → today-N ~ today
- "YYYY년" → year=YYYY, "M월" → month=M
- "N일 이내 만료" → expiring_within_days=N

## SQL 패턴

### 매출/매입 합계
```sql
SELECT COUNT(*), SUM(supply), SUM(vat), SUM(total)
FROM fact_sale
WHERE year=? AND month=? AND party_name LIKE ?
```

### 거래처 TOP
```sql
SELECT party_name, COUNT(*), SUM(supply)
FROM fact_sale
WHERE year=? AND party_name NOT IN ('합 계','합계','소계','총계')
GROUP BY party_name
ORDER BY SUM(supply) DESC LIMIT 10
```

### 만료 임박 문서
```sql
SELECT name, doc_type, expiry_date
FROM document
WHERE expiry_date BETWEEN date('now') AND date('now', '+30 days')
ORDER BY expiry_date
```

### KPI 종합
```sql
-- 연간
SELECT
  (SELECT SUM(supply) FROM fact_sale WHERE year=?) as sales,
  (SELECT SUM(supply) FROM fact_purchase WHERE year=?) as purchases,
  (SELECT SUM(current_balance) FROM master_loan) as loan_balance,
  (SELECT COUNT(*) FROM master_contract WHERE status='진행') as active_contracts
```

## RAG 검색 절차

LLM 의도 분류가 모호하거나 자유 질문일 때:
1. 질문 → bge-m3 임베딩
2. FAISS top-6 청크 retrieval (지식 4 + 학습된 대화 2)
3. min_score 0.3 필터링
4. 컨텍스트 빌드 (최대 1500 토큰)
5. LLM (llama3.1 또는 GLM)에 system+user 프롬프트

## LLM 프롬프트 템플릿

```
[system]
당신은 한국 의료 IT 회사 인비즈(Inviz)의 경영관리 비서입니다.
[참고 자료]만 근거로 한국어로 답하세요.
자료에 없으면 "자료에 없습니다"라고 답하세요.
숫자는 콤마와 단위(원/건/명)로 명확히. 2~5문장 간결.
마지막에 [자료 N]으로 인용.

[user]
[참고 자료]
{context}

[질문]
{query}
```

## 응답 형식

답변 구조:
1. **핵심 수치** (큰 글씨, 강조)
2. **세부 내용** (테이블·리스트)
3. **출처** (인용된 자료 번호)
4. **페이지 링크** (→ /sales?year=2024 등)
5. **메타** (모델, 소요 시간, 토큰)

## 데이터 정합성

- "합 계", "합계", "소계", "총계" 행은 항상 제외
- NULL 거래처는 필터링
- web_app 입력 데이터(`source_file='web_app'`)는 신뢰도 높음
- 동일 거래처가 다른 표기로 중복될 수 있음 (예: "써밋영상의원" vs "써밋영상")

## 자가 학습

답변 후 사용자가 👍 누르면:
- `chat_history.user_feedback = 'good'`
- `chat_history.is_indexed = 'Y'`
- 백그라운드로 `conv_faiss` 컬렉션에 임베딩 추가
- 다음 유사 질문에 우선 retrieval
