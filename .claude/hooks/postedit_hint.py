# -*- coding: utf-8 -*-
"""PostToolUse(Edit|Write) 훅 — 편집한 파일에 따라 맥락 힌트를 출력.

stdin: {tool_name, tool_input:{file_path}} JSON. 힌트는 stdout으로(차단 안 함, exit 0).
"""
import sys
import json


def main():
    try:
        data = json.load(sys.stdin)
    except Exception:
        sys.exit(0)
    fp = ((data.get("tool_input", {}) or {}).get("file_path", "") or "").replace("\\", "/")
    hints = []
    low = fp.lower()
    if low.endswith("models.py"):
        hints.append("[hint] 모델 변경 — 새 '컬럼'은 ALTER TABLE 일회성 스크립트 필요(create_all은 컬럼 추가 안 함). 새 '테이블'은 재시작 시 자동 생성.")
    if "/routers/" in low:
        hints.append("[hint] 라우터 — 리터럴 경로를 /{id:int} 같은 동적경로보다 먼저 등록(아니면 422 int_parsing). 변경 후 서버 재시작 + HTTP 스모크 검증.")
    if "/templates/" in low or low.endswith("helpers.py"):
        hints.append("[hint] 템플릿/메뉴 변경 — 서버 재시작 후 /경로 200·무오류 확인. NAV active 충돌(부모==자식 경로) 주의.")
    if low.endswith("settings.py") or "/settings/" in low:
        hints.append("[hint] 설정 변경 — settings_store 캐시는 서버 재시작해야 반영(별도 프로세스 변경 시).")
    if hints:
        print("\n".join(hints))
    sys.exit(0)


if __name__ == "__main__":
    main()
