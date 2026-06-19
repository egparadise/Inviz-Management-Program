# -*- coding: utf-8 -*-
"""P2: DIM_거래처 추출

소스:
- 외상매출금 (2022~2026 시트)
- 외상매입금 (2022~2026 시트)
- 미수금 현황 (전체 시트)
- 계약관리 (계약현황_2025, 미수금현황, 2016~종료 시트)
- 매출분류 (2021~2023 시트의 거래처 컬럼)
- 거래처세계 (2022~2024 매출/매입 시트)
"""
import pandas as pd
from collections import defaultdict
from common import SRC, load_master, save_master, write_dim_or_fact, normalize_name, classify_party

def collect():
    parties = defaultdict(lambda: {
        "is_매출": 0, "is_매입": 0, "is_계약": 0, "is_미수금": 0,
        "first_seen": None, "last_seen": None, "sources": set(),
    })

    def add(name, kind, when=None, source=None):
        nm = normalize_name(name)
        if not nm:
            return
        # 합계/소계/총계 등 제외
        if any(s in nm for s in ["합계", "소계", "총계", "TOTAL", "Total"]):
            return
        # 단순 숫자/구분자 제외
        if nm.isdigit() or len(nm) <= 1:
            return
        rec = parties[nm]
        rec[kind] = 1
        if source:
            rec["sources"].add(source)
        if when:
            try:
                w = pd.to_datetime(when, errors="coerce")
                if pd.notna(w):
                    if rec["first_seen"] is None or w < rec["first_seen"]:
                        rec["first_seen"] = w
                    if rec["last_seen"] is None or w > rec["last_seen"]:
                        rec["last_seen"] = w
            except Exception:
                pass

    # --- 외상매출금/매입금: 거래처명 컬럼 (B열) -----
    for label, src_key, kind in [("외상매출금", "외상매출금", "is_매출"),
                                  ("외상매입금", "외상매입금", "is_매입")]:
        path = SRC[src_key]
        for sh in ["외상매출금(2022)", "외상매출금(2023)", "외상매출금(2024)",
                   "외상매출금(2025)", "외상매출금(2026)",
                   "외상매입금(2022)", "외상매입금(2023)", "외상매입금(2024)",
                   "외상매입금(2025)", "외상매입금(2026)"]:
            try:
                df = pd.read_excel(path, sheet_name=sh, header=1)
            except Exception:
                continue
            col = df.columns[0]
            for v in df[col].dropna():
                add(v, kind, source=f"{label}/{sh}")

    # --- 미수금 현황: 전체 시트 + 거래처별 시트 -----
    path = SRC["미수금"]
    try:
        xl = pd.ExcelFile(path)
        for sh in xl.sheet_names:
            if sh == "전체":
                df = pd.read_excel(path, sheet_name=sh, header=1)
                col = df.columns[0]
                for v in df[col].dropna():
                    add(v, "is_미수금", source=f"미수금/{sh}")
            else:
                # 시트 이름 자체가 거래처명인 경우가 많음
                add(sh, "is_미수금", source="미수금/시트명")
    except Exception as e:
        print(f"미수금 처리 오류: {e}")

    # --- 계약관리 -----
    path = SRC["계약관리"]
    try:
        df = pd.read_excel(path, sheet_name="계약현황_2025", header=1)
        for col in df.columns:
            if "공급" in str(col) or "받는자" in str(col):
                for v, dt in zip(df[col].dropna(), df.get("계약시작일", [None]*len(df))):
                    add(v, "is_계약", when=dt, source="계약/현황2025")
                break
        # 2016~종료 시트
        df2 = pd.read_excel(path, sheet_name="2016 ~ (종료)", header=1)
        for col in df2.columns:
            if "공급" in str(col) or "받는자" in str(col):
                for v in df2[col].dropna():
                    add(v, "is_계약", source="계약/종료")
                break
        # 미수금현황 시트
        df3 = pd.read_excel(path, sheet_name="미수금현황 (세부내역)", header=2)
        col = df3.columns[1]
        for v in df3[col].dropna():
            add(v, "is_미수금", source="계약/미수금")
    except Exception as e:
        print(f"계약관리 처리 오류: {e}")

    # --- 매출분류: 2021~2023 시트의 거래처 + 전표일자 -----
    path = SRC["매출분류"]
    for sh in ["2021", "2022", "2023"]:
        try:
            df = pd.read_excel(path, sheet_name=sh)
            party_col = [c for c in df.columns if "거래처" in str(c)]
            date_col = [c for c in df.columns if "전표일자" in str(c) or "일자" in str(c)]
            if party_col:
                pc = party_col[0]
                dc = date_col[0] if date_col else None
                for i, v in df[pc].dropna().items():
                    dt = df.at[i, dc] if dc else None
                    add(v, "is_매출", when=dt, source=f"매출분류/{sh}")
        except Exception as e:
            print(f"매출분류/{sh} 오류: {e}")

    # --- 거래처세계: 매출/매입 시트 -----
    path = SRC["거래처세계"]
    xl = pd.ExcelFile(path)
    for sh in xl.sheet_names:
        try:
            df = pd.read_excel(path, sheet_name=sh, header=1)
            # 거래처명 컬럼 찾기
            for col in df.columns:
                if "거래처" in str(col):
                    is_sales = "매출" in sh or "수금" in sh
                    kind = "is_매출" if is_sales else "is_매입"
                    for v in df[col].dropna():
                        add(v, kind, source=f"세계/{sh}")
                    break
        except Exception:
            continue

    return parties


def to_df(parties):
    rows = []
    sorted_parties = sorted(parties.items(),
                            key=lambda kv: (-kv[1]["is_매출"], -kv[1]["is_계약"], kv[0]))
    # 코드 부여: 매출 거래처 우선, 그 외 알파벳 순
    for i, (name, rec) in enumerate(sorted_parties, start=1):
        code = f"C{i:04d}"
        구분 = classify_party(name)
        rows.append({
            "거래처코드": code,
            "거래처명": name,
            "사업자번호": None,
            "구분(병원/대리점/공급사/기타)": 구분,
            "주거래제품": None,
            "활성여부": "Y" if rec["last_seen"] and rec["last_seen"].year >= 2024 else (
                "Y" if rec["is_매출"] or rec["is_계약"] else "N"),
            "최초거래일": rec["first_seen"].date() if rec["first_seen"] else None,
            "최종거래일": rec["last_seen"].date() if rec["last_seen"] else None,
            "주담당자": None,
            "연락처": None,
            "비고": ",".join(k.replace("is_", "") for k, v in rec.items()
                            if k.startswith("is_") and v == 1),
        })
    return pd.DataFrame(rows)


if __name__ == "__main__":
    print("=== P2: DIM_거래처 추출 ===")
    parties = collect()
    print(f"총 고유 거래처: {len(parties)}")
    df = to_df(parties)
    print(f"DataFrame shape: {df.shape}")
    print("\n구분 분포:")
    print(df["구분(병원/대리점/공급사/기타)"].value_counts())
    print("\n상위 10개 (활성여부 Y):")
    print(df[df["활성여부"] == "Y"].head(10)[["거래처코드", "거래처명", "구분(병원/대리점/공급사/기타)", "비고"]].to_string())

    print("\n워크북 적재 중...")
    wb = load_master()
    write_dim_or_fact(wb, "10_DIM_거래처", df, "tbl_거래처")
    save_master(wb)
    print("완료.")
