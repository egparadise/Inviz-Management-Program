# -*- coding: utf-8 -*-
"""계약 라우터"""
from pathlib import Path
from datetime import date, datetime
from fastapi import APIRouter, Request, Form, Depends, HTTPException
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy import select, func, or_
from sqlalchemy.orm import Session

from database import get_db
from helpers import templates
from models import Contract, Party, Product

router = APIRouter()


def parse_date(s):
    if not s: return None
    try: return datetime.strptime(s, "%Y-%m-%d").date()
    except: return None


@router.get("", response_class=HTMLResponse)
def list_contracts(
    request: Request, db: Session = Depends(get_db),
    q: str = "", status: str = "", kind: str = "",
    page: int = 1, per_page: int = 50,
):
    stmt = select(Contract)
    if q: stmt = stmt.where(or_(Contract.name.contains(q), Contract.party_name.contains(q)))
    if status: stmt = stmt.where(Contract.status == status)
    if kind: stmt = stmt.where(Contract.kind == kind)

    total_count = db.scalar(select(func.count()).select_from(stmt.subquery()))
    total_amount = db.scalar(select(func.coalesce(func.sum(Contract.contract_amount), 0)).select_from(stmt.subquery())) or 0
    total_unpaid = db.scalar(select(func.coalesce(func.sum(Contract.unpaid_amount), 0)).select_from(stmt.subquery())) or 0

    rows = db.execute(
        stmt.order_by(Contract.start_date.desc().nullslast(), Contract.id)
        .offset((page - 1) * per_page).limit(per_page)
    ).scalars().all()

    # 잔여일수 갱신
    today = date.today()
    for r in rows:
        if r.end_date:
            r.remain_days = (r.end_date - today).days

    return templates.TemplateResponse("contracts/list.html", {
        "request": request, "rows": rows,
        "total_count": total_count, "total_amount": float(total_amount), "total_unpaid": float(total_unpaid),
        "filter": {"q": q, "status": status, "kind": kind},
        "page": page, "per_page": per_page,
        "total_pages": (total_count + per_page - 1) // per_page,
    })


@router.get("/new", response_class=HTMLResponse)
def new_form(request: Request, db: Session = Depends(get_db)):
    products = db.execute(select(Product).order_by(Product.code)).scalars().all()
    parties = db.execute(select(Party).where(Party.active == "Y").order_by(Party.name).limit(2000)).scalars().all()
    last = db.execute(select(Contract).order_by(Contract.id.desc()).limit(1)).scalar_one_or_none()
    next_num = 1
    if last and last.id.startswith("K-W-"):
        try: next_num = int(last.id.split("-")[-1]) + 1
        except: pass
    return templates.TemplateResponse("contracts/form.html", {
        "request": request, "row": None,
        "next_id": f"K-W-{next_num:04d}",
        "products": products, "parties": parties,
    })


@router.post("")
def create_contract(
    db: Session = Depends(get_db),
    id: str = Form(...), name: str = Form(...), kind: str = Form(""),
    party_code: str = Form(""), party_name: str = Form(""),
    product_code: str = Form(""), item_name: str = Form(""),
    signed_date: str = Form(""), start_date: str = Form(""), end_date: str = Form(""),
    duration_months: float = Form(0), auto_renew: str = Form("N"),
    contract_amount: float = Form(0), issued_amount: float = Form(0), unpaid_amount: float = Form(0),
    payment_term: str = Form(""), install_date: str = Form(""), warranty_end: str = Form(""),
    has_contract_doc: str = Form("Y"), owner: str = Form(""), phone: str = Form(""),
    status: str = Form("진행"), note: str = Form(""),
):
    if db.get(Contract, id): raise HTTPException(400, "계약ID 중복")
    end_d = parse_date(end_date)
    remain = (end_d - date.today()).days if end_d else None
    db.add(Contract(
        id=id, name=name, kind=kind or None,
        party_code=party_code or None, party_name=party_name or None,
        product_code=product_code or None, item_name=item_name or None,
        signed_date=parse_date(signed_date), start_date=parse_date(start_date), end_date=end_d,
        duration_months=duration_months or None, auto_renew=auto_renew,
        contract_amount=contract_amount, issued_amount=issued_amount, unpaid_amount=unpaid_amount,
        payment_term=payment_term or None,
        install_date=parse_date(install_date), warranty_end=parse_date(warranty_end),
        has_contract_doc=has_contract_doc, owner=owner or None, phone=phone or None,
        status=status, note=note or None, remain_days=remain,
    ))
    db.commit()
    return RedirectResponse("/contracts", status_code=303)


@router.get("/{cid}/edit", response_class=HTMLResponse)
def edit_form(cid: str, request: Request, db: Session = Depends(get_db)):
    row = db.get(Contract, cid)
    if not row: raise HTTPException(404)
    products = db.execute(select(Product).order_by(Product.code)).scalars().all()
    parties = db.execute(select(Party).where(Party.active == "Y").order_by(Party.name).limit(2000)).scalars().all()
    return templates.TemplateResponse("contracts/form.html", {
        "request": request, "row": row, "next_id": cid, "products": products, "parties": parties,
    })


@router.post("/{cid}")
def update_contract(
    cid: str, db: Session = Depends(get_db),
    name: str = Form(...), kind: str = Form(""),
    party_code: str = Form(""), party_name: str = Form(""),
    product_code: str = Form(""), item_name: str = Form(""),
    signed_date: str = Form(""), start_date: str = Form(""), end_date: str = Form(""),
    duration_months: float = Form(0), auto_renew: str = Form("N"),
    contract_amount: float = Form(0), issued_amount: float = Form(0), unpaid_amount: float = Form(0),
    payment_term: str = Form(""), install_date: str = Form(""), warranty_end: str = Form(""),
    has_contract_doc: str = Form("Y"), owner: str = Form(""), phone: str = Form(""),
    status: str = Form("진행"), note: str = Form(""),
):
    row = db.get(Contract, cid)
    if not row: raise HTTPException(404)
    row.name = name; row.kind = kind or None
    row.party_code = party_code or None; row.party_name = party_name or None
    row.product_code = product_code or None; row.item_name = item_name or None
    row.signed_date = parse_date(signed_date); row.start_date = parse_date(start_date)
    row.end_date = parse_date(end_date)
    row.duration_months = duration_months or None; row.auto_renew = auto_renew
    row.contract_amount = contract_amount; row.issued_amount = issued_amount
    row.unpaid_amount = unpaid_amount; row.payment_term = payment_term or None
    row.install_date = parse_date(install_date); row.warranty_end = parse_date(warranty_end)
    row.has_contract_doc = has_contract_doc; row.owner = owner or None; row.phone = phone or None
    row.status = status; row.note = note or None
    if row.end_date: row.remain_days = (row.end_date - date.today()).days
    db.commit()
    return RedirectResponse("/contracts", status_code=303)


@router.post("/{cid}/delete")
def delete_contract(cid: str, db: Session = Depends(get_db)):
    row = db.get(Contract, cid)
    if row: db.delete(row); db.commit()
    return RedirectResponse("/contracts", status_code=303)
