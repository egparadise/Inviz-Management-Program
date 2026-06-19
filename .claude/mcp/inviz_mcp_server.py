# -*- coding: utf-8 -*-
"""Inviz 경영관리 MCP 서버 — Claude/외부 LLM이 Inviz DB·RAG에 접근하는 도구

사용:
  python inviz_mcp_server.py                      # stdio (Claude Desktop / Claude Code)

도구:
  - query_sales(year, month, party_name) — 매출 조회
  - query_purchases(...) — 매입 조회
  - kpi_overview(year) — 연간 KPI
  - search_party(name) — 거래처 조회
  - list_contracts(status, expiring_within_days) — 계약
  - list_documents(doc_type, expiring_within_days) — 인증서·서류
  - loan_status() — 차입금 잔액
  - rag_search(query, k) — 벡터 DB 의미 검색
  - integrity_status() — 무결성 점검 결과
  - sync_status() — 동기화 이력
"""
import sys
from pathlib import Path
from datetime import date, datetime, timedelta
from typing import Optional

# 웹앱 모듈을 import 경로에 추가
ROOT = Path(__file__).parent.parent.parent / "web_app"
sys.path.insert(0, str(ROOT))

from mcp.server.fastmcp import FastMCP
from sqlalchemy import select, func, or_

mcp = FastMCP("inviz-management")


def _db():
    from database import SessionLocal
    return SessionLocal()


def _fmt(v):
    if v is None:
        return None
    try:
        return int(round(float(v)))
    except Exception:
        return v


# ============ 매출 ============
@mcp.tool()
def query_sales(year: Optional[int] = None, month: Optional[int] = None,
                party_name: Optional[str] = None,
                from_date: Optional[str] = None, to_date: Optional[str] = None) -> dict:
    """인비즈 매출 트랜잭션 조회. 연도/월/거래처/기간 필터 조합 가능.

    Returns: count, sum_supply, sum_vat, sum_total, top_parties, top_products
    """
    from models import Sale
    db = _db()
    try:
        conds = []
        if year: conds.append(Sale.year == int(year))
        if month: conds.append(Sale.month == int(month))
        if party_name: conds.append(Sale.party_name.contains(party_name))
        if from_date: conds.append(Sale.txn_date >= datetime.strptime(from_date, "%Y-%m-%d").date())
        if to_date: conds.append(Sale.txn_date <= datetime.strptime(to_date, "%Y-%m-%d").date())

        cnt = db.scalar(select(func.count()).select_from(Sale).where(*conds)) or 0
        sum_supply = db.scalar(select(func.coalesce(func.sum(Sale.supply), 0)).where(*conds)) or 0
        sum_vat = db.scalar(select(func.coalesce(func.sum(Sale.vat), 0)).where(*conds)) or 0
        sum_total = db.scalar(select(func.coalesce(func.sum(Sale.total), 0)).where(*conds)) or 0

        excl = ["합 계", "합계", "소계", "총계", "TOTAL"]
        top_parties = db.execute(
            select(Sale.party_name, func.sum(Sale.supply))
            .where(*conds, Sale.party_name.is_not(None), ~Sale.party_name.in_(excl))
            .group_by(Sale.party_name)
            .order_by(func.sum(Sale.supply).desc()).limit(5)
        ).all()
        top_products = db.execute(
            select(Sale.product_name, func.sum(Sale.supply))
            .where(*conds, Sale.product_name.is_not(None))
            .group_by(Sale.product_name)
            .order_by(func.sum(Sale.supply).desc()).limit(5)
        ).all()
        return {
            "count": cnt,
            "sum_supply": _fmt(sum_supply),
            "sum_vat": _fmt(sum_vat),
            "sum_total": _fmt(sum_total),
            "top_parties": [{"name": n, "supply": _fmt(v)} for n, v in top_parties],
            "top_products": [{"product": n, "supply": _fmt(v)} for n, v in top_products],
            "filters": {"year": year, "month": month, "party_name": party_name,
                        "from_date": from_date, "to_date": to_date},
        }
    finally:
        db.close()


# ============ 매입 ============
@mcp.tool()
def query_purchases(year: Optional[int] = None, month: Optional[int] = None,
                    party_name: Optional[str] = None,
                    from_date: Optional[str] = None, to_date: Optional[str] = None) -> dict:
    """인비즈 매입 트랜잭션 조회."""
    from models import Purchase
    db = _db()
    try:
        conds = []
        if year: conds.append(Purchase.year == int(year))
        if month: conds.append(Purchase.month == int(month))
        if party_name: conds.append(Purchase.party_name.contains(party_name))
        if from_date: conds.append(Purchase.txn_date >= datetime.strptime(from_date, "%Y-%m-%d").date())
        if to_date: conds.append(Purchase.txn_date <= datetime.strptime(to_date, "%Y-%m-%d").date())

        cnt = db.scalar(select(func.count()).select_from(Purchase).where(*conds)) or 0
        sum_supply = db.scalar(select(func.coalesce(func.sum(Purchase.supply), 0)).where(*conds)) or 0
        excl = ["합 계", "합계", "소계", "총계"]
        top = db.execute(
            select(Purchase.party_name, func.sum(Purchase.supply))
            .where(*conds, Purchase.party_name.is_not(None), ~Purchase.party_name.in_(excl))
            .group_by(Purchase.party_name)
            .order_by(func.sum(Purchase.supply).desc()).limit(5)
        ).all()
        return {
            "count": cnt, "sum_supply": _fmt(sum_supply),
            "top_parties": [{"name": n, "supply": _fmt(v)} for n, v in top],
            "filters": {"year": year, "month": month, "party_name": party_name},
        }
    finally:
        db.close()


# ============ KPI ============
@mcp.tool()
def kpi_overview(year: Optional[int] = None) -> dict:
    """연간 종합 KPI — 매출/매입/이익/급여/차입금/계약/만료임박 문서."""
    from models import Sale, Purchase, Payroll, LoanMaster, Contract, Document
    db = _db()
    try:
        y = year or date.today().year
        sales = float(db.scalar(select(func.coalesce(func.sum(Sale.supply), 0)).where(Sale.year == y)) or 0)
        purch = float(db.scalar(select(func.coalesce(func.sum(Purchase.supply), 0)).where(Purchase.year == y)) or 0)
        payroll = float(db.scalar(select(func.coalesce(func.sum(Payroll.gross_pay), 0)).where(Payroll.year == y)) or 0)
        loan = float(db.scalar(select(func.coalesce(func.sum(LoanMaster.current_balance), 0))) or 0)
        contracts_active = db.scalar(select(func.count()).where(Contract.status == "진행").select_from(Contract)) or 0
        today = date.today()
        exp30 = db.scalar(select(func.count()).where(
            Document.expiry_date.is_not(None),
            Document.expiry_date >= today,
            Document.expiry_date <= today + timedelta(days=30),
        ).select_from(Document)) or 0
        return {
            "year": y,
            "sales": _fmt(sales),
            "purchases": _fmt(purch),
            "gross_margin": _fmt(sales - purch),
            "gross_margin_pct": round((sales - purch) / sales * 100, 1) if sales else 0,
            "payroll": _fmt(payroll),
            "operating_income": _fmt(sales - purch - payroll),
            "loan_balance": _fmt(loan),
            "active_contracts": contracts_active,
            "docs_expiring_30d": exp30,
        }
    finally:
        db.close()


# ============ 거래처 ============
@mcp.tool()
def search_party(name: str) -> dict:
    """거래처(병원·회사) 검색 및 매출/매입 누계."""
    from models import Party, Sale, Purchase
    db = _db()
    try:
        rows = db.execute(
            select(Party).where(or_(Party.name.contains(name), Party.code == name)).limit(10)
        ).scalars().all()
        items = []
        for p in rows:
            s = float(db.scalar(select(func.coalesce(func.sum(Sale.supply), 0))
                                .where(Sale.party_code == p.code)) or 0)
            pur = float(db.scalar(select(func.coalesce(func.sum(Purchase.supply), 0))
                                  .where(Purchase.party_code == p.code)) or 0)
            items.append({
                "code": p.code, "name": p.name, "category": p.category,
                "biz_no": p.biz_no, "active": p.active,
                "sale_total": _fmt(s), "purchase_total": _fmt(pur),
                "first_seen": p.first_seen.isoformat() if p.first_seen else None,
                "last_seen": p.last_seen.isoformat() if p.last_seen else None,
            })
        return {"query": name, "found": len(items), "items": items}
    finally:
        db.close()


# ============ 계약 ============
@mcp.tool()
def list_contracts(status: Optional[str] = None,
                   expiring_within_days: Optional[int] = None,
                   party_name: Optional[str] = None) -> dict:
    """계약 목록. status='진행'/'만료'/'해지', expiring_within_days로 만료 임박 필터."""
    from models import Contract
    db = _db()
    try:
        conds = []
        if status: conds.append(Contract.status == status)
        if party_name: conds.append(Contract.party_name.contains(party_name))
        today = date.today()
        if expiring_within_days:
            cutoff = today + timedelta(days=int(expiring_within_days))
            conds.append(Contract.end_date.is_not(None))
            conds.append(Contract.end_date <= cutoff)
            conds.append(Contract.end_date >= today)

        cnt = db.scalar(select(func.count()).select_from(Contract).where(*conds)) or 0
        rows = db.execute(
            select(Contract).where(*conds)
            .order_by(Contract.end_date.asc().nullslast()).limit(20)
        ).scalars().all()
        items = [{
            "id": c.id, "name": c.name, "party": c.party_name, "kind": c.kind,
            "start": c.start_date.isoformat() if c.start_date else None,
            "end": c.end_date.isoformat() if c.end_date else None,
            "remain_days": (c.end_date - today).days if c.end_date else None,
            "amount": _fmt(c.contract_amount or 0),
            "unpaid": _fmt(c.unpaid_amount or 0),
            "status": c.status,
        } for c in rows]
        return {"count": cnt, "items": items, "filters": {
            "status": status, "expiring_within_days": expiring_within_days,
            "party_name": party_name,
        }}
    finally:
        db.close()


# ============ 서류·인증서 ============
@mcp.tool()
def list_documents(doc_type: Optional[str] = None,
                   expiring_within_days: Optional[int] = None,
                   search: Optional[str] = None) -> dict:
    """인증서·특허·공증·납세증명 등 회사 서류 검색."""
    from models import Document
    db = _db()
    try:
        conds = []
        if doc_type: conds.append(Document.doc_type.contains(doc_type))
        if search:
            conds.append(or_(Document.name.contains(search),
                             Document.file_name.contains(search),
                             Document.note.contains(search)))
        today = date.today()
        if expiring_within_days:
            cutoff = today + timedelta(days=int(expiring_within_days))
            conds.append(Document.expiry_date.is_not(None))
            conds.append(Document.expiry_date <= cutoff)
            conds.append(Document.expiry_date >= today)

        cnt = db.scalar(select(func.count()).select_from(Document).where(*conds)) or 0
        rows = db.execute(
            select(Document).where(*conds)
            .order_by(Document.expiry_date.asc().nullslast()).limit(30)
        ).scalars().all()
        items = [{
            "id": d.id, "name": d.name, "type": d.doc_type, "issuer": d.issuer,
            "issue_date": d.issue_date.isoformat() if d.issue_date else None,
            "expiry_date": d.expiry_date.isoformat() if d.expiry_date else None,
            "remain_days": (d.expiry_date - today).days if d.expiry_date else None,
            "has_file": bool(d.file_path),
            "folder": d.folder_category,
        } for d in rows]
        return {"count": cnt, "items": items}
    finally:
        db.close()


# ============ 차입금 ============
@mcp.tool()
def loan_status() -> dict:
    """전체 차입금 현황 — 은행/개인/임원 구분."""
    from models import LoanMaster
    db = _db()
    try:
        rows = db.execute(select(LoanMaster).order_by(LoanMaster.current_balance.desc().nullslast())).scalars().all()
        items = [{
            "id": l.id, "institution": l.institution,
            "kind": l.kind, "term": l.term,
            "initial": _fmt(l.initial_amount or 0),
            "balance": _fmt(l.current_balance or 0),
            "rate_pct": l.interest_rate,
            "start": l.start_date.isoformat() if l.start_date else None,
            "end": l.end_date.isoformat() if l.end_date else None,
            "status": l.status,
        } for l in rows]
        total = sum((l.current_balance or 0) for l in rows)
        return {"count": len(items), "total_balance": _fmt(total), "items": items}
    finally:
        db.close()


# ============ RAG 의미 검색 ============
@mcp.tool()
def rag_search(query: str, k: int = 5) -> dict:
    """벡터 DB(FAISS + bge-m3)에서 의미 기반 검색. LLM 호출 없이 유사 청크만 반환.

    회사 데이터 1,321개 청크: 거래처·제품·계약·서류·차입금·매출요약·매입요약
    """
    try:
        from rag import retrieve_hybrid
        hits = retrieve_hybrid(query, k_kb=int(k), k_conv=2, min_score=0.0)
        return {
            "query": query,
            "found": len(hits),
            "results": [{
                "title": h.get("metadata", {}).get("title"),
                "type": h.get("metadata", {}).get("source_type"),
                "score": round(h.get("score", 0), 3),
                "page_url": h.get("metadata", {}).get("page_url"),
                "content": h.get("content", "")[:300],
                "source": h.get("source"),
            } for h in hits],
        }
    except Exception as e:
        return {"error": str(e), "hint": "FAISS 인덱스가 비어있을 수 있음. /knowledge에서 재인덱싱."}


# ============ 무결성·동기화 ============
@mcp.tool()
def integrity_status() -> dict:
    """데이터 무결성 검증 결과."""
    from models import IntegrityCheck
    db = _db()
    try:
        total = db.scalar(select(func.count()).select_from(IntegrityCheck)) or 0
        by_status = db.execute(
            select(IntegrityCheck.status, func.count()).group_by(IntegrityCheck.status)
        ).all()
        recent = db.execute(
            select(IntegrityCheck).where(IntegrityCheck.status.in_(["warning", "critical", "rolled_back"]))
            .order_by(IntegrityCheck.id.desc()).limit(10)
        ).scalars().all()
        suspicious = [{
            "table": w.table_name, "metric": w.metric,
            "before": w.before_value, "after": w.after_value,
            "delta_pct": round(w.delta_pct, 1) if w.delta_pct else None,
            "status": w.status,
        } for w in recent]
        return {
            "total_checks": total,
            "by_status": {s: c for s, c in by_status},
            "recent_suspicious": suspicious,
        }
    finally:
        db.close()


@mcp.tool()
def sync_status() -> dict:
    """최근 동기화 이력 + 미매핑 파일 큐."""
    from models import SyncRun, FileRegistry, UnmappedFileReview
    db = _db()
    try:
        runs = db.execute(select(SyncRun).order_by(SyncRun.id.desc()).limit(5)).scalars().all()
        unmapped = db.scalar(select(func.count()).where(FileRegistry.domain.is_(None))
                             .select_from(FileRegistry)) or 0
        pending_review = db.scalar(select(func.count()).where(UnmappedFileReview.status == "pending")
                                   .select_from(UnmappedFileReview)) or 0
        return {
            "tracked_files": db.scalar(select(func.count()).select_from(FileRegistry)) or 0,
            "unmapped_files": unmapped,
            "llm_review_queue": pending_review,
            "recent_runs": [{
                "id": r.id, "started": r.started_at.isoformat() if r.started_at else None,
                "status": r.status, "files_processed": r.files_processed,
                "rows_added": r.rows_added, "rows_removed": r.rows_removed,
            } for r in runs],
        }
    finally:
        db.close()


# ============ 개발 방법론 플레이북 ============
_PLAYBOOK = {
    "design": "inviz-design",          # 디자인
    "feature": "inviz-feature",        # 기능 개발 레시피
    "process": "inviz-dev-process",    # 개발 전체 프로세스
    "troubleshoot": "inviz-troubleshoot",  # 문제 해결
}


@mcp.tool()
def dev_playbook(section: Optional[str] = None) -> dict:
    """인비즈 제품 개발 방법론 플레이북 조회(.claude 스킬).

    section: design(디자인) / feature(기능 레시피) / process(개발 프로세스) / troubleshoot(문제해결).
    비우면 사용 가능한 섹션·에이전트 목록 반환.
    """
    skills_dir = Path(__file__).parent.parent / "skills"
    if not section:
        return {
            "sections": list(_PLAYBOOK.keys()),
            "agents": ["inviz-feature-builder", "inviz-ui-designer", "inviz-debugger"],
            "hint": "section=feature 처럼 호출하면 해당 스킬 전문을 반환합니다.",
        }
    name = _PLAYBOOK.get(section.lower().strip())
    if not name:
        return {"error": f"알 수 없는 섹션: {section}", "available": list(_PLAYBOOK.keys())}
    f = skills_dir / name / "SKILL.md"
    if not f.exists():
        return {"error": f"스킬 파일 없음: {name}"}
    return {"section": section, "skill": name, "content": f.read_text(encoding="utf-8")}


# ============ 리소스 — 회사 컨텍스트 ============
@mcp.resource("inviz://overview")
def overview() -> str:
    """인비즈 회사 개요 + 시스템 안내"""
    return (Path(__file__).parent.parent / "CLAUDE.md").read_text(encoding="utf-8")


@mcp.resource("inviz://playbook")
def playbook_index() -> str:
    """개발 방법론(디자인·기능·프로세스·문제해결) 인덱스"""
    idx = Path(__file__).parent.parent / "METHODOLOGY.md"
    return idx.read_text(encoding="utf-8") if idx.exists() else "METHODOLOGY.md 없음 (아직 생성 전)"


if __name__ == "__main__":
    mcp.run()
