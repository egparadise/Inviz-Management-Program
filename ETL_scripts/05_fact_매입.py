# -*- coding: utf-8 -*-
"""P5: FACT_매입 적재

소스:
1. 매출분류 파일의 2021/2022/2023 시트 중 매입 row만 (구분 컬럼 = '매입')
2. 거래처세계 파일의 매입 시트 (2024 매입, 2024 매입(서울지점), 2024 매입(광주지점))
3. 외상매입금 파일의 2025/2026 시트 unpivot
"""
import pandas as pd
import re
from datetime import datetime
from common import SRC, load_master, save_master, write_dim_or_fact, normalize_name, year_quarter_half, apply_product_mapping, get_mapping_rules


def build_party_map(wb):
    ws = wb["10_DIM_거래처"]
    m = {}
    for row in ws.iter_rows(min_row=2, values_only=True):
        if row[0] and row[1]:
            m[normalize_name(row[1])] = (row[0], row[1])
    return m


def resolve_party(name, party_map):
    nm = normalize_name(name)
    if not nm:
        return (None, None)
    if nm in party_map:
        return party_map[nm]
    for k, v in party_map.items():
        if k and (k in nm or nm in k) and abs(len(k) - len(nm)) < 5:
            return v
    return (None, nm)


def load_매출분류_매입(rules, party_map):
    """매출분류 파일에서 구분='매입'인 행만 추출"""
    rows = []
    path = SRC["매출분류"]
    for sh in ["2021", "2022", "2023"]:
        df = pd.read_excel(path, sheet_name=sh)

        def get_col(*candidates):
            for cand in candidates:
                for c in df.columns:
                    if cand in str(c):
                        return c
            return None

        c_date = get_col("전표일자", "일자")
        c_party = get_col("거래처")
        c_item = get_col("품명")
        c_supply = get_col("공급가액")
        c_vat = get_col("부가세")
        c_total = get_col("합계")
        c_type = get_col("매입/매출", "매입유형")
        c_acct = get_col("계정과목")
        c_kind = get_col("구분")

        if not c_date or not c_party or not c_kind:
            continue

        n = 0
        for idx, r in df.iterrows():
            kind = str(r.get(c_kind, "")).strip()
            if "매입" not in kind:
                continue
            dt = pd.to_datetime(r[c_date], errors="coerce")
            if pd.isna(dt):
                continue
            party_name = normalize_name(r[c_party])
            if not party_name:
                continue
            party_code, party_display = resolve_party(party_name, party_map)
            item = normalize_name(r.get(c_item)) if c_item else None
            prod_code, prod_name = apply_product_mapping(item, rules)
            try:
                supply = float(r.get(c_supply, 0)) if pd.notna(r.get(c_supply)) else 0
                vat = float(r.get(c_vat, 0)) if pd.notna(r.get(c_vat)) else 0
                total = float(r.get(c_total, 0)) if pd.notna(r.get(c_total)) else (supply + vat)
            except Exception:
                continue
            if supply == 0 and total == 0:
                continue
            y, m, q, h = year_quarter_half(dt.year, dt.month)
            rows.append({
                "거래ID": f"P-{sh}-{idx + 2:05d}",
                "전표일자": dt.date(),
                "년": y, "월": m, "분기": q, "반기": h,
                "거래처코드": party_code, "거래처명": party_display,
                "제품코드": prod_code, "제품명": prod_name, "품명(원본)": item,
                "계정코드": None, "계정과목": str(r.get(c_acct, "") or "").strip() if c_acct else None,
                "매입유형(정기/일회성/기타)": str(r.get(c_type, "") or "").strip() if c_type else "기타",
                "공급가액": supply, "부가세": vat, "합계": total,
                "결제수단": None, "비고": None,
                "원본파일": "매출분류 인비즈 (보고용).xlsx",
                "원본시트": sh, "원본행": idx + 2,
            })
            n += 1
        print(f"  매출분류/{sh} 매입: {n}건")
    return rows


def load_거래처세계_매입(rules, party_map):
    """거래처세계 파일의 매입 시트 unpivot"""
    rows = []
    path = SRC["거래처세계"]
    for sh in ["2022 매입", "2023 매입", "2024 매입", "2024 매입(서울지점)", "2024 매입(광주지점)",
               "2023 매입(서울지점)", "2023 매입(광주지점)", "2022 매입(지점)"]:
        try:
            df = pd.read_excel(path, sheet_name=sh, header=1)
        except Exception:
            continue
        # 연도 추출
        m_year = re.match(r"^(\d{4})", sh)
        if not m_year:
            continue
        year = int(m_year.group(1))

        party_col = next((c for c in df.columns if "거래처" in str(c)), None)
        item_col = next((c for c in df.columns if "품목" in str(c)), None)
        if not party_col:
            continue

        # 월별 매입 컬럼: "1월매입", "2월매입" 또는 단순 "1월"
        month_cols = []
        for c in df.columns:
            s = str(c)
            m = re.match(r"^(\d+)월매입$", s)
            if m:
                month_cols.append((int(m.group(1)), c))
            else:
                m2 = re.match(r"^(\d+)월$", s)
                if m2:
                    month_cols.append((int(m2.group(1)), c))
        if not month_cols:
            continue

        n = 0
        for idx, r in df.iterrows():
            party_name = normalize_name(r[party_col])
            if not party_name or any(s in party_name for s in ["합계", "소계", "총계"]):
                continue
            party_code, party_display = resolve_party(party_name, party_map)
            item = normalize_name(r.get(item_col)) if item_col else None
            prod_code, prod_name = apply_product_mapping(item, rules)
            for month, col in month_cols:
                val = r.get(col)
                try:
                    amount = float(val) if pd.notna(val) else 0
                except Exception:
                    continue
                if amount == 0:
                    continue
                y, m, q, h = year_quarter_half(year, month)
                dt = datetime(year, month, 28).date()
                rows.append({
                    "거래ID": f"P-{year}W-{idx + 3:05d}-{month:02d}",
                    "전표일자": dt,
                    "년": y, "월": m, "분기": q, "반기": h,
                    "거래처코드": party_code, "거래처명": party_display,
                    "제품코드": prod_code, "제품명": prod_name, "품명(원본)": item,
                    "계정코드": None, "계정과목": None,
                    "매입유형(정기/일회성/기타)": "정기",
                    "공급가액": amount, "부가세": 0, "합계": amount,
                    "결제수단": None, "비고": f"{sh} wide→long",
                    "원본파일": "03. 거래처별매입매출세금계산서.xlsx",
                    "원본시트": sh, "원본행": idx + 3,
                })
                n += 1
        print(f"  거래처세계/{sh}: {n}건")
    return rows


def load_외상매입금(rules, party_map):
    """외상매입금 파일 unpivot"""
    rows = []
    path = SRC["외상매입금"]
    for sh, year in [("외상매입금(2024)", 2024), ("외상매입금(2025)", 2025), ("외상매입금(2026)", 2026)]:
        try:
            df = pd.read_excel(path, sheet_name=sh, header=2)
        except Exception:
            try:
                df = pd.read_excel(path, sheet_name=sh, header=1)
            except Exception:
                continue
        party_col = df.columns[1] if len(df.columns) > 1 else df.columns[0]
        month_cols = []
        for c in df.columns:
            s = str(c)
            m = re.match(r"^(\d+)[월月]$", s)
            if m:
                month_cols.append((int(m.group(1)), c))
        if not month_cols:
            print(f"  {sh}: 월 컬럼 없음 — cols={list(df.columns)[:8]}")
            continue
        n = 0
        for idx, r in df.iterrows():
            party_name = normalize_name(r[party_col])
            if not party_name or any(s in party_name for s in ["합계", "소계", "총계"]):
                continue
            party_code, party_display = resolve_party(party_name, party_map)
            for month, col in month_cols:
                val = r.get(col)
                try:
                    amount = float(val) if pd.notna(val) else 0
                except Exception:
                    continue
                if amount == 0:
                    continue
                supply = round(amount / 1.1, 0)
                vat = amount - supply
                y, m, q, h = year_quarter_half(year, month)
                dt = datetime(year, month, 28).date()
                rows.append({
                    "거래ID": f"P-AP{year}-{idx + 3:05d}-{month:02d}",
                    "전표일자": dt,
                    "년": y, "월": m, "분기": q, "반기": h,
                    "거래처코드": party_code, "거래처명": party_display,
                    "제품코드": "P999", "제품명": "기타", "품명(원본)": None,
                    "계정코드": None, "계정과목": "외상매입금",
                    "매입유형(정기/일회성/기타)": "정기",
                    "공급가액": supply, "부가세": vat, "합계": amount,
                    "결제수단": None, "비고": "외상매입금 unpivot",
                    "원본파일": "외상매입금 (20260422).xlsx",
                    "원본시트": sh, "원본행": idx + 3,
                })
                n += 1
        print(f"  {sh}: {n}건")
    return rows


if __name__ == "__main__":
    print("=== P5: FACT_매입 적재 ===")
    wb = load_master()
    rules = get_mapping_rules(wb)
    party_map = build_party_map(wb)

    all_rows = []
    print("\n[1/3] 매출분류 매입 long")
    all_rows.extend(load_매출분류_매입(rules, party_map))
    print("\n[2/3] 거래처세계 매입 시트 unpivot")
    all_rows.extend(load_거래처세계_매입(rules, party_map))
    print("\n[3/3] 외상매입금 unpivot")
    all_rows.extend(load_외상매입금(rules, party_map))

    df = pd.DataFrame(all_rows)
    print(f"\n총 매입 트랜잭션: {len(df)}건")
    if len(df) > 0:
        print("\n연도별:")
        print(df.groupby("년")["공급가액"].agg(["count", "sum"]))

    cols = ["거래ID", "전표일자", "년", "월", "분기", "반기",
            "거래처코드", "거래처명", "제품코드", "제품명", "품명(원본)",
            "계정코드", "계정과목", "매입유형(정기/일회성/기타)",
            "공급가액", "부가세", "합계", "결제수단", "비고",
            "원본파일", "원본시트", "원본행"]
    df = df[cols]

    write_dim_or_fact(wb, "21_FACT_매입", df, "tbl_매입")
    save_master(wb)
    print("완료.")
