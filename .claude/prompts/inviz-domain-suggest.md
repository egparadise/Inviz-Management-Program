---
name: inviz-domain-suggest
description: 임의의 시트(헤더+샘플 행)를 받아 매출/매입/급여/비용 중 어느 도메인인지 + 컬럼 매핑을 JSON으로 출력하는 LLM system+user 프롬프트
type: prompt
used-by:
  - routers/ai_classify.py:_llm_classify
  - routers/ai_classify.py:ai_classify_suggest_domain
  - routers/ai_classify.py:_run_multi_sheet_job
output-mode: json_object
temperature: 0.1
max-tokens: 600
---

# 인비즈 도메인 추정 프롬프트

## System
```
당신은 한국 의료 IT 회사 인비즈(Inviz)의 경영관리 데이터 분류 비서입니다.
JSON으로만 답하세요.
```

## User Template
```
아래 파일의 헤더와 샘플 행을 보고 어떤 도메인인지 판단하고,
각 도메인 필드가 어느 헤더에 매핑되는지 알려주세요.

[헤더]
{headers}

[샘플]
{sample_rows}    # 최대 5행, "행 i: 컬럼=값, ..." 형식

[가능한 도메인]
- sale: 매출 — 필드: txn_date, party_name, party_code, product_code,
        item_raw, sale_type, supply, vat, payment_method, note
- purchase: 매입 — 필드: txn_date, party_name, party_code, product_code,
            item_raw, purchase_type, supply, vat, payment_method, note
- payroll: 급여 — 필드: period, employee_name, employee_code, department,
           basic, allowance, gross_pay, total_deduction, net_pay
- expense: 비용 — 필드: use_date, employee_name, department, party_or_place,
           amount, payment_method, category_main, category_sub, note

[출력 JSON 형식]
{
  "domain": "sale|purchase|payroll|expense|unknown",
  "confidence": 0.0~1.0 사이 숫자,
  "reason": "한국어로 판단 이유 한 문장",
  "column_mapping": {
    "도메인_필드명": "원본_헤더명 (없으면 빈 문자열)"
  }
}

JSON만 출력. 마크다운 코드블록 사용 금지.
```

## 사용 예시

### 매출 입력
- 헤더: `[일자, 거래처명, 거래처코드, 공급가액, 부가세, 품명, 매출유형, 결제수단, 비고]`
- 샘플: `2024-03-15 써밋영상의원 C0123 2500000 250000 ...`

### 응답 예시 (95% 신뢰도)
```json
{
  "domain": "sale",
  "confidence": 0.95,
  "reason": "의료기관 거래처를 대상으로 한 소프트웨어/서비스 정기료 데이터로, 공급가액·부가세·매출유형 등 매출 거래의 특징을 명확히 보여줍니다.",
  "column_mapping": {
    "txn_date": "일자",
    "party_name": "거래처명",
    "party_code": "거래처코드",
    "supply": "공급가액",
    "vat": "부가세",
    "item_raw": "품명",
    "sale_type": "매출유형",
    "payment_method": "결제수단",
    "note": "비고"
  }
}
```

## 안전장치 (코드에서 적용)
1. **JSON 추출**: `re.search(r"\{[\s\S]*\}", resp)` — 코드블록·잡음 제거
2. **도메인 정규화**: `DOMAIN_SCHEMAS`에 없으면 `unknown`으로 강등
3. **매핑 검증**: 응답의 헤더명이 실제 헤더 리스트에 있는지 확인 → 없으면 빈 문자열
4. **자동 적재 조건**: `confidence >= 0.7` AND 필수 필드 모두 매핑됨

## 변경 이력
- 2026-06-19 초안 — 단일 시트 추정 + 멀티시트 자동 처리에 동일 프롬프트 재사용

## 관련 자산
- [[inviz-business-context]] — LLM에 비즈니스 맥락 주입 (선택적)
- [[inviz-multi-sheet-classifier]] — 이 프롬프트를 시트마다 호출하는 에이전트
