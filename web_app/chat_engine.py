# -*- coding: utf-8 -*-
"""LLM 챗 검색 엔진 — Ollama 연동

플로우:
  사용자 질문 → Ollama (의도+엔티티 JSON 추출) → DB 검색 함수 분기 →
  결과 카드 + 페이지 링크 + LLM 한 문장 요약

지원 의도:
  search_sale, search_purchase, search_party, search_contract,
  search_document, search_loan, search_payroll, search_employee, kpi
"""
import os
import json
import re
import urllib.request
import urllib.error
from datetime import date, datetime, timedelta
from typing import Optional
from sqlalchemy import select, func, or_
from sqlalchemy.orm import Session

from models import (Sale, Purchase, Party, Product, Contract, LoanMaster,
                    Loan, Document, Employee, Payroll, Expense, Rental)

# Ollama 접속 — Docker 배포 시 OLLAMA_HOST=http://ollama:11434 로 주입
OLLAMA_HOST = os.environ.get("OLLAMA_HOST", "http://localhost:11434")
DEFAULT_MODEL = "llama3.1:latest"


# ---------------- Ollama 연동 ----------------
def ollama_available() -> bool:
    try:
        req = urllib.request.Request(f"{OLLAMA_HOST}/api/tags")
        with urllib.request.urlopen(req, timeout=2) as r:
            return r.status == 200
    except Exception:
        return False


def list_models() -> list[dict]:
    try:
        req = urllib.request.Request(f"{OLLAMA_HOST}/api/tags")
        with urllib.request.urlopen(req, timeout=3) as r:
            data = json.loads(r.read())
        models = []
        for m in data.get("models", []):
            models.append({
                "name": m.get("name"),
                "size_gb": round(m.get("size", 0) / (1024**3), 1),
                "param": m.get("details", {}).get("parameter_size", "?"),
            })
        return models
    except Exception as e:
        return []


def ollama_chat_stream(messages: list[dict], model: str = DEFAULT_MODEL,
                       temperature: float = 0.2, num_predict: int = 400):
    """Ollama /api/chat 스트리밍 호출 → 토큰별 yield"""
    payload = {
        "model": model, "messages": messages, "stream": True,
        "keep_alive": "30m",
        "options": {"temperature": temperature, "num_predict": num_predict, "num_ctx": 4096},
    }
    req = urllib.request.Request(
        f"{OLLAMA_HOST}/api/chat",
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=180) as r:
        for line in r:
            if not line:
                continue
            try:
                obj = json.loads(line.decode("utf-8"))
                content = obj.get("message", {}).get("content", "")
                if content:
                    yield content
                if obj.get("done"):
                    break
            except Exception:
                continue


def ollama_chat(messages: list[dict], model: str = DEFAULT_MODEL,
                temperature: float = 0.1, json_mode: bool = False,
                num_predict: int = 512) -> str:
    """Ollama /api/chat 호출 → assistant 메시지 텍스트 반환

    keep_alive='30m' — 모델을 30분간 메모리에 유지 → 다음 호출부터 빨라짐
    num_predict — 생성 토큰 상한 (응답 시간 단축용)
    """
    payload = {
        "model": model,
        "messages": messages,
        "stream": False,
        "keep_alive": "30m",
        "options": {
            "temperature": temperature,
            "num_predict": num_predict,
            "num_ctx": 4096,
        },
    }
    if json_mode:
        payload["format"] = "json"

    req = urllib.request.Request(
        f"{OLLAMA_HOST}/api/chat",
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=120) as r:
            data = json.loads(r.read())
            return data.get("message", {}).get("content", "")
    except urllib.error.URLError as e:
        raise RuntimeError(f"Ollama 연결 실패: {e}")


# ---------------- 의도 추출 ----------------
INTENT_SYSTEM_PROMPT = """You convert Korean queries into JSON for a Korean medical-IT company management system.
Output JSON only, no explanation.

Schema:
{
  "intent": "search_sale" | "search_purchase" | "search_party" | "search_contract" | "search_document" | "search_loan" | "search_payroll" | "search_employee" | "kpi" | "unknown",
  "from_date": "YYYY-MM-DD" or null,
  "to_date": "YYYY-MM-DD" or null,
  "year": number or null,
  "month": number or null,
  "party_name": "company/hospital Korean name" or null,
  "product": "product name" or null,
  "doc_type": "Korean doc type (사업자등록증, 인증서, 특허, 납세증명 etc.)" or null,
  "expiring_within_days": number or null
}

Intent mapping (Korean keywords):
- 매출 → search_sale
- 매입 → search_purchase
- 거래처, 병원, 회사명 정보 → search_party
- 계약 → search_contract
- 인증서, 특허, 공증, 납세증명, 사업자등록증, 문서, 서류 → search_document
- 차입금, 대출, 은행 → search_loan
- 급여, 인건비 → search_payroll
- 직원, 사원 → search_employee
- KPI, 현황, 요약, 전체 → kpi
- else → unknown

Date parsing rules:
- "이번 달" = current month (from = first day, to = last day)
- "지난 달" = last month
- A quarter (분기) is ALWAYS 3 months: 1분기=Jan-Mar, 2분기=Apr-Jun, 3분기=Jul-Sep, 4분기=Oct-Dec.
- "이번 분기" = current quarter (3 months).
- "N분기" (e.g. "1분기") → set from_date/to_date to that 3-month range. If a year precedes it ("2026년 1분기"), use that year; else current year. Example: "2026년 1분기" → from_date=2026-01-01, to_date=2026-03-31. Do NOT also set year/month when a quarter range is used.
- "최근 한 달" / "지난 30일" = today minus 30 days to today
- "2024년" → year=2024
- "X월" → month=X
- "X일 이내 만료" → expiring_within_days=X
"""


def fast_intent_match(query: str) -> Optional[dict]:
    """LLM 우회 — 명확한 키워드 패턴이 매칭되면 즉시 의도 반환.
    매칭 안 되면 None → LLM으로 fallback.
    """
    import re as _re
    q = query.strip().lower()
    today = date.today()

    # 폴더 분석 명령 — 경로 + 분석/적용 키워드 감지
    folder_re = _re.search(r'([a-z]:\\[^"\'<>|?*\n]+|/[a-z]/[^"\'<>|?*\n]+)', query, _re.I)
    if folder_re and any(kw in query for kw in ("분석", "적용", "동기화", "스캔", "읽어", "처리")):
        return {"intent": "analyze_folder", "folder_path": folder_re.group(1).strip().strip("'\"`")}

    # 기간 키워드
    period = {}
    if "이번 달" in query or "이번달" in query or "이달" in query or "당월" in query:
        first = today.replace(day=1)
        # 다음 달 1일 - 1일 = 이번 달 말일
        if today.month == 12:
            last = date(today.year, 12, 31)
        else:
            last = date(today.year, today.month + 1, 1) - timedelta(days=1)
        period = {"from_date": first.isoformat(), "to_date": last.isoformat()}
    elif "지난 달" in query or "지난달" in query or "전월" in query:
        if today.month == 1:
            first = date(today.year - 1, 12, 1); last = date(today.year - 1, 12, 31)
        else:
            first = date(today.year, today.month - 1, 1)
            last = today.replace(day=1) - timedelta(days=1)
        period = {"from_date": first.isoformat(), "to_date": last.isoformat()}
    elif "이번 분기" in query or "이번분기" in query or "당분기" in query:
        q_num = (today.month - 1) // 3
        first = date(today.year, q_num * 3 + 1, 1)
        last_month = q_num * 3 + 3
        if last_month == 12:
            last = date(today.year, 12, 31)
        else:
            last = date(today.year, last_month + 1, 1) - timedelta(days=1)
        period = {"from_date": first.isoformat(), "to_date": last.isoformat()}
    elif "최근 한 달" in query or "지난 30일" in query or "최근 30일" in query:
        period = {"from_date": (today - timedelta(days=30)).isoformat(),
                  "to_date": today.isoformat()}
    elif "올해" in query or "당해" in query or "금년" in query or "ytd" in q:
        period = {"year": today.year}

    # 연도/월 추출
    m = re.search(r"(\d{4})\s*년", query)
    if m and "year" not in period and "from_date" not in period:
        period["year"] = int(m.group(1))
    m = re.search(r"(?<![\d])(\d{1,2})\s*월(?!\s*이?내)", query)
    if m and "month" not in period and "from_date" not in period:
        period["month"] = int(m.group(1))

    # 분기(1~4분기) — 분기는 3개월 단위: 1분기=1~3월, 2분기=4~6월, 3분기=7~9월, 4분기=10~12월
    # 예) "2026년 1분기" → 2026-01-01 ~ 2026-03-31. "4/4분기" 같은 표기도 인식.
    mq = re.search(r"(?:제\s*)?([1-4])\s*(?:/\s*4)?\s*분기", query)
    if mq:
        qn = int(mq.group(1))
        qy = period.get("year") or today.year
        start_m = (qn - 1) * 3 + 1
        end_m = qn * 3
        first = date(qy, start_m, 1)
        if end_m == 12:
            last = date(qy, 12, 31)
        else:
            last = date(qy, end_m + 1, 1) - timedelta(days=1)
        period["from_date"] = first.isoformat()
        period["to_date"] = last.isoformat()
        period.pop("year", None)   # 분기는 from/to로만 필터 (연도 단독 조건 제거)
        period.pop("month", None)

    # N일 이내 만료
    m = re.search(r"(\d{1,3})\s*일\s*(?:이?내|안에|이전)", query)
    expiring = int(m.group(1)) if m else None

    # 도메인 키워드
    base = {"_fast": True, "from_date": None, "to_date": None, "year": None, "month": None,
            "party_name": None, "product": None, "doc_type": None, "expiring_within_days": None}
    base.update(period)
    if expiring:
        base["expiring_within_days"] = expiring

    # 재무제표 / 손익계산서 / P&L (매출/매입 키워드보다 우선)
    if re.search(r"재무제표|손익계산서|손익\s*계산서|손익현황|p\s*[&/]?\s*l|영업\s*이익|당기\s*순이익", query, re.IGNORECASE):
        base["intent"] = "financial_statement"
        return base

    # 매출/매입 (정확한 키워드)
    if re.search(r"매출|판매|영업.*수익", query) and not re.search(r"매입|매출원가", query):
        base["intent"] = "search_sale"
        return base
    if re.search(r"매입|구매|원가", query):
        base["intent"] = "search_purchase"
        return base
    # 문서/인증서/특허/공증
    if re.search(r"인증서|특허|공증|사업자등록증|납세증명|부가세증명|증명원|문서|서류", query):
        base["intent"] = "search_document"
        if "사업자등록증" in query: base["doc_type"] = "사업자등록증"
        elif "인증서" in query: base["doc_type"] = "인증서"
        elif "특허" in query: base["doc_type"] = "특허"
        elif "공증" in query: base["doc_type"] = "공증"
        elif "납세" in query: base["doc_type"] = "납세증명"
        elif "부가세" in query: base["doc_type"] = "부가세증명"
        return base
    # 차입금
    if re.search(r"차입금|대출|융자|은행", query):
        base["intent"] = "search_loan"
        return base
    # 급여
    if re.search(r"급여|인건비|월급", query):
        base["intent"] = "search_payroll"
        return base
    # 계약
    if re.search(r"계약(?!금)|계약서|약정", query):
        base["intent"] = "search_contract"
        return base
    # KPI
    if re.search(r"\b(kpi|현황|요약|전체|종합)\b", q) or "kpi" in q or "현황" in query:
        base["intent"] = "kpi"
        return base
    # 직원
    if re.search(r"직원|사원|인원", query) and not re.search(r"급여|인건비", query):
        base["intent"] = "search_employee"
        return base

    return None  # LLM으로 fallback


def extract_intent(query: str, model: str = DEFAULT_MODEL) -> dict:
    today = date.today().isoformat()
    user_prompt = f"Today: {today}\nKorean query: {query}"
    messages = [
        {"role": "system", "content": INTENT_SYSTEM_PROMPT},
        {"role": "user", "content": user_prompt},
    ]
    # 설정된 AI 공급자(클라우드/Ollama) 사용
    try:
        import llm_provider
        raw = llm_provider.chat_complete(messages, temperature=0.1, json_mode=True, max_tokens=256)
    except Exception:
        raw = ollama_chat(messages, model=model, json_mode=True, num_predict=256)
    try:
        return json.loads(raw)
    except Exception:
        m = re.search(r"\{[\s\S]*\}", raw)
        if m:
            try:
                return json.loads(m.group(0))
            except Exception:
                pass
        return {"intent": "unknown", "explanation": "의도 분석 실패", "_raw": raw[:200]}


# ---------------- DB 검색 디스패치 ----------------
def _parse_d(s):
    if not s or s == "null":
        return None
    try:
        return datetime.strptime(s, "%Y-%m-%d").date()
    except Exception:
        return None


# 거짓 거래처(엑셀 합계 행 등) 제외 목록
EXCLUDE_PARTY_NAMES = ["합 계", "합계", "소 계", "소계", "총 계", "총계", "TOTAL", "Total", "total"]


def search_sale(intent: dict, db: Session) -> dict:
    fd = _parse_d(intent.get("from_date"))
    td = _parse_d(intent.get("to_date"))
    year = intent.get("year")
    month = intent.get("month")
    party = intent.get("party_name")
    product = intent.get("product")
    conds = []
    if fd: conds.append(Sale.txn_date >= fd)
    if td: conds.append(Sale.txn_date <= td)
    if year: conds.append(Sale.year == int(year))
    if month: conds.append(Sale.month == int(month))
    if party: conds.append(Sale.party_name.contains(party))
    if product:
        conds.append(or_(Sale.product_name.contains(product), Sale.item_raw.contains(product)))

    cnt = db.scalar(select(func.count()).select_from(Sale).where(*conds)) or 0
    sum_supply = db.scalar(select(func.coalesce(func.sum(Sale.supply), 0)).where(*conds)) or 0
    sum_total = db.scalar(select(func.coalesce(func.sum(Sale.total), 0)).where(*conds)) or 0
    top_parties = db.execute(
        select(Sale.party_name, func.sum(Sale.supply))
        .where(*conds, Sale.party_name.is_not(None), ~Sale.party_name.in_(EXCLUDE_PARTY_NAMES))
        .group_by(Sale.party_name)
        .order_by(func.sum(Sale.supply).desc()).limit(5)
    ).all()
    top_products = db.execute(
        select(Sale.product_name, func.sum(Sale.supply))
        .where(*conds, Sale.product_name.is_not(None))
        .group_by(Sale.product_name)
        .order_by(func.sum(Sale.supply).desc()).limit(5)
    ).all()
    # 페이지 링크 QS
    qs = []
    if fd: qs.append(f"from_date={fd}")
    if td: qs.append(f"to_date={td}")
    if year: qs.append(f"year={year}")
    if month: qs.append(f"month={month}")
    if party: qs.append(f"party={party}")
    page_url = "/sales" + (f"?{'&'.join(qs)}" if qs else "")
    return {
        "kind": "sale", "count": cnt,
        "sum_supply": float(sum_supply), "sum_total": float(sum_total),
        "top_parties": [(r[0], float(r[1] or 0)) for r in top_parties],
        "top_products": [(r[0], float(r[1] or 0)) for r in top_products],
        "page_url": page_url, "page_label": "매출 페이지에서 자세히 보기",
    }


def search_purchase(intent: dict, db: Session) -> dict:
    fd = _parse_d(intent.get("from_date"))
    td = _parse_d(intent.get("to_date"))
    year = intent.get("year"); month = intent.get("month")
    party = intent.get("party_name")
    conds = []
    if fd: conds.append(Purchase.txn_date >= fd)
    if td: conds.append(Purchase.txn_date <= td)
    if year: conds.append(Purchase.year == int(year))
    if month: conds.append(Purchase.month == int(month))
    if party: conds.append(Purchase.party_name.contains(party))
    cnt = db.scalar(select(func.count()).select_from(Purchase).where(*conds)) or 0
    sum_supply = db.scalar(select(func.coalesce(func.sum(Purchase.supply), 0)).where(*conds)) or 0
    top_parties = db.execute(
        select(Purchase.party_name, func.sum(Purchase.supply))
        .where(*conds, Purchase.party_name.is_not(None), ~Purchase.party_name.in_(EXCLUDE_PARTY_NAMES))
        .group_by(Purchase.party_name)
        .order_by(func.sum(Purchase.supply).desc()).limit(5)
    ).all()
    qs = []
    if fd: qs.append(f"from_date={fd}")
    if td: qs.append(f"to_date={td}")
    if year: qs.append(f"year={year}")
    if month: qs.append(f"month={month}")
    if party: qs.append(f"party={party}")
    return {
        "kind": "purchase", "count": cnt,
        "sum_supply": float(sum_supply),
        "top_parties": [(r[0], float(r[1] or 0)) for r in top_parties],
        "page_url": "/purchases" + (f"?{'&'.join(qs)}" if qs else ""),
        "page_label": "매입 페이지에서 자세히 보기",
    }


def search_party(intent: dict, db: Session) -> dict:
    name = intent.get("party_name") or ""
    parties = db.execute(
        select(Party).where(or_(Party.name.contains(name), Party.code == name)).limit(10)
    ).scalars().all()
    items = []
    for p in parties:
        sale_total = db.scalar(
            select(func.coalesce(func.sum(Sale.supply), 0)).where(Sale.party_code == p.code)
        ) or 0
        purch_total = db.scalar(
            select(func.coalesce(func.sum(Purchase.supply), 0)).where(Purchase.party_code == p.code)
        ) or 0
        items.append({
            "code": p.code, "name": p.name, "category": p.category,
            "active": p.active, "biz_no": p.biz_no,
            "sale_total": float(sale_total), "purchase_total": float(purch_total),
        })
    return {
        "kind": "party", "items": items,
        "page_url": f"/parties?q={name}",
        "page_label": "거래처 페이지에서 자세히 보기",
    }


def search_contract(intent: dict, db: Session) -> dict:
    party = intent.get("party_name")
    expiring = intent.get("expiring_within_days")
    conds = []
    if party:
        conds.append(or_(Contract.party_name.contains(party), Contract.name.contains(party)))
    if expiring:
        cutoff = date.today() + timedelta(days=int(expiring))
        conds.append(Contract.end_date.is_not(None))
        conds.append(Contract.end_date <= cutoff)
        conds.append(Contract.end_date >= date.today())
    cnt = db.scalar(select(func.count()).select_from(Contract).where(*conds)) or 0
    sum_amt = db.scalar(select(func.coalesce(func.sum(Contract.contract_amount), 0)).where(*conds)) or 0
    sum_unpaid = db.scalar(select(func.coalesce(func.sum(Contract.unpaid_amount), 0)).where(*conds)) or 0
    rows = db.execute(
        select(Contract).where(*conds)
        .order_by(Contract.end_date.asc().nullslast()).limit(10)
    ).scalars().all()
    today = date.today()
    items = []
    for c in rows:
        items.append({
            "name": c.name, "party": c.party_name, "kind": c.kind,
            "end_date": c.end_date.isoformat() if c.end_date else None,
            "remain_days": (c.end_date - today).days if c.end_date else None,
            "amount": float(c.contract_amount or 0),
            "unpaid": float(c.unpaid_amount or 0),
            "status": c.status,
        })
    qs = []
    if party: qs.append(f"q={party}")
    return {
        "kind": "contract", "count": cnt, "sum_amount": float(sum_amt), "sum_unpaid": float(sum_unpaid),
        "items": items, "page_url": "/contracts" + (f"?{'&'.join(qs)}" if qs else ""),
        "page_label": "계약 페이지에서 자세히 보기",
    }


def search_document(intent: dict, db: Session) -> dict:
    doc_type = intent.get("doc_type")
    expiring = intent.get("expiring_within_days")
    conds = []
    if doc_type:
        conds.append(Document.doc_type.contains(doc_type))
    if expiring:
        cutoff = date.today() + timedelta(days=int(expiring))
        conds.append(Document.expiry_date.is_not(None))
        conds.append(Document.expiry_date <= cutoff)
        conds.append(Document.expiry_date >= date.today())
    cnt = db.scalar(select(func.count()).select_from(Document).where(*conds)) or 0
    rows = db.execute(
        select(Document).where(*conds).order_by(Document.expiry_date.asc().nullslast()).limit(15)
    ).scalars().all()
    today = date.today()
    items = []
    for d in rows:
        items.append({
            "id": d.id, "name": d.name, "doc_type": d.doc_type,
            "issue_date": d.issue_date.isoformat() if d.issue_date else None,
            "expiry_date": d.expiry_date.isoformat() if d.expiry_date else None,
            "remain_days": (d.expiry_date - today).days if d.expiry_date else None,
            "has_file": bool(d.file_path),
            "view_url": f"/documents/{d.id}/view" if d.file_path else None,
        })
    qs = []
    if doc_type: qs.append(f"doc_type={doc_type}")
    if expiring: qs.append(f"expiring_within={expiring}")
    return {
        "kind": "document", "count": cnt, "items": items,
        "page_url": "/documents" + (f"?{'&'.join(qs)}" if qs else ""),
        "page_label": "서류·인증 페이지에서 자세히 보기",
    }


def search_loan(intent: dict, db: Session) -> dict:
    rows = db.execute(
        select(LoanMaster).order_by(LoanMaster.current_balance.desc().nullslast()).limit(15)
    ).scalars().all()
    items = [{
        "institution": r.institution, "kind": r.kind, "term": r.term,
        "initial": float(r.initial_amount or 0),
        "balance": float(r.current_balance or 0),
        "rate": r.interest_rate,
        "end_date": r.end_date.isoformat() if r.end_date else None,
        "status": r.status,
    } for r in rows]
    total_bal = sum(i["balance"] for i in items)
    return {
        "kind": "loan", "count": len(items), "total_balance": total_bal,
        "items": items, "page_url": "/loans",
        "page_label": "차입금 페이지에서 자세히 보기",
    }


def search_payroll(intent: dict, db: Session) -> dict:
    year = intent.get("year"); month = intent.get("month")
    conds = []
    if year: conds.append(Payroll.year == int(year))
    if month: conds.append(Payroll.month == int(month))
    cnt = db.scalar(select(func.count()).select_from(Payroll).where(*conds)) or 0
    sum_gross = db.scalar(select(func.coalesce(func.sum(Payroll.gross_pay), 0)).where(*conds)) or 0
    by_dept = db.execute(
        select(Payroll.department, func.count(), func.sum(Payroll.gross_pay))
        .where(*conds).group_by(Payroll.department)
        .order_by(func.sum(Payroll.gross_pay).desc())
    ).all()
    qs = []
    if year: qs.append(f"year={year}")
    if month: qs.append(f"month={month}")
    return {
        "kind": "payroll", "count": cnt, "sum_gross": float(sum_gross),
        "by_dept": [(r[0] or "(미지정)", r[1], float(r[2] or 0)) for r in by_dept],
        "page_url": "/payroll" + (f"?{'&'.join(qs)}" if qs else ""),
        "page_label": "급여 페이지에서 자세히 보기",
    }


def search_employee(intent: dict, db: Session) -> dict:
    name = intent.get("party_name")  # 사람 이름도 party_name에 올 수 있음
    conds = []
    if name:
        conds.append(or_(Employee.name.contains(name), Employee.code == name))
    cnt = db.scalar(select(func.count()).select_from(Employee).where(*conds)) or 0
    rows = db.execute(select(Employee).where(*conds).limit(15)).scalars().all()
    items = [{
        "code": e.code, "name": e.name, "department": e.department,
        "hire_date": e.hire_date.isoformat() if e.hire_date else None,
        "resign_date": e.resign_date.isoformat() if e.resign_date else None,
        "active": e.active,
    } for e in rows]
    return {
        "kind": "employee", "count": cnt, "items": items,
        "page_url": f"/employees?q={name or ''}",
        "page_label": "직원 페이지에서 자세히 보기",
    }


def kpi_overview(intent: dict, db: Session) -> dict:
    today = date.today()
    year = intent.get("year") or today.year

    def sumcol(model, col, **filt):
        st = select(func.coalesce(func.sum(col), 0))
        for k, v in filt.items():
            st = st.where(getattr(model, k) == v)
        return float(db.scalar(st) or 0)

    sales_y = sumcol(Sale, Sale.supply, year=year)
    purch_y = sumcol(Purchase, Purchase.supply, year=year)
    payroll_y = sumcol(Payroll, Payroll.gross_pay, year=year)
    loan_balance = float(db.scalar(select(func.coalesce(func.sum(LoanMaster.current_balance), 0))) or 0)
    expiring_docs = db.scalar(select(func.count()).where(
        Document.expiry_date.is_not(None),
        Document.expiry_date >= today,
        Document.expiry_date <= today + timedelta(days=30),
    ).select_from(Document)) or 0
    active_contracts = db.scalar(select(func.count()).where(Contract.status == "진행").select_from(Contract)) or 0
    return {
        "kind": "kpi", "year": year,
        "sales": sales_y, "purchases": purch_y,
        "gross_margin": sales_y - purch_y,
        "payroll": payroll_y,
        "loan_balance": loan_balance,
        "expiring_docs_30": expiring_docs,
        "active_contracts": active_contracts,
        "page_url": "/", "page_label": "대시보드에서 자세히 보기",
    }


def financial_statement(intent: dict, db: Session) -> dict:
    """간이 손익계산서(P/L) — 한국 중소기업 기준
    매출액 → 매출원가(매입) → 매출총이익 → 판관비(급여+비용+임대료) → 영업이익 → 추정 순이익
    """
    fd = _parse_d(intent.get("from_date"))
    td = _parse_d(intent.get("to_date"))
    year = intent.get("year")
    month = intent.get("month")

    # 기간 라벨
    if fd and td:
        period_label = f"{fd.isoformat()} ~ {td.isoformat()}"
    elif year and month:
        period_label = f"{year}년 {month}월"
    elif year:
        period_label = f"{year}년"
    else:
        # 기본: 올해 (YTD)
        year = date.today().year
        period_label = f"{year}년 YTD"

    # 공통 WHERE
    def _conds_for_date(date_col, year_col=None, month_col=None):
        c = []
        if fd: c.append(date_col >= fd)
        if td: c.append(date_col <= td)
        if year and year_col is not None: c.append(year_col == int(year))
        if month and month_col is not None: c.append(month_col == int(month))
        return c

    # 1. 매출액
    s_conds = _conds_for_date(Sale.txn_date, Sale.year, Sale.month)
    sales_amt = float(db.scalar(select(func.coalesce(func.sum(Sale.supply), 0)).where(*s_conds)) or 0)
    sales_cnt = db.scalar(select(func.count()).select_from(Sale).where(*s_conds)) or 0

    # 2. 매출원가 (매입 합계)
    p_conds = _conds_for_date(Purchase.txn_date, Purchase.year, Purchase.month)
    cogs_amt = float(db.scalar(select(func.coalesce(func.sum(Purchase.supply), 0)).where(*p_conds)) or 0)
    cogs_cnt = db.scalar(select(func.count()).select_from(Purchase).where(*p_conds)) or 0

    # 3. 매출총이익
    gross_profit = sales_amt - cogs_amt
    gross_margin = (gross_profit / sales_amt * 100) if sales_amt else 0

    # 4. 판매비와 관리비
    # 4a. 급여 (period 형식 YYYY-MM, year/month로 필터)
    pay_conds = []
    if fd: pay_conds.append(Payroll.period >= fd.strftime("%Y-%m"))
    if td: pay_conds.append(Payroll.period <= td.strftime("%Y-%m"))
    if year: pay_conds.append(Payroll.year == int(year))
    if month: pay_conds.append(Payroll.month == int(month))
    payroll_amt = float(db.scalar(select(func.coalesce(func.sum(Payroll.gross_pay), 0)).where(*pay_conds)) or 0)
    employer_ins = float(db.scalar(select(func.coalesce(func.sum(Payroll.employer_insurance), 0)).where(*pay_conds)) or 0)

    # 4b. 일반 비용
    e_conds = _conds_for_date(Expense.use_date, Expense.year, Expense.month)
    expense_amt = float(db.scalar(select(func.coalesce(func.sum(Expense.amount), 0)).where(*e_conds)) or 0)

    # 4c. 임차료 (Rental — direction='지출'만)
    rental_amt = 0.0
    try:
        r_conds = [Rental.direction == "지출"]
        if fd: r_conds.append(Rental.txn_date >= fd)
        if td: r_conds.append(Rental.txn_date <= td)
        if year: r_conds.append(Rental.year == int(year))
        if month: r_conds.append(Rental.month == int(month))
        rental_amt = float(db.scalar(select(func.coalesce(func.sum(Rental.amount), 0)).where(*r_conds)) or 0)
    except Exception:
        rental_amt = 0.0

    sga_amt = payroll_amt + employer_ins + expense_amt + rental_amt

    # 5. 영업이익
    operating_profit = gross_profit - sga_amt
    operating_margin = (operating_profit / sales_amt * 100) if sales_amt else 0

    # 6. 영업외 (간이 — 0 처리, 추후 확장)
    non_op_income = 0.0
    non_op_expense = 0.0

    # 7. 법인세비용차감전순이익
    pre_tax = operating_profit + non_op_income - non_op_expense

    # 8. 추정 법인세 (영업이익 > 0이면 한국 중소기업 평균 ~10%)
    tax_rate = 0.10 if pre_tax > 0 else 0
    estimated_tax = pre_tax * tax_rate

    # 9. 당기순이익
    net_income = pre_tax - estimated_tax
    net_margin = (net_income / sales_amt * 100) if sales_amt else 0

    # 페이지 링크
    qs = []
    if fd: qs.append(f"from_date={fd}")
    if td: qs.append(f"to_date={td}")
    if year: qs.append(f"year={year}")
    if month: qs.append(f"month={month}")

    return {
        "kind": "financial_statement",
        "period_label": period_label,
        "lines": [
            # (label, amount, ratio_to_sales, indent_level, is_subtotal, is_total)
            {"label": "Ⅰ. 매출액",       "amount": sales_amt,       "ratio": 100.0,           "indent": 0, "subtotal": True,  "total": False, "note": f"{sales_cnt:,}건"},
            {"label": "Ⅱ. 매출원가",     "amount": cogs_amt,        "ratio": (cogs_amt/sales_amt*100) if sales_amt else 0, "indent": 0, "subtotal": True, "total": False, "note": f"{cogs_cnt:,}건 (매입)"},
            {"label": "Ⅲ. 매출총이익",   "amount": gross_profit,    "ratio": gross_margin,    "indent": 0, "subtotal": False, "total": True,  "note": ""},
            {"label": "Ⅳ. 판매비와관리비","amount": sga_amt,         "ratio": (sga_amt/sales_amt*100) if sales_amt else 0,  "indent": 0, "subtotal": True, "total": False, "note": ""},
            {"label": "  급여",          "amount": payroll_amt,     "ratio": (payroll_amt/sales_amt*100) if sales_amt else 0,"indent": 1, "subtotal": False, "total": False, "note": ""},
            {"label": "  사용자 부담 4대보험","amount": employer_ins,"ratio": (employer_ins/sales_amt*100) if sales_amt else 0,"indent": 1, "subtotal": False, "total": False, "note": ""},
            {"label": "  일반비용",      "amount": expense_amt,     "ratio": (expense_amt/sales_amt*100) if sales_amt else 0,"indent": 1, "subtotal": False, "total": False, "note": ""},
            {"label": "  임차료",        "amount": rental_amt,      "ratio": (rental_amt/sales_amt*100) if sales_amt else 0,"indent": 1, "subtotal": False, "total": False, "note": ""},
            {"label": "Ⅴ. 영업이익",     "amount": operating_profit,"ratio": operating_margin,"indent": 0, "subtotal": False, "total": True, "note": ""},
            {"label": "Ⅵ. 영업외수익",   "amount": non_op_income,   "ratio": 0,               "indent": 0, "subtotal": True, "total": False, "note": "(미적용)"},
            {"label": "Ⅶ. 영업외비용",   "amount": non_op_expense,  "ratio": 0,               "indent": 0, "subtotal": True, "total": False, "note": "(미적용)"},
            {"label": "Ⅷ. 법인세비용차감전순이익", "amount": pre_tax,  "ratio": (pre_tax/sales_amt*100) if sales_amt else 0, "indent": 0, "subtotal": False, "total": True, "note": ""},
            {"label": "Ⅸ. 법인세비용(추정)", "amount": estimated_tax,"ratio": (estimated_tax/sales_amt*100) if sales_amt else 0,"indent": 0, "subtotal": True, "total": False, "note": "10% 가정"},
            {"label": "Ⅹ. 당기순이익",    "amount": net_income,      "ratio": net_margin,     "indent": 0, "subtotal": False, "total": True, "note": ""},
        ],
        "key_metrics": {
            "sales": sales_amt,
            "gross_profit": gross_profit,
            "gross_margin": gross_margin,
            "operating_profit": operating_profit,
            "operating_margin": operating_margin,
            "net_income": net_income,
            "net_margin": net_margin,
        },
        "page_url": "/",
        "page_label": "대시보드에서 자세히 보기",
    }


def analyze_folder(intent: dict, db: Session) -> dict:
    """챗 명령으로 폴더 경로 분석/적용 — base_data_folder 등록 + 백그라운드 sync 트리거."""
    from pathlib import Path
    import settings_store as ss
    import subprocess, sys, os
    folder = (intent.get("folder_path") or "").strip().strip('"\'')
    if not folder:
        return {"kind": "analyze_folder", "ok": False,
                "msg": "폴더 경로를 인식하지 못했습니다.",
                "summary": "❌ 폴더 경로를 인식하지 못했습니다. 예: \"C:\\path\\to\\folder 분석해\""}
    p_norm = folder.replace("/", "\\") if folder[0:1].isalpha() and folder[1:2] == ":" else folder
    p = Path(p_norm)
    if not p.exists() or not p.is_dir():
        msg = f"경로가 존재하지 않거나 폴더가 아닙니다:\n{folder}"
        return {"kind": "analyze_folder", "ok": False, "msg": msg, "summary": "❌ " + msg}
    # base_data_folder 등록
    ss.save({"base_data_folder": str(p)})
    ss.invalidate()
    # 백그라운드 sync 트리거
    web_app = Path(__file__).parent
    try:
        subprocess.Popen(
            [sys.executable, "-u", "-c",
             "import sync_core; print(sync_core.run_sync(triggered_by='chat-folder', force=True, verbose=False).status)"],
            cwd=str(web_app),
            env={**os.environ, "PYTHONIOENCODING": "utf-8"},
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            creationflags=getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0),
        )
        bg_started = True
    except Exception as e:
        bg_started = False
    n_files = 0
    try:
        for _ in p.rglob("*.xlsx"): n_files += 1
        for _ in p.rglob("*.xls"): n_files += 1
    except Exception:
        pass
    summary = (
        f"✅ 폴더를 기본 데이터 소스로 등록하고 백그라운드 분석을 시작했습니다.\n"
        f"📁 경로: {p}\n"
        f"📊 Excel 파일 후보: 약 {n_files:,}개\n"
        f"⏳ 진행 상황은 동기화 페이지에서 확인하세요."
    ) if bg_started else (
        f"⚠️ 폴더는 등록했지만 백그라운드 동기화 시작에 실패했습니다.\n"
        f"📁 경로: {p}\n동기화 페이지에서 수동 실행해 주세요."
    )
    return {"kind": "analyze_folder", "ok": True, "folder": str(p), "n_files": n_files,
            "msg": summary, "summary": summary,
            "page_url": "/sync", "page_label": "동기화 진행 상황 보기"}


DISPATCH = {
    "search_sale": search_sale,
    "search_purchase": search_purchase,
    "search_party": search_party,
    "search_contract": search_contract,
    "search_document": search_document,
    "search_loan": search_loan,
    "search_payroll": search_payroll,
    "search_employee": search_employee,
    "kpi": kpi_overview,
    "financial_statement": financial_statement,
    "analyze_folder": analyze_folder,
}


def dispatch(intent: dict, db: Session) -> Optional[dict]:
    fn = DISPATCH.get(intent.get("intent"))
    if not fn:
        return None
    try:
        return fn(intent, db)
    except Exception as e:
        return {"kind": "error", "error": f"{type(e).__name__}: {e}"}


# ---------------- 응답 요약 ----------------
def summarize(query: str, intent: dict, result: dict, model: str = DEFAULT_MODEL) -> str:
    """LLM이 결과를 사용자에게 한국어로 한 두 문장 요약"""
    if result is None or intent.get("intent") == "unknown":
        return ""
    # 결과를 간단한 텍스트로 변환
    if result.get("kind") == "error":
        return f"검색 중 오류가 발생했습니다: {result.get('error')}"

    summary_input = {"intent": intent.get("intent"), "result": result}
    system = """당신은 경영관리 시스템의 비서입니다. 사용자의 질문과 DB 검색 결과를 받아,
2~3문장의 친절한 한국어로 답하세요. 숫자는 콤마로 표기하고 단위(원/건/명)를 붙이세요.
결과 외 정보는 추측하지 마세요. 마지막에 "더 자세한 내용은 페이지에서 확인하세요" 같은 안내를 한 줄 덧붙여도 됩니다."""
    user = f"질문: {query}\n\n검색 결과 (JSON):\n{json.dumps(summary_input, ensure_ascii=False)}"
    try:
        return ollama_chat(
            [{"role": "system", "content": system}, {"role": "user", "content": user}],
            model=model, temperature=0.3,
        ).strip()
    except Exception as e:
        return f"(요약 생성 실패) 결과 카드를 직접 확인하세요. 오류: {e}"


def template_summary(intent: dict, result: dict) -> str:
    """LLM 없이 결과를 한국어 요약으로 즉시 변환 (빠른 응답용)"""
    if not result:
        return ""
    k = result.get("kind")
    fmt = lambda v: f"{int(round(v)):,}"
    if k == "sale":
        s = f"매출 {fmt(result['count'])}건, 공급가액 합계 {fmt(result['sum_supply'])}원 (총합 {fmt(result['sum_total'])}원)입니다."
        if result["top_parties"]:
            n, v = result["top_parties"][0]
            s += f" 가장 큰 거래처는 {n} ({fmt(v)}원)입니다."
        return s
    if k == "purchase":
        s = f"매입 {fmt(result['count'])}건, 공급가액 합계 {fmt(result['sum_supply'])}원입니다."
        if result["top_parties"]:
            n, v = result["top_parties"][0]
            s += f" 최대 매입처는 {n} ({fmt(v)}원)입니다."
        return s
    if k == "party":
        if not result["items"]:
            return "조건에 맞는 거래처를 찾지 못했습니다."
        items = result["items"]
        s = f"거래처 {len(items)}건 찾았습니다."
        if items:
            top = items[0]
            s += f" 첫 번째 결과: {top['name']} ({top['category'] or '-'}) — 매출 누계 {fmt(top['sale_total'])}원."
        return s
    if k == "contract":
        s = f"계약 {fmt(result['count'])}건, 계약금 합계 {fmt(result['sum_amount'])}원, 미수금 {fmt(result['sum_unpaid'])}원입니다."
        return s
    if k == "document":
        if intent.get("expiring_within_days"):
            d = intent["expiring_within_days"]
            return f"{d}일 이내 만료되는 문서 {fmt(result['count'])}건이 있습니다." if result['count'] else f"{d}일 이내 만료되는 문서가 없습니다."
        return f"문서 {fmt(result['count'])}건 찾았습니다."
    if k == "loan":
        return f"차입금 {fmt(result['count'])}건, 총 잔액 {fmt(result['total_balance'])}원입니다."
    if k == "payroll":
        return f"급여 {fmt(result['count'])}건, 지급합계 {fmt(result['sum_gross'])}원입니다."
    if k == "employee":
        return f"직원 {fmt(result['count'])}명 찾았습니다."
    if k == "kpi":
        return (f"{result['year']}년 매출 {fmt(result['sales'])}원, 매입 {fmt(result['purchases'])}원, "
                f"매출이익 {fmt(result['gross_margin'])}원. 차입금 잔액 {fmt(result['loan_balance'])}원, "
                f"30일 내 만료 문서 {result['expiring_docs_30']}건.")
    if k == "financial_statement":
        km = result.get("key_metrics", {})
        return (f"{result['period_label']} 손익계산서 — "
                f"매출 {fmt(km.get('sales', 0))}원, "
                f"매출총이익 {fmt(km.get('gross_profit', 0))}원 ({km.get('gross_margin', 0):.1f}%), "
                f"영업이익 {fmt(km.get('operating_profit', 0))}원 ({km.get('operating_margin', 0):.1f}%), "
                f"당기순이익 {fmt(km.get('net_income', 0))}원.")
    if k == "error":
        return f"오류: {result.get('error', '')}"
    if k == "analyze_folder":
        # 핸들러가 만든 summary를 그대로 사용 (백그라운드 sync 안내)
        return result.get("summary") or result.get("msg") or ""
    return ""


# ---------------- RAG 통합 ----------------
def rag_answer(query: str, model: str = DEFAULT_MODEL, k: int = 6) -> dict:
    """RAG: 벡터 DB 검색 → 컨텍스트 + 질문 → LLM → 답변

    의도 분류로 해결 안 되는 자유 질문(예: '인비즈 주요 거래처는?', '회사 소개해줘')에 사용.
    """
    from rag import retrieve_hybrid, build_context, count_tokens

    hits = retrieve_hybrid(query, k_kb=k, k_conv=2, min_score=0.3)
    if not hits:
        return {
            "answer": "관련 자료를 찾지 못했습니다. 더 구체적인 질문을 해주시거나 다른 키워드를 시도해 보세요.",
            "sources": [], "chunks_used": 0,
            "tokens_input": count_tokens(query),
            "tokens_output": 0,
        }

    context, sources, ctx_tok = build_context(hits, max_tokens=2000)

    system = """당신은 한국 의료 IT 회사 "인비즈(Inviz)"의 경영관리 비서입니다.
아래 [참고 자료]만 근거로 한국어로 답하세요. 자료에 없는 내용은 추측하지 말고 "자료에 없습니다"라고 답하세요.
핵심 답변을 맨 앞에 1~3문장으로 명확히 제시하세요. 상세 수치·근거는 화면의 접이식 '데이터 결과'·'참고 자료'에 따로 표시되므로, 답변만으로도 충분히 이해되도록 작성하세요.
숫자는 콤마와 단위(원, 건, 명)를 명확히 표기하세요.
분기는 3개월 단위입니다: 1분기=1~3월, 2분기=4~6월, 3분기=7~9월, 4분기=10~12월. 예) '2026년 1분기'는 2026-01-01 ~ 2026-03-31 입니다.
답변 마지막에 어떤 자료를 참조했는지 [자료 N] 번호로 인용하세요."""

    user = f"[참고 자료]\n{context}\n\n[질문]\n{query}"
    input_tokens = count_tokens(system) + count_tokens(user)

    try:
        answer = ollama_chat(
            [{"role": "system", "content": system},
             {"role": "user", "content": user}],
            model=model, temperature=0.2, num_predict=400,
        )
    except Exception as e:
        return {
            "answer": f"LLM 호출 실패: {e}",
            "sources": sources, "chunks_used": len(hits),
            "tokens_input": input_tokens, "tokens_output": 0,
        }

    return {
        "answer": answer.strip(),
        "sources": sources,
        "chunks_used": len(hits),
        "hits": [{
            "title": h.get("metadata", {}).get("title"),
            "page_url": h.get("metadata", {}).get("page_url"),
            "score": h.get("score"),
            "source": h.get("source"),
            "source_type": h.get("metadata", {}).get("source_type"),
            "preview": h["content"][:120] + ("..." if len(h["content"]) > 120 else ""),
        } for h in hits],
        "tokens_input": input_tokens,
        "tokens_output": count_tokens(answer),
        "context_tokens": ctx_tok,
    }


# ---------------- 통합 처리 ----------------
def process_query(query: str, db: Session, model: str = DEFAULT_MODEL,
                  ai_summary: bool = False, use_rag: bool = False) -> dict:
    """
    use_rag=True: 벡터 DB에서 관련 자료 검색 → LLM 컨텍스트 증강 → 자유 형식 답변
    use_rag=False (기본): 구조화된 DB 쿼리 + 템플릿 답변 (빠름, 정확)

    ai_summary=True: LLM 추가 요약 (use_rag와 독립)

    빠른 경로: 키워드 매칭으로 의도를 즉시 결정 가능하면 LLM 우회 (1초 미만).
    """
    # Mojibake 자동 복구
    if query and not re.search(r"[가-힣]", query):
        try:
            recovered = query.encode("cp1252").decode("utf-8")
            if re.search(r"[가-힣]", recovered):
                query = recovered
        except (UnicodeEncodeError, UnicodeDecodeError):
            pass

    # 의도 분류
    fast = fast_intent_match(query)
    if fast:
        intent = fast
    else:
        intent = extract_intent(query, model=model)
    result = dispatch(intent, db)

    # RAG 모드: 항상 RAG 답변을 추가 (의도 검색 결과와 함께)
    rag = None
    if use_rag or result is None:
        rag = rag_answer(query, model=model)

    # 의도 매칭 실패 + RAG도 없으면 안내
    if result is None and (not rag or not rag.get("answer")):
        return {
            "intent": intent, "result": None, "rag": rag,
            "summary": "질문을 분류하지 못했습니다. 더 구체적인 키워드로 시도해 보세요.",
        }

    if ai_summary and result:
        summary = summarize(query, intent, result, model=model)
    elif result:
        summary = template_summary(intent, result)
    else:
        summary = rag.get("answer", "") if rag else ""

    return {"intent": intent, "result": result, "rag": rag, "summary": summary}
