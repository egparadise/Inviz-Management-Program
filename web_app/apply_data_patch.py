# -*- coding: utf-8 -*-
"""데이터 패치 적용기 — inviz_data_patch.zip 을 제자리에 복원.

  python apply_data_patch.py            # 로컬(Windows/직접 실행) 레이아웃으로 복원
  python apply_data_patch.py --docker   # docker-compose 레이아웃(web_app/data/...)으로 복원
  python apply_data_patch.py --zip /path/inviz_data_patch.zip

로컬:   app.db→web_app/app.db, vector_store→%LOCALAPPDATA%/Inviz/vector_store, .env→web_app/.env ...
Docker: app.db→web_app/data/app.db, vector_store→web_app/data/vector_store, .env→web_app/.env ...
"""
import os
import sys
import zipfile
from pathlib import Path

WEB = Path(__file__).resolve().parent
ROOT = WEB.parent
DOCKER = "--docker" in sys.argv
LOCALAPPDATA = os.environ.get("LOCALAPPDATA") or str(Path.home() / "AppData" / "Local")

zip_path = ROOT / "inviz_data_patch.zip"
if "--zip" in sys.argv:
    zip_path = Path(sys.argv[sys.argv.index("--zip") + 1])
if not zip_path.exists():
    print(f"❌ 패치 파일이 없습니다: {zip_path}")
    sys.exit(1)


def dest_for(arcname: str) -> Path | None:
    """zip 내부 경로 → 복원 위치."""
    data = WEB / "data"
    if arcname == "MANIFEST.txt":
        return None
    if arcname == "app.db":
        return (data / "app.db") if DOCKER else (WEB / "app.db")
    if arcname == ".env":
        return WEB / ".env"
    if arcname.startswith("vector_store/"):
        rel = arcname[len("vector_store/"):]
        base = (data / "vector_store") if DOCKER else (Path(LOCALAPPDATA) / "Inviz" / "vector_store")
        return base / rel
    for d in ("report_templates", "report_snapshots", "doc_uploads", "certs"):
        if arcname.startswith(d + "/"):
            rel = arcname[len(d) + 1:]
            base = (data / d) if DOCKER else (WEB / d)
            return base / rel
    if arcname.startswith("MASTER/"):
        # Docker 런타임엔 불필요 — 로컬에서만 복원
        return None if DOCKER else (ROOT / arcname[len("MASTER/"):])
    return WEB / arcname  # 기타


def main():
    n = 0
    with zipfile.ZipFile(zip_path, "r") as zf:
        for info in zf.infolist():
            if info.is_dir():
                continue
            dest = dest_for(info.filename)
            if dest is None:
                continue
            dest.parent.mkdir(parents=True, exist_ok=True)
            with zf.open(info) as src, open(dest, "wb") as out:
                out.write(src.read())
            n += 1
    print(f"✅ 패치 적용 완료: {n}개 파일 복원 ({'Docker' if DOCKER else '로컬'} 레이아웃)")
    print("   - 서버라면 이제  docker compose up -d --build  후  ./pull_models.sh")


if __name__ == "__main__":
    main()
