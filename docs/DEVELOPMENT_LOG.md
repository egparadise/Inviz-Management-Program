# 인비즈 경영관리 시스템 — 전체 개발 로그

> 본 문서는 ㈜인비즈 경영관리 통합 시스템의 처음부터 끝까지 개발 과정을 단계별로 정리한 기록입니다.
> 향후 유지보수·확장 시 의사결정 배경을 이해하는 데 사용하세요.

## 프로젝트 개요

| 항목 | 값 |
|---|---|
| 회사 | ㈜인비즈 (Inviz Corporation) — 한국 의료 영상 IT |
| 시작 시점 | 2026-05-27 |
| 환경 | Windows 11 / Python 3.14 / Ollama (로컬 LLM) |
| 원본 데이터 | OneDrive `14.경영정보/` (Excel·PDF·HWP 산재) |
| 사용자 | 경영지원팀 2~5명 + 대표이사 |
| 최종 산출물 | 통합 Excel 마스터 + FastAPI 웹앱 + AI Chat + 자가발전 시스템 |

## 개발 단계 요약 (45개 작업)

### Phase P (1~8): Excel 마스터 워크북 구축
원본 데이터가 산재한 상황에서 통합 Excel 마스터를 만든 단계.

| # | 작업 | 산출물 |
|---|---|---|
| P1 | 마스터 워크북 프레임워크 (24시트) | `인비즈_경영관리마스터_v1.xlsx` |
| P2 | 거래처 마스터 추출 | 984개 거래처 |
| P3 | 직원 마스터 추출 | 56명 |
| P4 | FACT_매출 적재 (2021~2026) | 3,458건 → 추후 5,409건 |
| P5 | FACT_매입 적재 | 1,080건 → 추후 2,221건 |
| P6 | 급여·비용·미수금·차입금·퇴직금 | 1,738건 |
| P7 | 판독수수료·임대료·계약·차입금마스터 | 324건 |
| P8 | 대시보드 + 차트 + 검증 시트 | KPI + 26 페이지 |

**핵심 결정**:
- Excel을 마스터로 둔 이유: 사용자가 Excel에 익숙, 비편집 가능
- 24시트 구조: README + Dashboard + DIM (5) + FACT (9) + 마스터 (3) + 집계 (5) + 검증 (1)
- 컬러 코드: 보라(DIM) / 노랑(FACT) / 초록(집계) / 주황(대시보드)

### Phase S (9~14): SQLite + FastAPI 웹앱
Excel만으로는 다중 사용자·CRUD·자동화가 어려워 웹앱으로 전환.

| # | 작업 | 핵심 |
|---|---|---|
| S1 | 프로젝트 구조 + 의존성 | `web_app/` + requirements.txt |
| S2 | DB 스키마 (16개 테이블) | SQLAlchemy 2.0 ORM |
| S3 | Excel → SQLite 마이그레이션 | 7,678행 이관 |
| S4 | FastAPI 백엔드 (8 라우터) | 56개 라우트 + 공동비밀번호 인증 |
| S5 | HTMX 프론트엔드 (CRUD UI) | 14개 HTML + Tailwind + Chart.js |
| S6 | 시작 스크립트 + 백업 + README | `start.bat`, `backup.bat` |

**핵심 결정**:
- **SQLite 선택**: 5명 동시 사용에 충분, 단일 파일 백업/이동 쉬움
- **FastAPI**: 모던, 자동 OpenAPI 문서, 의존성 주입
- **HTMX**: 무거운 React 없이도 인터랙티브 UI
- **공동 비밀번호**: 사내 5명이 동일 자격으로 사용 (역할 분리 불필요)
- **인비즈 보라(#6B2C91) + 주황(#F47521)** 브랜드 컬러 적용

### Phase SY (15~20): 자동 동기화 시스템
원본 폴더의 새 파일·변경을 자동 감지·반영.

| # | 작업 | 핵심 |
|---|---|---|
| SY1 | 동기화 인프라 모델 | FileRegistry, SyncRun, SyncRunDetail |
| SY2 | 변경 감지 엔진 | 폴더 walk + mtime + SHA256 |
| SY3 | 도메인별 핸들러 (13종) | sync_handlers.py |
| SY4 | Windows 작업 스케줄러 | `register_sync_task.bat` → 매일 04:00 |
| SY5 | 웹 UI (동기화 페이지) | `/sync` 현황·이력·수동 실행 |
| SY6 | 통합 테스트 + 문서화 | 505개 파일 자동 추적 |

**핵심 결정**:
- **2단계 감지**: mtime+size 1차, SHA256 2차 (정확 + 빠름)
- **도메인 최신 1건만 처리**: 같은 도메인 여러 파일 시 mtime 최신 1개만
- **트랜잭션 + 백업**: 매 sync 전 자동 DB 백업
- **수동 입력 데이터 보존**: `source_file='web_app'` 행은 절대 삭제 안 됨

### Phase F (21~24): 기간 필터·Excel/PDF Export·CSV Import·브랜드
사용자 요청 — 매출/매입에 기간 설정, 합계, 다양한 출력 형식.

| # | 작업 | 핵심 |
|---|---|---|
| F1 | 매출/매입 기간 필터 + 합계 카드 | from_date/to_date + KPI 4개 + TOP10 |
| F2 | Excel · PDF Export | openpyxl + reportlab (맑은 고딕) |
| F3 | CSV 업로드 (일괄 등록) | 미리보기 → 검증 → 확정 |
| F4 | 인비즈 브랜드 디자인 | SVG 로고 + 보라/주황 컬러 토큰 |

**핵심 결정**:
- **PDF 한글 폰트**: Windows 시스템 폰트 `malgun.ttf` 직접 등록
- **CSV 인코딩**: UTF-8/CP949 자동 감지 (BOM 처리)
- **빠른 기간 버튼**: "이번 달", "이번 분기", "올해 누계" 등 4종

### Phase G (25~27): 서류 관리·로고·AI Chat
사용자 요청 — 인증서/특허/공증 관리 + Ollama LLM 챗.

| # | 작업 | 핵심 |
|---|---|---|
| G1 | 로고 수정 (SVG 정확화 + PNG 폴백) | 보라+주황 럭비공 |
| G2 | 서류·인증서 관리 (`/documents`) | 자동 폴더 스캔 85건 자동 등록 |
| G3 | 상단 AI Chat (Ollama 연동) | llama3.1 / 3.2 / GLM 4.7 |

**핵심 결정**:
- **Ollama 사용**: 외부 API 키 없이 로컬 LLM (4개 모델 발견됨)
- **자동 폴더 스캔**: 21.증명서·29.공증·13.거래처자료 폴더에서 PDF/HWP 자동 인식
- **파일명에서 만료일 자동 추출**: 정규식 패턴 (예: "유효기간 25.03.12")

### Phase H (28): 응답 속도·UX 개선
초기 챗 응답이 30초+ → 사용자 불만 → 대대적 개선.

| # | 작업 | 핵심 |
|---|---|---|
| H1 | 응답 속도·UX 개선 | keep_alive·템플릿 요약·진행 표시·빠른 액션 버튼 |

**개선 결과**:
- 빠른 키워드 매칭 (`fast_intent_match`): 30초 → **5ms** (6000배)
- LLM 의도 분류: 14~16초 (이전 30초의 절반)
- AI 요약 토글: 기본 OFF (LLM 호출 1번만)
- 단계별 진행 표시 + 경과 시간 카운터

### Phase R (29~33): RAG + 자가 학습
사용자 요청 — LLM이 회사 데이터를 잘 분석하도록 RAG + 자가 학습.

| # | 작업 | 핵심 |
|---|---|---|
| R1 | RAG 인프라 (임베딩 + LangChain) | nomic → bge-m3 (다국어, 한국어↑) |
| R2 | KnowledgeChunk + ChatHistory 모델 | 청크 메타 + 토큰 추적 |
| R3 | 데이터 인제스트 (회사 → 벡터 DB) | 1,321 청크 (거래처 786 등) |
| R4 | RAG 엔진 + 챗 통합 | retrieve → 컨텍스트 → LLM |
| R5 | 자가 학습 + 지식 관리 UI | 👍/👎 → 학습된 대화 컬렉션 |

**핵심 결정**:
- **벡터 DB 선택 여정**:
  1. ChromaDB 1.5.x → Windows + Python 3.14에서 HNSW 인덱스 깨짐
  2. ChromaDB 0.5.x → Python 3.14에서 빌드 실패
  3. **FAISS 채택** → 안정, pre-built wheel
- **임베딩 모델**:
  1. nomic-embed-text (768d, 영어 위주) → 한국어 변별력 약함
  2. **bge-m3 (1024d, 다국어)** → 한국어 검색 정확
- **벡터 저장 경로**:
  - FAISS C++ 라이브러리가 한글 경로 불가
  - `%LOCALAPPDATA%\Inviz\vector_store\` ASCII 경로 강제
- **자가 학습**: 👍 받은 Q&A → conversation 컬렉션 자동 인덱싱

### Phase U (34~35): 챗 UI 통합 + 애니메이션
사용자 보고 — 응답이 안 옴, 채팅 버튼 안 됨, 분석 중 표시 부족.

| # | 작업 | 핵심 |
|---|---|---|
| U1 | 스트리밍 응답 + UI 통합 | SSE + ChatGPT 스타일 우측 패널 |
| U2 | 분석 중 애니메이션 + 버그 픽스 | 회전 스피너·점프 점·진행바·단계 체크리스트 |

**디버그 발견**:
- **JS SyntaxError**: `const fmt`가 `base.html`과 `dashboard.html`에 중복 선언 → 전체 스크립트 실행 정지 → 모든 onclick 함수 미정의
- **해결**: `base.html`의 `fmt` → `invizFmt`로 이름 변경 (sed replace_all)
- **Node.js로 syntax 검증**: 4페이지 모두 통과 확인
- **CSS 애니메이션**: 이중 회전 스피너, typing indicator, 진행바 + shimmer

### Phase SD (36~40): 자가발전 시스템
사용자 요청 — 데이터 변조 절대 방지 + AI 자가 학습 + 시스템 자가 개선.

| # | 작업 | 핵심 |
|---|---|---|
| SD1 | 데이터 무결성 (백업·롤백) | DB 스냅샷 + 트랜잭션 |
| SD2 | LLM 자동 분류 (새 파일) | 신뢰도 ≥85% 자동, 미만 검토 큐 |
| SD3 | 변조·이상 변화 감지 | 행수 ±50%, 합계 ±70% → critical 자동 롤백 |
| SD4 | 벡터 DB 자동 갱신 | sync 후 재인덱싱 |
| SD5 | 자가발전 대시보드 (`/self-dev`) | 무결성 점수 + LLM 정확도 |

**핵심 결정**:
- **5중 안전 장치**: 백업 → 사전 KPI → sync → 사후 KPI → 자동 롤백
- **임계값 조정 가능**: `SUSPICION_THRESHOLDS` 딕셔너리
- **LLM 분류**: 파일명 + 시트명 + 헤더 컬럼 → JSON 응답 (도메인, 신뢰도, 근거)
- **자가 발전**: 매일 04:00 자동 실행으로 시스템이 새 데이터 패턴에 적응

### Phase C (41~45): Claude Code 통합
본 작업 — 시스템 전체를 Agent·Skill·MCP·하네스로 재패키징.

| # | 작업 | 핵심 |
|---|---|---|
| C1 | `.claude/CLAUDE.md` | 프로젝트 컨텍스트 (회사·기술·데이터) |
| C2 | MCP 서버 (FastMCP, 10 도구) | 외부 LLM이 인비즈 데이터 접근 |
| C3 | 서브에이전트 5종 | data-analyst, rag-builder, sync-doctor 등 |
| C4 | 스킬 4종 + 슬래시 명령 5종 | 표준 작업 절차 + 단축 명령 |
| C5 | settings.json + DEVELOPMENT_LOG | 권한·env·hooks + 본 문서 |

## 핵심 기술 결정 회고

### 무엇이 잘 됐나
1. **단계적 진화**: Excel → SQLite → 웹앱 → RAG → 자가발전 — 각 단계가 다음 단계의 토대
2. **로컬 우선**: Ollama, FAISS, SQLite 모두 로컬 — 외부 의존성 0
3. **데이터 보존 정책**: web_app 입력은 절대 삭제 안 됨 — 사용자 신뢰 확보
4. **fast match 도입**: 키워드 명확하면 LLM 우회 → 1000배 빠른 응답

### 무엇이 어려웠나
1. **Windows + Python 3.14 호환성**: ChromaDB·FAISS 한글 경로 문제 → 우회 필요
2. **한글 인코딩**: 콘솔 cp949 vs 파일 UTF-8 vs Bash curl mojibake — 여러 곳에서 깨짐
3. **JS 글로벌 충돌**: 동일 변수명 중복 선언 → 전체 스크립트 정지 (Node syntax 검증 후 발견)
4. **RAG 검색 정확도**: nomic-embed로는 한국어 약함 → bge-m3로 교체

### 학습 사항
- **시스템 자가발전을 위해 LLM에게 위임할 수 있는 것**: 새 파일 분류, 도메인 추론, 컨텍스트 요약
- **LLM에게 맡기면 안 되는 것**: 데이터 변조 판단 (정량 임계값 기반), 무결성 검증 (해시·합계)
- **신뢰도 임계값**: LLM 자동 처리는 85% 이상만, 미만은 사람 확정

## 시스템 현황 (개발 완료 시점)

| 지표 | 값 |
|---|---|
| 총 라인 수 (Python) | ~6,500 줄 |
| HTML 템플릿 | 26개 |
| SQLAlchemy 모델 | 17개 |
| FastAPI 라우터 | 56개 |
| 동기화 핸들러 | 13개 |
| MCP 도구 | 10개 |
| 서브에이전트 | 5종 |
| 스킬 | 4종 |
| 슬래시 명령 | 5종 |
| 인덱싱된 RAG 청크 | 1,321 |
| 추적 파일 | 505개 |

## 향후 확장 방향

### 단기 (1~3개월)
- 판독수수료 도메인 핸들러 보강 (현재 0건)
- 비용 도메인 다년도 확장 (현재 2024만)
- 매출/매입 2021/2022 보강
- 거래처 자동 통합 (유사 이름 군집)

### 중기 (3~6개월)
- 다중 사용자 + 권한 분리 (현재 공동 비밀번호)
- 모바일 UI 최적화
- Slack/Email 알림 (만료 임박, 위험 변동)
- 회계법인 데이터와 자동 대사 (홈택스 연동)

### 장기 (6개월+)
- 예측 모델 (매출 forecasting, 미수금 위험)
- 사외 접근 (Cloudflare Tunnel 또는 클라우드 마이그레이션)
- 다른 회사 인스턴스로 확장 (멀티 테넌트)

## 디렉토리 트리

```
14.경영정보/00.경영관리마스터/
├── 인비즈_경영관리마스터_v1.xlsx        (Excel 마스터, 24시트)
├── ETL_scripts/                          (Excel ETL 스크립트 8개)
├── web_app/                              (FastAPI 웹앱)
│   ├── main.py                           (앱 진입)
│   ├── models.py                         (17개 SQLAlchemy 모델)
│   ├── database.py                       (DB 세션)
│   ├── auth.py                           (인증)
│   ├── helpers.py                        (Jinja 필터)
│   ├── export_util.py                    (Excel/PDF Export)
│   ├── sync_core.py                      (동기화 엔진)
│   ├── sync_handlers.py                  (13개 도메인 핸들러)
│   ├── self_dev.py                       (자가발전 시스템)
│   ├── rag.py                            (RAG 인프라 — FAISS)
│   ├── rag_ingest.py                     (벡터 DB 인덱싱)
│   ├── chat_engine.py                    (LLM + 의도 분류 + RAG)
│   ├── migrate.py                        (Excel → SQLite)
│   ├── app.db                            (SQLite DB)
│   ├── routers/                          (10개 라우터)
│   ├── templates/                        (26개 HTML)
│   ├── static/                           (로고·CSS·JS)
│   ├── db_backup/                        (DB 백업)
│   ├── sync_log/                         (동기화 로그)
│   ├── start.bat                         (서버 시작)
│   ├── safe_sync.bat                     (안전 동기화)
│   ├── register_safe_sync_task.bat       (작업 스케줄러 등록)
│   └── README.md                         (운영 매뉴얼)
├── .claude/                              (Claude Code 통합)
│   ├── CLAUDE.md                         (프로젝트 컨텍스트)
│   ├── settings.json                     (권한·env·hooks)
│   ├── agents/                           (5 서브에이전트)
│   ├── skills/                           (4 스킬)
│   ├── commands/                         (5 슬래시 명령)
│   └── mcp/inviz_mcp_server.py           (MCP 서버)
├── .mcp.json                             (MCP 등록)
└── docs/                                 (개발 문서)
    ├── DEVELOPMENT_LOG.md                (본 문서)
    ├── 01_architecture.md
    ├── 02_database.md
    ├── 03_rag_system.md
    ├── 04_self_dev.md
    └── 05_claude_integration.md
```

## 참고 자료

- Claude Code: https://claude.com/claude-code
- Ollama: https://ollama.com
- FAISS: https://github.com/facebookresearch/faiss
- bge-m3: https://huggingface.co/BAAI/bge-m3
- LangChain: https://python.langchain.com
- FastAPI: https://fastapi.tiangolo.com
- SQLAlchemy 2.0: https://docs.sqlalchemy.org
