# 인비즈 경영관리 — 인터넷 배포 가이드

> ⚠️ **중요(보안)**: 이 프로그램은 매출·급여·세금계산서·사업자번호·API키 등 **민감한 회사 재무정보**를 담고 있습니다.
> 인터넷에 공개하면 누구나 주소를 알면 접근을 시도할 수 있으므로, 아래 **보안 체크리스트**를 반드시 지키세요.
> 가능하면 **완전 공개 대신** 회사 IP만 허용(방화벽/Cloudflare Access/VPN)하는 것을 권장합니다.

이 패키지는 **Docker** 한 줄로 배포되며, **Caddy**가 도메인에 **자동 HTTPS(Let's Encrypt)** 를 붙여줍니다.

---

## A. 준비물
1. **서버 1대** — Ubuntu 22.04+ VPS(예: Vultr/Linode/AWS Lightsail/네이버클라우드, 1~2GB RAM) 또는 사내 리눅스 서버
2. **도메인 1개** — 예) `inviz.example.com` (없어도 IP+`:80` 테스트는 가능)
3. 서버에 **Docker + Compose** 설치:
   ```bash
   curl -fsSL https://get.docker.com | sh
   sudo usermod -aG docker $USER   # 재로그인
   ```

## B. 코드 배포 (git)
코드만 git으로 가져옵니다. **민감정보(DB·.env·API키·인증서·벡터)는 git에 없으며**, 아래 C의 데이터 패치로 따로 전달합니다.
```bash
git clone <비공개_저장소_URL> inviz && cd inviz/web_app
```
(또는 `web_app` 폴더를 `scp`/WinSCP로 복사. 배포 파일: `Dockerfile`, `docker-compose.yml`, `Caddyfile`, `requirements-deploy.txt`, `.dockerignore`, `.env.example`)

## C. 데이터 패치 적용 (중요 — DB·설정·API키·벡터)
현재 PC에서 패치를 만들고, 서버로 **안전하게** 전달한 뒤 적용합니다.
```bash
# (현재 PC, web_app 폴더에서) 데이터 패치 생성 → ../inviz_data_patch.zip
python make_data_patch.py
#  → app.db, .env, certs, vector_store, report_templates/snapshots, doc_uploads,
#    (선택) 통합 Excel 마스터 가 한 파일로 묶임. git/메일 금지, USB·사내 보안채널로 전달.

# (서버, web_app 폴더에서) 패치 업로드 후 적용
scp inviz_data_patch.zip  서버:/경로/inviz/inviz_data_patch.zip   # 또는 WinSCP
python3 apply_data_patch.py --docker     # app.db→data/app.db, vector_store→data/vector_store, .env→.env ...
```
> 패치를 적용하지 않으면 **빈 새 DB·설정 없음**으로 시작합니다. **API키·메일·카카오·텔레그램 비밀번호는 app.db(app_setting) 안**에 있으므로 패치로 함께 전달됩니다.
> 이후 키만 바꿀 때는 서버 **설정 화면**에서 수정하거나, 새 패치를 다시 적용하면 됩니다.

## D. 환경변수(.env) 작성
```bash
cp .env.production.example .env
nano .env
```
- `INVIZ_PASSWORD` : **강력한** 공유 비밀번호
- `INVIZ_SECRET`   : 아래로 생성해 붙여넣기 → `python3 -c "import secrets;print(secrets.token_hex(32))"`
- `SITE_ADDRESS`   : 도메인(예 `inviz.example.com`). 도메인 없으면 `:80`

> 도메인이라면 먼저 **DNS A레코드**가 서버 공인 IP를 가리키게 설정하세요(HTTPS 자동발급에 필요).

## E. 실행 + LLM 모델 받기
```bash
docker compose up -d --build      # 앱 + Caddy + Ollama(LLM) 기동
./pull_models.sh                  # Ollama에 bge-m3(임베딩)·llama3.1(LLM) 다운로드 (수 GB, 1회)
docker compose logs -f app        # 시작 로그 확인 (Ctrl+C 로 빠져나오기)
```
브라우저에서 `https://inviz.example.com` 접속 → 비밀번호 로그인.
> 모델은 `ollama_models` 볼륨에 영속 저장되어 재시작해도 다시 받지 않습니다.
> RAM이 부족하면(2GB급) 큰 LLM은 느릴 수 있습니다 — 4~8GB+ 권장, GPU 서버면 compose의 GPU 블록 주석 해제.

## F. 업데이트 / 운영
```bash
docker compose up -d --build      # 코드 갱신 후 재배포
docker compose restart app        # 앱만 재시작
docker compose down               # 중지
```

---

## 🔐 보안 체크리스트 (반드시)
- [ ] **강력한 `INVIZ_PASSWORD`** + 접속 후 **설정 ▸ 비밀번호 변경**(DB에 해시 저장)
- [ ] `INVIZ_PUBLIC=1` 유지 — **서버 폴더 탐색 비활성화**(공개환경 필수, compose에 기본 설정됨)
- [ ] 서버 **방화벽**: 80/443 만 개방 (예: `ufw allow 80,443/tcp; ufw enable`)
- [ ] **접근 제한 권장**: 회사 고정 IP만 허용하거나 **Cloudflare(프록시+Access)** / VPN 뒤에 두기
- [ ] `.env`·`data/app.db` 는 **절대 git/공개 금지** (`.dockerignore`로 이미지에도 미포함)
- [ ] **정기 백업**: `data/app.db` 를 매일 외부로 복사 (앱 내 `db_backup/` + 서버 외부 보관)
- [ ] HTTPS 확인(자물쇠), 관리자 외 계정 공유 금지

## 🤖 AI(Llama) 기능
- 이 배포는 **Ollama 컨테이너를 포함**하므로, `./pull_models.sh` 로 모델을 받으면 **RAG 챗·자기학습·자가발전·요율 AI검색** 등 로컬 LLM 기능이 서버에서도 동작합니다.
- 앱은 `OLLAMA_HOST=http://ollama:11434` 로 자동 연결됩니다(compose에 설정됨).
- 더 빠르거나 고품질이 필요하면 **설정 ▸ AI 공급자**에서 **OpenAI/Anthropic/Gemini** 키를 등록해 병행할 수 있습니다. (단, **자기학습은 항상 오픈소스 Ollama만** 사용)
- 자원 절약을 원하면 compose에서 `ollama` 서비스를 빼고 상용 API만 써도 됩니다.

## 대안 1) 도메인 없이 빠른 테스트
`.env` 에서 `SITE_ADDRESS=:80` → `docker compose up -d --build` → `http://서버IP` 로 접속(HTTP, 임시).

## 대안 2) PaaS (Render / Railway / Fly.io)
1. 이 폴더를 git 저장소로 올리고, PaaS에서 **Dockerfile** 기반 서비스 생성
2. **영속 디스크**를 `/app/data` 에 마운트하고 `INVIZ_DB_PATH=/app/data/app.db` 설정
3. 환경변수 `INVIZ_PASSWORD`, `INVIZ_SECRET`, `INVIZ_PUBLIC=1` 설정 (TLS는 플랫폼이 자동)
4. 일부 PaaS는 포트를 `$PORT`로 주입 → 시작 명령을 `uvicorn main:app --host 0.0.0.0 --port $PORT --proxy-headers --forwarded-allow-ips *` 로 지정

---
문의: 특정 호스팅(예: 네이버클라우드/AWS)·도메인·사내서버에 맞춰 더 자세히 세팅해 드릴 수 있습니다.
