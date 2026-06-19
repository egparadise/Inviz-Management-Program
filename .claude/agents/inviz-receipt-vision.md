---
name: inviz-receipt-vision
description: 영수증 사진을 받아 OpenAI/Anthropic Vision으로 일자·금액·사용처·결제수단·분류·품목을 JSON으로 추출하는 에이전트. 모바일 카메라 촬영 + 데스크탑 업로드 모두 지원.
type: agent
tools: [llm_provider.analyze_receipt_image, fact_expense 적재]
trigger:
  - 사용자가 영수증 사진 업로드
  - /expense/receipt 에서 분석 버튼 클릭
fallback-chain: [OpenAI gpt-4o-mini, Anthropic Claude Haiku, 수동 입력]
---

# 인비즈 영수증 Vision 에이전트

## 워크플로

```
📷 사진 입력 (file upload | camera capture)
    ↓
1. /expense/receipt/analyze POST (multipart)
    ↓
2. uploads/expense_receipts/YYYYMMDD_HHMMSS_*.jpg 저장 (감사용)
    ↓
3. llm_provider.analyze_receipt_image(bytes, mime)
    ├ OpenAI Vision (gpt-4o-mini) — 1순위
    └ Anthropic Vision (Claude Haiku 4.5) — fallback
    ↓
4. JSON 응답
    {
      "date": "YYYY-MM-DD",
      "amount": 12500,
      "supply": null|10000,
      "vat": null|1000,
      "place": "스타벅스 강남점",
      "payment_method": "법인카드|현금|이체|개인지출|체크카드|기타",
      "category_main": "운영비|인건비|판매관리비|R&D|기타",
      "category_sub": "회식·접대|...",
      "items": "주요 품목 요약",
      "confidence": 0.85,
      "_provider": "OpenAI · gpt-4o-mini"
    }
    ↓
5. 사용자 화면에 폼 자동 채움
    ↓
6. 사용자 검토·수정 → ✓ 적용
    ↓
7. fact_expense INSERT (txn_id = "EXP-OCR-{ts}")
   비고에 [영수증: {파일명}] 자동 첨부
```

## Vision 프롬프트 (한국어 영수증)

```
이것은 한국어 영수증 이미지입니다. 다음 항목을 JSON으로 추출하세요.
값을 모르면 null로 두세요. 절대 추측하지 마세요.
{
  "date": "YYYY-MM-DD",
  "amount": 정수(원, 부가세 포함 총액),
  "supply": 정수(공급가액, 없으면 null),
  "vat": 정수(부가세, 없으면 null),
  "place": "사용처/상호 (예: 스타벅스 강남점)",
  "payment_method": "법인카드|현금|이체|개인지출|체크카드|기타",
  "category_main": "운영비|인건비|판매관리비|R&D|기타",
  "category_sub": "회식·접대|사무용품|... 추론",
  "items": "주요 품목 요약 (한 줄)",
  "confidence": 0.0~1.0
}
JSON만 출력하세요. 설명, 코드 펜스 금지.
```

## 안전장치
1. **이미지 검증**: `mime.startswith("image/")` 아니면 거부
2. **원본 보존**: `uploads/expense_receipts/` 에 항상 저장
3. **JSON 파싱 실패**: regex로 `{...}` 추출 → 그래도 실패 시 빈 폼 + 수동 입력
4. **신뢰도 표시**: UI에 ✅(≥0.7) / ⚠️(0.4~0.7) / ℹ️(<0.4) 색상
5. **추측 금지**: LLM 지시문에 명시 (잘못된 금액으로 적재되는 사고 방지)

## 모바일 카메라 지원
```html
<input type="file" accept="image/*" capture="environment">
```
- `capture="environment"` — 후면 카메라 우선
- Android Chrome / iOS Safari 모두 지원

## 비용
- OpenAI gpt-4o-mini Vision: 1장당 약 $0.0001~0.0003 (해상도에 따라)
- Anthropic Claude Haiku: 1장당 약 $0.0002~0.0005

## 관련 자산
- [[inviz-domain-suggest]] — 표 형식 데이터용 도메인 추정 (OCR과 다른 워크플로)
- [[inviz-business-context]] — 거래처명·결제수단 정규화에 활용
