# -*- coding: utf-8 -*-
"""동기화 라우터 — 현황·로그·수동 실행"""
from fastapi import APIRouter, Request, Depends, BackgroundTasks
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy import select, func, desc
from sqlalchemy.orm import Session

from database import get_db, SessionLocal
from helpers import templates
from models import FileRegistry, SyncRun, SyncRunDetail

router = APIRouter()


@router.get("", response_class=HTMLResponse)
def sync_dashboard(request: Request, db: Session = Depends(get_db)):
    # 최근 실행 이력 10건
    runs = db.execute(select(SyncRun).order_by(SyncRun.id.desc()).limit(10)).scalars().all()

    # 마지막 실행
    last = runs[0] if runs else None

    # 도메인별 추적 중인 파일
    files_by_domain = {}
    domain_rows = db.execute(
        select(FileRegistry.domain, func.count(), func.max(FileRegistry.last_processed_at))
        .group_by(FileRegistry.domain)
        .order_by(func.count().desc())
    ).all()

    domain_files = []
    for domain, cnt, last_proc in domain_rows:
        latest = db.execute(
            select(FileRegistry)
            .where(FileRegistry.domain == domain, FileRegistry.is_latest_for_domain == "Y")
            .limit(1)
        ).scalar_one_or_none()
        domain_files.append({
            "domain": domain or "(미매핑)",
            "count": cnt,
            "last_processed": last_proc,
            "latest_file": latest.file_name if latest else None,
            "latest_path": latest.rel_path if latest else None,
            "status": latest.status if latest else None,
            "rows_loaded": latest.rows_loaded if latest else None,
            "last_error": latest.last_error if latest and latest.last_error else None,
        })

    # 마지막 실행의 상세
    last_details = []
    if last:
        last_details = db.execute(
            select(SyncRunDetail)
            .where(SyncRunDetail.run_id == last.id)
            .order_by(SyncRunDetail.id)
        ).scalars().all()

    # 전체 통계
    total_files = db.scalar(select(func.count()).select_from(FileRegistry))
    mapped_files = db.scalar(select(func.count()).select_from(FileRegistry).where(FileRegistry.domain.is_not(None)))

    return templates.TemplateResponse("sync/dashboard.html", {
        "request": request,
        "runs": runs, "last": last, "last_details": last_details,
        "domain_files": domain_files,
        "total_files": total_files, "mapped_files": mapped_files,
    })


def _run_in_background(triggered_by: str):
    """별도 세션으로 sync 실행 (백그라운드 작업)"""
    from sync_core import run_sync
    run_sync(triggered_by=triggered_by, verbose=False)


@router.post("/run")
def run_now(bg: BackgroundTasks):
    """수동 실행 — 백그라운드로 sync 시작, 즉시 리다이렉트"""
    bg.add_task(_run_in_background, "manual_web")
    return RedirectResponse("/sync?started=1", status_code=303)


@router.get("/runs/{run_id}", response_class=HTMLResponse)
def run_detail(run_id: int, request: Request, db: Session = Depends(get_db)):
    run = db.get(SyncRun, run_id)
    if not run:
        return RedirectResponse("/sync", status_code=303)
    details = db.execute(
        select(SyncRunDetail).where(SyncRunDetail.run_id == run_id).order_by(SyncRunDetail.id)
    ).scalars().all()
    return templates.TemplateResponse("sync/run_detail.html", {
        "request": request, "run": run, "details": details,
    })


@router.get("/files", response_class=HTMLResponse)
def files_list(request: Request, db: Session = Depends(get_db),
               domain: str = "", status: str = "", q: str = ""):
    stmt = select(FileRegistry)
    if domain:
        stmt = stmt.where(FileRegistry.domain == domain)
    if status:
        stmt = stmt.where(FileRegistry.status == status)
    if q:
        stmt = stmt.where(FileRegistry.file_name.contains(q))
    files = db.execute(stmt.order_by(FileRegistry.domain.nullslast(), FileRegistry.mtime.desc().nullslast())).scalars().all()

    domains = sorted(set(d for d in db.execute(select(FileRegistry.domain).distinct()).scalars().all() if d))
    return templates.TemplateResponse("sync/files.html", {
        "request": request, "files": files, "domains": domains,
        "filter": {"domain": domain, "status": status, "q": q},
    })
