# -*- coding: utf-8 -*-
"""거래처 라우터"""
from pathlib import Path
from datetime import date
from fastapi import APIRouter, Request, Form, Depends, HTTPException
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy import select, func, or_
from sqlalchemy.orm import Session

from database import get_db
from helpers import templates
from models import Party

router = APIRouter()


@router.get("", response_class=HTMLResponse)
def list_parties(
    request: Request, db: Session = Depends(get_db),
    q: str = "", category: str = "", active: str = "",
    page: int = 1, per_page: int = 50,
):
    stmt = select(Party)
    if q: stmt = stmt.where(or_(Party.name.contains(q), Party.code.contains(q), Party.biz_no.contains(q)))
    if category: stmt = stmt.where(Party.category == category)
    if active: stmt = stmt.where(Party.active == active)

    total_count = db.scalar(select(func.count()).select_from(stmt.subquery()))
    rows = db.execute(
        stmt.order_by(Party.name).offset((page - 1) * per_page).limit(per_page)
    ).scalars().all()

    categories = ["병원", "대리점", "공급사", "영상센터", "교육/연구", "금융", "법인기타", "기타"]
    return templates.TemplateResponse("parties/list.html", {
        "request": request, "rows": rows,
        "total_count": total_count, "categories": categories,
        "filter": {"q": q, "category": category, "active": active},
        "page": page, "per_page": per_page,
        "total_pages": (total_count + per_page - 1) // per_page,
    })


@router.get("/new", response_class=HTMLResponse)
def new_form(request: Request, db: Session = Depends(get_db)):
    # 다음 코드 생성
    last = db.execute(select(Party).order_by(Party.code.desc()).limit(1)).scalar_one_or_none()
    next_num = int(last.code[1:]) + 1 if last and last.code.startswith("C") else 1
    return templates.TemplateResponse("parties/form.html", {
        "request": request, "row": None, "next_code": f"C{next_num:04d}",
    })


@router.post("")
def create_party(
    db: Session = Depends(get_db),
    code: str = Form(...), name: str = Form(...),
    biz_no: str = Form(""), category: str = Form(""), main_product: str = Form(""),
    active: str = Form("Y"), contact_person: str = Form(""), phone: str = Form(""),
    note: str = Form(""),
):
    if db.get(Party, code):
        raise HTTPException(400, f"거래처코드 {code} 이미 존재")
    db.add(Party(
        code=code, name=name, biz_no=biz_no or None, category=category or None,
        main_product=main_product or None, active=active,
        contact_person=contact_person or None, phone=phone or None, note=note or None,
    ))
    db.commit()
    return RedirectResponse("/parties", status_code=303)


@router.get("/{code}/edit", response_class=HTMLResponse)
def edit_form(code: str, request: Request, db: Session = Depends(get_db)):
    row = db.get(Party, code)
    if not row: raise HTTPException(404)
    return templates.TemplateResponse("parties/form.html", {"request": request, "row": row, "next_code": code})


@router.post("/{code}")
def update_party(
    code: str, db: Session = Depends(get_db),
    name: str = Form(...), biz_no: str = Form(""), category: str = Form(""),
    main_product: str = Form(""), active: str = Form("Y"),
    contact_person: str = Form(""), phone: str = Form(""), note: str = Form(""),
):
    row = db.get(Party, code)
    if not row: raise HTTPException(404)
    row.name = name; row.biz_no = biz_no or None; row.category = category or None
    row.main_product = main_product or None; row.active = active
    row.contact_person = contact_person or None; row.phone = phone or None; row.note = note or None
    db.commit()
    return RedirectResponse("/parties", status_code=303)


@router.post("/{code}/delete")
def delete_party(code: str, db: Session = Depends(get_db)):
    row = db.get(Party, code)
    if row: db.delete(row); db.commit()
    return RedirectResponse("/parties", status_code=303)


# API: 자동완성용
@router.get("/api/search")
def search_api(q: str = "", db: Session = Depends(get_db), limit: int = 20):
    rows = db.execute(
        select(Party).where(or_(Party.name.contains(q), Party.code.contains(q))).limit(limit)
    ).scalars().all()
    return [{"code": r.code, "name": r.name, "category": r.category} for r in rows]
