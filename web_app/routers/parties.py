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
from models import Party, Sale, Purchase, Product, Contract

router = APIRouter()


@router.get("", response_class=HTMLResponse)
def list_parties(
    request: Request, db: Session = Depends(get_db),
    q: str = "", category: str = "", active: str = "",
    sort: str = "name", dir: str = "asc",
    product: str = "",
    page: int = 1, per_page: int = 50,
):
    stmt = select(Party)
    if q: stmt = stmt.where(or_(Party.name.contains(q), Party.code.contains(q), Party.biz_no.contains(q)))
    if category: stmt = stmt.where(Party.category == category)
    if active: stmt = stmt.where(Party.active == active)
    if product: stmt = stmt.where(Party.main_product == product)

    # 정렬 가능 컬럼 매핑 (한글/영문/코드/최근거래 등)
    SORT_MAP = {
        "name": Party.name,          # 가나다 + ABC 자동 (SQLite COLLATE NOCASE는 한글은 unicode 순)
        "code": Party.code,
        "category": Party.category,
        "main_product": Party.main_product,
        "first_seen": Party.first_seen,
        "last_seen": Party.last_seen,
        "biz_no": Party.biz_no,
        "active": Party.active,
        "note": Party.note,
    }
    col = SORT_MAP.get(sort, Party.name)
    direction = "desc" if (dir or "").lower() == "desc" else "asc"
    order = col.desc() if direction == "desc" else col.asc()

    total_count = db.scalar(select(func.count()).select_from(stmt.subquery()))
    rows = db.execute(
        stmt.order_by(order, Party.code).offset((page - 1) * per_page).limit(per_page)
    ).scalars().all()

    # 빠른 그룹 카운트 (좌측 ㄱㄴㄷ/ABC 점프용)
    initials = []
    for r in db.execute(select(Party.name).where(Party.name.is_not(None))).all():
        n = r[0] or ""
        if not n: continue
        ch = n[0]
        # 한글 초성 추출 또는 첫 글자
        if "가" <= ch <= "힣":
            code = ord(ch) - ord("가")
            cho_idx = code // 588
            CHO = "ㄱㄲㄴㄷㄸㄹㅁㅂㅃㅅㅆㅇㅈㅉㅊㅋㅌㅍㅎ"
            initials.append(CHO[cho_idx])
        elif ch.isascii() and ch.isalpha():
            initials.append(ch.upper())
        else:
            initials.append("#")
    from collections import Counter
    init_counts = Counter(initials)

    products = db.execute(select(Product).order_by(Product.code)).scalars().all()
    categories = ["병원", "대리점", "공급사", "영상센터", "교육/연구", "금융", "법인기타", "기타"]
    return templates.TemplateResponse("parties/list.html", {
        "request": request, "rows": rows,
        "total_count": total_count, "categories": categories,
        "products": products,
        "init_counts": dict(init_counts.most_common()),
        "filter": {"q": q, "category": category, "active": active,
                   "sort": sort, "dir": direction, "product": product},
        "page": page, "per_page": per_page,
        "total_pages": (total_count + per_page - 1) // per_page,
    })


# ===== 다중 선택 일괄 삭제 — 동적 /{code} 라우트보다 먼저 정의 =====
@router.post("/bulk-delete")
async def bulk_delete_parties(request: Request, db: Session = Depends(get_db)):
    """체크된 거래처 코드 목록을 일괄 삭제. 자동 DB 백업 후 진행.
    매출/매입 거래 데이터(fact)는 삭제하지 않음 — 거래처 마스터(dim_party)만."""
    form = await request.form()
    codes = form.getlist("codes")
    back = (form.get("back") or "/parties").strip()
    if not back.startswith("/parties"):
        back = "/parties"
    from urllib.parse import quote
    if not codes:
        return RedirectResponse(back + ("&" if "?" in back else "?") +
                                "_msg=" + quote("삭제할 거래처가 선택되지 않았습니다"), status_code=303)

    # 자동 DB 백업
    import shutil
    from datetime import datetime as _dt
    from database import DB_PATH
    backup_dir = DB_PATH.parent / "db_backup"
    backup_dir.mkdir(parents=True, exist_ok=True)
    ts = _dt.now().strftime("%Y%m%d_%H%M%S")
    backup_path = backup_dir / f"pre_bulk_delete_party_{ts}.db"
    try:
        shutil.copy2(DB_PATH, backup_path)
    except Exception as e:
        return RedirectResponse(back + ("&" if "?" in back else "?") +
                                "_msg=" + quote(f"❌ 백업 실패 — 삭제 중단: {e}"), status_code=303)

    n_deleted = 0
    for code in codes:
        row = db.get(Party, code)
        if row:
            db.delete(row); n_deleted += 1
    db.commit()
    msg = f"✅ 거래처 {n_deleted}개 일괄 삭제 완료 (백업: {backup_path.name})"
    return RedirectResponse(back + ("&" if "?" in back else "?") + "_msg=" + quote(msg), status_code=303)


@router.get("/lookup", response_class=HTMLResponse)
def lookup_party(name: str, request: Request, db: Session = Depends(get_db)):
    """매출/매입 화면에서 거래처명을 클릭했을 때 — 등록돼 있으면 상세, 아니면 신규 등록 폼."""
    # 1) 정확 이름 매칭 우선
    party = db.execute(select(Party).where(Party.name == name)).scalar_one_or_none()
    if party:
        # 등록된 거래처 → 상세 페이지로 redirect
        return RedirectResponse(f"/parties/{party.code}", status_code=303)

    # 2) 미등록 — 매출/매입에서 추출한 정보로 사전 채움
    sale_info = db.execute(
        select(func.count(), func.coalesce(func.sum(Sale.supply), 0),
               func.min(Sale.txn_date), func.max(Sale.txn_date),
               func.max(Sale.party_code))
        .where(Sale.party_name == name)
    ).one()
    purchase_info = db.execute(
        select(func.count(), func.coalesce(func.sum(Purchase.supply), 0),
               func.min(Purchase.txn_date), func.max(Purchase.txn_date),
               func.max(Purchase.party_code))
        .where(Purchase.party_name == name)
    ).one()

    # 가장 흔한 제품 추출 (이 거래처와 관련된)
    top_product = db.execute(
        select(Sale.product_name, func.count().label("cnt"))
        .where(Sale.party_name == name, Sale.product_name.is_not(None))
        .group_by(Sale.product_name).order_by(func.count().desc()).limit(1)
    ).first()

    # 다음 가용 코드 생성
    last = db.execute(select(Party).order_by(Party.code.desc()).limit(1)).scalar_one_or_none()
    next_num = int(last.code[1:]) + 1 if last and last.code.startswith("C") else 1
    next_code = sale_info[4] or purchase_info[4] or f"C{next_num:04d}"

    extracted = {
        "name": name,
        "code": next_code,
        "main_product": top_product[0] if top_product else "",
        "sale_count": int(sale_info[0] or 0),
        "sale_sum": float(sale_info[1] or 0),
        "purchase_count": int(purchase_info[0] or 0),
        "purchase_sum": float(purchase_info[1] or 0),
        "first_seen": min(d for d in [sale_info[2], purchase_info[2]] if d) if (sale_info[2] or purchase_info[2]) else None,
        "last_seen": max(d for d in [sale_info[3], purchase_info[3]] if d) if (sale_info[3] or purchase_info[3]) else None,
    }
    return templates.TemplateResponse("parties/lookup_new.html", {
        "request": request, "extracted": extracted,
    })


@router.post("/quick-register")
def quick_register_party(
    db: Session = Depends(get_db),
    code: str = Form(...), name: str = Form(...),
    biz_no: str = Form(""), category: str = Form(""), main_product: str = Form(""),
    contact_person: str = Form(""), phone: str = Form(""), note: str = Form(""),
):
    """매출/매입의 거래처 정보 창에서 즉시 등록. 이미 코드 있으면 update."""
    row = db.get(Party, code)
    if row:
        # 기존 행 업데이트 (덮어쓰기, 빈 값은 제외)
        if name: row.name = name
        if biz_no: row.biz_no = biz_no
        if category: row.category = category
        if main_product: row.main_product = main_product
        if contact_person: row.contact_person = contact_person
        if phone: row.phone = phone
        if note: row.note = note
    else:
        db.add(Party(
            code=code, name=name, biz_no=biz_no or None, category=category or None,
            main_product=main_product or None, active="Y",
            contact_person=contact_person or None, phone=phone or None, note=note or None,
        ))
    db.commit()
    return RedirectResponse(f"/parties/{code}", status_code=303)


# ===== Excel 파일 기반 거래처 정보 자동 보강 =====
@router.get("/enrich", response_class=HTMLResponse)
def enrich_preview(request: Request, db: Session = Depends(get_db)):
    """매출·매입 원본 Excel에서 추출 가능한 거래처 정보 미리보기 (dry-run)."""
    from party_enrich import run_enrichment
    try:
        result = run_enrichment(db, dry_run=True)
    except Exception as e:
        result = {"error": f"{type(e).__name__}: {e}"}
    return templates.TemplateResponse("parties/enrich.html", {
        "request": request, "result": result, "dry_run": True,
    })


@router.post("/enrich")
def enrich_apply(db: Session = Depends(get_db)):
    """Excel에서 추출한 정보를 dim_party 빈 칸에 실제 적용."""
    from party_enrich import run_enrichment
    try:
        result = run_enrichment(db, dry_run=False)
        # 결과 요약 → 쿼리스트링으로 전달
        fc = result.get("fill_counts", {})
        msg = f"매칭 {result['matched']}건 · 갱신 {result['updated']}건 · " \
              f"사업자번호 {fc.get('biz_no',0)}, 담당자 {fc.get('contact_person',0)}, " \
              f"전화 {fc.get('phone',0)}, 휴대폰 {fc.get('mobile',0)}, " \
              f"이메일 {fc.get('email',0)}, 주소 {fc.get('address',0)}"
        from urllib.parse import quote
        return RedirectResponse(f"/parties?enriched={quote(msg)}", status_code=303)
    except Exception as e:
        from urllib.parse import quote
        return RedirectResponse(f"/parties?enrich_error={quote(str(e))}", status_code=303)


@router.get("/{code}", response_class=HTMLResponse)
def party_detail(
    code: str, request: Request, db: Session = Depends(get_db),
    year: int | None = None, month: int | None = None, tab: str = "all",
):
    """거래처 상세 — 마스터 정보 + 매출/매입 명세 + 연도/월 필터."""
    party = db.get(Party, code)
    if not party:
        raise HTTPException(404, f"거래처 코드 {code} 없음")

    # 연도 후보 추출
    year_rows = db.execute(
        select(Sale.year).where(Sale.party_code == code)
        .union(select(Purchase.year).where(Purchase.party_code == code))
        .order_by(Sale.year.desc())
    ).all()
    # name 기반도 함께 (party_code 없을 수 있음)
    year_rows_by_name = db.execute(
        select(Sale.year).where(Sale.party_name == party.name)
        .union(select(Purchase.year).where(Purchase.party_name == party.name))
    ).all()
    years_avail = sorted({r[0] for r in year_rows + year_rows_by_name if r[0]}, reverse=True)

    def filter_sale(stmt):
        # 거래처 매칭: code OR name (code가 비어 있을 수 있음)
        stmt = stmt.where(or_(Sale.party_code == code, Sale.party_name == party.name))
        if year: stmt = stmt.where(Sale.year == year)
        if month: stmt = stmt.where(Sale.month == month)
        return stmt

    def filter_purchase(stmt):
        stmt = stmt.where(or_(Purchase.party_code == code, Purchase.party_name == party.name))
        if year: stmt = stmt.where(Purchase.year == year)
        if month: stmt = stmt.where(Purchase.month == month)
        return stmt

    # 통계
    sale_summary = db.execute(filter_sale(
        select(func.count(), func.coalesce(func.sum(Sale.supply), 0), func.coalesce(func.sum(Sale.total), 0))
    )).one()
    purchase_summary = db.execute(filter_purchase(
        select(func.count(), func.coalesce(func.sum(Purchase.supply), 0), func.coalesce(func.sum(Purchase.total), 0))
    )).one()

    # 연도별 그래프 데이터
    sale_by_year = db.execute(filter_sale(
        select(Sale.year, func.coalesce(func.sum(Sale.supply), 0)).group_by(Sale.year).order_by(Sale.year)
    )).all()
    purchase_by_year = db.execute(filter_purchase(
        select(Purchase.year, func.coalesce(func.sum(Purchase.supply), 0)).group_by(Purchase.year).order_by(Purchase.year)
    )).all()

    # 명세 행 (탭별)
    sales_rows = db.execute(filter_sale(select(Sale)).order_by(Sale.txn_date.desc(), Sale.id.desc()).limit(200)).scalars().all() if tab in ("all", "sale") else []
    purchase_rows = db.execute(filter_purchase(select(Purchase)).order_by(Purchase.txn_date.desc(), Purchase.id.desc()).limit(200)).scalars().all() if tab in ("all", "purchase") else []

    # 계약 (Contract 모델에 party_name 기반 매칭)
    try:
        contracts = db.execute(select(Contract).where(Contract.party_name == party.name).order_by(Contract.start_date.desc().nullslast()).limit(50)).scalars().all()
    except Exception:
        contracts = []

    return templates.TemplateResponse("parties/detail.html", {
        "request": request, "party": party,
        "sale_summary": {"count": int(sale_summary[0] or 0), "supply": float(sale_summary[1] or 0), "total": float(sale_summary[2] or 0)},
        "purchase_summary": {"count": int(purchase_summary[0] or 0), "supply": float(purchase_summary[1] or 0), "total": float(purchase_summary[2] or 0)},
        "sale_by_year": [(y, float(v)) for y, v in sale_by_year],
        "purchase_by_year": [(y, float(v)) for y, v in purchase_by_year],
        "sales_rows": sales_rows, "purchase_rows": purchase_rows,
        "contracts": contracts,
        "years_avail": years_avail,
        "filter": {"year": year, "month": month, "tab": tab},
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
