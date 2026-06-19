---
description: 새 도메인의 sync 핸들러 생성 (LLM 미매핑 파일 처리)
---

새 종류의 회사 파일이 들어왔을 때 sync 핸들러를 작성합니다.

대상 파일 또는 도메인: $ARGUMENTS

`inviz-handler-generator` 에이전트를 사용해 다음 절차로 진행:

1. **파일 구조 분석** — 시트·헤더·날짜·키 컬럼 식별
2. **모델 결정** — 기존 모델 재사용 또는 신규
3. **DOMAIN_MATCHERS 추가** — `sync_core.py`에 파일명 정규식
4. **handler 함수 작성** — `sync_handlers.py`
5. **HANDLERS 등록** + 테스트
6. **file_registry 갱신** — 해당 파일 status='changed'

상세 가이드: `.claude/skills/inviz-create-handler/SKILL.md`

핸들러 작성 후 즉시 테스트:
```python
from sync_handlers import handler_<domain>
from database import SessionLocal
from pathlib import Path
db = SessionLocal()
result = handler_<domain>(db, Path("..."))
print(result)
```

전체 sync 통합 검증:
```bash
cd web_app
python sync_core.py --force
```

이후 `/self-dev`에서 무결성 변화 확인.
