# -*- coding: utf-8 -*-
"""활동 로그 — 모든 작업을 DB(activity_log)에 기록"""
from datetime import datetime

# 경로 prefix → 항목(category) 매핑
_CATEGORY = [
    ("/sales", "매출"), ("/purchases", "매입"), ("/payroll", "급여"),
    ("/contracts", "계약"), ("/loans", "차입금"), ("/parties", "거래처"),
    ("/products", "제품"), ("/employees", "직원"), ("/documents", "서류·인증"),
    ("/reports", "보고서"), ("/company", "회사정보"), ("/ai-classify", "AI 분류"),
    ("/knowledge", "AI 학습"), ("/self-dev", "자가발전"), ("/sync", "동기화"),
    ("/settings", "설정"), ("/chat", "AI 챗"),
    ("/login", "인증"), ("/logout", "인증"),
]

# 로그를 남기지 않을 경로(폴링·정적·스트림 등)
_SKIP_EXACT = {"/chat/status", "/api/health", "/favicon.ico"}
_SKIP_PREFIX = ("/static", "/chat/stream", "/settings/browse", "/settings/logs")


def categorize(path: str) -> str:
    for pre, cat in _CATEGORY:
        if path == pre or path.startswith(pre + "/") or (pre == "/login" and path == "/login"):
            return cat
    if path == "/":
        return "대시보드"
    return "기타"


def should_log(method: str, path: str) -> bool:
    if path in _SKIP_EXACT:
        return False
    for pre in _SKIP_PREFIX:
        if path.startswith(pre):
            return False
    # 모든 변경(비-GET) + 주요 페이지 GET 기록
    return True


def log_activity(method, path, status_code, client_ip, user="", duration_ms=None):
    """비동기 안전 — 별도 세션으로 기록. 실패해도 요청에 영향 없음."""
    try:
        from database import SessionLocal
        from models import ActivityLog
        db = SessionLocal()
        try:
            db.add(ActivityLog(
                ts=datetime.now(),
                category=categorize(path),
                action=f"{method} {path}",
                method=method, path=path[:500],
                status_code=status_code, client_ip=client_ip,
                user=user or None, duration_ms=duration_ms,
            ))
            db.commit()
        finally:
            db.close()
    except Exception as e:
        print(f"[activity] 로그 기록 실패: {e}")


def log_event(category: str, action: str, client_ip: str = "", user: str = ""):
    """코드에서 직접 호출하는 이벤트 로그 (예: 스케줄러 자동 실행)"""
    try:
        from database import SessionLocal
        from models import ActivityLog
        db = SessionLocal()
        try:
            db.add(ActivityLog(ts=datetime.now(), category=category,
                               action=action[:300], client_ip=client_ip or None,
                               user=user or None))
            db.commit()
        finally:
            db.close()
    except Exception as e:
        print(f"[activity] 이벤트 로그 실패: {e}")
