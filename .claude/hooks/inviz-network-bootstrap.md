---
name: inviz-network-bootstrap
description: start.bat 부팅 시 settings_store에서 네트워크 바인딩을 읽어 uvicorn 명령어를 동적으로 구성하는 부팅 hook. 사내망 ON 시 자동으로 0.0.0.0 적용.
type: hook
phase: startup
trigger: start.bat 실행
implements: _get_bind_config.py
---

# 인비즈 네트워크 부트스트랩 Hook

## 동작 원리

```
사용자가 바탕화면 lnk 더블클릭
    ↓
인비즈 경영관리.lnk → start.bat 실행
    ↓
[start.bat의 부트스트랩 hook 단계]
    for /f %%i in ('python _get_bind_config.py HOST')        do set BIND_HOST=%%i
    for /f %%i in ('python _get_bind_config.py PORT')        do set BIND_PORT=%%i
    for /f %%i in ('python _get_bind_config.py HTTPS_ARGS')  do set HTTPS_ARGS=%%i
    for /f %%i in ('python _get_bind_config.py DISPLAY_URL') do set DISPLAY_URL=%%i
    ↓
[settings_store가 결정한 값으로]
    python -m uvicorn main:app --host %BIND_HOST% --port %BIND_PORT% %HTTPS_ARGS%
```

## settings_store → 환경변수 변환 규칙

| settings 키 | 처리 | uvicorn 인자 |
|---|---|---|
| `net_intranet_enabled == "1"` | 호스트가 비었거나 127.0.0.1이면 → `0.0.0.0` | `--host 0.0.0.0` |
| `net_bind_host` | 그대로 전달 (intranet OFF면) | `--host {값}` |
| `net_port` | 빈 값이면 8000 | `--port {값}` |
| `net_https == "1"` + cert/key 존재 | SSL 활성 | `--ssl-keyfile "{key}" --ssl-certfile "{cert}"` |
| `net_domain` | uvicorn 인자가 아닌 콘솔 표시 URL에만 사용 | (DISPLAY_URL) |

## 안전한 기본값 (모든 키 비었을 때)

```
HOST       = 127.0.0.1
PORT       = 8000
HTTPS_ARGS = (빈 문자열)
URL_PROTO  = http
DISPLAY_URL = http://127.0.0.1:8000/login
```

## settings_store 로드 실패 시
- `try/except`로 감싸 기본값 출력 → start.bat이 fail-open으로 동작
- 즉 설정이 깨져도 서버는 최소한 127.0.0.1:8000으로 뜸

## 관리자 권한 안내 (80/443 사용 시)
- start.bat을 우클릭 → "관리자 권한으로 실행"
- 또는 lnk 속성에서 "관리자 권한으로 실행" 체크박스

## 적용된 파일
- `web_app/_get_bind_config.py` (헬퍼)
- `web_app/start.bat` (호출)
- `web_app/settings_store.py` (7개 키 등록)
- `routers/settings.py` — `/settings/save`의 network 섹션 처리

## 관련 자산
- [[inviz-network-publish]] — 사내망 배포 스킬 (이 hook 사용)
- [[inviz-business-context]] — 회사 도메인 컨벤션
