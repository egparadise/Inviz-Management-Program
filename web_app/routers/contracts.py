# -*- coding: utf-8 -*-
"""계약 라우터 — 등록·수정 + 계약서 파일 업로드 + 표준 양식 + 전자서명(공급자/고객)"""
import uuid
from pathlib import Path
from datetime import date, datetime
from fastapi import APIRouter, Request, Form, Depends, HTTPException, UploadFile, File
from fastapi.responses import HTMLResponse, RedirectResponse, FileResponse, JSONResponse
from sqlalchemy import select, func, or_
from sqlalchemy.orm import Session

from database import get_db
from helpers import templates
from models import Contract, Party, Product

router = APIRouter()
esign_router = APIRouter()  # 고객 서명용 공개 라우터 (/esign — 로그인 불필요, main.py에서 include)

# 계약서 파일 저장 디렉토리
CONTRACT_FILE_DIR = Path(__file__).parent.parent / "contract_files"
CONTRACT_FILE_DIR.mkdir(parents=True, exist_ok=True)
ALLOWED_EXT = {".pdf", ".jpg", ".jpeg", ".png", ".gif", ".bmp", ".webp", ".hwp", ".doc", ".docx"}

# ===== 계약서 종류 + 표준 양식 =====
CONTRACT_TYPES = {
    "서비스 유지보수 계약": {
        "title": "서비스 유지보수 계약서",
        "articles": [
            ("제1조 (목적)", "본 계약은 을이 갑에게 제공한 시스템/소프트웨어에 대한 유지보수 서비스의 범위와 조건을 정함을 목적으로 한다."),
            ("제2조 (유지보수 범위)", "① 시스템 정기 점검 및 장애 대응\n② 소프트웨어 업데이트 및 패치 적용\n③ 원격/방문 기술 지원\n④ 데이터 백업 상태 점검"),
            ("제3조 (계약기간)", "계약기간은 {시작일}부터 {만료일}까지로 하며, 만료 1개월 전까지 별도 의사표시가 없으면 동일 조건으로 1년씩 자동 연장된다."),
            ("제4조 (유지보수료)", "월 유지보수료는 금 {계약금액}원(VAT 별도)으로 하며, 갑은 {대금지불} 기준으로 을에게 지급한다."),
            ("제5조 (장애 대응)", "을은 갑의 장애 접수 후 4시간 이내 대응을 개시하며, 중대 장애는 우선 처리한다."),
            ("제6조 (비밀유지)", "양 당사자는 본 계약 수행 중 알게 된 상대방의 기밀정보를 제3자에게 누설하지 않는다."),
            ("제7조 (계약해지)", "일방이 본 계약을 중대하게 위반한 경우 상대방은 서면 통보 후 30일 이내 시정되지 않으면 계약을 해지할 수 있다."),
        ],
    },
    "영업계약": {
        "title": "영업(판매대리) 계약서",
        "articles": [
            ("제1조 (목적)", "본 계약은 을의 제품/서비스에 대한 갑의 영업(판매대리) 활동의 범위와 수수료 조건을 정함을 목적으로 한다."),
            ("제2조 (영업 범위)", "갑은 을의 제품({품명})을 담당 지역 내 의료기관에 소개·판매하는 영업 활동을 수행한다."),
            ("제3조 (수수료)", "영업 수수료는 판매 계약 금액 기준으로 상호 합의한 요율을 적용하며, 세부 요율표는 별첨으로 한다."),
            ("제4조 (계약기간)", "계약기간은 {시작일}부터 {만료일}까지로 한다."),
            ("제5조 (정산)", "수수료 정산은 {대금지불} 기준으로 하며, 고객 입금 확인 후 지급한다."),
            ("제6조 (금지사항)", "갑은 을의 사전 서면 동의 없이 경쟁 제품을 취급하거나 을의 가격 정책을 위반할 수 없다."),
            ("제7조 (비밀유지·해지)", "양 당사자는 기밀을 유지하며, 중대 위반 시 서면 통보로 계약을 해지할 수 있다."),
        ],
    },
    "원격판독 계약": {
        "title": "원격판독 서비스 계약서",
        "articles": [
            ("제1조 (목적)", "본 계약은 을이 갑에게 제공하는 의료영상 원격판독 서비스의 범위와 조건을 정함을 목적으로 한다."),
            ("제2조 (서비스 범위)", "① 영상의학과 전문의에 의한 X-ray/CT/MRI 등 의료영상 판독\n② 판독 결과 리포트 제공 (Cloud Care Life 시스템)\n③ 응급 판독 우선 처리"),
            ("제3조 (판독료)", "판독료는 검사 종류별 단가표(별첨)에 따르며, 월 판독료는 약 금 {계약금액}원 수준으로 한다."),
            ("제4조 (계약기간)", "계약기간은 {시작일}부터 {만료일}까지로 하며, 자동 연장 조건은 {자동연장}으로 한다."),
            ("제5조 (정산·지급)", "판독료 정산은 {대금지불} 기준으로 하며, 을은 월별 판독 내역서를 제공한다."),
            ("제6조 (의료정보 보호)", "양 당사자는 의료법 및 개인정보보호법을 준수하며, 환자 정보를 판독 목적 외 사용하지 않는다."),
            ("제7조 (책임)", "판독 소견은 임상 참고용이며, 최종 진단 책임은 진료 의사에게 있다."),
        ],
    },
    "장비판매 계약": {
        "title": "의료장비 판매(공급) 계약서",
        "articles": [
            ("제1조 (목적)", "본 계약은 을이 갑에게 판매(공급)하는 의료장비의 사양·대금·설치 조건을 정함을 목적으로 한다."),
            ("제2조 (계약 품목)", "품목: {품명}\n수량 및 세부 사양은 별첨 견적서에 따른다."),
            ("제3조 (계약금액)", "총 계약금액은 금 {계약금액}원(VAT 별도)으로 하며, 지급 조건은 {대금지불}로 한다."),
            ("제4조 (납품·설치)", "을은 {설치일}까지 갑의 사업장에 장비를 납품·설치하고 정상 동작을 확인한다."),
            ("제5조 (검수)", "갑은 설치 완료 후 7일 이내 검수하며, 이 기간 내 이의가 없으면 검수 완료로 본다."),
            ("제6조 (하자보수)", "하자보수 기간은 설치일로부터 {하자보수만료}까지로 하며, 정상 사용 중 발생한 하자는 을이 무상 수리한다."),
            ("제7조 (소유권)", "장비의 소유권은 계약금액 완납 시 갑에게 이전된다."),
        ],
    },
    "인공지능 사용 계약": {
        "title": "인공지능(AI) 솔루션 사용 계약서",
        "articles": [
            ("제1조 (목적)", "본 계약은 을이 제공하는 AI 의료영상 분석 솔루션({품명})의 사용권 부여와 조건을 정함을 목적으로 한다."),
            ("제2조 (사용권)", "을은 갑에게 계약기간 동안 본 솔루션의 비독점적 사용권을 부여한다. 갑은 제3자에게 재판매·재라이선스할 수 없다."),
            ("제3조 (사용료)", "사용료는 금 {계약금액}원(VAT 별도, {대금지불} 기준)으로 한다."),
            ("제4조 (계약기간)", "계약기간은 {시작일}부터 {만료일}까지로 하며, 자동 연장 조건은 {자동연장}으로 한다."),
            ("제5조 (AI 결과의 성격)", "AI 분석 결과는 진단 보조 참고자료이며, 최종 판단 책임은 사용 의료인에게 있다."),
            ("제6조 (데이터)", "갑의 의료영상 데이터는 분석 목적으로만 처리되며, 을은 관련 법령에 따라 안전하게 관리한다."),
            ("제7조 (지식재산권)", "본 솔루션에 대한 일체의 지식재산권은 을에게 있다."),
        ],
    },
}


def parse_date(s):
    if not s: return None
    try: return datetime.strptime(s, "%Y-%m-%d").date()
    except: return None


def _save_contract_file(cid: str, file: UploadFile) -> tuple:
    """업로드 파일 저장 → (저장경로, 원본파일명). 확장자 검증."""
    if not file or not file.filename:
        return None, None
    ext = Path(file.filename).suffix.lower()
    if ext not in ALLOWED_EXT:
        raise HTTPException(400, f"허용되지 않는 파일 형식: {ext} (허용: {', '.join(sorted(ALLOWED_EXT))})")
    import re as _re
    safe_cid = _re.sub(r"[^\w\-]", "_", cid)
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    dest = CONTRACT_FILE_DIR / f"{safe_cid}_{ts}{ext}"
    data = file.file.read()
    if len(data) > 30 * 1024 * 1024:
        raise HTTPException(400, "파일이 30MB를 초과합니다")
    dest.write_bytes(data)
    return str(dest), file.filename


def _fill_template(text: str, row: Contract) -> str:
    """양식 placeholder를 계약 데이터로 치환."""
    def money(v):
        try: return f"{int(float(v or 0)):,}"
        except Exception: return "0"
    rep = {
        "{시작일}": str(row.start_date or "     년   월   일"),
        "{만료일}": str(row.end_date or "     년   월   일"),
        "{계약금액}": money(row.contract_amount),
        "{대금지불}": row.payment_term or "월별",
        "{품명}": row.item_name or (row.product_code or ""),
        "{자동연장}": ("자동 연장" if row.auto_renew == "Y" else "연장 없음(협의)"),
        "{설치일}": str(row.install_date or "협의된 일자"),
        "{하자보수만료}": str(row.warranty_end or "설치일로부터 12개월"),
    }
    for k, v in rep.items():
        text = text.replace(k, v)
    return text


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
    doc_kind: str = Form(""), file: UploadFile = File(None),
):
    if db.get(Contract, id): raise HTTPException(400, "계약ID 중복")
    end_d = parse_date(end_date)
    remain = (end_d - date.today()).days if end_d else None
    fpath, fname = _save_contract_file(id, file)
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
        doc_kind=doc_kind or None, file_path=fpath, file_name=fname,
        sign_token=uuid.uuid4().hex, sign_status="none",
    ))
    db.commit()
    return RedirectResponse(f"/contracts/{id}/sign" if doc_kind or fpath else "/contracts", status_code=303)


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
    doc_kind: str = Form(""), file: UploadFile = File(None),
):
    row = db.get(Contract, cid)
    if not row: raise HTTPException(404)
    row.doc_kind = doc_kind or row.doc_kind
    if file and file.filename:
        fpath, fname = _save_contract_file(cid, file)
        row.file_path = fpath; row.file_name = fname
    if not row.sign_token:
        row.sign_token = uuid.uuid4().hex
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
    if row:
        try:
            if row.file_path:
                Path(row.file_path).unlink(missing_ok=True)
        except Exception:
            pass
        db.delete(row); db.commit()
    return RedirectResponse("/contracts", status_code=303)


# ===================== 계약서 양식·파일·전자서명 =====================
@router.get("/api/template/{kind}")
def contract_template_api(kind: str):
    """계약서 종류 선택 시 표준 양식 미리보기 (JSON)."""
    t = CONTRACT_TYPES.get(kind)
    if not t:
        return JSONResponse({"ok": False, "kinds": list(CONTRACT_TYPES.keys())}, status_code=404)
    return {"ok": True, "kind": kind, "title": t["title"],
            "articles": [{"head": h, "body": b} for h, b in t["articles"]]}


@router.get("/{cid}/file")
def contract_file(cid: str, db: Session = Depends(get_db)):
    """업로드된 계약서 파일 보기/다운로드."""
    row = db.get(Contract, cid)
    if not row or not row.file_path or not Path(row.file_path).exists():
        raise HTTPException(404, "계약서 파일 없음")
    return FileResponse(row.file_path, filename=row.file_name or Path(row.file_path).name)


def _sign_context(row: Contract, db: Session, *, public: bool = False) -> dict:
    """서명 페이지 컨텍스트 — 양식 본문 채움 + 서명 상태."""
    doc = None
    if row.doc_kind and row.doc_kind in CONTRACT_TYPES:
        t = CONTRACT_TYPES[row.doc_kind]
        doc = {"title": t["title"],
               "articles": [{"head": h, "body": _fill_template(b, row)} for h, b in t["articles"]]}
    # 공급자(을) 정보 — 회사정보
    try:
        from models import CompanyInfo
        ci = db.get(CompanyInfo, 1)
        supplier = {"name": ci.name if ci else "(주)인비즈", "ceo": (ci.ceo if ci else "") or "",
                    "biz_no": (ci.biz_no if ci else "") or "", "address": (ci.address if ci else "") or ""}
    except Exception:
        supplier = {"name": "(주)인비즈", "ceo": "", "biz_no": "", "address": ""}
    file_ext = Path(row.file_path).suffix.lower() if row.file_path else ""
    return {"row": row, "doc": doc, "supplier": supplier, "public": public,
            "file_ext": file_ext,
            "is_image": file_ext in (".jpg", ".jpeg", ".png", ".gif", ".bmp", ".webp"),
            "is_pdf": file_ext == ".pdf"}


@router.get("/{cid}/sign", response_class=HTMLResponse)
def contract_sign_page(cid: str, request: Request, db: Session = Depends(get_db)):
    """전자계약 서명 페이지 (내부용 — 공급자·고객 모두 서명 가능)."""
    row = db.get(Contract, cid)
    if not row:
        raise HTTPException(404)
    if not row.sign_token:
        row.sign_token = uuid.uuid4().hex; db.commit()
    ctx = _sign_context(row, db, public=False)
    ctx["request"] = request
    return templates.TemplateResponse("contracts/sign.html", ctx)


def _apply_sign(row: Contract, role: str, signer: str, sign_data: str) -> str:
    if role == "supplier":
        row.supplier_sign = sign_data; row.supplier_signer = signer or "공급자"
        row.supplier_signed_at = datetime.now()
    else:
        row.customer_sign = sign_data; row.customer_signer = signer or "고객"
        row.customer_signed_at = datetime.now()
    both = bool(row.supplier_sign) and bool(row.customer_sign)
    row.sign_status = "complete" if both else "partial"
    return row.sign_status


@router.post("/{cid}/sign")
def contract_sign_save(cid: str, db: Session = Depends(get_db),
                       role: str = Form(...), signer: str = Form(""),
                       sign_data: str = Form(...)):
    row = db.get(Contract, cid)
    if not row:
        raise HTTPException(404)
    if role not in ("supplier", "customer"):
        raise HTTPException(400, "role must be supplier|customer")
    if not sign_data.startswith("data:image/"):
        raise HTTPException(400, "서명 데이터 형식 오류")
    st = _apply_sign(row, role, signer, sign_data)
    db.commit()
    return {"ok": True, "sign_status": st,
            "signed_at": datetime.now().strftime("%Y-%m-%d %H:%M")}


# ===================== 고객 서명 공개 링크 (/esign — 로그인 불필요) =====================
def _find_by_token(db: Session, token: str) -> Contract:
    row = db.execute(select(Contract).where(Contract.sign_token == token).limit(1)).scalar_one_or_none()
    if not row:
        raise HTTPException(404, "유효하지 않은 서명 링크입니다")
    return row


@esign_router.get("/{token}", response_class=HTMLResponse)
def esign_page(token: str, request: Request, db: Session = Depends(get_db)):
    """고객용 서명 페이지 — 토큰 링크로 접속, 고객 서명만 가능."""
    row = _find_by_token(db, token)
    ctx = _sign_context(row, db, public=True)
    ctx["request"] = request
    return templates.TemplateResponse("contracts/sign.html", ctx)


@esign_router.post("/{token}/sign")
def esign_save(token: str, db: Session = Depends(get_db),
               signer: str = Form(""), sign_data: str = Form(...)):
    row = _find_by_token(db, token)
    if not sign_data.startswith("data:image/"):
        raise HTTPException(400, "서명 데이터 형식 오류")
    st = _apply_sign(row, "customer", signer, sign_data)  # 공개 링크는 고객 서명만
    db.commit()
    return {"ok": True, "sign_status": st,
            "signed_at": datetime.now().strftime("%Y-%m-%d %H:%M")}


@esign_router.get("/{token}/file")
def esign_file(token: str, db: Session = Depends(get_db)):
    """고객 서명 페이지에서 첨부 계약서 파일 열람 (토큰 검증)."""
    row = _find_by_token(db, token)
    if not row.file_path or not Path(row.file_path).exists():
        raise HTTPException(404, "계약서 파일 없음")
    return FileResponse(row.file_path, filename=row.file_name or Path(row.file_path).name)
