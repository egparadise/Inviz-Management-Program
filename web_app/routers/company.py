# -*- coding: utf-8 -*-
"""회사 기본정보 라우터 — 조회·수정 (주소·대표자·임원·임직원수·자본금·주주현황 등)

단일 행(id=1)으로 관리. 보고서 placeholder가 이 정보를 참조한다.
"""
import json
from datetime import datetime
from fastapi import APIRouter, Request, Form, Depends
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy import select
from sqlalchemy.orm import Session

from database import get_db
from helpers import templates
from models import CompanyInfo, Employee

router = APIRouter()


def employee_counts(db: Session) -> dict:
    """직원 마스터(dim_employee) 실시간 집계 — 재직/전체."""
    from sqlalchemy import func
    total = db.scalar(select(func.count()).select_from(Employee)) or 0
    active = db.scalar(select(func.count()).select_from(Employee)
                       .where(Employee.active.in_(["재직", "Y"]))) or 0
    return {"active": int(active), "total": int(total)}


def get_or_create_company(db: Session) -> CompanyInfo:
    """회사정보 단일 행 조회. 없으면 기본값으로 생성."""
    ci = db.get(CompanyInfo, 1)
    if not ci:
        ci = CompanyInfo(
            id=1, name="(주)인비즈", name_en="Inviz Corporation",
            ceo="박성철", industry="의료 영상 IT (원격판독·PACS·AI)",
            executives_json="[]", shareholders_json="[]",
        )
        db.add(ci); db.commit(); db.refresh(ci)
    return ci


@router.get("", response_class=HTMLResponse)
@router.get("/", response_class=HTMLResponse)
def company_view(request: Request, db: Session = Depends(get_db), edit: str = ""):
    ci = get_or_create_company(db)
    try:
        executives = json.loads(ci.executives_json or "[]")
    except Exception:
        executives = []
    try:
        shareholders = json.loads(ci.shareholders_json or "[]")
    except Exception:
        shareholders = []
    emp = employee_counts(db)
    return templates.TemplateResponse("company/view.html", {
        "request": request, "ci": ci,
        "executives": executives, "shareholders": shareholders,
        "edit": edit == "1",
        "emp_active": emp["active"], "emp_total": emp["total"],
    })


@router.post("/save")
async def company_save(request: Request, db: Session = Depends(get_db)):
    ci = get_or_create_company(db)
    form = await request.form()

    def g(key, default=None):
        v = form.get(key)
        return v.strip() if isinstance(v, str) else default

    ci.name = g("name") or ci.name
    ci.name_en = g("name_en")
    ci.biz_no = g("biz_no")
    ci.corp_no = g("corp_no")
    ci.ceo = g("ceo")
    ci.established = g("established")
    ci.address = g("address")
    ci.phone = g("phone")
    ci.fax = g("fax")
    ci.email = g("email")
    ci.website = g("website")
    ci.industry = g("industry")
    ci.note = g("note")
    # 숫자
    try:
        cap = (g("capital") or "0").replace(",", "")
        ci.capital = float(cap) if cap else 0
    except Exception:
        ci.capital = 0
    try:
        emp = (g("employee_count") or "0").replace(",", "")
        ci.employee_count = int(float(emp)) if emp else 0
    except Exception:
        ci.employee_count = 0

    # 임원 — 병렬 배열(exec_name[], exec_title[], exec_note[])
    exec_names = form.getlist("exec_name")
    exec_titles = form.getlist("exec_title")
    exec_notes = form.getlist("exec_note")
    executives = []
    for i, nm in enumerate(exec_names):
        nm = (nm or "").strip()
        if not nm:
            continue
        executives.append({
            "name": nm,
            "title": (exec_titles[i].strip() if i < len(exec_titles) else ""),
            "note": (exec_notes[i].strip() if i < len(exec_notes) else ""),
        })
    ci.executives_json = json.dumps(executives, ensure_ascii=False)

    # 주주 — sh_name[], sh_shares[], sh_ratio[], sh_note[]
    sh_names = form.getlist("sh_name")
    sh_shares = form.getlist("sh_shares")
    sh_ratios = form.getlist("sh_ratio")
    sh_notes = form.getlist("sh_note")
    shareholders = []
    for i, nm in enumerate(sh_names):
        nm = (nm or "").strip()
        if not nm:
            continue
        shareholders.append({
            "name": nm,
            "shares": (sh_shares[i].strip() if i < len(sh_shares) else ""),
            "ratio": (sh_ratios[i].strip() if i < len(sh_ratios) else ""),
            "note": (sh_notes[i].strip() if i < len(sh_notes) else ""),
        })
    ci.shareholders_json = json.dumps(shareholders, ensure_ascii=False)

    db.commit()
    return RedirectResponse("/company?saved=1", status_code=303)
