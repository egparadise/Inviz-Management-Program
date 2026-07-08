# -*- coding: utf-8 -*-
"""시스템 컨설턴트 모드용 컨텍스트 빌더

상단 AI 검색바에서 "🛠 시스템" 모드를 선택하면, /chat/stream이 이 모듈을 호출해
다음을 LLM에 주입한다:

  1) 프로젝트 개요 (.claude/CLAUDE.md 의 앞부분)
  2) 모듈 맵 — routers/*.py, templates/*/*.html 파일 목록
  3) DB 통계 — 주요 테이블 행수·최신 갱신일
  4) 운영 상태 — sync_run / integrity_check / self_dev 최근 결과
  5) RAG 상태 — knowledge_chunk 수, FAISS 인덱스 크기
  6) 최근 활동 — 최근 챗 질문 5건 (사용자가 무엇에 관심 있는지)
"""
from pathlib import Path
from datetime import date, timedelta
from sqlalchemy import select, func, desc
from sqlalchemy.orm import Session

PROJECT_ROOT = Path(__file__).parent.parent
WEB_APP = Path(__file__).parent


def _safe(fn, default="(N/A)"):
    try:
        return fn()
    except Exception as e:
        return f"(오류: {type(e).__name__})"


def _read_claude_md(max_chars: int = 3500) -> str:
    p = PROJECT_ROOT / ".claude" / "CLAUDE.md"
    if not p.exists():
        return "(.claude/CLAUDE.md 없음)"
    try:
        text = p.read_text(encoding="utf-8")
        # 너무 길면 앞부분만
        if len(text) > max_chars:
            return text[:max_chars] + f"\n...(이하 {len(text)-max_chars}자 생략)"
        return text
    except Exception as e:
        return f"(읽기 실패: {e})"


def _module_map() -> str:
    """routers/, templates/ 파일 목록 — 간략"""
    lines = []
    routers_dir = WEB_APP / "routers"
    if routers_dir.exists():
        py_files = sorted(p.name for p in routers_dir.glob("*.py") if not p.name.startswith("_"))
        lines.append("• routers/ — " + ", ".join(py_files))
    tpl_dir = WEB_APP / "templates"
    if tpl_dir.exists():
        sub = sorted(p.name for p in tpl_dir.iterdir() if p.is_dir() and not p.name.startswith("_"))
        lines.append("• templates/ — " + ", ".join(sub))
    py_files = sorted(p.name for p in WEB_APP.glob("*.py")
                      if p.name not in ("main.py", "models.py") and not p.name.startswith("_"))
    if py_files:
        lines.append("• core/ — " + ", ".join(py_files[:20]))
    return "\n".join(lines)


def _db_stats(db: Session) -> str:
    """주요 테이블 행수 · 최신 거래일"""
    from models import (Sale, Purchase, Party, Product, Employee, Payroll,
                        Expense, Contract, Document, LoanMaster, Loan,
                        Rental, KnowledgeChunk, ChatHistory)
    items = []

    def cnt(model, label):
        try:
            n = db.scalar(select(func.count()).select_from(model)) or 0
            items.append(f"{label} {n:,}")
        except Exception:
            items.append(f"{label} ?")

    cnt(Sale, "매출")
    cnt(Purchase, "매입")
    cnt(Payroll, "급여")
    cnt(Expense, "비용")
    cnt(Rental, "임차료")
    cnt(Contract, "계약")
    cnt(Document, "문서")
    cnt(Party, "거래처")
    cnt(Product, "제품")
    cnt(Employee, "직원")
    cnt(KnowledgeChunk, "RAG청크")
    cnt(ChatHistory, "챗이력")

    # 최신 거래일
    try:
        last_sale = db.scalar(select(func.max(Sale.txn_date)))
        last_pur = db.scalar(select(func.max(Purchase.txn_date)))
        items.append(f"최신매출일 {last_sale}")
        items.append(f"최신매입일 {last_pur}")
    except Exception:
        pass
    return " · ".join(items)


def _intent_status(db: Session) -> str:
    """사용자 의도 원장 — sync가 몇 번 재삽입을 막았는지 AI가 인식"""
    try:
        from user_intent import stats
        s = stats(db)
        parts = [f"기록 {s['total_entries']}건",
                 f"활성 차단 {s['active_blocks']}건",
                 f"누적 방어 {s['total_preventions']}회"]
        if s['by_action']:
            parts.append("액션: " + ", ".join(f"{k}={v}" for k, v in s['by_action'].items()))
        return " · ".join(parts)
    except Exception as e:
        return f"(원장 조회 실패: {e})"


def _dedup_status(db: Session) -> str:
    """매출/매입 중복 현황 — AI가 데이터 위생을 진단할 때 활용"""
    try:
        from dedup import overall_stats
        s = overall_stats(db)
        lines = []
        for key, label in [("sale", "매출"), ("purchase", "매입")]:
            d = s[key]
            tag = "⚠ 주의" if d["dup_rate_pct"] >= 1 else "정상"
            lines.append(f"{label}: 전체 {d['total_rows']:,}행 / 중복 그룹 {d['dup_groups']} / "
                         f"중복초과 {d['dup_excess_rows']}건 ({d['dup_rate_pct']}%) [{tag}]")
        return "\n".join(lines)
    except Exception as e:
        return f"(중복 진단 실패: {e})"


def _ops_status(db: Session) -> str:
    """sync_run, integrity_check, self_dev 최근 상태"""
    lines = []
    # sync_run
    try:
        from models import SyncRun
        last = db.execute(select(SyncRun).order_by(desc(SyncRun.id)).limit(1)).scalar_one_or_none()
        if last:
            lines.append(f"마지막 sync: {last.started_at} · {last.status} · "
                         f"{getattr(last,'files_changed',0)}건 처리")
        else:
            lines.append("sync 이력 없음")
    except Exception:
        pass
    # integrity_check
    try:
        from models import IntegrityCheck
        last = db.execute(select(IntegrityCheck).order_by(desc(IntegrityCheck.id)).limit(1)).scalar_one_or_none()
        if last:
            lines.append(f"무결성: {last.checked_at} · {last.severity or 'ok'} · "
                         f"{(last.message or '')[:80]}")
    except Exception:
        pass
    # unmapped_file_review queue
    try:
        from models import UnmappedFileReview
        pending = db.scalar(select(func.count()).select_from(UnmappedFileReview)
                            .where(UnmappedFileReview.status == "pending")) or 0
        if pending:
            lines.append(f"미매핑 파일 검토 큐: {pending}건")
    except Exception:
        pass
    return "\n".join(lines) if lines else "(운영 이력 없음)"


def _rag_status() -> str:
    try:
        from rag import store_stats
        s = store_stats()
        if not s:
            return "RAG 인덱스: (비활성)"
        parts = [f"임베딩 {s.get('embedding_model','?')}",
                 f"청크 {s.get('chunks', s.get('count','?'))}"]
        if "kb_chunks" in s:
            parts.append(f"KB {s['kb_chunks']} · CONV {s.get('conv_chunks',0)}")
        return "RAG: " + " · ".join(parts)
    except Exception as e:
        return f"RAG: (확인 불가 — {e})"


def _recent_questions(db: Session, n: int = 5) -> str:
    try:
        from models import ChatHistory
        rows = db.execute(
            select(ChatHistory.query, ChatHistory.intent, ChatHistory.user_feedback)
            .order_by(desc(ChatHistory.id)).limit(n)
        ).all()
        if not rows:
            return "(최근 질문 없음)"
        return "\n".join(
            f"- [{r[1] or 'unknown'}{('/' + r[2]) if r[2] else ''}] {r[0][:120]}"
            for r in rows)
    except Exception:
        return "(이력 조회 실패)"


def _settings_snapshot(db: Session) -> str:
    """주요 설정값"""
    try:
        from settings_store import get as sget
        keys = ["ai_provider", "ai_default_model", "ai_default_mode",
                "app_title", "ui_font_scale", "host_bind", "https_enabled"]
        items = []
        for k in keys:
            v = sget(k, "")
            if v:
                items.append(f"{k}={v}")
        return " · ".join(items) if items else "(설정 없음)"
    except Exception:
        return "(설정 조회 실패)"


def build_system_context(db: Session, *, max_chars: int = 6000) -> str:
    """LLM에 주입할 시스템 컨텍스트 문자열 — 시스템 모드 전용."""
    today = date.today().isoformat()
    sections = [
        f"# 인비즈 경영관리 시스템 — 현재 상태 ({today})\n",
        "## 1) 프로젝트 개요",
        _safe(lambda: _read_claude_md(2800)),
        "\n## 2) 시스템 모듈 맵",
        _safe(_module_map),
        "\n## 3) DB 통계 (주요 테이블)",
        _safe(lambda: _db_stats(db)),
        "\n## 4) 운영 상태",
        _safe(lambda: _ops_status(db)),
        "\n## 4-2) 중복 감시 (Dedup Guardian)",
        _safe(lambda: _dedup_status(db)),
        "\n## 4-3) 사용자 의도 보존 (Intent Ledger)",
        _safe(lambda: _intent_status(db)),
        "\n## 5) RAG 인덱스",
        _safe(_rag_status),
        "\n## 6) 현재 설정",
        _safe(lambda: _settings_snapshot(db)),
        "\n## 7) 최근 사용자 질문",
        _safe(lambda: _recent_questions(db, 5)),
    ]
    text = "\n".join(sections)
    if len(text) > max_chars:
        return text[:max_chars] + f"\n...(이하 {len(text)-max_chars}자 생략)"
    return text


SYSTEM_MODE_PROMPT = """당신은 한국 의료 IT 회사 ㈜인비즈의 경영관리 시스템(FastAPI+SQLite+Ollama RAG)의 시스템 컨설턴트입니다.

아래 [시스템 상태] 와 [참고 자료(RAG)]를 모두 활용하여, 사용자의 질문에 한국어로 답하세요. 응답 시 다음을 지키세요:

1. **시스템 구조/기능 질문**(예: "이 프로그램은 어떻게 구성?", "RAG는 어떤 모델?"):
   → 시스템 상태를 근거로 모듈·파일경로·테이블명을 명시하여 답합니다.

2. **데이터 질문**(예: "매출이 왜 떨어졌나?", "어떤 거래처가 위험?"):
   → 참고 자료(RAG)와 DB 통계를 함께 인용합니다. 숫자는 콤마+단위(원/건/명)로.

3. **개선 제안 요청**(예: "이 기능 개선해줘", "느린 부분 찾아줘"):
   → 다음 형식으로 답하세요:
      • **What** — 무엇을 개선할지 (1줄)
      • **Why** — 왜 (관찰된 문제·KPI 영향)
      • **How** — 구체적 파일경로·라우터·테이블·함수까지. 예: `routers/sales.py의 list_sales() 함수에 product_code 인덱스 추가`
      • **영향도** — Low/Med/High + 예상 작업시간
   → 한번에 1~3가지 제안만, 중요도순.

4. **새 기능 요청**(예: "원가관리 메뉴 추가"):
   → 모델·라우터·템플릿·메뉴 4-스택 변경계획을 제시.

5. **답을 모르거나 정보 부족** → "시스템 상태에 없습니다"라고 솔직히 답하세요. 추측하지 마세요.

답변은 핵심을 맨 앞 1~3문장으로 명확히 제시한 뒤, 상세 근거·계획을 이어 작성하세요.
"""
