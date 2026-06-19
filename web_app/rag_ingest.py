# -*- coding: utf-8 -*-
"""데이터 인제스트 — DB 데이터 → KnowledgeChunk → 벡터 DB

소스 도메인:
- party (거래처)
- product (제품)
- contract (계약)
- document (인증서/특허/공증/납세증명 등)
- loan_master (차입금)
- sale_monthly (월별 매출 요약)
- purchase_monthly (월별 매입 요약)

각 청크는 자연어 텍스트로 변환되어 임베딩됨.
"""
import json
from datetime import date, datetime
from typing import Optional
from sqlalchemy import select, func, and_
from sqlalchemy.orm import Session

from database import SessionLocal
from models import (Party, Product, Contract, Document, LoanMaster,
                    Sale, Purchase, KnowledgeChunk)
from rag import (count_tokens, content_hash, index_chunks_bulk,
                 get_splitter, EMBEDDING_MODEL)


def upsert_chunk(db: Session, source_type: str, source_id: str, title: str,
                 content: str, page_url: str = "", meta: dict = None) -> KnowledgeChunk:
    """청크를 SQLite에 upsert. 내용 변경 시에만 임베딩 재실행."""
    ch = content_hash(content)
    existing = db.execute(
        select(KnowledgeChunk).where(
            KnowledgeChunk.source_type == source_type,
            KnowledgeChunk.source_id == source_id,
        )
    ).scalar_one_or_none()

    if existing:
        if existing.content_hash == ch and existing.embedding_status == "embedded":
            return existing  # 변경 없음
        existing.content = content
        existing.title = title
        existing.page_url = page_url
        existing.content_hash = ch
        existing.token_count = count_tokens(content)
        existing.chunk_metadata = json.dumps(meta or {}, ensure_ascii=False)
        existing.embedding_status = "pending"
        return existing
    chunk = KnowledgeChunk(
        source_type=source_type, source_id=source_id,
        title=title, content=content, page_url=page_url,
        content_hash=ch, token_count=count_tokens(content),
        chunk_metadata=json.dumps(meta or {}, ensure_ascii=False),
        embedding_status="pending",
    )
    db.add(chunk)
    db.flush()
    return chunk


# ============ 청크 생성기 ============
def ingest_parties(db: Session) -> int:
    n = 0
    parties = db.execute(select(Party).where(Party.active == "Y")).scalars().all()
    for p in parties:
        # 거래처 누계
        sale_sum = db.scalar(select(func.coalesce(func.sum(Sale.supply), 0)).where(Sale.party_code == p.code)) or 0
        purch_sum = db.scalar(select(func.coalesce(func.sum(Purchase.supply), 0)).where(Purchase.party_code == p.code)) or 0
        sale_cnt = db.scalar(select(func.count()).select_from(Sale).where(Sale.party_code == p.code)) or 0
        text = (
            f"거래처 {p.name} ({p.code}). 구분 {p.category or '미분류'}."
            f" 사업자번호 {p.biz_no or '미등록'}."
            f" 누적 매출 {int(sale_sum):,}원 ({sale_cnt}건), 누적 매입 {int(purch_sum):,}원."
            f" 최초거래 {p.first_seen or '-'}, 최종거래 {p.last_seen or '-'}."
            f" 활성여부 {p.active}. 비고: {p.note or '없음'}"
        )
        upsert_chunk(db, "party", p.code, p.name, text,
                     page_url=f"/parties?q={p.name}",
                     meta={"category": p.category, "code": p.code})
        n += 1
    db.commit()
    return n


def ingest_products(db: Session) -> int:
    n = 0
    for p in db.execute(select(Product)).scalars().all():
        sale_sum = db.scalar(select(func.coalesce(func.sum(Sale.supply), 0)).where(Sale.product_code == p.code)) or 0
        sale_cnt = db.scalar(select(func.count()).select_from(Sale).where(Sale.product_code == p.code)) or 0
        text = (
            f"제품 {p.name} (코드 {p.code}, 카테고리 {p.category or '-'}). "
            f"그룹 {p.group or '-'}, 단가기준 {p.unit_basis or '-'}. "
            f"누적 매출 {int(sale_sum):,}원, 거래 {sale_cnt}건. 설명: {p.note or '없음'}"
        )
        upsert_chunk(db, "product", p.code, p.name, text,
                     page_url=f"/products",
                     meta={"category": p.category})
        n += 1
    db.commit()
    return n


def ingest_contracts(db: Session) -> int:
    n = 0
    today = date.today()
    for c in db.execute(select(Contract)).scalars().all():
        remain = (c.end_date - today).days if c.end_date else None
        text = (
            f"계약 {c.name or c.id}. 거래처: {c.party_name or '-'}. 구분: {c.kind or '-'}."
            f" 시작 {c.start_date or '-'}, 만료 {c.end_date or '-'} (잔여 {remain}일)."
            f" 계약금액 {int(c.contract_amount or 0):,}원, 발행 {int(c.issued_amount or 0):,}원,"
            f" 미수금 {int(c.unpaid_amount or 0):,}원."
            f" 상태 {c.status or '-'}, 담당자 {c.owner or '-'}. 비고: {c.note or ''}"
        )
        upsert_chunk(db, "contract", c.id, c.name or c.id, text,
                     page_url=f"/contracts?q={c.party_name or ''}",
                     meta={"status": c.status, "kind": c.kind})
        n += 1
    db.commit()
    return n


def ingest_documents(db: Session) -> int:
    n = 0
    today = date.today()
    for d in db.execute(select(Document)).scalars().all():
        remain = (d.expiry_date - today).days if d.expiry_date else None
        text = (
            f"서류 {d.name}. 종류 {d.doc_type or '-'}, 발급기관 {d.issuer or '-'}."
            f" 발급일 {d.issue_date or '-'}, 만료일 {d.expiry_date or '미정'}"
            + (f" (잔여 {remain}일)" if remain is not None else "") + "."
            f" 담당자 {d.owner or '-'}. 문서번호 {d.doc_no or '-'}."
            f" 폴더 {d.folder_category or '-'}, 파일 {d.file_name or '-'}."
            f" 비고: {d.note or '없음'}"
        )
        upsert_chunk(db, "document", str(d.id), d.name, text,
                     page_url=f"/documents/{d.id}/view" if d.file_path else "/documents",
                     meta={"doc_type": d.doc_type, "doc_id": d.id})
        n += 1
    db.commit()
    return n


def ingest_loans(db: Session) -> int:
    n = 0
    for l in db.execute(select(LoanMaster)).scalars().all():
        text = (
            f"차입금 {l.institution or '-'} ({l.kind or '-'}, {l.term or '-'})."
            f" 최초 {int(l.initial_amount or 0):,}원, 현재잔액 {int(l.current_balance or 0):,}원."
            f" 이자율 {l.interest_rate or '-'}%, 만기 {l.end_date or '-'}."
            f" 차입종류 {l.loan_type or '-'}. 담보 {l.collateral or '-'}."
            f" 상태 {l.status or '-'}. 비고: {l.note or ''}"
        )
        upsert_chunk(db, "loan_master", l.id, l.institution or l.id, text,
                     page_url="/loans",
                     meta={"kind": l.kind, "term": l.term})
        n += 1
    db.commit()
    return n


def ingest_sale_monthly(db: Session) -> int:
    """매출 월별 요약 청크 (연도-월별 + TOP 거래처/제품)"""
    n = 0
    rows = db.execute(
        select(Sale.year, Sale.month, func.count(), func.sum(Sale.supply))
        .group_by(Sale.year, Sale.month)
        .order_by(Sale.year, Sale.month)
    ).all()
    for year, month, cnt, total in rows:
        if not year or not month:
            continue
        # TOP 3 거래처
        tops = db.execute(
            select(Sale.party_name, func.sum(Sale.supply))
            .where(Sale.year == year, Sale.month == month, Sale.party_name.is_not(None),
                   ~Sale.party_name.in_(["합 계", "합계", "소계", "총계", "TOTAL"]))
            .group_by(Sale.party_name)
            .order_by(func.sum(Sale.supply).desc()).limit(3)
        ).all()
        top_txt = ", ".join(f"{n} ({int(v or 0):,}원)" for n, v in tops)
        text = (
            f"{year}년 {month}월 매출 요약. 총 {cnt}건, 공급가액 합계 {int(total or 0):,}원."
            f" 주요 거래처: {top_txt or '없음'}."
        )
        upsert_chunk(db, "sale_monthly", f"{year}-{month:02d}",
                     f"{year}년 {month}월 매출", text,
                     page_url=f"/sales?year={year}&month={month}",
                     meta={"year": year, "month": month})
        n += 1
    db.commit()
    return n


def ingest_purchase_monthly(db: Session) -> int:
    n = 0
    rows = db.execute(
        select(Purchase.year, Purchase.month, func.count(), func.sum(Purchase.supply))
        .group_by(Purchase.year, Purchase.month)
        .order_by(Purchase.year, Purchase.month)
    ).all()
    for year, month, cnt, total in rows:
        if not year or not month:
            continue
        tops = db.execute(
            select(Purchase.party_name, func.sum(Purchase.supply))
            .where(Purchase.year == year, Purchase.month == month, Purchase.party_name.is_not(None),
                   ~Purchase.party_name.in_(["합 계", "합계", "소계", "총계", "TOTAL"]))
            .group_by(Purchase.party_name)
            .order_by(func.sum(Purchase.supply).desc()).limit(3)
        ).all()
        top_txt = ", ".join(f"{n} ({int(v or 0):,}원)" for n, v in tops)
        text = (
            f"{year}년 {month}월 매입 요약. 총 {cnt}건, 공급가액 합계 {int(total or 0):,}원."
            f" 주요 매입처: {top_txt or '없음'}."
        )
        upsert_chunk(db, "purchase_monthly", f"{year}-{month:02d}",
                     f"{year}년 {month}월 매입", text,
                     page_url=f"/purchases?year={year}&month={month}",
                     meta={"year": year, "month": month})
        n += 1
    db.commit()
    return n


# ============ 전체 인제스트 + 벡터화 ============
def embed_pending(db: Session, batch_size: int = 40) -> dict:
    """embedding_status='pending'인 청크를 ChromaDB에 임베딩"""
    pending = db.execute(
        select(KnowledgeChunk).where(KnowledgeChunk.embedding_status == "pending")
    ).scalars().all()

    if not pending:
        return {"embedded": 0, "errors": 0, "remaining": 0}

    embedded = 0
    errors = 0
    for i in range(0, len(pending), batch_size):
        batch = pending[i:i + batch_size]
        try:
            items = []
            for ch in batch:
                meta = {
                    "source_type": ch.source_type,
                    "source_id": ch.source_id,
                    "title": ch.title or "",
                    "page_url": ch.page_url or "",
                }
                try:
                    meta.update(json.loads(ch.chunk_metadata or "{}"))
                except Exception:
                    pass
                items.append({"id": ch.id, "content": ch.content, "metadata": meta})

            index_chunks_bulk(items)
            for ch in batch:
                ch.embedding_status = "embedded"
                ch.embedding_model = EMBEDDING_MODEL
                ch.vector_id = f"kb-{ch.id}"
                ch.last_embedded_at = datetime.utcnow()
                embedded += 1
            db.commit()
        except Exception as e:
            for ch in batch:
                ch.embedding_status = "failed"
            db.commit()
            errors += len(batch)
            print(f"  임베딩 오류 (batch {i}): {e}")

    return {"embedded": embedded, "errors": errors, "remaining": len(pending) - embedded - errors}


def run_full_ingest(verbose: bool = True) -> dict:
    db = SessionLocal()
    stats = {}
    try:
        if verbose:
            print("=== 1. 청크 생성 (DB에 텍스트 저장) ===")
        stats["parties"] = ingest_parties(db)
        if verbose: print(f"  거래처: {stats['parties']}")
        stats["products"] = ingest_products(db)
        if verbose: print(f"  제품: {stats['products']}")
        stats["contracts"] = ingest_contracts(db)
        if verbose: print(f"  계약: {stats['contracts']}")
        stats["documents"] = ingest_documents(db)
        if verbose: print(f"  서류: {stats['documents']}")
        stats["loans"] = ingest_loans(db)
        if verbose: print(f"  차입금: {stats['loans']}")
        stats["sale_monthly"] = ingest_sale_monthly(db)
        if verbose: print(f"  매출 월요약: {stats['sale_monthly']}")
        stats["purchase_monthly"] = ingest_purchase_monthly(db)
        if verbose: print(f"  매입 월요약: {stats['purchase_monthly']}")

        if verbose:
            print("\n=== 2. ChromaDB 벡터화 (변경된 것만) ===")
        emb_stats = embed_pending(db)
        stats.update(emb_stats)
        if verbose:
            print(f"  임베딩 신규: {emb_stats['embedded']}, 오류: {emb_stats['errors']}")
    finally:
        db.close()
    return stats


if __name__ == "__main__":
    import time
    t0 = time.time()
    res = run_full_ingest()
    print(f"\n총 소요: {time.time() - t0:.1f}초")
    print(f"전체: {res}")

    from rag import store_stats
    print(f"벡터 DB 현황: {store_stats()}")
