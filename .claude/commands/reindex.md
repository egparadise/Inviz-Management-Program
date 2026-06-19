---
description: RAG 벡터 DB 재인덱싱 — 변경된 청크 또는 전체
---

인비즈 RAG 시스템의 벡터 인덱스를 갱신합니다.

옵션: $1
- `pending` (기본) — embedding_status='pending'인 청크만 처리
- `full` — 전체 재인덱싱 (모든 청크 다시 임베딩)
- `clean` — vector_store 폴더 삭제 후 전체 재구축 (가장 깨끗)

실행:
```bash
cd "C:\Users\scpar\OneDrive - Inviz\5.Inviz_Corporation\14.경영정보\00.경영관리마스터\web_app"

# pending만
python -c "from rag_ingest import embed_pending; from database import SessionLocal; print(embed_pending(SessionLocal()))"

# 전체
python rag_ingest.py

# clean
rm -rf "$LOCALAPPDATA/Inviz/vector_store"
python -c "from database import SessionLocal; from sqlalchemy import update; from models import KnowledgeChunk; db=SessionLocal(); db.execute(update(KnowledgeChunk).values(embedding_status='pending')); db.commit()"
python rag_ingest.py
```

완료 후 검색 테스트:
```python
from rag import retrieve_hybrid
hits = retrieve_hybrid("테스트 질의", k_kb=3)
for h in hits:
    print(h['score'], h['metadata'].get('title'))
```

보고:
- 청크 수 (전후)
- 임베딩 소요 시간
- 임베딩 모델 (bge-m3, 1024차원)
- 검색 품질 샘플 (top 3 점수)
