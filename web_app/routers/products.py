# -*- coding: utf-8 -*-
"""제품 라우터"""
from pathlib import Path
from fastapi import APIRouter, Request, Form, Depends, HTTPException
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy import select
from sqlalchemy.orm import Session

from database import get_db
from helpers import templates
from models import Product, ProductMapping

router = APIRouter()


@router.get("", response_class=HTMLResponse)
def list_products(request: Request, db: Session = Depends(get_db)):
    rows = db.execute(select(Product).order_by(Product.code)).scalars().all()
    mappings = db.execute(select(ProductMapping).order_by(ProductMapping.priority, ProductMapping.pattern)).scalars().all()
    return templates.TemplateResponse("products/list.html", {"request": request, "rows": rows, "mappings": mappings})


@router.get("/new", response_class=HTMLResponse)
def new_form(request: Request):
    return templates.TemplateResponse("products/form.html", {"request": request, "row": None})


@router.post("")
def create_product(
    db: Session = Depends(get_db),
    code: str = Form(...), name: str = Form(...),
    category: str = Form(""), group: str = Form(""),
    unit_basis: str = Form(""), note: str = Form(""),
):
    if db.get(Product, code):
        raise HTTPException(400, "코드 중복")
    db.add(Product(code=code, name=name, category=category or None, group=group or None,
                   unit_basis=unit_basis or None, note=note or None))
    db.commit()
    return RedirectResponse("/products", status_code=303)


@router.get("/{code}/edit", response_class=HTMLResponse)
def edit_form(code: str, request: Request, db: Session = Depends(get_db)):
    row = db.get(Product, code)
    if not row: raise HTTPException(404)
    return templates.TemplateResponse("products/form.html", {"request": request, "row": row})


@router.post("/{code}")
def update_product(
    code: str, db: Session = Depends(get_db),
    name: str = Form(...), category: str = Form(""), group: str = Form(""),
    unit_basis: str = Form(""), note: str = Form(""),
):
    row = db.get(Product, code)
    if not row: raise HTTPException(404)
    row.name = name; row.category = category or None; row.group = group or None
    row.unit_basis = unit_basis or None; row.note = note or None
    db.commit()
    return RedirectResponse("/products", status_code=303)


@router.post("/{code}/delete")
def delete_product(code: str, db: Session = Depends(get_db)):
    row = db.get(Product, code)
    if row: db.delete(row); db.commit()
    return RedirectResponse("/products", status_code=303)


# 제품매핑 관리
@router.post("/mappings")
def add_mapping(
    db: Session = Depends(get_db),
    priority: int = Form(10), pattern: str = Form(...),
    product_code: str = Form(...), product_name: str = Form(...),
    default_sale_type: str = Form(""), note: str = Form(""),
):
    db.add(ProductMapping(
        priority=priority, pattern=pattern, product_code=product_code,
        product_name=product_name, default_sale_type=default_sale_type or None, note=note or None,
    ))
    db.commit()
    return RedirectResponse("/products", status_code=303)


@router.post("/mappings/{mid}/delete")
def delete_mapping(mid: int, db: Session = Depends(get_db)):
    row = db.get(ProductMapping, mid)
    if row: db.delete(row); db.commit()
    return RedirectResponse("/products", status_code=303)
