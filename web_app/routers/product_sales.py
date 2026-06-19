# -*- coding: utf-8 -*-
"""제품별 매출 분석 — 기간·연도·월·분기·거래처별로 제품(상품) 매출 평가"""
from datetime import date, datetime
from fastapi import APIRouter, Request, Depends
from fastapi.responses import HTMLResponse
from sqlalchemy import select, func, or_
from sqlalchemy.orm import Session

from database import get_db
from helpers import templates
from models import Sale, Product

router = APIRouter()


def _parse_d(s):
    if not s:
        return None
    try:
        return datetime.strptime(s, "%Y-%m-%d").date()
    except Exception:
        return None


def _parse_i(s):
    if s is None or s == "":
        return None
    try:
        return int(s)
    except (ValueError, TypeError):
        return None


@router.get("", response_class=HTMLResponse)
@router.get("/", response_class=HTMLResponse)
def product_sales(request: Request, db: Session = Depends(get_db),
                  year: str = "", month: str = "", quarter: str = "",
                  from_date: str = "", to_date: str = "", party: str = ""):
    year_i = _parse_i(year)
    month_i = _parse_i(month)
    fd = _parse_d(from_date)
    td = _parse_d(to_date)

    conds = []
    if fd: conds.append(Sale.txn_date >= fd)
    if td: conds.append(Sale.txn_date <= td)
    if year_i: conds.append(Sale.year == year_i)
    if month_i: conds.append(Sale.month == month_i)
    if quarter: conds.append(Sale.quarter == quarter)
    if party: conds.append(Sale.party_name.contains(party))

    def W(stmt):
        return stmt.where(*conds) if conds else stmt

    # 전체 합계
    s_row = db.execute(W(select(
        func.coalesce(func.sum(Sale.supply), 0),
        func.coalesce(func.sum(Sale.vat), 0),
        func.coalesce(func.sum(Sale.total), 0),
        func.count(),
    ))).one()
    tot_supply, tot_vat, tot_total, tot_cnt = float(s_row[0] or 0), float(s_row[1] or 0), float(s_row[2] or 0), int(s_row[3] or 0)

    # 제품별 집계
    prod_rows = db.execute(
        W(select(
            Sale.product_code, Sale.product_name,
            func.count().label("cnt"),
            func.coalesce(func.sum(Sale.supply), 0).label("supply"),
            func.coalesce(func.sum(Sale.vat), 0).label("vat"),
            func.coalesce(func.sum(Sale.total), 0).label("total"),
        )).group_by(Sale.product_code, Sale.product_name)
        .order_by(func.sum(Sale.supply).desc())
    ).all()
    products = [{
        "code": r.product_code or "", "name": r.product_name or "기타",
        "count": r.cnt, "supply": float(r.supply or 0),
        "vat": float(r.vat or 0), "total": float(r.total or 0),
        "pct": (float(r.supply or 0) / tot_supply * 100) if tot_supply else 0,
    } for r in prod_rows]

    # 거래처별 TOP (선택된 필터 기준)
    party_rows = db.execute(
        W(select(
            Sale.party_name, func.count().label("cnt"),
            func.coalesce(func.sum(Sale.supply), 0).label("supply"),
        ).where(Sale.party_name.is_not(None)))
        .group_by(Sale.party_name).order_by(func.sum(Sale.supply).desc()).limit(15)
    ).all()
    parties = [{"name": r.party_name, "count": r.cnt, "supply": float(r.supply or 0)} for r in party_rows]

    # 제품 × 월 추이 (선택 연도, 없으면 당해)
    cy = year_i or datetime.now().year
    months_by_product = {}
    monthly_conds = [Sale.year == cy]
    if party: monthly_conds.append(Sale.party_name.contains(party))
    trend = db.execute(
        select(Sale.product_name, Sale.month, func.coalesce(func.sum(Sale.supply), 0))
        .where(*monthly_conds).group_by(Sale.product_name, Sale.month)
    ).all()
    for pname, m, sup in trend:
        months_by_product.setdefault(pname or "기타", [0] * 12)
        if m and 1 <= m <= 12:
            months_by_product[pname or "기타"][m - 1] = float(sup or 0)

    years = list(range(2021, datetime.now().year + 1))
    return templates.TemplateResponse("product_sales/list.html", {
        "request": request,
        "products": products, "parties": parties,
        "tot_supply": tot_supply, "tot_vat": tot_vat, "tot_total": tot_total, "tot_cnt": tot_cnt,
        "years": years, "trend_year": cy,
        "months_by_product": months_by_product,
        "filter": {"year": year_i, "month": month_i, "quarter": quarter,
                   "from_date": from_date, "to_date": to_date, "party": party},
    })
