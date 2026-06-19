# 인비즈 경영관리 시스템 — 프로젝트 컨텍스트

이 디렉토리는 한국 의료 IT 회사 **(주)인비즈**의 경영관리 통합 시스템입니다.
Claude 세션이 이 프로젝트에 들어오면 우선 본 문서로 컨텍스트를 잡으세요.

## 회사·도메인 요약

- **회사**: ㈜인비즈 (Inviz Corporation), 한국 의료 영상 IT
- **주요 제품**: Cloud Care Life (원격판독), Saintview PACS, Vision Maker, Ai Echo Care, AI CXR/MMG
- **거래처**: 병원·의원 약 786개 + 대리점·공급사 약 200개
- **연 매출 규모**: 약 24억 원 (2024년 기준)
- **데이터 보관**: OneDrive `14.경영정보/` 폴더에 Excel/PDF/HWP 산재

## 시스템 위치

| 경로 | 역할 |
|---|---|
| `14.경영정보/` | 회사 원본 자료 폴더 (Excel·PDF 등) |
| `00.경영관리마스터/` | **본 프로젝트 루트** |
| `00.경영관리마스터/인비즈_경영관리마스터_v1.xlsx` | 통합 Excel 마스터 워크북 (24시트) |
| `00.경영관리마스터/web_app/` | FastAPI 웹 시스템 (메인) |
| `00.경영관리마스터/web_app/app.db` | SQLite DB (전체 데이터) |
| `00.경영관리마스터/web_app/db_backup/` | 일일 + 안전 동기화 백업 |
| `%LOCALAPPDATA%\Inviz\vector_store\` | FAISS 벡터 인덱스 (ASCII 경로) |
| `00.경영관리마스터/.claude/` | Claude Code 통합 (본 디렉토리) |
| `00.경영관리마스터/docs/` | 개발 문서·로그 |

## 기술 스택

- **백엔드**: Python 3.14 + FastAPI 0.136 + SQLAlchemy 2.0 + SQLite
- **프론트엔드**: Jinja2 + HTMX + Tailwind CSS (CDN) + Chart.js
- **AI**: Ollama (로컬) — llama3.1 / llama3.2 / GLM 4.7 / nomic-embed / bge-m3
- **RAG**: LangChain + FAISS + bge-m3 (1024차원, 다국어)
- **인증**: itsdangerous 세션 쿠키 (공동 비밀번호)
- **OS**: Windows 11 (사내 PC)

## 데이터 모델 (SQLite)

### DIM (기준)
- `dim_party` (984) · `dim_product` (10) · `dim_employee` (56) · `dim_account` (21) · `dim_department` (5)

### FACT (트랜잭션)
- `fact_sale` (5,409) · `fact_purchase` (2,221) · `fact_payroll` (616)
- `fact_expense` (311) · `fact_receivable` (133) · `fact_loan` (128)
- `fact_rental` (49) · `fact_severance` (550) · `fact_reading` (보강 필요)

### 마스터
- `master_contract` (299) · `master_loan` (25) · `master_product_mapping` (13)
- `document` (85, 인증서·특허·공증)

### 운영·AI·자가발전
- `file_registry` (505) — 추적 파일 메타
- `sync_run` / `sync_run_detail` — 동기화 이력
- `chat_history` — AI Q&A 이력 + 피드백
- `knowledge_chunk` (1,321) — RAG 청크 메타
- `integrity_check` — 무결성 검증
- `unmapped_file_review` — LLM 분류 검토 큐

## 핵심 시스템

### 1. 데이터 흐름
```
14.경영정보/ (Excel·PDF 산재)
    ↓ sync_core.py (변경 감지)
    ↓ sync_handlers.py (도메인별 ETL)
SQLite app.db
    ↓ rag_ingest.py (청크화)
    ↓ rag.py (임베딩)
FAISS vector_store
    ↓ chat_engine.py (RAG retrieve)
LLM (Ollama) → 사용자
```

### 2. 자가발전 시스템 (self_dev.py)
1. DB 백업 (스냅샷)
2. 사전 KPI 측정 (11개 지표)
3. sync_core 실행
4. 사후 KPI 측정 + 변동 검증
5. critical 변동 시 자동 롤백
6. 미매핑 파일 → LLM 도메인 분류
7. 벡터 DB 자가 갱신

### 3. AI Chat 모드 (chat_engine.py)
- **fast match** (1초 미만): 키워드 매칭으로 즉시 응답
- **자동**: fast 매칭 실패 시 LLM 의도 분류
- **🔍 RAG**: 벡터 DB 검색 + LLM 컨텍스트 증강 (스트리밍)
- **🧪 검색만**: LLM 없이 FAISS 검색만 (500ms)

## 명명 규약

- 거래처: `C0001`~`C9999`
- 제품: `P001`~`P999`
- 직원: 사번 그대로 (`IV_*` 또는 `E0001`~)
- 계약: `K-{시트}-{행번호}` 또는 `K-W-{auto}` (웹 입력)
- 차입금: `LM-{auto}`
- 매출 ID: `S-{출처}-{seq}`, 매입 ID: `P-{출처}-{seq}`

## 데이터 무결성 원칙

- **웹 입력 데이터 보존**: `source_file = 'web_app'` 데이터는 동기화에서 절대 삭제 안 됨
- **위험 변동 차단**:
  - 행수 ±50% 초과 → critical → 자동 롤백
  - 합계 ±70% 초과 → critical
  - ±20~30% → warning (검토)
- **DB 백업**: 매 sync 전 자동 스냅샷, 30일 보관

## 작업 시 주의사항

1. **OneDrive 한글 경로**: `14.경영정보/00.경영관리마스터` — Python OK, FAISS C++ 라이브러리는 ASCII 경로만 (`%LOCALAPPDATA%\Inviz\vector_store` 사용)
2. **Windows 콘솔 cp949**: print 출력 시 한글 깨질 수 있음 — `set PYTHONIOENCODING=utf-8`
3. **Bash + curl + 한글**: form-data 인코딩 깨짐 — Python urllib로 테스트 권장
4. **FAISS persistence**: `save_local` 호출 필수, save 안 하면 메모리만
5. **JS 글로벌 충돌**: `base.html`의 변수는 `invizFmt` 같이 접두사. dashboard.html의 `const fmt`와 충돌 주의

## 실행 명령

```cmd
web_app\install.bat                      :: 최초 1회 — pip install + DB 생성
web_app\start.bat                        :: 서버 시작 (포트 8000)
web_app\register_safe_sync_task.bat      :: 매일 04:00 안전 동기화 등록
web_app\safe_sync.bat                    :: 수동 안전 동기화
web_app\sync.bat                         :: 일반 동기화 (자가발전 비포함)
```

## 웹 페이지 맵

| URL | 페이지 |
|---|---|
| `/` | 대시보드 (연간 KPI, 매출 추이, 제품별, 거래처 TOP) |
| `/sales` `/purchases` | 매출·매입 (기간 필터, CSV, Excel/PDF Export) |
| `/contracts` | 계약 (만료 임박 강조) |
| `/payroll` | 급여 (월별 집계) |
| `/loans` | 차입금 마스터 + 임원 거래 |
| `/parties` `/products` `/employees` | DIM 마스터 |
| `/documents` | 인증서·특허·공증 (만료일 추적) |
| `/sync` | 일반 동기화 현황 |
| `/knowledge` | AI 지식베이스 (RAG 청크 통계) |
| `/self-dev` | **자가발전 대시보드 (무결성·LLM 분류)** |
| `/chat/stream` | SSE 스트리밍 챗 (RAG + LLM) |

## 재사용 자산 — 개발 방법론 (이름으로 호출)

이 프로젝트를 만든 방법론을 `.claude/`에 자산으로 저장했다. 인덱스: `.claude/METHODOLOGY.md`.
새 작업 시 아래 **이름**으로 불러 쓴다 (스킬은 `/이름`, 에이전트는 위임, 훅·MCP는 자동).

| 종류 | 이름 | 용도 |
|---|---|---|
| 🎨 Skill | **`inviz-design`** | 화면 디자인(브랜드 색·컴포넌트·레이아웃·연도그룹·라이브계산) |
| 🧩 Skill | **`inviz-feature`** | 새 기능 레시피(모델→마이그레이션→라우터→템플릿→메뉴→설정→스케줄러→검증) |
| 🔄 Skill | **`inviz-dev-process`** | 개발 루프·서버 재시작·HTTP 스모크·DB 검증·비밀안전 커밋 |
| 🛠 Skill | **`inviz-troubleshoot`** | 문제해결 플레이북(라우트422·인코딩·마이그레이션·설정캐시·연동) |
| 🤖 Agent | **`inviz-feature-builder`** | 기능 end-to-end 구현 + HTTP 검증 |
| 🤖 Agent | **`inviz-ui-designer`** | 브랜드 일관 페이지/템플릿 작성 |
| 🤖 Agent | **`inviz-debugger`** | 런타임/라우트/데이터 문제 진단·수정 |
| 🪝 Hook | **`precommit_guard`** | `git commit` 시 민감파일 자동 차단 (`.claude/hooks/`) |
| 🪝 Hook | **`postedit_hint`** | 편집 파일별 맥락 힌트 |
| 🔌 MCP | **`dev_playbook(section)`** | 방법론 조회 도구 + 리소스 `inviz://playbook` |
| ⚙ Harness | **`.claude/settings.json`** | 권한·env·훅 연결 |

(운영용 기존 자산: 스킬 `inviz-add-domain`·`inviz-business-query`·`inviz-create-handler`·`inviz-self-dev-review`,
에이전트 `inviz-data-analyst`·`inviz-document-classifier`·`inviz-handler-generator`·`inviz-rag-builder`·`inviz-sync-doctor`,
명령 `/ask`·`/kpi`·`/new-handler`·`/reindex`·`/safe-sync`)

## 다음 작업 시 참고할 문서

- `docs/DEVELOPMENT_LOG.md` — 전체 개발 과정 (40+ 작업)
- `docs/01_architecture.md` — 아키텍처 다이어그램
- `docs/02_database.md` — 17개 테이블 스키마 상세
- `docs/03_rag_system.md` — RAG 파이프라인 + 임베딩
- `docs/04_self_dev.md` — 무결성 + 자가학습 시스템
- `docs/05_claude_integration.md` — 본 .claude/ 구조 설명
- `web_app/README.md` — 운영 매뉴얼
