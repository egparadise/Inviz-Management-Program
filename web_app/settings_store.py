# -*- coding: utf-8 -*-
"""전역 설정 저장소 — DB(app_setting) key-value + 메모리 캐시.

사용:
  import settings_store as ss
  ss.get("ui_font_scale")          # 단일 값 (기본값 폴백)
  ss.all()                         # 전체 dict
  ss.save({"ui_font_scale": "110"})
  ss.set_password("새비번"); ss.check_password("입력")
  ss.add_user("alice", "pw"); ss.check_user_password("pw")
"""
import json
import hashlib
import binascii
import os

# ---- 기본값 ----
DEFAULTS = {
    # 외관
    "ui_font_scale": "100",        # 90 / 100 / 110 / 125 (%)
    "ui_logo_show": "1",           # 1=표시 / 0=숨김
    "ui_logo_custom": "",          # 업로드한 로고 파일명 (static/img/ 하위)
    "ui_input_size": "normal",     # compact / normal / large
    "app_title": "경영관리 시스템",
    # AI
    "ai_default_model": "llama3.1:latest",
    "ai_default_mode": "auto",     # auto / rag / search
    # AI 공급자 (클라우드 API)
    "ai_provider": "ollama",       # ollama / openai / anthropic / gemini
    "ai_openai_model": "gpt-4o-mini",
    "ai_anthropic_model": "claude-3-5-haiku-latest",
    "ai_gemini_model": "gemini-1.5-flash",
    # API 키 (ai_openai_key / ai_anthropic_key / ai_gemini_key) 는 저장 시 생성
    # 파일 출력
    "export_default": "xlsx",      # xlsx / pdf
    "pdf_orientation": "portrait", # portrait / landscape
    # 검색
    "search_default_period": "none",  # none / this_month / last_month / ytd
    "search_per_page": "100",
    # 기본 데이터 폴더 (시스템 전체 분석·동기화의 루트)
    "base_data_folder": "",
    # 자가발전 / AI 학습 (오직 오픈소스 Ollama 모델만 사용)
    "learning_model": "llama3.1:latest",       # 자기학습 전용 모델 (오픈소스만)
    "learning_folder": "",                      # 학습·확인 대상 폴더 경로 (비우면 기본 경영정보 폴더)
    "learning_include_subfolders": "1",         # 하위폴더 모두 포함
    "selfdev_paths": "",                        # 자가발전용 공유 폴더·파일 경로 (줄바꿈 구분)
    # 자동 실행 스케줄 (동기화 / AI 학습 / 자가발전)
    "sched_sync_enabled": "0",     "sched_sync_freq": "daily",     "sched_sync_time": "04:00",     "sched_sync_dow": "0", "sched_sync_dom": "1",
    "sched_learning_enabled": "0", "sched_learning_freq": "daily", "sched_learning_time": "04:30", "sched_learning_dow": "0", "sched_learning_dom": "1",
    "sched_selfdev_enabled": "0",  "sched_selfdev_freq": "weekly", "sched_selfdev_time": "03:00",  "sched_selfdev_dow": "0", "sched_selfdev_dom": "1",

    # 국세청 홈택스 / 전자세금계산서 (ASP)
    "tax_corp_no": "",          # 우리 사업자등록번호
    "tax_corp_name": "(주)인비즈",
    "tax_ceo": "박성철",
    "tax_issuer_email": "",     # 발행 담당자/회신 이메일
    "tax_asp": "manual",        # manual / popbill / barobill
    "tax_popbill_linkid": "",
    "tax_popbill_secret": "",   # secret (재노출 안 함)
    "tax_barobill_certkey": "", # secret
    "tax_popbill_test": "1",    # 1=테스트, 0=운영

    # 카카오톡 (나에게 보내기)
    "kakao_enabled": "0",
    "kakao_rest_key": "",       # secret (REST API 키)
    "kakao_access_token": "",   # secret
    "kakao_refresh_token": "",  # secret

    # 텔레그램 (봇 알림)
    "telegram_enabled": "0",
    "telegram_bot_token": "",   # secret (BotFather 토큰)
    "telegram_chat_id": "",     # 내 chat_id

    # 이메일 (발송 SMTP / 수신확인 IMAP)
    "mail_smtp_host": "",  "mail_smtp_port": "587", "mail_smtp_user": "", "mail_smtp_pass": "",  # smtp_pass secret
    "mail_smtp_tls": "1",  "mail_from": "",
    "mail_imap_host": "",  "mail_imap_port": "993", "mail_imap_user": "", "mail_imap_pass": "",  # imap_pass secret
    "mail_notify_to": "",       # 알림 받을 이메일 주소
    "mail_imap_days": "7",      # IMAP 최근 N일 검색

    # 네트워크 / 사내 접속
    "net_bind_host": "127.0.0.1",     # uvicorn 바인딩 호스트 (0.0.0.0 = 사내망 공개)
    "net_port": "8000",                # 포트 번호 (80/443은 관리자 권한 필요)
    "net_domain": "",                  # 외부 표시 도메인 (예: www.invizaccount.com — hosts/내부 DNS 등록 후)
    "net_https": "0",                  # 1=HTTPS, 0=HTTP (HTTPS는 인증서 필요)
    "net_cert_path": "",               # SSL cert.pem 경로
    "net_key_path": "",                # SSL key.pem 경로
    "net_intranet_enabled": "0",       # 1=사내망 접속 허용 (자동으로 net_bind_host=0.0.0.0)
}

_cache = None


def _load():
    global _cache
    try:
        from database import SessionLocal
        from models import Setting
        from sqlalchemy import select
        db = SessionLocal()
        try:
            rows = db.execute(select(Setting)).scalars().all()
            d = dict(DEFAULTS)
            for r in rows:
                d[r.key] = r.value
            _cache = d
        finally:
            db.close()
    except Exception as e:
        print(f"[settings] load 실패, 기본값 사용: {e}")
        _cache = dict(DEFAULTS)
    return _cache


def invalidate():
    global _cache
    _cache = None


def all() -> dict:
    if _cache is None:
        _load()
    return dict(_cache)


def get(key, default=None):
    if _cache is None:
        _load()
    if key in _cache and _cache[key] is not None:
        return _cache[key]
    return DEFAULTS.get(key, default)


def get_int(key, default=0):
    try:
        return int(str(get(key, default)).strip())
    except Exception:
        return default


def selfdev_path_list() -> list:
    """자가발전 공유 경로 목록 (줄바꿈/세미콜론 구분)"""
    raw = get("selfdev_paths", "") or ""
    parts = []
    for line in raw.replace(";", "\n").splitlines():
        p = line.strip()
        if p:
            parts.append(p)
    return parts


def default_search_filter():
    """검색 기본 기간 설정 → (year, from_date, to_date). 적용 안 함이면 (None,None,None)"""
    from datetime import date, timedelta
    period = get("search_default_period", "none")
    today = date.today()
    if period == "this_month":
        fd = today.replace(day=1)
        nm = date(today.year + 1, 1, 1) if today.month == 12 else date(today.year, today.month + 1, 1)
        return None, fd, nm - timedelta(days=1)
    if period == "last_month":
        first_this = today.replace(day=1)
        last_prev = first_this - timedelta(days=1)
        return None, last_prev.replace(day=1), last_prev
    if period == "ytd":
        return today.year, None, None
    return None, None, None


def save(updates: dict):
    """여러 설정을 일괄 upsert. None 값은 무시."""
    from database import SessionLocal
    from models import Setting
    db = SessionLocal()
    try:
        for k, v in updates.items():
            if v is None:
                continue
            row = db.get(Setting, k)
            if row:
                row.value = str(v)
            else:
                db.add(Setting(key=k, value=str(v)))
        db.commit()
    finally:
        db.close()
    invalidate()


# ---- 비밀번호 (공통) ----
def _hash(plain: str, salt: bytes) -> str:
    h = hashlib.pbkdf2_hmac("sha256", plain.encode("utf-8"), salt, 100_000)
    return binascii.hexlify(h).decode()


def set_password(plain: str):
    salt = os.urandom(16)
    stored = binascii.hexlify(salt).decode() + ":" + _hash(plain, salt)
    save({"auth_password_hash": stored})


def check_password(plain: str):
    """반환: True/False, 또는 None(미설정 → 환경변수 비번 사용)"""
    stored = get("auth_password_hash")
    if not stored:
        return None
    try:
        salt_hex, h_hex = stored.split(":")
        salt = binascii.unhexlify(salt_hex)
        return _hash(plain, salt) == h_hex
    except Exception:
        return None


# ---- 추가 사용자 (ID/PW) ----
def get_users() -> list:
    raw = get("auth_users")
    if not raw:
        return []
    try:
        return json.loads(raw)
    except Exception:
        return []


def add_user(username: str, plain: str):
    username = (username or "").strip()
    if not username or not plain:
        return False
    users = get_users()
    salt = os.urandom(16)
    stored = binascii.hexlify(salt).decode() + ":" + _hash(plain, salt)
    # 동일 username 있으면 교체
    users = [u for u in users if u.get("username") != username]
    users.append({"username": username, "hash": stored})
    save({"auth_users": json.dumps(users, ensure_ascii=False)})
    return True


def remove_user(username: str):
    users = [u for u in get_users() if u.get("username") != username]
    save({"auth_users": json.dumps(users, ensure_ascii=False)})


def check_user_password(plain: str) -> bool:
    """등록된 추가 사용자 중 비밀번호 일치하는 사용자가 있으면 True"""
    for u in get_users():
        stored = u.get("hash", "")
        try:
            salt_hex, h_hex = stored.split(":")
            salt = binascii.unhexlify(salt_hex)
            if _hash(plain, salt) == h_hex:
                return True
        except Exception:
            continue
    return False
