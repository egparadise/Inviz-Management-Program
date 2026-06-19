# -*- coding: utf-8 -*-
"""서류·인증 관리 라우터 — 카테고리별 세분화 + 연도별 관리

페이지 구조
- /documents                  — 허브(카테고리 카드 + 만료임박 요약)
- /documents/cat/{category}    — 카테고리별 목록 (연도별 그룹/필터, 검색, 스캔, 등록)
- /documents/contracts         — 고객 계약서(제품별) : master_contract 재사용, 연도별
- /documents/scan              — 폴더 자동 스캔(+카테고리 자동분류)
- /documents/recategorize      — 규칙 기반 재분류(미분류 보정)
- /documents/{id}/download|view|edit|delete, /new, POST /
"""
import os
import re
import shutil
import mimetypes
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Optional
from fastapi import APIRouter, Request, Form, Depends, HTTPException, UploadFile, File
from fastapi.responses import HTMLResponse, RedirectResponse, FileResponse
from sqlalchemy import select, func, or_
from sqlalchemy.orm import Session

from database import get_db
from helpers import templates
from models import Document, Contract

router = APIRouter()

def _scan_root() -> Path:
    """스캔 루트: settings.base_data_folder의 부모(14.경영정보) → base 자체 → 기본 fallback."""
    try:
        import settings_store as ss
        bf = (ss.get("base_data_folder", "") or "").strip()
        if bf:
            p = Path(bf)
            if p.exists():
                parent = p.parent
                if parent.exists() and ("경영정보" in parent.name or "Inviz" in parent.name):
                    return parent
                return p
    except Exception:
        pass
    return Path(r"C:\Users\inviz\OneDrive - Inviz (1)\5.Inviz_Corporation\14.경영정보")


# 호환: ROOT 자리표시 — 사용 시점에 _scan_root() 호출
ROOT = _scan_root()
UPLOAD_DIR = Path(__file__).resolve().parent.parent / "doc_uploads"  # 수동 업로드 보관

# ───────────────────────── 카테고리 체계 ─────────────────────────
# key, 라벨, 아이콘, 설명. 'customer_contract' 는 master_contract 를 읽는 가상 카테고리(/documents/contracts).
CATEGORIES = [
    {"key": "company",        "label": "회사 서류",        "icon": "🏢",
     "desc": "사업자등록증·법인등기·인감·주주명부·자본금·통장·납세/부가세 증명·공증 등"},
    {"key": "certification",  "label": "인증 서류",        "icon": "📜",
     "desc": "각종 인증서·특허·협약서·ISO/KC/CE 등"},
    {"key": "product",        "label": "제품 서류",        "icon": "📦",
     "desc": "제품 매뉴얼·품목허가·기술문서·사양서·카탈로그 등"},
    {"key": "mgmt_contract",  "label": "경영 계약서",      "icon": "📋",
     "desc": "임대차·용역·위탁·도급·비밀유지(NDA)·차입 등 회사 운영 계약(파일)"},
    {"key": "etc",            "label": "기타",            "icon": "🗂",
     "desc": "미분류 — 편집에서 카테고리를 지정하거나 재분류하세요"},
]
CATEGORY_KEYS = [c["key"] for c in CATEGORIES]
CATEGORY_LABELS = {c["key"]: c["label"] for c in CATEGORIES}
CATEGORY_ICONS = {c["key"]: c["icon"] for c in CATEGORIES}
# 고객 계약서(제품별) — Document 가 아니라 Contract 테이블 사용
CUSTOMER_CONTRACT = {"key": "customer_contract", "label": "고객 계약서(제품별)", "icon": "🤝",
                     "desc": "거래처·제품별 영업/서비스 계약 (계약마스터)", "path": "/documents/contracts"}

# 문서 종류 → 카테고리 매핑
CATEGORY_BY_TYPE = {
    "사업자등록증": "company", "법인인감/등기": "company", "인감": "company",
    "주주명부": "company", "자본금 변동": "company", "법인 통장/계좌": "company",
    "대표자 신분증": "company", "위임장": "company", "납세증명": "company",
    "부가세증명": "company", "원천징수영수증": "company", "수출실적증명": "company",
    "공증": "company", "채무변제 공증": "company", "매출 합계표": "company", "매입 합계표": "company",
    "인증서": "certification", "특허": "certification", "협약서": "certification",
    "계약서": "mgmt_contract", "수주/계약 현황": "mgmt_contract",
}
_KW_PRODUCT = re.compile(r"매뉴얼|사용설명|품목허가|허가증|인허가|기술문서|사양서|규격|카탈로그|catalog|제품설명|datasheet|GMP|식약처|KFDA", re.I)
_KW_CERT = re.compile(r"인증서|인증$|특허|실용신안|ISO|KC인증|CE인증|FDA|상표|디자인등록|벤처기업|연구소|이노비즈|메인비즈", re.I)
_KW_MGMT = re.compile(r"임대차|임대|임차|입주|용역|위탁|도급|업무협약|MOU|비밀유지|NDA|차입|대출약정|근저당|투자계약|주주간", re.I)


def infer_category(doc_type: Optional[str], folder: Optional[str], name: Optional[str]) -> str:
    """문서 종류·폴더·파일명으로 대분류 추론."""
    if doc_type and doc_type in CATEGORY_BY_TYPE:
        return CATEGORY_BY_TYPE[doc_type]
    nm = name or ""
    if _KW_PRODUCT.search(nm):
        return "product"
    if _KW_CERT.search(nm):
        return "certification"
    if _KW_MGMT.search(nm):
        return "mgmt_contract"
    f = folder or ""
    if f.startswith("21.증명서") or f.startswith("29"):
        return "company"
    return "etc"


# 자동 스캔 대상 폴더 (상대 경로)
SCAN_FOLDERS = [
    "21.증명서 사업자등록증 외/21.증명서 사업자등록증 외",
    "29. 공증/29. 공증",
    "13.거래처자료/13.거래처자료",
]
DOC_EXTENSIONS = {".pdf", ".hwp", ".hwpx", ".jpg", ".jpeg", ".png", ".docx", ".doc", ".xlsx", ".xls", ".pptx"}

# 문서 종류 추론 규칙 (우선순위 순)
TYPE_RULES = [
    (re.compile(r"사업자등록증"), "사업자등록증"),
    (re.compile(r"법인등기|법인인감"), "법인인감/등기"),
    (re.compile(r"인감"), "인감"),
    (re.compile(r"특허"), "특허"),
    (re.compile(r"공증|법무법인.*변제|공정증서"), "공증"),
    (re.compile(r"국세|지방세|납세증명"), "납세증명"),
    (re.compile(r"부가가치세|부가세증명|표준증명원"), "부가세증명"),
    (re.compile(r"원천징수영수증"), "원천징수영수증"),
    (re.compile(r"수출실적"), "수출실적증명"),
    (re.compile(r"인증서|인증$"), "인증서"),
    (re.compile(r"매출.*계산서.*합계|매출.*합계표"), "매출 합계표"),
    (re.compile(r"매입.*합계"), "매입 합계표"),
    (re.compile(r"입주계약서|계약서"), "계약서"),
    (re.compile(r"신분증"), "대표자 신분증"),
    (re.compile(r"통장|계좌"), "법인 통장/계좌"),
    (re.compile(r"위임장"), "위임장"),
    (re.compile(r"주주명부"), "주주명부"),
    (re.compile(r"자본금"), "자본금 변동"),
    (re.compile(r"협약서"), "협약서"),
    (re.compile(r"수주잔고|매출 계약"), "수주/계약 현황"),
    (re.compile(r"채무변제"), "채무변제 공증"),
]


def infer_doc_type(file_name: str) -> str:
    for rx, label in TYPE_RULES:
        if rx.search(file_name):
            return label
    return "기타"


def infer_dates(file_name: str, mtime: datetime) -> dict:
    """파일명에서 발급일/만료일 추출 시도"""
    out = {"issue_date": None, "expiry_date": None}
    m = re.search(r"유효기간\s*(\d{2}[\.\-]\d{1,2}[\.\-]\d{1,2})", file_name)
    if m:
        try:
            parts = re.split(r"[\.\-]", m.group(1))
            y = 2000 + int(parts[0]) if int(parts[0]) < 100 else int(parts[0])
            out["expiry_date"] = date(y, int(parts[1]), int(parts[2]))
        except Exception:
            pass
    m = re.search(r"\((\d{8})\)", file_name)
    if m:
        s = m.group(1)
        try:
            out["issue_date"] = date(int(s[:4]), int(s[4:6]), int(s[6:8]))
        except Exception:
            pass
    if not out["issue_date"]:
        m = re.search(r"_(\d{6})\b", file_name)
        if m:
            s = m.group(1)
            try:
                y = 2000 + int(s[:2])
                out["issue_date"] = date(y, int(s[2:4]), int(s[4:6]))
            except Exception:
                pass
    if not out["issue_date"]:
        m = re.search(r"(\d{2})\.(\d{1,2})(?:[^0-9]|$)", file_name)
        if m:
            try:
                y = 2000 + int(m.group(1))
                out["issue_date"] = date(y, int(m.group(2)), 1)
            except Exception:
                pass
    if not out["issue_date"]:
        out["issue_date"] = mtime.date() if mtime else None
    return out


def scan_documents(db: Session) -> dict:
    """관련 폴더 자동 스캔. 기존(file_path 동일) 문서는 건너뛰고 신규만 등록(+카테고리 자동분류)."""
    n_new = 0
    n_seen = 0
    existing = {d.file_path for d in db.execute(select(Document).where(Document.file_path.is_not(None))).scalars().all() if d.file_path}

    root = _scan_root()
    for rel in SCAN_FOLDERS:
        base = root / rel
        if not base.exists():
            continue
        for dirpath, dirnames, filenames in os.walk(base):
            for fn in filenames:
                ext = os.path.splitext(fn)[1].lower()
                if ext not in DOC_EXTENSIONS:
                    continue
                if fn.startswith("~$") or fn.startswith(".~lock"):
                    continue
                full = Path(dirpath) / fn
                if str(full) in existing:
                    n_seen += 1
                    continue
                try:
                    stat = full.stat()
                except OSError:
                    continue
                mtime = datetime.fromtimestamp(stat.st_mtime)
                inferred_dates = infer_dates(fn, mtime)
                doc_type = infer_doc_type(fn)
                try:
                    rel_to_root = str(full.relative_to(root))
                except Exception:
                    rel_to_root = str(full)
                folder_cat = rel.split("/")[0]
                mime, _ = mimetypes.guess_type(fn)
                name_only = os.path.splitext(fn)[0]

                db.add(Document(
                    name=name_only,
                    category=infer_category(doc_type, folder_cat, name_only),
                    doc_type=doc_type,
                    issuer=None,
                    issue_date=inferred_dates["issue_date"],
                    expiry_date=inferred_dates["expiry_date"],
                    file_path=str(full),
                    rel_path=rel_to_root,
                    file_name=fn,
                    file_size=stat.st_size,
                    mime_type=mime,
                    folder_category=folder_cat,
                    status="active",
                    source="auto",
                ))
                n_new += 1
    db.commit()
    return {"new": n_new, "seen": n_seen}


def parse_d(s):
    if not s:
        return None
    try:
        return datetime.strptime(s, "%Y-%m-%d").date()
    except Exception:
        return None


def _doc_year(d: Document):
    """문서의 '관리 연도' = 발급일 연도(없으면 만료일 연도)."""
    if d.issue_date:
        return d.issue_date.year
    if d.expiry_date:
        return d.expiry_date.year
    return None


def _attach_remaining(rows):
    today = date.today()
    for r in rows:
        r.days_remaining = (r.expiry_date - today).days if r.expiry_date else None
    return rows


def _category_stats(db: Session) -> list:
    """허브용 카테고리별 통계."""
    today = date.today()
    out = []
    for c in CATEGORIES:
        base = select(Document).where(Document.category == c["key"])
        # etc 에는 category 가 NULL 인 레거시도 포함
        if c["key"] == "etc":
            base = select(Document).where(or_(Document.category == "etc", Document.category.is_(None)))
        cnt = db.scalar(select(func.count()).select_from(base.subquery())) or 0
        exp30 = db.scalar(select(func.count()).select_from(
            base.where(Document.expiry_date.is_not(None),
                       Document.expiry_date >= today,
                       Document.expiry_date <= today + timedelta(days=30)).subquery())) or 0
        expired = db.scalar(select(func.count()).select_from(
            base.where(Document.expiry_date.is_not(None),
                       Document.expiry_date < today).subquery())) or 0
        files = db.scalar(select(func.count()).select_from(
            base.where(Document.file_path.is_not(None)).subquery())) or 0
        out.append({**c, "count": cnt, "expiring_30": exp30, "expired": expired, "files": files})
    return out


# ───────────────────────── 허브 ─────────────────────────
@router.get("", response_class=HTMLResponse)
def hub(request: Request, db: Session = Depends(get_db)):
    today = date.today()
    cats = _category_stats(db)
    # 고객 계약서 카드 통계
    cc_cnt = db.scalar(select(func.count()).select_from(Contract)) or 0
    cc_active = db.scalar(select(func.count()).where(Contract.status == "진행").select_from(Contract)) or 0
    cc_exp30 = db.scalar(select(func.count()).where(
        Contract.end_date.is_not(None),
        Contract.end_date >= today,
        Contract.end_date <= today + timedelta(days=30)).select_from(Contract)) or 0
    customer = {**CUSTOMER_CONTRACT, "count": cc_cnt, "active": cc_active, "expiring_30": cc_exp30}

    total_docs = db.scalar(select(func.count()).select_from(Document)) or 0
    # 전체 만료임박(30일) 상위 — 모든 카테고리 통합
    expiring = _attach_remaining(db.execute(
        select(Document).where(
            Document.expiry_date.is_not(None),
            Document.expiry_date >= today,
            Document.expiry_date <= today + timedelta(days=60),
        ).order_by(Document.expiry_date.asc()).limit(20)
    ).scalars().all())

    return templates.TemplateResponse("documents/hub.html", {
        "request": request, "categories": cats, "customer": customer,
        "total_docs": total_docs, "expiring": expiring,
        "category_labels": CATEGORY_LABELS,
    })


# ───────────────────────── 카테고리별 목록(연도별) ─────────────────────────
@router.get("/cat/{category}", response_class=HTMLResponse)
def list_category(
    category: str, request: Request, db: Session = Depends(get_db),
    q: str = "", doc_type: str = "", status: str = "", year: str = "",
    expiring_within: int = 0,
):
    if category == "customer_contract":
        return RedirectResponse("/documents/contracts", status_code=307)
    if category != "all" and category not in CATEGORY_KEYS:
        raise HTTPException(404, "알 수 없는 카테고리")

    meta = next((c for c in CATEGORIES if c["key"] == category), None) or \
        {"key": "all", "label": "전체 서류", "icon": "📁", "desc": "모든 카테고리 통합"}

    stmt = select(Document)
    if category == "etc":
        stmt = stmt.where(or_(Document.category == "etc", Document.category.is_(None)))
    elif category != "all":
        stmt = stmt.where(Document.category == category)

    if q:
        stmt = stmt.where(or_(
            Document.name.contains(q), Document.file_name.contains(q),
            Document.issuer.contains(q), Document.note.contains(q),
            Document.tags.contains(q), Document.doc_no.contains(q),
        ))
    if doc_type:
        stmt = stmt.where(Document.doc_type == doc_type)
    if status:
        stmt = stmt.where(Document.status == status)
    if expiring_within > 0:
        cutoff = date.today() + timedelta(days=expiring_within)
        stmt = stmt.where(Document.expiry_date.is_not(None),
                          Document.expiry_date <= cutoff,
                          Document.expiry_date >= date.today())

    rows = db.execute(stmt.order_by(
        Document.issue_date.desc().nullslast(),
        Document.expiry_date.asc().nullslast(),
        Document.id.desc())).scalars().all()
    _attach_remaining(rows)

    # 연도 목록 + 연도 필터
    years = sorted({y for y in (_doc_year(r) for r in rows) if y}, reverse=True)
    sel_year = None
    if year:
        try:
            sel_year = int(year)
        except ValueError:
            sel_year = None

    # 연도별 그룹 (필터 적용)
    groups = []
    if sel_year is not None:
        gr = [r for r in rows if _doc_year(r) == sel_year]
        if gr:
            groups.append({"year": sel_year, "rows": gr})
    else:
        from collections import OrderedDict
        bucket = OrderedDict()
        for y in years:
            bucket[y] = []
        bucket_none = []
        for r in rows:
            y = _doc_year(r)
            (bucket[y] if y in bucket else bucket_none).append(r)
        for y, rs in bucket.items():
            if rs:
                groups.append({"year": y, "rows": rs})
        if bucket_none:
            groups.append({"year": None, "rows": bucket_none})

    # 종류 옵션(이 카테고리 내)
    type_stmt = select(Document.doc_type, func.count())
    if category == "etc":
        type_stmt = type_stmt.where(or_(Document.category == "etc", Document.category.is_(None)))
    elif category != "all":
        type_stmt = type_stmt.where(Document.category == category)
    types = [r[0] for r in db.execute(type_stmt.group_by(Document.doc_type).order_by(func.count().desc())).all() if r[0]]

    total_count = len(rows)
    return templates.TemplateResponse("documents/category.html", {
        "request": request, "meta": meta, "category": category,
        "groups": groups, "years": years, "sel_year": sel_year,
        "types": types, "total_count": total_count,
        "categories": CATEGORIES,
        "filter": {"q": q, "doc_type": doc_type, "status": status,
                   "year": year, "expiring_within": expiring_within},
    })


# ───────────────────────── 고객 계약서(제품별, 연도별) ─────────────────────────
@router.get("/contracts", response_class=HTMLResponse)
def customer_contracts(
    request: Request, db: Session = Depends(get_db),
    q: str = "", kind: str = "", item: str = "", year: str = "",
):
    stmt = select(Contract)
    if q:
        stmt = stmt.where(or_(Contract.name.contains(q), Contract.party_name.contains(q),
                              Contract.item_name.contains(q)))
    if kind:
        stmt = stmt.where(Contract.kind == kind)
    if item:
        stmt = stmt.where(Contract.item_name.contains(item))

    rows = db.execute(stmt.order_by(Contract.start_date.desc().nullslast(), Contract.id)).scalars().all()
    today = date.today()
    for r in rows:
        r.remain_days = (r.end_date - today).days if r.end_date else None

    def _cyear(c):
        d = c.start_date or c.signed_date or c.end_date
        return d.year if d else None

    years = sorted({y for y in (_cyear(r) for r in rows) if y}, reverse=True)
    sel_year = None
    if year:
        try:
            sel_year = int(year)
        except ValueError:
            sel_year = None

    groups = []
    if sel_year is not None:
        gr = [r for r in rows if _cyear(r) == sel_year]
        if gr:
            groups.append({"year": sel_year, "rows": gr})
    else:
        from collections import OrderedDict
        bucket = OrderedDict((y, []) for y in years)
        bucket_none = []
        for r in rows:
            y = _cyear(r)
            (bucket[y] if y in bucket else bucket_none).append(r)
        for y, rs in bucket.items():
            if rs:
                groups.append({"year": y, "rows": rs})
        if bucket_none:
            groups.append({"year": None, "rows": bucket_none})

    kinds = [r[0] for r in db.execute(
        select(Contract.kind, func.count()).group_by(Contract.kind).order_by(func.count().desc())).all() if r[0]]
    items = [r[0] for r in db.execute(
        select(Contract.item_name, func.count()).where(Contract.item_name.is_not(None))
        .group_by(Contract.item_name).order_by(func.count().desc()).limit(40)).all() if r[0]]

    total_amount = sum(float(r.contract_amount or 0) for r in rows)
    total_unpaid = sum(float(r.unpaid_amount or 0) for r in rows)
    return templates.TemplateResponse("documents/contracts_view.html", {
        "request": request, "meta": CUSTOMER_CONTRACT, "categories": CATEGORIES,
        "groups": groups, "years": years, "sel_year": sel_year,
        "kinds": kinds, "items": items, "total_count": len(rows),
        "total_amount": total_amount, "total_unpaid": total_unpaid,
        "filter": {"q": q, "kind": kind, "item": item, "year": year},
    })


# ───────────────────────── 스캔 / 재분류 ─────────────────────────
@router.post("/scan")
def trigger_scan(request: Request, db: Session = Depends(get_db), back: str = Form("")):
    res = scan_documents(db)
    dest = back or "/documents"
    sep = "&" if "?" in dest else "?"
    return RedirectResponse(f"{dest}{sep}scanned_new={res['new']}&scanned_seen={res['seen']}", status_code=303)


@router.post("/recategorize")
def recategorize(request: Request, db: Session = Depends(get_db),
                 only_etc: str = Form("1"), back: str = Form("")):
    """규칙 기반 카테고리 재분류. only_etc=1 이면 미분류(etc/NULL)만 보정."""
    stmt = select(Document)
    if only_etc == "1":
        stmt = stmt.where(or_(Document.category == "etc", Document.category.is_(None)))
    rows = db.execute(stmt).scalars().all()
    changed = 0
    for d in rows:
        new_cat = infer_category(d.doc_type, d.folder_category, d.name)
        if new_cat != (d.category or "etc"):
            d.category = new_cat
            changed += 1
    db.commit()
    dest = back or "/documents"
    sep = "&" if "?" in dest else "?"
    return RedirectResponse(f"{dest}{sep}recat={changed}", status_code=303)


# ───────────────────────── 파일 다운로드/뷰 ─────────────────────────
@router.get("/{doc_id}/download")
def download(doc_id: int, db: Session = Depends(get_db)):
    d = db.get(Document, doc_id)
    if not d or not d.file_path:
        raise HTTPException(404, "파일 없음")
    p = Path(d.file_path)
    if not p.exists():
        raise HTTPException(404, "파일을 디스크에서 찾을 수 없음")
    return FileResponse(p, filename=d.file_name or p.name, media_type=d.mime_type or "application/octet-stream")


@router.get("/{doc_id}/view")
def view_inline(doc_id: int, db: Session = Depends(get_db)):
    d = db.get(Document, doc_id)
    if not d or not d.file_path:
        raise HTTPException(404)
    p = Path(d.file_path)
    if not p.exists():
        raise HTTPException(404)
    return FileResponse(p, media_type=d.mime_type or "application/octet-stream",
                        headers={"Content-Disposition": f'inline; filename="{p.name}"'})


# ───────────────────────── 수동 등록/수정 ─────────────────────────
@router.get("/new", response_class=HTMLResponse)
def new_form(request: Request, db: Session = Depends(get_db), category: str = ""):
    types = [r[0] for r in db.execute(select(Document.doc_type).distinct()).all() if r[0]]
    return templates.TemplateResponse("documents/form.html", {
        "request": request, "row": None, "types": sorted(types),
        "categories": CATEGORIES, "preset_category": category if category in CATEGORY_KEYS else "",
    })


def _save_upload(upload: UploadFile, category: str) -> dict:
    """업로드 파일을 doc_uploads/<category>/ 에 저장. 반환: 파일 메타."""
    cat_dir = UPLOAD_DIR / (category or "etc")
    cat_dir.mkdir(parents=True, exist_ok=True)
    safe = re.sub(r'[\\/:*?"<>|]', "_", upload.filename or "file")
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    dest = cat_dir / f"{stamp}_{safe}"
    with open(dest, "wb") as f:
        upload.file.seek(0)
        shutil.copyfileobj(upload.file, f)
    mime, _ = mimetypes.guess_type(safe)
    return {"file_path": str(dest), "file_name": safe,
            "file_size": dest.stat().st_size, "mime_type": mime,
            "rel_path": f"doc_uploads/{category or 'etc'}/{dest.name}"}


@router.post("")
def create_doc(
    db: Session = Depends(get_db),
    name: str = Form(...), category: str = Form("etc"), doc_type: str = Form(""),
    issuer: str = Form(""), doc_no: str = Form(""),
    issue_date: str = Form(""), expiry_date: str = Form(""),
    renewal_cycle_months: int = Form(0), owner: str = Form(""),
    status: str = Form("active"), tags: str = Form(""), note: str = Form(""),
    upload: UploadFile = File(None),
):
    cat = category if category in CATEGORY_KEYS else infer_category(doc_type, None, name)
    d = Document(
        name=name, category=cat, doc_type=doc_type or None, issuer=issuer or None,
        doc_no=doc_no or None,
        issue_date=parse_d(issue_date), expiry_date=parse_d(expiry_date),
        renewal_cycle_months=renewal_cycle_months or None,
        owner=owner or None, status=status,
        tags=tags or None, note=note or None,
        source="manual",
    )
    if upload is not None and getattr(upload, "filename", ""):
        try:
            meta = _save_upload(upload, cat)
            d.file_path = meta["file_path"]; d.file_name = meta["file_name"]
            d.file_size = meta["file_size"]; d.mime_type = meta["mime_type"]
            d.rel_path = meta["rel_path"]; d.source = "upload"
        except Exception:
            pass
    db.add(d); db.commit()
    return RedirectResponse(f"/documents/cat/{cat}?created=1", status_code=303)


@router.get("/{doc_id}/edit", response_class=HTMLResponse)
def edit_form(doc_id: int, request: Request, db: Session = Depends(get_db)):
    row = db.get(Document, doc_id)
    if not row:
        raise HTTPException(404)
    types = [r[0] for r in db.execute(select(Document.doc_type).distinct()).all() if r[0]]
    return templates.TemplateResponse("documents/form.html", {
        "request": request, "row": row, "types": sorted(types),
        "categories": CATEGORIES, "preset_category": "",
    })


@router.post("/{doc_id}")
def update_doc(
    doc_id: int, db: Session = Depends(get_db),
    name: str = Form(...), category: str = Form("etc"), doc_type: str = Form(""),
    issuer: str = Form(""), doc_no: str = Form(""),
    issue_date: str = Form(""), expiry_date: str = Form(""),
    renewal_cycle_months: int = Form(0), owner: str = Form(""),
    status: str = Form("active"), tags: str = Form(""), note: str = Form(""),
    upload: UploadFile = File(None),
):
    row = db.get(Document, doc_id)
    if not row:
        raise HTTPException(404)
    row.name = name
    row.category = category if category in CATEGORY_KEYS else (row.category or "etc")
    row.doc_type = doc_type or None
    row.issuer = issuer or None; row.doc_no = doc_no or None
    row.issue_date = parse_d(issue_date); row.expiry_date = parse_d(expiry_date)
    row.renewal_cycle_months = renewal_cycle_months or None
    row.owner = owner or None; row.status = status
    row.tags = tags or None; row.note = note or None
    if upload is not None and getattr(upload, "filename", ""):
        try:
            meta = _save_upload(upload, row.category)
            row.file_path = meta["file_path"]; row.file_name = meta["file_name"]
            row.file_size = meta["file_size"]; row.mime_type = meta["mime_type"]
            row.rel_path = meta["rel_path"]
            if row.source != "auto":
                row.source = "upload"
        except Exception:
            pass
    db.commit()
    return RedirectResponse(f"/documents/cat/{row.category}?updated=1", status_code=303)


@router.post("/{doc_id}/delete")
def delete_doc(doc_id: int, db: Session = Depends(get_db), back: str = Form("")):
    row = db.get(Document, doc_id)
    cat = row.category if row else None
    if row:
        db.delete(row); db.commit()
    dest = back or (f"/documents/cat/{cat}" if cat else "/documents")
    return RedirectResponse(dest, status_code=303)
