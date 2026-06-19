# 인비즈 경영관리 시스템 — 문서 인덱스

| 문서 | 내용 |
|---|---|
| [DEVELOPMENT_LOG.md](./DEVELOPMENT_LOG.md) | **전체 개발 로그** — 45개 작업, 단계별 의사결정, 회고 |
| [01_architecture.md](./01_architecture.md) | 시스템 아키텍처 — 전체 구조도, 데이터 흐름, 외부 의존성 |
| [02_database.md](./02_database.md) | 17개 SQLite 테이블 — DIM·FACT·마스터·운영 스키마 |
| [03_rag_system.md](./03_rag_system.md) | RAG 파이프라인 — FAISS, bge-m3 임베딩, 자가 학습 |
| [04_self_dev.md](./04_self_dev.md) | 자가발전 시스템 — 무결성·LLM 분류·자동 롤백 |
| [05_claude_integration.md](./05_claude_integration.md) | Claude Code 통합 — Agent·Skill·MCP·하네스 |

## 빠른 시작

신규 인원이 이 시스템을 처음 만질 때:

1. **`../web_app/README.md`** 먼저 — 운영 매뉴얼 (서버 시작·동기화 등록)
2. **`DEVELOPMENT_LOG.md`** — 전체 그림 파악 (왜 이렇게 만들었는지)
3. **`01_architecture.md`** — 시스템 구성도
4. **`02_database.md`** — 데이터 모델

문제 진단·확장 작업 시:
- 데이터 변조 의심 → `04_self_dev.md`
- 챗 응답 정확도 문제 → `03_rag_system.md`
- Claude로 작업 자동화 → `05_claude_integration.md`

## 외부 참조

- 인비즈 경영관리 웹: http://localhost:8000
- API 문서: http://localhost:8000/api/docs
- Ollama: http://localhost:11434
