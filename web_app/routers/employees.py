# -*- coding: utf-8 -*-
"""직원 라우터"""
from pathlib import Path
from datetime import datetime
from fastapi import APIRouter, Request, Form, Depends, HTTPException
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy import select, func, or_
from sqlalchemy.orm import Session

from database import get_db
from helpers import templates
from models import Employee

router = APIRouter()


def parse_date(s):
    if not s: return None
    try: return datetime.strptime(s, "%Y-%m-%d").date()
    except: return None


# 정렬 가능한 컬럼 매핑
SORT_COLS = {
    "code": Employee.code, "name": Employee.name, "department": Employee.department,
    "rank": Employee.rank, "employment_type": Employee.employment_type,
    "hire_date": Employee.hire_date, "resign_date": Employee.resign_date,
    "active": Employee.active, "base_salary": Employee.base_salary,
    "pension_enrolled": Employee.pension_enrolled,
}


@router.post("/bulk-delete")
async def bulk_delete_employees(request: Request, db: Session = Depends(get_db)):
    """체크된 사번 목록을 일괄 삭제. 자동 DB 백업 후 진행.
    동적 라우터 `/{code}`보다 앞에 정의해야 매칭 우선됨."""
    form = await request.form()
    codes = form.getlist("codes")
    if not codes:
        return RedirectResponse("/employees?_msg=" + "삭제할 항목이 선택되지 않았습니다", status_code=303)

    import shutil
    from datetime import datetime as _dt
    from database import DB_PATH
    backup_dir = DB_PATH.parent / "db_backup"
    backup_dir.mkdir(parents=True, exist_ok=True)
    ts = _dt.now().strftime("%Y%m%d_%H%M%S")
    backup_path = backup_dir / f"pre_bulk_delete_employee_{ts}.db"
    try:
        shutil.copy2(DB_PATH, backup_path)
    except Exception as e:
        return RedirectResponse("/employees?_msg=" + f"백업 실패 - 삭제 중단: {e}", status_code=303)

    n_deleted = 0
    for code in codes:
        row = db.get(Employee, code)
        if row:
            db.delete(row); n_deleted += 1
    db.commit()
    msg = f"✅ {n_deleted}명 일괄 삭제 완료 (백업: {backup_path.name})"
    return RedirectResponse("/employees?_msg=" + msg, status_code=303)


@router.get("", response_class=HTMLResponse)
def list_employees(request: Request, db: Session = Depends(get_db),
                   q: str = "", active: str = "", department: str = "",
                   sort: str = "code", dir: str = "asc"):
    stmt = select(Employee)
    if q: stmt = stmt.where(or_(Employee.name.contains(q), Employee.code.contains(q)))
    if active: stmt = stmt.where(Employee.active == active)
    if department: stmt = stmt.where(Employee.department == department)

    # 정렬 (컬럼 머리글 클릭) — 성명은 가나다(자음)순, 일자/급여 등 지원
    col = SORT_COLS.get(sort, Employee.code)
    order = col.asc() if dir != "desc" else col.desc()
    try:
        order = order.nullslast()
    except Exception:
        pass
    rows = db.execute(stmt.order_by(order, Employee.code)).scalars().all()

    depts = sorted(set([r.department for r in db.execute(select(Employee)).scalars().all() if r.department]))
    return templates.TemplateResponse("employees/list.html", {
        "request": request, "rows": rows, "departments": depts,
        "filter": {"q": q, "active": active, "department": department},
        "sort": sort, "dir": dir,
    })


@router.get("/new", response_class=HTMLResponse)
def new_form(request: Request):
    return templates.TemplateResponse("employees/form.html", {"request": request, "row": None})


@router.post("")
def create_employee(
    db: Session = Depends(get_db),
    code: str = Form(...), name: str = Form(...),
    department: str = Form(""), rank: str = Form(""), employment_type: str = Form("정규"),
    hire_date: str = Form(""), resign_date: str = Form(""), active: str = Form("재직"),
    base_salary: float = Form(0), pension_enrolled: str = Form("Y"), note: str = Form(""),
    email: str = Form(""), birth_date: str = Form(""), salary_annual: str = Form("N"),
):
    if db.get(Employee, code): raise HTTPException(400, "사번 중복")
    db.add(Employee(
        code=code, name=name, department=department or None, rank=rank or None,
        employment_type=employment_type or None,
        hire_date=parse_date(hire_date), resign_date=parse_date(resign_date),
        active=active, base_salary=base_salary or None,
        salary_annual="Y" if salary_annual == "Y" else "N",
        pension_enrolled=pension_enrolled, email=email or None,
        birth_date=parse_date(birth_date), note=note or None,
    ))
    db.commit()
    return RedirectResponse("/employees", status_code=303)


@router.get("/{code}/edit", response_class=HTMLResponse)
def edit_form(code: str, request: Request, db: Session = Depends(get_db)):
    row = db.get(Employee, code)
    if not row: raise HTTPException(404)
    return templates.TemplateResponse("employees/form.html", {"request": request, "row": row})


@router.post("/{code}")
def update_employee(
    code: str, db: Session = Depends(get_db),
    name: str = Form(...),
    department: str = Form(""), rank: str = Form(""), employment_type: str = Form("정규"),
    hire_date: str = Form(""), resign_date: str = Form(""), active: str = Form("재직"),
    base_salary: float = Form(0), pension_enrolled: str = Form("Y"), note: str = Form(""),
    email: str = Form(""), birth_date: str = Form(""), salary_annual: str = Form("N"),
):
    row = db.get(Employee, code)
    if not row: raise HTTPException(404)
    row.name = name; row.department = department or None
    row.rank = rank or None; row.employment_type = employment_type or None
    row.hire_date = parse_date(hire_date); row.resign_date = parse_date(resign_date)
    row.active = active; row.base_salary = base_salary or None
    row.salary_annual = "Y" if salary_annual == "Y" else "N"
    row.pension_enrolled = pension_enrolled; row.email = email or None
    row.birth_date = parse_date(birth_date) or row.birth_date; row.note = note or None
    db.commit()
    return RedirectResponse("/employees", status_code=303)


@router.post("/{code}/delete")
def delete_employee(code: str, db: Session = Depends(get_db)):
    row = db.get(Employee, code)
    if row: db.delete(row); db.commit()
    return RedirectResponse("/employees", status_code=303)
