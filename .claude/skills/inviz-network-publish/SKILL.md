---
name: inviz-network-publish
description: 인비즈 시스템을 사내망(인트라넷)에 배포하기 위한 전 과정 스킬 — 호스트/포트/도메인/HTTPS 설정 + hosts 파일 등록 + 서비스 재시작
when-to-use:
  - 사용자가 "사내 다른 PC에서도 접속하게 해줘"
  - "도메인으로 들어가게 해줘"
  - "https://www.invizaccount.com" 같은 명시
trigger-words: [사내망, 인트라넷, 도메인, hosts, intranet, LAN, 0.0.0.0, HTTPS]
---

# 인비즈 사내망 도메인 배포 스킬

## 목표
이 PC에서 돌고 있는 인비즈 시스템을 사내 다른 PC가 도메인으로 접속하게 만든다.

## 단계

### 1. 현재 NIC 정보 확인
```python
import socket
s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
s.connect(("8.8.8.8", 80))
lan_ip = s.getsockname()[0]   # 예: 192.168.0.108
```

### 2. settings_store에 네트워크 키 저장
| 키 | 값 예시 | 의미 |
|---|---|---|
| `net_intranet_enabled` | "1" | ON 시 자동으로 0.0.0.0 바인딩 |
| `net_bind_host` | "0.0.0.0" | 바인딩 호스트 |
| `net_port` | "8000" | 포트 |
| `net_domain` | "www.invizaccount.com" | 표시 도메인 |
| `net_https` | "0" | HTTPS on/off |
| `net_cert_path` | "" | SSL cert (HTTPS 시) |
| `net_key_path` | "" | SSL key  (HTTPS 시) |

### 3. start.bat이 동적 적용 (자동)
- `_get_bind_config.py HOST` → 0.0.0.0
- `_get_bind_config.py PORT` → 8000
- `_get_bind_config.py HTTPS_ARGS` → uvicorn ssl 인자
- `_get_bind_config.py DISPLAY_URL` → 안내 URL

### 4. Windows 방화벽 인바운드 허용 (관리자 PowerShell)
```powershell
New-NetFirewallRule -DisplayName "Inviz 8000" -Direction Inbound -Protocol TCP -LocalPort 8000 -Action Allow
```

### 5. 사내 다른 PC의 hosts 파일에 도메인 등록
- 위치: `C:\Windows\System32\drivers\etc\hosts`
- 관리자 메모장으로 열어 한 줄 추가:
```
192.168.0.108  www.invizaccount.com
```

### 6. 접속 확인
- 브라우저: `http://www.invizaccount.com:8000/`
- (80 포트 + 관리자 권한이면 포트 생략 가능)

## HTTPS 추가 단계
```cmd
openssl req -x509 -nodes -days 365 -newkey rsa:2048 ^
  -keyout C:\certs\inviz_key.pem ^
  -out C:\certs\inviz_cert.pem ^
  -subj "/CN=www.invizaccount.com"
```
→ 설정에서 cert/key 경로 입력 + 🔒 HTTPS 체크 + 포트 443

## UI 경로
- `/settings/network` — 통합 설정 페이지 (NIC 자동 감지 + hosts 가이드 카드)

## 관련 자산
- [[inviz-network-bootstrap]] — start.bat 부팅 hook
- [[inviz-business-context]] — 회사 정보
