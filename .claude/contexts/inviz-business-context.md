---
name: inviz-business-context
description: 인비즈 회사·제품·KPI·명명 규약을 한 페이지로 압축한 LLM 컨텍스트 카드. 챗·도메인 추정·영수증 OCR에 system 메시지로 주입
type: context
length-tokens: ~800
inject-targets:
  - chat_engine.rag_answer
  - llm_provider.analyze_receipt_image
  - routers/ai_classify._llm_classify (보조)
---

# 인비즈 비즈니스 컨텍스트

## 회사
- **법인명**: ㈜인비즈 (Inviz Corporation)
- **업종**: 한국 의료 영상 IT
- **대표**: 박성철 (사번 E0004)
- **사업자번호**: 409-86-28572
- **본사**: 광주광역시 남구 송암로 60, 7층 700호 (광주CGI센터)

## 주요 제품
| 제품코드 | 이름 | 설명 |
|---|---|---|
| P001 | Cloud Care Life | 원격판독 솔루션 (정기료 매출) |
| P002 | Saintview PACS | 의료영상저장전송 시스템 |
| P003 | Vision Maker | 영상 워크스테이션 |
| P004 | Ai Echo Care | AI 보조 진단 (초음파) |
| P005 | AI CXR/MMG | AI 보조 진단 (흉부/유방) |

## 거래처 규모
- 병원·의원 ~786개
- 대리점·공급사 ~200개
- 합계 984개 (dim_party)

## 연간 KPI 기준 (2024년)
- **매출**: 24.2억 원 (CLAUDE.md 공식 수치)
- **매입**: 13.8억 원
- **차익**: 10.4억 원
- 거래처 TOP — 써밋영상의원, 광주일곡병원, 고흥종합병원, 화순전남대학교병원

## 명명 규약
| 항목 | 패턴 | 예시 |
|---|---|---|
| 거래처 | `C0001` ~ `C9999` | C0123 (써밋영상의원) |
| 제품 | `P001` ~ `P999` | P001 (Cloud Care Life) |
| 직원 | 사번 그대로 (`IV_*` 옛 사번 / `E0001~` 신 사번) | E0004 (박성철) |
| 계약 | `K-{시트}-{행번호}` / `K-W-{auto}` (웹 입력) | K-30-12 |
| 차입금 | `LM-{auto}` | LM-001 |
| 매출 ID | `S-{출처}-{seq}` | S-20FACT-1234 |
| 매입 ID | `P-{출처}-{seq}` | P-21FACT-567 |
| 지출 ID | `EXP-W-*` (수기) / `EXP-CSV-*` (업로드) / `EXP-OCR-*` (영수증) | |

## 데이터 무결성 원칙
- **웹 입력 보존**: `source_file = 'web_app'` 데이터는 sync에서 절대 삭제 안 됨
- **위험 변동 차단**: 행수 ±50%↑ / 합계 ±70%↑ → critical → 자동 롤백
- **백업**: 매 sync 전 자동 스냅샷, 30일 보관

## 기술 스택 (시스템 관점)
- FastAPI 0.136 + SQLAlchemy 2.0 + SQLite (`app.db`, 7.4MB)
- Jinja2 + HTMX + Tailwind CDN + Chart.js
- Ollama 로컬 LLM (llama3.1 8B, gemma4 31B, bge-m3 임베딩)
- RAG: LangChain + FAISS 1024d (`%LOCALAPPDATA%\Inviz\vector_store`)
- 인증: itsdangerous 세션 쿠키 (공동 비번 `Inviz0601!`)

## LLM 사용 가이드
- **돈/날짜**: 한국 단위(원, 억, YYYY-MM-DD) 사용
- **회사명 약식 표기**: "㈜인비즈" / "인비즈" — "Inviz Inc."는 영문 외부 보고서에만
- **음수 금액**: 회계 표기로 △1,234 또는 (1,234) 둘 다 허용
- **모름**: 추측 금지. `null` 또는 "확인 필요"로 응답

## 관련 자산
- [[inviz-domain-suggest]] — 이 컨텍스트를 함께 주입하면 도메인 추정 정확도↑
- [[inviz-receipt-vision]] — 영수증 OCR도 이 컨텍스트로 거래처명·결제수단 정규화
