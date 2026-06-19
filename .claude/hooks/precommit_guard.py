# -*- coding: utf-8 -*-
"""PreToolUse(Bash) 훅 — `git commit` 시 민감 파일이 스테이징되면 차단.

Claude Code 훅 규약: stdin으로 {tool_name, tool_input:{command}} JSON 수신.
- Bash 도구이고 명령에 'git commit'이 있으면 스테이징된 파일명을 검사.
- 민감 파일(아래 패턴)이 하나라도 있으면 stderr에 사유 출력 + exit 2 (커밋 차단).
- 그 외에는 exit 0 (통과). 오류 시에도 통과(fail-open) — 개발 흐름을 막지 않음.

⚠️ 이 스크립트에는 실제 비밀값을 넣지 않는다(파일명 패턴만 검사). 비밀값은 .env/start.bat(gitignore)에만.
"""
import sys
import json
import re
import subprocess

# 절대 커밋되면 안 되는 경로 패턴 (파일명 기준)
SENSITIVE = re.compile(
    r"(\.db$|\.db-|(^|/)\.env$|\.pem$|\.key$|\.crt$|\.pfx$"
    r"|(^|/)certs/|vector_store/|doc_uploads/|db_backup/"
    r"|report_templates/|report_snapshots/"
    r"|\.xlsx$|\.xls$|\.xlsm$|\.csv$"
    r"|_data_patch\.zip$"
    r"|(^|/)start\.bat$|\.vbs$|\.ps1$)",
    re.IGNORECASE,
)


def main():
    try:
        data = json.load(sys.stdin)
    except Exception:
        sys.exit(0)  # 입력 못 읽으면 통과
    if data.get("tool_name") != "Bash":
        sys.exit(0)
    cmd = (data.get("tool_input", {}) or {}).get("command", "") or ""
    if not re.search(r"\bgit\b.*\bcommit\b", cmd):
        sys.exit(0)
    try:
        out = subprocess.run(
            ["git", "diff", "--cached", "--name-only"],
            capture_output=True, text=True, timeout=15,
        )
        staged = [ln.strip() for ln in out.stdout.splitlines() if ln.strip()]
    except Exception:
        sys.exit(0)  # git 조회 실패 시 통과(fail-open)

    bad = [f for f in staged if SENSITIVE.search(f) and not f.endswith(".example")]
    if bad:
        msg = (
            "🚫 [precommit_guard] 민감 파일이 스테이징되어 커밋을 차단했습니다:\n  - "
            + "\n  - ".join(bad[:20])
            + "\n\n조치: `git restore --staged <파일>` 로 제외하고 .gitignore를 확인하세요.\n"
            "  (DB·.env·인증서·벡터·업로드·통합Excel·런처는 데이터 패치로만 전달합니다.)"
        )
        print(msg, file=sys.stderr)
        sys.exit(2)  # 차단
    sys.exit(0)


if __name__ == "__main__":
    main()
