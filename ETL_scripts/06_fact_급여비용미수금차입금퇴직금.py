# -*- coding: utf-8 -*-
"""P6: FACT_급여, 비용, 미수금, 차입금, 퇴직금 일괄 적재"""
import pandas as pd
import re
from datetime import datetime
from common import SRC, load_master, save_master, write_dim_or_fact, normalize_name, year_quarter_half


def build_party_map(wb):
    ws = wb["10_DIM_거래처"]
    m = {}
    for row in ws.iter_rows(min_row=2, values_only=True):
        if row[0] and row[1]:
            m[normalize_name(row[1])] = (row[0], row[1])
    return m


def build_emp_map(wb):
    ws = wb["13_DIM_직원"]
    m = {}
    for row in ws.iter_rows(min_row=2, values_only=True):
        if row[0] and row[1]:
            m[normalize_name(row[1])] = row[0]
    return m


def f(v, default=0):
    try:
        return float(v) if pd.notna(v) else default
    except Exception:
        return default


# ==================== 22. FACT_급여 ====================
def load_급여(emp_map):
    """부서별 인건비 2023/2024 + 급여대장 25.1월/25.2월"""
    rows = []

    # 부서별 인건비 2024 (header=3), 2023 (header=0) — long-format
    for src_path, sh, header_row, year in [
        (SRC["부서인건비"], "2024", 3, 2024),
        (SRC["부서인건비"], "2023", 0, 2023),
    ]:
        try:
            df = pd.read_excel(src_path, sheet_name=sh, header=header_row)
        except Exception as e:
            print(f"  부서인건비/{sh} 오류: {e}")
            continue

        cols = list(df.columns)
        # 월구분 컬럼은 B열 (2번째). 예: "1월급여", "12월급여"
        # B열 값에서 월 추출
        month_col_idx = 1  # B열
        sabeon_col = next((c for c in cols if "사번" in str(c)), None)
        name_col = next((c for c in cols if "사원명" in str(c) or "성명" in str(c)), None)
        dept_col = next((c for c in cols if "부서" in str(c)), None)

        if not name_col:
            print(f"  부서인건비/{sh}: 사원명 컬럼 없음")
            continue

        for idx, r in df.iterrows():
            nm = normalize_name(r[name_col])
            if not nm or any(s in nm for s in ["합계", "소계"]):
                continue
            # 월 추출 — B열 (위치 기반)
            month = None
            try:
                val_b = r.iloc[month_col_idx]
                if pd.notna(val_b):
                    m = re.search(r"(\d+)월", str(val_b))
                    if m:
                        month = int(m.group(1))
            except Exception:
                pass
            if not month:
                continue
            귀속 = f"{year}-{month:02d}"
            sabeon = emp_map.get(nm) or (str(r[sabeon_col]) if sabeon_col and pd.notna(r[sabeon_col]) else None)
            dept = normalize_name(r[dept_col]) if dept_col and pd.notna(r.get(dept_col)) else None

            def gv(*keys):
                for k in keys:
                    for c in cols:
                        if k in str(c):
                            return r.get(c)
                return None

            기본 = f(gv("기본급"))
            식대 = f(gv("식대"))
            차량 = f(gv("차량유지비"))
            연구 = f(gv("연구수당"))
            기타수 = f(gv("기타수당"))
            연차 = f(gv("연차수당"))
            연장 = f(gv("연장근로"))
            야간 = f(gv("야간근로"))
            성과 = f(gv("성과급"))
            지급합계 = f(gv("총급여", "지급합계")) or (기본 + 식대 + 차량 + 연구 + 기타수 + 연차 + 연장 + 야간 + 성과)
            국민 = f(gv("국민연금"))
            건강 = f(gv("건강보험"))
            장기 = f(gv("장기요양"))
            고용 = f(gv("고용보험"))
            소득 = f(gv("소득세"))
            지방 = f(gv("지방소득세"))
            기타공 = f(gv("기타공제"))
            공제합 = f(gv("공제합계")) or (국민 + 건강 + 장기 + 고용 + 소득 + 지방 + 기타공)
            실지급 = 지급합계 - 공제합
            기업4대 = f(gv("4대보험(기업)", "4대보험 기업"))

            if 지급합계 == 0:
                continue

            rows.append({
                "귀속년월": 귀속, "년": year, "월": month,
                "사번": sabeon, "성명": nm, "부서": dept,
                "기본급": 기본, "식대": 식대, "차량유지비": 차량,
                "연구수당": 연구, "기타수당": 기타수, "연차수당": 연차,
                "연장근로수당": 연장, "야간근로수당": 야간, "성과급": 성과,
                "지급합계": 지급합계,
                "국민연금": 국민, "건강보험": 건강, "장기요양": 장기, "고용보험": 고용,
                "소득세": 소득, "지방소득세": 지방, "기타공제": 기타공,
                "공제합계": 공제합, "실지급액": 실지급,
                "4대보험(기업부담)": 기업4대,
                "원본파일": "부서별 인건비_23-24.v1.xlsx",
                "원본행": idx + header_row + 2,
            })
        print(f"  부서인건비/{sh}: 누적 {len(rows)}건")

    # 급여대장2025 25.1월/25.2월
    for sh, year, month in [("25.1월", 2025, 1), ("25.2월", 2025, 2)]:
        try:
            df = pd.read_excel(SRC["급여대장"], sheet_name=sh, header=2)
        except Exception:
            continue
        cols = list(df.columns)
        name_col = next((c for c in cols if "사원명" in str(c) or "성명" in str(c) or "이름" in str(c)), None)
        sabeon_col = next((c for c in cols if "사번" in str(c)), None)
        dept_col = next((c for c in cols if "부서" in str(c)), None)
        if not name_col:
            continue

        for idx, r in df.iterrows():
            nm = normalize_name(r[name_col])
            if not nm or any(s in nm for s in ["합계", "소계"]):
                continue
            귀속 = f"{year}-{month:02d}"
            sabeon = emp_map.get(nm) or (str(r[sabeon_col]) if sabeon_col and pd.notna(r[sabeon_col]) else None)
            dept = normalize_name(r[dept_col]) if dept_col and pd.notna(r.get(dept_col)) else None

            def gv(*keys):
                for k in keys:
                    for c in cols:
                        if k in str(c):
                            return r.get(c)
                return None

            기본 = f(gv("기본급"))
            지급합계 = f(gv("지급합계", "총급여"))
            공제합 = f(gv("공제합계"))
            실지급 = f(gv("실지급액", "실수령"))
            if 지급합계 == 0 and 실지급 == 0:
                continue
            rows.append({
                "귀속년월": 귀속, "년": year, "월": month,
                "사번": sabeon, "성명": nm, "부서": dept,
                "기본급": 기본,
                "식대": f(gv("식대")),
                "차량유지비": f(gv("차량유지비")),
                "연구수당": f(gv("연구수당")),
                "기타수당": f(gv("기타수당")),
                "연차수당": f(gv("연차수당")),
                "연장근로수당": f(gv("연장근로")),
                "야간근로수당": f(gv("야간근로")),
                "성과급": f(gv("성과급")),
                "지급합계": 지급합계,
                "국민연금": f(gv("국민연금")),
                "건강보험": f(gv("건강보험")),
                "장기요양": f(gv("장기요양")),
                "고용보험": f(gv("고용보험")),
                "소득세": f(gv("소득세")),
                "지방소득세": f(gv("지방소득세")),
                "기타공제": f(gv("기타공제")),
                "공제합계": 공제합,
                "실지급액": 실지급 or (지급합계 - 공제합),
                "4대보험(기업부담)": 0,
                "원본파일": "급여대장2025 3.xlsx",
                "원본행": idx + 4,
            })
        print(f"  급여대장/{sh}: 누적 {len(rows)}건")

    return pd.DataFrame(rows)


# ==================== 23. FACT_비용 ====================
def load_비용():
    """월별 비용 파일의 직원별총합 시트"""
    rows = []
    try:
        df = pd.read_excel(SRC["월별비용"], sheet_name="직원별총합", header=2)
    except Exception as e:
        print(f"  월별비용 오류: {e}")
        return pd.DataFrame()

    cols = list(df.columns)
    name_col = next((c for c in cols if "이름" in str(c) or "사용자" in str(c) or "성명" in str(c)), cols[0])
    date_col = next((c for c in cols if "사용일" in str(c) or "일자" in str(c)), None)
    party_col = next((c for c in cols if "거래처" in str(c)), None)
    amt_col = next((c for c in cols if "금액" in str(c)), None)
    cat_col = next((c for c in cols if str(c).strip() == "구분"), None)
    sub_col = next((c for c in cols if "상세구분" in str(c) or "세부구분" in str(c)), None)
    pay_col = next((c for c in cols if "결제수단" in str(c) or "결제방법" in str(c)), None)

    if not date_col or not amt_col:
        print(f"  월별비용/직원별총합: 필수 컬럼 없음 — cols={cols}")
        return pd.DataFrame()

    n = 0
    for idx, r in df.iterrows():
        dt = pd.to_datetime(r[date_col], errors="coerce")
        if pd.isna(dt):
            continue
        amount = f(r[amt_col])
        if amount == 0:
            continue
        y, m, q, _ = year_quarter_half(dt.year, dt.month)
        nm = normalize_name(r[name_col]) if name_col else None
        rows.append({
            "거래ID": f"E-{idx + 4:05d}",
            "사용일": dt.date(),
            "년": y, "월": m, "분기": q,
            "사용자(직원)": nm,
            "부서": None,
            "거래처/사용처": normalize_name(r[party_col]) if party_col else None,
            "금액": amount,
            "계정코드": None,
            "계정과목": None,
            "구분(대)": str(r.get(cat_col, "") or "").strip() if cat_col else None,
            "상세구분(소)": str(r.get(sub_col, "") or "").strip() if sub_col else None,
            "결제수단": str(r.get(pay_col, "") or "").strip() if pay_col else None,
            "비고": None,
            "원본파일": "2024년 월별 비용정리.v2.xlsx",
            "원본행": idx + 4,
        })
        n += 1
    print(f"  월별비용/직원별총합: {n}건")
    return pd.DataFrame(rows)


# ==================== 24. FACT_미수금 ====================
def load_미수금(party_map):
    """미수금 현황 파일의 거래처별 시트 union"""
    rows = []
    path = SRC["미수금"]
    xl = pd.ExcelFile(path)
    n_total = 0
    for sh in xl.sheet_names:
        if sh == "전체":
            continue
        try:
            df = pd.read_excel(path, sheet_name=sh)
        except Exception:
            continue
        # 미수금 시트는 헤더 row 0
        df = pd.read_excel(path, sheet_name=sh, header=0)

        cols = list(df.columns)
        date_col = next((c for c in cols if "날짜" in str(c) or "일자" in str(c)), None)
        memo_col = next((c for c in cols if "적요" in str(c)), None)
        tax_col = next((c for c in cols if "세금계산서" in str(c)), None)
        in_col = next((c for c in cols if "통장입금" in str(c) or "입금액" in str(c)), None)
        bal_col = next((c for c in cols if "잔액" in str(c)), None)
        slip_col = next((c for c in cols if "전표번호" in str(c)), None)

        if not date_col:
            continue

        # 거래처명은 시트명에서 추출 (괄호 안 메모 제거)
        party_name = re.sub(r"[(（].*?[)）]", "", sh).strip()
        party_code, party_display = None, party_name
        nm = normalize_name(party_name)
        if nm in party_map:
            party_code, party_display = party_map[nm]

        n = 0
        for idx, r in df.iterrows():
            dt = pd.to_datetime(r[date_col], errors="coerce")
            if pd.isna(dt):
                continue
            tax = f(r.get(tax_col)) if tax_col else 0
            inc = f(r.get(in_col)) if in_col else 0
            bal = f(r.get(bal_col)) if bal_col else None
            if tax == 0 and inc == 0:
                continue
            y, m, _, _ = year_quarter_half(dt.year, dt.month)
            rows.append({
                "거래ID": f"AR-{sh[:6]}-{idx + 2:05d}",
                "일자": dt.date(),
                "년": y, "월": m,
                "거래처코드": party_code,
                "거래처명": party_display,
                "적요": str(r.get(memo_col, "") or "").strip() if memo_col else None,
                "세금계산서금액(증)": tax,
                "입금액(감)": inc,
                "잔액": bal,
                "전표번호": str(r.get(slip_col, "") or "").strip() if slip_col else None,
                "비고": None,
                "원본파일": "미수금 현황 (20250813).xlsx",
                "원본시트": sh,
            })
            n += 1
        n_total += n
    print(f"  미수금: {n_total}건")
    return pd.DataFrame(rows)


# ==================== 25. FACT_차입금 (movements) ====================
def load_차입금movements():
    """단기차입금 파일의 임원별 시트 (김하남, 최정훈, 송민희, 이현근)"""
    rows = []
    path = SRC["단기차입금"]
    for sh in ["김하남", "최정훈", "송민희", "이현근"]:
        try:
            df = pd.read_excel(path, sheet_name=sh)
        except Exception:
            continue

        # 차입금 임원 시트도 헤더 row 0
        df = pd.read_excel(path, sheet_name=sh, header=0)

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
            dt = pd.to_datetime(r[date_col], errors="coerce")
            if pd.isna(dt):
                continue
            inc = f(r.get(in_col)) if in_col else 0
            out = f(r.get(out_col)) if out_col else 0
            bal = f(r.get(bal_col)) if bal_col else None
            if inc == 0 and out == 0:
                continue
            y, m, _, _ = year_quarter_half(dt.year, dt.month)
            rows.append({
                "거래ID": f"L-{sh[:2]}-{idx + 2:05d}",
                "일자": dt.date(),
                "년": y, "월": m,
                "차입처구분(은행/개인)": "개인",
                "차입처명": sh,
                "차입ID": f"LM-{sh}",
                "적요": str(r.get(memo_col, "") or "").strip() if memo_col else None,
                "차입(+)": inc,
                "상환(-)": out,
                "잔액": bal,
                "이자": 0,
                "비고": str(r.get(kind_col, "") or "").strip() if kind_col else None,
                "원본파일": "단기차입금 및 임원 급여 미지급비용 (20260415).xlsx",
                "원본시트": sh,
            })
    print(f"  차입금: {len(rows)}건")
    return pd.DataFrame(rows)


# ==================== 27. FACT_퇴직금 ====================
def load_퇴직금(emp_map):
    """퇴직연금 파일의 기업납입금 시트 unpivot (직원별 × 월)"""
    rows = []
    try:
        df = pd.read_excel(SRC["퇴직연금"], sheet_name="기업납입금", header=1)
    except Exception as e:
        print(f"  퇴직연금/기업납입금 로드 실패: {e}")
        return pd.DataFrame()

    cols = list(df.columns)
    name_col = next((c for c in cols if "성명" in str(c) or "이름" in str(c) or "가입자" in str(c)), cols[0])
    # 월별 컬럼: datetime 또는 "YYYY-MM"
    month_cols = []
    for c in cols:
        if c == name_col:
            continue
        # datetime 객체인 경우
        if hasattr(c, "year") and hasattr(c, "month"):
            month_cols.append((c.year, c.month, c))
            continue
        s = str(c).strip()
        # "2024-01-01" 또는 "2024-01" 형식
        m = re.match(r"(\d{4})[-/.](\d{1,2})", s)
        if m:
            month_cols.append((int(m.group(1)), int(m.group(2)), c))
            continue
        # datetime으로 파싱
        try:
            d = pd.to_datetime(s, errors="coerce")
            if pd.notna(d):
                month_cols.append((d.year, d.month, c))
        except Exception:
            pass

    print(f"  퇴직금 월 컬럼: {len(month_cols)}개")
    if not month_cols:
        print(f"    cols sample: {cols[:8]}")
        return pd.DataFrame()

    n = 0
    for idx, r in df.iterrows():
        nm = normalize_name(r[name_col])
        if not nm or any(s in nm for s in ["합계", "소계", "총계"]):
            continue
        sabeon = emp_map.get(nm)
        for yr, mo, col in month_cols:
            val = r.get(col)
            try:
                amt = float(val) if pd.notna(val) else 0
            except Exception:
                continue
            if amt == 0:
                continue
            rows.append({
                "귀속년월": f"{yr}-{mo:02d}",
                "년": yr, "월": mo,
                "사번": sabeon, "성명": nm,
                "기준급여": None,
                "기업납입금": amt,
                "개인납입금": None,
                "납입일자": None,
                "구분(적립/지급/중도인출)": "적립",
                "비고": None,
                "원본파일": "(주)인비즈_퇴직연금_월별입금액표_251231.xlsx",
            })
            n += 1
    print(f"  퇴직금: {n}건")
    return pd.DataFrame(rows)


# ==================== MAIN ====================
if __name__ == "__main__":
    print("=== P6: 급여·비용·미수금·차입금·퇴직금 ===")
    wb = load_master()
    party_map = build_party_map(wb)
    emp_map = build_emp_map(wb)
    print(f"거래처 {len(party_map)}, 직원 {len(emp_map)}")

    print("\n[1/5] 급여")
    df_pay = load_급여(emp_map)
    cols_pay = ["귀속년월", "년", "월", "사번", "성명", "부서",
                "기본급", "식대", "차량유지비", "연구수당", "기타수당", "연차수당",
                "연장근로수당", "야간근로수당", "성과급", "지급합계",
                "국민연금", "건강보험", "장기요양", "고용보험", "소득세", "지방소득세",
                "기타공제", "공제합계", "실지급액", "4대보험(기업부담)",
                "원본파일", "원본행"]
    if len(df_pay):
        df_pay = df_pay[cols_pay]

    print("\n[2/5] 비용")
    df_exp = load_비용()
    cols_exp = ["거래ID", "사용일", "년", "월", "분기", "사용자(직원)", "부서",
                "거래처/사용처", "금액", "계정코드", "계정과목",
                "구분(대)", "상세구분(소)", "결제수단", "비고",
                "원본파일", "원본행"]
    if len(df_exp):
        df_exp = df_exp[cols_exp]

    print("\n[3/5] 미수금")
    df_ar = load_미수금(party_map)
    cols_ar = ["거래ID", "일자", "년", "월", "거래처코드", "거래처명", "적요",
               "세금계산서금액(증)", "입금액(감)", "잔액", "전표번호", "비고",
               "원본파일", "원본시트"]
    if len(df_ar):
        df_ar = df_ar[cols_ar]

    print("\n[4/5] 차입금")
    df_loan = load_차입금movements()
    cols_loan = ["거래ID", "일자", "년", "월", "차입처구분(은행/개인)", "차입처명",
                 "차입ID", "적요", "차입(+)", "상환(-)", "잔액", "이자", "비고",
                 "원본파일", "원본시트"]
    if len(df_loan):
        df_loan = df_loan[cols_loan]

    print("\n[5/5] 퇴직금")
    df_ret = load_퇴직금(emp_map)
    cols_ret = ["귀속년월", "년", "월", "사번", "성명", "기준급여",
                "기업납입금", "개인납입금", "납입일자",
                "구분(적립/지급/중도인출)", "비고", "원본파일"]
    if len(df_ret):
        df_ret = df_ret[cols_ret]

    print("\n워크북 적재 중...")
    if len(df_pay):
        write_dim_or_fact(wb, "22_FACT_급여", df_pay, "tbl_급여")
    if len(df_exp):
        write_dim_or_fact(wb, "23_FACT_비용", df_exp, "tbl_비용")
    if len(df_ar):
        write_dim_or_fact(wb, "24_FACT_미수금", df_ar, "tbl_미수금")
    if len(df_loan):
        write_dim_or_fact(wb, "25_FACT_차입금", df_loan, "tbl_차입금")
    if len(df_ret):
        write_dim_or_fact(wb, "27_FACT_퇴직금", df_ret, "tbl_퇴직금")
    save_master(wb)
    print("완료.")
