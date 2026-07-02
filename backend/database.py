import os

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from backend.models import Base

DATABASE_URL = os.getenv(
    "DATABASE_URL",
    "postgresql://varaprasad_admin:SecretAuditPassword2026@localhost:5432/freshaudit_master",
)

engine = create_engine(
    DATABASE_URL,
    pool_pre_ping=True,
    pool_size=10,
    max_overflow=20,
)

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


def init_db():
    Base.metadata.create_all(bind=engine)


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
