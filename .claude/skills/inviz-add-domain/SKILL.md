---
name: inviz-add-domain
description: 인비즈 시스템에 완전히 새로운 비즈니스 도메인을 추가. 모델·핸들러·라우터·페이지·RAG 청크 생성기를 한 번에 만들어 시스템에 통합.
---

새 비즈니스 도메인(예: "고정자산", "수출입실적", "법인카드") 추가 절차.

## 7단계 통합

### 1. 도메인 설계
- 도메인 ID (snake_case): `fixed_asset`
- 한국어 이름: "고정자산"
- 비즈니스 의미: 무엇을 추적하나
- 키 필드: id, 자산명, 취득일, 취득가액, 감가상각, 처분일 등
- 마스터 데이터인가 트랜잭션인가?

### 2. 모델 추가 (`web_app/models.py`)
```python
class FixedAsset(Base):
    __tablename__ = "master_fixed_asset"
    id: Mapped[str] = mapped_column(String(40), primary_key=True)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    acquisition_date: Mapped[Optional[date]] = mapped_column(Date)
    acquisition_amount: Mapped[float] = mapped_column(Numeric(18, 2), default=0)
    # ...
    source_file: Mapped[Optional[str]] = mapped_column(String(200))
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
```

### 3. 동기화 핸들러 (`web_app/sync_handlers.py`)
`inviz-create-handler` 스킬 참조. `HANDLERS`에 등록.

`sync_core.py`의 `DOMAIN_MATCHERS`에 파일명 패턴 추가.

### 4. RAG 청크 생성기 (`web_app/rag_ingest.py`)
```python
def ingest_fixed_assets(db: Session) -> int:
    n = 0
    for a in db.execute(select(FixedAsset)).scalars().all():
        text = (
            f"고정자산 {a.name}. 취득일 {a.acquisition_date or '-'},"
            f" 취득가액 {int(a.acquisition_amount):,}원."
            f" 감가상각 {a.depreciation or '-'}."
        )
        upsert_chunk(db, "fixed_asset", a.id, a.name, text,
                     page_url=f"/fixed-assets/{a.id}",
                     meta={"acquisition_date": str(a.acquisition_date)})
        n += 1
    db.commit()
    return n
```

`run_full_ingest()`에 호출 추가:
```python
stats["fixed_assets"] = ingest_fixed_assets(db)
```

### 5. 웹 라우터 (`web_app/routers/<domain>.py`)
기존 라우터 패턴 복사. CRUD + 목록 + 필터.

`main.py`에 라우터 등록:
```python
app.include_router(fixed_assets.router, prefix="/fixed-assets", tags=["고정자산"])
```

### 6. 템플릿 (`web_app/templates/<domain>/`)
- `list.html` — 목록 + 필터
- `form.html` — 입력 폼

`base.html`의 nav에 메뉴 추가:
```html
<a href="/fixed-assets" class="nav-link {% if p.startswith('/fixed-assets') %}active{% endif %}">고정자산</a>
```

### 7. 챗 엔진 통합 (`web_app/chat_engine.py`)
```python
# fast_intent_match
if re.search(r"고정자산|자산|감가상각", query):
    base["intent"] = "search_fixed_asset"
    return base

# DISPATCH
DISPATCH["search_fixed_asset"] = search_fixed_asset

def search_fixed_asset(intent, db):
    # SQL 집계
    return {"kind": "fixed_asset", ...}
```

JS의 `renderResult`에도 `kind === 'fixed_asset'` 케이스 추가.

## MCP 도구도 추가 (선택)

`.claude/mcp/inviz_mcp_server.py`에 `@mcp.tool()` 함수 하나 추가:
```python
@mcp.tool()
def list_fixed_assets(active: bool = True) -> dict:
    """고정자산 목록 조회."""
    ...
```

## 자가발전 시스템 통합

- `self_dev.py`의 `METRICS` + `SUSPICION_THRESHOLDS`에 새 테이블 추가:
```python
METRICS.append(("master_fixed_asset", "row_count",
                lambda db: db.scalar(select(func.count()).select_from(FixedAsset)) or 0))
SUSPICION_THRESHOLDS[("master_fixed_asset", "row_count")] = {"warn": 30, "critical": 70}
```

## 테스트 체크리스트

- [ ] DB 테이블 생성 (`init_db()`)
- [ ] 핸들러 단독 테스트 (실제 파일로)
- [ ] sync_core 통합 실행 OK
- [ ] 웹 페이지 200 OK
- [ ] CRUD 동작
- [ ] RAG 청크 임베딩 OK (`store_stats()`)
- [ ] 챗 검색 정확도 확인
- [ ] 무결성 임계값 정상 적용

## 운영 도입 순서

1. 개발: 로컬에서 모든 단계 완료
2. 백업: `safe_sync.bat` 실행으로 DB 백업
3. 모델 마이그레이션: `init_db()` 실행
4. 첫 sync: `sync_core.py --force` 로 새 도메인 처리
5. 검증: `/self-dev`에서 무결성 확인
6. 공지: 경영지원팀에 새 메뉴 안내
