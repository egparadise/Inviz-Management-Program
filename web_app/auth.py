# -*- coding: utf-8 -*-
"""공동 비밀번호 인증 — 세션 쿠키 기반"""
import os
import secrets
from fastapi import Request, Response, HTTPException, Depends
from fastapi.responses import RedirectResponse
from itsdangerous import URLSafeTimedSerializer, BadSignature, SignatureExpired

# 환경변수가 없으면 기본값 (실제 비밀번호는 .env/start.bat의 INVIZ_PASSWORD로 주입 — 커밋 금지)
SHARED_PASSWORD = os.environ.get("INVIZ_PASSWORD", "changeme")
SECRET_KEY = os.environ.get("INVIZ_SECRET", "change-me-in-production-aB3xZ9pQrM2vN8kL")
SESSION_COOKIE = "inviz_session"
SESSION_MAX_AGE = 60 * 60 * 12  # 12시간

serializer = URLSafeTimedSerializer(SECRET_KEY, salt="inviz-session")


def create_session_token(user_id: str = "shared") -> str:
    return serializer.dumps({"user": user_id, "ts": secrets.token_hex(8)})


def verify_session_token(token: str) -> dict | None:
    try:
        data = serializer.loads(token, max_age=SESSION_MAX_AGE)
        return data
    except (BadSignature, SignatureExpired):
        return None


def require_auth(request: Request):
    """라우트 디펜던시 — 인증 안 됐으면 /login으로 리다이렉트"""
    token = request.cookies.get(SESSION_COOKIE)
    if not token:
        raise HTTPException(status_code=302, headers={"Location": "/login"})
    session = verify_session_token(token)
    if not session:
        raise HTTPException(status_code=302, headers={"Location": "/login"})
    return session


def login(response: Response, password: str) -> bool:
    # 우선순위: 설정에 저장된 공통 비밀번호 → 환경변수 비밀번호 → 추가 사용자
    ok = False
    try:
        import settings_store as ss
        res = ss.check_password(password)
        if res is True:
            ok = True
        elif res is None:
            ok = (password == SHARED_PASSWORD)
        if not ok and ss.check_user_password(password):
            ok = True
    except Exception:
        ok = (password == SHARED_PASSWORD)
    if not ok:
        return False
    token = create_session_token()
    response.set_cookie(
        SESSION_COOKIE, token,
        max_age=SESSION_MAX_AGE,
        httponly=True,
        samesite="lax",
    )
    return True


def logout(response: Response):
    response.delete_cookie(SESSION_COOKIE)
