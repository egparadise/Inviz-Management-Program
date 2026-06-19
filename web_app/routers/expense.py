# -*- coding: utf-8 -*-
"""지출 라우터 — fact_expense 기반 수기입력·목록·CSV·PDF·업로드·영수증 OCR"""
import json
from datetime import datetime, date
from pathlib import Path
from fastapi import APIRouter, Request, Form, Depends, HTTPException, UploadFile, File
from fastapi.responses import HTMLResponse, RedirectResponse, Response, JSONResponse
from sqlalchemy import select, func, and_, desc
from sqlalchemy.orm import Session

from database import get_db
from helpers import templates
from models import Expense

router = APIRouter()

PAYMENT_METHODS = ["법인카드", "현금", "이체", "개인지출", "체크카드", "기타"]

# 분류 — settings_store(JSON)에 저장, 없으면 기본값
DEFAULT_CATEGORIES = [
    ("운영비", ["사무용품", "통신비", "사무실 임대료", "공과금", "보험", "기타"]),
    ("인건비", ["급여 외", "복리후생", "회식·접대", "교육", "기타"]),
    ("판매관리비", ["광고선전", "지급수수료", "운반비", "여비교통", "차량유지", "기타"]),
    ("R&D", ["연구개발", "외주용역", "특허·인증", "장비", "기타"]),
    ("기타", ["세금공과", "잡비", "기타"]),
]


def load_categories() -> list:
    """settings_store에서 expense_categories JSON 로드, 없으면 기본값."""
    try:
        import settings_store as ss
        raw = (ss.get("expense_categories", "") or "").strip()
        if raw:
            data = json.loads(raw)
            if isinstance(data, list) and data and all(
                    isinstance(x, (list, tuple)) and len(x) == 2 for x in data):
                return [(m, list(subs)) for m, subs in data]
    except Exception:
        pass
    return DEFAULT_CATEGORIES


def save_categories(cats: list) -> None:
    import settings_store as ss
    ss.save({"expense_categories": json.dumps(cats, ensure_ascii=False)})
    ss.invalidate()


def category_flat():
    return [(m, s) for m, subs in load_categories() for s in subs]


# 영수증 사진 저장 폴더
UPLOAD_DIR = Path(__file__).parent.parent / "uploads" / "expense_receipts"
UPLOAD_DIR.mkdir(parents=True, exist_ok=True)


def _quarter(m: int) -> str:
    if 1 <= m <= 3: return "Q1"
    if 4 <= m <= 6: return "Q2"
    if 7 <= m <= 9: return "Q3"
    return "Q4"


def _filters(year: int | None, month: int | None, payment: str, category: str, q: str):
    conds = []
    if year:
        conds.append(Expense.year == year)
    if month:
        conds.append(Expense.month == month)
    if payment:
        conds.append(Expense.payment_method == payment)
    if category:
        conds.append(Expense.category_main == category)
    if q:
        like = f"%{q}%"
        conds.append(
            (Expense.party_or_place.like(like)) |
            (Expense.note.like(like)) |
            (Expense.employee_name.like(like))
        )
    return conds


@router.get("", response_class=HTMLResponse)
def expense_list(request: Request, db: Session = Depends(get_db),
                 year: int | None = None, month: int | None = None,
                 payment: str = "", category: str = "", q: str = "",
                 page: int = 1, per_page: int = 50):
    today = date.today()
    if year is None and month is None and not (payment or category or q):
        year = today.year  # 기본: 올해

    conds = _filters(year, month, payment, category, q)

    base = select(Expense)
    if conds:
        base = base.where(and_(*conds))

    total = db.execute(
        select(func.count(Expense.id)).where(and_(*conds)) if conds else select(func.count(Expense.id))
    ).scalar() or 0
    sum_amt = db.execute(
        select(func.coalesce(func.sum(Expense.amount), 0)).where(and_(*conds))
        if conds else select(func.coalesce(func.sum(Expense.amount), 0))
    ).scalar() or 0

    page = max(1, page)
    offset = (page - 1) * per_page
    rows = db.execute(
        base.order_by(desc(Expense.use_date), desc(Expense.id))
            .limit(per_page).offset(offset)
    ).scalars().all()

    # 결제수단별 합계 (필터 적용 후)
    pay_sum = db.execute(
        select(Expense.payment_method, func.count(Expense.id), func.coalesce(func.sum(Expense.amount), 0))
        .where(and_(*conds)) if conds else
        select(Expense.payment_method, func.count(Expense.id), func.coalesce(func.sum(Expense.amount), 0))
    ).all()
    by_payment = sorted(
        [{"name": p or "(미지정)", "count": c, "sum": float(s)} for p, c, s in
         db.execute(
             select(Expense.payment_method, func.count(Expense.id), func.coalesce(func.sum(Expense.amount), 0))
             .where(and_(*conds)).group_by(Expense.payment_method)
             if conds else
             select(Expense.payment_method, func.count(Expense.id), func.coalesce(func.sum(Expense.amount), 0))
             .group_by(Expense.payment_method)
         ).all()],
        key=lambda x: -x["sum"]
    )

    years = sorted([r[0] for r in db.execute(select(Expense.year).distinct()).all() if r[0]], reverse=True)

    return templates.TemplateResponse("expense/list.html", {
        "request": request, "rows": rows, "total": total, "sum_amt": float(sum_amt),
        "year": year, "month": month, "payment": payment, "category": category, "q": q,
        "page": page, "per_page": per_page,
        "years": years, "payment_methods": PAYMENT_METHODS, "categories": [m for m, _ in load_categories()],
        "by_payment": by_payment,
        "total_pages": (total + per_page - 1) // per_page,
    })


@router.get("/new", response_class=HTMLResponse)
def expense_new_form(request: Request):
    return templates.TemplateResponse("expense/edit.html", {
        "request": request, "row": None,
        "payment_methods": PAYMENT_METHODS, "categories": load_categories(), "category_flat": category_flat(),
        "today": date.today(),
    })


@router.get("/{exp_id}/edit", response_class=HTMLResponse)
def expense_edit_form(exp_id: int, request: Request, db: Session = Depends(get_db)):
    row = db.get(Expense, exp_id)
    if not row:
        raise HTTPException(404)
    return templates.TemplateResponse("expense/edit.html", {
        "request": request, "row": row,
        "payment_methods": PAYMENT_METHODS, "categories": load_categories(), "category_flat": category_flat(),
        "today": date.today(),
    })


def _save_from_form(row: Expense | None, db: Session, form: dict) -> Expense:
    dt = datetime.strptime(form["use_date"], "%Y-%m-%d").date()
    if row is None:
        row = Expense()
        db.add(row)
    row.use_date = dt
    row.year = dt.year
    row.month = dt.month
    row.quarter = _quarter(dt.month)
    row.employee_name = (form.get("employee_name") or "").strip() or None
    row.department = (form.get("department") or "").strip() or None
    row.party_or_place = (form.get("party_or_place") or "").strip() or None
    row.amount = float(form.get("amount") or 0)
    row.category_main = (form.get("category_main") or "").strip() or None
    row.category_sub = (form.get("category_sub") or "").strip() or None
    row.payment_method = (form.get("payment_method") or "").strip() or None
    row.note = (form.get("note") or "").strip() or None
    if not row.txn_id:
        row.txn_id = f"EXP-W-{int(datetime.now().timestamp())}"
    db.flush()
    return row


@router.post("")
async def expense_create(request: Request, db: Session = Depends(get_db)):
    form = dict(await request.form())
    _save_from_form(None, db, form)
    db.commit()
    return RedirectResponse("/expense", status_code=303)


@router.post("/{exp_id}")
async def expense_update(exp_id: int, request: Request, db: Session = Depends(get_db)):
    row = db.get(Expense, exp_id)
    if not row:
        raise HTTPException(404)
    form = dict(await request.form())
    _save_from_form(row, db, form)
    db.commit()
    return RedirectResponse("/expense", status_code=303)


@router.post("/{exp_id}/delete")
def expense_delete(exp_id: int, db: Session = Depends(get_db)):
    row = db.get(Expense, exp_id)
    if row:
        db.delete(row); db.commit()
    return RedirectResponse("/expense", status_code=303)


@router.get("/export.csv")
def expense_csv(db: Session = Depends(get_db),
                year: int | None = None, month: int | None = None,
                payment: str = "", category: str = "", q: str = ""):
    import io, csv
    conds = _filters(year, month, payment, category, q)
    stmt = select(Expense).order_by(desc(Expense.use_date), desc(Expense.id))
    if conds:
        stmt = stmt.where(and_(*conds))
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(["일자", "직원", "부서", "사용처/거래처", "금액",
                "결제수단", "분류(대)", "분류(소)", "비고"])
    for r in db.execute(stmt).scalars():
        w.writerow([r.use_date.isoformat() if r.use_date else "",
                    r.employee_name or "", r.department or "",
                    r.party_or_place or "", float(r.amount or 0),
                    r.payment_method or "", r.category_main or "", r.category_sub or "",
                    r.note or ""])
    return Response(
        ("﻿" + buf.getvalue()).encode("utf-8"),
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": 'attachment; filename="expense.csv"'}
    )


@router.get("/export.pdf")
def expense_pdf(db: Session = Depends(get_db),
                year: int | None = None, month: int | None = None,
                payment: str = "", category: str = "", q: str = ""):
    import io as _io
    from reportlab.lib.pagesizes import A4, landscape
    from reportlab.lib.units import mm
    from reportlab.lib import colors
    from reportlab.platypus import (SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer)
    from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
    from reportlab.pdfbase import pdfmetrics
    from reportlab.pdfbase.ttfonts import TTFont
    import os

    # 한글 폰트
    font_name = "Helvetica"
    for cand in (r"C:\Windows\Fonts\malgun.ttf", r"C:\Windows\Fonts\NanumGothic.ttf"):
        if os.path.exists(cand):
            try:
                pdfmetrics.registerFont(TTFont("KR", cand))
                font_name = "KR"
                break
            except Exception:
                pass

    conds = _filters(year, month, payment, category, q)
    stmt = select(Expense).order_by(desc(Expense.use_date), desc(Expense.id))
    if conds:
        stmt = stmt.where(and_(*conds))
    rows = db.execute(stmt).scalars().all()

    total_amt = sum(float(r.amount or 0) for r in rows)

    buf = _io.BytesIO()
    doc = SimpleDocTemplate(buf, pagesize=landscape(A4),
                            leftMargin=15*mm, rightMargin=15*mm,
                            topMargin=15*mm, bottomMargin=15*mm)
    title_style = ParagraphStyle(name="t", fontName=font_name, fontSize=16, leading=20, spaceAfter=6)
    sub_style = ParagraphStyle(name="s", fontName=font_name, fontSize=10, leading=14, textColor=colors.grey)

    title_parts = ["지출 보고서"]
    if year: title_parts.append(f"{year}년")
    if month: title_parts.append(f"{month}월")
    if payment: title_parts.append(f"결제: {payment}")
    if category: title_parts.append(f"분류: {category}")

    story = [
        Paragraph(" · ".join(title_parts), title_style),
        Paragraph(f"건수 {len(rows):,}건 · 합계 {total_amt:,.0f}원 · 생성 {datetime.now():%Y-%m-%d %H:%M}", sub_style),
        Spacer(1, 6*mm),
    ]

    data = [["일자", "직원", "사용처/거래처", "금액", "결제수단", "분류(대)", "분류(소)", "비고"]]
    for r in rows:
        data.append([
            r.use_date.isoformat() if r.use_date else "",
            r.employee_name or "",
            (r.party_or_place or "")[:40],
            f"{float(r.amount or 0):,.0f}",
            r.payment_method or "",
            r.category_main or "",
            r.category_sub or "",
            (r.note or "")[:30],
        ])
    data.append(["", "", "합계", f"{total_amt:,.0f}", "", "", "", ""])
    tbl = Table(data, repeatRows=1, colWidths=[22*mm, 18*mm, 60*mm, 25*mm, 22*mm, 25*mm, 25*mm, 50*mm])
    tbl.setStyle(TableStyle([
        ("FONTNAME", (0, 0), (-1, -1), font_name),
        ("FONTSIZE", (0, 0), (-1, -1), 8),
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#7C3AED")),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
        ("ALIGN", (3, 1), (3, -1), "RIGHT"),
        ("BACKGROUND", (0, -1), (-1, -1), colors.HexColor("#F3F4F6")),
        ("FONTSIZE", (0, -1), (-1, -1), 9),
        ("FONTNAME", (2, -1), (3, -1), font_name),
        ("GRID", (0, 0), (-1, -1), 0.25, colors.HexColor("#E5E7EB")),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
    ]))
    story.append(tbl)
    doc.build(story)
    buf.seek(0)
    return Response(buf.read(), media_type="application/pdf",
                    headers={"Content-Disposition": 'attachment; filename="expense.pdf"'})


# ====== 분류(대/소) 관리 ======
@router.get("/categories", response_class=HTMLResponse)
def categories_page(request: Request):
    return templates.TemplateResponse("expense/categories.html", {
        "request": request, "categories": load_categories(),
        "categories_json": json.dumps(load_categories(), ensure_ascii=False),
    })


@router.post("/categories/save")
async def categories_save(request: Request):
    form = dict(await request.form())
    raw = form.get("categories_json", "")
    try:
        data = json.loads(raw)
        # 유효성: [[main, [sub1, sub2, ...]], ...]
        clean = []
        for item in data:
            if not isinstance(item, (list, tuple)) or len(item) != 2:
                continue
            m = str(item[0]).strip()
            subs = [str(s).strip() for s in (item[1] or []) if str(s).strip()]
            if m:
                clean.append([m, subs])
        save_categories(clean)
    except Exception as e:
        raise HTTPException(400, f"분류 JSON 파싱 오류: {e}")
    return RedirectResponse("/expense/categories", status_code=303)


# ====== CSV/Excel 업로드 — 분석·미리보기·적용 ======
EXPENSE_CSV_HEADERS = ["일자", "금액", "결제수단", "사용처/거래처", "분류(대)", "분류(소)", "직원", "부서", "비고"]


@router.get("/import", response_class=HTMLResponse)
def import_form(request: Request):
    return templates.TemplateResponse("expense/import.html", {
        "request": request, "headers": EXPENSE_CSV_HEADERS,
        "preview": None, "errors": None,
    })


@router.get("/import/template.csv")
def import_template_csv():
    import csv, io
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(EXPENSE_CSV_HEADERS)
    w.writerow(["2026-06-19", 12500, "법인카드", "스타벅스 강남점",
                "운영비", "회식·접대", "박성철", "경영지원", "거래처 미팅"])
    return Response(("﻿" + buf.getvalue()).encode("utf-8"),
                    media_type="text/csv; charset=utf-8",
                    headers={"Content-Disposition": 'attachment; filename="expense_template.csv"'})


def _parse_date(v):
    if v is None or v == "":
        return None
    if isinstance(v, (date, datetime)):
        return v.date() if isinstance(v, datetime) else v
    s = str(v).strip()
    for fmt in ("%Y-%m-%d", "%Y/%m/%d", "%Y.%m.%d", "%Y%m%d"):
        try:
            return datetime.strptime(s, fmt).date()
        except ValueError:
            continue
    return None


def _parse_amount(v):
    if v is None or v == "":
        return 0.0
    s = str(v).replace(",", "").replace("원", "").strip()
    try:
        return float(s)
    except ValueError:
        return None


@router.post("/import/preview", response_class=HTMLResponse)
async def import_preview(request: Request, file: UploadFile = File(...)):
    raw = await file.read()
    fname = (file.filename or "").lower()
    rows = []
    errs = []
    try:
        if fname.endswith((".xlsx", ".xls", ".xlsm")):
            from helpers import load_workbook_any
            wb = load_workbook_any(raw)
            ws = wb[wb.sheetnames[0]]
            all_rows = list(ws.iter_rows(values_only=True))
            if not all_rows:
                errs.append("시트가 비어있습니다.")
            else:
                hdr = [str(c).strip() if c is not None else "" for c in all_rows[0]]
                idx = {h: i for i, h in enumerate(hdr)}
                for i, r in enumerate(all_rows[1:], start=2):
                    if not r or not any(c not in (None, "") for c in r):
                        continue
                    rows.append({h: (r[idx[h]] if h in idx and idx[h] < len(r) else None) for h in EXPENSE_CSV_HEADERS})
        else:
            import csv, io
            text = raw.decode("utf-8-sig", errors="replace")
            reader = csv.DictReader(io.StringIO(text))
            for r in reader:
                rows.append({h: r.get(h, "") for h in EXPENSE_CSV_HEADERS})
    except Exception as e:
        errs.append(f"파일 읽기 오류: {e}")

    preview = []
    for i, r in enumerate(rows, start=2):
        dt = _parse_date(r.get("일자"))
        if not dt:
            errs.append(f"행 {i}: 일자 형식 오류 ({r.get('일자')!r})"); continue
        amt = _parse_amount(r.get("금액"))
        if amt is None:
            errs.append(f"행 {i}: 금액 형식 오류 ({r.get('금액')!r})"); continue
        preview.append({
            "row_no": i, "use_date": dt, "amount": amt,
            "payment_method": str(r.get("결제수단") or "").strip() or "기타",
            "party_or_place": str(r.get("사용처/거래처") or "").strip(),
            "category_main": str(r.get("분류(대)") or "").strip(),
            "category_sub": str(r.get("분류(소)") or "").strip(),
            "employee_name": str(r.get("직원") or "").strip(),
            "department": str(r.get("부서") or "").strip(),
            "note": str(r.get("비고") or "").strip(),
        })

    encoded = json.dumps(preview, default=str, ensure_ascii=False)
    return templates.TemplateResponse("expense/import.html", {
        "request": request, "headers": EXPENSE_CSV_HEADERS,
        "preview": preview, "errors": errs, "encoded": encoded,
    })


@router.post("/import/commit")
def import_commit(db: Session = Depends(get_db), payload: str = Form(...)):
    rows = json.loads(payload)
    n = 0
    for r in rows:
        dt = datetime.strptime(r["use_date"], "%Y-%m-%d").date() if isinstance(r["use_date"], str) else r["use_date"]
        exp = Expense(
            use_date=dt, year=dt.year, month=dt.month, quarter=_quarter(dt.month),
            amount=float(r.get("amount") or 0),
            payment_method=r.get("payment_method") or None,
            party_or_place=r.get("party_or_place") or None,
            category_main=r.get("category_main") or None,
            category_sub=r.get("category_sub") or None,
            employee_name=r.get("employee_name") or None,
            department=r.get("department") or None,
            note=r.get("note") or None,
            txn_id=f"EXP-CSV-{int(datetime.now().timestamp())}-{n}",
        )
        db.add(exp); n += 1
    db.commit()
    return RedirectResponse(f"/expense?_imported={n}", status_code=303)


# ====== 영수증 사진 — AI 분석 (OpenAI Vision / Claude Vision) ======
@router.get("/receipt", response_class=HTMLResponse)
def receipt_form(request: Request):
    return templates.TemplateResponse("expense/receipt.html", {
        "request": request, "categories": load_categories(),
        "payment_methods": PAYMENT_METHODS,
    })


@router.post("/receipt/analyze")
async def receipt_analyze(file: UploadFile = File(...)):
    """업로드된 영수증 이미지를 LLM Vision으로 분석 → JSON 반환."""
    raw = await file.read()
    mime = file.content_type or "image/jpeg"
    if not mime.startswith("image/"):
        return JSONResponse({"ok": False, "error": "이미지 파일만 지원합니다."}, status_code=400)
    # 원본 저장 (감사용)
    saved_name = f"{datetime.now():%Y%m%d_%H%M%S}_{(file.filename or 'receipt')[:60]}"
    saved_path = UPLOAD_DIR / saved_name
    try:
        saved_path.write_bytes(raw)
    except Exception:
        saved_name = ""
    try:
        from llm_provider import analyze_receipt_image
        result = analyze_receipt_image(raw, mime=mime)
        result["ok"] = True
        result["saved"] = saved_name
        return JSONResponse(result)
    except Exception as e:
        return JSONResponse({"ok": False, "error": str(e), "saved": saved_name}, status_code=500)


@router.post("/receipt/apply")
async def receipt_apply(request: Request, db: Session = Depends(get_db)):
    """사용자가 미리보기에서 확정한 영수증 데이터를 fact_expense에 적용."""
    form = dict(await request.form())
    dt = _parse_date(form.get("use_date"))
    if not dt:
        raise HTTPException(400, "일자 형식 오류")
    amt = _parse_amount(form.get("amount"))
    if amt is None:
        raise HTTPException(400, "금액 형식 오류")
    receipt_file = (form.get("receipt_file") or "").strip()
    note = (form.get("note") or "").strip()
    if receipt_file:
        note = (note + f" [영수증: {receipt_file}]").strip()
    db.add(Expense(
        use_date=dt, year=dt.year, month=dt.month, quarter=_quarter(dt.month),
        amount=amt,
        payment_method=(form.get("payment_method") or "기타").strip(),
        party_or_place=(form.get("party_or_place") or "").strip() or None,
        category_main=(form.get("category_main") or "").strip() or None,
        category_sub=(form.get("category_sub") or "").strip() or None,
        employee_name=(form.get("employee_name") or "").strip() or None,
        department=(form.get("department") or "").strip() or None,
        note=note or None,
        txn_id=f"EXP-OCR-{int(datetime.now().timestamp())}",
    ))
    db.commit()
    return RedirectResponse("/expense", status_code=303)
