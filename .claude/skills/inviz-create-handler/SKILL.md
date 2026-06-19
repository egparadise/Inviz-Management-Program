---
name: inviz-create-handler
description: 새 도메인의 sync 핸들러를 처음부터 생성. 새 종류의 Excel/CSV가 폴더에 추가됐을 때 자동 적재되도록 ETL 함수 + 도메인 매핑 룰 + 모델 추가까지 완료.
---

새 데이터 소스 → DB 자동 적재 파이프라인 구축 절차.

## 사전 조건

- 대상 파일이 `14.경영정보/` 하위에 존재
- 파일 구조(시트·컬럼)를 분석 가능
- 어느 SQLAlchemy 모델에 적재할지 결정 (기존 또는 신규)

## 5단계 절차

### 1. 파일 구조 분석
```python
import pandas as pd
from pathlib import Path
p = Path("...")
xl = pd.ExcelFile(p)
print("시트:", xl.sheet_names)
for sh in xl.sheet_names[:3]:
    for h in range(5):  # 헤더 위치 찾기
        df = pd.read_excel(p, sheet_name=sh, header=h, nrows=2)
        print(f"sheet={sh} header={h}: {list(df.columns)[:10]}")
```

체크리스트:
- [ ] 헤더 행 위치 (보통 0~3)
- [ ] Long-format vs Wide-format
- [ ] 날짜 형식
- [ ] 키 컬럼 (일자·거래처·금액)
- [ ] NULL/합계 행 패턴

### 2. 모델 확인 / 추가

기존 모델 재사용 가능?
- 매출 → `Sale`
- 매입 → `Purchase`
- 비용 → `Expense`
- 계약 → `Contract`

신규 모델 필요 시 `web_app/models.py`에 추가:
```python
class NewDomain(Base):
    __tablename__ = "fact_new"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    # ...
    source_file: Mapped[Optional[str]] = mapped_column(String(200))
    source_sheet: Mapped[Optional[str]] = mapped_column(String(100))
```

테이블 생성: `python -c "from database import init_db; init_db()"`

### 3. 도메인 매핑 룰 추가

`web_app/sync_core.py`의 `DOMAIN_MATCHERS`:
```python
DOMAIN_MATCHERS = [
    ...
    (re.compile(r"<파일명 패턴>", re.IGNORECASE), "<domain_id>", "<설명>"),
]
```

우선순위: 더 구체적인 패턴이 위에. 예: "외상매출금"이 "매출"보다 우선.

### 4. 핸들러 함수 작성

`web_app/sync_handlers.py`에 추가:

```python
def handler_<domain_id>(db: Session, path: Path) -> dict:
    """<설명>"""
    source_file = path.name
    removed = delete_by_source(db, <Model>, source_file)
    party_map = build_party_map(db)
    added = 0
    bulk = []

    try:
        df = pd.read_excel(path, sheet_name="<시트>", header=<row>)
    except Exception:
        return {"rows_added": 0, "rows_removed": removed}

    # ETL 로직 — 헤더 컬럼 자동 검출 패턴 활용
    cols = list(df.columns)
    date_col = next((c for c in cols if "일자" in str(c)), None)
    # ...

    for idx, r in df.iterrows():
        dt = s_date(r[date_col])
        if not dt: continue
        # 합계 행 제외
        nm = normalize_name(r.get(party_col))
        if not nm or any(s in nm for s in ["합계", "소계", "총계"]):
            continue
        # ...
        bulk.append(<Model>(
            txn_id=f"<prefix>-{idx:05d}",
            ...,
            source_file=source_file,
            source_sheet="<시트>",
            source_row=idx + 2,  # 1-based + 헤더
        ))
        added += 1

    if bulk:
        db.bulk_save_objects(bulk)
        db.commit()
    return {"rows_added": added, "rows_removed": removed}
```

마지막에 `HANDLERS` 딕셔너리 등록:
```python
HANDLERS = {
    ...,
    "<domain_id>": handler_<domain_id>,
}
```

### 5. 테스트 + 등록

테스트:
```python
from sync_handlers import handler_<domain_id>
from database import SessionLocal
from pathlib import Path
db = SessionLocal()
result = handler_<domain_id>(db, Path("..."))
print(result)
```

전체 sync에 통합:
```bash
python sync_core.py --force
```

## 핵심 유틸 (sync_handlers.py 상단)

```python
s_str(v)   # NULL 안전 str
s_int(v)   # NULL 안전 int
s_float(v) # NULL 안전 float
s_date(v)  # NULL 안전 date
normalize_name(s)  # 공백·구두점 정리
build_party_map(db)  # 거래처명 → 코드 dict
resolve_party(name, party_map)  # 거래처 매칭
apply_mapping(item_name, db)  # 품명 → (제품코드, 제품명)
yqh(year, month)  # (year, month, quarter, half)
delete_by_source(db, Model, source_file)  # web_app 보존하면서 해당 출처 삭제
```

## 무결성 보장

- `delete_by_source` 사용 시 `source_file != 'web_app'` 자동 적용
- 트랜잭션은 SQLAlchemy 세션이 자동 관리 — 예외 시 rollback
- 처리 후 행수·합계 확인 → self_dev.py가 자동 검증

## 흔한 함정

- pandas가 빈 셀을 NaN으로 → `s_*` 유틸 통해 None 처리
- mtime/sha256 동일하면 sync_core가 처리 안 함 → 테스트 시 `file_registry` 상태 강제 변경 필요
- Wide-format unpivot 시 `re.match("^(\d+)[월月]$", str(c))` 으로 월 컬럼 식별
