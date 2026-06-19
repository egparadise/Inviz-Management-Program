# 인비즈 경영관리 웹

사내 PC 한 대에서 구동되는 FastAPI + SQLite 기반 경영관리 시스템.
경영지원팀 2~5명이 같은 사내망에서 공유 사용합니다.

## 빠른 시작

### 최초 설치 (한 번만)
```
install.bat
```
- Python 패키지 설치
- Excel 마스터 워크북을 읽어 `app.db` 생성

### 매일 사용
```
start.bat
```
- 서버 시작. 창을 닫으면 종료
- 같은 PC: http://localhost:8000
- 사내 다른 PC: http://[이 PC의 IPv4 주소]:8000 (start.bat이 IP를 표시함)
- 공동 비밀번호: `.env`/`start.bat`의 `INVIZ_PASSWORD`로 설정 (변경 권장 — 아래 참조)

### 일일 백업
- `backup.bat`을 Windows 작업 스케줄러에 매일 등록
- `db_backup/app_YYYYMMDD_HHMMSS.db` 형식으로 보관 (30일 자동 정리)

### 🛡 자가발전 시스템 (권장)
모든 안전 장치를 포함한 통합 시스템. 일반 동기화 대신 이걸 사용 권장.

```
register_safe_sync_task.bat
```
- 한 번 더블클릭 → 매일 04:00 안전 동기화 자동 실행
- 백업 + 동기화 + 무결성 검증 + LLM 자동 분류 + 벡터 재인덱싱 + 변조 차단

수동 실행:
- 웹: `/self-dev` → "🚀 안전 동기화 실행"
- CLI: `safe_sync.bat`

### 자동 동기화 (신규 자료 자동 반영)
경영진/회계가 14.경영정보 폴더에 새 Excel 파일을 떨어뜨리거나 기존 파일을 갱신하면, 매일 새벽 자동으로 DB에 반영됩니다.

```
register_sync_task.bat
```
- 한 번만 더블클릭 → Windows 작업 스케줄러에 매일 04:00 동기화 등록
- 시간 변경: 파일 안 `/ST 04:00` 부분을 원하는 시각으로 수정 후 재실행
- 해제: `unregister_sync_task.bat`

수동 실행:
- 웹: `/sync` → "지금 동기화 실행" 버튼
- CLI: `sync.bat` 더블클릭
- `sync_log/sync_YYYYMMDD.log`에 결과 기록

---

## 구성

| 파일 | 역할 |
|---|---|
| `main.py` | FastAPI 앱 진입점, 인증 미들웨어, 대시보드 |
| `models.py` | 16개 테이블 SQLAlchemy 모델 |
| `database.py` | DB 엔진·세션·연결 |
| `auth.py` | 공동 비밀번호 인증 + 세션 쿠키 |
| `helpers.py` | Jinja2 템플릿·포맷 필터 |
| `migrate.py` | Excel 마스터 → SQLite 마이그레이션 |
| `routers/` | 8개 도메인 라우터 (매출/매입/계약/급여/차입금/거래처/제품/직원) |
| `templates/` | Jinja2 템플릿 (base + 도메인별 list/form) |
| `app.db` | SQLite 데이터 파일 (사내 PC에 보관, 백업 대상) |
| `db_backup/` | 일일 백업 사본 |
| `sync_core.py` | 동기화 엔진 (스캔·감지·실행) |
| `sync_handlers.py` | 도메인별 ETL 핸들러 (14개) |
| `sync.bat` | 동기화 실행 배치 (작업 스케줄러용 + 수동) |
| `register_sync_task.bat` | 매일 04:00 동기화 작업 등록 |
| `unregister_sync_task.bat` | 동기화 작업 해제 |
| `sync_log/` | 일별 sync 로그 (30일 자동 정리) |

---

## 도메인 (8개 메뉴)

| 메뉴 | URL | 기능 |
|---|---|---|
| **대시보드** | `/` | 연간 KPI, 월별 추이, 제품별 매출, 거래처 TOP10, 미수금 TOP10, 차입금·계약 현황 |
| **매출** | `/sales` | 3,458건 트랜잭션. 연도·월·거래처·제품·키워드 필터. CRUD |
| **매입** | `/purchases` | 1,080건. 동일 필터·CRUD |
| **계약** | `/contracts` | 299건. 진행/만료 상태, 잔여일수 자동계산, 미수금 추적 |
| **급여** | `/payroll` | 616건 급여대장. 연도별 월 인건비 요약 |
| **차입금** | `/loans` | 차입금 마스터 25건 + 임원 차입 movements 128건 |
| **거래처** | `/parties` | 984개 거래처 마스터. 카테고리·활성 필터 |
| **제품** | `/products` | 10개 제품 + 13개 자동매핑 룰 (품명 → 제품코드) |
| **직원** | `/employees` | 56명 직원 마스터. 재직/퇴직, 부서별 |

---

## 데이터

- **Excel 마스터:** 상위 폴더 `인비즈_경영관리마스터_v1.xlsx`
- **SQLite DB:** `app.db` (2.4MB, 7,678행)
- 신규 입력은 DB에 즉시 반영, Excel은 변경되지 않음
- 백업: 일일 `db_backup/` + OneDrive 자동 동기화

### 재마이그레이션 (Excel을 새로 만들었을 때)
```
python migrate.py
```
- 기존 `app.db`는 `db_backup/app_YYYYMMDD_HHMMSS.db`로 자동 백업
- 마이그레이션 후 신규 데이터 입력은 처음부터 다시 (Excel을 기준점으로 삼는 패턴)

---

## 비밀번호 변경

`start.bat` 파일을 메모장으로 열어 `set INVIZ_PASSWORD=` 줄의 값을 변경 후 저장.
변경 즉시 모든 사용자에게 적용되므로 사내 공지 필요.

`INVIZ_SECRET`은 세션 쿠키 서명용 — 신규 PC 설치 시 한 번만 변경 후 그대로 둡니다.

---

## 사내망 접속 가이드

1. `start.bat` 실행 → IP 표시됨 (예: `192.168.1.50`)
2. 같은 사내망에 있는 다른 PC에서 브라우저 → `http://192.168.1.50:8000`
3. 비밀번호 입력 후 사용
4. 만약 접속 불가 시: Windows 방화벽에서 포트 8000 인바운드 허용

서버를 항상 켜두려면 PC 전원 옵션을 "절전 안 함"으로 설정하고 `start.bat`을 시작 프로그램에 등록.

---

## 기술 스택

- Python 3.14 + FastAPI 0.136 + SQLAlchemy 2.0 + SQLite
- Jinja2 + HTMX 1.9 + Tailwind CSS (CDN) + Chart.js 4.4
- 인증: itsdangerous 세션 쿠키 (12시간 유효)

## API 문서
- `/api/docs` — Swagger UI (개발자용)
- `/api/health` — 헬스체크

---

## 자동 동기화 상세

### 작동 원리
1. **스캔:** `14.경영정보` 폴더 전체를 재귀 walk → `.xlsx/.xls/.xlsm` 파일 수집 (00.경영관리마스터 자기 폴더는 제외)
2. **변경 감지:** 각 파일의 `mtime + size` 1차 비교, 다르면 SHA256으로 2차 확인 (`file_registry` 테이블에 기록)
3. **도메인 매핑:** 파일명을 정규식 패턴과 매칭해 도메인 결정 (매출/매입/계약/차입금/급여/...)
4. **최신 1건 선택:** 같은 도메인의 여러 파일 중 mtime이 가장 최신인 1건만 처리 (예: `외상매출금(20260422).xlsx` vs `외상매출금(20260520).xlsx` → 더 최신)
5. **DB 반영:** 도메인별 핸들러가 기존 source_file 데이터를 삭제하고 신규 적재 (`web_app`으로 표시된 수동 입력 데이터는 보존)
6. **로그:** `sync_run` + `sync_run_detail` 테이블에 모든 실행·파일별 결과 기록

### 매핑되는 도메인 (14종)
| 도메인 | 파일명 패턴 | 적재 대상 테이블 |
|---|---|---|
| `sale_classification` | `매출분류...xlsx` | fact_sale |
| `sale_ar` | `외상매출금...xlsx` | fact_sale |
| `purchase_ap` | `외상매입금...xlsx` | fact_purchase |
| `sale_purchase_invoice` | `거래처별매입매출세금계산서...xlsx` | fact_sale + fact_purchase |
| `contract` | `_계약관리...xlsx` | master_contract |
| `receivable` | `미수금 현황...xlsx` | fact_receivable |
| `loan_movement` | `단기차입금...임원...xlsx` | fact_loan |
| `loan_master_long` | `주요계정명세서...xlsx` | master_loan (은행) |
| `payroll_dept` | `부서별 인건비...xlsx` | fact_payroll |
| `payroll_ledger` | `급여대장...xlsx` | fact_payroll |
| `expense_monthly` | `월별 비용정리...xlsx` | fact_expense |
| `rental` | `관리비...렌탈...xlsx` | fact_rental |
| `severance` | `퇴직연금...월별...xlsx` | fact_severance |
| `reading_fee` | `5) 판독수수료...xlsx` | (핸들러 미구현) |

매칭되지 않은 파일은 `unmapped` 상태로 file_registry에 기록만 됨 (DB에 적재 안 됨).

### 안전 장치
- **수동 입력 데이터 보존:** 웹에서 입력한 데이터(`source_file = 'web_app'`)는 절대 삭제·갱신되지 않음
- **트랜잭션:** 각 도메인 핸들러는 트랜잭션 안에서 실행, 실패 시 롤백
- **백업 우선:** 동기화 전에 `backup.bat`을 작업 스케줄러로 03:30에 등록해두면, 04:00 sync 직전에 백업 보장

### 신규 자료 추가 절차
1. 14.경영정보 폴더에 파일 추가 (기존 파일명 패턴을 따르면 자동 인식)
2. 다음 04:00 또는 `/sync` → "지금 동기화 실행"
3. `/sync` 페이지에서 처리 결과 확인
4. 새 파일이 미매핑(unmapped)이면, `sync_core.py`의 `DOMAIN_MATCHERS`에 패턴 추가 + 도메인 핸들러를 `sync_handlers.py`에 추가

### 등록·해제 명령
```cmd
register_sync_task.bat       :: 등록 (매일 04:00)
schtasks /Query /TN "Inviz_DailySync" /FO LIST   :: 상태 확인
schtasks /Run /TN "Inviz_DailySync"               :: 즉시 1회 실행
unregister_sync_task.bat      :: 해제
```

---

## 알려진 제약 / TODO

- 1차 버전은 매출/매입/계약/차입금/거래처/제품/직원/급여 8개만 CRUD. 다음은 비용/미수금/임대료/퇴직금/판독수수료를 추가.
- 감사 로그 테이블(`audit_log`)은 준비되어 있으나 자동 기록 미들웨어 미구현 — 향후 추가.
- Excel 백업본은 OneDrive로 별도 동기화. 웹 입력분은 DB에만 존재 (Excel으로 export 기능은 향후 추가).
