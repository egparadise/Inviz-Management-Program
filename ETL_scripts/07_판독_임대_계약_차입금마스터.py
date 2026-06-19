# -*- coding: utf-8 -*-
"""P7: FACT_판독수수료, 임대료, 30_계약마스터, 31_차입금마스터 적재"""
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
    return (None, nm)


def f(v, default=0):
    try:
        return float(v) if pd.notna(v) else default
    except Exception:
        return default


# ==================== 28. FACT_판독수수료 ====================
def load_판독수수료(party_map):
    """판독수수료 파일 매출 시트 unpivot.
    써밋영상(매출) — 월 컬럼 첫번째, 판독건수/판독료/사용료 row 기반
    실제로는 long-format에 가까운 시트들. 월별로 row가 있음.
    """
    rows = []
    path = SRC["판독수수료"]

    # 1. 써밋영상(매출) — long-format: 월/병원명/판독건수/판독료/사용료
    try:
        df = pd.read_excel(path, sheet_name="써밋영상(매출)", header=2)
        cols = list(df.columns)
        month_col = next((c for c in cols if "월" == str(c).strip() or "월" in str(c).strip()[:2]), None)
        hosp_col = next((c for c in cols if "병원" in str(c)), None)
        cnt_col = next((c for c in cols if "판독건수" in str(c) or "건수" in str(c)), None)
        price_col = next((c for c in cols if "판독료" == str(c).strip()), None)
        fee_col = next((c for c in cols if "사용료" in str(c)), None)

        n = 0
        for idx, r in df.iterrows():
            if not month_col:
                continue
            month_val = r.get(month_col)
            if pd.isna(month_val):
                continue
            m = re.search(r"(\d+)", str(month_val))
            if not m:
                continue
            month = int(m.group(1))
            year_m = re.search(r"(20\d{2})", str(month_val))
            year = int(year_m.group(1)) if year_m else 2024
            hosp = normalize_name(r.get(hosp_col)) if hosp_col else None
            if not hosp:
                continue
            party_code, _ = resolve_party(hosp, party_map)
            cnt = f(r.get(cnt_col)) if cnt_col else 0
            price = f(r.get(price_col)) if price_col else 0
            fee = f(r.get(fee_col)) if fee_col else 0
            if price + fee == 0:
                continue
            y, mo, _, _ = year_quarter_half(year, month)
            rows.append({
                "거래ID": f"R-써밋-{idx + 4:05d}",
                "귀속년월": f"{year}-{month:02d}",
                "년": y, "월": mo,
                "매출/매입": "매출",
                "병원/공급처": hosp,
                "대리점": "써밋영상",
                "제품코드": "P001", "제품명": "Cloud Care Life",
                "판독건수": cnt, "단가": (price / cnt) if cnt else 0,
                "판독료": price, "인비즈수익": fee, "대리점수수료": 0,
                "매출액": price + fee, "원가": 0,
                "순이익": price + fee, "이익률": 100.0,
                "비고": "써밋영상 매출",
                "원본파일": "5) 판독수수료 매출매입 정산_250620_SY.xlsx",
            })
            n += 1
        print(f"  써밋영상(매출): {n}건")
    except Exception as e:
        print(f"  써밋영상(매출) 오류: {e}")

    # 2. 강남미래영상(매출)
    try:
        df = pd.read_excel(path, sheet_name="강남미래영상(매출)", header=6)
        cols = list(df.columns)
        # 컬럼 패턴 같음
        month_col = next((c for c in cols if "월" == str(c).strip() or str(c).strip().endswith("월")), None)
        hosp_col = next((c for c in cols if "병원" in str(c)), None)
        cnt_col = next((c for c in cols if "건수" in str(c)), None)
        price_col = next((c for c in cols if "판독료" == str(c).strip()), None)
        n = 0
        for idx, r in df.iterrows():
            if not month_col:
                continue
            month_val = r.get(month_col)
            if pd.isna(month_val):
                continue
            m = re.search(r"(\d+)", str(month_val))
            if not m:
                continue
            month = int(m.group(1))
            year_m = re.search(r"(20\d{2})", str(month_val))
            year = int(year_m.group(1)) if year_m else 2024
            hosp = normalize_name(r.get(hosp_col)) if hosp_col else None
            if not hosp:
                continue
            cnt = f(r.get(cnt_col)) if cnt_col else 0
            price = f(r.get(price_col)) if price_col else 0
            if price == 0:
                continue
            y, mo, _, _ = year_quarter_half(year, month)
            rows.append({
                "거래ID": f"R-강남-{idx + 8:05d}",
                "귀속년월": f"{year}-{month:02d}",
                "년": y, "월": mo,
                "매출/매입": "매출",
                "병원/공급처": hosp,
                "대리점": "강남미래영상",
                "제품코드": "P001", "제품명": "Cloud Care Life",
                "판독건수": cnt, "단가": (price / cnt) if cnt else 0,
                "판독료": price, "인비즈수익": 0, "대리점수수료": 0,
                "매출액": price, "원가": 0,
                "순이익": price, "이익률": 100.0,
                "비고": "강남미래영상 매출",
                "원본파일": "5) 판독수수료 매출매입 정산_250620_SY.xlsx",
            })
            n += 1
        print(f"  강남미래영상(매출): {n}건")
    except Exception as e:
        print(f"  강남미래영상(매출) 오류: {e}")

    # 3. 2025) 원격판독 PACS (매입) — wide format unpivot
    for sh in ["2025)원격판독 PACS (매입)", "2024)원격판독 PACS (매입)"]:
        try:
            df = pd.read_excel(path, sheet_name=sh, header=1)
        except Exception:
            continue
        cols = list(df.columns)
        hosp_col = next((c for c in cols if "병원" in str(c)), None)
        agency_col = next((c for c in cols if "대리점" in str(c)), None)
        year_m = re.match(r"(\d{4})", sh)
        year = int(year_m.group(1)) if year_m else 2024

        # 월별 그룹: 1월 그룹 컬럼이 "판독료/인비즈/매출액/대리점/수수료정산/순이익/이익율"로 펼쳐짐
        # 단순화: 컬럼명이 "1월", "2월" 같은 헤더가 있고 그 아래 sub-header가 있는 multi-index. header=1만 사용.
        # 일단 모든 "X월" 매칭 컬럼을 매출액으로 가정
        month_cols = []
        for c in cols:
            s = str(c)
            m = re.match(r"^(\d+)월$", s)
            if m:
                month_cols.append((int(m.group(1)), c))

        n = 0
        for idx, r in df.iterrows():
            hosp = normalize_name(r.get(hosp_col)) if hosp_col else None
            agency = normalize_name(r.get(agency_col)) if agency_col else None
            if not hosp or any(s in hosp for s in ["합계", "소계"]):
                continue
            for month, col in month_cols:
                val = r.get(col)
                amt = f(val)
                if amt == 0:
                    continue
                y, mo, _, _ = year_quarter_half(year, month)
                rows.append({
                    "거래ID": f"R-PACS{year}-{idx + 3:05d}-{month:02d}",
                    "귀속년월": f"{year}-{month:02d}",
                    "년": y, "월": mo,
                    "매출/매입": "매입",
                    "병원/공급처": hosp,
                    "대리점": agency,
                    "제품코드": "P002", "제품명": "Saintview PACS",
                    "판독건수": 0, "단가": 0,
                    "판독료": amt, "인비즈수익": 0, "대리점수수료": 0,
                    "매출액": 0, "원가": amt,
                    "순이익": -amt, "이익률": 0,
                    "비고": "PACS 매입 unpivot",
                    "원본파일": "5) 판독수수료 매출매입 정산_250620_SY.xlsx",
                })
                n += 1
        print(f"  {sh}: {n}건")
    return pd.DataFrame(rows)


# ==================== 26. FACT_임대료 ====================
def load_임대료():
    """관리비 및 렌탈현황 파일"""
    rows = []
    path = SRC["관리비렌탈"]

    # 1. 관리비 시트 (지출)
    try:
        df = pd.read_excel(path, sheet_name="관리비", header=1)
        cols = list(df.columns)
        item_col = cols[0]
        month_cols = []
        for c in cols:
            s = str(c)
            m = re.match(r"^(\d+)월$", s)
            if m:
                month_cols.append((int(m.group(1)), c))
        n = 0
        for idx, r in df.iterrows():
            item = normalize_name(r[item_col])
            if not item or any(s in item for s in ["합계", "소계"]):
                continue
            for month, col in month_cols:
                amt = f(r.get(col))
                if amt == 0:
                    continue
                rows.append({
                    "거래ID": f"L-관리비-{idx + 3:05d}-{month:02d}",
                    "일자": datetime(2024, month, 28).date(),
                    "년": 2024, "월": month,
                    "구분(수입/지출)": "지출",
                    "거래처": None,
                    "물건명(사무실/장비)": "본사 사무실",
                    "항목(임차료/관리비/공과금/렌탈료)": item,
                    "금액": amt,
                    "결제수단": None, "비고": None,
                    "원본파일": "관리비 및 렌탈현황 (20240715).xlsx",
                })
                n += 1
        print(f"  관리비: {n}건")
    except Exception as e:
        print(f"  관리비 오류: {e}")

    # 2. 렌탈현황 시트
    try:
        df = pd.read_excel(path, sheet_name="렌탈현황", header=2)
        cols = list(df.columns)
        item_col = next((c for c in cols if "구분" in str(c) or "품목" in str(c)), cols[0])
        dept_col = next((c for c in cols if "부서" in str(c)), None)
        month_cols = []
        for c in cols:
            s = str(c)
            m = re.match(r"^(\d+)월$", s)
            if m:
                month_cols.append((int(m.group(1)), c))
        n = 0
        for idx, r in df.iterrows():
            item = normalize_name(r[item_col])
            if not item or any(s in item for s in ["합계", "소계", "수량", "금액"]):
                continue
            for month, col in month_cols:
                amt = f(r.get(col))
                if amt == 0:
                    continue
                rows.append({
                    "거래ID": f"L-렌탈-{idx + 4:05d}-{month:02d}",
                    "일자": datetime(2024, month, 28).date(),
                    "년": 2024, "월": month,
                    "구분(수입/지출)": "지출",
                    "거래처": normalize_name(r[dept_col]) if dept_col else None,
                    "물건명(사무실/장비)": item,
                    "항목(임차료/관리비/공과금/렌탈료)": "렌탈료",
                    "금액": amt,
                    "결제수단": None, "비고": None,
                    "원본파일": "관리비 및 렌탈현황 (20240715).xlsx",
                })
                n += 1
        print(f"  렌탈현황: {n}건")
    except Exception as e:
        print(f"  렌탈현황 오류: {e}")

    return pd.DataFrame(rows)


# ==================== 30. 계약마스터 ====================
def load_계약마스터(party_map, rules):
    rows = []
    path = SRC["계약관리"]

    for sh in ["계약현황_2025", "2016 ~ (종료)"]:
        try:
            df = pd.read_excel(path, sheet_name=sh, header=1)
        except Exception as e:
            print(f"  {sh} 오류: {e}")
            continue
        cols = list(df.columns)

        def get(*keys):
            for k in keys:
                for c in cols:
                    if k in str(c):
                        return c
            return None

        c_no = get("No.", "No", "번호")
        c_kind = get("구분")
        c_pay = get("대금지불")
        c_name = get("계약명")
        c_item = get("품명")
        c_start = get("계약시작일", "시작일")
        c_end = get("계약만료일", "만료일", "종료일")
        c_months = get("계약기간")
        c_remain = get("잔여일수")
        c_auto = get("자동연장")
        c_party = get("공급받는자", "공급 받는 자", "공급받는 자", "거래처")
        c_amount = get("계약금액")
        c_issued = get("발행금액")
        c_unpaid = get("미수금")
        c_setdate = get("계약체결일", "체결일")
        c_install = get("설치일")
        c_warranty = get("하자보수만료")
        c_doc = get("계약서")
        c_owner = get("담당자")
        c_phone = get("연락처")
        c_warranty_period = get("무상하자")

        n = 0
        for idx, r in df.iterrows():
            name = normalize_name(r.get(c_name)) if c_name else None
            party = normalize_name(r.get(c_party)) if c_party else None
            if not name and not party:
                continue
            if name and any(s in name for s in ["합계", "소계", "총계"]):
                continue
            party_code, party_display = resolve_party(party, party_map)
            item = normalize_name(r.get(c_item)) if c_item else None
            prod_code, prod_name = apply_product_mapping(item, rules)
            start = pd.to_datetime(r.get(c_start), errors="coerce") if c_start else pd.NaT
            end = pd.to_datetime(r.get(c_end), errors="coerce") if c_end else pd.NaT
            today = pd.Timestamp.today()
            remain = (end - today).days if pd.notna(end) else None
            status = "만료" if (pd.notna(end) and end < today) else "진행"
            if sh == "2016 ~ (종료)":
                status = "만료"

            rows.append({
                "계약ID": f"K-{sh[:4]}-{idx + 3:04d}",
                "계약명": name,
                "구분(유지보수/장비/AI/판독/임대/기타)": str(r.get(c_kind, "") or "").strip() if c_kind else None,
                "거래처코드": party_code,
                "공급받는자(거래처명)": party_display,
                "제품코드": prod_code,
                "품명": item,
                "계약체결일": pd.to_datetime(r.get(c_setdate), errors="coerce").date() if c_setdate and pd.notna(r.get(c_setdate)) else None,
                "계약시작일": start.date() if pd.notna(start) else None,
                "계약만료일": end.date() if pd.notna(end) else None,
                "계약기간(개월)": f(r.get(c_months)) if c_months else None,
                "자동연장(Y/N)": str(r.get(c_auto, "") or "").strip() if c_auto else None,
                "잔여일수": remain,
                "계약금액": f(r.get(c_amount)) if c_amount else 0,
                "발행금액": f(r.get(c_issued)) if c_issued else 0,
                "미수금": f(r.get(c_unpaid)) if c_unpaid else 0,
                "대금지불(월/분기/연/일시)": str(r.get(c_pay, "") or "").strip() if c_pay else None,
                "결제일": None,
                "설치일": pd.to_datetime(r.get(c_install), errors="coerce").date() if c_install and pd.notna(r.get(c_install)) else None,
                "하자보수만료일": pd.to_datetime(r.get(c_warranty), errors="coerce").date() if c_warranty and pd.notna(r.get(c_warranty)) else None,
                "계약서유무": str(r.get(c_doc, "") or "").strip() if c_doc else None,
                "담당자": str(r.get(c_owner, "") or "").strip() if c_owner else None,
                "연락처": str(r.get(c_phone, "") or "").strip() if c_phone else None,
                "활성상태(진행/만료/해지)": status,
                "비고": None,
            })
            n += 1
        print(f"  계약마스터/{sh}: {n}건")
    return pd.DataFrame(rows)


# ==================== 31. 차입금마스터 ====================
def load_차입금마스터():
    rows = []
    # 주요계정 파일의 장기차입금 시트
    try:
        df = pd.read_excel(SRC["주요계정"], sheet_name="장기차입금", header=0)
        cols = list(df.columns)
        for idx, r in df.iterrows():
            bank = normalize_name(r.get("금융기관명") if "금융기관명" in cols else None)
            if not bank or any(s in bank for s in ["합계", "소계", "총계"]):
                continue

            def gv(key):
                for c in cols:
                    if key in str(c):
                        return r.get(c)
                return None

            장단기 = str(gv("장단기") or "").strip()
            구분 = "은행" if 장단기 else "은행"
            if "개인" in bank or "사채" in bank:
                구분 = "개인"
            initial = f(gv("최초차입액"))
            current = f(gv("차입금"))
            rate = gv("이자율")
            start = pd.to_datetime(gv("차입일"), errors="coerce")
            end = pd.to_datetime(gv("만기일"), errors="coerce")
            today = pd.Timestamp.today()
            status = "만료" if (pd.notna(end) and end < today) else "활성"

            rows.append({
                "차입ID": f"LM-{idx + 2:04d}",
                "구분(은행/개인/사채)": 구분,
                "장단기": 장단기 or ("장기" if pd.notna(end) and (end - today).days > 365 else "단기"),
                "금융기관/차주": bank,
                "계좌번호/식별": None,
                "약정한도": None,
                "최초차입액": initial,
                "현재잔액": current,
                "차입종류": str(gv("차입종류") or "").strip(),
                "이자율(%)": float(rate) * 100 if (rate is not None and pd.notna(rate) and float(rate) < 1) else (float(rate) if rate is not None and pd.notna(rate) else None),
                "상환방법": str(gv("상환방법") or "").strip(),
                "차입일": start.date() if pd.notna(start) else None,
                "만기일": end.date() if pd.notna(end) else None,
                "담보": str(gv("담보") or "").strip(),
                "담보설정액": f(gv("담보설정액")),
                "대표이사지급보증": str(gv("대표이사지급보증") or "").strip(),
                "활성상태": status,
                "비고": str(gv("비고") or "").strip(),
            })
        print(f"  차입금마스터 (장기): {len(rows)}건")
    except Exception as e:
        print(f"  차입금마스터 오류: {e}")
        import traceback
        traceback.print_exc()

    # 단기차입금 (임원) 합계표
    try:
        df = pd.read_excel(SRC["단기차입금"], sheet_name="합계표")
        cols = list(df.columns)
        # 합계표는 임원별 row + 금액 컬럼
        for idx, r in df.iterrows():
            name = normalize_name(r.iloc[0]) if len(r) > 0 else None
            if not name or any(s in name for s in ["합계", "소계", "원장조회"]):
                continue
            # 임원명만 추출
            if name not in ["김하남", "최정훈", "송민희", "이현근"]:
                continue
            total = f(r.iloc[-1]) if len(r) > 1 else 0
            rows.append({
                "차입ID": f"LM-IM-{idx + 2:02d}",
                "구분(은행/개인/사채)": "개인(임원)",
                "장단기": "단기",
                "금융기관/차주": name,
                "계좌번호/식별": None,
                "약정한도": None,
                "최초차입액": None,
                "현재잔액": total,
                "차입종류": "임원 단기차입",
                "이자율(%)": None,
                "상환방법": None,
                "차입일": None,
                "만기일": None,
                "담보": None,
                "담보설정액": None,
                "대표이사지급보증": None,
                "활성상태": "활성" if total > 0 else "만료",
                "비고": "임원 단기차입금",
            })
        print(f"  차입금마스터 (임원 단기): 추가")
    except Exception as e:
        print(f"  단기차입금/합계표 오류: {e}")

    return pd.DataFrame(rows)


if __name__ == "__main__":
    print("=== P7: 판독수수료·임대료·계약·차입금마스터 ===")
    wb = load_master()
    party_map = build_party_map(wb)
    rules = get_mapping_rules(wb)

    print("\n[1/4] 판독수수료")
    df_r = load_판독수수료(party_map)
    cols_r = ["거래ID", "귀속년월", "년", "월", "매출/매입", "병원/공급처", "대리점",
              "제품코드", "제품명", "판독건수", "단가", "판독료", "인비즈수익",
              "대리점수수료", "매출액", "원가", "순이익", "이익률", "비고", "원본파일"]
    if len(df_r):
        df_r = df_r[cols_r]

    print("\n[2/4] 임대료")
    df_l = load_임대료()
    cols_l = ["거래ID", "일자", "년", "월", "구분(수입/지출)", "거래처",
              "물건명(사무실/장비)", "항목(임차료/관리비/공과금/렌탈료)",
              "금액", "결제수단", "비고", "원본파일"]
    if len(df_l):
        df_l = df_l[cols_l]

    print("\n[3/4] 계약마스터")
    df_k = load_계약마스터(party_map, rules)
    cols_k = ["계약ID", "계약명", "구분(유지보수/장비/AI/판독/임대/기타)",
              "거래처코드", "공급받는자(거래처명)", "제품코드", "품명",
              "계약체결일", "계약시작일", "계약만료일", "계약기간(개월)",
              "자동연장(Y/N)", "잔여일수", "계약금액", "발행금액", "미수금",
              "대금지불(월/분기/연/일시)", "결제일", "설치일", "하자보수만료일",
              "계약서유무", "담당자", "연락처", "활성상태(진행/만료/해지)", "비고"]
    if len(df_k):
        df_k = df_k[cols_k]

    print("\n[4/4] 차입금마스터")
    df_lm = load_차입금마스터()
    cols_lm = ["차입ID", "구분(은행/개인/사채)", "장단기", "금융기관/차주",
               "계좌번호/식별", "약정한도", "최초차입액", "현재잔액",
               "차입종류", "이자율(%)", "상환방법", "차입일", "만기일",
               "담보", "담보설정액", "대표이사지급보증", "활성상태", "비고"]
    if len(df_lm):
        df_lm = df_lm[cols_lm]

    print("\n워크북 적재 중...")
    if len(df_r):
        write_dim_or_fact(wb, "28_FACT_판독수수료", df_r, "tbl_판독수수료")
    if len(df_l):
        write_dim_or_fact(wb, "26_FACT_임대료", df_l, "tbl_임대료")
    if len(df_k):
        write_dim_or_fact(wb, "30_계약마스터", df_k, "tbl_계약")
    if len(df_lm):
        write_dim_or_fact(wb, "31_차입금마스터", df_lm, "tbl_차입금마스터")
    save_master(wb)
    print("완료.")
