---
name: inviz-bg-analysis-harness
description: 인비즈 시스템의 모든 백그라운드 분석 작업(폴더 적용·멀티시트·문서스캔)이 공유하는 진행 추적 + 분석 보고서 패턴 골격 (harness)
type: harness
language: python
pattern: thread-pool + memory-dict + polling endpoint + report
---

# 인비즈 백그라운드 분석 하니스

## 골격

```python
import threading as _thr
import uuid as _uuid
import time as _time

# 글로벌 작업 추적 dict (서버 프로세스 메모리)
_JOBS: dict = {}


def start_bg_job(work_fn, *args, **kwargs) -> str:
    """work_fn(job, *args, **kwargs)를 스레드로 시작하고 run_id 반환."""
    run_id = _uuid.uuid4().hex[:12]
    _JOBS[run_id] = {
        "run_id": run_id,
        "started_at": _time.time(),
        "stage": "🚀 초기화",
        "progress": 0,
        "ok": None,
        "finished_at": None,
    }
    t = _thr.Thread(target=work_fn, args=(_JOBS[run_id], *args),
                    kwargs=kwargs, daemon=True)
    t.start()
    return run_id


def get_status(run_id: str) -> dict:
    """폴링용 — 현재 상태 dict 반환 (traceback 제외)."""
    job = _JOBS.get(run_id, {})
    return {k: v for k, v in job.items() if k != "traceback"}


def make_report(run_id: str, label_map: dict, before_key="kpis_before",
                after_key="kpis_after") -> dict:
    """완료된 작업의 전후 KPI 비교 보고서 생성."""
    job = _JOBS.get(run_id, {})
    before = job.get(before_key, {}) or {}
    after = job.get(after_key, {}) or {}
    changes = []
    for k in label_map:
        b, a = before.get(k, 0), after.get(k, 0)
        diff = a - b
        if diff != 0:
            changes.append({
                "key": k, "label": label_map[k],
                "before": b, "after": a, "diff": diff,
                "pct": (diff / b * 100) if b else None,
            })
    return {
        "ok": job.get("ok"),
        "elapsed_s": int(job["finished_at"] - job["started_at"])
                     if job.get("finished_at") else None,
        "changes": changes,
    }
```

## 라우터 패턴 (FastAPI)

```python
@router.post("/<feature>/start")
def start(): 
    run_id = start_bg_job(_run_feature)
    return JSONResponse({"run_id": run_id})

@router.get("/<feature>/status")
def status(run_id: str):
    return JSONResponse(get_status(run_id))

@router.get("/<feature>/report")
def report(run_id: str):
    return JSONResponse(make_report(run_id, FEATURE_LABELS))
```

## 작업 함수 패턴

```python
def _run_feature(job, *args):
    try:
        # 1단계
        job.update(stage="📊 사전 측정", progress=5)
        job["kpis_before"] = capture_snapshot()
        # 2단계
        job.update(stage="🔍 처리", progress=15)
        result = do_heavy_work()
        job.update(progress=80)
        # 3단계
        job.update(stage="📈 사후 측정", progress=95)
        job["kpis_after"] = capture_snapshot()
        # 완료
        job.update(stage="✅ 완료", progress=100, ok=True,
                   finished_at=_time.time())
    except Exception as e:
        import traceback
        job["error"] = f"{type(e).__name__}: {e}"
        job["traceback"] = traceback.format_exc()[:2000]
        job.update(stage="❌ 오류", ok=False, finished_at=_time.time())
```

## UI 측 폴링 (JS)

```javascript
let timer = setInterval(async () => {
  const r = await fetch(`/<feature>/status?run_id=${runId}`);
  const d = await r.json();
  document.getElementById('stage').textContent = d.stage;
  document.getElementById('bar').style.width = (d.progress || 0) + '%';
  if (d.finished_at) {
    clearInterval(timer);
    showReport(runId);
  }
}, 1200);
```

## 적용된 라우터
- `POST /settings/base-folder/start` — 기본 폴더 AI 분석
- `POST /ai-classify/multi-sheet/start` — 멀티시트 자동 처리
- (확장 예정) documents 스캔, payroll 일괄 계산 등

## 디자인 결정
1. **메모리 dict** vs DB 테이블: 작업이 짧고(분 단위) 서버 재시작 시 잃어도 됨 → 메모리 충분
2. **스레드** vs asyncio task: 기존 동기 코드(`sync_core.run_sync`)와 호환 위해 thread
3. **폴링 1.2~3초**: 너무 짧으면 부하, 너무 길면 사용자 답답함

## 관련 자산
- [[inviz-multi-sheet-classifier]] — 이 하니스 위에 동작
- [[inviz-business-context]] — KPI label 매핑에 활용
