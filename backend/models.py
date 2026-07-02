from datetime import UTC, datetime
from enum import Enum

from sqlalchemy import JSON, Column, DateTime, Integer, String, Text
from sqlalchemy.orm import declarative_base

Base = declarative_base()


class UserRole(str, Enum):
    CENTRAL_ADMIN = "CENTRAL_ADMIN"
    HUB_AUDITOR = "HUB_AUDITOR"


class TaskStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    IN_PROGRESS = "IN_PROGRESS"
    COMPLETED = "COMPLETED"


class SubmissionStatus(str, Enum):
    PENDING_SYNC = "PENDING_SYNC"
    SUBMITTED = "SUBMITTED"


class SecurityUser(Base):
    __tablename__ = "security_users"

    username = Column(String(50), primary_key=True)
    password_hash = Column(String(255), nullable=False)
    role = Column(String(20), default=UserRole.HUB_AUDITOR, nullable=False)
    authorized_warehouses = Column(JSON, nullable=False)


class AuditTask(Base):
    __tablename__ = "audit_tasks"

    audit_task_id = Column(String(50), primary_key=True)
    warehouse_id = Column(String(50), nullable=False)
    status = Column(String(20), default=TaskStatus.SCHEDULED, nullable=False)
    created_at = Column(DateTime, default=lambda: datetime.now(UTC), nullable=False)


class AuditSnapshot(Base):
    __tablename__ = "audit_snapshots"

    snapshot_id = Column(Integer, primary_key=True, autoincrement=True)
    audit_task_id = Column(String(50), nullable=False)
    item_sku = Column(String(50), nullable=False)
    item_name = Column(String(100), nullable=False)
    shelf_location = Column(String(100), nullable=False)
    snapshot_quantity = Column(Integer, nullable=False)


class AuditorSubmission(Base):
    __tablename__ = "auditor_submissions"

    submission_id = Column(String(50), primary_key=True)
    audit_task_id = Column(String(50), nullable=False)
    warehouse_id = Column(String(50), nullable=False)
    shelf_location = Column(String(100), nullable=False)
    item_sku = Column(String(50), nullable=False)
    audited_quantity = Column(Integer, nullable=False)
    status = Column(String(20), default=SubmissionStatus.SUBMITTED, nullable=False)
    submitted_at = Column(DateTime, nullable=False)


class AuditTrail(Base):
    __tablename__ = "audit_trail"

    log_id = Column(Integer, primary_key=True, autoincrement=True)
    timestamp = Column(DateTime, default=lambda: datetime.now(UTC), nullable=False)
    user_id = Column(String(50), nullable=False)
    audit_task_id = Column(String(50), nullable=True)
    action_executed = Column(String(100), nullable=False)
    device_ip = Column(String(45), nullable=False)
    device_metadata = Column(Text, nullable=True)
