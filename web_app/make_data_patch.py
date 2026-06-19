# -*- coding: utf-8 -*-
"""데이터 패치 생성기 — 민감/가변 데이터를 inviz_data_patch.zip 으로 묶는다.

git에는 코드만 올리고, 아래 항목들은 이 패치로 서버에 따로 전달/갱신한다:
  - app.db          (DB: 전체 데이터 + 설정/API키/메일·카카오·텔레그램 비밀 = app_setting)
  - .env            (앱 비밀번호·세션키)
  - certs/          (로컬 HTTPS 인증서; Docker는 Caddy가 처리하므로 선택)
  - vector_store/   (FAISS 벡터 인덱스, RAG)
  - report_templates/ report_snapshots/ doc_uploads/  (업로드 양식·저장본·서류)
  - MASTER/인비즈_경영관리마스터_v1.xlsx  (통합 Excel, --no-master 로 제외)

사용:  python make_data_patch.py            (전체)
       python make_data_patch.py --no-master --no-vectors
적용:  서버에서  python apply_data_patch.py --docker   (또는 옵션 없이 로컬)
"""
import os
import sys
import zipfile
from pathlib import Path
from datetime import datetime

WEB = Path(__file__).resolve().parent           # web_app/
ROOT = WEB.parent                                # 00.경영관리마스터/
LOCALAPPDATA = os.environ.get("LOCALAPPDATA") or str(Path.home() / "AppData" / "Local")
VECTOR_SRC = Path(LOCALAPPDATA) / "Inviz" / "vector_store"

OUT = ROOT / "inviz_data_patch.zip"
no_master = "--no-master" in sys.argv
no_vectors = "--no-vectors" in sys.argv


def add_file(zf, src: Path, arc: str):
    if src.exists() and src.is_file():
        zf.write(src, arc)
        return src.stat().st_size
    return 0


def add_dir(zf, src: Path, arc_prefix: str):
    total = 0
    if not src.exists():
        return 0
    for p in src.rglob("*"):
        if p.is_file():
            rel = p.relative_to(src).as_posix()
            zf.write(p, f"{arc_prefix}/{rel}")
            total += p.stat().st_size
    return total


def human(n):
    for u in ("B", "KB", "MB", "GB"):
        if n < 1024:
            return f"{n:.1f}{u}"
        n /= 1024
    return f"{n:.1f}TB"


def main():
    items = []
    manifest = [f"인비즈 데이터 패치 — 생성 {datetime.now():%Y-%m-%d %H:%M}", ""]
    with zipfile.ZipFile(OUT, "w", zipfile.ZIP_DEFLATED) as zf:
        # 1) DB
        sz = add_file(zf, WEB / "app.db", "app.db")
        items.append(("app.db", sz))
        # 2) .env
        sz = add_file(zf, WEB / ".env", ".env")
        items.append((".env", sz))
        # 3) certs
        sz = add_dir(zf, WEB / "certs", "certs")
        items.append(("certs/", sz))
        # 4) vector_store (FAISS)
        if not no_vectors:
            sz = add_dir(zf, VECTOR_SRC, "vector_store")
            if sz == 0:
                sz = add_dir(zf, WEB / "vector_store", "vector_store")
            items.append(("vector_store/", sz))
        # 5) 업로드/저장본/서류
        for name in ("report_templates", "report_snapshots", "doc_uploads"):
            sz = add_dir(zf, WEB / name, name)
            items.append((f"{name}/", sz))
        # 6) 통합 Excel 마스터
        if not no_master:
            for x in ROOT.glob("인비즈_경영관리마스터*.xlsx"):
                sz = add_file(zf, x, f"MASTER/{x.name}")
                items.append((f"MASTER/{x.name}", sz))
        # MANIFEST
        for label, sz in items:
            manifest.append(f"- {label:28} {human(sz)}")
        manifest.append("")
        manifest.append("적용: python apply_data_patch.py --docker   (또는 옵션 없이 로컬)")
        zf.writestr("MANIFEST.txt", "\n".join(manifest))

    print("\n".join(manifest))
    print(f"\n✅ 생성 완료: {OUT}  ({human(OUT.stat().st_size)})")
    print("⚠️ 이 파일은 민감정보입니다 — git/외부에 올리지 말고 안전한 경로로만 서버에 전달하세요.")


if __name__ == "__main__":
    main()
