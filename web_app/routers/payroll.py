# -*- coding: utf-8 -*-
"""급여 라우터 — 조회 + 급여명세서 PDF(암호화) 이메일 발송"""
import io
import os
import re
import json
from datetime import datetime, date
from fastapi import APIRouter, Request, Depends, Form
from fastapi.responses import HTMLResponse, RedirectResponse, StreamingResponse, JSONResponse
from sqlalchemy import select, func, or_
from sqlalchemy.orm import Session

from database import get_db
from helpers import templates
from models import Payroll, Employee

router = APIRouter()

# ---------- 한글 폰트 등록 (PDF용, 1회) ----------
_KR_FONT = None
_KR_BOLD = None


def _ensure_font():
    """malgun(맑은 고딕) 우선 등록. 반환: (regular_name, bold_name)."""
    global _KR_FONT, _KR_BOLD
    if _KR_FONT:
        return _KR_FONT, _KR_BOLD
    from reportlab.pdfbase import pdfmetrics
    from reportlab.pdfbase.ttfonts import TTFont
    reg_cand = [
        r"C:\Windows\Fonts\malgun.ttf",
        os.path.join(os.path.dirname(os.path.dirname(__file__)), "fonts", "NanumGothic.ttf"),
        "/usr/share/fonts/truetype/nanum/NanumGothic.ttf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
    ]
    bold_cand = [
        r"C:\Windows\Fonts\malgunbd.ttf",
        os.path.join(os.path.dirname(os.path.dirname(__file__)), "fonts", "NanumGothicBold.ttf"),
        "/usr/share/fonts/truetype/nanum/NanumGothicBold.ttf",
    ]
    rf = next((p for p in reg_cand if os.path.exists(p)), None)
    if rf:
        try:
            pdfmetrics.registerFont(TTFont("KR", rf)); _KR_FONT = "KR"
        except Exception:
            _KR_FONT = "Helvetica"
    else:
        _KR_FONT = "Helvetica"
    bf = next((p for p in bold_cand if os.path.exists(p)), None)
    if bf:
        try:
            pdfmetrics.registerFont(TTFont("KRB", bf)); _KR_BOLD = "KRB"
        except Exception:
            _KR_BOLD = _KR_FONT
    else:
        _KR_BOLD = _KR_FONT
    return _KR_FONT, _KR_BOLD


def _parse_i(s):
    if s is None or s == "":
        return None
    try:
        return int(s)
    except (ValueError, TypeError):
        return None


def _won(v):
    try:
        return f"{int(round(float(v or 0))):,}"
    except Exception:
        return "0"


def _payslip_text(p) -> str:
    """Payroll 1건 → 급여명세서 텍스트."""
    pays = [("기본급", p.basic), ("식대", p.meal), ("차량유지", p.car), ("연구수당", p.research),
            ("기타수당", p.other_allow), ("연차수당", p.annual_leave), ("연장근로", p.overtime),
            ("야간근로", p.night), ("상여", p.bonus)]
    deds = [("국민연금", p.pension), ("건강보험", p.health), ("장기요양", p.longterm), ("고용보험", p.employment),
            ("소득세", p.income_tax), ("지방소득세", p.local_tax), ("기타공제", p.other_deduction)]
    lines = [f"[{p.period}] 급여명세서 — {p.employee_name} ({p.department or ''})", ""]
    lines.append("■ 지급 항목")
    for k, v in pays:
        if v:
            lines.append(f"  · {k}: {_won(v)}원")
    lines.append(f"  ─ 지급 합계: {_won(p.gross_pay)}원")
    lines.append("")
    lines.append("■ 공제 항목")
    for k, v in deds:
        if v:
            lines.append(f"  · {k}: {_won(v)}원")
    lines.append(f"  ─ 공제 합계: {_won(p.total_deduction)}원")
    lines.append("")
    lines.append(f"■ 실 수령액: {_won(p.net_pay)}원")
    lines.append("")
    lines.append("※ 본 명세서는 (주)인비즈 경영관리 시스템에서 자동 발송되었습니다.")
    return "\n".join(lines)


def _emp_obj(db, p):
    """Payroll 행에 대응하는 Employee 객체 (사번 우선, 없으면 이름)."""
    emp = None
    if p.employee_code:
        emp = db.get(Employee, p.employee_code)
    if not emp and p.employee_name:
        emp = db.execute(select(Employee).where(Employee.name == p.employee_name)).scalars().first()
    return emp


def _emp_email(db, p) -> str:
    """Payroll 행의 직원 이메일 조회 (사번 우선, 없으면 이름)."""
    emp = _emp_obj(db, p)
    return (emp.email or "").strip() if emp else ""


# ───────────────────────── 4대보험 요율 + 자동계산 ─────────────────────────
# 근로자 부담분 기본 요율(%). settings(pay_rate_*)로 변경 가능.
_RATE_DEFAULTS = {
    "pension": 4.5,        # 국민연금(근로자) — 회사분도 동일 요율
    "health": 3.545,       # 건강보험(근로자) — 회사분도 동일 요율
    "longterm": 12.95,     # 장기요양 = 건강보험료 × %
    "employment": 0.9,     # 고용보험(근로자)
    "local_tax": 10.0,     # 지방소득세 = 소득세 × %
    "emp_employment": 1.15,  # 고용보험(회사) — 실업급여 0.9 + 고용안정·직업능력 0.25(150인 미만)
    "accident": 0.7,       # 산재보험(회사 전액) — 업종 평균(업종별 상이)
    "pension_cap": 6370000,    # 국민연금 기준소득월액 상한(원)
    "pension_floor": 400000,   # 국민연금 기준소득월액 하한(원)
    "meal_taxfree": 200000,    # 식대 비과세 한도(월, 원)
}


def _rates() -> dict:
    """설정 오버라이드가 있으면 반영한 요율 딕셔너리."""
    r = dict(_RATE_DEFAULTS)
    try:
        import settings_store as ss
        for k in r:
            v = ss.get(f"pay_rate_{k}")
            if v not in (None, ""):
                try:
                    r[k] = float(v)
                except (ValueError, TypeError):
                    pass
    except Exception:
        pass
    return r


def _round10(x):
    """원단위 절사(10원 단위)."""
    try:
        return int(float(x) // 10 * 10)
    except (ValueError, TypeError):
        return 0


PAY_KEYS = ["basic", "meal", "car", "research", "other_allow",
            "annual_leave", "overtime", "night", "bonus"]
DED_KEYS = ["pension", "health", "longterm", "employment",
            "income_tax", "local_tax", "other_deduction"]


def _calc_deductions(items: dict, pension_enrolled: bool, rates: dict) -> dict:
    """지급항목 dict → 4대보험 공제 자동계산(소득세 제외)."""
    gross = sum(float(items.get(k) or 0) for k in PAY_KEYS)
    taxfree = min(float(items.get("meal") or 0), rates["meal_taxfree"])
    base = max(gross - taxfree, 0)  # 과세 보수월액
    pen_base = min(max(base, rates["pension_floor"]), rates["pension_cap"])
    pension = _round10(pen_base * rates["pension"] / 100) if pension_enrolled else 0
    health = _round10(base * rates["health"] / 100)
    longterm = _round10(health * rates["longterm"] / 100)
    employment = _round10(base * rates["employment"] / 100)
    return {"gross": gross, "base": base, "pension": pension,
            "health": health, "longterm": longterm, "employment": employment}


def _calc_employer(items: dict, pension_enrolled: bool, rates: dict) -> dict:
    """지급항목 dict → 회사(사용자) 부담 4대보험 자동계산."""
    gross = sum(float(items.get(k) or 0) for k in PAY_KEYS)
    taxfree = min(float(items.get("meal") or 0), rates["meal_taxfree"])
    base = max(gross - taxfree, 0)
    pen_base = min(max(base, rates["pension_floor"]), rates["pension_cap"])
    pension = _round10(pen_base * rates["pension"] / 100) if pension_enrolled else 0
    health = _round10(base * rates["health"] / 100)
    longterm = _round10(health * rates["longterm"] / 100)
    employment = _round10(base * rates["emp_employment"] / 100)
    accident = _round10(base * rates["accident"] / 100)
    total = pension + health + longterm + employment + accident
    return {"pension": pension, "health": health, "longterm": longterm,
            "employment": employment, "accident": accident, "total": total}


def _payslip_pdf(p, emp=None) -> bytes:
    """Payroll 1건 → 첨부 이미지 양식의 급여명세서 PDF(bytes).
    emp.birth_date 가 있으면 앞 6자리(YYMMDD)로 열기 암호 설정.
    반환: 암호화된 PDF bytes (생년월일 없으면 암호 없이 반환)."""
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.units import mm
    from reportlab.lib import colors
    from reportlab.platypus import (SimpleDocTemplate, Table, TableStyle,
                                     Paragraph, Spacer)
    from reportlab.lib.styles import ParagraphStyle
    from reportlab.lib.enums import TA_CENTER

    F, FB = _ensure_font()

    def won(v):
        try:
            iv = int(round(float(v or 0)))
            return f"{iv:,}" if iv else ""
        except Exception:
            return ""

    # 회사명 / 지급일
    try:
        import settings_store as ss
        company = (ss.get("tax_corp_name", "") or "").strip() or "(주)인비즈"
        pay_day = (ss.get("payroll_pay_day", "") or "").strip() or "25"
    except Exception:
        company, pay_day = "(주)인비즈", "25"
    pay_date = f"{p.year}.{int(p.month):02d}.{int(pay_day):02d}" if p.year and p.month else ""

    # 직원 기본정보
    code = (emp.code if emp else p.employee_code) or ""
    name = (emp.name if emp else p.employee_name) or ""
    dept = (emp.department if emp else None) or p.department or ""
    rank = (emp.rank if emp else "") or ""
    bd = getattr(emp, "birth_date", None) if emp else None
    bd_str = bd.strftime("%Y.%m.%d") if bd else ""

    PURPLE = colors.HexColor("#6D28D9")
    HEAD_BG = colors.HexColor("#EDE9FE")
    LBL_BG = colors.HexColor("#F5F3FF")
    LINE = colors.HexColor("#C4B5FD")

    buf = io.BytesIO()
    doc = SimpleDocTemplate(buf, pagesize=A4,
                            leftMargin=18 * mm, rightMargin=18 * mm,
                            topMargin=16 * mm, bottomMargin=16 * mm,
                            title=f"{p.year}년{int(p.month):02d}월분 급여명세서")
    story = []
    title_st = ParagraphStyle("t", fontName=FB, fontSize=17, leading=22,
                              alignment=TA_CENTER, spaceAfter=4)
    small_r = ParagraphStyle("sr", fontName=F, fontSize=8.5, leading=11,
                             alignment=2, textColor=colors.HexColor("#475569"))
    story.append(Paragraph(f"{p.year}년 {int(p.month):02d}월분 <b>급여명세서</b>", title_st))
    story.append(Spacer(1, 2 * mm))
    story.append(Paragraph(f"회사명 : {company} &nbsp;&nbsp;|&nbsp;&nbsp; 지급일 : {pay_date}", small_r))
    story.append(Spacer(1, 2 * mm))

    # 사원 정보 (6열 × 2행)
    info = [
        ["사원코드", code, "사원명", name, "생년월일", bd_str],
        ["부서", dept, "직급", rank, "호봉", ""],
    ]
    info_tbl = Table(info, colWidths=[20 * mm, 30 * mm, 18 * mm, 30 * mm, 20 * mm, 26 * mm])
    info_tbl.setStyle(TableStyle([
        ("FONTNAME", (0, 0), (-1, -1), F),
        ("FONTSIZE", (0, 0), (-1, -1), 8.5),
        ("BACKGROUND", (0, 0), (0, -1), LBL_BG),
        ("BACKGROUND", (2, 0), (2, -1), LBL_BG),
        ("BACKGROUND", (4, 0), (4, -1), LBL_BG),
        ("FONTNAME", (0, 0), (0, -1), FB),
        ("FONTNAME", (2, 0), (2, -1), FB),
        ("FONTNAME", (4, 0), (4, -1), FB),
        ("GRID", (0, 0), (-1, -1), 0.5, LINE),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("TOPPADDING", (0, 0), (-1, -1), 4),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
        ("LEFTPADDING", (0, 0), (-1, -1), 5),
    ]))
    story.append(info_tbl)
    story.append(Spacer(1, 2 * mm))

    # 근로시간 (4열: 헤더 + 값) — 시간 데이터 미보유 시 양식만 유지
    hrs = [
        ["연장근로시간", "야간근로시간", "휴일근로시간", "통상시급(원)"],
        ["", "", "", ""],
    ]
    hrs_tbl = Table(hrs, colWidths=[36 * mm, 36 * mm, 36 * mm, 36 * mm])
    hrs_tbl.setStyle(TableStyle([
        ("FONTNAME", (0, 0), (-1, -1), F),
        ("FONTNAME", (0, 0), (-1, 0), FB),
        ("FONTSIZE", (0, 0), (-1, -1), 8.5),
        ("BACKGROUND", (0, 0), (-1, 0), HEAD_BG),
        ("ALIGN", (0, 0), (-1, -1), "CENTER"),
        ("GRID", (0, 0), (-1, -1), 0.5, LINE),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("TOPPADDING", (0, 0), (-1, -1), 4),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
    ]))
    story.append(hrs_tbl)
    story.append(Spacer(1, 1.5 * mm))
    story.append(Paragraph("(단위 : 원)", small_r))
    story.append(Spacer(1, 1 * mm))

    # 지급/공제 (4열)
    pays = [("기본급", p.basic), ("식대", p.meal), ("차량유지", p.car), ("연구수당", p.research),
            ("기타수당", p.other_allow), ("연차수당", p.annual_leave), ("연장근로", p.overtime),
            ("야간근로", p.night), ("상여", p.bonus)]
    deds = [("국민연금", p.pension), ("건강보험", p.health), ("장기요양보험료", p.longterm),
            ("고용보험", p.employment), ("소득세", p.income_tax), ("지방소득세", p.local_tax),
            ("기타공제", p.other_deduction)]
    pays_d = [(k, won(v)) for k, v in pays if v]
    deds_d = [(k, won(v)) for k, v in deds if v]
    deds_d.append(("공제 액 계", won(p.total_deduction)))  # 공제 합계행
    n = max(len(pays_d), len(deds_d), 1)
    data = [["지급 내역", "지급 액", "공제 내역", "공제 액"]]
    for i in range(n):
        pl, pa = pays_d[i] if i < len(pays_d) else ("", "")
        dl, da = deds_d[i] if i < len(deds_d) else ("", "")
        data.append([pl, pa, dl, da])
    data.append(["지급 액 계", won(p.gross_pay), "차인지급액", won(p.net_pay)])

    ded_total_row = len(deds_d)        # 본문 내 '공제 액 계' 행 (헤더 제외 1-base → +0; +1 for header)
    sum_row = len(data) - 1            # 마지막 합계행
    main = Table(data, colWidths=[42 * mm, 30 * mm, 42 * mm, 30 * mm])
    main.setStyle(TableStyle([
        ("FONTNAME", (0, 0), (-1, -1), F),
        ("FONTSIZE", (0, 0), (-1, -1), 9),
        # 헤더
        ("FONTNAME", (0, 0), (-1, 0), FB),
        ("BACKGROUND", (0, 0), (-1, 0), HEAD_BG),
        ("ALIGN", (0, 0), (-1, 0), "CENTER"),
        # 금액 우측정렬
        ("ALIGN", (1, 1), (1, -1), "RIGHT"),
        ("ALIGN", (3, 1), (3, -1), "RIGHT"),
        # 항목 라벨 약한 음영
        ("BACKGROUND", (0, 1), (0, -2), LBL_BG),
        ("BACKGROUND", (2, 1), (2, -2), LBL_BG),
        # 공제 액 계 행 강조
        ("FONTNAME", (2, ded_total_row), (3, ded_total_row), FB),
        ("BACKGROUND", (2, ded_total_row), (3, ded_total_row), HEAD_BG),
        # 마지막 합계행 강조
        ("FONTNAME", (0, sum_row), (-1, sum_row), FB),
        ("BACKGROUND", (0, sum_row), (-1, sum_row), HEAD_BG),
        ("TEXTCOLOR", (1, sum_row), (1, sum_row), PURPLE),
        ("TEXTCOLOR", (3, sum_row), (3, sum_row), PURPLE),
        ("GRID", (0, 0), (-1, -1), 0.5, LINE),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("TOPPADDING", (0, 0), (-1, -1), 3.5),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 3.5),
        ("LEFTPADDING", (0, 0), (-1, -1), 6),
        ("RIGHTPADDING", (0, 0), (-1, -1), 6),
    ]))
    story.append(main)
    story.append(Spacer(1, 4 * mm))

    # 계산 방법
    calc_st = ParagraphStyle("c", fontName=F, fontSize=8, leading=12,
                             textColor=colors.HexColor("#475569"))
    story.append(Paragraph("<b>■ 계산 방법</b>", ParagraphStyle(
        "ch", fontName=FB, fontSize=9, leading=13, textColor=PURPLE)))
    story.append(Paragraph(
        "· 지급 액 계 = 기본급 + 제수당 + 상여 등 과세·비과세 지급항목 합계<br/>"
        "· 공제 액 계 = 국민연금 + 건강보험 + 장기요양 + 고용보험 + 소득세 + 지방소득세 등<br/>"
        "· 차인지급액(실수령액) = 지급 액 계 - 공제 액 계", calc_st))
    story.append(Spacer(1, 6 * mm))
    foot_st = ParagraphStyle("f", fontName=FB, fontSize=11, leading=15,
                             alignment=TA_CENTER, textColor=PURPLE)
    story.append(Paragraph("귀하의 노고에 감사드립니다.", foot_st))
    story.append(Spacer(1, 2 * mm))
    story.append(Paragraph(f"{company}", ParagraphStyle(
        "co", fontName=FB, fontSize=10, leading=13, alignment=TA_CENTER)))

    doc.build(story)
    pdf_bytes = buf.getvalue()

    # 생년월일 앞 6자리(YYMMDD)로 열기 암호 설정
    if bd:
        try:
            from pypdf import PdfReader, PdfWriter
            reader = PdfReader(io.BytesIO(pdf_bytes))
            writer = PdfWriter()
            for pg in reader.pages:
                writer.add_page(pg)
            pwd = bd.strftime("%y%m%d")
            writer.encrypt(pwd)
            out = io.BytesIO()
            writer.write(out)
            return out.getvalue()
        except Exception:
            return pdf_bytes  # 암호화 실패 시 평문 PDF
    return pdf_bytes


@router.get("", response_class=HTMLResponse)
def list_payroll(
    request: Request, db: Session = Depends(get_db),
    year: str = "", month: str = "", name: str = "",
    page: int = 1, per_page: int = 100,
):
    year_i = _parse_i(year)
    month_i = _parse_i(month)
    stmt = select(Payroll)
    if year_i: stmt = stmt.where(Payroll.year == year_i)
    if month_i: stmt = stmt.where(Payroll.month == month_i)
    if name: stmt = stmt.where(Payroll.employee_name.contains(name))

    total_count = db.scalar(select(func.count()).select_from(stmt.subquery()))
    total_gross = db.scalar(select(func.coalesce(func.sum(Payroll.gross_pay), 0)).select_from(stmt.subquery())) or 0
    total_net = db.scalar(select(func.coalesce(func.sum(Payroll.net_pay), 0)).select_from(stmt.subquery())) or 0

    rows = db.execute(
        stmt.order_by(Payroll.period.desc(), Payroll.employee_name)
        .offset((page - 1) * per_page).limit(per_page)
    ).scalars().all()

    # 직원 이메일·생년월일 맵 (사번/이름)
    emps = db.execute(select(Employee)).scalars().all()
    email_by_code = {e.code: (e.email or "") for e in emps}
    email_by_name = {e.name: (e.email or "") for e in emps}
    birth_by_code = {e.code: e.birth_date for e in emps}
    birth_by_name = {e.name: e.birth_date for e in emps}
    emails = {}
    births = {}
    for r in rows:
        emails[r.id] = (email_by_code.get(r.employee_code) or email_by_name.get(r.employee_name) or "")
        bd = birth_by_code.get(r.employee_code) or birth_by_name.get(r.employee_name)
        births[r.id] = bd.isoformat() if bd else ""

    years = list(range(2021, datetime.now().year + 1))
    cy = year_i or datetime.now().year
    monthly = []
    for m in range(1, 13):
        g = db.scalar(select(func.coalesce(func.sum(Payroll.gross_pay), 0)).where(
            Payroll.year == cy, Payroll.month == m)) or 0
        n = db.scalar(select(func.coalesce(func.sum(Payroll.net_pay), 0)).where(
            Payroll.year == cy, Payroll.month == m)) or 0
        cnt = db.scalar(select(func.count()).where(Payroll.year == cy, Payroll.month == m)) or 0
        monthly.append({"month": m, "count": cnt, "gross": float(g), "net": float(n)})

    try:
        import integrations as ig
        mail_ready = ig.mail_send_ready()
    except Exception:
        mail_ready = False

    return templates.TemplateResponse("payroll/list.html", {
        "request": request, "rows": rows, "emails": emails, "births": births, "mail_ready": mail_ready,
        "total_count": total_count, "total_gross": float(total_gross), "total_net": float(total_net),
        "years": years, "monthly": monthly,
        "filter": {"year": year_i, "month": month_i, "name": name},
        "page": page, "per_page": per_page,
        "total_pages": (total_count + per_page - 1) // per_page,
    })


def _parse_date(s):
    s = (s or "").strip()
    if not s:
        return None
    for fmt in ("%Y-%m-%d", "%Y.%m.%d", "%y%m%d", "%Y%m%d"):
        try:
            return datetime.strptime(s, fmt).date()
        except ValueError:
            continue
    return None


@router.post("/set-email")
def set_email(request: Request, db: Session = Depends(get_db),
              code: str = Form(""), name: str = Form(""), email: str = Form(""),
              birth_date: str = Form(""), back: str = Form("/payroll")):
    """직원 이메일·생년월일 등록/수정 (급여명세서 발송 + PDF 비밀번호용)."""
    emp = None
    if code.strip():
        emp = db.get(Employee, code.strip())
    if not emp and name.strip():
        emp = db.execute(select(Employee).where(Employee.name == name.strip())).scalars().first()
    if emp:
        emp.email = email.strip() or None
        bd = _parse_date(birth_date)
        if bd:
            emp.birth_date = bd
        db.commit()
    return RedirectResponse(f"{back}?email_saved=1", status_code=303)


@router.get("/payslip/{pid}.pdf")
def payslip_pdf(pid: int, db: Session = Depends(get_db)):
    """급여명세서 PDF 미리보기/다운로드 (생년월일 등록 시 암호화)."""
    p = db.get(Payroll, pid)
    if not p:
        return RedirectResponse("/payroll?mailerr=대상없음", status_code=303)
    emp = _emp_obj(db, p)
    pdf = _payslip_pdf(p, emp)
    fname = f"payslip_{p.period}_{(emp.name if emp else p.employee_name) or ''}.pdf"
    return StreamingResponse(
        io.BytesIO(pdf), media_type="application/pdf",
        headers={"Content-Disposition": f"inline; filename=payslip_{pid}.pdf",
                 "X-Filename": fname})


def _send_payslip(db, p, base_url=""):
    """급여명세서를 암호화 PDF로 첨부하여 직원 이메일로 발송."""
    import integrations as ig
    emp = _emp_obj(db, p)
    to = (emp.email or "").strip() if emp else ""
    if not to:
        return False, "이메일 미등록"
    bd = getattr(emp, "birth_date", None) if emp else None
    try:
        pdf = _payslip_pdf(p, emp)
    except Exception as e:
        return False, f"명세서 PDF 생성 실패: {e}"
    fname = f"급여명세서_{p.period}_{p.employee_name or ''}.pdf"
    if bd:
        pw_note = f"\n\n※ 첨부 PDF는 보안을 위해 암호화되어 있습니다. 열기 비밀번호: 생년월일 앞 6자리(YYMMDD), 예) {bd.strftime('%y%m%d')}"
    else:
        pw_note = "\n\n※ (생년월일 미등록 — PDF 비밀번호 미설정) 회사 관리자에게 생년월일 등록을 요청하세요."
    body = (f"{p.employee_name}님, {p.period} 급여명세서를 첨부합니다.\n"
            f"실수령액: {_won(p.net_pay)}원" + pw_note +
            "\n\n본 메일은 (주)인비즈 경영관리 시스템에서 자동 발송되었습니다.")
    ok, msg = ig.send_email(
        f"[급여명세서] {p.period} {p.employee_name}", body, to=to,
        attachments=[(fname, pdf, "application", "pdf")])
    if ok:
        try:
            from activity import log_event
            log_event("급여", f"{p.employee_name} {p.period} 급여명세서 PDF 이메일 발송 → {to}",
                      client_ip=(base_url or ""))
        except Exception:
            pass
    return ok, msg


@router.post("/email-one/{pid}")
def email_one(pid: int, request: Request, db: Session = Depends(get_db)):
    p = db.get(Payroll, pid)
    if not p:
        return RedirectResponse("/payroll?mailerr=대상없음", status_code=303)
    ok, msg = _send_payslip(db, p, base_url=str(request.client.host if request.client else ""))
    q = "sent=1" if ok else f"mailerr={msg}"
    return RedirectResponse(f"/payroll?year={p.year}&month={p.month}&{q}", status_code=303)


@router.post("/email-all")
def email_all(request: Request, db: Session = Depends(get_db),
              year: str = Form(""), month: str = Form("")):
    yi = _parse_i(year); mi = _parse_i(month)
    stmt = select(Payroll)
    if yi: stmt = stmt.where(Payroll.year == yi)
    if mi: stmt = stmt.where(Payroll.month == mi)
    rows = db.execute(stmt).scalars().all()
    sent = skipped = failed = 0
    ip = str(request.client.host if request.client else "")
    for p in rows:
        if not _emp_email(db, p):
            skipped += 1; continue
        ok, _ = _send_payslip(db, p, base_url=ip)
        if ok:
            sent += 1
        else:
            failed += 1
    return RedirectResponse(
        f"/payroll?year={year}&month={month}&bulk=발송 {sent} · 미등록 {skipped} · 실패 {failed}",
        status_code=303)


# ───────────────────────── 요율: AI 검색 + 저장 (반드시 /{pid} 라우트보다 먼저 등록) ─────────────────────────
_RATE_FIELDS = ("pension", "health", "longterm", "employment",
                "local_tax", "emp_employment", "accident",
                "pension_cap", "pension_floor", "meal_taxfree")


@router.post("/save-rates")
async def save_rates(request: Request):
    """폼에서 수정한 요율을 설정(pay_rate_*)에 저장 → 이후 모든 급여 등록에 적용."""
    form = await request.form()
    import settings_store as ss
    upd = {}
    for k in _RATE_FIELDS:
        v = form.get(f"pay_rate_{k}")
        if v not in (None, ""):
            upd[f"pay_rate_{k}"] = str(v).strip()
    if upd:
        ss.save(upd)
    try:
        from activity import log_event
        log_event("급여", "급여 요율 저장(요율 패널)")
    except Exception:
        pass
    return JSONResponse({"ok": True, "saved": len(upd)})


@router.post("/ai-rates")
async def ai_rates(request: Request):
    """AI(설정된 공급자)로 해당 연도 4대보험 요율을 검색해 제안값(JSON) 반환."""
    form = await request.form()
    year = (form.get("year") or "").strip() or str(datetime.now().year)
    try:
        import llm_provider
        ok, msg = llm_provider.provider_ready()
        if not ok:
            return JSONResponse({"ok": False, "error": f"AI가 설정되지 않았습니다: {msg}"})
        prompt = (
            f"대한민국 {year}년 기준 4대보험 '근로자 부담분' 요율과 국민연금 기준소득월액 상한·하한, "
            "식대 비과세 월 한도를 알려줘. 아래 JSON 형식으로만 답하라(숫자만, % 기호 없이 숫자로):\n"
            '{"pension":4.5,"health":3.545,"longterm":12.95,"employment":0.9,"local_tax":10,'
            '"pension_cap":6370000,"pension_floor":390000,"meal_taxfree":200000}\n'
            "pension·health·employment·local_tax는 %, longterm은 건강보험료 대비 %, "
            "pension_cap·pension_floor·meal_taxfree는 원(KRW) 정수.")
        txt = llm_provider.chat_complete(
            [{"role": "system", "content": "너는 한국 4대보험 요율 정보 도우미다. 반드시 JSON만 출력한다."},
             {"role": "user", "content": prompt}],
            temperature=0.0, json_mode=True, max_tokens=300)
        m = re.search(r"\{.*\}", txt, re.S)
        data = json.loads(m.group(0) if m else txt)
        rates = {}
        for k in _RATE_FIELDS:
            if data.get(k) is not None:
                try:
                    rates[k] = float(data[k])
                except (ValueError, TypeError):
                    pass
        if not rates:
            return JSONResponse({"ok": False, "error": "AI 응답에서 요율을 해석하지 못했습니다."})
        return JSONResponse({
            "ok": True, "rates": rates,
            "note": (f"{year}년 AI 제안값입니다. AI는 최신 고시와 다를 수 있으니 반드시 확인 후 "
                     f"[💾 기본값으로 저장]하세요. (출처: {llm_provider.active_label()})")})
    except Exception as e:
        return JSONResponse({"ok": False, "error": str(e)[:200]})


# ───────────────────────── 급여 항목 등록/수정 (직원 기준 자동계산) ─────────────────────────
def _f(v):
    try:
        return float(str(v).replace(",", "").strip() or 0)
    except (ValueError, TypeError):
        return 0.0


def _active_employees(db):
    return db.execute(select(Employee).where(
        or_(Employee.active.is_(None), Employee.active != "퇴직"))
        .order_by(Employee.department, Employee.name)).scalars().all()


def _form_ctx(db, request, row=None, year=None, month=None, code=None):
    import json
    emps = _active_employees(db)
    emp_map = {}
    for e in emps:
        raw = float(e.base_salary or 0)
        is_annual = (e.salary_annual or "N") == "Y"
        monthly = round(raw / 12) if is_annual else raw
        annual = raw if is_annual else raw * 12
        emp_map[e.code] = {
            "name": e.name, "monthly": monthly, "annual": annual, "is_annual": is_annual,
            "pension": (e.pension_enrolled or "Y") != "N",
            "department": e.department or "", "rank": e.rank or "",
        }
    rates = _rates()
    return {
        "request": request, "row": row, "employees": emps,
        "emp_map_json": json.dumps(emp_map, ensure_ascii=False),
        "rates": rates, "rates_json": json.dumps(rates),
        "sel_code": code or (row.employee_code if row else ""),
        "year": year or (row.year if row else datetime.now().year),
        "month": month or (row.month if row else datetime.now().month),
        "years": list(range(2021, datetime.now().year + 2)),
    }


@router.get("/new", response_class=HTMLResponse)
def new_payroll(request: Request, db: Session = Depends(get_db),
                year: str = "", month: str = "", code: str = ""):
    ctx = _form_ctx(db, request, None, _parse_i(year), _parse_i(month), code.strip() or None)
    return templates.TemplateResponse("payroll/form.html", ctx)


@router.get("/{pid}/edit", response_class=HTMLResponse)
def edit_payroll(pid: int, request: Request, db: Session = Depends(get_db)):
    p = db.get(Payroll, pid)
    if not p:
        return RedirectResponse("/payroll?mailerr=대상없음", status_code=303)
    return templates.TemplateResponse("payroll/form.html", _form_ctx(db, request, p))


def _save_payroll_from_form(db, form, row=None):
    """폼 → Payroll 저장(생성/수정). 반환: (payroll, error)."""
    code = (form.get("employee_code") or "").strip()
    yi = _parse_i(form.get("year")); mi = _parse_i(form.get("month"))
    if not code or not yi or not mi:
        return None, "직원·연도·월은 필수입니다."
    emp = db.get(Employee, code)
    pays = {k: _f(form.get(k)) for k in PAY_KEYS}
    deds = {k: _f(form.get(k)) for k in DED_KEYS}
    gross = sum(pays.values()); total = sum(deds.values())
    if row is None:
        row = Payroll()
        db.add(row)
    row.period = f"{yi}-{mi:02d}"; row.year = yi; row.month = mi
    row.employee_code = code
    row.employee_name = (emp.name if emp else (form.get("employee_name") or "").strip())
    row.department = (emp.department if emp else None)
    for k, v in pays.items():
        setattr(row, k, v)
    for k, v in deds.items():
        setattr(row, k, v)
    row.gross_pay = gross; row.total_deduction = total; row.net_pay = gross - total
    # 회사 부담 4대보험 — 폼 계산값 우선, 없으면 서버 재계산
    emp_total = _f(form.get("employer_insurance"))
    if not emp_total:
        enrolled = (emp.pension_enrolled or "Y") != "N" if emp else True
        emp_total = _calc_employer(pays, enrolled, _rates())["total"]
    row.employer_insurance = emp_total
    row.note = (form.get("note") or "").strip() or None
    db.commit()
    return row, None


@router.post("")
async def create_payroll(request: Request, db: Session = Depends(get_db)):
    form = await request.form()
    code = (form.get("employee_code") or "").strip()
    yi = _parse_i(form.get("year")); mi = _parse_i(form.get("month"))
    if code and yi and mi:
        dup = db.execute(select(Payroll).where(
            Payroll.employee_code == code, Payroll.year == yi, Payroll.month == mi)).scalars().first()
        if dup:
            return RedirectResponse(f"/payroll/{dup.id}/edit?dup=1", status_code=303)
    row, err = _save_payroll_from_form(db, form, None)
    if err:
        return RedirectResponse(f"/payroll/new?err={err}", status_code=303)
    try:
        from activity import log_event
        log_event("급여", f"{row.employee_name} {row.period} 급여 등록 (실수령 {_won(row.net_pay)}원)")
    except Exception:
        pass
    return RedirectResponse(f"/payroll?year={row.year}&month={row.month}&saved=1", status_code=303)


@router.post("/{pid}")
async def update_payroll(pid: int, request: Request, db: Session = Depends(get_db)):
    p = db.get(Payroll, pid)
    if not p:
        return RedirectResponse("/payroll?mailerr=대상없음", status_code=303)
    form = await request.form()
    row, err = _save_payroll_from_form(db, form, p)
    if err:
        return RedirectResponse(f"/payroll/{pid}/edit?err={err}", status_code=303)
    return RedirectResponse(f"/payroll?year={row.year}&month={row.month}&updated=1", status_code=303)
