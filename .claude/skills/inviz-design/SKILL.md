---
name: inviz-design
description: 인비즈 화면 디자인 — 브랜드 색·공용 컴포넌트·페이지 레이아웃·네비게이션·필터/연도그룹·라이브 JS 계산 패턴을 일관되게 적용.
---

인비즈 경영관리 시스템의 화면을 새로 만들거나 고칠 때 따르는 디자인 방법론. 모든 페이지는 `base.html`을 extends 하고, 브랜드 색·공용 클래스·필터 패턴을 재사용한다. 새 디자인을 짤 때 임의 색·임의 컴포넌트를 만들지 말고 아래 규약을 그대로 쓴다.

## 1. 브랜드 / 스택 요약

- **스택**: FastAPI + Jinja2 + HTMX(1.9) + Tailwind CSS(CDN) + Chart.js(4.4). 빌드 단계 없음 — CDN 스크립트만 `base.html` `<head>`에 있다.
- **브랜드 색** (CSS 변수, `base.html`에 정의):
  - `--inviz-purple` `#6B2C91` (메인), `--inviz-purple-dark` `#4F1D6B`, `--inviz-purple-50` `#F5EDFA` (연보라 배경)
  - `--inviz-orange` `#F47521` (강조/액션), `--inviz-orange-dark` `#D85F11`
- 색을 직접 쓸 때는 `style="color: var(--inviz-purple);"` 처럼 **CSS 변수로** 참조. `#6B2C91` 하드코딩 금지.
- 페이지 시작은 항상:

```html
{% extends "base.html" %}
{% block title %}매출 — 인비즈 경영관리{% endblock %}
{% block content %}
  <!-- 여기에 화면 -->
{% endblock %}
```

- 페이지 전용 JS는 `{% block scripts %}` 또는 `{% block content %}` 맨 끝 `<script>`에. 전역 변수는 `invizFmt` 처럼 **접두사**를 붙여 `base.html`의 챗 스크립트와 충돌을 피한다 (예: dashboard의 `const fmt`가 챗 패널과 충돌한 전례 있음).

### 공용 컴포넌트 클래스 (직접 정의된 것만 사용)

| 클래스 | 용도 |
|---|---|
| `.card` | 흰 박스 (radius 10, 그림자) |
| `.kpi-card` | 좌측 보라 4px 라인 KPI 박스 |
| `.btn` + `.btn-primary`/`.btn-accent`/`.btn-secondary`/`.btn-danger` | 버튼 (primary=보라, accent=주황, secondary=회색) |
| `.input` `.select` `.textarea` | 폼 입력 (포커스 시 보라 링) |
| `.table` | 표 (th=연보라 헤더, hover, `.total-row`=주황 합계행) |
| `.badge` + `.badge-purple`/`.badge-green`/`.badge-red`/`.badge-orange`/`.badge-blue`/`.badge-gray` | 상태 배지 |
| `.num` | 숫자 우측정렬 + tabular-nums |

### Jinja 필터 / 전역

- 필터: `|money` (천단위 콤마, 소수 버림), `|pct` (퍼센트), `|date` (YYYY-MM-DD), `|period`.
- 금액은 항상 `{{ v|money }}` + 우측에 `원` 텍스트. 날짜는 `{{ d|date }}`.

## 2. 페이지 골격 — 헤더 + 카드/표/배지/KPI

표준 헤더는 `flex items-center justify-between`: 좌측 h1(보라), 우측 액션 버튼들. 실제 `/sales` 패턴.

```html
{% block content %}
<div class="flex items-center justify-between mb-4">
  <h1 class="text-2xl font-bold" style="color: var(--inviz-purple);">매출 트랜잭션</h1>
  <div class="flex gap-2">
    <a href="/sales/import-csv" class="btn btn-secondary">📥 CSV 업로드</a>
    <a href="/sales/export.xlsx?{{ qs }}" class="btn btn-secondary">📊 Excel</a>
    <a href="/sales/new" class="btn btn-primary">+ 신규 매출</a>
  </div>
</div>

<!-- KPI 카드 줄 -->
<div class="grid grid-cols-2 md:grid-cols-4 gap-3 mb-6">
  <div class="kpi-card">
    <div class="text-xs text-slate-500">공급가액 합계</div>
    <div class="text-2xl font-bold text-slate-800 mt-1">{{ sum_supply|money }}<span class="text-sm font-normal text-slate-400 ml-1">원</span></div>
  </div>
  <div class="kpi-card" style="border-color: var(--inviz-orange);">
    <div class="text-xs text-slate-500">총 합계</div>
    <div class="text-2xl font-bold mt-1" style="color: var(--inviz-purple);">{{ sum_total|money }}<span class="text-sm font-normal text-slate-400 ml-1">원</span></div>
  </div>
</div>

<!-- 표 + 배지 -->
<div class="card">
  <table class="table">
    <thead><tr><th>일자</th><th>거래처</th><th>제품</th><th class="num">합계</th><th>상태</th></tr></thead>
    <tbody>
      {% for r in rows %}
      <tr>
        <td class="whitespace-nowrap">{{ r.txn_date|date }}</td>
        <td>{{ r.party_name }}</td>
        <td><span class="badge badge-purple">{{ r.product_code }}</span> {{ r.product_name }}</td>
        <td class="num font-semibold">{{ r.total|money }}</td>
        <td><span class="badge badge-green">완료</span></td>
      </tr>
      {% endfor %}
    </tbody>
  </table>
</div>
{% endblock %}
```

규칙: KPI 카드 줄은 `grid grid-cols-2 md:grid-cols-4 gap-3 mb-6`. 강조하려는 카드만 `style="border-color: var(--inviz-orange);"`. 데이터 없을 때는 `<tr><td colspan="N" class="text-center text-slate-400 py-4">데이터 없음</td></tr>`.

## 3. 필터 패턴 (GET form)

필터는 항상 `<form method="get">` 안의 `.card`. 서버가 현재 필터값을 `filter.*`로 다시 내려주고, 셀렉트는 `{% if filter.x == y %}selected{% endif %}`로 상태를 복원한다. 버튼형(필터 적용)과 즉시반영형 둘 다 지원.

```html
<div class="card mb-4">
  <form method="get" class="grid grid-cols-1 md:grid-cols-7 gap-3">
    <div class="md:col-span-2">
      <label class="text-xs text-slate-500">기간 (시작 ~ 종료)</label>
      <div class="flex gap-2">
        <input type="date" name="from_date" value="{{ filter.from_date }}" class="input">
        <span class="self-center text-slate-400">~</span>
        <input type="date" name="to_date" value="{{ filter.to_date }}" class="input">
      </div>
    </div>
    <div>
      <label class="text-xs text-slate-500">연도</label>
      <!-- 즉시 반영: 바꾸면 폼 자동 제출 -->
      <select name="year" class="select" onchange="this.form.submit()">
        <option value="">전체</option>
        {% for y in years %}<option value="{{ y }}" {% if filter.year == y %}selected{% endif %}>{{ y }}</option>{% endfor %}
      </select>
    </div>
    <div>
      <label class="text-xs text-slate-500">월</label>
      <select name="month" class="select" onchange="this.form.submit()">
        <option value="">전체</option>
        {% for m in range(1, 13) %}<option value="{{ m }}" {% if filter.month == m %}selected{% endif %}>{{ m }}월</option>{% endfor %}
      </select>
    </div>
    <div class="md:col-span-7 flex gap-2 justify-end pt-1 border-t">
      <button class="btn btn-primary px-6">필터 적용</button>
      <a href="/sales" class="btn btn-secondary">초기화</a>
    </div>
  </form>
</div>
```

- **즉시 반영** 셀렉트(연도/월 등 옵션이 적은 것): `onchange="this.form.submit()"`. 사용자가 "필터 적용"을 안 눌러도 된다.
- **버튼 제출**: 텍스트 입력(거래처·품명 검색)이 섞이면 즉시 제출이 거슬리므로 "필터 적용" 버튼을 둔다. `/sales`는 둘을 같이 쓴다.
- 페이지네이션·Export 링크에 현재 필터를 유지하려면 서버에서 `qs`(query string)를 만들어 `?page={{ page+1 }}&{{ qs }}`, `export.xlsx?{{ qs }}`로 넘긴다.

## 4. 연도별 접이식 그룹

연·기간 단위로 묶어 보여줄 때(차입금·계약 이력, 연도별 매출 요약 등)는 `<details class="card">`. 최신 연도만 `open`.

```html
{% for year, items in grouped.items() %}
<details class="card mb-3" {% if loop.first %}open{% endif %}>
  <summary class="cursor-pointer font-semibold flex items-center justify-between" style="color: var(--inviz-purple);">
    <span>{{ year }}년 <span class="badge badge-purple ml-1">{{ items|length }}건</span></span>
    <span class="text-sm font-normal text-slate-500">합계 {{ items|sum(attribute='amount')|money }} 원</span>
  </summary>
  <div class="overflow-x-auto mt-3">
    <table class="table">
      <thead><tr><th>일자</th><th>내용</th><th class="num">금액</th></tr></thead>
      <tbody>
        {% for it in items %}
        <tr><td>{{ it.date|date }}</td><td>{{ it.title }}</td><td class="num">{{ it.amount|money }}</td></tr>
        {% endfor %}
      </tbody>
    </table>
  </div>
</details>
{% endfor %}
```

`<summary>`에는 연도 + 건수 배지 + 합계를 한 줄로. `cursor-pointer`로 클릭 가능함을 표시. 기본 펼침은 `loop.first`(보통 최신 연도)만.

## 5. 표 규약

- 가로로 넓은 표는 항상 `<div class="overflow-x-auto"><table class="table">…`. 모바일에서 잘리지 않게.
- 금액 컬럼: `<th class="num">` + `<td class="num">{{ v|money }}</td>`. `.num`이 우측정렬 + 등폭 숫자.
- 상태/분류는 텍스트 대신 배지: 완료=`badge-green`, 만료임박=`badge-orange`, 미수/위험=`badge-red`, 코드/태그=`badge-purple`/`badge-blue`, 비활성=`badge-gray`.
- 합계행은 `<tfoot><tr class="total-row">…` (주황 상단선 + 굵게). 페이지네이션이 있으면 "현재 페이지 기준" 명시하고 전체 합계는 상단 KPI 카드로.

```html
<tfoot>
  <tr class="total-row">
    <td colspan="3">합계 (현재 페이지 기준 — 전체 합계는 위 KPI 카드 참조)</td>
    <td class="num">{{ (rows|sum(attribute='supply'))|money }}</td>
  </tr>
</tfoot>
```

## 6. 반응형 그리드

Tailwind 브레이크포인트로 모바일 1열 → 데스크톱 다열. KPI 줄은 보통 4~5열.

```html
<!-- KPI 4개 -->
<div class="grid grid-cols-2 md:grid-cols-4 gap-3 mb-6"> … </div>
<!-- KPI 5개 (예: /self-dev 지표) -->
<div class="grid grid-cols-2 md:grid-cols-5 gap-3 mb-6"> … </div>
<!-- 좌우 2분할 (거래처 TOP / 제품별) -->
<div class="grid grid-cols-1 lg:grid-cols-2 gap-4 mb-6"> … </div>
<!-- 입력 폼 줄: 라벨+필드 6열 -->
<form class="grid grid-cols-2 md:grid-cols-6 gap-3 items-end"> … </form>
```

기본은 모바일 `grid-cols-2`(KPI는 2개씩 보이게), `md:`/`lg:`에서 펼친다. 폼 줄은 `items-end`로 라벨 높이가 달라도 입력칸 바닥을 맞춘다.

## 7. 네비게이션 추가

메뉴는 **`helpers.py`의 `NAV_ITEMS`** 리스트로 데이터 관리하며 `base.html`이 전역 `nav_items()`로 렌더한다. 각 항목은 `{"key","path","icon","label"}`, 펼침 메뉴는 `"children":[...]`. ★active는 `p.startswith(it.path)`로 판정 → **부모 경로와 자식 경로가 같으면 안 된다**(부모 `/banking`·자식 `/banking`이면 모든 하위에서 자식도 active로 잡힘). 자식은 부모보다 더 깊은 경로(`/banking/transactions`)로 두는 게 안전.

```python
# helpers.py — 실제 형식: key/path/icon/label (+children)
NAV_ITEMS = [
    {"key": "dashboard", "path": "/",        "icon": "🏠", "label": "대시보드", "exact": True},
    {"key": "sales",     "path": "/sales",   "icon": "💰", "label": "매출"},
    {"key": "payroll",   "path": "/payroll", "icon": "💵", "label": "급여"},
    # 펼침 메뉴: children 가진 항목
    {"key": "reports", "path": "/reports", "icon": "📑", "label": "보고서", "children": [
        {"key": "reports-tax", "path": "/reports/tax", "icon": "🧾", "label": "세금"},
    ]},
]
# 순서는 _nav_items()가 설정(nav_order)에 따라 재정렬, 신규 키는 기본 위치에 삽입.
```

`base.html`에서 렌더 (부모는 children 중 하나가 active면 펼침):

```html
{% set p = request.url.path %}
{% for item in nav_items() %}
  {% if item.children %}
    {% set act = item.children | selectattr('href','in',p) | list %}
    <details class="nav-group" {% if act %}open{% endif %}>
      <summary class="nav-link">{{ item.icon }} {{ item.label }}</summary>
      {% for c in item.children %}
        <a href="{{ c.href }}" class="nav-link {% if p.startswith(c.href) %}active{% endif %}">{{ c.label }}</a>
      {% endfor %}
    </details>
  {% else %}
    <a href="{{ item.href }}"
       class="nav-link {% if item.href == '/' and p == '/' or item.href != '/' and p.startswith(item.href) %}active{% endif %}">
      {{ item.icon }} {{ item.label }}
    </a>
  {% endif %}
{% endfor %}
```

**active 충돌 주의** — `p.startswith()`로 판정하므로 하위 경로는 부모 경로보다 **더 깊게** 설계한다.
- 좋음: 부모 `/loans`, 하위 `/loans/officer` → `/loans/officer`는 둘 다 startswith지만 자식이 더 길어 같이 켜져도 자연스럽다.
- 나쁨: 별개 메뉴인데 `/report`와 `/reportcard`처럼 한쪽이 다른 쪽의 접두사 → `/reportcard`에서 `/report`도 active로 켜짐. 이럴 땐 경로를 `/reports/...`, `/report-cards/...`로 분리해 접두사 충돌을 없앤다.
- 대시보드(`/`)만 예외적으로 `p == '/'` 정확 일치로 판정(모든 경로가 `/`로 시작하므로).

## 8. 라이브 JS 계산 폼 (급여 폼 사례)

급여명세서·세금 계산처럼 입력값을 바꿀 때마다 합계가 즉시 갱신돼야 하는 폼. 서버가 기준값(요율·공제표)을 JSON으로 주입하고, 클라이언트가 입력 이벤트마다 재계산한다. 합계는 **숨은 필드**에 넣어 함께 POST.

`/payroll/form` 패턴:

```html
<form method="post" action="/payroll/save" id="payForm">
  <div class="grid grid-cols-2 md:grid-cols-4 gap-3 items-end">
    <div><label class="text-xs text-slate-500">기본급</label>
      <input type="text" name="base" class="input calc" value="{{ row.base }}"></div>
    <div><label class="text-xs text-slate-500">식대</label>
      <input type="text" name="meal" class="input calc" value="{{ row.meal }}"></div>
    <div><label class="text-xs text-slate-500">국민연금</label>
      <input type="text" name="pension" class="input" id="pension" readonly></div>
    <div><label class="text-xs text-slate-500">실수령액</label>
      <input type="text" class="input font-bold" id="net" readonly style="color:var(--inviz-purple);"></div>
  </div>
  <!-- 합계는 숨은 필드로 서버 전송 -->
  <input type="hidden" name="gross" id="h_gross">
  <input type="hidden" name="deduction" id="h_ded">
  <input type="hidden" name="net" id="h_net">
  <button class="btn btn-primary mt-4">저장</button>
</form>

<script>
// 서버가 요율표를 주입 (소득세 간이세액·4대보험 요율 등)
const PAY = {{ pay_json|safe }};   // 예: {pensionRate:0.045, healthRate:0.03545, taxTable:{...}}

// 입력값 읽기/쓰기 헬퍼 (콤마 제거 → 숫자, 숫자 → 콤마)
function gv(id) { return Number((document.getElementById(id)?.value || '0').replace(/[^0-9.-]/g,'')) || 0; }
function gvn(name) { return Number((document.querySelector(`[name=${name}]`)?.value || '0').replace(/[^0-9.-]/g,'')) || 0; }
function sv(id, v) { const el = document.getElementById(id); if (el) el.value = new Intl.NumberFormat('ko-KR').format(Math.round(v)); }
function svh(id, v) { const el = document.getElementById(id); if (el) el.value = Math.round(v); }  // 숨은 필드: 콤마 없이
function round10(v) { return Math.floor(v / 10) * 10; }   // 원단위 절사 (10원 미만 버림)

// 재계산 — 함수 선언이라 호이스팅되어 아래 이벤트 바인딩보다 먼저 정의 안 해도 됨
function recalc() {
  const gross = gvn('base') + gvn('meal');
  const pension = round10(gross * PAY.pensionRate);
  const health = round10(gross * PAY.healthRate);
  const ded = pension + health;
  const net = gross - ded;
  sv('pension', pension);
  sv('net', net);
  svh('h_gross', gross); svh('h_ded', ded); svh('h_net', net);
}

// 모든 .calc 입력에 바인딩 + 최초 1회 실행
document.querySelectorAll('.calc').forEach(el => el.addEventListener('input', recalc));
recalc();
</script>
```

핵심 규칙:
- **서버 주입**: 요율·세액표는 코드에 하드코딩하지 말고 `{{ pay_json|safe }}`로 내려받는다. `|safe`를 꼭 붙여야 JSON이 escape되지 않는다.
- **gv()/sv()/round10()** 헬퍼로 콤마 파싱·포맷·원단위 절사를 일관 처리. 화면 표시는 콤마(`sv`), 서버 전송 숨은 필드는 콤마 없는 정수(`svh`).
- **함수 호이스팅**: `function recalc(){}` 선언식은 호이스팅되므로 이벤트 바인딩 코드와 순서를 신경 쓸 필요 없다(화살표 함수 `const recalc =`는 호이스팅 안 됨 — 선언식 사용).
- **숨은 필드 합계 전송**: 표시용 readonly 필드와 별개로 `<input type="hidden">`에 계산 결과를 넣어 POST. 서버는 클라 계산을 신뢰하지 말고 같은 식으로 재검증한다(`/reports/tax` 부가세도 동일 — 화면 합계는 미리보기, 확정은 서버 재계산).

## 9. 한국어 UX / 접근성

- **말줄임**: 긴 거래처명·품명은 `class="truncate"` + `title="{{ name }}"`로 잘라도 hover 시 전체가 보이게. 표 셀이 좁으면 `max-w-[200px] truncate`.
- **모바일**: 넓은 표는 `overflow-x-auto`, 헤더 우측 버튼 묶음은 `flex gap-2 flex-wrap`로 줄바꿈 허용. nav 로고 옆 텍스트는 `hidden md:inline`처럼 작은 화면에서 숨긴다.
- **숫자/날짜 현지화**: JS 포맷은 `new Intl.NumberFormat('ko-KR')`, 서버는 `|money`/`|date`. 통화 단위 `원`은 숫자 뒤 별도 `<span class="text-slate-400">원</span>`로.
- **확인 다이얼로그**: 삭제는 `onsubmit="return confirm('삭제하시겠습니까?')"`.
- **빈 상태**: "데이터 없음"을 `text-slate-400 text-center py-4`로 표시. 에러/안내는 `.card`에 `bg-green-50 border-green-200`(성공) / `bg-amber-50 text-amber-700`(경고).
- **포커스 가시성**: `.input/.select`는 포커스 시 보라 링(`box-shadow`)이 이미 적용됨 — 커스텀 입력에도 `.input` 클래스를 붙여 동일하게 맞춘다.
