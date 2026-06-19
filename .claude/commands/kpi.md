---
description: 인비즈 KPI 종합 조회 — 매출/매입/이익/차입금/계약/만료임박 한 번에
---

인비즈 경영관리 시스템의 현재 KPI를 조회합니다.

대상 연도: $1 (없으면 현재 연도)

다음 단계로 조회:

1. SQLite로 직접 KPI 측정 (`web_app/app.db`):
```sql
SELECT
  (SELECT SUM(supply) FROM fact_sale WHERE year=?) as sales,
  (SELECT SUM(supply) FROM fact_purchase WHERE year=?) as purchases,
  (SELECT SUM(gross_pay) FROM fact_payroll WHERE year=?) as payroll,
  (SELECT SUM(current_balance) FROM master_loan) as loan_balance,
  (SELECT COUNT(*) FROM master_contract WHERE status='진행') as active_contracts,
  (SELECT COUNT(*) FROM document WHERE expiry_date BETWEEN date('now') AND date('now','+30 days')) as docs_expiring_30d;
```

2. 도메인별 TOP 5 거래처:
```sql
SELECT party_name, SUM(supply) FROM fact_sale
WHERE year=? AND party_name NOT IN ('합 계','합계','소계','총계')
GROUP BY party_name ORDER BY 2 DESC LIMIT 5;
```

3. 결과 요약:
- 매출 / 매입 / 매출이익 / 이익률
- 인건비 / 영업이익
- 차입금 잔액
- 진행 중 계약 / 만료 임박 문서

콤마와 단위(원, 건) 포함. 전년 대비 YoY 변화도 함께.
