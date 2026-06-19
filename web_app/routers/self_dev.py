# -*- coding: utf-8 -*-
"""자가발전 시스템 대시보드 + 안전 동기화 트리거"""
from datetime import datetime, timedelta
from fastapi import APIRouter, Request, Form, Depends, BackgroundTasks
from fastapi.responses import HTMLResponse, RedirectResponse, JSONResponse
from sqlalchemy import select, func, desc
from sqlalchemy.orm import Session

from database import get_db, SessionLocal
from helpers import templates
from models import (IntegrityCheck, UnmappedFileReview, SyncRun,
                    FileRegistry, KnowledgeChunk, ChatHistory)

router = APIRouter()


@router.get("", response_class=HTMLResponse)
def self_dev_dashboard(request: Request, db: Session = Depends(get_db)):
    # 최근 SyncRun + 무결성 통계
    recent_runs = db.execute(
        select(SyncRun).order_by(SyncRun.id.desc()).limit(10)
    ).scalars().all()

    # 무결성 검사 통계
    total_checks = db.scalar(select(func.count()).select_from(IntegrityCheck)) or 0
    by_status = db.execute(
        select(IntegrityCheck.status, func.count())
        .group_by(IntegrityCheck.status)
    ).all()
    integrity_by_status = {s: c for s, c in by_status}

    # 최근 의심·롤백
    recent_warns = db.execute(
        select(IntegrityCheck).where(
            IntegrityCheck.status.in_(["warning", "critical", "rolled_back"])
        ).order_by(IntegrityCheck.id.desc()).limit(15)
    ).scalars().all()

    # 미매핑 파일 검토 큐
    pending_reviews = db.execute(
        select(UnmappedFileReview).where(UnmappedFileReview.status == "pending")
        .order_by(UnmappedFileReview.confidence.desc().nullslast())
        .limit(20)
    ).scalars().all()

    auto_processed = db.scalar(
        select(func.count()).where(UnmappedFileReview.status == "auto_processed")
        .select_from(UnmappedFileReview)
    ) or 0

    # 학습된 대화 (피드백 기반)
    learned_chats = db.scalar(
        select(func.count()).where(ChatHistory.is_indexed == "Y").select_from(ChatHistory)
    ) or 0
    good_feedback = db.scalar(
        select(func.count()).where(ChatHistory.user_feedback == "good").select_from(ChatHistory)
    ) or 0
    bad_feedback = db.scalar(
        select(func.count()).where(ChatHistory.user_feedback == "bad").select_from(ChatHistory)
    ) or 0

    # 무결성 점수 (warning/critical 없으면 100점)
    ok_count = integrity_by_status.get("ok", 0)
    warn_count = integrity_by_status.get("warning", 0)
    crit_count = integrity_by_status.get("critical", 0)
    rb_count = integrity_by_status.get("rolled_back", 0)
    integrity_score = 100
    if total_checks:
        deductions = (warn_count * 2 + crit_count * 10 + rb_count * 5) / total_checks
        integrity_score = max(0, int(100 - deductions))

    # LLM 분류 정확도 (auto_processed 비율)
    total_reviews = db.scalar(select(func.count()).select_from(UnmappedFileReview)) or 0
    classify_rate = round(auto_processed / total_reviews * 100, 1) if total_reviews else 0

    return templates.TemplateResponse("self_dev/dashboard.html", {
        "request": request,
        "recent_runs": recent_runs,
        "total_checks": total_checks,
        "integrity_by_status": integrity_by_status,
        "integrity_score": integrity_score,
        "recent_warns": recent_warns,
        "pending_reviews": pending_reviews,
        "auto_processed": auto_processed,
        "total_reviews": total_reviews,
        "classify_rate": classify_rate,
        "learned_chats": learned_chats,
        "good_feedback": good_feedback,
        "bad_feedback": bad_feedback,
    })


@router.post("/run-safe-sync")
def run_safe_sync(bg: BackgroundTasks, auto_rollback: str = Form("true")):
    """수동으로 안전 동기화 트리거"""
    auto_rb = auto_rollback.lower() in ("true", "1", "yes", "on")
    bg.add_task(_safe_sync_bg, auto_rb)
    return RedirectResponse("/self-dev?started=1", status_code=303)


def _safe_sync_bg(auto_rollback: bool):
    from self_dev import safe_sync
    try:
        safe_sync(triggered_by="manual_self_dev",
                  auto_rollback_on_critical=auto_rollback)
    except Exception as e:
        print(f"[safe_sync bg] error: {e}")


@router.post("/review/{review_id}/approve")
def approve_review(review_id: int, db: Session = Depends(get_db),
                   domain: str = Form(...)):
    """검토 대기열에서 사용자가 도메인 확정"""
    review = db.get(UnmappedFileReview, review_id)
    if not review:
        return JSONResponse({"error": "검토 없음"}, status_code=404)
    review.user_assigned_domain = domain
    review.status = "approved"
    review.decided_at = datetime.utcnow()
    # 해당 file_registry 갱신
    if review.file_registry_id:
        fr = db.get(FileRegistry, review.file_registry_id)
        if fr:
            fr.domain = domain
            fr.matched_pattern = "사용자 확정"
            fr.status = "new"  # 다음 sync에서 처리
    db.commit()
    return RedirectResponse("/self-dev", status_code=303)


@router.post("/review/{review_id}/reject")
def reject_review(review_id: int, db: Session = Depends(get_db)):
    review = db.get(UnmappedFileReview, review_id)
    if not review:
        return JSONResponse({"error": "없음"}, status_code=404)
    review.status = "rejected"
    review.decided_at = datetime.utcnow()
    db.commit()
    return RedirectResponse("/self-dev", status_code=303)


@router.post("/rollback/{run_id}")
def manual_rollback(run_id: int, db: Session = Depends(get_db)):
    """특정 sync의 스냅샷으로 수동 롤백"""
    ic = db.execute(
        select(IntegrityCheck).where(IntegrityCheck.run_id == run_id,
                                      IntegrityCheck.snapshot_path.is_not(None)).limit(1)
    ).scalar_one_or_none()
    if not ic or not ic.snapshot_path:
        return JSONResponse({"error": "스냅샷 없음"}, status_code=404)
    from pathlib import Path
    from self_dev import restore_db
    ok = restore_db(Path(ic.snapshot_path))
    return JSONResponse({"ok": ok, "snapshot": ic.snapshot_path})
