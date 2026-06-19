# -*- coding: utf-8 -*-
"""인비즈 경영관리 웹 — FastAPI 메인"""
from pathlib import Path
from datetime import datetime, date
from fastapi import FastAPI, Request, Form, Depends, HTTPException
from fastapi.responses import HTMLResponse, RedirectResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from sqlalchemy import func, select, and_, or_
from sqlalchemy.orm import Session

from database import get_db, init_db, DB_PATH
from auth import login, logout, verify_session_token, SESSION_COOKIE, SHARED_PASSWORD
from helpers import templates
from models import (Party, Product, Account, Employee, Department,
                    Sale, Purchase, Payroll, Expense, Receivable, Loan, Rental,
                    Severance, Contract, LoanMaster, ProductMapping, AuditLog)

ROOT = Path(__file__).parent

app = FastAPI(title="인비즈 경영관리", docs_url="/api/docs")
app.mount("/static", StaticFiles(directory=str(ROOT / "static")), name="static")

init_db()

# 자동 실행 스케줄러 시작 (동기화 / AI 학습 / 자가발전)
try:
    import scheduler
    scheduler.start()
except Exception as e:
    print(f"[main] 스케줄러 시작 실패: {e}")


# ===== 인증 미들웨어 + 활동 로그 =====
@app.middleware("http")
async def auth_middleware(request: Request, call_next):
    import time as _t
    import activity
    PUBLIC_PATHS = {"/login", "/static", "/api/docs", "/openapi.json", "/api/health"}
    path = request.url.path
    is_public = any(path == p or path.startswith(p + "/") for p in PUBLIC_PATHS)
    if not is_public:
        token = request.cookies.get(SESSION_COOKIE)
        if not token or not verify_session_token(token):
            return RedirectResponse("/login", status_code=303)
    t0 = _t.time()
    response = await call_next(request)
    # 활동 로그 기록
    try:
        if activity.should_log(request.method, path):
            client_ip = request.client.host if request.client else None
            activity.log_activity(
                request.method, path, getattr(response, "status_code", None),
                client_ip, duration_ms=int((_t.time() - t0) * 1000),
            )
    except Exception:
        pass
    return response


# ===== 인증 라우트 =====
@app.get("/login", response_class=HTMLResponse)
def login_page(request: Request, error: str = ""):
    return templates.TemplateResponse("login.html", {"request": request, "error": error})


@app.post("/login")
def login_action(request: Request, password: str = Form(...)):
    response = RedirectResponse("/", status_code=303)
    if login(response, password):
        return response
    return RedirectResponse("/login?error=1", status_code=303)


@app.get("/logout")
def logout_action():
    response = RedirectResponse("/login", status_code=303)
    logout(response)
    return response


@app.get("/api/health")
def health():
    return {"status": "ok", "ts": datetime.now().isoformat()}


# ===== 대시보드 =====
@app.get("/", response_class=HTMLResponse)
def dashboard(request: Request, db: Session = Depends(get_db)):
    # KPI 집계
    current_year = datetime.now().year

    def year_sum(model, field_name, year):
        col = getattr(model, field_name)
        return db.scalar(select(func.coalesce(func.sum(col), 0)).where(model.year == year)) or 0

    years_data = {}
    for y in range(2021, current_year + 1):
        years_data[y] = {
            "sales": year_sum(Sale, "supply", y),
            "purchases": year_sum(Purchase, "supply", y),
            "payroll": year_sum(Payroll, "gross_pay", y),
            "expense": year_sum(Expense, "amount", y),
        }
        years_data[y]["gross"] = years_data[y]["sales"] - years_data[y]["purchases"]
        years_data[y]["operating"] = years_data[y]["gross"] - years_data[y]["payroll"] - years_data[y]["expense"]
        years_data[y]["margin"] = (years_data[y]["gross"] / years_data[y]["sales"] * 100) if years_data[y]["sales"] else 0

    # 월별 (당해)
    months_data = []
    for m in range(1, 13):
        s = db.scalar(select(func.coalesce(func.sum(Sale.supply), 0)).where(Sale.year == current_year, Sale.month == m)) or 0
        p = db.scalar(select(func.coalesce(func.sum(Purchase.supply), 0)).where(Purchase.year == current_year, Purchase.month == m)) or 0
        months_data.append({"month": m, "sales": float(s), "purchases": float(p)})

    # 제품별 매출 (당해)
    product_data = db.execute(
        select(Sale.product_code, Sale.product_name, func.sum(Sale.supply).label("total"))
        .where(Sale.year == current_year)
        .group_by(Sale.product_code, Sale.product_name)
        .order_by(func.sum(Sale.supply).desc())
    ).all()

    # 거래처 TOP10 매출 (당해)
    top_parties = db.execute(
        select(Sale.party_name, func.sum(Sale.supply).label("total"))
        .where(Sale.year == current_year, Sale.party_name.isnot(None))
        .group_by(Sale.party_name)
        .order_by(func.sum(Sale.supply).desc())
        .limit(10)
    ).all()

    # 차입금 합계
    loan_summary = db.execute(
        select(LoanMaster.kind,
               func.count().label("cnt"),
               func.coalesce(func.sum(LoanMaster.current_balance), 0).label("balance"))
        .group_by(LoanMaster.kind)
    ).all()

    # 미수금 잔액 (거래처별)
    ar_balance = db.execute(
        select(Receivable.party_name,
               func.sum(Receivable.invoice_amount).label("invoiced"),
               func.sum(Receivable.paid_amount).label("paid"))
        .group_by(Receivable.party_name)
    ).all()
    ar_top = sorted(
        [{"name": r.party_name, "invoiced": float(r.invoiced or 0),
          "paid": float(r.paid or 0), "balance": float((r.invoiced or 0) - (r.paid or 0))}
         for r in ar_balance],
        key=lambda x: x["balance"], reverse=True,
    )[:10]

    # 계약 현황
    contracts_by_status = db.execute(
        select(Contract.status, func.count(), func.coalesce(func.sum(Contract.contract_amount), 0))
        .group_by(Contract.status)
    ).all()

    return templates.TemplateResponse("dashboard.html", {
        "request": request,
        "current_year": current_year,
        "years_data": years_data,
        "months_data": months_data,
        "product_data": [(r[0], r[1], float(r[2] or 0)) for r in product_data],
        "top_parties": [(r[0], float(r[1] or 0)) for r in top_parties],
        "loan_summary": [(r[0], r[1], float(r[2] or 0)) for r in loan_summary],
        "ar_top": ar_top,
        "contracts_by_status": [(r[0], r[1], float(r[2] or 0)) for r in contracts_by_status],
    })


# ===== 라우터 등록 =====
from routers import (sales, purchases, parties, products, contracts, payroll,
                     loans, employees, sync, documents, chat, knowledge, self_dev,
                     ai_classify, reports, company, settings as settings_router,
                     product_sales, tax, calendar as calendar_router, banking, expense)
app.include_router(sales.router, prefix="/sales", tags=["매출"])
app.include_router(purchases.router, prefix="/purchases", tags=["매입"])
app.include_router(expense.router, prefix="/expense", tags=["지출"])
app.include_router(product_sales.router, prefix="/product-sales", tags=["제품별매출"])
app.include_router(parties.router, prefix="/parties", tags=["거래처"])
app.include_router(products.router, prefix="/products", tags=["제품"])
app.include_router(contracts.router, prefix="/contracts", tags=["계약"])
app.include_router(payroll.router, prefix="/payroll", tags=["급여"])
app.include_router(loans.router, prefix="/loans", tags=["차입금"])
app.include_router(banking.router, prefix="/banking", tags=["자금/계좌"])
app.include_router(employees.router, prefix="/employees", tags=["직원"])
app.include_router(sync.router, prefix="/sync", tags=["동기화"])
app.include_router(documents.router, prefix="/documents", tags=["서류"])
app.include_router(chat.router, prefix="/chat", tags=["챗"])
app.include_router(knowledge.router, prefix="/knowledge", tags=["지식베이스"])
app.include_router(self_dev.router, prefix="/self-dev", tags=["자가발전"])
app.include_router(ai_classify.router, prefix="/ai-classify", tags=["AI 자동 분류"])
app.include_router(reports.router, prefix="/reports", tags=["보고서"])
app.include_router(tax.router, prefix="/tax", tags=["세금계산서"])
app.include_router(calendar_router.router, prefix="/calendar", tags=["캘린더"])
app.include_router(company.router, prefix="/company", tags=["회사정보"])
app.include_router(settings_router.router, prefix="/settings", tags=["설정"])


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=False)
