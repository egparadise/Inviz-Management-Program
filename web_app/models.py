# -*- coding: utf-8 -*-
"""인비즈 경영관리 DB 모델 — SQLAlchemy 2.0 style

DIM (기준): 거래처, 제품, 계정, 직원, 부서
FACT (트랜잭션): 매출, 매입, 급여, 비용, 미수금, 차입금, 임대료, 퇴직금, 판독수수료
마스터: 계약, 차입금마스터, 제품매핑
"""
from datetime import date, datetime
from typing import Optional
from sqlalchemy import String, Integer, Float, Date, DateTime, Text, ForeignKey, Index, BigInteger, Numeric
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    pass


# ==================== DIM ====================
class Party(Base):
    """10_DIM_거래처"""
    __tablename__ = "dim_party"
    code: Mapped[str] = mapped_column(String(10), primary_key=True)
    name: Mapped[str] = mapped_column(String(200), nullable=False, index=True)
    biz_no: Mapped[Optional[str]] = mapped_column(String(20))
    category: Mapped[Optional[str]] = mapped_column(String(40))  # 병원/대리점/공급사/기타
    main_product: Mapped[Optional[str]] = mapped_column(String(100))
    active: Mapped[str] = mapped_column(String(1), default="Y")
    first_seen: Mapped[Optional[date]] = mapped_column(Date)
    last_seen: Mapped[Optional[date]] = mapped_column(Date)
    contact_person: Mapped[Optional[str]] = mapped_column(String(50))
    phone: Mapped[Optional[str]] = mapped_column(String(40))
    note: Mapped[Optional[str]] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class Product(Base):
    """11_DIM_제품"""
    __tablename__ = "dim_product"
    code: Mapped[str] = mapped_column(String(10), primary_key=True)
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    category: Mapped[Optional[str]] = mapped_column(String(40))  # 상품/제품/용역/기타
    group: Mapped[Optional[str]] = mapped_column(String(40))
    unit_basis: Mapped[Optional[str]] = mapped_column(String(40))
    note: Mapped[Optional[str]] = mapped_column(Text)


class Account(Base):
    """12_DIM_계정"""
    __tablename__ = "dim_account"
    code: Mapped[str] = mapped_column(String(10), primary_key=True)
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    main_class: Mapped[Optional[str]] = mapped_column(String(20))  # B/S, P/L
    sub_class: Mapped[Optional[str]] = mapped_column(String(40))
    detail_class: Mapped[Optional[str]] = mapped_column(String(40))
    side: Mapped[Optional[str]] = mapped_column(String(2))  # 차/대


class Employee(Base):
    """13_DIM_직원"""
    __tablename__ = "dim_employee"
    code: Mapped[str] = mapped_column(String(20), primary_key=True)  # 사번
    name: Mapped[str] = mapped_column(String(50), nullable=False)
    department: Mapped[Optional[str]] = mapped_column(String(40))
    rank: Mapped[Optional[str]] = mapped_column(String(40))
    employment_type: Mapped[Optional[str]] = mapped_column(String(20))
    hire_date: Mapped[Optional[date]] = mapped_column(Date)
    resign_date: Mapped[Optional[date]] = mapped_column(Date)
    active: Mapped[str] = mapped_column(String(10), default="재직")
    jumin_last4: Mapped[Optional[str]] = mapped_column(String(4))
    base_salary: Mapped[Optional[float]] = mapped_column(Float)  # 기준임금(연봉 또는 월급 — salary_annual로 구분)
    salary_annual: Mapped[Optional[str]] = mapped_column(String(1), default="N")  # Y=base_salary가 연봉, N=월급
    pension_enrolled: Mapped[Optional[str]] = mapped_column(String(1))
    email: Mapped[Optional[str]] = mapped_column(String(200))   # 급여명세서 발송용 이메일
    birth_date: Mapped[Optional[date]] = mapped_column(Date)    # 생년월일 — 명세서 PDF 비밀번호(앞6자리 YYMMDD)
    note: Mapped[Optional[str]] = mapped_column(Text)


class Department(Base):
    """14_DIM_부서"""
    __tablename__ = "dim_department"
    code: Mapped[str] = mapped_column(String(10), primary_key=True)
    name: Mapped[str] = mapped_column(String(50), nullable=False)
    parent: Mapped[Optional[str]] = mapped_column(String(50))
    function: Mapped[Optional[str]] = mapped_column(String(100))
    active: Mapped[str] = mapped_column(String(1), default="Y")


# ==================== FACT (트랜잭션) ====================
class Sale(Base):
    """20_FACT_매출"""
    __tablename__ = "fact_sale"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    txn_id: Mapped[Optional[str]] = mapped_column(String(40), index=True)
    txn_date: Mapped[date] = mapped_column(Date, nullable=False, index=True)
    year: Mapped[int] = mapped_column(Integer, index=True)
    month: Mapped[int] = mapped_column(Integer, index=True)
    quarter: Mapped[str] = mapped_column(String(3))
    half: Mapped[str] = mapped_column(String(3))
    party_code: Mapped[Optional[str]] = mapped_column(String(10), ForeignKey("dim_party.code"), index=True)
    party_name: Mapped[Optional[str]] = mapped_column(String(200))
    product_code: Mapped[Optional[str]] = mapped_column(String(10), ForeignKey("dim_product.code"), index=True)
    product_name: Mapped[Optional[str]] = mapped_column(String(100))
    item_raw: Mapped[Optional[str]] = mapped_column(String(200))
    account_code: Mapped[Optional[str]] = mapped_column(String(10), ForeignKey("dim_account.code"))
    account_name: Mapped[Optional[str]] = mapped_column(String(100))
    sale_type: Mapped[Optional[str]] = mapped_column(String(40))  # 정기/신규/일회성/기타
    supply: Mapped[float] = mapped_column(Numeric(18, 2), default=0)
    vat: Mapped[float] = mapped_column(Numeric(18, 2), default=0)
    total: Mapped[float] = mapped_column(Numeric(18, 2), default=0)
    payment_method: Mapped[Optional[str]] = mapped_column(String(40))
    note: Mapped[Optional[str]] = mapped_column(Text)
    source_file: Mapped[Optional[str]] = mapped_column(String(200))
    source_sheet: Mapped[Optional[str]] = mapped_column(String(100))
    source_row: Mapped[Optional[int]] = mapped_column(Integer)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class Purchase(Base):
    """21_FACT_매입"""
    __tablename__ = "fact_purchase"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    txn_id: Mapped[Optional[str]] = mapped_column(String(40), index=True)
    txn_date: Mapped[date] = mapped_column(Date, nullable=False, index=True)
    year: Mapped[int] = mapped_column(Integer, index=True)
    month: Mapped[int] = mapped_column(Integer, index=True)
    quarter: Mapped[str] = mapped_column(String(3))
    half: Mapped[str] = mapped_column(String(3))
    party_code: Mapped[Optional[str]] = mapped_column(String(10), ForeignKey("dim_party.code"), index=True)
    party_name: Mapped[Optional[str]] = mapped_column(String(200))
    product_code: Mapped[Optional[str]] = mapped_column(String(10), ForeignKey("dim_product.code"), index=True)
    product_name: Mapped[Optional[str]] = mapped_column(String(100))
    item_raw: Mapped[Optional[str]] = mapped_column(String(200))
    account_code: Mapped[Optional[str]] = mapped_column(String(10))
    account_name: Mapped[Optional[str]] = mapped_column(String(100))
    purchase_type: Mapped[Optional[str]] = mapped_column(String(40))
    supply: Mapped[float] = mapped_column(Numeric(18, 2), default=0)
    vat: Mapped[float] = mapped_column(Numeric(18, 2), default=0)
    total: Mapped[float] = mapped_column(Numeric(18, 2), default=0)
    payment_method: Mapped[Optional[str]] = mapped_column(String(40))
    note: Mapped[Optional[str]] = mapped_column(Text)
    source_file: Mapped[Optional[str]] = mapped_column(String(200))
    source_sheet: Mapped[Optional[str]] = mapped_column(String(100))
    source_row: Mapped[Optional[int]] = mapped_column(Integer)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class Payroll(Base):
    """22_FACT_급여"""
    __tablename__ = "fact_payroll"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    period: Mapped[str] = mapped_column(String(7), index=True)  # YYYY-MM
    year: Mapped[int] = mapped_column(Integer, index=True)
    month: Mapped[int] = mapped_column(Integer, index=True)
    employee_code: Mapped[Optional[str]] = mapped_column(String(20), ForeignKey("dim_employee.code"))
    employee_name: Mapped[str] = mapped_column(String(50))
    department: Mapped[Optional[str]] = mapped_column(String(40))
    basic: Mapped[float] = mapped_column(Numeric(18, 2), default=0)
    meal: Mapped[float] = mapped_column(Numeric(18, 2), default=0)
    car: Mapped[float] = mapped_column(Numeric(18, 2), default=0)
    research: Mapped[float] = mapped_column(Numeric(18, 2), default=0)
    other_allow: Mapped[float] = mapped_column(Numeric(18, 2), default=0)
    annual_leave: Mapped[float] = mapped_column(Numeric(18, 2), default=0)
    overtime: Mapped[float] = mapped_column(Numeric(18, 2), default=0)
    night: Mapped[float] = mapped_column(Numeric(18, 2), default=0)
    bonus: Mapped[float] = mapped_column(Numeric(18, 2), default=0)
    gross_pay: Mapped[float] = mapped_column(Numeric(18, 2), default=0)
    pension: Mapped[float] = mapped_column(Numeric(18, 2), default=0)
    health: Mapped[float] = mapped_column(Numeric(18, 2), default=0)
    longterm: Mapped[float] = mapped_column(Numeric(18, 2), default=0)
    employment: Mapped[float] = mapped_column(Numeric(18, 2), default=0)
    income_tax: Mapped[float] = mapped_column(Numeric(18, 2), default=0)
    local_tax: Mapped[float] = mapped_column(Numeric(18, 2), default=0)
    other_deduction: Mapped[float] = mapped_column(Numeric(18, 2), default=0)
    total_deduction: Mapped[float] = mapped_column(Numeric(18, 2), default=0)
    net_pay: Mapped[float] = mapped_column(Numeric(18, 2), default=0)
    employer_insurance: Mapped[float] = mapped_column(Numeric(18, 2), default=0)
    note: Mapped[Optional[str]] = mapped_column(Text)


class Expense(Base):
    """23_FACT_비용"""
    __tablename__ = "fact_expense"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    txn_id: Mapped[Optional[str]] = mapped_column(String(40))
    use_date: Mapped[date] = mapped_column(Date, nullable=False, index=True)
    year: Mapped[int] = mapped_column(Integer, index=True)
    month: Mapped[int] = mapped_column(Integer, index=True)
    quarter: Mapped[str] = mapped_column(String(3))
    employee_name: Mapped[Optional[str]] = mapped_column(String(50))
    department: Mapped[Optional[str]] = mapped_column(String(40))
    party_or_place: Mapped[Optional[str]] = mapped_column(String(200))
    amount: Mapped[float] = mapped_column(Numeric(18, 2), default=0)
    account_code: Mapped[Optional[str]] = mapped_column(String(10))
    account_name: Mapped[Optional[str]] = mapped_column(String(100))
    category_main: Mapped[Optional[str]] = mapped_column(String(40))
    category_sub: Mapped[Optional[str]] = mapped_column(String(40))
    payment_method: Mapped[Optional[str]] = mapped_column(String(40))
    note: Mapped[Optional[str]] = mapped_column(Text)


class Receivable(Base):
    """24_FACT_미수금 (movements)"""
    __tablename__ = "fact_receivable"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    txn_id: Mapped[Optional[str]] = mapped_column(String(40))
    txn_date: Mapped[date] = mapped_column(Date, nullable=False, index=True)
    year: Mapped[int] = mapped_column(Integer, index=True)
    month: Mapped[int] = mapped_column(Integer, index=True)
    party_code: Mapped[Optional[str]] = mapped_column(String(10), ForeignKey("dim_party.code"))
    party_name: Mapped[str] = mapped_column(String(200))
    memo: Mapped[Optional[str]] = mapped_column(String(200))
    invoice_amount: Mapped[float] = mapped_column(Numeric(18, 2), default=0)  # 세금계산서금액(증)
    paid_amount: Mapped[float] = mapped_column(Numeric(18, 2), default=0)  # 입금액(감)
    balance: Mapped[Optional[float]] = mapped_column(Numeric(18, 2))
    slip_no: Mapped[Optional[str]] = mapped_column(String(40))
    note: Mapped[Optional[str]] = mapped_column(Text)


class Loan(Base):
    """25_FACT_차입금 (movements)"""
    __tablename__ = "fact_loan"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    txn_id: Mapped[Optional[str]] = mapped_column(String(40))
    txn_date: Mapped[date] = mapped_column(Date, nullable=False, index=True)
    year: Mapped[int] = mapped_column(Integer, index=True)
    month: Mapped[int] = mapped_column(Integer, index=True)
    lender_kind: Mapped[Optional[str]] = mapped_column(String(20))  # 은행/개인
    lender_name: Mapped[str] = mapped_column(String(100))
    loan_master_id: Mapped[Optional[str]] = mapped_column(String(40))
    memo: Mapped[Optional[str]] = mapped_column(String(200))
    borrowed: Mapped[float] = mapped_column(Numeric(18, 2), default=0)
    repaid: Mapped[float] = mapped_column(Numeric(18, 2), default=0)
    balance: Mapped[Optional[float]] = mapped_column(Numeric(18, 2))
    interest: Mapped[float] = mapped_column(Numeric(18, 2), default=0)
    note: Mapped[Optional[str]] = mapped_column(Text)


class Rental(Base):
    """26_FACT_임대료"""
    __tablename__ = "fact_rental"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    txn_id: Mapped[Optional[str]] = mapped_column(String(40))
    txn_date: Mapped[date] = mapped_column(Date, nullable=False, index=True)
    year: Mapped[int] = mapped_column(Integer, index=True)
    month: Mapped[int] = mapped_column(Integer, index=True)
    direction: Mapped[str] = mapped_column(String(10))  # 수입/지출
    party: Mapped[Optional[str]] = mapped_column(String(200))
    asset_name: Mapped[Optional[str]] = mapped_column(String(100))
    item: Mapped[Optional[str]] = mapped_column(String(40))  # 임차료/관리비/공과금/렌탈료
    amount: Mapped[float] = mapped_column(Numeric(18, 2), default=0)
    payment_method: Mapped[Optional[str]] = mapped_column(String(40))
    note: Mapped[Optional[str]] = mapped_column(Text)


class Severance(Base):
    """27_FACT_퇴직금"""
    __tablename__ = "fact_severance"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    period: Mapped[str] = mapped_column(String(7), index=True)
    year: Mapped[int] = mapped_column(Integer, index=True)
    month: Mapped[int] = mapped_column(Integer, index=True)
    employee_code: Mapped[Optional[str]] = mapped_column(String(20))
    employee_name: Mapped[str] = mapped_column(String(50))
    base_salary: Mapped[Optional[float]] = mapped_column(Numeric(18, 2))
    employer_contribution: Mapped[float] = mapped_column(Numeric(18, 2), default=0)
    employee_contribution: Mapped[float] = mapped_column(Numeric(18, 2), default=0)
    paid_date: Mapped[Optional[date]] = mapped_column(Date)
    txn_type: Mapped[Optional[str]] = mapped_column(String(20))  # 적립/지급/중도인출
    note: Mapped[Optional[str]] = mapped_column(Text)


class Reading(Base):
    """28_FACT_판독수수료"""
    __tablename__ = "fact_reading"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    txn_id: Mapped[Optional[str]] = mapped_column(String(40))
    period: Mapped[str] = mapped_column(String(7))
    year: Mapped[int] = mapped_column(Integer, index=True)
    month: Mapped[int] = mapped_column(Integer, index=True)
    direction: Mapped[str] = mapped_column(String(10))  # 매출/매입
    hospital: Mapped[Optional[str]] = mapped_column(String(200))
    agency: Mapped[Optional[str]] = mapped_column(String(100))
    product_code: Mapped[Optional[str]] = mapped_column(String(10))
    product_name: Mapped[Optional[str]] = mapped_column(String(100))
    read_count: Mapped[Optional[int]] = mapped_column(Integer)
    unit_price: Mapped[Optional[float]] = mapped_column(Numeric(18, 2))
    reading_fee: Mapped[Optional[float]] = mapped_column(Numeric(18, 2))
    inviz_income: Mapped[Optional[float]] = mapped_column(Numeric(18, 2))
    agency_fee: Mapped[Optional[float]] = mapped_column(Numeric(18, 2))
    revenue: Mapped[Optional[float]] = mapped_column(Numeric(18, 2))
    cost: Mapped[Optional[float]] = mapped_column(Numeric(18, 2))
    net_profit: Mapped[Optional[float]] = mapped_column(Numeric(18, 2))
    margin: Mapped[Optional[float]] = mapped_column(Float)
    note: Mapped[Optional[str]] = mapped_column(Text)


# ==================== 마스터 ====================
class Contract(Base):
    """30_계약마스터"""
    __tablename__ = "master_contract"
    id: Mapped[str] = mapped_column(String(40), primary_key=True)
    name: Mapped[Optional[str]] = mapped_column(String(200))
    kind: Mapped[Optional[str]] = mapped_column(String(40))
    party_code: Mapped[Optional[str]] = mapped_column(String(10), ForeignKey("dim_party.code"))
    party_name: Mapped[Optional[str]] = mapped_column(String(200))
    product_code: Mapped[Optional[str]] = mapped_column(String(10))
    item_name: Mapped[Optional[str]] = mapped_column(String(200))
    signed_date: Mapped[Optional[date]] = mapped_column(Date)
    start_date: Mapped[Optional[date]] = mapped_column(Date, index=True)
    end_date: Mapped[Optional[date]] = mapped_column(Date, index=True)
    duration_months: Mapped[Optional[float]] = mapped_column(Float)
    auto_renew: Mapped[Optional[str]] = mapped_column(String(5))
    remain_days: Mapped[Optional[int]] = mapped_column(Integer)
    contract_amount: Mapped[float] = mapped_column(Numeric(18, 2), default=0)
    issued_amount: Mapped[float] = mapped_column(Numeric(18, 2), default=0)
    unpaid_amount: Mapped[float] = mapped_column(Numeric(18, 2), default=0)
    payment_term: Mapped[Optional[str]] = mapped_column(String(40))
    payment_day: Mapped[Optional[str]] = mapped_column(String(40))
    install_date: Mapped[Optional[date]] = mapped_column(Date)
    warranty_end: Mapped[Optional[date]] = mapped_column(Date)
    has_contract_doc: Mapped[Optional[str]] = mapped_column(String(5))
    owner: Mapped[Optional[str]] = mapped_column(String(50))
    phone: Mapped[Optional[str]] = mapped_column(String(40))
    status: Mapped[Optional[str]] = mapped_column(String(20), index=True)  # 진행/만료/해지
    note: Mapped[Optional[str]] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class LoanMaster(Base):
    """31_차입금마스터"""
    __tablename__ = "master_loan"
    id: Mapped[str] = mapped_column(String(40), primary_key=True)
    kind: Mapped[Optional[str]] = mapped_column(String(20))  # 은행/개인/사채/개인(임원)
    term: Mapped[Optional[str]] = mapped_column(String(10))  # 장기/단기
    institution: Mapped[Optional[str]] = mapped_column(String(100))
    account_no: Mapped[Optional[str]] = mapped_column(String(40))
    limit_amount: Mapped[Optional[float]] = mapped_column(Numeric(18, 2))
    initial_amount: Mapped[Optional[float]] = mapped_column(Numeric(18, 2))
    current_balance: Mapped[Optional[float]] = mapped_column(Numeric(18, 2))
    loan_type: Mapped[Optional[str]] = mapped_column(String(40))
    interest_rate: Mapped[Optional[float]] = mapped_column(Float)
    repayment_method: Mapped[Optional[str]] = mapped_column(String(40))
    start_date: Mapped[Optional[date]] = mapped_column(Date)
    end_date: Mapped[Optional[date]] = mapped_column(Date)
    collateral: Mapped[Optional[str]] = mapped_column(String(200))
    collateral_amount: Mapped[Optional[float]] = mapped_column(Numeric(18, 2))
    ceo_guarantee: Mapped[Optional[str]] = mapped_column(String(20))
    status: Mapped[Optional[str]] = mapped_column(String(20))
    note: Mapped[Optional[str]] = mapped_column(Text)


class ProductMapping(Base):
    """32_제품매핑"""
    __tablename__ = "master_product_mapping"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    priority: Mapped[int] = mapped_column(Integer, default=99)
    pattern: Mapped[str] = mapped_column(String(100), nullable=False)
    product_code: Mapped[str] = mapped_column(String(10))
    product_name: Mapped[str] = mapped_column(String(100))
    default_sale_type: Mapped[Optional[str]] = mapped_column(String(40))
    note: Mapped[Optional[str]] = mapped_column(Text)


# ==================== Audit ====================
class AuditLog(Base):
    """변경 이력 (감사 로그)"""
    __tablename__ = "audit_log"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    ts: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, index=True)
    user_session: Mapped[Optional[str]] = mapped_column(String(40))
    table_name: Mapped[str] = mapped_column(String(40))
    row_id: Mapped[str] = mapped_column(String(40))
    action: Mapped[str] = mapped_column(String(10))  # INSERT/UPDATE/DELETE
    summary: Mapped[Optional[str]] = mapped_column(Text)


# ==================== 동기화 인프라 ====================
class FileRegistry(Base):
    """추적 중인 원본 파일 — mtime/해시 비교로 변경 감지"""
    __tablename__ = "file_registry"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    path: Mapped[str] = mapped_column(String(1000), unique=True, index=True)  # 절대 경로
    rel_path: Mapped[str] = mapped_column(String(1000))  # 14.경영정보 기준 상대 경로
    file_name: Mapped[str] = mapped_column(String(300), index=True)
    size_bytes: Mapped[int] = mapped_column(BigInteger, default=0)
    mtime: Mapped[Optional[datetime]] = mapped_column(DateTime)
    sha256: Mapped[Optional[str]] = mapped_column(String(64))
    domain: Mapped[Optional[str]] = mapped_column(String(40), index=True)
    matched_pattern: Mapped[Optional[str]] = mapped_column(String(200))
    status: Mapped[str] = mapped_column(String(20), default="new")  # new/processed/skipped/error/unmapped
    last_processed_at: Mapped[Optional[datetime]] = mapped_column(DateTime)
    last_error: Mapped[Optional[str]] = mapped_column(Text)
    rows_loaded: Mapped[Optional[int]] = mapped_column(Integer)
    is_latest_for_domain: Mapped[str] = mapped_column(String(1), default="N")  # 도메인별 최신 파일 표시
    first_seen: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    last_seen: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class SyncRun(Base):
    """동기화 실행 이력 (1회 실행 = 1행)"""
    __tablename__ = "sync_run"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    started_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, index=True)
    finished_at: Mapped[Optional[datetime]] = mapped_column(DateTime)
    triggered_by: Mapped[str] = mapped_column(String(20), default="manual")  # manual/scheduled/api
    files_scanned: Mapped[int] = mapped_column(Integer, default=0)
    files_changed: Mapped[int] = mapped_column(Integer, default=0)
    files_processed: Mapped[int] = mapped_column(Integer, default=0)
    files_unmapped: Mapped[int] = mapped_column(Integer, default=0)
    files_errored: Mapped[int] = mapped_column(Integer, default=0)
    rows_added: Mapped[int] = mapped_column(Integer, default=0)
    rows_removed: Mapped[int] = mapped_column(Integer, default=0)
    status: Mapped[str] = mapped_column(String(20), default="running")  # running/success/partial/failed
    error: Mapped[Optional[str]] = mapped_column(Text)
    summary: Mapped[Optional[str]] = mapped_column(Text)


class IntegrityCheck(Base):
    """동기화 전후 데이터 무결성 검증 결과"""
    __tablename__ = "integrity_check"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    run_id: Mapped[Optional[int]] = mapped_column(Integer, index=True)  # SyncRun ID
    check_time: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    snapshot_path: Mapped[Optional[str]] = mapped_column(String(500))  # 전 DB 백업 경로
    snapshot_size_bytes: Mapped[Optional[int]] = mapped_column(BigInteger)
    # 변화 측정
    table_name: Mapped[str] = mapped_column(String(40), index=True)
    metric: Mapped[str] = mapped_column(String(40))  # row_count/sum_supply/sum_amount/unique_parties
    before_value: Mapped[Optional[float]] = mapped_column(Float)
    after_value: Mapped[Optional[float]] = mapped_column(Float)
    delta: Mapped[Optional[float]] = mapped_column(Float)
    delta_pct: Mapped[Optional[float]] = mapped_column(Float)
    threshold_pct: Mapped[Optional[float]] = mapped_column(Float)  # 의심 임계값
    status: Mapped[str] = mapped_column(String(20), default="ok")  # ok/warning/critical/rolled_back
    note: Mapped[Optional[str]] = mapped_column(Text)


class UnmappedFileReview(Base):
    """LLM이 자동 분류 시도했으나 신뢰도 낮은 파일들 — 사용자 검토 대기열"""
    __tablename__ = "unmapped_file_review"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    file_registry_id: Mapped[Optional[int]] = mapped_column(Integer)
    file_path: Mapped[str] = mapped_column(String(1000))
    file_name: Mapped[str] = mapped_column(String(400))
    rel_path: Mapped[Optional[str]] = mapped_column(String(1000))
    suggested_domain: Mapped[Optional[str]] = mapped_column(String(40))
    confidence: Mapped[Optional[float]] = mapped_column(Float)
    llm_reasoning: Mapped[Optional[str]] = mapped_column(Text)
    sheet_summary: Mapped[Optional[str]] = mapped_column(Text)  # 시트·헤더 요약
    status: Mapped[str] = mapped_column(String(20), default="pending")  # pending/approved/rejected/auto_processed
    user_assigned_domain: Mapped[Optional[str]] = mapped_column(String(40))
    decided_at: Mapped[Optional[datetime]] = mapped_column(DateTime)
    decided_by: Mapped[Optional[str]] = mapped_column(String(40))
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, index=True)


class Document(Base):
    """인증서·특허·공증·납세증명·각종 회사 서류 마스터"""
    __tablename__ = "document"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(300), nullable=False)  # 표시 제목
    category: Mapped[Optional[str]] = mapped_column(String(30), index=True)  # 대분류: company/certification/product/mgmt_contract/etc
    doc_type: Mapped[Optional[str]] = mapped_column(String(40), index=True)
    issuer: Mapped[Optional[str]] = mapped_column(String(200))  # 발급기관
    doc_no: Mapped[Optional[str]] = mapped_column(String(100))  # 등록번호/문서번호
    issue_date: Mapped[Optional[date]] = mapped_column(Date)        # 최초 발급일/등록일
    effective_date: Mapped[Optional[date]] = mapped_column(Date)    # 효력 시작일
    expiry_date: Mapped[Optional[date]] = mapped_column(Date, index=True)  # 만료일
    renewal_cycle_months: Mapped[Optional[int]] = mapped_column(Integer)   # 갱신 주기(개월)
    next_renewal_date: Mapped[Optional[date]] = mapped_column(Date)        # 다음 갱신 예정일
    owner: Mapped[Optional[str]] = mapped_column(String(80))         # 담당자
    file_path: Mapped[Optional[str]] = mapped_column(String(1000))   # 절대 경로
    rel_path: Mapped[Optional[str]] = mapped_column(String(1000))    # 14.경영정보 기준 상대
    file_name: Mapped[Optional[str]] = mapped_column(String(400))
    file_size: Mapped[Optional[int]] = mapped_column(BigInteger)
    mime_type: Mapped[Optional[str]] = mapped_column(String(80))
    folder_category: Mapped[Optional[str]] = mapped_column(String(80))  # 발견된 폴더
    tags: Mapped[Optional[str]] = mapped_column(String(400))  # 콤마 구분 태그
    note: Mapped[Optional[str]] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(20), default="active")  # active/expired/superseded
    source: Mapped[str] = mapped_column(String(20), default="auto")    # auto/manual
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class KnowledgeChunk(Base):
    """벡터화 가능한 지식 청크 — 문서/거래처/계약/매출요약/FAQ 등.
    실제 임베딩 벡터는 ChromaDB에 저장, 여기는 메타데이터만.
    """
    __tablename__ = "knowledge_chunk"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    source_type: Mapped[str] = mapped_column(String(40), index=True)  # document/party/contract/sale_summary/manual_faq/conversation
    source_id: Mapped[str] = mapped_column(String(100), index=True)
    title: Mapped[Optional[str]] = mapped_column(String(400))
    content: Mapped[str] = mapped_column(Text, nullable=False)
    page_url: Mapped[Optional[str]] = mapped_column(String(400))  # 해당 페이지로 이동 링크
    chunk_metadata: Mapped[Optional[str]] = mapped_column(Text)  # JSON
    token_count: Mapped[Optional[int]] = mapped_column(Integer)
    embedding_status: Mapped[str] = mapped_column(String(20), default="pending")  # pending/embedded/failed/stale
    embedding_model: Mapped[Optional[str]] = mapped_column(String(80))
    vector_id: Mapped[Optional[str]] = mapped_column(String(80))  # ChromaDB 상의 ID
    content_hash: Mapped[Optional[str]] = mapped_column(String(64))  # 변경 감지
    last_embedded_at: Mapped[Optional[datetime]] = mapped_column(DateTime)
    last_retrieved_at: Mapped[Optional[datetime]] = mapped_column(DateTime)
    retrieval_count: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class ChatHistory(Base):
    """챗 대화 이력 — 모든 Q&A 저장. 자가 학습 + 토큰 사용량 추적."""
    __tablename__ = "chat_history"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    session_id: Mapped[Optional[str]] = mapped_column(String(40), index=True)
    query: Mapped[str] = mapped_column(Text, nullable=False)
    intent: Mapped[Optional[str]] = mapped_column(String(40), index=True)
    response_summary: Mapped[Optional[str]] = mapped_column(Text)
    response_kind: Mapped[Optional[str]] = mapped_column(String(40))
    rag_used: Mapped[str] = mapped_column(String(1), default="N")
    rag_chunks: Mapped[Optional[int]] = mapped_column(Integer)
    rag_chunk_ids: Mapped[Optional[str]] = mapped_column(Text)  # 콤마 구분 chunk id
    fast_match: Mapped[str] = mapped_column(String(1), default="N")
    model_used: Mapped[Optional[str]] = mapped_column(String(80))
    tokens_input: Mapped[Optional[int]] = mapped_column(Integer)
    tokens_output: Mapped[Optional[int]] = mapped_column(Integer)
    elapsed_ms: Mapped[Optional[int]] = mapped_column(Integer)
    user_feedback: Mapped[Optional[str]] = mapped_column(String(10))  # good/bad/null
    feedback_note: Mapped[Optional[str]] = mapped_column(Text)
    is_indexed: Mapped[str] = mapped_column(String(1), default="N")  # 자가학습용 벡터화 여부
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, index=True)


class SyncRunDetail(Base):
    """동기화 실행의 파일별 처리 결과"""
    __tablename__ = "sync_run_detail"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    run_id: Mapped[int] = mapped_column(Integer, ForeignKey("sync_run.id"), index=True)
    file_path: Mapped[str] = mapped_column(String(1000))
    file_name: Mapped[str] = mapped_column(String(300))
    domain: Mapped[Optional[str]] = mapped_column(String(40))
    action: Mapped[str] = mapped_column(String(20))  # processed/skipped_unchanged/skipped_not_latest/unmapped/error
    rows_added: Mapped[int] = mapped_column(Integer, default=0)
    rows_removed: Mapped[int] = mapped_column(Integer, default=0)
    error: Mapped[Optional[str]] = mapped_column(Text)
    duration_ms: Mapped[Optional[int]] = mapped_column(Integer)
    ts: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class ReportTemplate(Base):
    """B5: 보고서 양식 (사용자가 업로드한 xlsx 양식)"""
    __tablename__ = "report_template"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    description: Mapped[Optional[str]] = mapped_column(Text)
    file_path: Mapped[str] = mapped_column(String(1000))  # 디스크 절대경로
    file_name: Mapped[str] = mapped_column(String(300))   # 원본 파일명
    file_size: Mapped[Optional[int]] = mapped_column(Integer)
    placeholders_json: Mapped[Optional[str]] = mapped_column(Text)  # 발견된 placeholder 목록 (JSON 배열)
    category: Mapped[Optional[str]] = mapped_column(String(20), default="", index=True)  # '', closing(결산보고), financial(재무제표)
    file_kind: Mapped[Optional[str]] = mapped_column(String(10), default="xlsx")  # xlsx / pdf
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    last_used_at: Mapped[Optional[datetime]] = mapped_column(DateTime)
    use_count: Mapped[int] = mapped_column(Integer, default=0)


class ImportBatch(Base):
    """B19: 업로드 적용 배치 — 되돌리기(롤백)용. 적용된 행 id 기록"""
    __tablename__ = "import_batch"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    ts: Mapped[datetime] = mapped_column(DateTime, default=datetime.now, index=True)
    domain: Mapped[str] = mapped_column(String(20))      # sale / purchase
    kind: Mapped[Optional[str]] = mapped_column(String(20))   # xlsx / csv / ai
    count: Mapped[int] = mapped_column(Integer, default=0)
    row_ids: Mapped[Optional[str]] = mapped_column(Text)  # 적용된 행 id JSON 배열
    note: Mapped[Optional[str]] = mapped_column(String(300))
    client_ip: Mapped[Optional[str]] = mapped_column(String(60))
    undone: Mapped[str] = mapped_column(String(1), default="N")  # Y=되돌림


class ActivityLog(Base):
    """B14: 활동 로그 — 모든 작업 기록"""
    __tablename__ = "activity_log"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    ts: Mapped[datetime] = mapped_column(DateTime, default=datetime.now, index=True)
    category: Mapped[Optional[str]] = mapped_column(String(40), index=True)  # 매출/설정/인증/...
    action: Mapped[str] = mapped_column(String(300))
    method: Mapped[Optional[str]] = mapped_column(String(10))
    path: Mapped[Optional[str]] = mapped_column(String(500))
    status_code: Mapped[Optional[int]] = mapped_column(Integer)
    client_ip: Mapped[Optional[str]] = mapped_column(String(60))
    user: Mapped[Optional[str]] = mapped_column(String(60))
    duration_ms: Mapped[Optional[int]] = mapped_column(Integer)


class Setting(Base):
    """B9: 전역 설정 — key-value 저장소"""
    __tablename__ = "app_setting"
    key: Mapped[str] = mapped_column(String(80), primary_key=True)
    value: Mapped[Optional[str]] = mapped_column(Text)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class CompanyInfo(Base):
    """B7: 회사 기본정보 (단일 행, id=1 고정). 보고서 placeholder가 참조."""
    __tablename__ = "company_info"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, default=1)
    name: Mapped[str] = mapped_column(String(200), default="(주)인비즈")          # 회사명
    name_en: Mapped[Optional[str]] = mapped_column(String(200))                   # 영문명
    biz_no: Mapped[Optional[str]] = mapped_column(String(40))                     # 사업자등록번호
    corp_no: Mapped[Optional[str]] = mapped_column(String(40))                    # 법인등록번호
    ceo: Mapped[Optional[str]] = mapped_column(String(100))                       # 대표자
    established: Mapped[Optional[str]] = mapped_column(String(40))                # 설립일
    address: Mapped[Optional[str]] = mapped_column(String(400))                   # 주소
    phone: Mapped[Optional[str]] = mapped_column(String(60))                      # 대표 전화
    fax: Mapped[Optional[str]] = mapped_column(String(60))                        # 팩스
    email: Mapped[Optional[str]] = mapped_column(String(120))                     # 이메일
    website: Mapped[Optional[str]] = mapped_column(String(200))                   # 홈페이지
    industry: Mapped[Optional[str]] = mapped_column(String(200))                  # 업종/사업분야
    capital: Mapped[Optional[float]] = mapped_column(Numeric(18, 2), default=0)   # 자본금
    employee_count: Mapped[Optional[int]] = mapped_column(Integer, default=0)     # 임직원 수
    executives_json: Mapped[Optional[str]] = mapped_column(Text)   # 임원 [{name,title,note}]
    shareholders_json: Mapped[Optional[str]] = mapped_column(Text) # 주주 [{name,shares,ratio,note}]
    note: Mapped[Optional[str]] = mapped_column(Text)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class ReportSnapshot(Base):
    """B6: 보고서 저장본 — 분석·갱신·수기수정 후 저장한 스냅샷"""
    __tablename__ = "report_snapshot"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    template_id: Mapped[int] = mapped_column(Integer, ForeignKey("report_template.id"), index=True)
    template_name: Mapped[Optional[str]] = mapped_column(String(200))
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    note: Mapped[Optional[str]] = mapped_column(Text)
    cells_json: Mapped[str] = mapped_column(Text)  # {"시트!행!열": "값"} 매핑 (JSON)
    file_path: Mapped[Optional[str]] = mapped_column(String(1000))  # 저장된 xlsx 경로
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class TaxInvoice(Base):
    """전자세금계산서 — 매출(발행) / 매입(수신). 홈택스 연동은 ASP 키 등록 시 자동 발행."""
    __tablename__ = "tax_invoice"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    direction: Mapped[str] = mapped_column(String(10), index=True)   # sale=매출(발행) / purchase=매입(수신)
    doc_kind: Mapped[str] = mapped_column(String(20), default="세금계산서")  # 세금계산서 / 계산서(면세)
    invoice_no: Mapped[Optional[str]] = mapped_column(String(40))    # 국세청 승인번호(있으면)
    write_date: Mapped[Optional[date]] = mapped_column(Date, index=True)  # 작성일자
    issue_at: Mapped[Optional[datetime]] = mapped_column(DateTime)   # 발행/수신 일시
    send_date: Mapped[Optional[date]] = mapped_column(Date, index=True)   # 예약 발송일(status=scheduled)
    # 공급자(매출=우리, 매입=거래처) / 공급받는자(매출=거래처, 매입=우리)
    supplier_corp_no: Mapped[Optional[str]] = mapped_column(String(20))
    supplier_name: Mapped[Optional[str]] = mapped_column(String(200))
    supplier_email: Mapped[Optional[str]] = mapped_column(String(200))
    buyer_corp_no: Mapped[Optional[str]] = mapped_column(String(20))
    buyer_name: Mapped[Optional[str]] = mapped_column(String(200))
    buyer_email: Mapped[Optional[str]] = mapped_column(String(200))
    party_name: Mapped[Optional[str]] = mapped_column(String(200), index=True)  # 상대 거래처(간편표시)
    item_desc: Mapped[Optional[str]] = mapped_column(String(300))    # 대표 품목
    items_json: Mapped[Optional[str]] = mapped_column(Text)          # 품목 라인 [{품목,규격,수량,단가,공급가액,세액}]
    supply: Mapped[Optional[float]] = mapped_column(Numeric(18, 2), default=0)
    vat: Mapped[Optional[float]] = mapped_column(Numeric(18, 2), default=0)
    total: Mapped[Optional[float]] = mapped_column(Numeric(18, 2), default=0)
    status: Mapped[str] = mapped_column(String(20), default="draft", index=True)
    # draft(작성중)/ready(발행대기)/issued(발행완료)/sent(전송완료)/received(수신)/error
    issue_method: Mapped[Optional[str]] = mapped_column(String(20), default="manual")  # manual/hometax/popbill/barobill
    source: Mapped[Optional[str]] = mapped_column(String(20), default="manual")        # manual/email/hometax/api
    notified: Mapped[str] = mapped_column(String(1), default="N")    # 수신 알림 발송 여부
    note: Mapped[Optional[str]] = mapped_column(Text)
    raw_ref: Mapped[Optional[str]] = mapped_column(String(300))      # 이메일 Message-Id 등(중복 방지)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class CalendarEvent(Base):
    """캘린더 일정 — 계산서 발행 예정·지출·수입·미팅 등 스케줄 관리."""
    __tablename__ = "calendar_event"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    event_date: Mapped[date] = mapped_column(Date, index=True)       # 일정 날짜(반복이면 시작일)
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    category: Mapped[str] = mapped_column(String(20), default="etc", index=True)
    # invoice(계산서발행)/expense(지출)/income(수입)/contract(계약)/loan(차입)/meeting(미팅)/etc(기타)
    amount: Mapped[Optional[float]] = mapped_column(Numeric(18, 2))
    party_name: Mapped[Optional[str]] = mapped_column(String(200))
    time_text: Mapped[Optional[str]] = mapped_column(String(20))     # "14:00" 등(선택)
    repeat: Mapped[str] = mapped_column(String(10), default="none")  # none/weekly/monthly/yearly
    done: Mapped[str] = mapped_column(String(1), default="N")        # 완료 체크
    note: Mapped[Optional[str]] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


# ===== 은행·카드(자금) 관리 =====
class BankAccount(Base):
    """은행 계좌 마스터 — 신한/광주/하나/기업 등."""
    __tablename__ = "dim_bank_account"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    bank_name: Mapped[str] = mapped_column(String(40), index=True)         # 신한은행/광주은행/하나은행/기업은행
    bank_code: Mapped[Optional[str]] = mapped_column(String(10))           # 오픈뱅킹 은행코드(선택)
    account_no: Mapped[Optional[str]] = mapped_column(String(40))          # 계좌번호
    account_alias: Mapped[Optional[str]] = mapped_column(String(80))       # 별칭/용도(주거래/급여/세금 등)
    account_type: Mapped[Optional[str]] = mapped_column(String(20), default="입출금")  # 입출금/적금/외화/기타
    holder: Mapped[Optional[str]] = mapped_column(String(80))              # 예금주
    balance: Mapped[float] = mapped_column(Numeric(18, 2), default=0)      # 현재 잔액
    balance_date: Mapped[Optional[date]] = mapped_column(Date)             # 잔액 기준일
    currency: Mapped[str] = mapped_column(String(5), default="KRW")
    fintech_use_num: Mapped[Optional[str]] = mapped_column(String(40))     # 오픈뱅킹 핀테크이용번호(선택)
    active: Mapped[str] = mapped_column(String(1), default="Y")
    sort_order: Mapped[int] = mapped_column(Integer, default=0)
    note: Mapped[Optional[str]] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class BankTransaction(Base):
    """은행 거래내역 — 입금/출금/이체."""
    __tablename__ = "fact_bank_tx"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    account_id: Mapped[int] = mapped_column(Integer, ForeignKey("dim_bank_account.id"), index=True)
    tx_date: Mapped[Optional[date]] = mapped_column(Date, index=True)
    tx_time: Mapped[Optional[str]] = mapped_column(String(10))
    direction: Mapped[Optional[str]] = mapped_column(String(10), index=True)  # in(입금)/out(출금·이체)
    type_text: Mapped[Optional[str]] = mapped_column(String(20))           # 원문 거래구분(입금/출금/이체/이자 등)
    amount: Mapped[float] = mapped_column(Numeric(18, 2), default=0)       # 거래금액(양수)
    balance_after: Mapped[Optional[float]] = mapped_column(Numeric(18, 2))  # 거래후잔액
    counterparty: Mapped[Optional[str]] = mapped_column(String(200))       # 적요/내용/상대방
    category: Mapped[Optional[str]] = mapped_column(String(30), index=True)  # 매출/매입/급여/세금/카드대금/기타
    memo: Mapped[Optional[str]] = mapped_column(Text)
    source: Mapped[str] = mapped_column(String(20), default="upload")      # upload/manual/openbanking
    raw_ref: Mapped[Optional[str]] = mapped_column(String(120), index=True)  # 중복방지 해시
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class Card(Base):
    """카드 마스터 — 우리/광주/하나 등. 한도·출금일 관리."""
    __tablename__ = "dim_card"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    card_name: Mapped[str] = mapped_column(String(80), index=True)         # 별칭/카드명
    issuer: Mapped[Optional[str]] = mapped_column(String(40), index=True)  # 우리카드/광주카드/하나카드
    card_no_last4: Mapped[Optional[str]] = mapped_column(String(8))        # 끝 4자리
    card_type: Mapped[Optional[str]] = mapped_column(String(10), default="신용")  # 신용/체크
    credit_limit: Mapped[float] = mapped_column(Numeric(18, 2), default=0)  # 한도
    billing_day: Mapped[Optional[int]] = mapped_column(Integer)            # 출금(결제)일 — 매월 N일
    payment_account_id: Mapped[Optional[int]] = mapped_column(Integer, ForeignKey("dim_bank_account.id"))  # 결제 출금계좌
    active: Mapped[str] = mapped_column(String(1), default="Y")
    sort_order: Mapped[int] = mapped_column(Integer, default=0)
    note: Mapped[Optional[str]] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class CardTransaction(Base):
    """카드 이용(승인) 내역."""
    __tablename__ = "fact_card_tx"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    card_id: Mapped[int] = mapped_column(Integer, ForeignKey("dim_card.id"), index=True)
    tx_date: Mapped[Optional[date]] = mapped_column(Date, index=True)
    amount: Mapped[float] = mapped_column(Numeric(18, 2), default=0)
    merchant: Mapped[Optional[str]] = mapped_column(String(200))           # 가맹점/이용처
    category: Mapped[Optional[str]] = mapped_column(String(30), index=True)
    installment: Mapped[Optional[str]] = mapped_column(String(20))         # 할부(일시불/N개월)
    memo: Mapped[Optional[str]] = mapped_column(Text)
    source: Mapped[str] = mapped_column(String(20), default="upload")
    raw_ref: Mapped[Optional[str]] = mapped_column(String(120), index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
