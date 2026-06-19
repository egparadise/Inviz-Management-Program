# -*- coding: utf-8 -*-
"""도메인별 동기화 핸들러

각 핸들러는 (db, file_path) → {"rows_added": N, "rows_removed": M} 반환.

원칙:
- 동일 source_file로 적재됐던 기존 데이터를 먼저 삭제 (web_app은 보존)
- 그 다음 새 파일에서 다시 적재
- 트랜잭션 안에서 실행 (실패 시 롤백)
- pandas로 시트 파싱, SQLAlchemy bulk_insert로 적재
"""
import re
import pandas as pd
from datetime import datetime, date
from pathlib import Path
from typing import Optional
from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from models import (Party, Product, Employee, Sale, Purchase, Payroll, Expense,
                    Receivable, Loan, Rental, Severance, Contract, LoanMaster,
                    ProductMapping)


# ============ 공통 유틸 ============
def s_str(v):
    if v is None:
        return None
    try:
        if pd.isna(v):
            return None
    except (TypeError, ValueError):
        pass
    s = str(v).strip()
    return s or None


def s_int(v):
    if v is None:
        return None
    try:
        if pd.isna(v):
            return None
    except (TypeError, ValueError):
        pass
    try:
        return int(v)
    except Exception:
        try:
            return int(float(v))
        except Exception:
            return None


def s_float(v, default=0):
    if v is None:
        return default
    try:
        if pd.isna(v):
            return default
    except (TypeError, ValueError):
        pass
    try:
        return float(v)
    except Exception:
        return default


def s_date(v):
    if v is None:
        return None
    try:
        if pd.isna(v):
            return None
    except (TypeError, ValueError):
        pass
    if isinstance(v, date) and not isinstance(v, datetime):
        return v
    if isinstance(v, datetime):
        return v.date()
    try:
        ts = pd.to_datetime(v, errors="coerce")
        if pd.isna(ts):
            return None
        return ts.date()
    except Exception:
        return None


def normalize_name(name):
    if name is None:
        return None
    try:
        if pd.isna(name):
            return None
    except (TypeError, ValueError):
        pass
    s = str(name).strip()
    if not s or s.lower() in {"nan", "none"}:
        return None
    s = re.sub(r"\s+", " ", s)
    return s.rstrip(".,;:")


def yqh(year, month):
    q = (int(month) - 1) // 3 + 1
    h = 1 if int(month) <= 6 else 2
    return int(year), int(month), f"Q{q}", f"H{h}"


def build_party_map(db: Session) -> dict[str, str]:
    """거래처명 → 코드"""
    m = {}
    for p in db.execute(select(Party.code, Party.name)).all():
        nm = normalize_name(p.name)
        if nm:
            m[nm] = p.code
    return m


def resolve_party(name: str, party_map: dict) -> Optional[str]:
    nm = normalize_name(name)
    if not nm:
        return None
    return party_map.get(nm)


def apply_mapping(item_name, db: Session) -> tuple[str, str]:
    """품명 → (제품코드, 제품명)"""
    if not item_name:
        return "P999", "기타"
    rules = db.execute(select(ProductMapping).order_by(ProductMapping.priority)).scalars().all()
    s = str(item_name)
    for r in rules:
        if r.pattern == "*":
            return r.product_code, r.product_name
        if r.pattern.lower() in s.lower():
            return r.product_code, r.product_name
    return "P999", "기타"


def delete_by_source(db: Session, model, source_file: str) -> int:
    """source_file로 적재됐던 데이터 삭제 (web_app은 보존). 삭제된 행수 반환."""
    if not hasattr(model, "source_file"):
        return 0
    stmt = delete(model).where(
        model.source_file == source_file,
        model.source_file != "web_app",
    )
    return db.execute(stmt).rowcount or 0


# ============ 핸들러: 매출 (매출분류) ============
def handler_sale_classification(db: Session, path: Path) -> dict:
    """매출분류 파일 — 2021/2022/2023 시트 long-format"""
    source_file = path.name
    removed = delete_by_source(db, Sale, source_file)
    party_map = build_party_map(db)

    added = 0
    bulk = []
    for sh in ["2021", "2022", "2023"]:
        try:
            df = pd.read_excel(path, sheet_name=sh)
        except Exception:
            continue

        def col(*keys):
            for k in keys:
                for c in df.columns:
                    if k in str(c):
                        return c
            return None

        c_date = col("전표일자", "일자")
        c_party = col("거래처")
        c_item = col("품명")
        c_supply = col("공급가액")
        c_vat = col("부가세")
        c_total = col("합계")
        c_type = col("매입/매출")
        c_acct = col("계정과목")
        c_kind = col("구분")

        if not c_date or not c_party:
            continue
        for idx, r in df.iterrows():
            kind = str(r.get(c_kind, "") or "").strip() if c_kind else ""
            if "매입" in kind:
                continue
            dt = s_date(r[c_date])
            if not dt:
                continue
            party_name = normalize_name(r[c_party])
            if not party_name:
                continue
            item = normalize_name(r.get(c_item)) if c_item else None
            prod_code, prod_name = apply_mapping(item, db)
            supply = s_float(r.get(c_supply))
            vat = s_float(r.get(c_vat))
            total = s_float(r.get(c_total)) or (supply + vat)
            if supply == 0 and total == 0:
                continue
            y, m, q, h = yqh(dt.year, dt.month)
            bulk.append(Sale(
                txn_id=f"S-{sh}-{idx + 2:05d}",
                txn_date=dt, year=y, month=m, quarter=q, half=h,
                party_code=resolve_party(party_name, party_map),
                party_name=party_name,
                product_code=prod_code, product_name=prod_name,
                item_raw=item,
                account_name=str(r.get(c_acct, "") or "").strip() if c_acct else None,
                sale_type=str(r.get(c_type, "") or "").strip() if c_type else "기타",
                supply=supply, vat=vat, total=total,
                source_file=source_file, source_sheet=sh, source_row=idx + 2,
            ))
            added += 1
    if bulk:
        db.bulk_save_objects(bulk)
        db.commit()
    return {"rows_added": added, "rows_removed": removed}


# ============ 핸들러: 매출 (외상매출금) ============
def handler_sale_ar(db: Session, path: Path) -> dict:
    """외상매출금 파일 — 거래처×월 wide-format → long unpivot. 2024~2026 시트 처리."""
    source_file = path.name
    removed = delete_by_source(db, Sale, source_file)
    party_map = build_party_map(db)

    added = 0
    bulk = []
    sheets = pd.ExcelFile(path).sheet_names
    for sh in sheets:
        m = re.match(r"외상매출금\((\d{4})\)", sh)
        if not m:
            continue
        year = int(m.group(1))
        if year < 2024:  # 2021~2023은 매출분류에서 처리
            continue
        try:
            df = pd.read_excel(path, sheet_name=sh, header=2)
        except Exception:
            continue
        if df.shape[1] < 4:
            continue
        party_col = df.columns[1]
        month_cols = []
        for c in df.columns:
            mm = re.match(r"^(\d+)[월月]$", str(c))
            if mm:
                month_cols.append((int(mm.group(1)), c))
        if not month_cols:
            continue
        for idx, r in df.iterrows():
            party_name = normalize_name(r[party_col])
            if not party_name or any(x in party_name for x in ["합계", "소계", "총계"]):
                continue
            for month, col in month_cols:
                amount = s_float(r.get(col))
                if amount == 0:
                    continue
                supply = round(amount / 1.1, 0)
                vat = amount - supply
                y, mo, q, h = yqh(year, month)
                bulk.append(Sale(
                    txn_id=f"S-AR{year}-{idx + 3:05d}-{month:02d}",
                    txn_date=date(year, month, 28),
                    year=y, month=mo, quarter=q, half=h,
                    party_code=resolve_party(party_name, party_map),
                    party_name=party_name,
                    product_code="P999", product_name="기타",
                    account_name="외상매출금",
                    sale_type="정기",
                    supply=supply, vat=vat, total=amount,
                    note="외상매출금 unpivot",
                    source_file=source_file, source_sheet=sh, source_row=idx + 3,
                ))
                added += 1
    if bulk:
        db.bulk_save_objects(bulk)
        db.commit()
    return {"rows_added": added, "rows_removed": removed}


# ============ 핸들러: 매입 (외상매입금) ============
def handler_purchase_ap(db: Session, path: Path) -> dict:
    source_file = path.name
    removed = delete_by_source(db, Purchase, source_file)
    party_map = build_party_map(db)

    added = 0
    bulk = []
    sheets = pd.ExcelFile(path).sheet_names
    for sh in sheets:
        m = re.match(r"외상매입금\((\d{4})\)", sh)
        if not m:
            continue
        year = int(m.group(1))
        try:
            df = pd.read_excel(path, sheet_name=sh, header=2)
        except Exception:
            try:
                df = pd.read_excel(path, sheet_name=sh, header=1)
            except Exception:
                continue
        if df.shape[1] < 3:
            continue
        party_col = df.columns[1] if len(df.columns) > 1 else df.columns[0]
        month_cols = []
        for c in df.columns:
            mm = re.match(r"^(\d+)[월月]$", str(c))
            if mm:
                month_cols.append((int(mm.group(1)), c))
        if not month_cols:
            continue
        for idx, r in df.iterrows():
            party_name = normalize_name(r[party_col])
            if not party_name or any(x in party_name for x in ["합계", "소계", "총계"]):
                continue
            for month, col in month_cols:
                amount = s_float(r.get(col))
                if amount == 0:
                    continue
                supply = round(amount / 1.1, 0)
                vat = amount - supply
                y, mo, q, h = yqh(year, month)
                bulk.append(Purchase(
                    txn_id=f"P-AP{year}-{idx + 3:05d}-{month:02d}",
                    txn_date=date(year, month, 28),
                    year=y, month=mo, quarter=q, half=h,
                    party_code=resolve_party(party_name, party_map),
                    party_name=party_name,
                    product_code="P999", product_name="기타",
                    account_name="외상매입금",
                    purchase_type="정기",
                    supply=supply, vat=vat, total=amount,
                    note="외상매입금 unpivot",
                    source_file=source_file, source_sheet=sh, source_row=idx + 3,
                ))
                added += 1
    if bulk:
        db.bulk_save_objects(bulk)
        db.commit()
    return {"rows_added": added, "rows_removed": removed}


# ============ 핸들러: 거래처별 세금계산서 (매출+매입) ============
def handler_sale_purchase_invoice(db: Session, path: Path) -> dict:
    source_file = path.name
    removed = delete_by_source(db, Sale, source_file)
    removed += delete_by_source(db, Purchase, source_file)
    party_map = build_party_map(db)

    added_s = added_p = 0
    sale_bulk, purch_bulk = [], []

    sheets = pd.ExcelFile(path).sheet_names
    for sh in sheets:
        m = re.match(r"^(\d{4})\s*(매출|매입)", sh)
        if not m:
            continue
        year = int(m.group(1))
        is_sales = m.group(2) == "매출"
        try:
            df = pd.read_excel(path, sheet_name=sh, header=1)
        except Exception:
            continue

        party_col = next((c for c in df.columns if "거래처" in str(c)), None)
        item_col = next((c for c in df.columns if "품목" in str(c)), None)
        if not party_col:
            continue

        # 월별 매출/매입 컬럼
        month_cols = []
        target_kw = "매출" if is_sales else "매입"
        for c in df.columns:
            s = str(c)
            mm = re.match(rf"^(\d+)월{target_kw}$", s)
            if mm:
                month_cols.append((int(mm.group(1)), c))
            else:
                m2 = re.match(r"^(\d+)월$", s)
                if m2:
                    month_cols.append((int(m2.group(1)), c))
        if not month_cols:
            continue

        for idx, r in df.iterrows():
            party_name = normalize_name(r[party_col])
            if not party_name or any(x in party_name for x in ["합계", "소계", "총계"]):
                continue
            item = normalize_name(r.get(item_col)) if item_col else None
            prod_code, prod_name = apply_mapping(item, db)
            for month, col in month_cols:
                amount = s_float(r.get(col))
                if amount == 0:
                    continue
                y, mo, q, h = yqh(year, month)
                params = dict(
                    txn_date=date(year, month, 28),
                    year=y, month=mo, quarter=q, half=h,
                    party_code=resolve_party(party_name, party_map),
                    party_name=party_name,
                    product_code=prod_code, product_name=prod_name,
                    item_raw=item,
                    supply=amount, vat=0, total=amount,
                    note=f"{sh} wide→long",
                    source_file=source_file, source_sheet=sh, source_row=idx + 3,
                )
                if is_sales:
                    sale_bulk.append(Sale(txn_id=f"S-IV{year}-{idx + 3:05d}-{month:02d}",
                                         sale_type="정기", **params))
                    added_s += 1
                else:
                    purch_bulk.append(Purchase(txn_id=f"P-IV{year}-{idx + 3:05d}-{month:02d}",
                                              purchase_type="정기", **params))
                    added_p += 1

    if sale_bulk:
        db.bulk_save_objects(sale_bulk)
    if purch_bulk:
        db.bulk_save_objects(purch_bulk)
    db.commit()
    return {"rows_added": added_s + added_p, "rows_removed": removed}


# ============ 핸들러: 계약관리 ============
def handler_contract(db: Session, path: Path) -> dict:
    """계약마스터 — 기존 동일 source_file 데이터 삭제 후 재적재"""
    source_file = path.name
    # Contract엔 source_file 컬럼이 없음. note에 마커 두거나, 그냥 merge 사용 (계약ID는 같으면 update)
    # 안전한 방법: 이번 파일의 계약ID 목록을 만들어 그 외는 보존
    party_map = build_party_map(db)
    added = 0
    removed = 0

    new_ids = set()
    for sh in ["계약현황_2025", "2016 ~ (종료)"]:
        try:
            df = pd.read_excel(path, sheet_name=sh, header=1)
        except Exception:
            continue
        cols = list(df.columns)

        def col(*keys):
            for k in keys:
                for c in cols:
                    if k in str(c):
                        return c
            return None

        c_name = col("계약명")
        c_kind = col("구분")
        c_pay = col("대금지불")
        c_item = col("품명")
        c_start = col("계약시작일", "시작일")
        c_end = col("계약만료일", "만료일", "종료일")
        c_months = col("계약기간")
        c_auto = col("자동연장")
        c_party = col("공급받는자", "공급 받는 자", "거래처")
        c_amount = col("계약금액")
        c_issued = col("발행금액")
        c_unpaid = col("미수금")
        c_setdate = col("계약체결일")
        c_install = col("설치일")
        c_warranty = col("하자보수만료")
        c_doc = col("계약서")
        c_owner = col("담당자")
        c_phone = col("연락처")

        for idx, r in df.iterrows():
            name = normalize_name(r.get(c_name)) if c_name else None
            party = normalize_name(r.get(c_party)) if c_party else None
            if not name and not party:
                continue
            if name and any(x in name for x in ["합계", "소계", "총계"]):
                continue
            cid = f"K-{sh[:4]}-{idx + 3:04d}"
            new_ids.add(cid)
            start = s_date(r.get(c_start)) if c_start else None
            end = s_date(r.get(c_end)) if c_end else None
            today = date.today()
            remain = (end - today).days if end else None
            status = "만료" if (end and end < today) else "진행"
            if sh == "2016 ~ (종료)":
                status = "만료"

            data = dict(
                id=cid,
                name=name,
                kind=str(r.get(c_kind, "") or "").strip() if c_kind else None,
                party_code=resolve_party(party, party_map) if party else None,
                party_name=party,
                product_code=None,
                item_name=normalize_name(r.get(c_item)) if c_item else None,
                signed_date=s_date(r.get(c_setdate)) if c_setdate else None,
                start_date=start, end_date=end,
                duration_months=s_float(r.get(c_months), default=None) if c_months else None,
                auto_renew=str(r.get(c_auto, "") or "").strip() if c_auto else None,
                remain_days=remain,
                contract_amount=s_float(r.get(c_amount)) if c_amount else 0,
                issued_amount=s_float(r.get(c_issued)) if c_issued else 0,
                unpaid_amount=s_float(r.get(c_unpaid)) if c_unpaid else 0,
                payment_term=str(r.get(c_pay, "") or "").strip() if c_pay else None,
                install_date=s_date(r.get(c_install)) if c_install else None,
                warranty_end=s_date(r.get(c_warranty)) if c_warranty else None,
                has_contract_doc=str(r.get(c_doc, "") or "").strip() if c_doc else None,
                owner=str(r.get(c_owner, "") or "").strip() if c_owner else None,
                phone=str(r.get(c_phone, "") or "").strip() if c_phone else None,
                status=status,
            )
            existing = db.get(Contract, cid)
            if existing:
                for k, v in data.items():
                    if k != "id":
                        setattr(existing, k, v)
            else:
                db.add(Contract(**data))
                added += 1
    db.commit()
    return {"rows_added": added, "rows_removed": removed}


# ============ 핸들러: 미수금 ============
def handler_receivable(db: Session, path: Path) -> dict:
    source_file = path.name
    # Receivable엔 source_file 컬럼 없음 — note 마커로 식별 (또는 모두 갱신)
    # 안전: 이 파일에서 적재한 행만 삭제하려면 source 컬럼 필요. 지금은 전체 갱신.
    removed = db.execute(delete(Receivable)).rowcount or 0
    party_map = build_party_map(db)

    added = 0
    bulk = []
    xl = pd.ExcelFile(path)
    for sh in xl.sheet_names:
        if sh == "전체":
            continue
        try:
            df = pd.read_excel(path, sheet_name=sh, header=0)
        except Exception:
            continue
        cols = list(df.columns)
        date_col = next((c for c in cols if "날짜" in str(c) or "일자" in str(c)), None)
        memo_col = next((c for c in cols if "적요" in str(c)), None)
        tax_col = next((c for c in cols if "세금계산서" in str(c)), None)
        in_col = next((c for c in cols if "통장입금" in str(c) or "입금액" in str(c)), None)
        bal_col = next((c for c in cols if "잔액" in str(c)), None)
        slip_col = next((c for c in cols if "전표번호" in str(c)), None)
        if not date_col:
            continue
        party_name = re.sub(r"[(（].*?[)）]", "", sh).strip()
        party_code = resolve_party(party_name, party_map)
        for idx, r in df.iterrows():
            dt = s_date(r[date_col])
            if not dt:
                continue
            tax = s_float(r.get(tax_col)) if tax_col else 0
            inc = s_float(r.get(in_col)) if in_col else 0
            if tax == 0 and inc == 0:
                continue
            y, m, _, _ = yqh(dt.year, dt.month)
            bulk.append(Receivable(
                txn_id=f"AR-{sh[:6]}-{idx + 2:05d}",
                txn_date=dt, year=y, month=m,
                party_code=party_code, party_name=party_name,
                memo=str(r.get(memo_col, "") or "").strip() if memo_col else None,
                invoice_amount=tax, paid_amount=inc,
                balance=s_float(r.get(bal_col), default=None) if bal_col else None,
                slip_no=str(r.get(slip_col, "") or "").strip() if slip_col else None,
            ))
            added += 1
    if bulk:
        db.bulk_save_objects(bulk)
        db.commit()
    return {"rows_added": added, "rows_removed": removed}


# ============ 핸들러: 차입금 movements (단기차입금) ============
def handler_loan_movement(db: Session, path: Path) -> dict:
    removed = db.execute(delete(Loan)).rowcount or 0
    added = 0
    bulk = []
    for sh in ["김하남", "최정훈", "송민희", "이현근"]:
        try:
            df = pd.read_excel(path, sheet_name=sh, header=0)
        except Exception:
            continue
        cols = list(df.columns)
        date_col = next((c for c in cols if "날짜" in str(c) or "일자" in str(c)), None)
        memo_col = next((c for c in cols if "적요" in str(c)), None)
        in_col = next((c for c in cols if "차용금" in str(c) or "지급" in str(c)), None)
        out_col = next((c for c in cols if "상환" in str(c) or "미지급" in str(c)), None)
        bal_col = next((c for c in cols if "잔액" in str(c)), None)
        kind_col = next((c for c in cols if str(c).strip() == "구분"), None)
        if not date_col:
            continue
        for idx, r in df.iterrows():
            dt = s_date(r[date_col])
            if not dt:
                continue
            inc = s_float(r.get(in_col)) if in_col else 0
            out = s_float(r.get(out_col)) if out_col else 0
            if inc == 0 and out == 0:
                continue
            y, m, _, _ = yqh(dt.year, dt.month)
            bulk.append(Loan(
                txn_id=f"L-{sh[:2]}-{idx + 2:05d}",
                txn_date=dt, year=y, month=m,
                lender_kind="개인", lender_name=sh,
                loan_master_id=f"LM-{sh}",
                memo=str(r.get(memo_col, "") or "").strip() if memo_col else None,
                borrowed=inc, repaid=out,
                balance=s_float(r.get(bal_col), default=None) if bal_col else None,
                note=str(r.get(kind_col, "") or "").strip() if kind_col else None,
            ))
            added += 1
    if bulk:
        db.bulk_save_objects(bulk)
        db.commit()
    return {"rows_added": added, "rows_removed": removed}


# ============ 핸들러: 차입금 마스터 (주요계정명세서) ============
def handler_loan_master_long(db: Session, path: Path) -> dict:
    """주요계정명세서/장기차입금 시트 → LoanMaster 갱신"""
    # 은행 + 임원 합쳐서 전체 재구성하지 않고, 은행 부분만 갱신
    # 임원 정보(개인(임원))은 단기차입금 핸들러에서 별도 관리됨 → 보존
    removed = db.execute(delete(LoanMaster).where(LoanMaster.kind == "은행")).rowcount or 0
    added = 0
    try:
        df = pd.read_excel(path, sheet_name="장기차입금", header=0)
    except Exception:
        return {"rows_added": 0, "rows_removed": removed}
    cols = list(df.columns)
    for idx, r in df.iterrows():
        bank = normalize_name(r.get("금융기관명") if "금융기관명" in cols else None)
        if not bank or any(x in bank for x in ["합계", "소계", "총계"]):
            continue

        def gv(key):
            for c in cols:
                if key in str(c):
                    return r.get(c)
            return None

        장단기 = str(gv("장단기") or "").strip()
        start = s_date(gv("차입일"))
        end = s_date(gv("만기일"))
        rate = gv("이자율")
        today = date.today()
        status = "만료" if (end and end < today) else "활성"

        db.merge(LoanMaster(
            id=f"LM-{idx + 2:04d}",
            kind="은행",
            term=장단기 or ("장기" if end and (end - today).days > 365 else "단기"),
            institution=bank,
            initial_amount=s_float(gv("최초차입액"), default=None),
            current_balance=s_float(gv("차입금"), default=None),
            loan_type=str(gv("차입종류") or "").strip(),
            interest_rate=float(rate) * 100 if (rate is not None and pd.notna(rate) and float(rate) < 1) else (
                float(rate) if rate is not None and pd.notna(rate) else None),
            repayment_method=str(gv("상환방법") or "").strip(),
            start_date=start, end_date=end,
            collateral=str(gv("담보") or "").strip(),
            collateral_amount=s_float(gv("담보설정액"), default=None),
            ceo_guarantee=str(gv("대표이사지급보증") or "").strip(),
            status=status,
            note=str(gv("비고") or "").strip(),
        ))
        added += 1
    db.commit()
    return {"rows_added": added, "rows_removed": removed}


# ============ 핸들러: 급여 (부서별 인건비) ============
def handler_payroll_dept(db: Session, path: Path) -> dict:
    """부서별 인건비 — 2023 (header=0), 2024 (header=3) 시트"""
    # source_file 컬럼 없음 → period+사번 조합으로 식별, 전체 재구성
    removed = db.execute(delete(Payroll)).rowcount or 0
    emp_map = {e.name: e.code for e in db.execute(select(Employee)).scalars().all()}

    added = 0
    bulk = []
    for sh, hdr, year in [("2024", 3, 2024), ("2023", 0, 2023)]:
        try:
            df = pd.read_excel(path, sheet_name=sh, header=hdr)
        except Exception:
            continue
        cols = list(df.columns)
        name_col = next((c for c in cols if "사원명" in str(c) or "성명" in str(c)), None)
        sabeon_col = next((c for c in cols if "사번" in str(c)), None)
        dept_col = next((c for c in cols if "부서" in str(c)), None)
        if not name_col:
            continue

        def gv(r, *keys):
            for k in keys:
                for c in cols:
                    if k in str(c):
                        return r.get(c)
            return None

        for idx, r in df.iterrows():
            nm = normalize_name(r[name_col])
            if not nm or any(x in nm for x in ["합계", "소계"]):
                continue
            month = None
            try:
                vb = r.iloc[1]
                if pd.notna(vb):
                    m = re.search(r"(\d+)월", str(vb))
                    if m:
                        month = int(m.group(1))
            except Exception:
                pass
            if not month:
                continue
            basic = s_float(gv(r, "기본급"))
            gross = s_float(gv(r, "총급여", "지급합계"))
            if gross == 0:
                continue
            ded = s_float(gv(r, "공제합계"))
            bulk.append(Payroll(
                period=f"{year}-{month:02d}",
                year=year, month=month,
                employee_code=emp_map.get(nm) or (str(r[sabeon_col]) if sabeon_col and pd.notna(r[sabeon_col]) else None),
                employee_name=nm,
                department=normalize_name(r[dept_col]) if dept_col else None,
                basic=basic,
                meal=s_float(gv(r, "식대")),
                car=s_float(gv(r, "차량유지비")),
                research=s_float(gv(r, "연구수당")),
                other_allow=s_float(gv(r, "기타수당")),
                annual_leave=s_float(gv(r, "연차수당")),
                overtime=s_float(gv(r, "연장근로")),
                night=s_float(gv(r, "야간근로")),
                bonus=s_float(gv(r, "성과급")),
                gross_pay=gross,
                pension=s_float(gv(r, "국민연금")),
                health=s_float(gv(r, "건강보험")),
                longterm=s_float(gv(r, "장기요양")),
                employment=s_float(gv(r, "고용보험")),
                income_tax=s_float(gv(r, "소득세")),
                local_tax=s_float(gv(r, "지방소득세")),
                other_deduction=s_float(gv(r, "기타공제")),
                total_deduction=ded,
                net_pay=gross - ded,
                employer_insurance=s_float(gv(r, "4대보험(기업)", "4대보험 기업")),
            ))
            added += 1
    if bulk:
        db.bulk_save_objects(bulk)
        db.commit()
    return {"rows_added": added, "rows_removed": removed}


def handler_payroll_ledger(db: Session, path: Path) -> dict:
    """급여대장 — 25.1월/25.2월 (작은 보강) — payroll_dept가 메인이라 추가 적재"""
    emp_map = {e.name: e.code for e in db.execute(select(Employee)).scalars().all()}
    added = 0
    bulk = []
    try:
        sheets = pd.ExcelFile(path).sheet_names
    except Exception:
        return {"rows_added": 0, "rows_removed": 0}

    for sh in sheets:
        m = re.match(r"(\d{2})\.(\d+)월", sh)
        if not m:
            continue
        year = 2000 + int(m.group(1))
        month = int(m.group(2))
        # 동일 period 데이터 삭제
        db.execute(delete(Payroll).where(Payroll.period == f"{year}-{month:02d}"))
        try:
            df = pd.read_excel(path, sheet_name=sh, header=2)
        except Exception:
            continue
        cols = list(df.columns)
        name_col = next((c for c in cols if "사원명" in str(c) or "성명" in str(c)), None)
        sabeon_col = next((c for c in cols if "사번" in str(c)), None)
        dept_col = next((c for c in cols if "부서" in str(c)), None)
        if not name_col:
            continue

        def gv(r, *keys):
            for k in keys:
                for c in cols:
                    if k in str(c):
                        return r.get(c)
            return None

        for idx, r in df.iterrows():
            nm = normalize_name(r[name_col])
            if not nm or any(x in nm for x in ["합계", "소계"]):
                continue
            gross = s_float(gv(r, "지급합계", "총급여"))
            net = s_float(gv(r, "실지급액", "실수령"))
            if gross == 0 and net == 0:
                continue
            ded = s_float(gv(r, "공제합계"))
            bulk.append(Payroll(
                period=f"{year}-{month:02d}",
                year=year, month=month,
                employee_code=emp_map.get(nm),
                employee_name=nm,
                department=normalize_name(r[dept_col]) if dept_col else None,
                basic=s_float(gv(r, "기본급")),
                gross_pay=gross,
                total_deduction=ded,
                net_pay=net or (gross - ded),
            ))
            added += 1
    if bulk:
        db.bulk_save_objects(bulk)
        db.commit()
    return {"rows_added": added, "rows_removed": 0}


# ============ 핸들러: 비용 (월별 비용정리) ============
def handler_expense_monthly(db: Session, path: Path) -> dict:
    removed = db.execute(delete(Expense)).rowcount or 0
    added = 0
    bulk = []
    try:
        df = pd.read_excel(path, sheet_name="직원별총합", header=2)
    except Exception:
        return {"rows_added": 0, "rows_removed": removed}
    cols = list(df.columns)
    name_col = next((c for c in cols if "이름" in str(c) or "사용자" in str(c)), cols[0])
    date_col = next((c for c in cols if "사용일" in str(c) or "일자" in str(c)), None)
    party_col = next((c for c in cols if "거래처" in str(c)), None)
    amt_col = next((c for c in cols if "금액" in str(c)), None)
    cat_col = next((c for c in cols if str(c).strip() == "구분"), None)
    sub_col = next((c for c in cols if "상세구분" in str(c)), None)
    pay_col = next((c for c in cols if "결제수단" in str(c)), None)
    if not date_col or not amt_col:
        return {"rows_added": 0, "rows_removed": removed}

    for idx, r in df.iterrows():
        dt = s_date(r[date_col])
        if not dt:
            continue
        amt = s_float(r[amt_col])
        if amt == 0:
            continue
        y, m, q, _ = yqh(dt.year, dt.month)
        bulk.append(Expense(
            txn_id=f"E-{idx + 4:05d}",
            use_date=dt, year=y, month=m, quarter=q,
            employee_name=normalize_name(r[name_col]),
            party_or_place=normalize_name(r[party_col]) if party_col else None,
            amount=amt,
            category_main=str(r.get(cat_col, "") or "").strip() if cat_col else None,
            category_sub=str(r.get(sub_col, "") or "").strip() if sub_col else None,
            payment_method=str(r.get(pay_col, "") or "").strip() if pay_col else None,
        ))
        added += 1
    if bulk:
        db.bulk_save_objects(bulk)
        db.commit()
    return {"rows_added": added, "rows_removed": removed}


# ============ 핸들러: 임대료 ============
def handler_rental(db: Session, path: Path) -> dict:
    removed = db.execute(delete(Rental)).rowcount or 0
    added = 0
    bulk = []
    try:
        df = pd.read_excel(path, sheet_name="렌탈현황", header=2)
    except Exception:
        return {"rows_added": 0, "rows_removed": removed}
    cols = list(df.columns)
    item_col = next((c for c in cols if "구분" in str(c) or "품목" in str(c)), cols[0])
    dept_col = next((c for c in cols if "부서" in str(c)), None)
    month_cols = [(int(re.match(r"^(\d+)월$", str(c)).group(1)), c)
                  for c in cols if re.match(r"^(\d+)월$", str(c))]
    if not month_cols:
        return {"rows_added": 0, "rows_removed": removed}

    for idx, r in df.iterrows():
        item = normalize_name(r[item_col])
        if not item or any(x in item for x in ["합계", "소계", "수량", "금액"]):
            continue
        for month, col in month_cols:
            amt = s_float(r.get(col))
            if amt == 0:
                continue
            bulk.append(Rental(
                txn_id=f"L-렌탈-{idx + 4:05d}-{month:02d}",
                txn_date=date(2024, month, 28),  # 파일이 2024년 기준
                year=2024, month=month,
                direction="지출",
                party=normalize_name(r[dept_col]) if dept_col else None,
                asset_name=item, item="렌탈료",
                amount=amt,
            ))
            added += 1
    if bulk:
        db.bulk_save_objects(bulk)
        db.commit()
    return {"rows_added": added, "rows_removed": removed}


# ============ 핸들러: 퇴직금 ============
def handler_severance(db: Session, path: Path) -> dict:
    removed = db.execute(delete(Severance)).rowcount or 0
    emp_map = {e.name: e.code for e in db.execute(select(Employee)).scalars().all()}
    added = 0
    bulk = []
    try:
        df = pd.read_excel(path, sheet_name="기업납입금", header=1)
    except Exception:
        return {"rows_added": 0, "rows_removed": removed}
    cols = list(df.columns)
    name_col = next((c for c in cols if "성명" in str(c) or "이름" in str(c) or "가입자" in str(c)), cols[0])
    month_cols = []
    for c in cols:
        if c == name_col:
            continue
        if hasattr(c, "year") and hasattr(c, "month"):
            month_cols.append((c.year, c.month, c))
            continue
        s = str(c).strip()
        m = re.match(r"(\d{4})[-/.](\d{1,2})", s)
        if m:
            month_cols.append((int(m.group(1)), int(m.group(2)), c))
            continue
        try:
            d = pd.to_datetime(s, errors="coerce")
            if pd.notna(d):
                month_cols.append((d.year, d.month, c))
        except Exception:
            pass
    if not month_cols:
        return {"rows_added": 0, "rows_removed": removed}

    for idx, r in df.iterrows():
        nm = normalize_name(r[name_col])
        if not nm or any(x in nm for x in ["합계", "소계", "총계"]):
            continue
        for yr, mo, col in month_cols:
            amt = s_float(r.get(col))
            if amt == 0:
                continue
            bulk.append(Severance(
                period=f"{yr}-{mo:02d}",
                year=yr, month=mo,
                employee_code=emp_map.get(nm), employee_name=nm,
                employer_contribution=amt,
                txn_type="적립",
            ))
            added += 1
    if bulk:
        db.bulk_save_objects(bulk)
        db.commit()
    return {"rows_added": added, "rows_removed": removed}


# ============ 핸들러 매핑 ============
HANDLERS = {
    "sale_classification": handler_sale_classification,
    "sale_ar": handler_sale_ar,
    "purchase_ap": handler_purchase_ap,
    "sale_purchase_invoice": handler_sale_purchase_invoice,
    "contract": handler_contract,
    "receivable": handler_receivable,
    "loan_movement": handler_loan_movement,
    "loan_master_long": handler_loan_master_long,
    "payroll_dept": handler_payroll_dept,
    "payroll_ledger": handler_payroll_ledger,
    "expense_monthly": handler_expense_monthly,
    "rental": handler_rental,
    "severance": handler_severance,
    # "reading_fee": ...  # 추후 보강
}
