# -*- coding: utf-8 -*-
"""중복 감지·차단 핵심 모듈 (Duplicate Detection)

용도:
- 매출/매입 업로드 시 기존 데이터와의 중복 행 식별
- 같은 업로드 배치 내부의 중복 행 식별
- DB 전체 스캔으로 누적 중복 현황 보고
- self_dev 무결성 체크와 통합 (중복률 추이 감시)

매칭 규칙:
- strict: (txn_date, party_normalized, supply_int, vat_int)
- normal: (txn_date, party_normalized, supply_int)  # 부가세 다른 케이스 허용
- fuzzy:  (txn_date, party_normalized, supply_bucket) — 금액 ±0.5%

기본은 normal. settings.duplicate_strictness로 조정.
"""
import re
from datetime import date, datetime
from typing import Optional
from sqlalchemy import select, func, and_, tuple_
from sqlalchemy.orm import Session

from models import Sale, Purchase


# ===== 이름 정규화 =====
_RE_NOISE = re.compile(r"(주식회사|\(주\)|\(유\)|\(재\)|\(사\)|（주）)")
_RE_SPACE = re.compile(r"\s+")
_RE_PUNCT = re.compile(r"[(){}\[\]·.,\-_/]")


def norm_name(n) -> str:
    if not n:
        return ""
    s = str(n).strip()
    s = _RE_NOISE.sub("", s)
    s = _RE_PUNCT.sub("", s)
    s = _RE_SPACE.sub("", s)
    return s.lower()


def parse_date(v) -> Optional[date]:
    if isinstance(v, date):
        return v
    if isinstance(v, datetime):
        return v.date()
    if not v:
        return None
    s = str(v).strip()
    for fmt in ("%Y-%m-%d", "%Y/%m/%d", "%Y.%m.%d", "%Y%m%d"):
        try:
            return datetime.strptime(s, fmt).date()
        except ValueError:
            continue
    return None


def dup_key(txn_date, party_name, supply, vat=None, *, strictness="normal") -> tuple:
    """행의 중복 키 — 같은 키면 동일 거래로 간주."""
    d = txn_date if isinstance(txn_date, date) else parse_date(txn_date)
    if not d:
        return ()
    name = norm_name(party_name)
    sup = int(round(float(supply or 0)))
    if strictness == "strict":
        v = int(round(float(vat or 0)))
        return (d, name, sup, v)
    if strictness == "fuzzy":
        # 0.5% 버킷
        bucket = sup // max(1, int(sup * 0.005)) if sup > 1000 else sup
        return (d, name, bucket)
    return (d, name, sup)


# ===== 기존 DB와 대조 =====
def find_existing_keys(db: Session, kind: str, rows: list[dict],
                       *, strictness: str = "normal") -> dict[tuple, int]:
    """미리보기 행들에 대해 DB에 이미 있는 키 → id 매핑 반환.

    rows: [{txn_date, party_name, supply, vat}, ...]
    """
    if not rows:
        return {}
    Model = Sale if kind == "sale" else Purchase

    # 날짜·금액 범위만 좁혀서 후보 행 조회 (인덱스 활용)
    dates = {parse_date(r["txn_date"]) for r in rows}
    dates = {d for d in dates if d}
    if not dates:
        return {}
    sups = {int(round(float(r.get("supply") or 0))) for r in rows}

    cands = db.execute(
        select(Model.id, Model.txn_date, Model.party_name, Model.supply, Model.vat)
        .where(Model.txn_date.in_(dates))
        .where(Model.supply.in_(sups))
    ).all()

    idx = {}
    for cid, dt, pn, sup, vat in cands:
        k = dup_key(dt, pn, sup, vat, strictness=strictness)
        if k:
            idx.setdefault(k, cid)
    return idx


def annotate_duplicates(db: Session, kind: str, rows: list[dict],
                        *, strictness: str = "normal") -> dict:
    """미리보기 행들에 중복 상태(_dup_status, _dup_existing_id) 주입.

    상태:
      - "new": 신규
      - "db_dup": 기존 DB와 중복
      - "batch_dup": 같은 업로드 배치 내 중복 (앞 행과 같음)

    반환: {new, db_dup, batch_dup}
    """
    existing = find_existing_keys(db, kind, rows, strictness=strictness)
    seen_in_batch: dict[tuple, int] = {}
    stats = {"new": 0, "db_dup": 0, "batch_dup": 0}
    for i, r in enumerate(rows):
        k = dup_key(r.get("txn_date"), r.get("party_name"),
                    r.get("supply"), r.get("vat"), strictness=strictness)
        if not k:
            r["_dup_status"] = "new"
            r["_dup_existing_id"] = None
            r["_dup_first_idx"] = None
            stats["new"] += 1
            continue
        if k in existing:
            r["_dup_status"] = "db_dup"
            r["_dup_existing_id"] = existing[k]
            r["_dup_first_idx"] = None
            stats["db_dup"] += 1
        elif k in seen_in_batch:
            r["_dup_status"] = "batch_dup"
            r["_dup_existing_id"] = None
            r["_dup_first_idx"] = seen_in_batch[k]
            stats["batch_dup"] += 1
        else:
            seen_in_batch[k] = i
            r["_dup_status"] = "new"
            r["_dup_existing_id"] = None
            r["_dup_first_idx"] = None
            stats["new"] += 1
    return stats


def filter_for_commit(rows: list[dict], *, allow_duplicates: bool = False) -> tuple[list[dict], int]:
    """commit 직전 — 중복 행을 걸러내고 (commit 대상, skipped_count) 반환."""
    if allow_duplicates:
        return rows, 0
    keep = [r for r in rows if r.get("_dup_status", "new") == "new"]
    return keep, len(rows) - len(keep)


# ===== DB 전체 중복 스캔 (감시용) =====
def scan_duplicates(db: Session, kind: str, *, strictness: str = "normal",
                    limit: int = 200) -> dict:
    """DB 전체에서 누적된 중복 그룹을 탐지.

    반환:
      {count_groups, count_rows_dup, sample: [{key, ids[], party, date, supply, count}]}
    """
    Model = Sale if kind == "sale" else Purchase
    # 같은 (date, party_name, supply)에 N>=2 인 그룹
    q = (
        select(Model.txn_date, Model.party_name, Model.supply,
               func.count().label("c"),
               func.group_concat(Model.id).label("ids"))
        .where(Model.party_name.is_not(None))
        .group_by(Model.txn_date, Model.party_name, Model.supply)
        .having(func.count() > 1)
        .order_by(func.count().desc())
        .limit(limit)
    )
    rows = db.execute(q).all()
    samples = []
    total_dup_rows = 0
    for r in rows:
        c = int(r.c)
        total_dup_rows += c  # 그룹 전체 (1개는 원본, c-1개는 중복)
        ids = [int(x) for x in (r.ids or "").split(",") if x]
        samples.append({
            "date": r.txn_date.isoformat() if r.txn_date else "",
            "party": r.party_name or "",
            "supply": float(r.supply or 0),
            "count": c,
            "ids": ids,
        })
    return {
        "kind": kind,
        "count_groups": len(samples),
        "count_rows_dup": total_dup_rows - len(samples),  # excess rows
        "sample": samples,
    }


def merge_duplicates(db: Session, kind: str, *, dry_run: bool = True) -> dict:
    """중복 그룹별로 가장 오래된(id 작은) 행만 남기고 나머지 삭제.

    합치기 전: 원본 행의 note에 "[merged: id1+id2+...]"를 append.
    """
    Model = Sale if kind == "sale" else Purchase
    scan = scan_duplicates(db, kind, limit=10000)
    removed = 0
    for grp in scan["sample"]:
        ids = sorted(grp["ids"])
        if len(ids) < 2:
            continue
        keep_id = ids[0]
        drop_ids = ids[1:]
        if not dry_run:
            keep_row = db.get(Model, keep_id)
            if keep_row:
                tag = f"[중복병합:{'+'.join(map(str, drop_ids))}]"
                keep_row.note = (keep_row.note or "") + " " + tag
            db.execute(Model.__table__.delete().where(Model.id.in_(drop_ids)))
            removed += len(drop_ids)
    if not dry_run and removed:
        db.commit()
    return {"kind": kind, "groups": scan["count_groups"], "rows_removed": removed,
            "dry_run": dry_run}


def overall_stats(db: Session) -> dict:
    """대시보드/AI 컨텍스트용 — 매출·매입 중복 현황 요약"""
    sale = scan_duplicates(db, "sale", limit=20)
    purchase = scan_duplicates(db, "purchase", limit=20)
    total_sale = db.scalar(select(func.count()).select_from(Sale)) or 0
    total_purchase = db.scalar(select(func.count()).select_from(Purchase)) or 0
    return {
        "sale": {
            "total_rows": total_sale,
            "dup_groups": sale["count_groups"],
            "dup_excess_rows": sale["count_rows_dup"],
            "dup_rate_pct": round(100 * sale["count_rows_dup"] / max(1, total_sale), 2),
        },
        "purchase": {
            "total_rows": total_purchase,
            "dup_groups": purchase["count_groups"],
            "dup_excess_rows": purchase["count_rows_dup"],
            "dup_rate_pct": round(100 * purchase["count_rows_dup"] / max(1, total_purchase), 2),
        },
    }
