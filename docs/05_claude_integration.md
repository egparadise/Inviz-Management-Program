# 05. Claude Code 통합

본 시스템을 Claude Code SDK의 표준 프리미티브(Agent / Skill / MCP / 하네스)로 패키징한 결과.

## 구성 요소

```
.claude/
├── CLAUDE.md              ← 프로젝트 컨텍스트 (회사·기술·데이터 전체)
├── settings.json          ← 권한·env·hooks (하네스)
├── agents/                ← 5 서브에이전트
│   ├── inviz-data-analyst.md
│   ├── inviz-rag-builder.md
│   ├── inviz-sync-doctor.md
│   ├── inviz-document-classifier.md
│   └── inviz-handler-generator.md
├── skills/                ← 4 스킬
│   ├── inviz-business-query/SKILL.md
│   ├── inviz-create-handler/SKILL.md
│   ├── inviz-add-domain/SKILL.md
│   └── inviz-self-dev-review/SKILL.md
├── commands/              ← 5 슬래시 명령
│   ├── kpi.md             (/kpi [year])
│   ├── safe-sync.md       (/safe-sync [--no-rollback])
│   ├── reindex.md         (/reindex [pending|full|clean])
│   ├── new-handler.md     (/new-handler <file>)
│   └── ask.md             (/ask <question>)
└── mcp/
    └── inviz_mcp_server.py  ← MCP 서버 (10 도구)

.mcp.json                  ← MCP 등록
```

## 1. Context (CLAUDE.md)

세션 시작 시 자동 로드되는 프로젝트 컨텍스트.
- 회사 도메인 요약 (인비즈, 의료 IT, 5개 제품)
- 시스템 위치·기술 스택
- 17개 테이블 + 행수
- 핵심 시스템 흐름
- 명명 규약·무결성 원칙
- 작업 시 주의사항 (한글 인코딩 등)

## 2. Agents (5종)

### inviz-data-analyst
비즈니스 데이터 분석 — KPI, 추세, 이상치, 수익성. SQL 직접 작성.

### inviz-rag-builder
RAG 청크·임베딩·벡터 인덱스 관리. 새 도메인 추가, 검색 정확도 개선.

### inviz-sync-doctor
동기화 시스템 진단·복구. sync_run/integrity_check 분석, 롤백 실행.

### inviz-document-classifier
새 파일을 LLM이 분류. UnmappedFileReview 큐 처리.

### inviz-handler-generator
새 도메인의 ETL 핸들러 코드 자동 생성. sync_handlers.py 패턴 학습.

## 3. Skills (4종)

### inviz-business-query
자연어 비즈니스 질문 답변의 표준 절차 (fast match → RAG → LLM).

### inviz-create-handler
새 데이터 소스를 시스템에 통합하는 5단계.

### inviz-add-domain
완전히 새로운 비즈니스 도메인 추가의 7단계 통합.

### inviz-self-dev-review
자가발전 결과 검토·평가·후속 조치.

## 4. MCP 서버 (10 도구)

`.claude/mcp/inviz_mcp_server.py` — FastMCP 기반.

| 도구 | 기능 |
|---|---|
| `query_sales` | 매출 조회 (year/month/party/기간 필터) |
| `query_purchases` | 매입 조회 |
| `kpi_overview` | 연간 KPI 종합 |
| `search_party` | 거래처 검색 + 매출/매입 누계 |
| `list_contracts` | 계약 (status, expiring_within_days) |
| `list_documents` | 인증서·서류 검색 |
| `loan_status` | 차입금 잔액 |
| `rag_search` | 벡터 DB 의미 검색 (LLM 없이) |
| `integrity_status` | 무결성 검증 결과 |
| `sync_status` | 동기화 이력 + 미매핑 큐 |

### MCP 사용법

stdio (Claude Desktop / Claude Code):
```bash
python .claude/mcp/inviz_mcp_server.py
```

`.mcp.json`에 등록되어 있어 Claude Code가 자동 인식.

## 5. Slash Commands (5종)

| 명령 | 설명 |
|---|---|
| `/kpi [year]` | KPI 종합 조회 |
| `/safe-sync` | 안전 동기화 실행 |
| `/reindex [mode]` | RAG 벡터 재인덱싱 |
| `/new-handler <file>` | 새 핸들러 작성 |
| `/ask <question>` | 자연어 질문 |

## 6. 하네스 (settings.json)

### permissions
- **allow**: web_app 편집, SQLite 조회, Ollama 호출, sync 배치 등 자주 쓰는 작업
- **deny**: DB 파일 직접 편집, force push, 백업 삭제
- **ask**: delete, drop table 같은 위험 명령은 사람 확인

### env
- `INVIZ_PASSWORD`, `INVIZ_SECRET` — 시스템 인증
- `PYTHONIOENCODING=utf-8` — Windows 한글 출력

### hooks
- **PreToolUse Edit|Write**: DB 백업 필요 알림
- **PostToolUse Edit**: 서버 재시작 필요 알림

## 사용 시나리오

### 시나리오 A: 사용자가 새 데이터 분석 요청
1. 사용자: "최근 6개월 매출 추세 분석"
2. Claude: `inviz-data-analyst` 에이전트 위임 또는 직접 처리
3. MCP 도구 `query_sales(from_date=..., to_date=...)` 호출
4. SQL 추가 집계 → 분석 결과 보고

### 시나리오 B: 새 도메인 추가
1. 사용자: "법인카드 사용내역 자동화"
2. Claude: `/new-handler` 또는 `inviz-add-domain` 스킬 따라 진행
3. `inviz-handler-generator` 에이전트로 핸들러 코드 작성
4. 테스트 → 등록 → 다음 sync에서 자동 처리

### 시나리오 C: 동기화 문제 진단
1. 알림: sync 실패 / critical 변동
2. Claude: `inviz-sync-doctor` 에이전트 위임
3. `inviz-self-dev-review` 스킬로 결과 분석
4. 권장 조치 → 사용자 확인 후 실행

## 다른 LLM에서 사용

MCP 서버는 표준 프로토콜 — Claude 외 호환 도구에서도 사용 가능:
- Claude Desktop
- Cline / Roo Code
- Continue.dev
- 직접 Python 클라이언트

## 확장 방법

### 새 에이전트 추가
`.claude/agents/new-agent.md` 작성:
```markdown
---
name: new-agent
description: 무엇을 하는 에이전트인지
tools: [Bash, Read, Edit]
---

에이전트 행동 지침...
```

### 새 스킬 추가
`.claude/skills/new-skill/SKILL.md`:
```markdown
---
name: new-skill
description: 언제 사용하는지
---

작업 절차...
```

### 새 슬래시 명령
`.claude/commands/new-cmd.md`:
```markdown
---
description: 명령 설명
---

실행 지침...
사용자 인자: $1, $ARGUMENTS
```

### MCP 도구 추가
`.claude/mcp/inviz_mcp_server.py`에 `@mcp.tool()` 데코레이터로 함수 추가.

## 운영 권장

1. **세션 시작 시**: CLAUDE.md 자동 로드 — 별도 컨텍스트 설명 불필요
2. **자주 쓰는 명령**: 슬래시 명령으로 단축 (`/kpi`, `/ask`)
3. **복잡한 작업**: 에이전트 위임 (분석, 진단, 코드 생성)
4. **외부 도구**: MCP 서버로 다른 환경에서도 인비즈 데이터 접근

## 참고

- `DEVELOPMENT_LOG.md` — 전체 개발 과정 (45개 작업)
- `01_architecture.md` — 시스템 아키텍처
- `02_database.md` — 17개 테이블 스키마
- `03_rag_system.md` — RAG 파이프라인
- `04_self_dev.md` — 자가발전 시스템
- `web_app/README.md` — 운영 매뉴얼
