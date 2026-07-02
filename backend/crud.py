from datetime import UTC, datetime
from typing import Any, Dict, List

from sqlalchemy import func
from sqlalchemy.orm import Session

from backend.models import (
    AuditorSubmission,
    AuditSnapshot,
    AuditTask,
    AuditTrail,
    SecurityUser,
    SubmissionStatus,
)


def get_user_by_username(db: Session, username: str) -> SecurityUser:
    return db.query(SecurityUser).filter(SecurityUser.username == username).first()


def get_all_users(db: Session) -> List[SecurityUser]:
    return db.query(SecurityUser).all()


def register_system_user(
    db: Session, username: str, password_hash: str, role: str, warehouses: List[str]
) -> SecurityUser:
    new_user = SecurityUser(
        username=username,
        password_hash=password_hash,
        role=role,
        authorized_warehouses=warehouses,
    )
    db.add(new_user)
    db.commit()
    db.refresh(new_user)
    return new_user


def remove_system_user(db: Session, username: str):
    user = db.query(SecurityUser).filter(SecurityUser.username == username).first()
    if user:
        db.delete(user)
        db.commit()


def get_active_tasks_for_warehouse(
    db: Session, warehouse_id: str
) -> List[Dict[str, Any]]:
    tasks = (
        db.query(AuditTask)
        .filter(
            AuditTask.warehouse_id == warehouse_id,
            AuditTask.status != "COMPLETED",
        )
        .all()
    )
    payload = []
    for t in tasks:
        snapshots = (
            db.query(AuditSnapshot)
            .filter(AuditSnapshot.audit_task_id == t.audit_task_id)
            .all()
        )
        for snap in snapshots:
            already_audited = (
                db.query(AuditorSubmission)
                .filter(
                    AuditorSubmission.audit_task_id == t.audit_task_id,
                    AuditorSubmission.shelf_location == snap.shelf_location,
                    AuditorSubmission.item_sku == snap.item_sku,
                )
                .first()
            )

            if already_audited:
                continue

            payload.append(
                {
                    "id": t.audit_task_id,
                    "warehouseId": t.warehouse_id,
                    "location": snap.shelf_location,
                    "sku": snap.item_sku,
                    "item": snap.item_name,
                }
            )
    return payload


def create_audit_task_with_snapshot(
    db: Session, task_id: str, warehouse_id: str, items: List[Dict[str, Any]]
) -> AuditTask:
    task = AuditTask(
        audit_task_id=task_id, warehouse_id=warehouse_id, status="IN_PROGRESS"
    )
    db.add(task)
    for item in items:
        snapshot = AuditSnapshot(
            audit_task_id=task_id,
            item_sku=item["item_sku"],
            item_name=item["item_name"],
            shelf_location=item["shelf_location"],
            snapshot_quantity=item["snapshot_quantity"],
        )
        db.add(snapshot)
    db.commit()
    db.refresh(task)
    return task


def complete_audit_task(db: Session, task_id: str) -> bool:
    task = db.query(AuditTask).filter(AuditTask.audit_task_id == task_id).first()
    if not task:
        return False
    task.status = "COMPLETED"
    db.commit()
    return True


def process_offline_sync(
    db: Session, submissions: List[Dict[str, Any]], logs: List[Dict[str, Any]]
) -> Dict[str, Any]:
    processed_count = 0
    skipped_count = 0

    for sub_data in submissions:
        exists = (
            db.query(AuditorSubmission)
            .filter(
                AuditorSubmission.audit_task_id == sub_data["audit_task_id"],
                AuditorSubmission.shelf_location == sub_data["shelf_location"],
                AuditorSubmission.item_sku == sub_data["item_sku"],
            )
            .first()
        )

        if exists:
            skipped_count += 1
            continue

        submitted_at = sub_data.get("submitted_at")
        if isinstance(submitted_at, str):
            submitted_at = datetime.fromisoformat(submitted_at.replace("Z", "+00:00"))
        elif submitted_at is None:
            submitted_at = datetime.now(UTC)

        submission = AuditorSubmission(
            submission_id=sub_data["submission_id"],
            audit_task_id=sub_data["audit_task_id"],
            warehouse_id=sub_data["warehouse_id"],
            shelf_location=sub_data["shelf_location"],
            item_sku=sub_data["item_sku"],
            audited_quantity=sub_data["audited_quantity"],
            status=SubmissionStatus.SUBMITTED,
            submitted_at=submitted_at,
        )
        db.add(submission)
        processed_count += 1

    for log_data in logs:
        ts = log_data.get("timestamp")
        if isinstance(ts, str):
            ts = datetime.fromisoformat(ts.replace("Z", "+00:00"))
        elif ts is None:
            ts = datetime.now(UTC)

        trail_entry = AuditTrail(
            timestamp=ts,
            user_id=log_data["user_id"],
            audit_task_id=log_data.get("audit_task_id"),
            action_executed=log_data["action_executed"],
            device_ip=log_data.get("device_ip", "unknown"),
            device_metadata=log_data.get("device_metadata"),
        )
        db.add(trail_entry)

    db.commit()
    return {"synced": processed_count, "conflicts_skipped": skipped_count}


def add_manual_audit_log(
    db: Session, user_id: str, action: str, task_id: str, ip: str, metadata: str
):
    log_entry = AuditTrail(
        user_id=user_id,
        action_executed=action,
        audit_task_id=task_id,
        device_ip=ip,
        device_metadata=metadata,
    )
    db.add(log_entry)
    db.commit()


def generate_variance_report(db: Session) -> List[Dict[str, Any]]:
    results = (
        db.query(AuditSnapshot, AuditTask.warehouse_id)
        .join(AuditTask, AuditSnapshot.audit_task_id == AuditTask.audit_task_id)
        .all()
    )

    report = []
    for snap, warehouse_id in results:
        sub = (
            db.query(AuditorSubmission)
            .filter(
                AuditorSubmission.audit_task_id == snap.audit_task_id,
                AuditorSubmission.shelf_location == snap.shelf_location,
                AuditorSubmission.item_sku == snap.item_sku,
            )
            .first()
        )

        audited_qty = sub.audited_quantity if sub else None
        shrinkage_rate = None
        if audited_qty is not None and snap.snapshot_quantity > 0:
            shrinkage_rate = round(
                ((snap.snapshot_quantity - audited_qty) / snap.snapshot_quantity) * 100,
                2,
            )

        report.append(
            {
                "audit_task_id": snap.audit_task_id,
                "warehouse_id": warehouse_id,
                "item_sku": snap.item_sku,
                "item_name": snap.item_name,
                "shelf_location": snap.shelf_location,
                "snapshot_quantity": snap.snapshot_quantity,
                "audited_quantity": audited_qty,
                "shrinkage_rate": shrinkage_rate,
            }
        )
    return report


def get_all_audit_trails(db: Session) -> List[AuditTrail]:
    return db.query(AuditTrail).order_by(AuditTrail.timestamp.desc()).all()


def get_master_data(db: Session) -> Dict[str, Any]:
    warehouses = (
        db.query(AuditTask.warehouse_id)
        .distinct()
        .all()
    )
    warehouse_list = sorted([w[0] for w in warehouses])

    shelf_locations = (
        db.query(AuditSnapshot.shelf_location)
        .distinct()
        .all()
    )
    shelf_list = sorted([s[0] for s in shelf_locations])

    items_raw = (
        db.query(AuditSnapshot.item_sku, AuditSnapshot.item_name)
        .distinct()
        .all()
    )
    items_list = [{"sku": sku, "name": name} for sku, name in sorted(items_raw, key=lambda x: x[0])]

    return {
        "warehouses": warehouse_list,
        "shelf_locations": shelf_list,
        "items": items_list,
    }


def seed_initial_rbac_directory(db: Session):
    import bcrypt

    if not db.query(SecurityUser).filter(SecurityUser.username == "varaprasad_01").first():
        hashed = bcrypt.hashpw("123".encode(), bcrypt.gensalt()).decode()
        register_system_user(db, "varaprasad_01", hashed, "HUB_AUDITOR", ["WH-BLR-01"])
    if not db.query(SecurityUser).filter(SecurityUser.username == "admin_freshaudit").first():
        hashed = bcrypt.hashpw("admin".encode(), bcrypt.gensalt()).decode()
        register_system_user(
            db, "admin_freshaudit", hashed, "CENTRAL_ADMIN",
            ["WH-BLR-01", "WH-MUM-02", "WH-DEL-03"],
        )
    if not db.query(SecurityUser).filter(SecurityUser.username == "superadmin").first():
        hashed = bcrypt.hashpw("root2026".encode(), bcrypt.gensalt()).decode()
        register_system_user(
            db, "superadmin", hashed, "CENTRAL_ADMIN",
            ["WH-BLR-01", "WH-MUM-02", "WH-DEL-03"],
        )
    if not db.query(SecurityUser).filter(SecurityUser.username == "auditor_mumbai").first():
        hashed = bcrypt.hashpw("123".encode(), bcrypt.gensalt()).decode()
        register_system_user(db, "auditor_mumbai", hashed, "HUB_AUDITOR", ["WH-MUM-02"])
