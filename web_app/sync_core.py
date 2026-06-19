# -*- coding: utf-8 -*-
"""동기화 코어 — 파일 스캔, 변경 감지, 도메인 매핑

설계:
- ROOT (14.경영정보) 폴더를 walk하며 .xlsx/.xls 파일 수집
- 각 파일의 mtime + 크기 + sha256 (필요 시) 비교
- FileRegistry에서 이전 메타와 대조 → 신규/변경/무변경 판정
- 파일명 패턴으로 도메인 매핑 (DOMAIN_MATCHERS)
- 같은 도메인의 여러 파일이 있으면 mtime 최신 1건만 처리 (is_latest_for_domain='Y')
- 처리 결과를 SyncRunDetail에 기록
- 웹 입력 데이터(source_file='web_app')는 절대 건드리지 않음
"""
import os
import re
import sys
import io
import hashlib
import time
import traceback
from pathlib import Path
from datetime import datetime
from typing import Optional, Callable

# Windows 콘솔 UTF-8 강제
if sys.stdout.encoding and sys.stdout.encoding.lower() != "utf-8":
    try:
        sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
        sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8", errors="replace")
    except Exception:
        pass

from sqlalchemy import select, update
from sqlalchemy.orm import Session

from database import SessionLocal
from models import FileRegistry, SyncRun, SyncRunDetail

ROOT = Path(r"C:\Users\inviz\OneDrive - Inviz (1)\5.Inviz_Corporation\14.경영정보")
SELF_DIR = Path(__file__).parent.parent  # 00.경영관리마스터 — 자기 자신 폴더는 스캔에서 제외

EXCLUDE_DIRS = {
    SELF_DIR.name,  # "00.경영관리마스터"
    ".git", "__pycache__", "node_modules", "db_backup",
}
EXCLUDE_PATTERNS = [
    re.compile(r"^~\$"),      # Excel 임시 파일
    re.compile(r"^\.~lock"),  # LibreOffice 잠금 파일
]
EXTENSIONS = {".xlsx", ".xls", ".xlsm"}

# ---------- 도메인 매핑 룰 ----------
# (정규식 패턴, 도메인 ID, 설명)
# 우선순위가 높은 패턴(구체적인)부터 위에 배치
DOMAIN_MATCHERS = [
    (re.compile(r"외상매출금.*\.xlsx?$", re.IGNORECASE), "sale_ar", "외상매출금"),
    (re.compile(r"외상매입금.*\.xlsx?$", re.IGNORECASE), "purchase_ap", "외상매입금"),
    (re.compile(r"^매출분류.*\.xlsx?$", re.IGNORECASE), "sale_classification", "매출분류"),
    (re.compile(r"거래처별매입매출세금계산서.*\.xlsx?$", re.IGNORECASE), "sale_purchase_invoice", "거래처별 세금계산서"),
    (re.compile(r"단기차입금.*임원.*급여.*미지급.*\.xlsx?$", re.IGNORECASE), "loan_movement", "단기차입금/임원"),
    (re.compile(r"주요계정명세서.*\.xlsx?$", re.IGNORECASE), "loan_master_long", "주요계정명세서"),
    (re.compile(r"퇴직연금.*월별.*\.xlsx?$", re.IGNORECASE), "severance", "퇴직연금"),
    (re.compile(r"_계약관리.*\.xlsx?$"), "contract", "계약관리"),
    (re.compile(r"미수금 현황.*\.xlsx?$"), "receivable", "미수금 현황"),
    (re.compile(r"부서별 인건비.*\.xlsx?$"), "payroll_dept", "부서별 인건비"),
    (re.compile(r"급여대장.*\.xlsx?$"), "payroll_ledger", "급여대장"),
    (re.compile(r"월별 비용정리.*\.xlsx?$"), "expense_monthly", "월별 비용"),
    (re.compile(r"관리비.*렌탈.*\.xlsx?$"), "rental", "관리비/렌탈"),
    (re.compile(r"^5\) 판독수수료.*\.xlsx?$"), "reading_fee", "판독수수료"),
]


def sha256_of_file(path: Path, chunk_size: int = 65536) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        while True:
            data = f.read(chunk_size)
            if not data:
                break
            h.update(data)
    return h.hexdigest()


def match_domain(file_name: str) -> tuple[Optional[str], Optional[str]]:
    """파일명 → (도메인ID, 패턴 설명) 매핑"""
    for pattern, domain, desc in DOMAIN_MATCHERS:
        if pattern.search(file_name):
            return domain, desc
    return None, None


def _resolve_scan_config():
    """설정(자가발전/AI 학습)에서 스캔 루트·하위폴더 포함·공유 경로를 읽는다."""
    root = ROOT
    recurse = True
    extra = []
    try:
        import settings_store as ss
        # 기본 데이터 폴더(최우선) → 학습 폴더 → 기본 ROOT
        bf = (ss.get("base_data_folder", "") or "").strip()
        lf = (ss.get("learning_folder", "") or "").strip()
        if bf and Path(bf).exists():
            root = Path(bf)
        elif lf and Path(lf).exists():
            root = Path(lf)
        recurse = ss.get("learning_include_subfolders", "1") != "0"
        for p in ss.selfdev_path_list():
            pp = Path(p)
            if pp.exists():
                extra.append(pp)
    except Exception:
        pass
    return root, recurse, extra


def _scan_root(root: Path, recurse: bool, results: list, seen: set):
    """단일 루트 스캔(재귀 옵션). 결과를 results에 누적, 중복은 seen으로 방지."""
    if root.is_file():
        roots_iter = [(str(root.parent), [], [root.name])]
    elif recurse:
        roots_iter = os.walk(root)
    else:
        try:
            names = [n for n in os.listdir(root) if (Path(root) / n).is_file()]
        except OSError:
            names = []
        roots_iter = [(str(root), [], names)]
    base = root if root.is_dir() else root.parent
    for dirpath, dirnames, filenames in roots_iter:
        dirnames[:] = [d for d in dirnames if d not in EXCLUDE_DIRS]
        for name in filenames:
            ext = os.path.splitext(name)[1].lower()
            if ext not in EXTENSIONS:
                continue
            if any(p.match(name) for p in EXCLUDE_PATTERNS):
                continue
            full = Path(dirpath) / name
            key = str(full)
            if key in seen:
                continue
            try:
                stat = full.stat()
            except OSError:
                continue
            seen.add(key)
            try:
                rel = str(full.relative_to(base))
            except ValueError:
                rel = name
            results.append({
                "path": str(full),
                "rel_path": rel,
                "file_name": name,
                "size_bytes": stat.st_size,
                "mtime": datetime.fromtimestamp(stat.st_mtime),
            })


def scan_folder(root: Path = None) -> list[dict]:
    """폴더 스캔 → 파일 메타 목록.
    설정(AI 학습)의 학습 대상 폴더·하위폴더 포함 여부·자가발전 공유 경로를 반영한다.
    root를 명시하면 해당 폴더만(재귀) 스캔."""
    results, seen = [], set()
    if root is not None:
        _scan_root(root, True, results, seen)
        return results
    scan_root, recurse, extra = _resolve_scan_config()
    _scan_root(scan_root, recurse, results, seen)
    for ep in extra:
        _scan_root(ep, recurse, results, seen)
    return results


def detect_changes(db: Session, scanned: list[dict], compute_hash: bool = True) -> dict:
    """스캔 결과를 FileRegistry와 대조 → 신규/변경/무변경 분류"""
    # 기존 registry 한 번에 로드
    existing = {row.path: row for row in db.execute(select(FileRegistry)).scalars().all()}

    result = {"new": [], "changed": [], "unchanged": [], "scan_results": scanned}

    for s in scanned:
        prev = existing.get(s["path"])
        # 1차 비교 — mtime + size (빠름)
        unchanged_basic = (
            prev is not None
            and prev.mtime == s["mtime"]
            and prev.size_bytes == s["size_bytes"]
        )
        if unchanged_basic:
            result["unchanged"].append({"reg": prev, "scan": s})
            continue

        # 2차 비교 — 해시 (확실)
        if compute_hash:
            try:
                s["sha256"] = sha256_of_file(Path(s["path"]))
            except OSError:
                s["sha256"] = None
            if prev and prev.sha256 == s["sha256"]:
                # mtime만 바뀌고 내용은 동일 — mtime만 업데이트
                prev.mtime = s["mtime"]
                prev.size_bytes = s["size_bytes"]
                prev.last_seen = datetime.utcnow()
                result["unchanged"].append({"reg": prev, "scan": s})
                continue

        # 도메인 매핑
        domain, desc = match_domain(s["file_name"])
        if prev is None:
            # 신규
            reg = FileRegistry(
                path=s["path"], rel_path=s["rel_path"], file_name=s["file_name"],
                size_bytes=s["size_bytes"], mtime=s["mtime"],
                sha256=s.get("sha256"),
                domain=domain, matched_pattern=desc,
                status="new" if domain else "unmapped",
            )
            db.add(reg)
            result["new"].append({"reg": reg, "scan": s})
        else:
            prev.size_bytes = s["size_bytes"]
            prev.mtime = s["mtime"]
            prev.sha256 = s.get("sha256")
            prev.domain = domain
            prev.matched_pattern = desc
            prev.status = "changed" if domain else "unmapped"
            prev.last_seen = datetime.utcnow()
            result["changed"].append({"reg": prev, "scan": s})

    db.commit()
    return result


def pick_latest_per_domain(db: Session, domains_to_process: set[str]):
    """도메인별로 mtime이 가장 최신인 파일에만 is_latest_for_domain='Y' 표시"""
    for domain in domains_to_process:
        files = db.execute(
            select(FileRegistry)
            .where(FileRegistry.domain == domain)
            .order_by(FileRegistry.mtime.desc().nullslast())
        ).scalars().all()
        for i, f in enumerate(files):
            f.is_latest_for_domain = "Y" if i == 0 else "N"
    db.commit()


def get_latest_files_by_domain(db: Session) -> dict[str, FileRegistry]:
    """현재 도메인별 최신 파일 1개씩 반환"""
    files = db.execute(
        select(FileRegistry).where(FileRegistry.is_latest_for_domain == "Y")
    ).scalars().all()
    return {f.domain: f for f in files}


def run_sync(triggered_by: str = "manual", verbose: bool = False, force: bool = False) -> SyncRun:
    """동기화 실행 (1회) — sync_handlers.HANDLERS의 함수를 호출"""
    from sync_handlers import HANDLERS  # 지연 import로 순환 의존 회피

    db = SessionLocal()
    # 커밋 후에도 반환된 run 객체의 속성을 읽을 수 있도록 만료 비활성화
    # (세션 종료 후 safe_sync 등에서 run.id/status 등 접근 시 detached 오류 방지)
    db.expire_on_commit = False
    run = SyncRun(triggered_by=triggered_by, status="running")
    db.add(run)
    db.commit()
    db.refresh(run)
    if verbose:
        print(f"[Sync #{run.id}] 시작 ({triggered_by})")

    try:
        # 1. 스캔 (설정의 학습 폴더·하위폴더 포함·공유 경로 반영)
        scanned = scan_folder()
        run.files_scanned = len(scanned)
        if verbose:
            print(f"  스캔: {len(scanned)} 파일")

        # 2. 변경 감지
        det = detect_changes(db, scanned, compute_hash=True)
        run.files_changed = len(det["new"]) + len(det["changed"])
        if verbose:
            print(f"  신규 {len(det['new'])} · 변경 {len(det['changed'])} · 무변경 {len(det['unchanged'])}")

        # 3. 처리 대상 도메인 결정 (신규 + 변경된 파일 중 매핑된 것)
        domains_to_process = set()
        for item in det["new"] + det["changed"]:
            if item["reg"].domain:
                domains_to_process.add(item["reg"].domain)

        # force=True이면 모든 매핑된 도메인 재처리
        if force:
            for f in db.execute(select(FileRegistry).where(FileRegistry.domain.is_not(None))).scalars().all():
                domains_to_process.add(f.domain)

        # 4. 도메인별 최신 파일 결정
        pick_latest_per_domain(db, domains_to_process)
        latest = get_latest_files_by_domain(db)

        # 5. 각 도메인 핸들러 실행 (도메인별 최신 1개)
        for domain in sorted(domains_to_process):
            f = latest.get(domain)
            if not f:
                continue
            handler = HANDLERS.get(domain)
            if not handler:
                if verbose:
                    print(f"  [{domain}] 핸들러 없음 — skip")
                db.add(SyncRunDetail(
                    run_id=run.id, file_path=f.path, file_name=f.file_name,
                    domain=domain, action="unmapped",
                    error="no handler",
                ))
                run.files_unmapped += 1
                continue

            t0 = time.time()
            try:
                if verbose:
                    print(f"  [{domain}] {f.file_name} 처리 중...")
                result = handler(db, Path(f.path))
                f.status = "processed"
                f.last_processed_at = datetime.utcnow()
                f.last_error = None
                f.rows_loaded = result.get("rows_added", 0)
                db.add(SyncRunDetail(
                    run_id=run.id, file_path=f.path, file_name=f.file_name,
                    domain=domain, action="processed",
                    rows_added=result.get("rows_added", 0),
                    rows_removed=result.get("rows_removed", 0),
                    duration_ms=int((time.time() - t0) * 1000),
                ))
                run.files_processed += 1
                run.rows_added += result.get("rows_added", 0)
                run.rows_removed += result.get("rows_removed", 0)
                if verbose:
                    print(f"    +{result.get('rows_added', 0)} / -{result.get('rows_removed', 0)} rows  ({int((time.time() - t0) * 1000)}ms)")
                db.commit()
            except Exception as e:
                err_text = f"{type(e).__name__}: {e}\n{traceback.format_exc()}"
                f.status = "error"
                f.last_error = err_text[:2000]
                db.add(SyncRunDetail(
                    run_id=run.id, file_path=f.path, file_name=f.file_name,
                    domain=domain, action="error",
                    error=err_text[:2000],
                    duration_ms=int((time.time() - t0) * 1000),
                ))
                run.files_errored += 1
                db.commit()
                if verbose:
                    print(f"    오류: {e}")

        # 6. 미매핑 파일 기록 (신규만)
        for item in det["new"]:
            if not item["reg"].domain:
                db.add(SyncRunDetail(
                    run_id=run.id, file_path=item["reg"].path, file_name=item["reg"].file_name,
                    domain=None, action="unmapped",
                ))
                run.files_unmapped += 1

        # 7. 무변경 파일은 detail에 안 기록 (양 많아짐) — 통계만

        run.status = "success" if run.files_errored == 0 else "partial"
        run.finished_at = datetime.utcnow()
        run.summary = (
            f"신규 {len(det['new'])} · 변경 {len(det['changed'])} · 처리 {run.files_processed} · "
            f"미매핑 {run.files_unmapped} · 오류 {run.files_errored} · "
            f"+{run.rows_added}/-{run.rows_removed} rows"
        )
        db.commit()
        if verbose:
            print(f"[Sync #{run.id}] 완료: {run.summary}")
        return run

    except Exception as e:
        run.status = "failed"
        run.error = f"{type(e).__name__}: {e}\n{traceback.format_exc()}"[:4000]
        run.finished_at = datetime.utcnow()
        db.commit()
        if verbose:
            print(f"[Sync #{run.id}] 실패: {e}")
        return run
    finally:
        db.close()


if __name__ == "__main__":
    import sys
    triggered = "scheduled" if "--scheduled" in sys.argv else "manual"
    force = "--force" in sys.argv
    run = run_sync(triggered_by=triggered, verbose=True, force=force)
    sys.exit(0 if run.status in ("success", "partial") else 1)
