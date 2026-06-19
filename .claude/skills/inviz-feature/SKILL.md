---
name: inviz-feature
description: 인비즈 새 기능 개발 레시피 — 모델→마이그레이션→라우터(라우트순서)→템플릿→메뉴→설정→스케줄러→테스트→정리.
---

인비즈 경영관리 시스템에 새 기능을 end-to-end로 추가하는 레시피. 급여·은행카드·서류·세금 기능을 실제로 만든 절차를 그대로 정리했다. 순서대로 따르면 빠지는 단계가 없다.

## 1. 모델 (`web_app/models.py`)

SQLAlchemy 2.0 스타일 `Mapped` / `mapped_column`. 숫자 컬럼은 반드시 `default=0`을 준다. ORM insert가 빈 값을 0으로 채우게 하기 위함 — raw SQL로 넣을 때 NOT NULL 위반이 나는 걸 막는다.

```python
class TaxFiling(Base):
    __tablename__ = "tax_filing"
    id: Mapped[str] = mapped_column(String(40), primary_key=True)
    period: Mapped[str] = mapped_column(String(10), nullable=False)  # "2026-1Q"
    tax_type: Mapped[str] = mapped_column(String(40), nullable=False)  # "부가세"
    amount: Mapped[float] = mapped_column(Numeric(18, 2), default=0)   # ★ default=0
    due_date: Mapped[Optional[date]] = mapped_column(Date)
    filed: Mapped[bool] = mapped_column(Boolean, default=False)
    source_file: Mapped[Optional[str]] = mapped_column(String(200))
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
```

## 2. 마이그레이션

- **새 테이블**: 자동. startup의 `Base.metadata.create_all(engine)`가 없는 테이블을 만들어 준다. 모델만 추가하면 끝.
- **기존 테이블에 새 컬럼**: `create_all`은 컬럼을 추가하지 **않는다**. 일회성 스크립트로 `ALTER TABLE`을 직접 실행하고, 끝나면 스크립트를 삭제한다.

```python
# web_app/_migrate_add_col.py  (실행 후 삭제)
import sqlite3
db = sqlite3.connect("app.db")
cols = [r[1] for r in db.execute("PRAGMA table_info(tax_filing)")]
if "memo" not in cols:                       # ★ 존재 확인 후
    db.execute("ALTER TABLE tax_filing ADD COLUMN memo VARCHAR(300)")
    db.commit()
    print("added memo")
else:
    print("already exists")
db.close()
```

```cmd
cd web_app && python _migrate_add_col.py    :: 1회 실행 → 파일 삭제
```

## 3. 라우터 (`web_app/routers/<name>.py`)

라우터 파일을 만들고 `main.py`에서 prefix로 등록한다.

```python
# web_app/routers/tax.py
from fastapi import APIRouter, Request, Depends
router = APIRouter()

@router.get("/")
def tax_list(request: Request, db=Depends(get_db)):
    ...
```

```python
# web_app/main.py
from routers import tax
app.include_router(tax.router, prefix="/tax", tags=["세금"])
```

### ★ 라우트 순서 — 리터럴/구체 경로를 동적 경로보다 먼저

Starlette는 `/{id:int}`가 아닌 `/{id}`를 `[^/]+`로 매칭한다. `/tax/export.xlsx`를 `/tax/{tpl_id}` **뒤**에 두면 `export.xlsx`가 `{tpl_id}`로 잡혀 `422 int_parsing` 에러가 난다. 리터럴·구체 경로를 항상 먼저 등록하라.

```python
# ✅ 올바른 순서
@router.post("/save-rates")          # 리터럴 먼저
def save_rates(...): ...

@router.get("/ai-rates")
def ai_rates(...): ...

@router.get("/export.xlsx")          # 리터럴 먼저
def export_xlsx(...): ...

@router.get("/{tpl_id}")             # 동적 경로 나중
def tax_detail(tpl_id: int, ...): ...
```

급여(`/save-rates`, `/ai-rates`)·세금(`/tax/export.xlsx`) 라우터에서 실제로 이 순서로 배치했다. `/{pid}`, `/{tpl_id}` 같은 동적 경로는 항상 파일 맨 아래.

## 4. 템플릿 (`web_app/templates/<name>/*.html`)

`base.html`을 extends하고 공용 컴포넌트 클래스(`.card .btn .table .badge .input`)를 쓴다. 색·필터는 base에 이미 정의돼 있다.

```html
{% extends "base.html" %}
{% block content %}
<div class="card">
  <h1 class="text-xl font-bold mb-4">세금 신고 관리</h1>
  <table class="table">
    <thead><tr><th>기간</th><th>세목</th><th>금액</th><th>납부기한</th></tr></thead>
    <tbody>
      {% for t in items %}
      <tr>
        <td>{{ t.period }}</td>
        <td><span class="badge badge-purple">{{ t.tax_type }}</span></td>
        <td>{{ t.amount|money }}원</td>
        <td>{{ t.due_date|date }}</td>
      </tr>
      {% endfor %}
    </tbody>
  </table>
</div>
{% endblock %}
```

## 5. 메뉴 (`web_app/helpers.py`)

`NAV_ITEMS`에 항목을 추가한다. 하위 메뉴는 `children`으로.

```python
NAV_ITEMS = [
    # ...
    {"label": "세금", "url": "/tax", "icon": "receipt", "children": [
        {"label": "신고 현황", "url": "/tax"},
        {"label": "세율 설정", "url": "/tax/rates"},
    ]},
]
```

## 6. 설정이 필요하면 (`web_app/routers/settings.py` + `templates/settings/view.html`)

설정 페이지를 추가하려면 5곳을 손본다.

```python
# settings.py
SETTINGS_PAGES = [..., ("tax", "세금 설정")]          # 1) 페이지 목록
SECTION_TO_PAGE = {..., "tax_rate": "tax"}            # 2) 섹션→페이지 매핑

SAVE_ALLOWLIST = {                                    # 3) 저장 허용 키
    "tax": ["vat_rate", "tax_api_key"],
}

def _render_settings(page, db):                       # 4) 컨텍스트
    ctx = {...}
    if page == "tax":
        ctx["vat_rate"] = setting("vat_rate", "10")
    return ctx

def save_settings(page, form, db):                    # 비밀값은 입력 있을 때만
    for k in SAVE_ALLOWLIST.get(page, []):
        v = form.get(k)
        if k.endswith("_key") and not v:              # ★ 빈 입력이면 기존 비밀값 유지
            continue
        set_setting(k, v)
```

```html
<!-- templates/settings/view.html -->
{% if page == 'tax' %}                                <!-- 5) 페이지 블록 -->
<div class="card">
  <label class="block mb-2">부가세율(%)</label>
  <input class="input" name="vat_rate" value="{{ vat_rate }}">
  <label class="block mt-4 mb-2">국세청 API 키</label>
  <input class="input" name="tax_api_key" type="password" placeholder="변경 시에만 입력">
</div>
{% endif %}
```

## 7. 알림/스케줄 (`web_app/scheduler.py`)

`_loop()`에 점검 함수를 추가한다. 루프는 약 1분마다 돈다. 같은 사이클에 중복 발송되지 않도록 settings 플래그로 1일 1회 등 가드한다. 알림은 캘린더 이벤트(`CalendarEvent`, `category`) + 텔레그램(`integrations.send_telegram`)으로 보낸다.

```python
# scheduler.py
def _check_tax_due(db):
    today = date.today()
    flag = f"tax_alert_{today.isoformat()}"
    if setting(flag):                                 # ★ 사이클당 1회 중복방지
        return
    soon = db.execute(select(TaxFiling).where(
        TaxFiling.filed == False,
        TaxFiling.due_date <= today + timedelta(days=7),
    )).scalars().all()
    for t in soon:
        db.add(CalendarEvent(
            title=f"[세금] {t.tax_type} 납부기한 {t.due_date}",
            date=t.due_date, category="tax",
        ))
        send_telegram(f"⚠️ {t.tax_type} 납부기한 임박: {t.due_date} ({t.amount:,.0f}원)")
    db.commit()
    set_setting(flag, "1")

def _loop():
    while True:
        with SessionLocal() as db:
            _check_tax_due(db)                        # ★ 여기 추가
            # ... 기존 점검들
        time.sleep(60)
```

## 8. 시드/마이그레이션 데이터

초기 데이터가 필요하면 일회성 `_seed_*.py`를 만들어 실행하고 삭제한다. 코드베이스에 남기지 않는다.

```python
# web_app/_seed_tax.py  (실행 후 삭제)
from db import SessionLocal
from models import TaxFiling
with SessionLocal() as db:
    db.add(TaxFiling(id="TX-2026-1Q-VAT", period="2026-1Q",
                     tax_type="부가세", amount=0, filed=False))
    db.commit()
print("seeded")
```

```cmd
cd web_app && python _seed_tax.py     :: 1회 실행 → 삭제
```

## 9. 테스트 + 재시작

`inviz-dev-process` 스킬을 참조한다. 서버 재시작 → 페이지 200 확인 → CRUD 동작 → 라우트 순서 확인(리터럴 경로 200, 동적 경로 정상).

---

## ✅ 체크리스트

- [ ] **모델**: `Mapped`/`mapped_column`, 숫자 컬럼 `default=0`
- [ ] **마이그레이션**: 새 테이블은 자동 / 새 컬럼은 `PRAGMA` 확인 후 `ALTER TABLE`, 스크립트 삭제
- [ ] **라우터**: `main.py` `include_router(prefix=...)`, ★리터럴·구체 경로를 `/{id}` 동적 경로보다 먼저
- [ ] **템플릿**: `base.html` extends, 공용 컴포넌트 클래스
- [ ] **메뉴**: `helpers.py` `NAV_ITEMS` (+`children`)
- [ ] **설정(필요 시)**: `SETTINGS_PAGES` + `SECTION_TO_PAGE` + `SAVE_ALLOWLIST` + `_render_settings` + `view.html` 블록, 비밀값은 입력 있을 때만 저장
- [ ] **스케줄(필요 시)**: `_loop()`에 점검 함수, 사이클당 1회 가드, 캘린더 + 텔레그램
- [ ] **시드**: 일회성 `_seed_*.py` 실행 후 삭제
- [ ] **테스트**: 재시작 + 페이지 200 + 라우트 순서 검증 (`inviz-dev-process` 참조)
