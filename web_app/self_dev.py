# -*- coding: utf-8 -*-
"""자가 발전 시스템 — 무결성 + 자동 분류 + 변조 감지 + 벡터 자가 갱신

흐름:
  [동기화 시작]
    ↓ 1. DB 자동 백업 (.snapshot)
    ↓ 2. 전 상태 KPI 스냅샷
    ↓ 3. 일반 sync_core 실행
    ↓ 4. 후 상태 KPI 측정
    ↓ 5. 변화량 검증 (의심 임계값 초과 시 자동 롤백)
    ↓ 6. 미매핑 파일 → LLM 분류 시도 → 검토 큐
    ↓ 7. 변경된 데이터 → 벡터 DB 자동 갱신
"""
import json
import shutil
import os
import re
from datetime import datetime
from pathlib import Path
from typing import Optional

import pandas as pd
from sqlalchemy import select, func, update
from sqlalchemy.orm import Session

from database import SessionLocal, DB_PATH
from models import (
    FileRegistry, SyncRun, SyncRunDetail, IntegrityCheck, UnmappedFileReview,
    Sale, Purchase, Contract, Document, LoanMaster, Payroll, Party, Product,
)


# ============ 1. DB 백업·스냅샷 ============
BACKUP_DIR = DB_PATH.parent / "db_backup"


def snapshot_db(prefix: str = "presync") -> Path:
    """현재 DB를 백업 파일로 복사 → 반환 경로"""
    BACKUP_DIR.mkdir(exist_ok=True)
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    dst = BACKUP_DIR / f"{prefix}_{ts}.db"
    shutil.copy2(DB_PATH, dst)
    return dst


def restore_db(snapshot_path: Path) -> bool:
    """스냅샷으로 DB 롤백. 위험! 모든 세션 종료 필요."""
    if not snapshot_path.exists():
        return False
    # 현재 DB도 백업
    failed_backup = BACKUP_DIR / f"rollback_failed_{datetime.now().strftime('%Y%m%d_%H%M%S')}.db"
    try:
        shutil.copy2(DB_PATH, failed_backup)
        shutil.copy2(snapshot_path, DB_PATH)
        return True
    except Exception as e:
        print(f"[restore] error: {e}")
        return False


# ============ 2. KPI 스냅샷 (전후 비교용) ============
METRICS = [
    # (table, metric_name, function)
    ("fact_sale",      "row_count",   lambda db: db.scalar(select(func.count()).select_from(Sale)) or 0),
    ("fact_sale",      "sum_supply",  lambda db: float(db.scalar(select(func.coalesce(func.sum(Sale.supply), 0))) or 0)),
    ("fact_purchase",  "row_count",   lambda db: db.scalar(select(func.count()).select_from(Purchase)) or 0),
    ("fact_purchase",  "sum_supply",  lambda db: float(db.scalar(select(func.coalesce(func.sum(Purchase.supply), 0))) or 0)),
    ("master_contract", "row_count",  lambda db: db.scalar(select(func.count()).select_from(Contract)) or 0),
    ("master_contract", "sum_amount", lambda db: float(db.scalar(select(func.coalesce(func.sum(Contract.contract_amount), 0))) or 0)),
    ("master_loan",    "row_count",   lambda db: db.scalar(select(func.count()).select_from(LoanMaster)) or 0),
    ("master_loan",    "sum_balance", lambda db: float(db.scalar(select(func.coalesce(func.sum(LoanMaster.current_balance), 0))) or 0)),
    ("document",       "row_count",   lambda db: db.scalar(select(func.count()).select_from(Document)) or 0),
    ("dim_party",      "row_count",   lambda db: db.scalar(select(func.count()).select_from(Party)) or 0),
    ("fact_payroll",   "row_count",   lambda db: db.scalar(select(func.count()).select_from(Payroll)) or 0),
]

# 의심 임계값 (절대값 %)
SUSPICION_THRESHOLDS = {
    # 행수가 50% 이상 감소하면 critical (대량 삭제)
    ("fact_sale", "row_count"):       {"warn": 20, "critical": 50},
    ("fact_purchase", "row_count"):   {"warn": 20, "critical": 50},
    ("master_contract", "row_count"): {"warn": 20, "critical": 50},
    ("dim_party", "row_count"):       {"warn": 20, "critical": 50},
    # 합계 변동 — 매출/매입은 새 파일로 갱신되므로 ±30% 까지 정상, 더 크면 의심
    ("fact_sale", "sum_supply"):      {"warn": 30, "critical": 70},
    ("fact_purchase", "sum_supply"):  {"warn": 30, "critical": 70},
    # 차입금 — 대량 변동 의심
    ("master_loan", "sum_balance"):   {"warn": 25, "critical": 60},
}


def capture_kpis(db: Session) -> dict:
    """현재 KPI 스냅샷 측정"""
    out = {}
    for table, metric, fn in METRICS:
        try:
            out[(table, metric)] = fn(db)
        except Exception as e:
            out[(table, metric)] = None
    return out


def evaluate_changes(before: dict, after: dict, run_id: int, db: Session) -> dict:
    """전후 비교 → IntegrityCheck 행 생성, 의심 항목 반환"""
    suspicious = []
    rows_added = []
    for key, before_v in before.items():
        after_v = after.get(key)
        if before_v is None or after_v is None:
            continue
        delta = after_v - before_v
        delta_pct = (delta / before_v * 100) if before_v else (100 if after_v else 0)
        abs_delta_pct = abs(delta_pct)

        threshold = SUSPICION_THRESHOLDS.get(key, {"warn": 30, "critical": 80})
        if abs_delta_pct >= threshold["critical"]:
            status = "critical"
        elif abs_delta_pct >= threshold["warn"]:
            status = "warning"
        else:
            status = "ok"

        ic = IntegrityCheck(
            run_id=run_id, table_name=key[0], metric=key[1],
            before_value=float(before_v), after_value=float(after_v),
            delta=float(delta), delta_pct=float(delta_pct),
            threshold_pct=threshold["critical"], status=status,
            note=f"임계 warn {threshold['warn']}% / critical {threshold['critical']}%",
        )
        db.add(ic)
        rows_added.append(ic)
        if status in ("warning", "critical"):
            suspicious.append({
                "table": key[0], "metric": key[1],
                "before": before_v, "after": after_v,
                "delta_pct": delta_pct, "status": status,
            })
    db.commit()
    return {"suspicious": suspicious, "checks": len(rows_added)}


# ============ 3. LLM 자동 분류 ============
DOMAIN_LIST_PROMPT = """
가능한 도메인 (intent 외 시스템 매핑 ID):
- sale_classification (매출 분류 표 — 거래 명세서 형식)
- sale_ar (외상매출금)
- purchase_ap (외상매입금)
- sale_purchase_invoice (거래처별 세금계산서 합계)
- contract (계약 관리)
- receivable (미수금 현황)
- loan_movement (단기차입금 임원 거래)
- loan_master_long (주요계정명세서/장기차입금)
- payroll_dept (부서별 인건비)
- payroll_ledger (급여대장)
- expense_monthly (월별 비용/판관비)
- rental (임대료/렌탈)
- severance (퇴직연금)
- reading_fee (판독수수료/원격판독)
- document_certificate (인증서/특허/공증/납세증명/사업자등록증)
- unknown (분류 불가)
"""


def llm_classify_file(file_path: Path, model: str = None) -> dict:
    """파일을 읽어 LLM에 도메인 분류 요청. (자기학습 — 오직 오픈소스 Ollama 모델 사용)
    반환: {domain, confidence, reasoning, sheet_summary}
    """
    from chat_engine import ollama_chat
    # 자기학습은 상용 API와 무관하게 항상 오픈소스 학습 모델 사용
    if not model:
        try:
            import settings_store as ss
            model = ss.get("learning_model", "llama3.1:latest")
        except Exception:
            model = "llama3.1:latest"

    # 파일 요약 (시트명 + 헤더 컬럼)
    summary_parts = [f"파일명: {file_path.name}"]
    ext = file_path.suffix.lower()
    sheet_summary = ""

    if ext in (".xlsx", ".xls", ".xlsm"):
        try:
            xl = pd.ExcelFile(file_path)
            summary_parts.append(f"시트 ({len(xl.sheet_names)}개): {', '.join(xl.sheet_names[:8])}")
            # 첫 시트의 헤더 일부
            try:
                df = pd.read_excel(file_path, sheet_name=xl.sheet_names[0], header=None, nrows=5)
                rows_preview = []
                for i in range(min(5, len(df))):
                    cells = [str(df.iloc[i, j])[:20] for j in range(min(8, df.shape[1]))]
                    rows_preview.append(" | ".join(cells))
                summary_parts.append(f"첫 시트 상단 5행:\n" + "\n".join(rows_preview))
            except Exception:
                pass
            sheet_summary = " | ".join(xl.sheet_names[:10])
        except Exception as e:
            summary_parts.append(f"엑셀 읽기 실패: {e}")
    elif ext == ".pdf":
        summary_parts.append("PDF 문서 (인증서·서류 후보 가능)")
        sheet_summary = "PDF"
    elif ext in (".hwp", ".hwpx", ".docx"):
        summary_parts.append("한글/워드 문서 (서류 후보)")
        sheet_summary = ext

    file_summary = "\n".join(summary_parts)

    system = f"""당신은 한국 의료 IT 회사 인비즈의 데이터 분류 도우미입니다.
주어진 파일이 다음 도메인 중 어디에 해당하는지 분류하세요. JSON으로만 답하세요.

{DOMAIN_LIST_PROMPT}

스키마:
{{
  "domain": "위 목록 중 하나",
  "confidence": 0.0 ~ 1.0,
  "reasoning": "왜 그렇게 분류했는지 한 문장 한국어"
}}

신뢰도 가이드:
- 0.9+ : 파일명과 헤더가 매우 명확
- 0.7~0.9: 추론 가능하나 일부 모호
- 0.5~0.7: 비슷한 도메인 여러 후보
- 0.5 이하: 분류 어려움 → unknown
"""
    user = f"이 파일은 어떤 도메인일까요?\n\n{file_summary}"

    try:
        raw = ollama_chat(
            [{"role": "system", "content": system},
             {"role": "user", "content": user}],
            model=model, temperature=0.1, json_mode=True, num_predict=200,
        )
        data = json.loads(raw)
        return {
            "domain": data.get("domain", "unknown"),
            "confidence": float(data.get("confidence", 0)),
            "reasoning": data.get("reasoning", "")[:500],
            "sheet_summary": sheet_summary[:500],
        }
    except Exception as e:
        return {
            "domain": "unknown", "confidence": 0.0,
            "reasoning": f"LLM 호출 실패: {e}",
            "sheet_summary": sheet_summary[:500],
        }


def review_unmapped_files(db: Session, max_files: int = 10,
                          auto_threshold: float = 0.85,
                          model: str = "llama3.1:latest") -> dict:
    """미매핑 파일을 LLM으로 분류 → UnmappedFileReview 큐에 추가.
    신뢰도 ≥ auto_threshold면 file_registry에 도메인 자동 설정 (다음 sync에서 처리).
    """
    unmapped = db.execute(
        select(FileRegistry).where(
            FileRegistry.domain.is_(None),
            FileRegistry.status.in_(["new", "unmapped"]),
        ).limit(max_files)
    ).scalars().all()

    classified = 0
    auto_assigned = 0
    queued = 0

    for f in unmapped:
        # 이미 리뷰 큐에 있으면 스킵 (중복 행 안전)
        existing = db.execute(
            select(UnmappedFileReview).where(UnmappedFileReview.file_path == f.path).limit(1)
        ).scalars().first()
        if existing:
            continue

        path = Path(f.path)
        if not path.exists():
            continue

        result = llm_classify_file(path, model=model)
        classified += 1

        domain = result["domain"]
        conf = result["confidence"]

        review = UnmappedFileReview(
            file_registry_id=f.id, file_path=f.path,
            file_name=f.file_name, rel_path=f.rel_path,
            suggested_domain=domain, confidence=conf,
            llm_reasoning=result["reasoning"],
            sheet_summary=result["sheet_summary"],
            status="pending",
        )

        if conf >= auto_threshold and domain != "unknown":
            # 자동 매핑 (다만 핸들러가 있는 도메인만)
            from sync_handlers import HANDLERS
            if domain in HANDLERS:
                f.domain = domain
                f.matched_pattern = "LLM 자동 분류"
                f.status = "new"
                review.status = "auto_processed"
                auto_assigned += 1
            else:
                # 핸들러 없음 → 큐에 대기 (사람이 핸들러 추가해야 함)
                queued += 1
        else:
            queued += 1

        db.add(review)
    db.commit()
    return {"classified": classified, "auto_assigned": auto_assigned, "queued": queued}


# ============ 4. 벡터 DB 자가 갱신 ============
def auto_reindex_changed(db: Session) -> dict:
    """동기화 후 변경된 데이터에 해당하는 KnowledgeChunk를 재생성·재임베딩"""
    from rag_ingest import run_full_ingest
    try:
        res = run_full_ingest(verbose=False)
        return {"reindexed": res.get("embedded", 0), "errors": res.get("errors", 0)}
    except Exception as e:
        return {"reindexed": 0, "errors": -1, "error_message": str(e)}


# ============ 5. 통합 안전 동기화 ============
def safe_sync(triggered_by: str = "scheduled",
              model: str = "llama3.1:latest",
              auto_rollback_on_critical: bool = True,
              enable_llm_classify: bool = True,
              enable_auto_reindex: bool = True) -> dict:
    """안전 동기화 — 백업 → 사전 KPI → sync → 사후 KPI → 검증 → 자가 학습

    auto_rollback_on_critical: critical 변동 발견 시 자동으로 백업으로 롤백
    """
    from sync_core import run_sync

    log = {"started_at": datetime.now().isoformat(), "triggered_by": triggered_by}

    # 1. DB 스냅샷
    snapshot = snapshot_db(prefix=f"safe_{triggered_by}")
    log["snapshot"] = str(snapshot)
    log["snapshot_size_mb"] = round(snapshot.stat().st_size / (1024*1024), 2)
    print(f"[safe_sync] 스냅샷: {snapshot.name} ({log['snapshot_size_mb']}MB)")

    # 2. 사전 KPI
    db = SessionLocal()
    try:
        before = capture_kpis(db)
        log["kpis_before"] = {f"{t}.{m}": v for (t,m), v in before.items()}
    finally:
        db.close()

    # 3. sync 실행
    run = run_sync(triggered_by=triggered_by)
    log["sync_run_id"] = run.id
    log["sync_status"] = run.status
    log["files_processed"] = run.files_processed
    log["files_errored"] = run.files_errored
    log["rows_added"] = run.rows_added
    log["rows_removed"] = run.rows_removed

    # 4. 사후 KPI + 검증
    db = SessionLocal()
    try:
        after = capture_kpis(db)
        log["kpis_after"] = {f"{t}.{m}": v for (t,m), v in after.items()}

        # IntegrityCheck에 저장
        for ic in db.execute(select(IntegrityCheck).where(IntegrityCheck.run_id == run.id)).scalars().all():
            db.delete(ic)
        db.commit()

        # 새 IntegrityCheck 행들
        for (t, m), bv in before.items():
            av = after.get((t, m))
            if bv is None or av is None:
                continue
            delta = av - bv
            delta_pct = (delta / bv * 100) if bv else (100 if av else 0)
            threshold = SUSPICION_THRESHOLDS.get((t, m), {"warn": 30, "critical": 80})
            apct = abs(delta_pct)
            status = "critical" if apct >= threshold["critical"] else ("warning" if apct >= threshold["warn"] else "ok")
            db.add(IntegrityCheck(
                run_id=run.id, snapshot_path=str(snapshot),
                snapshot_size_bytes=snapshot.stat().st_size,
                table_name=t, metric=m,
                before_value=float(bv), after_value=float(av),
                delta=float(delta), delta_pct=float(delta_pct),
                threshold_pct=threshold["critical"], status=status,
            ))
        db.commit()

        # 의심 항목
        suspicious = db.execute(
            select(IntegrityCheck).where(
                IntegrityCheck.run_id == run.id,
                IntegrityCheck.status.in_(["warning", "critical"]),
            )
        ).scalars().all()
        log["suspicious_count"] = len(suspicious)
        critical = [s for s in suspicious if s.status == "critical"]
        log["critical_count"] = len(critical)

        # 5. 자동 롤백 검토
        if critical and auto_rollback_on_critical:
            print(f"[safe_sync] CRITICAL {len(critical)}건 감지 → 자동 롤백 시도")
            for s in critical:
                s.status = "rolled_back"
                s.note = (s.note or "") + " [자동 롤백]"
            db.commit()
            db.close()
            db = None
            ok = restore_db(snapshot)
            log["rolled_back"] = ok
            if ok:
                log["sync_status"] = "rolled_back"
                print(f"[safe_sync] 롤백 완료. 원본 DB 복구.")
                return log
    finally:
        if db: db.close()

    # 6. LLM 자동 분류 (미매핑 파일)
    if enable_llm_classify:
        db = SessionLocal()
        try:
            cls_result = review_unmapped_files(db, max_files=10, model=model)
            log["llm_classify"] = cls_result
            print(f"[safe_sync] LLM 분류: {cls_result}")
        finally:
            db.close()

    # 7. 벡터 DB 자가 갱신
    if enable_auto_reindex:
        try:
            reindex = auto_reindex_changed(SessionLocal())
            log["reindex"] = reindex
            print(f"[safe_sync] 벡터 재인덱싱: {reindex}")
        except Exception as e:
            log["reindex_error"] = str(e)

    log["finished_at"] = datetime.now().isoformat()
    log["sync_status"] = "success_with_self_dev"
    return log


if __name__ == "__main__":
    import sys
    triggered = "scheduled" if "--scheduled" in sys.argv else "manual"
    result = safe_sync(triggered_by=triggered)
    print(json.dumps(result, indent=2, ensure_ascii=False, default=str))
