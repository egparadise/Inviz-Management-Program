# -*- coding: utf-8 -*-
"""사용자 의도 원장 (User Intent Ledger)

문제:
  파일이 폴더에 다시 올라오면 자동 sync가 같은 데이터를 다시 적재한다.
  사용자가 그 사이에 특정 행을 "이건 잘못됐다" 하고 삭제/수정했다면,
  다음 sync에서 삭제한 행이 부활하고 수정 내용이 원상복귀되어
  사용자 작업이 파괴된다.

해결:
  모든 사용자 삭제·수정·거부 이벤트를 UserIntentLedger에 signature로 영구 기록.
  sync가 새 행을 insert 하기 직전에 ledger를 조회하여
  같은 signature가 "delete/reject"로 기록돼 있으면 스킵 + prevention_count 증가.

signature 규칙:
  sha1(f"{kind}|{txn_date}|{norm_party}|{supply_int}")[:16]
  — dedup.py의 dup_key와 동일한 정규화(공백/(주)/특수문자 제거) 사용.
"""
import hashlib
import re
from datetime import date, datetime
from typing import Optional
from sqlalchemy import select, func, and_
from sqlalchemy.orm import Session

from models import UserIntentLedger
from dedup import norm_name, parse_date


def signature(kind: str, txn_date, party_name, supply) -> str:
    d = parse_date(txn_date)
    dstr = d.isoformat() if d else ""
    pn = norm_name(party_name or "")
    try:
        sup = int(round(float(supply or 0)))
    except Exception:
        sup = 0
    key = f"{kind}|{dstr}|{pn}|{sup}"
    return hashlib.sha1(key.encode("utf-8")).hexdigest()[:16]


# ===== 기록 (사용자 이벤트 발생 시) =====
def record_deletion(db: Session, *, kind: str, row, source_file: str = None,
                    reason: str = "", user: str = "", client_ip: str = "") -> Optional[UserIntentLedger]:
    """단일 행 삭제 시 호출. row는 Sale/Purchase 등 ORM 객체."""
    if row is None:
        return None
    sig = signature(kind, getattr(row, "txn_date", None) or getattr(row, "use_date", None),
                    getattr(row, "party_name", None) or getattr(row, "party_or_place", None),
                    getattr(row, "supply", None) or getattr(row, "amount", None))
    entry = UserIntentLedger(
        action="delete", kind=kind, signature=sig,
        txn_date=getattr(row, "txn_date", None) or getattr(row, "use_date", None),
        party_name=(getattr(row, "party_name", None) or getattr(row, "party_or_place", ""))[:200] if (getattr(row, "party_name", None) or getattr(row, "party_or_place", None)) else None,
        supply=float(getattr(row, "supply", None) or getattr(row, "amount", None) or 0),
        source_file=source_file or getattr(row, "source_file", None),
        source_row=getattr(row, "source_row", None),
        original_id=getattr(row, "id", None),
        reason=(reason or "사용자 삭제")[:300],
        user=user or None, client_ip=client_ip or None,
    )
    db.add(entry)
    return entry


def record_bulk_deletion(db: Session, *, kind: str, rows: list,
                         reason: str = "일괄 삭제", user: str = "", client_ip: str = "") -> int:
    """대량 삭제 시 (매출·매입 관리·업로드 되돌리기 등). N개 등록."""
    n = 0
    for row in rows:
        if record_deletion(db, kind=kind, row=row, reason=reason, user=user, client_ip=client_ip) is not None:
            n += 1
    return n


def record_edit(db: Session, *, kind: str, row_before, row_after=None,
                reason: str = "사용자 편집", user: str = "", client_ip: str = "") -> Optional[UserIntentLedger]:
    """행 편집 시 — 편집 전 signature를 'edit'으로 기록.
    (편집 후 signature가 다르면 그것도 별도로 'restore' 유무를 확인해야 하지만,
     현 단계에서는 편집 전만 기록해도 sync가 원본을 재삽입하지 못하게 함)
    """
    if row_before is None:
        return None
    sig = signature(kind, getattr(row_before, "txn_date", None) or getattr(row_before, "use_date", None),
                    getattr(row_before, "party_name", None),
                    getattr(row_before, "supply", None) or getattr(row_before, "amount", None))
    entry = UserIntentLedger(
        action="edit", kind=kind, signature=sig,
        txn_date=getattr(row_before, "txn_date", None) or getattr(row_before, "use_date", None),
        party_name=getattr(row_before, "party_name", None),
        supply=float(getattr(row_before, "supply", None) or getattr(row_before, "amount", None) or 0),
        source_file=getattr(row_before, "source_file", None),
        source_row=getattr(row_before, "source_row", None),
        original_id=getattr(row_before, "id", None),
        reason=(reason or "")[:300],
        user=user or None, client_ip=client_ip or None,
    )
    db.add(entry)
    return entry


# ===== 조회 (sync가 새 행 insert 전에 호출) =====
def load_blocked_signatures(db: Session, kind: str, *, source_file: str = None) -> set:
    """이 kind + (선택) source_file 에 대해 '차단' 상태인 signature 집합."""
    now = datetime.now()
    stmt = select(UserIntentLedger.signature).where(
        UserIntentLedger.kind == kind,
        UserIntentLedger.action.in_(["delete", "reject", "edit"]),
    )
    stmt = stmt.where(
        (UserIntentLedger.suppress_until.is_(None)) |
        (UserIntentLedger.suppress_until > now)
    )
    if source_file:
        # 같은 source_file에서 삭제됐거나, 파일 지정 없음(전역) 둘 다 매치
        stmt = stmt.where(
            (UserIntentLedger.source_file == source_file) |
            (UserIntentLedger.source_file.is_(None))
        )
    return set(row[0] for row in db.execute(stmt).all())


def record_prevention(db: Session, *, kind: str, sig: str) -> int:
    """차단이 실제로 일어났을 때 카운트 증가. 몇 건 갱신됐는지 반환."""
    now = datetime.now()
    n = db.execute(
        UserIntentLedger.__table__.update()
        .where(UserIntentLedger.kind == kind, UserIntentLedger.signature == sig)
        .values(prevention_count=UserIntentLedger.prevention_count + 1,
                last_prevented_at=now)
    ).rowcount or 0
    return n


def filter_bulk_by_intent(db: Session, kind: str, candidates: list,
                          *, source_file: str = None) -> tuple[list, int, list]:
    """sync_handlers의 bulk insert 직전 필터.

    candidates: ORM 객체 리스트 (예: [Sale(...), Sale(...)])
    반환: (통과한 candidates, 차단된 수, 차단된 signature 리스트)
    """
    blocked_sigs = load_blocked_signatures(db, kind, source_file=source_file)
    if not blocked_sigs:
        return candidates, 0, []
    keep = []
    blocked_list = []
    for row in candidates:
        sig = signature(kind,
                        getattr(row, "txn_date", None) or getattr(row, "use_date", None),
                        getattr(row, "party_name", None),
                        getattr(row, "supply", None) or getattr(row, "amount", None))
        if sig in blocked_sigs:
            blocked_list.append(sig)
            record_prevention(db, kind=kind, sig=sig)
        else:
            keep.append(row)
    if blocked_list:
        db.commit()
    return keep, len(blocked_list), blocked_list


# ===== 감시·통계 =====
def scan_recent(db: Session, *, days: int = 30, limit: int = 100) -> list[dict]:
    """최근 N일간 기록된 intent 이벤트 (표시용)."""
    from datetime import timedelta
    since = datetime.now() - timedelta(days=days)
    rows = db.execute(
        select(UserIntentLedger).where(UserIntentLedger.ts >= since)
        .order_by(UserIntentLedger.ts.desc()).limit(limit)
    ).scalars().all()
    return [{
        "id": r.id, "ts": r.ts.isoformat() if r.ts else "",
        "action": r.action, "kind": r.kind,
        "signature": r.signature,
        "date": r.txn_date.isoformat() if r.txn_date else "",
        "party": r.party_name or "",
        "supply": float(r.supply) if r.supply is not None else 0,
        "source_file": r.source_file or "",
        "reason": r.reason or "",
        "user": r.user or "",
        "prevention_count": r.prevention_count,
        "last_prevented_at": r.last_prevented_at.isoformat() if r.last_prevented_at else None,
    } for r in rows]


def stats(db: Session) -> dict:
    """통계 — AI 시스템 컨텍스트/설정 페이지용."""
    total = db.scalar(select(func.count()).select_from(UserIntentLedger)) or 0
    by_action = {}
    for row in db.execute(
        select(UserIntentLedger.action, func.count())
        .group_by(UserIntentLedger.action)
    ).all():
        by_action[row[0]] = int(row[1])
    prevented_sum = db.scalar(
        select(func.coalesce(func.sum(UserIntentLedger.prevention_count), 0))
    ) or 0
    active_blocks = db.scalar(
        select(func.count()).select_from(UserIntentLedger).where(
            UserIntentLedger.action.in_(["delete", "reject", "edit"]),
            (UserIntentLedger.suppress_until.is_(None)) |
            (UserIntentLedger.suppress_until > datetime.now())
        )
    ) or 0
    return {
        "total_entries": int(total),
        "by_action": by_action,
        "total_preventions": int(prevented_sum),
        "active_blocks": int(active_blocks),
    }


def restore(db: Session, entry_id: int, *, user: str = "") -> bool:
    """사용자가 명시적으로 '이 삭제는 실수였다 — 복구'를 요청. 해당 signature의 차단 해제."""
    row = db.get(UserIntentLedger, entry_id)
    if not row:
        return False
    row.action = "restore"
    row.reason = (row.reason or "") + f" [restored by {user or 'user'} at {datetime.now().isoformat()}]"
    db.commit()
    return True
