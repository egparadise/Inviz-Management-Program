# -*- coding: utf-8 -*-
"""자동 실행 스케줄러 — 설정된 일·주·월간 시간에 기능 자동 실행

대상 작업:
  - sync     : 동기화 (sync_core.run_sync)
  - learning : AI 학습 / 벡터 인덱싱 (rag_ingest.run_full_ingest)
  - selfdev  : 자가발전 안전 동기화 (self_dev.safe_sync)

설정 키 (settings_store):
  sched_<task>_enabled  : "1"/"0"
  sched_<task>_freq     : daily / weekly / monthly
  sched_<task>_time     : "HH:MM"
  sched_<task>_dow      : 0(월)~6(일)   (weekly)
  sched_<task>_dom      : 1~28          (monthly)
  sched_<task>_last_run : 마지막 실행 슬롯 (ISO) — 중복 실행 방지
  sched_<task>_last_status / sched_<task>_last_done : 결과
"""
import threading
import time
from datetime import datetime, timedelta


# ---- 작업 실행자 ----
def _run_sync():
    from sync_core import run_sync
    run_sync(triggered_by="schedule")


def _run_learning():
    from rag_ingest import run_full_ingest
    run_full_ingest(verbose=False)


def _run_selfdev():
    from self_dev import safe_sync
    import settings_store as ss
    safe_sync(triggered_by="schedule",
              model=ss.get("learning_model", "llama3.1:latest"),
              auto_rollback_on_critical=True)


TASKS = {
    "sync":     {"label": "동기화",   "runner": _run_sync},
    "learning": {"label": "AI 학습",  "runner": _run_learning},
    "selfdev":  {"label": "자가발전", "runner": _run_selfdev},
}

_running = set()
_lock = threading.Lock()
_started = False


def _parse_hhmm(s):
    try:
        h, m = str(s).split(":")
        return int(h), int(m)
    except Exception:
        return 4, 0


def is_due(task: str, now: datetime) -> bool:
    import settings_store as ss
    if ss.get(f"sched_{task}_enabled", "0") != "1":
        return False
    freq = ss.get(f"sched_{task}_freq", "daily")
    h, m = _parse_hhmm(ss.get(f"sched_{task}_time", "04:00"))
    if freq == "daily":
        matches = True
    elif freq == "weekly":
        dow = str(ss.get(f"sched_{task}_dow", "0") or "0").strip()
        if dow == "*":
            matches = True   # 모두(매일)
        else:
            try:
                matches = now.weekday() == int(dow)
            except Exception:
                matches = False
    elif freq == "monthly":
        dom = str(ss.get(f"sched_{task}_dom", "1") or "1").strip()
        if dom == "*":
            matches = True   # 모두(매일)
        elif dom == "last":
            # 말일: 다음 날이 다음 달이면 오늘이 말일
            nxt = now.replace(hour=0, minute=0, second=0, microsecond=0) + timedelta(days=1)
            matches = (nxt.month != now.month)
        else:
            try:
                matches = now.day == int(dom)
            except Exception:
                matches = False
    else:
        matches = False
    if not matches:
        return False
    sched_dt = now.replace(hour=h, minute=m, second=0, microsecond=0)
    if now < sched_dt:
        return False
    last = ss.get(f"sched_{task}_last_run", "")
    if last:
        try:
            if datetime.fromisoformat(last) >= sched_dt:
                return False
        except Exception:
            pass
    return True


def run_task_async(task: str, manual: bool = False):
    """작업을 백그라운드 스레드로 실행 (중복 방지)."""
    meta = TASKS.get(task)
    if not meta:
        return False
    with _lock:
        if task in _running:
            return False
        _running.add(task)

    def worker():
        import settings_store as ss
        start = datetime.now()
        try:
            # 슬롯 중복 방지: 실행 시작 시점을 last_run으로 기록
            if not manual:
                ss.save({f"sched_{task}_last_run": start.isoformat()})
            print(f"[scheduler] '{meta['label']}' {'수동' if manual else '자동'} 실행 시작 {start:%Y-%m-%d %H:%M}")
            meta["runner"]()
            ss.save({
                f"sched_{task}_last_status": "성공",
                f"sched_{task}_last_done": datetime.now().isoformat(),
            })
            print(f"[scheduler] '{meta['label']}' 완료")
        except Exception as e:
            ss.save({
                f"sched_{task}_last_status": f"오류: {e}"[:180],
                f"sched_{task}_last_done": datetime.now().isoformat(),
            })
            print(f"[scheduler] '{meta['label']}' 실패: {e}")
        finally:
            with _lock:
                _running.discard(task)

    threading.Thread(target=worker, daemon=True, name=f"sched-{task}").start()
    return True


def _check_scheduled_invoices():
    """예약(scheduled) 세금계산서 중 발송일 도래분 자동 발송 + 알림."""
    from database import SessionLocal
    db = SessionLocal()
    try:
        import routers.tax as taxr
        n = taxr.process_due_invoices(db, base_url="")
        if n:
            print(f"[scheduler] 예약 세금계산서 {n}건 자동 발송 처리")
    finally:
        db.close()


def _check_card_billing():
    """카드 출금(결제)예정일 캘린더 자동 등록 + 임박(D-3 이내)·한도초과(90%↑) 텔레그램 알림."""
    from datetime import date
    from database import SessionLocal
    from sqlalchemy import select, func
    from models import Card, CardTransaction, CalendarEvent
    from routers.banking import _next_billing
    import settings_store as ss
    try:
        import integrations as ig
    except Exception:
        ig = None
    db = SessionLocal()
    try:
        today = date.today()
        month_start = today.replace(day=1)
        cards = db.execute(select(Card).where(Card.active == "Y")).scalars().all()
        for c in cards:
            nb = _next_billing(c.billing_day, today)
            if not nb:
                continue
            cycle = nb.strftime("%Y%m")
            # 1) 캘린더 일정 자동 등록(중복 방지)
            note_tag = f"card:{c.id}"
            exists = db.scalar(select(func.count()).select_from(CalendarEvent).where(
                CalendarEvent.category == "card", CalendarEvent.event_date == nb,
                CalendarEvent.note == note_tag))
            if not exists:
                used = float(db.scalar(select(func.coalesce(func.sum(CardTransaction.amount), 0)).where(
                    CardTransaction.card_id == c.id, CardTransaction.tx_date >= month_start)) or 0)
                db.add(CalendarEvent(
                    event_date=nb, title=f"💳 {c.card_name} 카드 출금예정",
                    category="card", amount=used or None, party_name=c.issuer,
                    repeat="monthly", done="N", note=note_tag))
                db.commit()
            # 2) 출금 임박 알림 (D-3 이내, 사이클당 1회)
            days_to = (nb - today).days
            if 0 <= days_to <= 3:
                flag = f"card_due_{c.id}_{cycle}"
                if ss.get(flag) != "1":
                    used = float(db.scalar(select(func.coalesce(func.sum(CardTransaction.amount), 0)).where(
                        CardTransaction.card_id == c.id, CardTransaction.tx_date >= month_start)) or 0)
                    msg = (f"[인비즈] 카드 출금예정 D-{days_to}\n"
                           f"· 카드: {c.card_name} ({c.issuer or ''})\n"
                           f"· 출금예정일: {nb}\n"
                           f"· 이번 달 사용액: {int(used):,}원")
                    if ig:
                        ig.send_telegram(msg)
                    ss.save({flag: "1"})
            # 3) 한도 초과 임박 알림 (90%↑, 월 1회)
            limit = float(c.credit_limit or 0)
            if limit > 0:
                used = float(db.scalar(select(func.coalesce(func.sum(CardTransaction.amount), 0)).where(
                    CardTransaction.card_id == c.id, CardTransaction.tx_date >= month_start)) or 0)
                pct = used / limit * 100
                if pct >= 90:
                    flag = f"card_lim_{c.id}_{today.strftime('%Y%m')}"
                    if ss.get(flag) != "1":
                        msg = (f"[인비즈] 카드 한도 임박 ({pct:.0f}%)\n"
                               f"· 카드: {c.card_name} ({c.issuer or ''})\n"
                               f"· 사용/한도: {int(used):,} / {int(limit):,}원")
                        if ig:
                            ig.send_telegram(msg)
                        ss.save({flag: "1"})
    except Exception as e:
        print(f"[scheduler] 카드 알림 처리 오류: {e}")
    finally:
        db.close()


def _loop():
    time.sleep(20)  # 앱 완전 기동 대기
    while True:
        try:
            now = datetime.now()
            for task in TASKS:
                try:
                    if is_due(task, now):
                        run_task_async(task, manual=False)
                except Exception as e:
                    print(f"[scheduler] '{task}' 판정 오류: {e}")
            # 예약 세금계산서 자동 발송(매 주기 점검)
            try:
                _check_scheduled_invoices()
            except Exception as e:
                print(f"[scheduler] 예약 계산서 처리 오류: {e}")
            # 카드 출금예정·한도 알림(매 주기 점검, 내부 중복 방지)
            try:
                _check_card_billing()
            except Exception as e:
                print(f"[scheduler] 카드 알림 처리 오류: {e}")
        except Exception as e:
            print(f"[scheduler] loop error: {e}")
        time.sleep(50)  # 약 1분 주기


def start():
    global _started
    if _started:
        return
    _started = True
    threading.Thread(target=_loop, daemon=True, name="scheduler-loop").start()
    print("[scheduler] 백그라운드 자동 실행 스케줄러 시작")
