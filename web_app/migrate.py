# -*- coding: utf-8 -*-
"""Excel 마스터 워크북 → SQLite 마이그레이션

실행: python migrate.py
- 기존 app.db 백업 (있다면)
- 테이블 재생성
- 25개 시트 데이터 적재
"""
import sys, io
from pathlib import Path
from datetime import datetime, date
import shutil
import pandas as pd

# UTF-8 출력
if sys.stdout.encoding.lower() != "utf-8":
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")

from database import engine, SessionLocal, init_db, DB_PATH
from models import (Base, Party, Product, Account, Employee, Department,
                    Sale, Purchase, Payroll, Expense, Receivable, Loan, Rental,
                    Severance, Reading, Contract, LoanMaster, ProductMapping)

import os
ROOT = Path(__file__).parent.parent
# 1) INVIZ_MASTER_XLSX 환경변수 우선
# 2) settings_store의 base_data_folder 안에서 검색
# 3) 기본: ROOT (프로젝트 루트)
def _find_master():
    env = os.environ.get("INVIZ_MASTER_XLSX", "").strip()
    if env and Path(env).exists():
        return Path(env)
    try:
        sys.path.insert(0, str(Path(__file__).parent))
        import settings_store as ss
        base = (ss.get("base_data_folder", "") or "").strip()
        if base:
            cand = Path(base) / "인비즈_경영관리마스터_v1.xlsx"
            if cand.exists():
                return cand
    except Exception:
        pass
    return ROOT / "인비즈_경영관리마스터_v1.xlsx"

MASTER_XLSX = _find_master()


def safe_str(v):
    if v is None:
        return None
    try:
        if pd.isna(v):
            return None
    except (TypeError, ValueError):
        pass
    s = str(v).strip()
    return s if s else None


def safe_int(v):
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


def safe_float(v, default=0):
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


def safe_date(v):
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


def load_sheet(name, header_row=0):
    return pd.read_excel(MASTER_XLSX, sheet_name=name, header=header_row)


def migrate_dim_party(db):
    df = load_sheet("10_DIM_거래처")
    seen = set()
    n = 0
    for _, r in df.iterrows():
        code = safe_str(r["거래처코드"])
        name = safe_str(r["거래처명"])
        if not code or not name:
            continue
        if code in seen:
            continue
        seen.add(code)
        db.merge(Party(
            code=code, name=name,
            biz_no=safe_str(r.get("사업자번호")),
            category=safe_str(r.get("구분(병원/대리점/공급사/기타)")),
            main_product=safe_str(r.get("주거래제품")),
            active=safe_str(r.get("활성여부")) or "Y",
            first_seen=safe_date(r.get("최초거래일")),
            last_seen=safe_date(r.get("최종거래일")),
            contact_person=safe_str(r.get("주담당자")),
            phone=safe_str(r.get("연락처")),
            note=safe_str(r.get("비고")),
        ))
        n += 1
    db.commit()
    print(f"  dim_party: {n}건")


def migrate_dim_product(db):
    df = load_sheet("11_DIM_제품")
    n = 0
    for _, r in df.iterrows():
        code = safe_str(r["제품코드"])
        name = safe_str(r["제품명"])
        if not code or not name:
            continue
        db.merge(Product(
            code=code, name=name,
            category=safe_str(r.get("카테고리(상품/제품/용역)")),
            group=safe_str(r.get("그룹")),
            unit_basis=safe_str(r.get("단가기준")),
            note=safe_str(r.get("비고")),
        ))
        n += 1
    db.commit()
    print(f"  dim_product: {n}건")


def migrate_dim_account(db):
    df = load_sheet("12_DIM_계정")
    n = 0
    for _, r in df.iterrows():
        code = safe_str(r["계정코드"])
        name = safe_str(r["계정과목"])
        if not code or not name:
            continue
        db.merge(Account(
            code=code, name=name,
            main_class=safe_str(r.get("대분류(B/S, P/L)")),
            sub_class=safe_str(r.get("중분류")),
            detail_class=safe_str(r.get("소분류")),
            side=safe_str(r.get("차/대")),
        ))
        n += 1
    db.commit()
    print(f"  dim_account: {n}건")


def migrate_dim_employee(db):
    df = load_sheet("13_DIM_직원")
    seen = set()
    n = 0
    for _, r in df.iterrows():
        code = safe_str(r["사번"])
        name = safe_str(r["성명"])
        if not code or not name:
            continue
        if code in seen:
            continue
        seen.add(code)
        db.merge(Employee(
            code=code, name=name,
            department=safe_str(r.get("부서")),
            rank=safe_str(r.get("직급")),
            employment_type=safe_str(r.get("고용형태")),
            hire_date=safe_date(r.get("입사일")),
            resign_date=safe_date(r.get("퇴사일")),
            active=safe_str(r.get("재직여부")) or "재직",
            jumin_last4=safe_str(r.get("주민등록번호(뒤4자리)")),
            base_salary=safe_float(r.get("기준임금"), default=None) if pd.notna(r.get("기준임금")) else None,
            pension_enrolled=safe_str(r.get("퇴직연금가입여부")),
            note=safe_str(r.get("비고")),
        ))
        n += 1
    db.commit()
    print(f"  dim_employee: {n}건")


def migrate_dim_department(db):
    df = load_sheet("14_DIM_부서")
    n = 0
    for _, r in df.iterrows():
        code = safe_str(r["부서코드"])
        name = safe_str(r["부서명"])
        if not code or not name:
            continue
        db.merge(Department(
            code=code, name=name,
            parent=safe_str(r.get("상위부서")),
            function=safe_str(r.get("주요기능")),
            active=safe_str(r.get("활성여부")) or "Y",
        ))
        n += 1
    db.commit()
    print(f"  dim_department: {n}건")


def migrate_fact_sale(db):
    df = load_sheet("20_FACT_매출")
    n = 0
    objs = []
    for _, r in df.iterrows():
        dt = safe_date(r.get("전표일자"))
        if not dt:
            continue
        objs.append(Sale(
            txn_id=safe_str(r.get("거래ID")),
            txn_date=dt,
            year=safe_int(r.get("년")) or dt.year,
            month=safe_int(r.get("월")) or dt.month,
            quarter=safe_str(r.get("분기")) or f"Q{(dt.month - 1) // 3 + 1}",
            half=safe_str(r.get("반기")) or ("H1" if dt.month <= 6 else "H2"),
            party_code=safe_str(r.get("거래처코드")),
            party_name=safe_str(r.get("거래처명")),
            product_code=safe_str(r.get("제품코드")),
            product_name=safe_str(r.get("제품명")),
            item_raw=safe_str(r.get("품명(원본)")),
            account_code=safe_str(r.get("계정코드")),
            account_name=safe_str(r.get("계정과목")),
            sale_type=safe_str(r.get("매출유형(정기/신규/일회성/기타)")),
            supply=safe_float(r.get("공급가액")),
            vat=safe_float(r.get("부가세")),
            total=safe_float(r.get("합계")),
            payment_method=safe_str(r.get("결제수단")),
            note=safe_str(r.get("비고")),
            source_file=safe_str(r.get("원본파일")),
            source_sheet=safe_str(r.get("원본시트")),
            source_row=safe_int(r.get("원본행")),
        ))
        n += 1
        if len(objs) >= 1000:
            db.bulk_save_objects(objs); db.commit(); objs = []
    if objs:
        db.bulk_save_objects(objs); db.commit()
    print(f"  fact_sale: {n}건")


def migrate_fact_purchase(db):
    df = load_sheet("21_FACT_매입")
    n = 0
    objs = []
    for _, r in df.iterrows():
        dt = safe_date(r.get("전표일자"))
        if not dt:
            continue
        objs.append(Purchase(
            txn_id=safe_str(r.get("거래ID")),
            txn_date=dt,
            year=safe_int(r.get("년")) or dt.year,
            month=safe_int(r.get("월")) or dt.month,
            quarter=safe_str(r.get("분기")) or f"Q{(dt.month - 1) // 3 + 1}",
            half=safe_str(r.get("반기")) or ("H1" if dt.month <= 6 else "H2"),
            party_code=safe_str(r.get("거래처코드")),
            party_name=safe_str(r.get("거래처명")),
            product_code=safe_str(r.get("제품코드")),
            product_name=safe_str(r.get("제품명")),
            item_raw=safe_str(r.get("품명(원본)")),
            account_code=safe_str(r.get("계정코드")),
            account_name=safe_str(r.get("계정과목")),
            purchase_type=safe_str(r.get("매입유형(정기/일회성/기타)")),
            supply=safe_float(r.get("공급가액")),
            vat=safe_float(r.get("부가세")),
            total=safe_float(r.get("합계")),
            payment_method=safe_str(r.get("결제수단")),
            note=safe_str(r.get("비고")),
            source_file=safe_str(r.get("원본파일")),
            source_sheet=safe_str(r.get("원본시트")),
            source_row=safe_int(r.get("원본행")),
        ))
        n += 1
        if len(objs) >= 1000:
            db.bulk_save_objects(objs); db.commit(); objs = []
    if objs:
        db.bulk_save_objects(objs); db.commit()
    print(f"  fact_purchase: {n}건")


def migrate_fact_payroll(db):
    df = load_sheet("22_FACT_급여")
    n = 0
    objs = []
    for _, r in df.iterrows():
        name = safe_str(r.get("성명"))
        period = safe_str(r.get("귀속년월"))
        if not name or not period:
            continue
        objs.append(Payroll(
            period=period,
            year=safe_int(r.get("년")),
            month=safe_int(r.get("월")),
            employee_code=safe_str(r.get("사번")),
            employee_name=name,
            department=safe_str(r.get("부서")),
            basic=safe_float(r.get("기본급")),
            meal=safe_float(r.get("식대")),
            car=safe_float(r.get("차량유지비")),
            research=safe_float(r.get("연구수당")),
            other_allow=safe_float(r.get("기타수당")),
            annual_leave=safe_float(r.get("연차수당")),
            overtime=safe_float(r.get("연장근로수당")),
            night=safe_float(r.get("야간근로수당")),
            bonus=safe_float(r.get("성과급")),
            gross_pay=safe_float(r.get("지급합계")),
            pension=safe_float(r.get("국민연금")),
            health=safe_float(r.get("건강보험")),
            longterm=safe_float(r.get("장기요양")),
            employment=safe_float(r.get("고용보험")),
            income_tax=safe_float(r.get("소득세")),
            local_tax=safe_float(r.get("지방소득세")),
            other_deduction=safe_float(r.get("기타공제")),
            total_deduction=safe_float(r.get("공제합계")),
            net_pay=safe_float(r.get("실지급액")),
            employer_insurance=safe_float(r.get("4대보험(기업부담)")),
        ))
        n += 1
    db.bulk_save_objects(objs); db.commit()
    print(f"  fact_payroll: {n}건")


def migrate_fact_expense(db):
    df = load_sheet("23_FACT_비용")
    n = 0
    objs = []
    for _, r in df.iterrows():
        dt = safe_date(r.get("사용일"))
        if not dt:
            continue
        objs.append(Expense(
            txn_id=safe_str(r.get("거래ID")),
            use_date=dt,
            year=safe_int(r.get("년")) or dt.year,
            month=safe_int(r.get("월")) or dt.month,
            quarter=safe_str(r.get("분기")) or f"Q{(dt.month - 1) // 3 + 1}",
            employee_name=safe_str(r.get("사용자(직원)")),
            department=safe_str(r.get("부서")),
            party_or_place=safe_str(r.get("거래처/사용처")),
            amount=safe_float(r.get("금액")),
            account_code=safe_str(r.get("계정코드")),
            account_name=safe_str(r.get("계정과목")),
            category_main=safe_str(r.get("구분(대)")),
            category_sub=safe_str(r.get("상세구분(소)")),
            payment_method=safe_str(r.get("결제수단")),
            note=safe_str(r.get("비고")),
        ))
        n += 1
    db.bulk_save_objects(objs); db.commit()
    print(f"  fact_expense: {n}건")


def migrate_fact_receivable(db):
    df = load_sheet("24_FACT_미수금")
    n = 0
    objs = []
    for _, r in df.iterrows():
        dt = safe_date(r.get("일자"))
        if not dt:
            continue
        name = safe_str(r.get("거래처명"))
        if not name:
            continue
        objs.append(Receivable(
            txn_id=safe_str(r.get("거래ID")),
            txn_date=dt,
            year=safe_int(r.get("년")) or dt.year,
            month=safe_int(r.get("월")) or dt.month,
            party_code=safe_str(r.get("거래처코드")),
            party_name=name,
            memo=safe_str(r.get("적요")),
            invoice_amount=safe_float(r.get("세금계산서금액(증)")),
            paid_amount=safe_float(r.get("입금액(감)")),
            balance=safe_float(r.get("잔액"), default=None),
            slip_no=safe_str(r.get("전표번호")),
            note=safe_str(r.get("비고")),
        ))
        n += 1
    db.bulk_save_objects(objs); db.commit()
    print(f"  fact_receivable: {n}건")


def migrate_fact_loan(db):
    df = load_sheet("25_FACT_차입금")
    n = 0
    objs = []
    for _, r in df.iterrows():
        dt = safe_date(r.get("일자"))
        if not dt:
            continue
        name = safe_str(r.get("차입처명"))
        if not name:
            continue
        objs.append(Loan(
            txn_id=safe_str(r.get("거래ID")),
            txn_date=dt,
            year=safe_int(r.get("년")) or dt.year,
            month=safe_int(r.get("월")) or dt.month,
            lender_kind=safe_str(r.get("차입처구분(은행/개인)")),
            lender_name=name,
            loan_master_id=safe_str(r.get("차입ID")),
            memo=safe_str(r.get("적요")),
            borrowed=safe_float(r.get("차입(+)")),
            repaid=safe_float(r.get("상환(-)")),
            balance=safe_float(r.get("잔액"), default=None),
            interest=safe_float(r.get("이자")),
            note=safe_str(r.get("비고")),
        ))
        n += 1
    db.bulk_save_objects(objs); db.commit()
    print(f"  fact_loan: {n}건")


def migrate_fact_rental(db):
    df = load_sheet("26_FACT_임대료")
    n = 0
    objs = []
    for _, r in df.iterrows():
        dt = safe_date(r.get("일자"))
        if not dt:
            continue
        objs.append(Rental(
            txn_id=safe_str(r.get("거래ID")),
            txn_date=dt,
            year=safe_int(r.get("년")) or dt.year,
            month=safe_int(r.get("월")) or dt.month,
            direction=safe_str(r.get("구분(수입/지출)")) or "지출",
            party=safe_str(r.get("거래처")),
            asset_name=safe_str(r.get("물건명(사무실/장비)")),
            item=safe_str(r.get("항목(임차료/관리비/공과금/렌탈료)")),
            amount=safe_float(r.get("금액")),
            payment_method=safe_str(r.get("결제수단")),
            note=safe_str(r.get("비고")),
        ))
        n += 1
    db.bulk_save_objects(objs); db.commit()
    print(f"  fact_rental: {n}건")


def migrate_fact_severance(db):
    df = load_sheet("27_FACT_퇴직금")
    n = 0
    objs = []
    for _, r in df.iterrows():
        name = safe_str(r.get("성명"))
        period = safe_str(r.get("귀속년월"))
        if not name or not period:
            continue
        objs.append(Severance(
            period=period,
            year=safe_int(r.get("년")),
            month=safe_int(r.get("월")),
            employee_code=safe_str(r.get("사번")),
            employee_name=name,
            base_salary=safe_float(r.get("기준급여"), default=None),
            employer_contribution=safe_float(r.get("기업납입금")),
            employee_contribution=safe_float(r.get("개인납입금")),
            paid_date=safe_date(r.get("납입일자")),
            txn_type=safe_str(r.get("구분(적립/지급/중도인출)")),
            note=safe_str(r.get("비고")),
        ))
        n += 1
    db.bulk_save_objects(objs); db.commit()
    print(f"  fact_severance: {n}건")


def migrate_master_contract(db):
    df = load_sheet("30_계약마스터")
    n = 0
    for _, r in df.iterrows():
        cid = safe_str(r.get("계약ID"))
        if not cid:
            continue
        db.merge(Contract(
            id=cid,
            name=safe_str(r.get("계약명")),
            kind=safe_str(r.get("구분(유지보수/장비/AI/판독/임대/기타)")),
            party_code=safe_str(r.get("거래처코드")),
            party_name=safe_str(r.get("공급받는자(거래처명)")),
            product_code=safe_str(r.get("제품코드")),
            item_name=safe_str(r.get("품명")),
            signed_date=safe_date(r.get("계약체결일")),
            start_date=safe_date(r.get("계약시작일")),
            end_date=safe_date(r.get("계약만료일")),
            duration_months=safe_float(r.get("계약기간(개월)"), default=None),
            auto_renew=safe_str(r.get("자동연장(Y/N)")),
            remain_days=safe_int(r.get("잔여일수")),
            contract_amount=safe_float(r.get("계약금액")),
            issued_amount=safe_float(r.get("발행금액")),
            unpaid_amount=safe_float(r.get("미수금")),
            payment_term=safe_str(r.get("대금지불(월/분기/연/일시)")),
            install_date=safe_date(r.get("설치일")),
            warranty_end=safe_date(r.get("하자보수만료일")),
            has_contract_doc=safe_str(r.get("계약서유무")),
            owner=safe_str(r.get("담당자")),
            phone=safe_str(r.get("연락처")),
            status=safe_str(r.get("활성상태(진행/만료/해지)")),
            note=safe_str(r.get("비고")),
        ))
        n += 1
    db.commit()
    print(f"  master_contract: {n}건")


def migrate_master_loan(db):
    df = load_sheet("31_차입금마스터")
    n = 0
    for _, r in df.iterrows():
        lid = safe_str(r.get("차입ID"))
        if not lid:
            continue
        db.merge(LoanMaster(
            id=lid,
            kind=safe_str(r.get("구분(은행/개인/사채)")),
            term=safe_str(r.get("장단기")),
            institution=safe_str(r.get("금융기관/차주")),
            account_no=safe_str(r.get("계좌번호/식별")),
            limit_amount=safe_float(r.get("약정한도"), default=None),
            initial_amount=safe_float(r.get("최초차입액"), default=None),
            current_balance=safe_float(r.get("현재잔액"), default=None),
            loan_type=safe_str(r.get("차입종류")),
            interest_rate=safe_float(r.get("이자율(%)"), default=None),
            repayment_method=safe_str(r.get("상환방법")),
            start_date=safe_date(r.get("차입일")),
            end_date=safe_date(r.get("만기일")),
            collateral=safe_str(r.get("담보")),
            collateral_amount=safe_float(r.get("담보설정액"), default=None),
            ceo_guarantee=safe_str(r.get("대표이사지급보증")),
            status=safe_str(r.get("활성상태")),
            note=safe_str(r.get("비고")),
        ))
        n += 1
    db.commit()
    print(f"  master_loan: {n}건")


def migrate_master_product_mapping(db):
    df = load_sheet("32_제품매핑")
    n = 0
    for _, r in df.iterrows():
        pattern = safe_str(r.get("매칭패턴(품명에 포함)"))
        pcode = safe_str(r.get("제품코드"))
        if not pattern or not pcode:
            continue
        db.merge(ProductMapping(
            priority=safe_int(r.get("우선순위")) or 99,
            pattern=pattern,
            product_code=pcode,
            product_name=safe_str(r.get("제품명")) or "기타",
            default_sale_type=safe_str(r.get("매출유형 default")),
            note=safe_str(r.get("비고")),
        ))
        n += 1
    db.commit()
    print(f"  master_product_mapping: {n}건")


def main():
    # 기존 DB 백업
    if DB_PATH.exists():
        bk = DB_PATH.parent / "db_backup" / f"app_{datetime.now().strftime('%Y%m%d_%H%M%S')}.db"
        bk.parent.mkdir(exist_ok=True)
        shutil.copy(DB_PATH, bk)
        print(f"기존 DB 백업: {bk.name}")
        DB_PATH.unlink()

    print(f"DB 생성: {DB_PATH}")
    print(f"소스 워크북: {MASTER_XLSX}")
    print(f"존재 여부: {MASTER_XLSX.exists()}")

    init_db()
    db = SessionLocal()
    try:
        print("\n[1] DIM 테이블")
        migrate_dim_party(db)
        migrate_dim_product(db)
        migrate_dim_account(db)
        migrate_dim_employee(db)
        migrate_dim_department(db)

        print("\n[2] FACT 테이블")
        migrate_fact_sale(db)
        migrate_fact_purchase(db)
        migrate_fact_payroll(db)
        migrate_fact_expense(db)
        migrate_fact_receivable(db)
        migrate_fact_loan(db)
        migrate_fact_rental(db)
        migrate_fact_severance(db)

        print("\n[3] 마스터 테이블")
        migrate_master_contract(db)
        migrate_master_loan(db)
        migrate_master_product_mapping(db)
    finally:
        db.close()

    print("\n=== 검증 ===")
    db = SessionLocal()
    try:
        from sqlalchemy import func, select
        for cls in [Party, Product, Account, Employee, Department,
                    Sale, Purchase, Payroll, Expense, Receivable, Loan, Rental, Severance,
                    Contract, LoanMaster, ProductMapping]:
            n = db.scalar(select(func.count()).select_from(cls))
            print(f"  {cls.__tablename__}: {n}행")
    finally:
        db.close()
    print(f"\n완료. DB 파일: {DB_PATH}")


if __name__ == "__main__":
    main()
