---
name: inviz-troubleshoot
description: 인비즈 문제 해결 플레이북 — 라우트 422·한글 인코딩·마이그레이션·설정캐시·메일/은행 연동·비밀안전 등 실전 함정과 해결.
---

인비즈 경영관리 시스템 개발에서 실제로 겪은 함정과 해결법. **증상 → 원인 → 해결** 순으로 찾는다. 각 항목에 한 줄 진단 명령을 붙였다.

## 1. 라우트 / FastAPI

### POST·GET이 422 `int_parsing` (loc에 path id)
**증상**: `/parties/new` 같은 리터럴 경로 요청에 `{"type":"int_parsing","loc":["path","party_id"]}` 422.
**원인**: 동적 `/{party_id:int}` 라우트가 먼저 등록되어 리터럴 경로(`/new`)를 가로챔. FastAPI는 등록 순서대로 매칭한다.
**해결**: 리터럴 라우트를 동적 라우트보다 **먼저** 선언.
```python
@router.get("/parties/new")        # 먼저 — 리터럴
def party_new(): ...

@router.get("/parties/{party_id:int}")   # 나중 — 동적
def party_detail(party_id: int): ...
```
**진단**: 라우터에서 등록 순서 확인 — `grep -n "parties/" web_app/routers/parties.py`

### Jinja에서 `row[k]` subscript 실패
**증상**: 템플릿에서 `{{ row[col] }}` 가 `TypeError: 'X' object is not subscriptable`.
**원인**: SQLAlchemy ORM 객체는 dict가 아니라 속성 접근 객체.
**해결**: getattr 폴백을 거치는 전역/필터를 쓰거나, 핸들러에서 `dict`로 변환해 넘긴다. 속성 접근(`row.col`)은 항상 동작.
**진단**: `python -c "from web_app.models import Party; print(hasattr(Party,'__getitem__'))"`

## 2. 한글 인코딩

### 콘솔 한글 깨짐 (cp949)
**증상**: Windows 콘솔에서 `print()` 한글이 `???`/모지바케.
**원인**: Windows 기본 콘솔 코드페이지 cp949.
**해결**: 실행 전 환경변수 설정.
```cmd
set PYTHONIOENCODING=utf-8
```
**진단**: `python -c "import sys; print(sys.stdout.encoding)"` → `utf-8` 이어야 함.

### Bash + curl 한글 form-data 깨짐
**증상**: curl로 한글 폼 전송 시 DB에 깨진 문자 저장.
**원인**: Git Bash/curl의 form-data 인코딩이 UTF-8로 안 넘어감.
**해결**: curl 대신 Python `urllib`로 테스트.
```python
import urllib.request, urllib.parse
data = urllib.parse.urlencode({"name": "테스트거래처"}).encode("utf-8")
req = urllib.request.Request("http://127.0.0.1:8000/parties/new", data=data)
print(urllib.request.urlopen(req).status)
```
**진단**: 같은 값을 urllib로 보내 깨지면 코드 문제, 안 깨지면 curl 문제.

### PDF 한글 깨짐 (□□□)
**증상**: PDF Export·급여명세서에서 한글이 빈 네모로.
**원인**: 폰트 미등록 — 기본 폰트에 한글 글리프 없음.
**해결**: 로컬은 `malgun.ttf`, Docker는 `fonts-nanum` 등록 확인.
```python
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
pdfmetrics.registerFont(TTFont("Malgun", r"C:\Windows\Fonts\malgun.ttf"))
```
**진단**: `python -c "import os; print(os.path.exists(r'C:\Windows\Fonts\malgun.ttf'))"`

## 3. 마이그레이션 / DB

### 새 컬럼이 안 생김
**증상**: 모델에 컬럼 추가했는데 SQLite에 반영 안 됨, `no such column` 에러.
**원인**: SQLAlchemy `create_all()`은 **없는 테이블만** 만든다. 기존 테이블에 컬럼 추가는 안 함.
**해결**: 직접 `ALTER TABLE`.
```sql
ALTER TABLE fact_sale ADD COLUMN memo VARCHAR(200);
```
**진단**: `python -c "import sqlite3; print([r[1] for r in sqlite3.connect('web_app/app.db').execute('PRAGMA table_info(fact_sale)')])"`

### raw sqlite insert가 NOT NULL 실패
**증상**: `sqlite3`로 직접 INSERT 시 `NOT NULL constraint failed`.
**원인**: 모델의 `default=`는 ORM 레벨에서만 채워진다. raw SQL은 안 거침.
**해결**: ORM(`db.add(...)` / `bulk_save_objects`)으로 insert하거나, raw SQL이면 모든 NOT NULL 값을 직접 채운다.
```python
db.add(Sale(txn_id="S-web-1", amount=0, source_file="web_app"))  # default 적용됨
```
**진단**: `python -c "import sqlite3; print([(r[1],r[3]) for r in sqlite3.connect('web_app/app.db').execute('PRAGMA table_info(fact_sale)') if r[3]])"` (NOT NULL 컬럼 목록)

## 4. 설정 캐시

### 설정 바꿨는데 반영 안 됨
**증상**: `/settings`에서 또는 DB에서 값 바꿨는데 동작 그대로.
**원인**: `settings_store`가 값을 메모리 캐시한다. **별도 프로세스**(스크립트·다른 콘솔)에서 바꾸면 실행 중인 서버는 모름.
**해결**: 서버 재시작, 또는 같은 프로세스 내에서 변경. 스케줄러·sync가 바꾼 값은 서버가 못 봄.
**진단**: `python -c "from web_app.settings_store import setting; print(setting('키'))"` 를 별도 콘솔에서 실행해 DB 실제값 확인 → 서버 화면값과 비교.

## 5. 테스트 데이터 함정

### 필드가 한 칸씩 밀려 보임
**증상**: 화면에서 컬럼 값이 옆 필드로 밀려 출력되는 것처럼 보임.
**원인**: 실제 밀림이 아니라 **테스트 데이터 교차·이전 행 잔존**. 비슷한 더미값이 섞여 착시.
**해결**: 구분되는 고유값(예: `name="ZZZ구분용"`)으로 **깨끗한 상태**에서 재현해 확인. 진짜 버그인지 데이터 문제인지 분리.
**진단**: `python -c "import sqlite3; [print(r) for r in sqlite3.connect('web_app/app.db').execute(\"select * from fact_sale where source_file='web_app' order by id desc limit 5\")]"`

## 6. 외부 연동

### 메일 자동발송 안 됨
**증상**: 명세서·알림 메일이 코드상 정상인데 안 나감.
**원인**: 코드가 아니라 **메일플러그 계정 보안설정** — IMAP/SMTP 외부 접속 차단.
**해결**: 코드 디버깅 전에 메일플러그 관리자에서 IMAP/SMTP 외부 허용부터 확인. TCP/TLS는 붙는데 `AUTH` 단계에서 거부되면 거의 정책 문제.
**진단**:
```python
import smtplib
s = smtplib.SMTP_SSL("smtp.mailplug.co.kr", 465, timeout=5)
print("연결 OK"); s.login("계정", "비번")  # 여기서 AUTH 거부 → 외부허용 설정 문제
```

### 은행 계좌 자동연결 불가
**증상**: `/banking`에서 계좌 잔액·거래내역을 자동으로 끌어오고 싶음.
**원인**: 개인 인증정보(공인인증서·아이디/비번) 입력 기반 스크래핑은 **보안상 금지**. 정식 자동연결은 오픈뱅킹 **기관(법인) API**만 가능.
**해결**: 엑셀/CSV 업로드 기반으로 운영. 자동화가 필요하면 오픈뱅킹 기관 API 신청.
**진단**: 요구가 "개인 로그인 정보 입력"이면 즉시 중단 — 업로드 방식으로 전환.

## 7. 비밀 안전 (커밋)

### 커밋에 비밀 섞임 위험
**증상**: SMTP 비번·세션 시크릿 같은 실제 비밀이 커밋에 들어갈 위험.
**원인**: 코드 기본값에 실제 비밀번호 하드코딩, 또는 `.env`/`start.bat` 추적.
**해결**: `git add` 후 **2단계 스캔** — ① 파일명 ② 내용(알려진 비밀 리터럴). 코드 기본값의 실제 비밀번호는 플레이스홀더로 치환하고, 실제값은 `.env`/`start.bat`에 두고 `.gitignore`.
**진단** (2단계):
```bash
git diff --cached --name-only                              # ① 파일명 스캔
git diff --cached | grep -iE "password|secret|smtp|api_key|mailplug"   # ② 내용 스캔
```

### HTTPS self-signed 신뢰 실패
**증상**: 로컬 HTTPS 테스트 시 `CERTIFICATE_VERIFY_FAILED`.
**원인**: 자체 서명 인증서(`certs/`)를 클라이언트가 신뢰 안 함.
**해결**: 테스트 한정으로 검증 끄기. (운영 코드엔 절대 남기지 말 것.)
```python
import ssl, urllib.request
ctx = ssl.create_default_context(); ctx.check_hostname=False; ctx.verify_mode=ssl.CERT_NONE
print(urllib.request.urlopen("https://127.0.0.1:8000/", context=ctx).status)
```
**진단**: `python -c "import os; print(os.path.exists('web_app/certs/cert.pem'))"`

## 빠른 점검 순서

1. **422/404 라우트** → 리터럴이 동적보다 먼저인지
2. **한글 깨짐** → 콘솔이면 `PYTHONIOENCODING`, 폼이면 urllib, PDF면 폰트
3. **DB 반영 안 됨** → 컬럼이면 `ALTER TABLE`, 설정이면 서버 재시작
4. **연동 안 됨** → 코드 전에 외부 계정/정책 설정부터
5. **커밋 전** → 파일명+내용 2단계 비밀 스캔
