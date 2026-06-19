# -*- coding: utf-8 -*-
"""P3: DIM_직원 추출

소스:
- 퇴직연금 가입자명부조회 (입사·퇴사·재직여부·기준임금)
- 부서별 인건비 2023/2024 시트 (사번·부서·직급)
- 급여대장2025 (25.1월·25.2월·총괄표)
"""
import pandas as pd
import re
from common import SRC, load_master, save_master, write_dim_or_fact, normalize_name


def parse_jumin_last4(jumin):
    if pd.isna(jumin):
        return None
    s = str(jumin).replace("-", "").strip()
    if len(s) >= 7 and s[-7:].isdigit():
        return s[-4:]
    return None


def collect():
    employees = {}

    # --- 퇴직연금 가입자명부 ---
    df = pd.read_excel(SRC["퇴직연금"], sheet_name="가입자명부조회")
    # 컬럼: 가입자명, 주민등록번호, 기준임금, 기업납입금, 개인납입금, 입사일자, 가입일자, 퇴사일, 중간정산일, 가입자상태
    name_col = [c for c in df.columns if "가입자명" in str(c) or c == "성명"][0]
    for _, r in df.iterrows():
        nm = normalize_name(r[name_col])
        if not nm:
            continue
        employees[nm] = {
            "성명": nm,
            "주민_뒤4": parse_jumin_last4(r.get("주민등록번호")),
            "기준임금": r.get("기준임금"),
            "입사일": pd.to_datetime(r.get("입사일자"), errors="coerce"),
            "퇴사일": pd.to_datetime(r.get("퇴사일"), errors="coerce"),
            "재직여부": "재직" if pd.isna(r.get("퇴사일")) else "퇴직",
            "퇴직연금가입": "Y" if r.get("가입자상태") in ("가입", "재직", "운용") or pd.notna(r.get("가입일자")) else "N",
            "부서": None, "직급": None, "고용형태": None,
        }

    # --- 부서별 인건비 2023/2024 (부서·직급 보완) ---
    for sh in ["2023", "2024"]:
        try:
            df = pd.read_excel(SRC["부서인건비"], sheet_name=sh, header=2 if sh == "2024" else 0)
            name_col = next((c for c in df.columns if "사원명" in str(c) or "성명" in str(c) or "이름" in str(c)), None)
            dept_col = next((c for c in df.columns if "부서" in str(c)), None)
            sabeon_col = next((c for c in df.columns if "사번" in str(c)), None)
            if not name_col:
                continue
            for _, r in df.iterrows():
                nm = normalize_name(r[name_col])
                if not nm:
                    continue
                if nm not in employees:
                    employees[nm] = {
                        "성명": nm, "주민_뒤4": None, "기준임금": None,
                        "입사일": None, "퇴사일": None,
                        "재직여부": "재직", "퇴직연금가입": None,
                        "부서": None, "직급": None, "고용형태": None,
                    }
                if dept_col and pd.notna(r[dept_col]) and not employees[nm]["부서"]:
                    employees[nm]["부서"] = normalize_name(r[dept_col])
                if sabeon_col and pd.notna(r[sabeon_col]):
                    employees[nm]["사번"] = str(r[sabeon_col])
        except Exception as e:
            print(f"부서인건비/{sh} 오류: {e}")

    # --- 급여대장2025 ---
    for sh in ["25.1월", "25.2월"]:
        try:
            df = pd.read_excel(SRC["급여대장"], sheet_name=sh, header=2)
            name_col = next((c for c in df.columns if "사원명" in str(c) or "성명" in str(c) or "이름" in str(c)), None)
            dept_col = next((c for c in df.columns if "부서" in str(c)), None)
            sabeon_col = next((c for c in df.columns if "사번" in str(c)), None)
            if not name_col:
                continue
            for _, r in df.iterrows():
                nm = normalize_name(r[name_col])
                if not nm or nm in ("합계", "소계"):
                    continue
                if nm not in employees:
                    employees[nm] = {
                        "성명": nm, "주민_뒤4": None, "기준임금": None,
                        "입사일": None, "퇴사일": None,
                        "재직여부": "재직", "퇴직연금가입": None,
                        "부서": None, "직급": None, "고용형태": None,
                    }
                if dept_col and pd.notna(r[dept_col]) and not employees[nm].get("부서"):
                    employees[nm]["부서"] = normalize_name(r[dept_col])
                if sabeon_col and pd.notna(r[sabeon_col]):
                    employees[nm]["사번"] = str(r[sabeon_col])
        except Exception as e:
            print(f"급여대장/{sh} 오류: {e}")

    return employees


def to_df(employees):
    rows = []
    # 사번 부여: 입사일순으로 E0001~ (사번이 이미 있으면 우선 사용)
    sorted_emp = sorted(employees.values(),
                        key=lambda e: (pd.Timestamp.max if pd.isna(e["입사일"]) else e["입사일"]))
    for i, e in enumerate(sorted_emp, start=1):
        sabeon = e.get("사번") if e.get("사번") else f"E{i:04d}"
        rows.append({
            "사번": sabeon,
            "성명": e["성명"],
            "부서": e.get("부서"),
            "직급": e.get("직급"),
            "고용형태": e.get("고용형태") or ("정규" if pd.notna(e["입사일"]) else None),
            "입사일": e["입사일"].date() if pd.notna(e["입사일"]) else None,
            "퇴사일": e["퇴사일"].date() if pd.notna(e["퇴사일"]) else None,
            "재직여부": e["재직여부"],
            "주민등록번호(뒤4자리)": e["주민_뒤4"],
            "기준임금": e["기준임금"] if pd.notna(e.get("기준임금")) else None,
            "퇴직연금가입여부": e["퇴직연금가입"],
            "비고": None,
        })
    return pd.DataFrame(rows)


if __name__ == "__main__":
    print("=== P3: DIM_직원 추출 ===")
    emps = collect()
    print(f"총 직원: {len(emps)}")
    df = to_df(emps)
    print(f"DataFrame shape: {df.shape}")
    print("\n재직 분포:")
    print(df["재직여부"].value_counts())
    print("\n부서 분포 (상위 10):")
    print(df["부서"].value_counts().head(10))
    print("\n샘플 5명:")
    print(df.head(5).to_string())

    wb = load_master()
    write_dim_or_fact(wb, "13_DIM_직원", df, "tbl_직원")
    save_master(wb)
    print("완료.")
