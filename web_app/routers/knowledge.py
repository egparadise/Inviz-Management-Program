# -*- coding: utf-8 -*-
"""지식베이스 관리 라우터 — 인덱싱·통계·재학습"""
from datetime import datetime, timedelta
from fastapi import APIRouter, Request, Depends, Form, BackgroundTasks
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy import select, func
from sqlalchemy.orm import Session

from database import get_db, SessionLocal
from helpers import templates
from models import KnowledgeChunk, ChatHistory

router = APIRouter()


@router.get("", response_class=HTMLResponse)
def knowledge_dashboard(request: Request, db: Session = Depends(get_db)):
    from rag import store_stats

    # 청크 통계
    total = db.scalar(select(func.count()).select_from(KnowledgeChunk)) or 0
    by_type = db.execute(
        select(KnowledgeChunk.source_type, func.count(),
               func.coalesce(func.sum(KnowledgeChunk.token_count), 0))
        .group_by(KnowledgeChunk.source_type)
        .order_by(func.count().desc())
    ).all()
    by_status = db.execute(
        select(KnowledgeChunk.embedding_status, func.count())
        .group_by(KnowledgeChunk.embedding_status)
    ).all()

    # 최근 변경/미임베딩 청크
    pending = db.execute(
        select(KnowledgeChunk).where(KnowledgeChunk.embedding_status == "pending").limit(20)
    ).scalars().all()

    # 챗 이력 통계
    chat_total = db.scalar(select(func.count()).select_from(ChatHistory)) or 0
    chat_good = db.scalar(select(func.count()).where(ChatHistory.user_feedback == "good").select_from(ChatHistory)) or 0
    chat_bad = db.scalar(select(func.count()).where(ChatHistory.user_feedback == "bad").select_from(ChatHistory)) or 0
    indexed_convs = db.scalar(select(func.count()).where(ChatHistory.is_indexed == "Y").select_from(ChatHistory)) or 0

    # 토큰 사용량 (최근 30일)
    cutoff = datetime.utcnow() - timedelta(days=30)
    tok_input = db.scalar(select(func.coalesce(func.sum(ChatHistory.tokens_input), 0)).where(
        ChatHistory.created_at >= cutoff
    ).select_from(ChatHistory)) or 0
    tok_output = db.scalar(select(func.coalesce(func.sum(ChatHistory.tokens_output), 0)).where(
        ChatHistory.created_at >= cutoff
    ).select_from(ChatHistory)) or 0

    # 가장 자주 검색되는 청크 (top 10)
    top_retrieved = db.execute(
        select(KnowledgeChunk).where(KnowledgeChunk.retrieval_count > 0)
        .order_by(KnowledgeChunk.retrieval_count.desc()).limit(10)
    ).scalars().all()

    # 최근 챗 이력 (최근 20건)
    recent_chats = db.execute(
        select(ChatHistory).order_by(ChatHistory.id.desc()).limit(20)
    ).scalars().all()

    vstore = store_stats()

    return templates.TemplateResponse("knowledge/dashboard.html", {
        "request": request,
        "total_chunks": total,
        "by_type": by_type, "by_status": by_status,
        "pending_chunks": pending,
        "chat_total": chat_total, "chat_good": chat_good, "chat_bad": chat_bad,
        "indexed_convs": indexed_convs,
        "tokens_input_30d": int(tok_input), "tokens_output_30d": int(tok_output),
        "top_retrieved": top_retrieved,
        "recent_chats": recent_chats,
        "vstore": vstore,
    })


@router.post("/reindex")
def reindex(bg: BackgroundTasks):
    """모든 데이터 재인제스트 (백그라운드)"""
    bg.add_task(_reindex_bg)
    return RedirectResponse("/knowledge?started=1", status_code=303)


def _reindex_bg():
    from rag_ingest import run_full_ingest
    try:
        run_full_ingest(verbose=False)
    except Exception as e:
        print(f"[reindex] error: {e}")


@router.post("/embed-pending")
def embed_pending_btn(bg: BackgroundTasks):
    """pending 상태인 청크만 벡터화"""
    bg.add_task(_embed_pending_bg)
    return RedirectResponse("/knowledge?embedded=1", status_code=303)


def _embed_pending_bg():
    from rag_ingest import embed_pending
    db = SessionLocal()
    try:
        embed_pending(db)
    finally:
        db.close()


@router.post("/test-rag", response_class=HTMLResponse)
def test_rag(request: Request, query: str = Form(...), k: int = Form(5)):
    """RAG 검색 테스트 (인덱스 품질 확인용)"""
    from rag import retrieve_hybrid
    hits = retrieve_hybrid(query.strip(), k_kb=k, k_conv=2, min_score=0.0)
    return templates.TemplateResponse("knowledge/test_result.html", {
        "request": request, "query": query, "hits": hits,
    })
