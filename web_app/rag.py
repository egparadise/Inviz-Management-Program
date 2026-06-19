# -*- coding: utf-8 -*-
"""RAG 인프라 — FAISS (Windows + Python 3.14 호환)

벡터 DB: FAISS (Facebook AI Similarity Search)
- 임베디드, 디스크 persist (save_local/load_local)
- 인메모리 검색 (수 ms), HNSW 인덱스 없이 flat L2
- ChromaDB 1.5.x의 Rust 엔진 윈도우 호환성 이슈 우회
"""
import hashlib
import json
import os
import pickle
from pathlib import Path
from typing import Optional
from datetime import datetime

import tiktoken
from langchain_ollama import OllamaEmbeddings
from langchain_community.vectorstores import FAISS
from langchain_text_splitters import RecursiveCharacterTextSplitter
from langchain_core.documents import Document

ROOT = Path(__file__).parent
# FAISS C++ 라이브러리가 한글 경로를 지원하지 않아 ASCII 경로 사용
# OneDrive 동기화 대상 아님 (재생성 가능 인덱스)
_LOCALAPPDATA = os.environ.get("LOCALAPPDATA") or str(Path.home() / "AppData" / "Local")
# Docker/서버 배포 시 INVIZ_VECTOR_PATH 로 영속 볼륨 경로 지정 (ASCII 경로 필수)
VECTOR_DIR = Path(os.environ.get("INVIZ_VECTOR_PATH") or (Path(_LOCALAPPDATA) / "Inviz" / "vector_store"))
VECTOR_DIR.mkdir(parents=True, exist_ok=True)

EMBEDDING_MODEL = "bge-m3:latest"  # 다국어 (한국어 우수), 1024d
KB_INDEX_PATH = VECTOR_DIR / "kb_faiss"     # 지식
CONV_INDEX_PATH = VECTOR_DIR / "conv_faiss" # 학습된 대화

_tokenizer = None


def get_tokenizer():
    global _tokenizer
    if _tokenizer is None:
        _tokenizer = tiktoken.get_encoding("cl100k_base")
    return _tokenizer


def count_tokens(text: str) -> int:
    if not text:
        return 0
    return len(get_tokenizer().encode(text))


_embeddings = None


def get_embeddings():
    global _embeddings
    if _embeddings is None:
        _embeddings = OllamaEmbeddings(model=EMBEDDING_MODEL)
    return _embeddings


# ============ FAISS Vector Store ============
_kb_store = None
_conv_store = None


def get_kb_store() -> FAISS:
    global _kb_store
    if _kb_store is None:
        emb = get_embeddings()
        if (KB_INDEX_PATH / "index.faiss").exists():
            _kb_store = FAISS.load_local(
                str(KB_INDEX_PATH), emb, allow_dangerous_deserialization=True,
            )
        else:
            # 빈 인덱스로 초기화
            dummy = Document(page_content="__init__", metadata={"_init": True})
            _kb_store = FAISS.from_documents([dummy], emb)
    return _kb_store


def get_conv_store() -> FAISS:
    global _conv_store
    if _conv_store is None:
        emb = get_embeddings()
        if (CONV_INDEX_PATH / "index.faiss").exists():
            _conv_store = FAISS.load_local(
                str(CONV_INDEX_PATH), emb, allow_dangerous_deserialization=True,
            )
        else:
            dummy = Document(page_content="__init__", metadata={"_init": True})
            _conv_store = FAISS.from_documents([dummy], emb)
    return _conv_store


def save_kb_store():
    store = get_kb_store()
    KB_INDEX_PATH.mkdir(exist_ok=True)
    store.save_local(str(KB_INDEX_PATH))


def save_conv_store():
    store = get_conv_store()
    CONV_INDEX_PATH.mkdir(exist_ok=True)
    store.save_local(str(CONV_INDEX_PATH))


def reset_kb_store():
    """KB 인덱스 초기화 (재인덱싱 전 호출)"""
    global _kb_store
    _kb_store = None
    import shutil
    if KB_INDEX_PATH.exists():
        shutil.rmtree(KB_INDEX_PATH)


# ============ 청크 분할 ============
def get_splitter():
    return RecursiveCharacterTextSplitter(
        chunk_size=800,
        chunk_overlap=120,
        separators=["\n\n", "\n", ". ", "。", " ", ""],
        length_function=count_tokens,
    )


def content_hash(text: str) -> str:
    return hashlib.sha256((text or "").encode("utf-8")).hexdigest()


# ============ 인덱싱 ============
def index_chunks_bulk(items: list[dict]) -> int:
    """대량 인덱싱. items = [{id, content, metadata}, ...]"""
    if not items:
        return 0
    store = get_kb_store()
    docs = []
    ids = []
    for it in items:
        meta = dict(it["metadata"])
        meta["chunk_id"] = it["id"]
        docs.append(Document(page_content=it["content"], metadata=meta))
        ids.append(f"kb-{it['id']}")
    # __init__ 더미 문서가 있으면 삭제 (첫 인덱싱 시)
    try:
        dummy_id = None
        for k, doc in store.docstore._dict.items():
            if doc.metadata.get("_init"):
                dummy_id = k
                break
        if dummy_id:
            store.delete([dummy_id])
    except Exception:
        pass
    # 기존 동일 ID 청크 삭제
    try:
        existing_ids = []
        for k, doc in list(store.docstore._dict.items()):
            cid = doc.metadata.get("chunk_id")
            if cid is not None and cid in [it["id"] for it in items]:
                existing_ids.append(k)
        if existing_ids:
            store.delete(existing_ids)
    except Exception:
        pass

    store.add_documents(documents=docs)
    save_kb_store()
    return len(items)


def index_conversation(history_id: int, query: str, response: str, intent: str, kind: str) -> str:
    """좋은 평가 받은 대화를 학습 컬렉션에 추가"""
    store = get_conv_store()
    content = f"질문: {query}\n답변: {response}"
    metadata = {
        "history_id": history_id, "intent": intent or "",
        "kind": kind or "", "type": "conversation",
    }
    # __init__ 더미 제거
    try:
        for k, doc in list(store.docstore._dict.items()):
            if doc.metadata.get("_init"):
                store.delete([k])
                break
    except Exception:
        pass
    store.add_documents(
        documents=[Document(page_content=content, metadata=metadata)],
    )
    save_conv_store()
    return f"conv-{history_id}"


# ============ 검색 ============
def retrieve_relevant(query: str, k: int = 5, kind: str = "kb") -> list[dict]:
    store = get_kb_store() if kind == "kb" else get_conv_store()
    try:
        # FAISS는 L2 거리 — relevance score로 변환 (1 - normalized distance)
        results = store.similarity_search_with_score(query, k=k)
    except Exception as e:
        return [{"error": str(e)}]
    out = []
    for doc, distance in results:
        # __init__ 더미 제외
        if doc.metadata.get("_init"):
            continue
        # L2 distance → similarity score (대략 0~1, 작을수록 가까움)
        # nomic-embed-text는 normalized이므로 0~2 range
        score = max(0.0, 1.0 - float(distance) / 2.0)
        out.append({
            "content": doc.page_content,
            "metadata": doc.metadata,
            "score": score,
            "distance": float(distance),
        })
    return out


def retrieve_hybrid(query: str, k_kb: int = 4, k_conv: int = 2,
                    min_score: float = 0.3) -> list[dict]:
    kb_hits = retrieve_relevant(query, k=k_kb, kind="kb")
    conv_hits = retrieve_relevant(query, k=k_conv, kind="conv")
    kb_hits = [h for h in kb_hits if "error" not in h]
    conv_hits = [h for h in conv_hits if "error" not in h]
    for h in kb_hits:
        h["source"] = "knowledge"
    for h in conv_hits:
        h["source"] = "conversation"
    combined = sorted(kb_hits + conv_hits, key=lambda x: -x.get("score", 0))
    return [h for h in combined if h.get("score", 0) >= min_score]


# ============ 컨텍스트 빌드 ============
def build_context(hits: list[dict], max_tokens: int = 2000) -> tuple[str, list[str], int]:
    parts = []
    sources = []
    total_tok = 0
    for i, h in enumerate(hits):
        meta = h.get("metadata", {})
        title = meta.get("title") or meta.get("source_id") or f"{h.get('source', '')}"
        text = h["content"]
        tk = count_tokens(text)
        if total_tok + tk > max_tokens:
            break
        prefix = f"[자료 {i + 1} | {title}] "
        parts.append(prefix + text)
        sources.append(title)
        total_tok += tk + count_tokens(prefix)
    return "\n\n".join(parts), sources, total_tok


# ============ 통계 ============
def store_stats() -> dict:
    out = {}
    try:
        kb = get_kb_store()
        kb_count = sum(1 for k, d in kb.docstore._dict.items() if not d.metadata.get("_init"))
        out["kb_count"] = kb_count
    except Exception as e:
        out["kb_count"] = -1
        out["kb_error"] = str(e)[:200]
    try:
        conv = get_conv_store()
        conv_count = sum(1 for k, d in conv.docstore._dict.items() if not d.metadata.get("_init"))
        out["conv_count"] = conv_count
    except Exception as e:
        out["conv_count"] = -1
    return out


if __name__ == "__main__":
    print("=== FAISS RAG 인프라 셀프 테스트 ===")
    print(f"Vector dir: {VECTOR_DIR}")
    emb = get_embeddings()
    v = emb.embed_query("테스트")
    print(f"임베딩 차원: {len(v)}")
    print(f"토큰 ('안녕하세요 인비즈입니다'): {count_tokens('안녕하세요 인비즈입니다')}")
    print(f"Store stats: {store_stats()}")
