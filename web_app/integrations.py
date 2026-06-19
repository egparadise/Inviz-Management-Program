# -*- coding: utf-8 -*-
"""외부 연동 — 이메일(SMTP 발송 / IMAP 수신확인) + 카카오톡(나에게 보내기) + 알림.

설계 원칙:
 - 모든 함수는 설정(settings_store)이 비어 있으면 안전하게 (ok=False, 사유) 반환 (예외 안 던짐).
 - 비밀값(비밀번호·토큰)은 DB(app_setting)에만 저장, 화면 재노출 안 함.
 - 국세청 홈택스는 직접 API가 없어 ASP(팝빌/바로빌) 키가 있을 때만 자동 발행. (manual 모드는 기록·홈택스 바로가기)
"""
import json
import re
import ssl
import smtplib
import imaplib
import email
import urllib.request
import urllib.parse
from email.message import EmailMessage
from email.header import decode_header
from datetime import datetime, timedelta


def _s(key, default=""):
    try:
        import settings_store as ss
        return (ss.get(key, default) or "").strip()
    except Exception:
        return default


# ---------- 준비 상태(설정 아이콘용) ----------
def mail_send_ready():
    return bool(_s("mail_smtp_host") and _s("mail_smtp_user") and _s("mail_smtp_pass"))


def mail_recv_ready():
    return bool(_s("mail_imap_host") and _s("mail_imap_user") and _s("mail_imap_pass"))


def kakao_ready():
    return _s("kakao_enabled") == "1" and bool(_s("kakao_access_token"))


def asp_ready():
    asp = _s("tax_asp", "manual")
    if asp == "popbill":
        return bool(_s("tax_popbill_linkid") and _s("tax_popbill_secret"))
    if asp == "barobill":
        return bool(_s("tax_barobill_certkey"))
    return False  # manual


# ---------- 이메일 발송 (SMTP) ----------
def send_email(subject, body, to=None, html=False, attachments=None):
    """이메일 발송. attachments: [(filename, bytes[, maintype, subtype]), ...] 또는
    [{'filename','data','maintype','subtype'}, ...]. PDF 첨부 시 maintype='application', subtype='pdf'."""
    if not mail_send_ready():
        return False, "이메일(SMTP)이 설정되지 않았습니다."
    host = _s("mail_smtp_host"); port = int(_s("mail_smtp_port", "587") or 587)
    user = _s("mail_smtp_user"); pw = _s("mail_smtp_pass")
    sender = _s("mail_from") or user
    to = to or _s("mail_notify_to") or user
    msg = EmailMessage()
    msg["Subject"] = subject
    msg["From"] = sender
    msg["To"] = to
    if html:
        msg.set_content("HTML 메일입니다.")
        msg.add_alternative(body, subtype="html")
    else:
        msg.set_content(body)
    for att in (attachments or []):
        if isinstance(att, dict):
            fname = att.get("filename", "attachment"); data = att.get("data", b"")
            maintype = att.get("maintype", "application"); subtype = att.get("subtype", "octet-stream")
        else:
            fname, data = att[0], att[1]
            maintype = att[2] if len(att) > 2 else "application"
            subtype = att[3] if len(att) > 3 else "octet-stream"
        msg.add_attachment(data, maintype=maintype, subtype=subtype, filename=fname)
    try:
        if port == 465:
            with smtplib.SMTP_SSL(host, port, timeout=20, context=ssl.create_default_context()) as s:
                s.login(user, pw); s.send_message(msg)
        else:
            with smtplib.SMTP(host, port, timeout=20) as s:
                if _s("mail_smtp_tls", "1") == "1":
                    s.starttls(context=ssl.create_default_context())
                s.login(user, pw); s.send_message(msg)
        return True, f"이메일 발송 완료 → {to}"
    except Exception as e:
        return False, f"이메일 발송 실패: {e}"


# ---------- 카카오톡 '나에게 보내기' ----------
def kakao_send_self(text, link_url=None):
    if not kakao_ready():
        return False, "카카오톡(나에게 보내기)이 설정되지 않았습니다."
    token = _s("kakao_access_token")
    obj = {"object_type": "text", "text": text[:2000],
           "link": {"web_url": link_url or "", "mobile_web_url": link_url or ""}}
    data = urllib.parse.urlencode({"template_object": json.dumps(obj, ensure_ascii=False)}).encode()
    req = urllib.request.Request(
        "https://kapi.kakao.com/v2/api/talk/memo/default/send",
        data=data, headers={"Authorization": f"Bearer {token}",
                            "Content-Type": "application/x-www-form-urlencoded;charset=utf-8"}, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=15) as r:
            r.read()
        return True, "카카오톡 알림 발송 완료(나에게 보내기)"
    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8", "replace")[:200]
        # 401 → 토큰 만료. refresh 시도
        if e.code == 401 and _s("kakao_refresh_token") and _s("kakao_rest_key"):
            if kakao_refresh()[0]:
                return kakao_send_self(text, link_url)
        return False, f"카카오 발송 실패({e.code}): {body}"
    except Exception as e:
        return False, f"카카오 발송 실패: {e}"


def kakao_refresh():
    """access_token 만료 시 refresh_token으로 갱신."""
    rest = _s("kakao_rest_key"); refresh = _s("kakao_refresh_token")
    if not (rest and refresh):
        return False, "카카오 갱신 정보 부족"
    data = urllib.parse.urlencode({
        "grant_type": "refresh_token", "client_id": rest, "refresh_token": refresh}).encode()
    try:
        with urllib.request.urlopen(urllib.request.Request(
                "https://kauth.kakao.com/oauth/token", data=data), timeout=15) as r:
            j = json.loads(r.read().decode())
        import settings_store as ss
        upd = {"kakao_access_token": j["access_token"]}
        if j.get("refresh_token"):
            upd["kakao_refresh_token"] = j["refresh_token"]
        ss.save(upd)
        return True, "카카오 토큰 갱신 완료"
    except Exception as e:
        return False, f"카카오 토큰 갱신 실패: {e}"


# ---------- 텔레그램 ----------
def telegram_ready():
    return _s("telegram_enabled") == "1" and bool(_s("telegram_bot_token") and _s("telegram_chat_id"))


def send_telegram(text):
    if not telegram_ready():
        return False, "텔레그램이 설정되지 않았습니다."
    token = _s("telegram_bot_token"); chat = _s("telegram_chat_id")
    data = urllib.parse.urlencode({"chat_id": chat, "text": text[:4000],
                                   "disable_web_page_preview": "true"}).encode()
    req = urllib.request.Request(f"https://api.telegram.org/bot{token}/sendMessage", data=data)
    try:
        with urllib.request.urlopen(req, timeout=15) as r:
            r.read()
        return True, "텔레그램 알림 발송 완료"
    except urllib.error.HTTPError as e:
        return False, f"텔레그램 발송 실패({e.code}): {e.read().decode('utf-8','replace')[:150]}"
    except Exception as e:
        return False, f"텔레그램 발송 실패: {e}"


def notify(subject, body, link=None):
    """통합 알림 — 이메일 + 카카오(나에게) + 텔레그램. 설정된 채널만 발송."""
    msg = subject + "\n" + body
    return [
        ("email",) + tuple(send_email(subject, body)),
        ("kakao",) + tuple(kakao_send_self(msg, link)),
        ("telegram",) + tuple(send_telegram(msg)),
    ]


# ---------- 매입 세금계산서 수신 알림 ----------
def notify_purchase(inv, base_url=""):
    """매입 세금계산서 1건 알림 (이메일 + 카카오). 결과 메시지 리스트 반환."""
    won = f"{int(inv.total or 0):,}"
    subject = f"[인비즈] 매입 세금계산서 수신 — {inv.party_name or '거래처'} {won}원"
    body = (f"매입 전자세금계산서가 수신되었습니다.\n\n"
            f"· 공급자(거래처): {inv.party_name or '-'}\n"
            f"· 작성일자: {inv.write_date or '-'}\n"
            f"· 품목: {inv.item_desc or '-'}\n"
            f"· 공급가액: {int(inv.supply or 0):,}원 / 세액: {int(inv.vat or 0):,}원 / 합계: {won}원\n"
            f"· 출처: {inv.source or '-'}\n")
    link = (base_url.rstrip('/') + "/tax/inbox") if base_url else None
    out = []
    e_ok, e_msg = send_email(subject, body)
    out.append(("email", e_ok, e_msg))
    k_ok, k_msg = kakao_send_self(subject + "\n" + body, link)
    out.append(("kakao", k_ok, k_msg))
    t_ok, t_msg = send_telegram(subject + "\n" + body)
    out.append(("telegram", t_ok, t_msg))
    return out


# ---------- 이메일(IMAP)로 매입 세금계산서 수신 확인 ----------
def _dec(s):
    if not s:
        return ""
    parts = decode_header(s)
    out = []
    for txt, enc in parts:
        if isinstance(txt, bytes):
            try:
                out.append(txt.decode(enc or "utf-8", "replace"))
            except Exception:
                out.append(txt.decode("utf-8", "replace"))
        else:
            out.append(txt)
    return "".join(out)


def _body_text(msg):
    try:
        if msg.is_multipart():
            for part in msg.walk():
                if part.get_content_type() == "text/plain":
                    return part.get_payload(decode=True).decode(part.get_content_charset() or "utf-8", "replace")
            for part in msg.walk():
                if part.get_content_type() == "text/html":
                    html = part.get_payload(decode=True).decode(part.get_content_charset() or "utf-8", "replace")
                    return re.sub(r"<[^>]+>", " ", html)
        else:
            return msg.get_payload(decode=True).decode(msg.get_content_charset() or "utf-8", "replace")
    except Exception:
        return ""
    return ""


_TAX_KW = re.compile(r"전자\s*\(?\s*세금\s*\)?\s*계산서|세금계산서|계산서\s*발급", re.IGNORECASE)
_AMT = re.compile(r"(?:합계|공급대가|총액|금액)\D{0,8}([0-9][0-9,]{3,})")
_SUP = re.compile(r"(?:공급가액)\D{0,8}([0-9][0-9,]{3,})")
_VAT = re.compile(r"(?:세액|부가세)\D{0,8}([0-9][0-9,]{3,})")
_SUPPLIER = re.compile(r"공급자\s*[:：]?\s*([^\n,/]{2,40})")


def imap_fetch_purchase(db, days=None, base_url=""):
    """IMAP로 최근 N일 메일 중 '전자세금계산서' 알림을 찾아 매입 TaxInvoice 생성 + 알림.
    반환: {ok, msg, found(신규 건수), notified}
    """
    if not mail_recv_ready():
        return {"ok": False, "msg": "이메일(IMAP) 수신이 설정되지 않았습니다.", "found": 0}
    from models import TaxInvoice
    from sqlalchemy import select
    host = _s("mail_imap_host"); port = int(_s("mail_imap_port", "993") or 993)
    user = _s("mail_imap_user"); pw = _s("mail_imap_pass")
    days = int(days or _s("mail_imap_days", "7") or 7)
    new_rows = []
    try:
        M = imaplib.IMAP4_SSL(host, port)
        M.login(user, pw)
        M.select("INBOX")
        since = (datetime.now() - timedelta(days=days)).strftime("%d-%b-%Y")
        typ, data = M.search(None, f'(SINCE {since})')
        ids = data[0].split() if data and data[0] else []
        for num in ids[-200:]:  # 최근 200개 한도
            typ, msg_data = M.fetch(num, "(RFC822)")
            if typ != "OK" or not msg_data or not msg_data[0]:
                continue
            msg = email.message_from_bytes(msg_data[0][1])
            subj = _dec(msg.get("Subject"))
            frm = _dec(msg.get("From"))
            mid = (msg.get("Message-ID") or f"{num}-{subj}")[:300]
            blob = subj + " " + frm
            text = _body_text(msg)
            if not _TAX_KW.search(blob) and not _TAX_KW.search(text[:3000]):
                continue  # 세금계산서 메일 아님
            # 중복 방지
            if db.scalar(select(TaxInvoice.id).where(TaxInvoice.raw_ref == mid)):
                continue
            full = subj + "\n" + text[:4000]
            def _num(rx):
                m = rx.search(full)
                return float(m.group(1).replace(",", "")) if m else 0.0
            supply = _num(_SUP); vat = _num(_VAT); total = _num(_AMT)
            if total == 0 and supply:
                total = supply + vat
            ms = _SUPPLIER.search(full)
            supplier = (ms.group(1).strip() if ms else "") or re.sub(r"<.*?>", "", frm).strip()[:60]
            inv = TaxInvoice(
                direction="purchase", doc_kind="세금계산서",
                write_date=None, issue_at=datetime.now(),
                supplier_name=supplier, party_name=supplier,
                buyer_name=_s("tax_corp_name"), buyer_corp_no=_s("tax_corp_no"),
                item_desc=subj[:200],
                supply=supply, vat=vat, total=total,
                status="received", issue_method="hometax", source="email",
                note=f"메일수신: {frm}", raw_ref=mid, notified="N",
            )
            db.add(inv); db.commit(); db.refresh(inv)
            new_rows.append(inv)
        M.logout()
    except Exception as e:
        return {"ok": False, "msg": f"IMAP 수신 실패: {e}", "found": 0}

    # 신규 건 알림
    notified = 0
    for inv in new_rows:
        res = notify_purchase(inv, base_url)
        if any(ok for _, ok, _ in res):
            inv.notified = "Y"; db.commit(); notified += 1
    return {"ok": True, "msg": f"수신확인 완료 — 신규 {len(new_rows)}건, 알림 {notified}건",
            "found": len(new_rows), "notified": notified}
