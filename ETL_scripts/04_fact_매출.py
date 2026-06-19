# -*- coding: utf-8 -*-
"""P4: FACT_매출 적재

소스:
1. 매출분류 파일의 2021/2022/2023 시트 (가장 깨끗한 long-format)
2. 거래처세계 파일의 2024 매출 시트 (wide-format → unpivot)
3. 외상매출금 파일의 2025/2026 시트 (wide-format → unpivot)
"""
import pandas as pd
import re
from datetime import datetime
from common import SRC, load_master, save_master, write_dim_or_fact, normalize_name, year_quarter_half, apply_product_mapping, get_mapping_rules


def build_party_map(wb):
    """거래처명 → 거래처코드 매핑 사전"""
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
    # 부분 매치 시도
    for k, v in party_map.items():
        if k and (k in nm or nm in k) and abs(len(k) - len(nm)) < 5:
            return v
    return (None, nm)


def load_long_매출분류(rules, party_map):
    """매출분류 파일의 2021/2022/2023 long-format → 표준 매출 fact"""
    rows = []
    path = SRC["매출분류"]
    for sh in ["2021", "2022", "2023"]:
        df = pd.read_excel(path, sheet_name=sh)
        # 컬럼 정규화
        cols = {str(c).strip(): c for c in df.columns}

        # 필수 컬럼 추출
        def get_col(*candidates):
            for cand in candidates:
                for k, v in cols.items():
                    if cand in k:
                        return v
            return None

        c_date = get_col("전표일자", "일자")
        c_party = get_col("거래처")
        c_biz = get_col("사업자", "주민")
        c_item = get_col("품명")
        c_supply = get_col("공급가액")
        c_vat = get_col("부가세")
        c_total = get_col("합계")
        c_type = get_col("매입/매출", "매출유형")
        c_acct = get_col("계정과목")
        c_kind = get_col("구분")

        if not c_date or not c_party:
            print(f"  [{sh}] 필수 컬럼 누락. 건너뜀.")
            continue

        n_rows = 0
        for idx, r in df.iterrows():
            dt = pd.to_datetime(r[c_date], errors="coerce")
            if pd.isna(dt):
                continue
            kind = str(r.get(c_kind, "")).strip() if c_kind else ""
            # "매출"만 채택 (매입은 별도 시트)
            if "매입" in kind:
                continue
            party_name = normalize_name(r[c_party])
            if not party_name:
                continue
            party_code, party_display = resolve_party(party_name, party_map)
            item = normalize_name(r.get(c_item)) if c_item else None
            prod_code, prod_name = apply_product_mapping(item, rules)
            supply = r.get(c_supply, 0)
            vat = r.get(c_vat, 0)
            total = r.get(c_total, 0)
            try:
                supply = float(supply) if pd.notna(supply) else 0
                vat = float(vat) if pd.notna(vat) else 0
                total = float(total) if pd.notna(total) else (supply + vat)
            except Exception:
                continue
            if supply == 0 and total == 0:
                continue
            y, m, q, h = year_quarter_half(dt.year, dt.month)
            매출유형 = str(r.get(c_type, "") or "").strip() if c_type else ""
            계정과목 = str(r.get(c_acct, "") or "").strip() if c_acct else ""
            rows.append({
                "거래ID": f"S-{sh}-{idx + 2:05d}",
                "전표일자": dt.date(),
                "년": y, "월": m, "분기": q, "반기": h,
                "거래처코드": party_code,
                "거래처명": party_display,
                "제품코드": prod_code,
                "제품명": prod_name,
                "품명(원본)": item,
                "계정코드": None,
                "계정과목": 계정과목,
                "매출유형(정기/신규/일회성/기타)": 매출유형 or "기타",
                "공급가액": supply,
                "부가세": vat,
                "합계": total,
                "결제수단": None,
                "비고": None,
                "원본파일": "매출분류 인비즈 (보고용).xlsx",
                "원본시트": sh,
                "원본행": idx + 2,
            })
            n_rows += 1
        print(f"  매출분류/{sh}: {n_rows}건")
    return rows


def load_wide_거래처세계_2024(rules, party_map):
    """거래처세계 파일의 2024 매출 시트는 wide-format. 월별 매출 컬럼 unpivot."""
    rows = []
    path = SRC["거래처세계"]
    try:
        df = pd.read_excel(path, sheet_name="2024 매출", header=1)
    except Exception:
        try:
            df = pd.read_excel(path, sheet_name="2024 매출", header=0)
        except Exception as e:
            print(f"  거래처세계/2024매출 로드 실패: {e}")
            return rows
    if False:  # placeholder
        e = None
        print(f"  거래처세계/2024매출 로드 실패: {e}")
        return rows

    # 거래처명 컬럼
    party_col = next((c for c in df.columns if "거래처" in str(c)), None)
    item_col = next((c for c in df.columns if "품목" in str(c)), None)
    if not party_col:
        return rows

    # 월별 매출 컬럼 찾기 — "1월매출", "2월매출" 패턴 (수금 컬럼은 제외)
    month_sales_cols = []
    for c in df.columns:
        s = str(c)
        m = re.match(r"^(\d+)월매출$", s)
        if m:
            month_sales_cols.append((int(m.group(1)), c))
        else:
            m2 = re.match(r"^(\d+)월$", s)
            if m2:
                month_sales_cols.append((int(m2.group(1)), c))

    if not month_sales_cols:
        print(f"  거래처세계/2024매출: 월 컬럼 없음")
        return rows

    n = 0
    for idx, r in df.iterrows():
        party_name = normalize_name(r[party_col])
        if not party_name or "합계" in party_name or "소계" in party_name:
            continue
        party_code, party_display = resolve_party(party_name, party_map)
        item = normalize_name(r.get(item_col)) if item_col else None
        prod_code, prod_name = apply_product_mapping(item, rules)

        for month, col in month_sales_cols:
            val = r.get(col)
            try:
                amount = float(val) if pd.notna(val) else 0
            except Exception:
                continue
            if amount == 0:
                continue
            # 매출은 부가세 별도 → 공급가액=amount, 부가세는 거래처세계가 합계인지 공급가액인지 모호
            # 일단 공급가액으로 처리
            y, m, q, h = year_quarter_half(2024, month)
            dt = datetime(2024, month, 28).date()  # 월말 가정
            rows.append({
                "거래ID": f"S-2024W-{idx + 3:05d}-{month:02d}",
                "전표일자": dt,
                "년": y, "월": m, "분기": q, "반기": h,
                "거래처코드": party_code,
                "거래처명": party_display,
                "제품코드": prod_code,
                "제품명": prod_name,
                "품명(원본)": item,
                "계정코드": None,
                "계정과목": None,
                "매출유형(정기/신규/일회성/기타)": "정기",
                "공급가액": amount,
                "부가세": 0,
                "합계": amount,
                "결제수단": None,
                "비고": "wide→long unpivot",
                "원본파일": "03. 거래처별매입매출세금계산서.xlsx",
                "원본시트": "2024 매출",
                "원본행": idx + 3,
            })
            n += 1
    print(f"  거래처세계/2024 매출: {n}건 (unpivot)")
    return rows


def load_wide_외상매출금(rules, party_map):
    """외상매출금 파일의 2025/2026 시트 unpivot"""
    rows = []
    path = SRC["외상매출금"]
    for sh, year in [("외상매출금(2025)", 2025), ("외상매출금(2026)", 2026)]:
        try:
            df = pd.read_excel(path, sheet_name=sh, header=2)
        except Exception as e:
            print(f"  {sh} 로드 실패: {e}")
            continue

        party_col = df.columns[0]
        # 월별 매출 컬럼 찾기 (보통 "1월", "2월" 또는 "1月" 같은 패턴)
        month_cols = []
        for c in df.columns:
            s = str(c)
            m = re.match(r"^(\d+)[월月]$", s)
            if m:
                month_cols.append((int(m.group(1)), c))

        if not month_cols:
            print(f"  {sh}: 월 컬럼 없음 (cols={list(df.columns)[:8]}...)")
            continue

        n = 0
        for idx, r in df.iterrows():
            party_name = normalize_name(r[party_col])
            if not party_name or "합계" in party_name or "소계" in party_name or "총계" in party_name:
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
                # 외상매출금은 발행액 — 공급가액인지 합계(VAT 포함)인지 검토. 보통 발행합계.
                # supply=amount/1.1 (가정) — 다만 원본 수치 보존 위해 합계로 처리
                supply = round(amount / 1.1, 0)
                vat = amount - supply
                y, m, q, h = year_quarter_half(year, month)
                dt = datetime(year, month, 28).date()
                rows.append({
                    "거래ID": f"S-AR{year}-{idx + 3:05d}-{month:02d}",
                    "전표일자": dt,
                    "년": y, "월": m, "분기": q, "반기": h,
                    "거래처코드": party_code,
                    "거래처명": party_display,
                    "제품코드": "P999",
                    "제품명": "기타",
                    "품명(원본)": None,
                    "계정코드": None,
                    "계정과목": "외상매출금",
                    "매출유형(정기/신규/일회성/기타)": "정기",
                    "공급가액": supply,
                    "부가세": vat,
                    "합계": amount,
                    "결제수단": None,
                    "비고": "외상매출금 발행 unpivot",
                    "원본파일": "외상매출금 (20260422).xlsx",
                    "원본시트": sh,
                    "원본행": idx + 3,
                })
                n += 1
        print(f"  {sh}: {n}건 (unpivot)")
    return rows


if __name__ == "__main__":
    print("=== P4: FACT_매출 적재 ===")
    wb = load_master()
    rules = get_mapping_rules(wb)
    print(f"제품매핑 룰 {len(rules)}개")
    party_map = build_party_map(wb)
    print(f"거래처 사전 {len(party_map)}개")

    all_rows = []
    print("\n[1/3] 매출분류 long-format")
    all_rows.extend(load_long_매출분류(rules, party_map))
    print("\n[2/3] 거래처세계 2024 wide unpivot")
    all_rows.extend(load_wide_거래처세계_2024(rules, party_map))
    print("\n[3/3] 외상매출금 2025/2026 unpivot")
    all_rows.extend(load_wide_외상매출금(rules, party_map))

    df = pd.DataFrame(all_rows)
    print(f"\n총 매출 트랜잭션: {len(df)}건")
    print("\n연도별 집계:")
    yr_summary = df.groupby("년")["공급가액"].agg(["count", "sum"])
    yr_summary.columns = ["건수", "공급가액합계"]
    print(yr_summary)

    print("\n제품별 집계:")
    print(df.groupby("제품명")["공급가액"].agg(["count", "sum"]).sort_values("sum", ascending=False))

    print("\n워크북 적재 중...")
    # 컬럼 순서를 시트 헤더에 맞춤
    cols_order = ["거래ID", "전표일자", "년", "월", "분기", "반기",
                  "거래처코드", "거래처명", "제품코드", "제품명", "품명(원본)",
                  "계정코드", "계정과목", "매출유형(정기/신규/일회성/기타)",
                  "공급가액", "부가세", "합계", "결제수단", "비고",
                  "원본파일", "원본시트", "원본행"]
    df = df[cols_order]
    write_dim_or_fact(wb, "20_FACT_매출", df, "tbl_매출")
    save_master(wb)
    print("완료.")
