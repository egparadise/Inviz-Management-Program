# 인비즈 제품 개발 방법론 — 재사용 자산 인덱스

이 문서는 인비즈 경영관리 시스템을 만든 **개발 방법론**을 앞으로도 불러 쓸 수 있도록
`.claude/`에 저장한 **Skill · Agent · Hook · Harness · MCP** 자산의 인덱스입니다.

요청하신 4개 영역을 자산으로 캡처했습니다:

| 영역 | Skill | Agent | 불러쓰기 |
|---|---|---|---|
| 🎨 디자인 | `inviz-design` | `inviz-ui-designer` | `/inviz-design` 또는 "인비즈 화면 디자인" |
| 🧩 기능 | `inviz-feature` | `inviz-feature-builder` | `/inviz-feature` 또는 "새 기능 추가" |
| 🔄 개발 전체 과정 | `inviz-dev-process` | — | `/inviz-dev-process` |
| 🛠 문제 해결 | `inviz-troubleshoot` | `inviz-debugger` | `/inviz-troubleshoot` 또는 "이 문제 디버그" |

---

## 1) Skills — `.claude/skills/<name>/SKILL.md`
재사용 가능한 절차 문서. Claude Code가 자동 인식하며, `/inviz-design`처럼 호출하거나
자연어로 관련 작업을 요청하면 로드됩니다.

- **inviz-design** — 브랜드 색(#6B2C91/#F47521)·공용 컴포넌트·페이지 레이아웃·네비게이션·연도 접이식 그룹·라이브 JS 계산 패턴.
- **inviz-feature** — 새 기능 end-to-end 레시피: 모델→마이그레이션(ALTER TABLE)→라우터(라우트 순서)→템플릿→메뉴→설정→스케줄러→테스트→정리.
- **inviz-dev-process** — 개발 루프 + 서버 재시작 패턴 + HTTP 스모크 테스트 하니스 + DB 수치검증 + 비밀안전 커밋.
- **inviz-troubleshoot** — 실전 함정 플레이북(라우트 422·인코딩·마이그레이션·설정캐시·메일/은행 연동·비밀안전).

(기존 운영 스킬: `inviz-add-domain`, `inviz-business-query`, `inviz-create-handler`, `inviz-self-dev-review`)

## 2) Agents — `.claude/agents/<name>.md`
특정 역할의 서브에이전트. 복잡한 작업 위임 시 Claude가 호출하거나, "inviz-feature-builder로 ~를 만들어" 처럼 지정.

- **inviz-feature-builder** — 기능을 레시피대로 풀스택 구현 + HTTP 검증.
- **inviz-ui-designer** — 브랜드 일관 페이지/템플릿 작성(파일 도구만).
- **inviz-debugger** — 런타임/라우트/데이터 문제 진단·수정(플레이북 기반).

(기존 운영 에이전트: `inviz-data-analyst`, `inviz-document-classifier`, `inviz-handler-generator`, `inviz-rag-builder`, `inviz-sync-doctor`)

## 3) Hooks (Harness) — `.claude/settings.json` + `.claude/hooks/`
- **precommit_guard.py** (PreToolUse·Bash) — `git commit` 시 민감 파일(`*.db`, `.env`, `certs/`, `vector_store/`, 업로드, `*.xlsx`, 런처…)이 스테이징되면 **커밋 차단**(exit 2).
- **postedit_hint.py** (PostToolUse·Edit/Write) — 편집 파일별 맥락 힌트(models.py→마이그레이션, routers→라우트순서·재시작, settings→캐시 등).
- 기존: 편집 전 백업 권장 echo. permissions(allow/deny/ask)·env(PYTHONIOENCODING 등)도 settings.json.

## 4) MCP — `.claude/mcp/inviz_mcp_server.py` (`.mcp.json`으로 등록)
- 도구 **`dev_playbook(section)`** — `design/feature/process/troubleshoot` 섹션의 스킬 전문을 반환(외부 LLM/도구도 방법론 조회 가능).
- 리소스 **`inviz://playbook`** — 본 인덱스. **`inviz://overview`** — 회사/시스템 개요.
- (기존 데이터 도구: query_sales, kpi_overview, rag_search, list_contracts/documents, loan_status …)

## 5) Commands — `.claude/commands/<name>.md`
`/ask`, `/kpi`, `/new-handler`, `/reindex`, `/safe-sync` (운영용 슬래시 명령).

---

## 앞으로 사용하는 법
1. **새 화면/기능**: "인비즈에 ○○ 기능 추가" → `inviz-feature`/`inviz-design` 스킬 자동 적용, 필요 시 `inviz-feature-builder` 위임.
2. **문제 발생**: "○○가 안 돼" → `inviz-troubleshoot` 플레이북 + `inviz-debugger`.
3. **방법론 직접 조회**: 슬래시 `/inviz-dev-process` 또는 MCP `dev_playbook(section="feature")`.
4. 이 자산들은 git에 포함되어 **다른 PC/세션에서도** clone 후 그대로 재사용됩니다.

> 저장 위치: `00.경영관리마스터/.claude/` (git 추적). 새 패턴이 생기면 해당 스킬을 갱신하세요.
