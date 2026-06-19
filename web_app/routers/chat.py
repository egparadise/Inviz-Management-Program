# -*- coding: utf-8 -*-
"""Chat 라우터 — Ollama + RAG + 스트리밍 + 자가 학습"""
import json
import time
from datetime import datetime
from fastapi import APIRouter, Request, Form, Depends, BackgroundTasks
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse, StreamingResponse
from sqlalchemy import select, func
from sqlalchemy.orm import Session

from database import get_db, SessionLocal
from helpers import templates
from models import ChatHistory, KnowledgeChunk
from chat_engine import process_query, list_models, ollama_available, DEFAULT_MODEL

router = APIRouter()


@router.get("/status")
def chat_status(db: Session = Depends(get_db)):
    from rag import store_stats
    avail = ollama_available()
    models = list_models() if avail else []
    # AI 공급자(클라우드 포함) 준비 상태
    try:
        import llm_provider
        ai_ready, _ai_msg = llm_provider.provider_ready()
        ai_label = llm_provider.active_label()
    except Exception:
        ai_ready, ai_label = avail, f"Ollama · {DEFAULT_MODEL}"
    return {
        "ollama_available": avail,
        # 챗 사용 가능 여부 — 클라우드 공급자면 Ollama 없이도 True
        "ai_available": ai_ready,
        "ai_label": ai_label,
        "default_model": DEFAULT_MODEL,
        "models": models,
        "rag_stats": store_stats() if avail else {},
        "chat_history_count": db.scalar(select(func.count()).select_from(ChatHistory)) or 0,
        "knowledge_chunks": db.scalar(select(func.count()).select_from(KnowledgeChunk)) or 0,
    }


@router.post("/query")
def chat_query(
    db: Session = Depends(get_db),
    query: str = Form(...),
    model: str = Form(DEFAULT_MODEL),
    ai_summary: str = Form("false"),
    use_rag: str = Form("false"),
):
    """비-스트리밍 단발 응답"""
    if not query.strip():
        return JSONResponse({"error": "질문이 비어 있습니다."}, status_code=400)
    t0 = time.time()
    use_ai = ai_summary.lower() in ("true", "1", "yes", "on")
    use_rag_bool = use_rag.lower() in ("true", "1", "yes", "on")
    try:
        res = process_query(query.strip(), db, model=model,
                            ai_summary=use_ai, use_rag=use_rag_bool)
        elapsed_ms = int((time.time() - t0) * 1000)
        res["elapsed_ms"] = elapsed_ms
        res["used_ai_summary"] = use_ai
        res["used_rag"] = use_rag_bool

        try:
            rag_meta = res.get("rag") or {}
            history = ChatHistory(
                query=query.strip()[:2000],
                intent=res.get("intent", {}).get("intent"),
                response_summary=(res.get("summary") or "")[:4000],
                response_kind=res.get("result", {}).get("kind") if res.get("result") else None,
                rag_used="Y" if use_rag_bool else "N",
                rag_chunks=rag_meta.get("chunks_used"),
                fast_match="Y" if res.get("intent", {}).get("_fast") else "N",
                model_used=model if not res.get("intent", {}).get("_fast") else "fast_match",
                tokens_input=rag_meta.get("tokens_input"),
                tokens_output=rag_meta.get("tokens_output"),
                elapsed_ms=elapsed_ms,
            )
            db.add(history); db.commit(); db.refresh(history)
            res["history_id"] = history.id
        except Exception as e:
            print(f"[chat] history save error: {e}")
        return JSONResponse(res)
    except RuntimeError as e:
        return JSONResponse({"error": str(e)}, status_code=503)
    except Exception as e:
        return JSONResponse({"error": f"{type(e).__name__}: {e}"}, status_code=500)


@router.post("/stream")
def chat_stream(
    query: str = Form(...),
    model: str = Form(DEFAULT_MODEL),
    use_rag: str = Form("true"),
):
    """SSE 스트리밍 응답:
    - 1) 즉시 의도 분류 + DB 결과 전송 (event: result)
    - 2) RAG 검색 결과 전송 (event: sources)
    - 3) LLM 토큰을 받는 대로 전송 (event: token)
    - 4) 완료 (event: done)
    """
    from chat_engine import (
        fast_intent_match, extract_intent, dispatch, ollama_chat_stream,
        template_summary,
    )
    from rag import retrieve_hybrid, build_context, count_tokens
    import re

    def gen():
        t0 = time.time()
        db = SessionLocal()
        try:
            q = query.strip()
            # Mojibake 복구
            if q and not re.search(r"[가-힣]", q):
                try:
                    rec = q.encode("cp1252").decode("utf-8")
                    if re.search(r"[가-힣]", rec):
                        q = rec
                except Exception:
                    pass

            search_only = use_rag.lower() == "search_only"
            yield _sse("status", {"stage": "intent", "msg": "의도 분석 중..."})

            # 의도 분류 (fast first)
            fast = fast_intent_match(q)
            if fast:
                intent = fast
            elif search_only:
                # 검색만 모드 — LLM 호출 안 하고 unknown으로
                intent = {"intent": "unknown", "_fast": False}
            else:
                yield _sse("status", {"stage": "intent_llm", "msg": f"의도 분류 LLM 호출 ({model.split(':')[0]})..."})
                intent = extract_intent(q, model=model)

            # DB 결과
            yield _sse("status", {"stage": "db", "msg": "DB 검색..."})
            result = dispatch(intent, db)
            if result:
                yield _sse("result", {
                    "intent": intent, "result": result,
                    "summary": template_summary(intent, result),
                })

            use_rag_b = search_only or use_rag.lower() in ("true", "1", "yes", "on")
            rag_hits = []
            answer_text = ""
            ctx_tokens = 0

            if use_rag_b or result is None:
                yield _sse("status", {"stage": "rag", "msg": "벡터 DB에서 관련 자료 검색..."})
                hits = retrieve_hybrid(q, k_kb=6, k_conv=2, min_score=0.3)
                rag_hits = hits
                yield _sse("sources", {
                    "chunks_used": len(hits),
                    "hits": [{
                        "title": h.get("metadata", {}).get("title"),
                        "page_url": h.get("metadata", {}).get("page_url"),
                        "score": h.get("score"),
                        "source": h.get("source"),
                        "source_type": h.get("metadata", {}).get("source_type"),
                        "preview": h["content"][:140] + ("..." if len(h["content"]) > 140 else ""),
                    } for h in hits[:6]],
                })

                if hits and not search_only:
                    context, _, ctx_tokens = build_context(hits, max_tokens=1500)
                    yield _sse("status", {"stage": "llm", "msg": f"LLM 답변 생성 중 ({model.split(':')[0]})..."})

                    system = """당신은 한국 의료 IT 회사 "인비즈(Inviz)"의 경영관리 비서입니다.
[참고 자료]만 근거로 한국어로 답하세요. 자료에 없으면 "자료에 없습니다"라고 답하세요.
핵심 답변을 맨 앞에 1~3문장으로 명확히 제시하세요. 상세 수치·근거는 화면의 접이식 '데이터 결과'·'참고 자료'에 따로 표시되므로, 답변만으로도 충분히 이해되도록 작성하세요.
숫자는 콤마와 단위(원, 건, 명)로 명확히 표기하세요.
분기는 3개월 단위입니다: 1분기=1~3월, 2분기=4~6월, 3분기=7~9월, 4분기=10~12월. 예) '2026년 1분기'는 2026-01-01 ~ 2026-03-31 입니다.
마지막에 [자료 N]으로 인용하세요."""
                    user = f"[참고 자료]\n{context}\n\n[질문]\n{q}"

                    try:
                        import llm_provider
                        msgs = [{"role": "system", "content": system},
                                {"role": "user", "content": user}]
                        if llm_provider.is_cloud():
                            # 클라우드 API — 단발 호출 후 전체 답변 전송 (빠름)
                            full = llm_provider.chat_complete(msgs, temperature=0.2, max_tokens=400)
                            answer_text += full
                            yield _sse("token", {"text": full})
                        else:
                            for tok in ollama_chat_stream(msgs, model=model, temperature=0.2, num_predict=350):
                                answer_text += tok
                                yield _sse("token", {"text": tok})
                    except Exception as e:
                        yield _sse("error", {"message": f"LLM 호출 실패: {e}"})

            # 이력 저장
            elapsed_ms = int((time.time() - t0) * 1000)
            history_id = None
            try:
                tokens_in = count_tokens(q) + ctx_tokens
                history = ChatHistory(
                    query=q[:2000],
                    intent=intent.get("intent") if intent else None,
                    response_summary=(answer_text or (result and template_summary(intent, result)) or "")[:4000],
                    response_kind=(result or {}).get("kind"),
                    rag_used="Y" if use_rag_b else "N",
                    rag_chunks=len(rag_hits),
                    fast_match="Y" if (intent and intent.get("_fast")) else "N",
                    model_used=model,
                    tokens_input=tokens_in,
                    tokens_output=count_tokens(answer_text),
                    elapsed_ms=elapsed_ms,
                )
                db.add(history); db.commit(); db.refresh(history)
                history_id = history.id
            except Exception as e:
                print(f"[stream] history save error: {e}")

            yield _sse("done", {
                "elapsed_ms": elapsed_ms,
                "history_id": history_id,
                "tokens_input": count_tokens(q) + ctx_tokens,
                "tokens_output": count_tokens(answer_text),
                "model": model,
                "intent": intent.get("intent") if intent else None,
                "_fast": intent.get("_fast") if intent else None,
            })
        except Exception as e:
            yield _sse("error", {"message": f"{type(e).__name__}: {e}"})
        finally:
            db.close()

    return StreamingResponse(gen(), media_type="text/event-stream")


def _sse(event: str, data: dict) -> bytes:
    return f"event: {event}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n".encode("utf-8")


@router.post("/feedback")
def chat_feedback(
    bg: BackgroundTasks,
    db: Session = Depends(get_db),
    history_id: int = Form(...),
    rating: str = Form(...),
    note: str = Form(""),
):
    h = db.get(ChatHistory, history_id)
    if not h:
        return JSONResponse({"error": "이력 없음"}, status_code=404)
    h.user_feedback = rating
    h.feedback_note = note or None
    db.commit()
    if rating == "good" and h.is_indexed != "Y":
        bg.add_task(_index_conversation_bg, history_id)
    return {"ok": True, "rating": rating}


def _index_conversation_bg(history_id: int):
    from rag import index_conversation
    db = SessionLocal()
    try:
        h = db.get(ChatHistory, history_id)
        if not h or h.is_indexed == "Y":
            return
        try:
            index_conversation(
                history_id=h.id, query=h.query,
                response=h.response_summary or "",
                intent=h.intent or "", kind=h.response_kind or "",
            )
            h.is_indexed = "Y"
            db.commit()
        except Exception as e:
            print(f"[chat] conv indexing error: {e}")
    finally:
        db.close()


@router.get("/history")
def chat_history_list(db: Session = Depends(get_db), limit: int = 30):
    rows = db.execute(
        select(ChatHistory).order_by(ChatHistory.id.desc()).limit(limit)
    ).scalars().all()
    return [{
        "id": r.id, "query": r.query[:200],
        "intent": r.intent, "response_kind": r.response_kind,
        "elapsed_ms": r.elapsed_ms,
        "rag_used": r.rag_used, "fast_match": r.fast_match,
        "tokens_input": r.tokens_input, "tokens_output": r.tokens_output,
        "user_feedback": r.user_feedback,
        "created_at": r.created_at.isoformat() if r.created_at else None,
    } for r in rows]
