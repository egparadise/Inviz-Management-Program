# -*- coding: utf-8 -*-
"""차입금 라우터 (마스터 + movements)"""
from pathlib import Path
from datetime import date, datetime
from fastapi import APIRouter, Request, Form, Depends, HTTPException
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy import select, func
from sqlalchemy.orm import Session

from database import get_db
from helpers import templates
from models import Loan, LoanMaster

router = APIRouter()


def parse_date(s):
    if not s: return None
    try: return datetime.strptime(s, "%Y-%m-%d").date()
    except: return None


@router.get("", response_class=HTMLResponse)
def list_loans(request: Request, db: Session = Depends(get_db), kind: str = ""):
    stmt = select(LoanMaster)
    if kind: stmt = stmt.where(LoanMaster.kind == kind)
    masters = db.execute(stmt.order_by(LoanMaster.term, LoanMaster.institution)).scalars().all()

    # 합계
    total_initial = sum((m.initial_amount or 0) for m in masters)
    total_balance = sum((m.current_balance or 0) for m in masters)

    # 임원 차입금 movements 최근 50건
    movements = db.execute(
        select(Loan).order_by(Loan.txn_date.desc(), Loan.id.desc()).limit(50)
    ).scalars().all()

    return templates.TemplateResponse("loans/list.html", {
        "request": request, "masters": masters,
        "total_initial": float(total_initial), "total_balance": float(total_balance),
        "movements": movements, "filter": {"kind": kind},
    })


@router.get("/new", response_class=HTMLResponse)
def new_form(request: Request, db: Session = Depends(get_db)):
    last = db.execute(select(LoanMaster).order_by(LoanMaster.id.desc()).limit(1)).scalar_one_or_none()
    next_num = 1
    if last and last.id.startswith("LM-W-"):
        try: next_num = int(last.id.split("-")[-1]) + 1
        except: pass
    return templates.TemplateResponse("loans/form.html", {
        "request": request, "row": None, "next_id": f"LM-W-{next_num:04d}",
    })


@router.post("")
def create_loan(
    db: Session = Depends(get_db),
    id: str = Form(...), kind: str = Form(""), term: str = Form(""),
    institution: str = Form(...), account_no: str = Form(""),
    limit_amount: float = Form(0), initial_amount: float = Form(0), current_balance: float = Form(0),
    loan_type: str = Form(""), interest_rate: float = Form(0),
    repayment_method: str = Form(""), start_date: str = Form(""), end_date: str = Form(""),
    collateral: str = Form(""), collateral_amount: float = Form(0),
    ceo_guarantee: str = Form(""), status: str = Form("활성"), note: str = Form(""),
):
    if db.get(LoanMaster, id): raise HTTPException(400, "ID 중복")
    db.add(LoanMaster(
        id=id, kind=kind or None, term=term or None,
        institution=institution, account_no=account_no or None,
        limit_amount=limit_amount or None, initial_amount=initial_amount or None,
        current_balance=current_balance or None,
        loan_type=loan_type or None, interest_rate=interest_rate or None,
        repayment_method=repayment_method or None,
        start_date=parse_date(start_date), end_date=parse_date(end_date),
        collateral=collateral or None, collateral_amount=collateral_amount or None,
        ceo_guarantee=ceo_guarantee or None, status=status, note=note or None,
    ))
    db.commit()
    return RedirectResponse("/loans", status_code=303)


@router.get("/{lid}/edit", response_class=HTMLResponse)
def edit_form(lid: str, request: Request, db: Session = Depends(get_db)):
    row = db.get(LoanMaster, lid)
    if not row: raise HTTPException(404)
    return templates.TemplateResponse("loans/form.html", {"request": request, "row": row, "next_id": lid})


@router.post("/{lid}")
def update_loan(
    lid: str, db: Session = Depends(get_db),
    kind: str = Form(""), term: str = Form(""),
    institution: str = Form(...), account_no: str = Form(""),
    limit_amount: float = Form(0), initial_amount: float = Form(0), current_balance: float = Form(0),
    loan_type: str = Form(""), interest_rate: float = Form(0),
    repayment_method: str = Form(""), start_date: str = Form(""), end_date: str = Form(""),
    collateral: str = Form(""), collateral_amount: float = Form(0),
    ceo_guarantee: str = Form(""), status: str = Form("활성"), note: str = Form(""),
):
    row = db.get(LoanMaster, lid)
    if not row: raise HTTPException(404)
    row.kind = kind or None; row.term = term or None
    row.institution = institution; row.account_no = account_no or None
    row.limit_amount = limit_amount or None; row.initial_amount = initial_amount or None
    row.current_balance = current_balance or None
    row.loan_type = loan_type or None; row.interest_rate = interest_rate or None
    row.repayment_method = repayment_method or None
    row.start_date = parse_date(start_date); row.end_date = parse_date(end_date)
    row.collateral = collateral or None; row.collateral_amount = collateral_amount or None
    row.ceo_guarantee = ceo_guarantee or None; row.status = status; row.note = note or None
    db.commit()
    return RedirectResponse("/loans", status_code=303)


@router.post("/{lid}/delete")
def delete_loan(lid: str, db: Session = Depends(get_db)):
    row = db.get(LoanMaster, lid)
    if row: db.delete(row); db.commit()
    return RedirectResponse("/loans", status_code=303)
