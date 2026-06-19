# -*- coding: utf-8 -*-
"""캘린더 — 스케줄 관리. 수동 일정(계산서 발행예정·지출·수입·미팅 등) +
기존 데이터 자동 표시(발행대기 계산서·계약 만료·차입금 만기)."""
import calendar as _cal
from datetime import date, datetime, timedelta
from fastapi import APIRouter, Request, Form, Depends, HTTPException
from fastapi.responses import HTMLResponse, RedirectResponse, JSONResponse
from sqlalchemy import select
from sqlalchemy.orm import Session

from database import get_db
from helpers import templates
from models import CalendarEvent, TaxInvoice, Contract, LoanMaster

router = APIRouter()

CATS = {
    "invoice":  {"label": "계산서 발행", "icon": "🧾", "color": "#6B2C91", "bg": "#F3E8FF"},
    "expense":  {"label": "지출",       "icon": "💸", "color": "#B91C1C", "bg": "#FEE2E2"},
    "income":   {"label": "수입",       "icon": "💰", "color": "#065F46", "bg": "#D1FAE5"},
    "contract": {"label": "계약",       "icon": "📋", "color": "#1E40AF", "bg": "#DBEAFE"},
    "loan":     {"label": "차입/상환",  "icon": "🏦", "color": "#475569", "bg": "#F1F5F9"},
    "card":     {"label": "카드 출금",  "icon": "💳", "color": "#9D174D", "bg": "#FCE7F3"},
    "tax":      {"label": "세금 신고",  "icon": "🧾", "color": "#B45309", "bg": "#FEF3C7"},
    "meeting":  {"label": "미팅/일정",  "icon": "📅", "color": "#9A3412", "bg": "#FFEDD5"},
    "etc":      {"label": "기타",       "icon": "📌", "color": "#334155", "bg": "#E2E8F0"},
}
WEEKDAYS = ["일", "월", "화", "수", "목", "금", "토"]


def _cat(c):
    return CATS.get(c or "etc", CATS["etc"])


def _expand(ev, start, end):
    """반복 일정을 [start,end] 범위 내 날짜 목록으로 펼침."""
    d0 = ev.event_date
    if not d0:
        return []
    out = []
    rep = (ev.repeat or "none")
    if rep == "none":
        if start <= d0 <= end:
            out.append(d0)
    elif rep == "weekly":
        # d0 기준 7일 간격
        first = start + timedelta(days=(d0.weekday() - start.weekday()) % 7)
        d = max(first, d0)
        while d <= end:
            if d >= d0:
                out.append(d)
            d += timedelta(days=7)
    elif rep == "monthly":
        y, m = start.year, start.month
        while date(y, m, 1) <= end:
            last = _cal.monthrange(y, m)[1]
            day = min(d0.day, last)
            cand = date(y, m, day)
            if start <= cand <= end and cand >= d0:
                out.append(cand)
            m += 1
            if m > 12:
                m = 1; y += 1
    elif rep == "yearly":
        for y in range(start.year, end.year + 1):
            try:
                cand = date(y, d0.month, d0.day)
            except ValueError:
                continue
            if start <= cand <= end and cand >= d0:
                out.append(cand)
    return out


def _events_in_range(db, start, end):
    """범위 내 모든 일정(수동 펼침 + 자동) → {iso: [event dict, ...]}"""
    by = {}

    def add(d, ev):
        by.setdefault(d.isoformat(), []).append(ev)

    # 1) 수동 일정
    rows = db.execute(select(CalendarEvent)).scalars().all()
    for r in rows:
        for d in _expand(r, start, end):
            add(d, {"id": r.id, "title": r.title, "category": r.category or "etc",
                    "amount": float(r.amount) if r.amount is not None else None,
                    "party": r.party_name, "time": r.time_text, "done": r.done == "Y",
                    "repeat": r.repeat, "note": r.note, "source": "manual"})

    # 2) 자동: 발행대기 매출 계산서
    try:
        inv = db.execute(select(TaxInvoice).where(
            TaxInvoice.direction == "sale", TaxInvoice.status.in_(["draft", "ready"]),
            TaxInvoice.write_date >= start, TaxInvoice.write_date <= end)).scalars().all()
        for t in inv:
            add(t.write_date, {"id": None, "title": f"계산서 발행예정 · {t.party_name or ''}",
                               "category": "invoice", "amount": float(t.total or 0),
                               "party": t.party_name, "time": None, "done": False,
                               "source": "auto", "link": "/tax/issue"})
    except Exception:
        pass

    # 3) 자동: 계약 만료
    try:
        cons = db.execute(select(Contract).where(
            Contract.end_date >= start, Contract.end_date <= end)).scalars().all()
        for c in cons:
            add(c.end_date, {"id": None, "title": f"계약 만료 · {c.name or c.party_name or ''}",
                             "category": "contract", "amount": float(c.contract_amount or 0),
                             "party": c.party_name, "time": None, "done": False,
                             "source": "auto", "link": "/contracts"})
    except Exception:
        pass

    # 4) 자동: 차입금 만기
    try:
        lns = db.execute(select(LoanMaster).where(
            LoanMaster.end_date >= start, LoanMaster.end_date <= end)).scalars().all()
        for l in lns:
            add(l.end_date, {"id": None, "title": f"차입금 만기 · {l.institution or ''}",
                             "category": "loan", "amount": float(l.current_balance or 0),
                             "party": l.institution, "time": None, "done": False,
                             "source": "auto", "link": "/loans"})
    except Exception:
        pass

    # 정렬(시간 있는 것 우선X → 단순 카테고리/제목)
    for k in by:
        by[k].sort(key=lambda e: (e["category"] != "invoice", e.get("time") or "", e["title"]))
    return by


@router.get("", response_class=HTMLResponse)
@router.get("/", response_class=HTMLResponse)
def calendar_view(request: Request, db: Session = Depends(get_db), y: str = "", m: str = ""):
    today = date.today()
    try:
        yy = int(y) if y else today.year
        mm = int(m) if m else today.month
        if not (1 <= mm <= 12):
            mm = today.month
    except Exception:
        yy, mm = today.year, today.month

    cal = _cal.Calendar(firstweekday=6)  # 일요일 시작
    weeks_dates = cal.monthdatescalendar(yy, mm)
    grid_start, grid_end = weeks_dates[0][0], weeks_dates[-1][-1]
    by = _events_in_range(db, grid_start, grid_end)

    weeks = []
    for wk in weeks_dates:
        row = []
        for d in wk:
            row.append({"day": d.day, "iso": d.isoformat(), "in_month": d.month == mm,
                        "is_today": d == today, "weekday": d.weekday(),
                        "events": by.get(d.isoformat(), [])})
        weeks.append(row)

    # 다가오는 일정 (오늘~+30일)
    up_by = _events_in_range(db, today, today + timedelta(days=30))
    upcoming = []
    for iso in sorted(up_by.keys()):
        for ev in up_by[iso]:
            upcoming.append({"date": iso, **ev})
    upcoming = upcoming[:20]

    prev_y, prev_m = (yy - 1, 12) if mm == 1 else (yy, mm - 1)
    next_y, next_m = (yy + 1, 1) if mm == 12 else (yy, mm + 1)
    return templates.TemplateResponse("calendar/month.html", {
        "request": request, "year": yy, "month": mm, "weeks": weeks,
        "weekday_names": WEEKDAYS, "cats": CATS, "today": today,
        "prev": f"?y={prev_y}&m={prev_m}", "next": f"?y={next_y}&m={next_m}",
        "this_month": f"?y={today.year}&m={today.month}",
        "upcoming": upcoming, "default_date": today.isoformat(),
    })


@router.post("/add")
def calendar_add(request: Request, db: Session = Depends(get_db),
                 event_date: str = Form(...), title: str = Form(...), category: str = Form("etc"),
                 amount: str = Form(""), party_name: str = Form(""), time_text: str = Form(""),
                 repeat: str = Form("none"), note: str = Form("")):
    try:
        d = date.fromisoformat(event_date)
    except Exception:
        d = date.today()
    try:
        amt = float(str(amount).replace(",", "").strip()) if str(amount).strip() else None
    except Exception:
        amt = None
    ev = CalendarEvent(event_date=d, title=title.strip()[:200] or "(제목없음)",
                       category=category if category in CATS else "etc",
                       amount=amt, party_name=party_name.strip() or None,
                       time_text=time_text.strip() or None,
                       repeat=repeat if repeat in ("none", "weekly", "monthly", "yearly") else "none",
                       note=note.strip() or None)
    db.add(ev); db.commit()
    return RedirectResponse(f"/calendar?y={d.year}&m={d.month}", status_code=303)


@router.post("/{ev_id}/update")
def calendar_update(ev_id: int, db: Session = Depends(get_db),
                    event_date: str = Form(...), title: str = Form(...), category: str = Form("etc"),
                    amount: str = Form(""), party_name: str = Form(""), time_text: str = Form(""),
                    repeat: str = Form("none"), note: str = Form("")):
    ev = db.get(CalendarEvent, ev_id)
    if not ev:
        raise HTTPException(404, "일정 없음")
    try:
        ev.event_date = date.fromisoformat(event_date)
    except Exception:
        pass
    ev.title = title.strip()[:200] or ev.title
    ev.category = category if category in CATS else "etc"
    try:
        ev.amount = float(str(amount).replace(",", "").strip()) if str(amount).strip() else None
    except Exception:
        ev.amount = None
    ev.party_name = party_name.strip() or None
    ev.time_text = time_text.strip() or None
    ev.repeat = repeat if repeat in ("none", "weekly", "monthly", "yearly") else "none"
    ev.note = note.strip() or None
    db.commit()
    return RedirectResponse(f"/calendar?y={ev.event_date.year}&m={ev.event_date.month}", status_code=303)


@router.post("/{ev_id}/delete")
def calendar_delete(ev_id: int, db: Session = Depends(get_db), y: str = Form(""), m: str = Form("")):
    ev = db.get(CalendarEvent, ev_id)
    if ev:
        db.delete(ev); db.commit()
    suffix = f"?y={y}&m={m}" if y and m else ""
    return RedirectResponse(f"/calendar{suffix}", status_code=303)


@router.post("/{ev_id}/toggle")
def calendar_toggle(ev_id: int, db: Session = Depends(get_db)):
    ev = db.get(CalendarEvent, ev_id)
    if not ev:
        raise HTTPException(404, "일정 없음")
    ev.done = "N" if ev.done == "Y" else "Y"
    db.commit()
    return JSONResponse({"ok": True, "done": ev.done == "Y"})
