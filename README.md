# 인비즈 경영관리 시스템

㈜인비즈(의료 영상 IT)의 경영관리 통합 시스템 — 매출·매입·급여·세금·계약·서류·자금(은행/카드)·AI 분석을 한 곳에서 관리하는 FastAPI 웹 애플리케이션.

## 구성
- `web_app/` — FastAPI 웹 시스템 (메인). 실행·배포·운영 문서는 [`web_app/README.md`](web_app/README.md), [`web_app/DEPLOY.md`](web_app/DEPLOY.md).
- `ETL_scripts/` — 초기 데이터 적재 스크립트.
- `docs/` — 개발 문서·로그.
- `.claude/` — Claude Code 통합(컨텍스트/에이전트/스킬).

## 기술 스택
Python 3.12+ · FastAPI · SQLAlchemy · SQLite · Jinja2/HTMX/Tailwind · Ollama(Llama, RAG) · reportlab/openpyxl.

## ⚠️ 보안 — 저장소에 포함되지 않는 것 (데이터 패치로 별도 전달)
민감정보는 **git에 절대 커밋하지 않습니다.** `.gitignore`로 차단되며, 서버에는 **데이터 패치**로 따로 적용합니다.
- `app.db` (전체 데이터 + 설정/API키/메일·카카오·텔레그램 비밀), `.env`, `certs/`, `vector_store/`
- `report_templates/` `report_snapshots/` `doc_uploads/` `db_backup/`, 통합 Excel 마스터(`*.xlsx`)

데이터 패치: `python web_app/make_data_patch.py` → `inviz_data_patch.zip` → 서버에서 `python apply_data_patch.py --docker`.

## 배포 (요약)
```bash
git clone <비공개_저장소_URL> inviz && cd inviz/web_app
python3 apply_data_patch.py --docker      # 데이터 패치 적용(별도 전달)
cp .env.example .env && nano .env          # 비밀번호·세션키·도메인
docker compose up -d --build               # 앱 + Caddy(HTTPS) + Ollama(LLM)
./pull_models.sh                           # LLM 모델 다운로드
```
자세한 절차·보안 체크리스트는 [`web_app/DEPLOY.md`](web_app/DEPLOY.md) 참고.
