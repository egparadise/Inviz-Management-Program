# 03. RAG 시스템 (Retrieval-Augmented Generation)

## 목적

LLM이 인비즈 회사 데이터를 정확히 답하도록, 질문 시점에 관련 문서 청크를 자동으로 찾아 컨텍스트로 제공.

## 아키텍처

```
사용자 질문 (자유 한국어)
    ↓
[1] fast_intent_match (키워드 매칭)
    │   1ms — 명확하면 종결
    ↓ (모호 시)
[2] 임베딩 (bge-m3, 1024d)
    │   ~50ms
    ↓
[3] FAISS 유사도 검색 (top-K)
    │   ~5ms
    ↓
[4] 컨텍스트 빌드 (max 1500 토큰)
    │   tiktoken cl100k_base 토큰 카운트
    ↓
[5] LLM 호출 (Ollama llama3.1)
    │   첫 토큰 ~13초, 완료 ~30초
    ↓
[6] 토큰별 SSE 스트리밍 → 사용자
    ↓
[7] 응답 + 출처 + 페이지 링크 + 👍/👎 버튼
```

## 임베딩 모델: bge-m3

| 속성 | 값 |
|---|---|
| 모델 ID | `bge-m3:latest` (Ollama) |
| 차원 | 1024 |
| 언어 | 다국어 (한국어 우수) |
| 크기 | 1.2GB |
| 호출 방식 | `OllamaEmbeddings(model='bge-m3:latest')` |
| 호출 시간 | ~50ms per embed (CPU) |

이전 시도:
- `nomic-embed-text` (768d) — 영어 위주, 한국어 변별력 부족
- `bge-m3` 채택 후 한국어 검색 점수 0.4 → 0.7+ 향상

## 벡터 DB: FAISS

| 속성 | 값 |
|---|---|
| 라이브러리 | `faiss-cpu` 1.14 |
| 인덱스 타입 | Flat L2 (전체 비교, 정확) |
| 저장 위치 | `%LOCALAPPDATA%\Inviz\vector_store\` |
| Persist | `save_local()` / `load_local()` |
| 컬렉션 2개 | `kb_faiss` (지식), `conv_faiss` (학습 대화) |

### 왜 FAISS인가 (다른 후보 대비)

| 후보 | 시도 결과 |
|---|---|
| ChromaDB 1.5 | Windows + Python 3.14에서 HNSW 인덱스 깨짐 (`Error loading hnsw index`) |
| ChromaDB 0.5 | chroma-hnswlib·tokenizers Python 3.14 빌드 실패 |
| **FAISS** | Pre-built wheel, 안정 동작 ✓ |
| Qdrant | 외부 서버 필요, 오버킬 |
| sqlite-vss | Windows 빌드 어려움 |

### 한글 경로 회피
FAISS C++ 라이브러리는 한글 경로 미지원 ("Illegal byte sequence"). 해결:
```python
VECTOR_DIR = Path(os.environ.get("LOCALAPPDATA")) / "Inviz" / "vector_store"
```
OneDrive 동기화 안 함 (재생성 가능한 인덱스).

## 청크 인덱싱

### 청크 1,321개 분포

| source_type | 수 | 예시 텍스트 |
|---|---:|---|
| party | 786 | "거래처 써밋영상의원 (C0058). 구분 병원. 누적 매출 2,021,813,283원..." |
| contract | 299 | "계약 X. 거래처: Y. 시작 ~ 만료 ~. 잔여 ~일. 미수금 ~원..." |
| document | 85 | "서류 납세증명서. 종류 납세증명. 발급일 ~. 만료일 ~..." |
| sale_monthly | 64 | "2025년 6월 매출 요약. 총 102건, 공급가액 189,537,284원..." |
| purchase_monthly | 52 | (동일 패턴) |
| loan_master | 25 | "차입금 기업은행. 최초 3억, 현재잔액 ~..." |
| product | 10 | "제품 Vision Maker. AI 영상. 누적 매출 ~..." |

### 청크 생성 원칙
- **자연어 한국어 텍스트** — LLM이 이해하기 좋음
- **숫자는 콤마와 단위** — "2,021,813,283원"
- **메타데이터 포함** — title, page_url, source_type
- **300~800 토큰 청크 크기** — 컨텍스트 효율

## 검색 로직 (rag.py)

```python
def retrieve_hybrid(query, k_kb=4, k_conv=2, min_score=0.3):
    kb_hits = retrieve_relevant(query, k=k_kb, kind="kb")
    conv_hits = retrieve_relevant(query, k=k_conv, kind="conv")
    # 점수 정렬 + min_score 필터
    return sorted(kb_hits + conv_hits, key=lambda x: -x["score"])
```

**Score 계산** (FAISS L2 거리 → 유사도):
```python
score = max(0.0, 1.0 - distance / 2.0)
```
bge-m3는 normalized 임베딩이므로 거리 0~2 범위.

## 컨텍스트 빌드

```python
def build_context(hits, max_tokens=1500):
    parts = []
    total_tok = 0
    for i, h in enumerate(hits):
        text = h["content"]
        tk = count_tokens(text)
        if total_tok + tk > max_tokens: break
        parts.append(f"[자료 {i+1} | {h['metadata']['title']}] " + text)
        total_tok += tk
    return "\n\n".join(parts), sources, total_tok
```

## LLM 프롬프트

```
[system]
당신은 한국 의료 IT 회사 인비즈(Inviz)의 경영관리 비서입니다.
[참고 자료]만 근거로 한국어로 답하세요. 자료에 없으면 "자료에 없습니다".
숫자는 콤마와 단위(원/건/명)로 명확히. 2~5문장 간결.
마지막에 [자료 N]으로 인용.

[user]
[참고 자료]
{context}

[질문]
{query}
```

## 자가 학습 (Continuous Learning)

1. 사용자 질문 → RAG 답변 → `chat_history`에 저장
2. 사용자가 👍 클릭 → `user_feedback='good'`
3. 백그라운드로 `index_conversation(history_id, query, response)`
4. `conv_faiss` 컬렉션에 임베딩 추가
5. 다음 유사 질문 시 `retrieve_hybrid`가 학습된 Q&A를 검색 결과에 포함

## 응답 시간 프로파일

| 모드 | 시간 |
|---|---:|
| Fast match (키워드 명확) | 5ms |
| 검색만 (LLM 없이) | 500ms |
| RAG + LLM (llama3.1 8B) | 30초 (첫 토큰 13초) |
| RAG + LLM (GLM 4.7) | 60초+ (한국어 정확도↑) |

`keep_alive=30m` Ollama 옵션으로 두 번째 호출부터 모델 로딩 시간 제거.

## 성능 튜닝

- `chunk_size=800, chunk_overlap=120` — 한국어 적합
- `k_kb=6, k_conv=2` — 균형
- `min_score=0.3` — 무관한 청크 필터
- `num_predict=350` — LLM 응답 토큰 상한

## RAG 디버깅

`/knowledge` 페이지의 "🧪 검색만" 모드로:
- 검색 점수 0.7 이상 → 인덱싱 양호
- 0.5~0.7 → 청크 텍스트 개선 필요
- 0.3 이하 → 임베딩 모델 또는 청크 자체 부적절

`Top retrieved` 통계로 자주 매칭되는 청크 모니터링.
