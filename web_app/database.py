# -*- coding: utf-8 -*-
"""DB 엔진·세션·디펜던시"""
import os
from pathlib import Path
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, Session
from models import Base

ROOT = Path(__file__).parent
# 배포 시 INVIZ_DB_PATH 로 DB 위치를 볼륨에 지정(데이터 영속화). 미지정 시 web_app/app.db
DB_PATH = Path(os.environ.get("INVIZ_DB_PATH") or (ROOT / "app.db"))
try:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
except Exception:
    pass
DATABASE_URL = f"sqlite:///{DB_PATH}"

engine = create_engine(
    DATABASE_URL,
    connect_args={"check_same_thread": False},
    echo=False,
)

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


def init_db():
    """테이블 생성 (멱등)"""
    Base.metadata.create_all(bind=engine)


def get_db():
    """FastAPI 디펜던시"""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
