---
name: inviz-self-dev-review
description: 자가발전 시스템의 실행 결과를 검토하고 무결성·LLM 분류·재인덱싱 품질을 평가. 위험 신호 감지 시 롤백 권장.
---

매일 04:00 또는 수동 실행된 안전 동기화 결과를 검토하는 절차.

## 검토 대상

`/self-dev` 페이지 또는 SQL로:
1. 최근 SyncRun 상태
2. IntegrityCheck (warning·critical·rolled_back)
3. UnmappedFileReview 큐
4. KnowledgeChunk 임베딩 상태

## 진단 흐름

### 1단계: 동기화 완료 여부
```sql
SELECT id, started_at, finished_at, status,
       files_processed, files_errored, rows_added, rows_removed
FROM sync_run ORDER BY id DESC LIMIT 1;
```

- `status='success'` → 진행
- `status='partial'` → 일부 오류, 상세 확인 필요
- `status='rolled_back'` → critical 변동 감지, **즉시 검토**
- `status='failed'` → 동기화 자체 실패

### 2단계: 무결성 점수 평가
```sql
SELECT status, COUNT(*) FROM integrity_check
WHERE run_id = (SELECT MAX(id) FROM sync_run)
GROUP BY status;
```

기준:
- 모두 `ok` → 100점, 안전
- `warning` 있음 → 검토 필요 (예: 매출 합계 -30%)
- `critical` 있음 → 즉시 조사 (자동 롤백됐을 수도)

### 3단계: 의심 변동 상세
```sql
SELECT table_name, metric, before_value, after_value, delta_pct, status, note
FROM integrity_check
WHERE run_id = ? AND status != 'ok'
ORDER BY ABS(delta_pct) DESC;
```

각 변동에 대해 판단:
- **정상적인 신규 데이터 유입**? (예: 새 월 매출 추가로 합계 +30%)
- **이상 변조**? (예: 매출 -70% — 의도 없는 대량 삭제)
- **데이터 정제**? (예: 중복 거래처 통합으로 -100명)

### 4단계: LLM 분류 큐 검토
```sql
SELECT id, file_name, suggested_domain, confidence, llm_reasoning, status
FROM unmapped_file_review
WHERE status='pending' ORDER BY confidence DESC;
```

각 항목 처리:
- 신뢰도 ≥ 0.85 + 핸들러 있는 도메인 → 이미 auto_processed
- 신뢰도 < 0.85 → 사람이 확정해야 함:
  - LLM 추천 도메인이 맞는지 파일 직접 확인
  - 맞으면 `/self-dev` 확정 버튼
  - 새 도메인이라면 `inviz-handler-generator` 호출

### 5단계: 벡터 DB 갱신 확인
```sql
SELECT embedding_status, COUNT(*) FROM knowledge_chunk GROUP BY embedding_status;
```

- `pending` 있음 → 재임베딩 필요: `/knowledge` → 미임베딩만 벡터화
- 모두 `embedded` → 양호

## 권장 액션 매트릭스

| 상황 | 조치 |
|---|---|
| critical 자동 롤백 발생 | 원인 파일 식별 → 해당 파일 수정 또는 임계값 조정 |
| warning 5건 이상 | 새 데이터 패턴 변화 — 임계값 재검토 |
| LLM 분류 정확도 < 50% | 프롬프트 개선 (self_dev.py의 DOMAIN_LIST_PROMPT) |
| 미매핑 파일 누적 (10+) | 새 도메인 핸들러 작성 (inviz-handler-generator) |
| 벡터 DB pending 누적 | 재인덱싱 실행 |
| 챗 답변 정확도 저하 | 청크 텍스트 품질 점검 (inviz-rag-builder) |

## 자동 롤백 후 복구 절차

critical 변동으로 자동 롤백된 경우:
1. **롤백 확인**: `integrity_check.status = 'rolled_back'` 행 조회
2. **원본 파일 검증**: 어떤 파일이 critical 변동을 일으켰는지
3. **데이터 검증**: 원본이 실제로 잘못된 것? 또는 의도된 변경?
4. **재시도 옵션**:
   - 원본 수정 → 다시 sync
   - 임계값 임시 완화 → `auto_rollback_on_critical=False`로 sync
   - 데이터 수동 입력 → 웹에서 신규 등록

## 보고서 형식

검토 후 다음 형식으로 정리:

```
[자가발전 검토 #YYYY-MM-DD]

✓ 동기화: 성공 / 부분성공 / 롤백
   - 처리 파일: N건, 오류 N건
   - +N rows / -N rows

✓ 무결성: ✅ 100점 / ⚠ 85점 / 🛑 60점
   - warning: N건
   - critical: N건
   - 자동 롤백: N회

✓ LLM 분류: N건 검토 (자동 N건, 대기 N건)
   - 정확도: NN%

✓ 벡터 DB: pending N건

🎯 권장 조치:
1. ...
2. ...
```
