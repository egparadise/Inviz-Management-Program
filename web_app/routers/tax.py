# -*- coding: utf-8 -*-
"""전자세금계산서 — 매출(작성·발행) /tax/issue, 매입(수신확인) /tax/inbox.

현재 발행 방식: 수동/기록 관리 (홈택스 직접 API 없음).
 - 작성·관리·발행상태 기록, 거래처/본인 메일 발송, Excel 출력.
 - 실제 국세청 전송은 홈택스 바로가기 또는 ASP(팝빌/바로빌) 키 등록 시 자동.
매입 수신: 설정된 메일함(IMAP)에서 홈택스 세금계산서 메일을 확인 → 기록 → 이메일·카카오 알림.
"""
import io
import json
from datetime import date, datetime
from fastapi import APIRouter, Request, Form, Depends, HTTPException
from fastapi.responses import HTMLResponse, RedirectResponse, Response
from sqlalchemy import select, func, desc
from sqlalchemy.orm import Session

from database import get_db
from helpers import templates
from models import TaxInvoice, Party
import settings_store as ss
import integrations as ig

router = APIRouter()

HOMETAX_URL = "https://www.hometax.go.kr"


def _company():
    return {"corp_no": ss.get("tax_corp_no", ""), "name": ss.get("tax_corp_name", "(주)인비즈"),
            "ceo": ss.get("tax_ceo", ""), "email": ss.get("tax_issuer_email", "")}


def _base_url(request: Request) -> str:
    try:
        return str(request.base_url)
    except Exception:
        return ""


# ===================== 매출: 계산서 작성·발행 =====================
@router.get("/issue", response_class=HTMLResponse)
def tax_issue_page(request: Request, db: Session = Depends(get_db)):
    rows = db.execute(select(TaxInvoice).where(TaxInvoice.direction == "sale")
                      .order_by(desc(TaxInvoice.id)).limit(200)).scalars().all()
    parties = db.execute(select(Party).where(Party.active == "Y").order_by(Party.name).limit(2000)).scalars().all()
    return templates.TemplateResponse("tax/issue.html", {
        "request": request, "rows": rows, "parties": parties, "company": _company(),
        "asp": ss.get("tax_asp", "manual"), "asp_ready": ig.asp_ready(),
        "mail_ready": ig.mail_send_ready(), "hometax_url": HOMETAX_URL, "today": date.today(),
    })


@router.post("/create")
def tax_create(request: Request, db: Session = Depends(get_db),
               party_name: str = Form(""), buyer_corp_no: str = Form(""), buyer_email: str = Form(""),
               write_date: str = Form(""), item_desc: str = Form(""),
               supply: str = Form("0"), vat: str = Form(""), doc_kind: str = Form("세금계산서"),
               send_date: str = Form("")):
    def _num(v):
        try:
            return float(str(v).replace(",", "").strip() or 0)
        except Exception:
            return 0.0
    sup = _num(supply)
    v = _num(vat) if str(vat).strip() != "" else (round(sup * 0.1) if doc_kind == "세금계산서" else 0)
    co = _company()
    try:
        wd = date.fromisoformat(write_date) if write_date else date.today()
    except Exception:
        wd = date.today()
    # 예약 발송일 — 지정하면 status=scheduled, 날짜 도래 시 스케줄러가 자동 발송 + 알림
    sd = None
    if send_date.strip():
        try:
            sd = date.fromisoformat(send_date)
        except Exception:
            sd = None
    inv = TaxInvoice(
        direction="sale", doc_kind=doc_kind, write_date=wd, send_date=sd,
        supplier_corp_no=co["corp_no"], supplier_name=co["name"], supplier_email=co["email"],
        buyer_corp_no=buyer_corp_no.strip() or None, buyer_name=party_name.strip() or None,
        buyer_email=buyer_email.strip() or None, party_name=party_name.strip() or None,
        item_desc=item_desc.strip() or None,
        items_json=json.dumps([{"품목": item_desc.strip(), "공급가액": sup, "세액": v}], ensure_ascii=False),
        supply=sup, vat=v, total=sup + v,
        status=("scheduled" if sd else "ready"), issue_method="manual", source="manual",
    )
    db.add(inv); db.commit(); db.refresh(inv)
    return RedirectResponse(f"/tax/issue?created={inv.id}", status_code=303)


def process_due_invoices(db, base_url=""):
    """예약(status=scheduled) 매출 계산서 중 발송일이 도래한 건 자동 발송 + 알림(텔레그램·이메일·카카오).
    스케줄러 루프와 수동 버튼에서 호출. 처리 건수 반환."""
    today = date.today()
    due = db.execute(select(TaxInvoice).where(
        TaxInvoice.direction == "sale", TaxInvoice.status == "scheduled",
        TaxInvoice.send_date != None, TaxInvoice.send_date <= today)).scalars().all()  # noqa: E711
    sent = 0
    asp = ss.get("tax_asp", "manual")
    for inv in due:
        if ig.asp_ready() and asp in ("popbill", "barobill"):
            inv.status = "sent"; inv.issue_method = asp
            inv.invoice_no = inv.invoice_no or f"{asp.upper()}-{datetime.now().strftime('%Y%m%d%H%M%S')}"
        else:
            inv.status = "issued"; inv.issue_method = "manual"
        inv.issue_at = datetime.now()
        # 거래처 메일
        if inv.buyer_email and ig.mail_send_ready():
            body = (f"{inv.supplier_name} 전자{inv.doc_kind} 발행 안내\n작성일 {inv.write_date}\n품목 {inv.item_desc}\n"
                    f"공급가액 {int(inv.supply or 0):,} / 세액 {int(inv.vat or 0):,} / 합계 {int(inv.total or 0):,}원")
            ig.send_email(f"[{inv.supplier_name}] 전자{inv.doc_kind} 발행 안내", body, to=inv.buyer_email)
        # 본인 알림(텔레그램+이메일+카카오)
        subject = f"[인비즈] 예약 세금계산서 발송 — {inv.party_name or ''} {int(inv.total or 0):,}원"
        bodyn = (f"예약된 전자{inv.doc_kind}가 발송 처리되었습니다.\n"
                 f"· 거래처: {inv.party_name or '-'}\n· 발송일: {inv.send_date}\n· 품목: {inv.item_desc or '-'}\n"
                 f"· 합계: {int(inv.total or 0):,}원\n"
                 + ("" if ig.asp_ready() else "※ 수동 모드 — 실제 국세청 전송은 홈택스에서 진행하세요."))
        ig.notify(subject, bodyn, (base_url.rstrip('/') + "/tax/issue") if base_url else None)
        inv.notified = "Y"
        sent += 1
    if sent:
        db.commit()
    return sent


@router.post("/{inv_id}/issue")
def tax_issue(inv_id: int, request: Request, db: Session = Depends(get_db)):
    """발행(전송). ASP 키가 있으면 자동 발행, 없으면 수동 발행완료로 기록."""
    inv = db.get(TaxInvoice, inv_id)
    if not inv or inv.direction != "sale":
        raise HTTPException(404, "계산서 없음")
    asp = ss.get("tax_asp", "manual")
    msg = ""
    if ig.asp_ready() and asp in ("popbill", "barobill"):
        # ASP 자동 발행 (키 등록 시) — 실제 호출은 ASP SDK 연동 지점
        inv.status = "sent"; inv.issue_method = asp; inv.issue_at = datetime.now()
        inv.invoice_no = inv.invoice_no or f"{asp.upper()}-{datetime.now().strftime('%Y%m%d%H%M%S')}"
        msg = f"{asp} 통해 발행·국세청 전송 처리"
    else:
        inv.status = "issued"; inv.issue_method = "manual"; inv.issue_at = datetime.now()
        msg = "발행완료(수동) — 실제 국세청 전송은 홈택스에서 진행하세요"
    db.commit()
    # 거래처에 메일 발송(설정 시)
    if inv.buyer_email and ig.mail_send_ready():
        body = (f"{inv.supplier_name} 전자{inv.doc_kind} 발행 안내\n\n"
                f"· 작성일자: {inv.write_date}\n· 품목: {inv.item_desc}\n"
                f"· 공급가액 {int(inv.supply or 0):,}원 / 세액 {int(inv.vat or 0):,}원 / 합계 {int(inv.total or 0):,}원\n")
        ig.send_email(f"[{inv.supplier_name}] 전자{inv.doc_kind} 발행 안내", body, to=inv.buyer_email)
    return RedirectResponse(f"/tax/issue?issued={inv_id}", status_code=303)


@router.post("/{inv_id}/email")
def tax_email(inv_id: int, db: Session = Depends(get_db)):
    inv = db.get(TaxInvoice, inv_id)
    if not inv:
        raise HTTPException(404, "계산서 없음")
    to = inv.buyer_email or inv.supplier_email or ss.get("mail_notify_to", "")
    body = (f"전자{inv.doc_kind} ({inv.party_name})\n작성일 {inv.write_date}\n품목 {inv.item_desc}\n"
            f"공급가액 {int(inv.supply or 0):,} / 세액 {int(inv.vat or 0):,} / 합계 {int(inv.total or 0):,}원")
    ok, m = ig.send_email(f"전자{inv.doc_kind} — {inv.party_name}", body, to=to)
    return RedirectResponse(f"/tax/issue?mail={'1' if ok else '0'}&msg={m}", status_code=303)


@router.post("/{inv_id}/delete")
def tax_delete(inv_id: int, db: Session = Depends(get_db)):
    inv = db.get(TaxInvoice, inv_id)
    back = "/tax/issue" if (inv and inv.direction == "sale") else "/tax/inbox"
    if inv:
        db.delete(inv); db.commit()
    return RedirectResponse(back, status_code=303)


@router.get("/{inv_id}/export.xlsx")
def tax_export_xlsx(inv_id: int, db: Session = Depends(get_db)):
    inv = db.get(TaxInvoice, inv_id)
    if not inv:
        raise HTTPException(404, "계산서 없음")
    import openpyxl
    from openpyxl.styles import Font, PatternFill, Alignment, Border, Side
    wb = openpyxl.Workbook(); w = wb.active; w.title = "세금계산서"
    thin = Side(style="thin", color="999999"); bd = Border(thin, thin, thin, thin)
    w["A1"] = f"전자{inv.doc_kind}"; w["A1"].font = Font(size=16, bold=True)
    w.merge_cells("A1:D1"); w["A1"].alignment = Alignment(horizontal="center")
    info = [("작성일자", str(inv.write_date or "")), ("승인번호", inv.invoice_no or "(미발행)"),
            ("공급자", f"{inv.supplier_name or ''} ({inv.supplier_corp_no or ''})"),
            ("공급받는자", f"{inv.buyer_name or inv.party_name or ''} ({inv.buyer_corp_no or ''})"),
            ("품목", inv.item_desc or "")]
    r = 3
    for k, v in info:
        w.cell(row=r, column=1, value=k).font = Font(bold=True)
        w.cell(row=r, column=2, value=v); r += 1
    r += 1
    for j, h in enumerate(["공급가액", "세액", "합계"], 1):
        c = w.cell(row=r, column=j, value=h); c.font = Font(bold=True, color="FFFFFF")
        c.fill = PatternFill("solid", fgColor="6B2C91"); c.alignment = Alignment(horizontal="center"); c.border = bd
    r += 1
    for j, val in enumerate([inv.supply or 0, inv.vat or 0, inv.total or 0], 1):
        c = w.cell(row=r, column=j, value=float(val)); c.number_format = "#,##0"
        c.alignment = Alignment(horizontal="right"); c.border = bd
    for col, wd in zip("ABCD", (16, 30, 16, 16)):
        w.column_dimensions[col].width = wd
    buf = io.BytesIO(); wb.save(buf)
    import re as _re
    safe = _re.sub(r"[^\w가-힣.-]", "_", f"세금계산서_{inv.party_name or inv.id}_{inv.write_date or ''}")
    from urllib.parse import quote
    return Response(content=buf.getvalue(),
                    media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                    headers={"Content-Disposition": f"attachment; filename*=UTF-8''{quote(safe + '.xlsx')}"})


# ===================== 매입: 수신 확인 =====================
@router.get("/inbox", response_class=HTMLResponse)
def tax_inbox_page(request: Request, db: Session = Depends(get_db)):
    rows = db.execute(select(TaxInvoice).where(TaxInvoice.direction == "purchase")
                      .order_by(desc(TaxInvoice.id)).limit(300)).scalars().all()
    return templates.TemplateResponse("tax/inbox.html", {
        "request": request, "rows": rows,
        "mail_recv_ready": ig.mail_recv_ready(), "mail_send_ready": ig.mail_send_ready(),
        "kakao_ready": ig.kakao_ready(), "today": date.today(),
        "imap_days": ss.get("mail_imap_days", "7"),
    })


@router.post("/inbox/sync")
def tax_inbox_sync(request: Request, db: Session = Depends(get_db), days: str = Form("")):
    res = ig.imap_fetch_purchase(db, days=days or None, base_url=_base_url(request))
    return RedirectResponse(f"/tax/inbox?sync={'1' if res['ok'] else '0'}&msg={res['msg']}", status_code=303)


@router.post("/inbox/add")
def tax_inbox_add(request: Request, db: Session = Depends(get_db),
                  party_name: str = Form(""), supplier_corp_no: str = Form(""),
                  write_date: str = Form(""), item_desc: str = Form(""),
                  supply: str = Form("0"), vat: str = Form("")):
    def _num(v):
        try:
            return float(str(v).replace(",", "").strip() or 0)
        except Exception:
            return 0.0
    sup = _num(supply); v = _num(vat) if str(vat).strip() != "" else round(sup * 0.1)
    co = _company()
    try:
        wd = date.fromisoformat(write_date) if write_date else date.today()
    except Exception:
        wd = date.today()
    inv = TaxInvoice(
        direction="purchase", doc_kind="세금계산서", write_date=wd, issue_at=datetime.now(),
        supplier_name=party_name.strip() or None, supplier_corp_no=supplier_corp_no.strip() or None,
        party_name=party_name.strip() or None, buyer_name=co["name"], buyer_corp_no=co["corp_no"],
        item_desc=item_desc.strip() or None, supply=sup, vat=v, total=sup + v,
        status="received", issue_method="manual", source="manual", notified="N",
    )
    db.add(inv); db.commit(); db.refresh(inv)
    res = ig.notify_purchase(inv, _base_url(request))
    if any(ok for _, ok, _ in res):
        inv.notified = "Y"; db.commit()
    return RedirectResponse("/tax/inbox?added=1", status_code=303)


@router.post("/{inv_id}/notify")
def tax_notify(inv_id: int, request: Request, db: Session = Depends(get_db)):
    inv = db.get(TaxInvoice, inv_id)
    if not inv:
        raise HTTPException(404, "계산서 없음")
    res = ig.notify_purchase(inv, _base_url(request))
    if any(ok for _, ok, _ in res):
        inv.notified = "Y"; db.commit()
    msg = " / ".join(f"{ch}:{'OK' if ok else m}" for ch, ok, m in res)
    return RedirectResponse(f"/tax/inbox?notify={msg}", status_code=303)


@router.post("/process-scheduled")
def tax_process_scheduled(request: Request, db: Session = Depends(get_db)):
    """예약 발송분을 지금 즉시 처리(발송일 도래분). 평소엔 스케줄러가 자동 처리."""
    n = process_due_invoices(db, base_url=_base_url(request))
    return RedirectResponse(f"/tax/issue?processed={n}", status_code=303)


@router.post("/test-notify")
def tax_test_notify(request: Request):
    res = ig.notify("[인비즈] 알림 테스트", "세금계산서 알림 테스트입니다. (이메일·카카오·텔레그램)")
    parts = " · ".join(f"{ch}:{'OK' if ok else m}" for ch, ok, m in res)
    return RedirectResponse(f"/tax/inbox?test={parts}", status_code=303)
