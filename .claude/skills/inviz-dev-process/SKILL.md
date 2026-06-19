---
name: inviz-dev-process
description: 인비즈 개발 루프 — 파악→설계→구현→검증(HTTP 스모크)→서버 재시작→DB 수치검증→정리→커밋(비밀안전).
---

인비즈 경영관리 시스템(FastAPI + SQLAlchemy 2.0 + SQLite + Jinja2/HTMX)의 표준 개발 루프. 작은 변경 하나도 "구현했다"로 끝내지 말고, **서버 재시작 → HTTP 스모크 → DB 수치검증**까지 돌려서 실제로 동작함을 확인한 뒤 마무리한다.

## 개발 루프 (8단계)

1. **파악** — Read/Grep으로 영향 범위 확인 (아래 체크리스트)
2. **설계** — 모델/라우터/템플릿/nav 중 어디를 건드릴지 결정
3. **구현** — 최소 변경, 기존 컴포넌트 클래스 재사용
4. **검증** — HTTP 스모크 하니스 실행 (status 200 + 오류 문자열 미포함)
5. **재시작** — uvicorn 종료 → 환경변수 → 숨김 재기동 → 포트 폴링
6. **수치검증** — sqlite3로 app.db 직접 조회, 기대값 대조
7. **정리** — 테스트 행 삭제, 임시 파일 제거
8. **커밋** — *요청 시에만*. 비밀안전 2단계 스캔 후 커밋

### 1단계: 파악 체크리스트

```
# 모델: 어떤 테이블/컬럼을 쓰나
grep -n "class .*Base" web_app/models.py

# 라우터: 이 URL은 어느 파일에 있나
grep -rn "@router.get\|@router.post" web_app/routers/

# 템플릿: 어떤 페이지가 이 데이터를 그리나
grep -rln "기존_변수명" web_app/templates/

# nav: 새 페이지면 좌측 메뉴(nav_items)에 등록 필요
grep -n "nav_items" web_app/helpers.py
```

새 페이지/메뉴를 추가하면 `nav_items()`에 항목을 넣어야 좌측 네비에 노출된다. 빠뜨리면 라우트는 살아있는데 메뉴엔 안 보인다.

## ★ 서버 재시작 패턴 (HTTPS)

코드를 고쳤으면 **반드시 재시작**해야 반영된다(특히 모델·전역·settings). 순서대로:

### (a) 기존 uvicorn 종료

```powershell
Get-CimInstance Win32_Process |
  Where-Object { $_.Name -eq 'python.exe' -and $_.CommandLine -like '*uvicorn main:app*' } |
  ForEach-Object { Stop-Process -Id $_.ProcessId -Force }
```

### (b) 환경변수 설정 (로그인 비밀번호 / 세션 시크릿)

```powershell
$env:INVIZ_PASSWORD = "실제_운영_비밀번호"
$env:INVIZ_SECRET   = "실제_세션_시크릿"
$env:PYTHONIOENCODING = "utf-8"
```

이 두 변수가 없으면 `/login`이 기대대로 통과하지 않거나 세션 쿠키가 매번 무효화될 수 있다.

### (c) 숨김 재기동 (콘솔 창 없이 백그라운드)

```powershell
cscript //nologo web_app/_run_server_hidden.vbs 8000 "--ssl-keyfile certs\inviz_key.pem --ssl-certfile certs\inviz_cert.pem"
```

런처는 포트(8000)와 추가 uvicorn 인자를 받아 HTTPS로 띄운다. 인증서는 `certs\inviz_key.pem` / `certs\inviz_cert.pem`.

### (d) 포트 LISTENING 폴링 (기동 완료 대기)

```powershell
$ready = $false
1..30 | ForEach-Object {
  if (-not $ready) {
    $c = Get-NetTCPConnection -LocalPort 8000 -State Listen -ErrorAction SilentlyContinue
    if ($c) { $ready = $true; "READY" } else { Start-Sleep -Milliseconds 500 }
  }
}
if (-not $ready) { "FAILED to start" }
```

`READY`가 떠야 스모크 테스트로 넘어간다. 안 뜨면 import 에러 가능성 — 잠깐 포그라운드로 `python -m uvicorn main:app`을 띄워 traceback을 본다.

## ★ HTTP 스모크 테스트 하니스 (Python urllib + cookiejar)

로컬 자체서명 HTTPS이므로 **ssl 검증을 끈다**. 로그인 후 쿠키를 유지하며 페이지를 받아 status 200과 오류 문자열 미포함을 확인한다.

```python
import ssl, urllib.request, urllib.parse, http.cookiejar

BASE = "https://localhost:8000"
PW   = "실제_운영_비밀번호"  # = INVIZ_PASSWORD
BAD  = ("Traceback", "UndefinedError", "Internal Server Error")

ctx = ssl.create_default_context()
ctx.check_hostname = False
ctx.verify_mode = ssl.CERT_NONE

cj = http.cookiejar.CookieJar()
opener = urllib.request.build_opener(
    urllib.request.HTTPSHandler(context=ctx),
    urllib.request.HTTPCookieProcessor(cj),
)

def login():
    data = urllib.parse.urlencode({"password": PW}).encode()
    r = opener.open(BASE + "/login", data=data)  # POST
    assert r.status == 200, f"login status {r.status}"

def check(path):
    r = opener.open(BASE + path)
    html = r.read().decode("utf-8", "replace")
    assert r.status == 200, f"{path} -> status {r.status}"
    for b in BAD:
        assert b not in html, f"{path} contains '{b}'"
    print(f"OK {path}  ({len(html)} bytes)")

login()
for p in ["/", "/sales", "/purchases", "/contracts", "/loans"]:
    check(p)
print("SMOKE PASS")
```

### 한글 쿼리파라미터

GET 쿼리에 한글을 넣으면 `urllib`이 ascii로 인코딩하려다 에러난다. 반드시 `quote`로 감싼다.

```python
q = urllib.parse.quote("거래처명")           # 단일 값
qs = urllib.parse.urlencode({"q": "병원"})    # dict 전체 (한글 자동 처리)
check(f"/parties?q={q}")
```

### 업로드(multipart) 수작업

폼 업로드는 multipart 바디를 손으로 만든다.

```python
import uuid
def post_file(path, field, filename, content: bytes, extra: dict):
    boundary = uuid.uuid4().hex
    parts = []
    for k, v in extra.items():
        parts.append(f"--{boundary}\r\nContent-Disposition: form-data; name=\"{k}\"\r\n\r\n{v}\r\n".encode())
    parts.append(
        f"--{boundary}\r\nContent-Disposition: form-data; "
        f"name=\"{field}\"; filename=\"{filename}\"\r\n"
        f"Content-Type: application/octet-stream\r\n\r\n".encode()
        + content + b"\r\n"
    )
    parts.append(f"--{boundary}--\r\n".encode())
    body = b"".join(parts)
    req = urllib.request.Request(BASE + path, data=body)
    req.add_header("Content-Type", f"multipart/form-data; boundary={boundary}")
    return opener.open(req)
```

## settings_store 캐시 주의

`settings_store`는 값을 캐시한다.

- **같은 프로세스 내** `save()`는 캐시를 invalidate → 즉시 반영.
- **별도 프로세스**(스크립트/sqlite 직접 수정)에서 설정을 바꾸면, **실행 중인 서버는 옛 값을 계속 보유**한다. → 반드시 서버를 **재시작**해야 반영된다.

설정 변경 후 동작이 안 바뀌면 "재시작 안 함"을 먼저 의심하라.

## 수치 검증 (sqlite3 직접 조회)

UI/응답만 보지 말고 **app.db를 직접 조회**해 기대값과 대조한다.

```bash
sqlite3 web_app/app.db "SELECT COUNT(*), SUM(amount) FROM fact_sale WHERE year=2024;"
```

```python
import sqlite3
con = sqlite3.connect("web_app/app.db")
cur = con.cursor()
cur.execute("SELECT id, party_id, amount FROM fact_sale WHERE id=?", ("S-WEB-TEST",))
print(cur.fetchone())   # 방금 입력한 값이 그대로 들어갔나
```

### 필드 매핑 오판 방지

여러 컬럼이 **비슷한 값**이면 어느 필드에 들어갔는지 헷갈린다. 검증용 입력은 **서로 다른 구분되는 값**을 쓴다.

```
amount = 12345,  vat = 678,  qty = 9     # 우연히 겹치지 않는 값
```

중복·교차 데이터로는 "맞게 들어갔다"를 단정하지 말 것 — 다른 행의 값과 우연히 일치할 수 있다.

### 검증 후 테스트 행 삭제

```bash
sqlite3 web_app/app.db "DELETE FROM fact_sale WHERE id='S-WEB-TEST';"
```

웹 입력 보존 규칙(`source_file='web_app'`은 동기화에서 안 지워짐) 때문에 테스트 행을 남기면 영구 잔존한다. 반드시 정리.

## 한글 처리

- 콘솔/스크립트 출력 깨짐 → `PYTHONIOENCODING=utf-8` (PowerShell: `$env:PYTHONIOENCODING = "utf-8"`).
- **Bash + curl + 한글 form-data → 깨진다.** curl 대신 위의 **Python urllib 하니스**를 쓴다.
- FAISS는 ASCII 경로만 (`%LOCALAPPDATA%\Inviz\vector_store`). 한글 경로로 save_local 하지 말 것.

## 커밋 (요청 시에만)

사용자가 명시적으로 요청할 때만 커밋한다. 기본 브랜치에 있으면 **먼저 브랜치를 판다**. (git 저장소 루트는 프로젝트 루트 `00.경영관리마스터` — 아래 명령은 그 루트에서 실행. `.claude/hooks/precommit_guard.py`가 민감 파일 스테이징을 자동 차단한다.)

```bash
git rev-parse --abbrev-ref HEAD
# main/master면:
git checkout -b feature/짧은-설명
```

### 비밀안전 2단계 스캔 (커밋 전 필수)

**1단계 — 파일명**: 스테이징 목록에 비밀/실데이터 파일이 없는지.

```bash
git diff --cached --name-only
# *.db .env *.pem *.key certs/ vector_store/ *.xlsx 업로드 파일 → 있으면 unstage + .gitignore 확인
```

**2단계 — 내용**: diff 본문에 비밀값이 박혀있지 않은지.

```bash
git diff --cached |
  grep -niE "INVIZ_PASSWORD|INVIZ_SECRET|password\s*=|secret\s*=|-----BEGIN|api[_-]?key"
```

위 명령에 운영 비밀번호/시크릿/키가 잡히면 **커밋 중단**, 코드에서 제거(환경변수로 빼기) 후 재스캔.

### .gitignore 가드

다음은 이미 `.gitignore`로 차단되어야 한다(누락 시 추가): `*.db`, `.env*`, `*.pem`/`*.key`, `certs/`, `vector_store/`/`*.faiss`, 업로드 파일, `*.xlsx`/`*.xls`, 서버 런처 등 로컬 전용 파일.

### 커밋 메시지

```bash
git commit -m "feat(sales): 거래처별 매출 합계 KPI 추가"
```

한국어 요약 + 변경 의도. 시크릿은 절대 메시지에 쓰지 않는다.

## 메모리 (비자명한 사실 기록)

코드만 봐서는 알 수 없는 사실(왜 이렇게 했는지, 외부 의존, 함정)은 메모리 디렉토리에 저장한다. "무엇을"이 아니라 **"왜/어떻게"**를 남긴다.

예: "메일 자동발송 실패 시 코드가 아니라 메일플러그 IMAP/SMTP 외부허용을 먼저 확인", "급여 PDF 열기암호=생년월일 6자리", "은행 자동 계좌연결은 보안상 불가, 엑셀/CSV 업로드만".
