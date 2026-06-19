# 04. 자가발전 시스템

## 설계 목표

1. **데이터 변조 절대 방지** — 외부 파일이 시스템 데이터를 오염시키지 못하게
2. **새 데이터 유형 자동 적응** — LLM이 새 파일을 분류해 시스템이 진화
3. **사람 개입 최소화** — 자동 처리, 위험 시만 알림
4. **롤백 가능** — 무엇이 잘못돼도 1분 내 이전 상태로 복구

## 5중 안전 장치

```
새 폴더·파일 감지
    ↓
[1] DB 자동 백업 (snapshot_db)
    │  db_backup/safe_<trigger>_<timestamp>.db
    │  4.8MB 즉시 복사 (shutil.copy2)
    ↓
[2] 사전 KPI 측정 (capture_kpis)
    │  11개 지표: 매출/매입/계약/차입금 행수+합계, 거래처 수 등
    ↓
[3] sync_core 실행
    │  • 변경 감지 (mtime + SHA256)
    │  • 도메인별 핸들러
    │  • web_app 데이터 보존
    ↓
[4] 사후 KPI 측정 + 변동 검증 (evaluate_changes)
    │  • 전후 비교
    │  • SUSPICION_THRESHOLDS 적용
    │  • integrity_check 테이블에 영구 기록
    ↓
[5] Critical 변동 시 자동 롤백 (restore_db)
    │  • status='rolled_back' 마킹
    │  • shutil.copy2 (snapshot → app.db)
```

## 무결성 임계값

| (table, metric) | warning | critical |
|---|---:|---:|
| fact_sale.row_count | ±20% | ±50% |
| fact_sale.sum_supply | ±30% | ±70% |
| fact_purchase.row_count | ±20% | ±50% |
| fact_purchase.sum_supply | ±30% | ±70% |
| master_contract.row_count | ±20% | ±50% |
| dim_party.row_count | ±20% | ±50% |
| master_loan.sum_balance | ±25% | ±60% |

`self_dev.py`의 `SUSPICION_THRESHOLDS` 딕셔너리에서 조정 가능.

### 의도된 변동 vs 의심 변동

| 변동 유형 | 정상 / 의심 |
|---|---|
| 새 매출 파일 추가 → 합계 +15% | ✅ 정상 |
| 거래처 추가 → 거래처 수 +10명 | ✅ 정상 |
| 매출 합계 +250% | ⚠ 검토 (대규모 신규 계약?) |
| 매출 합계 -70% | 🛑 critical (오류 가능성 높음) |
| 거래처 수 -100명 | 🛑 critical (대량 삭제 의심) |

## LLM 자동 분류 (review_unmapped_files)

### 흐름
1. `file_registry`에서 `domain IS NULL` 파일 조회
2. 각 파일에 대해 `llm_classify_file()` 호출:
   - 파일명 + 시트명 + 헤더 컬럼 추출
   - LLM(llama3.1)에 JSON 응답 요청
3. 응답 파싱: `{domain, confidence, reasoning}`
4. **신뢰도 분기**:
   - ≥ 0.85 + 핸들러 있는 도메인 → `file_registry.domain` 자동 설정 → 다음 sync에서 처리
   - < 0.85 또는 핸들러 없음 → `unmapped_file_review` 큐 (사람 확정)

### 프롬프트
시스템 메시지: `DOMAIN_LIST_PROMPT` (13개 매핑 도메인 + document_certificate + unknown)

스키마:
```json
{
  "domain": "위 목록 중 하나",
  "confidence": 0.0 ~ 1.0,
  "reasoning": "왜 그렇게 분류했는지 한 문장"
}
```

### 신뢰도 가이드 (LLM에게 안내)
- 0.9+ : 파일명·헤더 매우 명확
- 0.7~0.9: 추론 가능, 일부 모호
- 0.5~0.7: 비슷한 후보 여럿
- 0.5↓: 분류 어려움 → unknown

## 벡터 DB 자가 갱신 (auto_reindex_changed)

```python
from rag_ingest import run_full_ingest
res = run_full_ingest(verbose=False)
# 청크 생성 함수가 변경 감지: content_hash 비교 → 변경된 청크만 재임베딩
```

`upsert_chunk`가 동일 (source_type, source_id)의 content_hash 비교:
- 변화 없음 → 임베딩 유지
- 변화 있음 → embedding_status='pending'으로 변경 → `embed_pending` 단계에서 재임베딩

## 통합 함수: safe_sync()

```python
def safe_sync(triggered_by="scheduled", model="llama3.1:latest",
              auto_rollback_on_critical=True,
              enable_llm_classify=True,
              enable_auto_reindex=True) -> dict:
    # 1. snapshot_db()
    # 2. capture_kpis() — before
    # 3. run_sync()
    # 4. capture_kpis() — after
    # 5. evaluate_changes() → IntegrityCheck 행 추가
    # 6. critical 있고 auto_rollback이면 restore_db()
    # 7. review_unmapped_files() — LLM 분류
    # 8. auto_reindex_changed() — 벡터 갱신
    return log_dict
```

## 운영 흐름

### 매일 04:00 자동 실행
1. Windows 작업 스케줄러 → `safe_sync.bat scheduled`
2. `python self_dev.py --scheduled`
3. 결과를 `sync_log/safe_sync_YYYYMMDD.log` 저장
4. DB의 `sync_run` + `integrity_check`에 기록

### 사용자가 다음 날 확인
1. `/self-dev` 페이지 접속
2. **무결성 점수** 확인 (95+ 권장)
3. **의심 변화** 0 또는 검토 (예: 매출 -15% — 정상이라면 OK)
4. **LLM 분류 대기열** 처리 (사람 확정 필요)

### 위험 변동 발견 시
1. 자동 롤백된 경우 → 원본 파일 검토 → 의도된 변경이면 임계값 임시 완화
2. 자동 롤백 안 된 warning → 사람 검토 → 데이터 보정
3. critical 자동 롤백 후에도 sync 필요하면: `auto_rollback=False`로 강제 실행

## 등록 명령

```cmd
register_safe_sync_task.bat   :: 매일 04:00 안전 동기화 등록
unregister_sync_task.bat       :: 해제 (별도 일반 동기화 작업)
```

기존 일반 동기화(`Inviz_DailySync`)는 자동 비활성화되고 `Inviz_SafeSync`로 대체됨.

## 확장: 새 KPI 지표 추가

`self_dev.py`의 `METRICS` 리스트에 추가:
```python
METRICS.append(
    ("fact_new_table", "sum_amount",
     lambda db: float(db.scalar(select(func.coalesce(func.sum(NewModel.amount), 0))) or 0))
)
SUSPICION_THRESHOLDS[("fact_new_table", "sum_amount")] = {"warn": 30, "critical": 70}
```

## 자가발전이 보장하지 못하는 것

- **의도된 대량 변경**: 회사가 일부러 모든 매출을 재정비하면 critical 발생 → `auto_rollback=False` 옵션 필요
- **새 핸들러 자동 작성**: LLM 분류는 가능하지만 핸들러 코드 자동 생성은 미구현 (`inviz-handler-generator` 에이전트로 위임)
- **외부 파일 변조 감지**: SHA256은 보관하지만 원본 폴더 자체가 손상되면 알 수 없음 → OneDrive 버전 관리로 보완
