import os
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, Dict, List, Optional

import bcrypt
import jwt
from fastapi import Depends, FastAPI, Header, HTTPException, Query, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, field_validator
from sqlalchemy.orm import Session

from backend import crud
from backend.database import get_db, init_db
from backend.models import UserRole

app = FastAPI(title="FreshAudit - Enterprise Synchronization Platform", version="2.0")

FRONTEND_DIR = Path(__file__).resolve().parent.parent / "auditor_client"

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

JWT_SECRET = os.getenv("JWT_SECRET", "freshaudit-change-this-in-production")
JWT_ALGORITHM = "HS256"
JWT_EXPIRY_HOURS = int(os.getenv("JWT_EXPIRY_HOURS", "8"))


@app.on_event("startup")
def startup_event():
    init_db()
    db = next(get_db())
    try:
        crud.seed_initial_rbac_directory(db)

        task_exists = (
            db.query(crud.AuditTask)
            .filter(crud.AuditTask.audit_task_id == "TASK-2026-001")
            .first()
        )
        if not task_exists:
            crud.create_audit_task_with_snapshot(
                db,
                "TASK-2026-001",
                "WH-BLR-01",
                [
                    {
                        "item_sku": "SKU-0128",
                        "item_name": "Apples (Fuji)",
                        "shelf_location": "Aisle_B-Bay_12-Shelf_1",
                        "snapshot_quantity": 100,
                    }
                ],
            )
        print("Systems Online. Postgres schemas populated and verified.")
    except Exception as e:
        db.rollback()
        print(f"Startup seeding adjustment: {e}")
    finally:
        db.close()


class UserLoginSchema(BaseModel):
    username: str
    password: str


class UserCreateSchema(BaseModel):
    username: str
    password: str
    role: str
    authorized_warehouses: List[str]

    @field_validator("role")
    @classmethod
    def validate_role(cls, v):
        allowed = {r.value for r in UserRole}
        if v not in allowed:
            raise ValueError(f"Role must be one of: {allowed}")
        return v


class InboundSubmission(BaseModel):
    submission_id: str
    audit_task_id: str
    warehouse_id: str
    shelf_location: str
    item_sku: str
    audited_quantity: int
    submitted_at: str

    @field_validator("audited_quantity")
    @classmethod
    def validate_quantity(cls, v):
        if v < 0:
            raise ValueError("Audited quantity must be non-negative")
        return v


class AuditLogEntry(BaseModel):
    timestamp: str
    user_id: str
    audit_task_id: Optional[str] = None
    action_executed: str
    device_ip: str = "unknown"
    device_metadata: Optional[str] = None


class SyncPayload(BaseModel):
    submissions: List[InboundSubmission]
    logs: List[AuditLogEntry]


class TaskCreate(BaseModel):
    task_id: str
    warehouse_id: str
    items: List[Dict[str, Any]]


class TaskComplete(BaseModel):
    task_id: str


def create_access_token(username: str, role: str, warehouses: List[str]) -> str:
    payload = {
        "sub": username,
        "role": role,
        "warehouses": warehouses,
        "iat": datetime.now(UTC),
        "exp": datetime.now(UTC) + timedelta(hours=JWT_EXPIRY_HOURS),
    }
    return jwt.encode(payload, JWT_SECRET, algorithm=JWT_ALGORITHM)


def decode_access_token(token: str) -> dict:
    try:
        return jwt.decode(token, JWT_SECRET, algorithms=[JWT_ALGORITHM])
    except jwt.ExpiredSignatureError:
        raise HTTPException(status_code=401, detail="Session expired. Please log in again.")
    except jwt.InvalidTokenError:
        raise HTTPException(status_code=401, detail="Invalid access token.")


def verify_access_token(authorization: Optional[str] = Header(None), db: Session = Depends(get_db)):
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(
            status_code=401, detail="Access Token Key Signature missing."
        )

    token = authorization.replace("Bearer ", "")
    payload = decode_access_token(token)

    username = payload.get("sub")
    if not username:
        raise HTTPException(status_code=401, detail="Invalid token payload.")

    user = crud.get_user_by_username(db, username)
    if not user:
        raise HTTPException(status_code=401, detail="User not found in security directory.")

    class AuthenticatedUser:
        username = user.username
        role = user.role
        authorized_warehouses = user.authorized_warehouses

    return AuthenticatedUser()


def get_client_ip(request: Request) -> str:
    forwarded = request.headers.get("X-Forwarded-For")
    if forwarded:
        return forwarded.split(",")[0].strip()
    return request.client.host if request.client else "unknown"


@app.post("/api/v1/auth/login")
def authenticate_operator(payload: UserLoginSchema, request: Request, db: Session = Depends(get_db)):
    user = crud.get_user_by_username(db, payload.username)
    if not user:
        raise HTTPException(
            status_code=401, detail="Authentication Failure: Invalid Access Keys."
        )

    if not bcrypt.checkpw(payload.password.encode(), user.password_hash.encode()):
        raise HTTPException(
            status_code=401, detail="Authentication Failure: Invalid Access Keys."
        )

    token = create_access_token(user.username, user.role, user.authorized_warehouses)

    crud.add_manual_audit_log(
        db,
        user.username,
        "LOGIN",
        None,
        get_client_ip(request),
        None,
    )

    return {
        "access_token": token,
        "token_type": "bearer",
        "username": user.username,
        "role": user.role,
        "authorized_warehouses": user.authorized_warehouses,
    }


@app.get("/api/v1/tasks")
def read_active_tasks(
    warehouse_id: str = Query(...),
    current_user=Depends(verify_access_token),
    db: Session = Depends(get_db),
):
    if warehouse_id not in current_user.authorized_warehouses:
        raise HTTPException(
            status_code=403,
            detail="Isolation Guardrail: Access level mapping restricted.",
        )
    return crud.get_active_tasks_for_warehouse(db, warehouse_id)


@app.post("/api/v1/sync")
def sync_offline_payload(
    payload: SyncPayload,
    request: Request,
    current_user=Depends(verify_access_token),
    db: Session = Depends(get_db),
):
    for sub in payload.submissions:
        if sub.warehouse_id not in current_user.authorized_warehouses:
            raise HTTPException(
                status_code=403,
                detail=f"Isolation Guardrail: Cannot submit counts for warehouse {sub.warehouse_id}.",
            )

    submissions_dict = [sub.model_dump() for sub in payload.submissions]
    logs_dict = [log.model_dump() for log in payload.logs]
    result = crud.process_offline_sync(db, submissions_dict, logs_dict)

    crud.add_manual_audit_log(
        db,
        current_user.username,
        "SYNC_SUBMISSION",
        None,
        get_client_ip(request),
        f"synced={result['synced']},skipped={result['conflicts_skipped']}",
    )

    return {"status": "success", "metrics": result}


@app.post("/api/v1/admin/tasks")
def create_new_task(
    task_data: TaskCreate,
    request: Request,
    current_user=Depends(verify_access_token),
    db: Session = Depends(get_db),
):
    if current_user.role != "CENTRAL_ADMIN":
        raise HTTPException(
            status_code=403, detail="Privilege Failure: Central Admin access required."
        )

    existing = db.query(crud.AuditTask).filter(crud.AuditTask.audit_task_id == task_data.task_id).first()
    if existing:
        raise HTTPException(
            status_code=409, detail=f"Task with ID '{task_data.task_id}' already exists."
        )

    task = crud.create_audit_task_with_snapshot(
        db, task_data.task_id, task_data.warehouse_id, task_data.items
    )

    crud.add_manual_audit_log(
        db,
        current_user.username,
        "CREATE_TASK",
        task_data.task_id,
        get_client_ip(request),
        f"warehouse={task_data.warehouse_id},items={len(task_data.items)}",
    )

    return {"status": "success", "audit_task_id": task.audit_task_id}


@app.post("/api/v1/admin/tasks/complete")
def complete_task(
    payload: TaskComplete,
    request: Request,
    current_user=Depends(verify_access_token),
    db: Session = Depends(get_db),
):
    if current_user.role != "CENTRAL_ADMIN":
        raise HTTPException(
            status_code=403, detail="Privilege Failure: Central Admin access required."
        )

    success = crud.complete_audit_task(db, payload.task_id)
    if not success:
        raise HTTPException(status_code=404, detail="Task not found.")

    crud.add_manual_audit_log(
        db,
        current_user.username,
        "COMPLETE_TASK",
        payload.task_id,
        get_client_ip(request),
        None,
    )

    return {"status": "success", "audit_task_id": payload.task_id}


@app.post("/api/v1/admin/users")
def register_new_operator(
    payload: UserCreateSchema,
    request: Request,
    current_user=Depends(verify_access_token),
    db: Session = Depends(get_db),
):
    if current_user.role != "CENTRAL_ADMIN":
        raise HTTPException(
            status_code=403, detail="Privilege Failure: Central Admin access required."
        )

    existing = crud.get_user_by_username(db, payload.username)
    if existing:
        raise HTTPException(
            status_code=409, detail=f"User '{payload.username}' already exists."
        )

    hashed = bcrypt.hashpw(payload.password.encode(), bcrypt.gensalt()).decode()
    crud.register_system_user(
        db, payload.username, hashed, payload.role, payload.authorized_warehouses
    )

    crud.add_manual_audit_log(
        db,
        current_user.username,
        "CREATE_USER",
        None,
        get_client_ip(request),
        f"new_user={payload.username},role={payload.role}",
    )

    return {"status": "success"}


@app.get("/api/v1/admin/users")
def list_system_directory(
    current_user=Depends(verify_access_token), db: Session = Depends(get_db)
):
    if current_user.role != "CENTRAL_ADMIN":
        raise HTTPException(
            status_code=403, detail="Privilege Failure: Central Admin access required."
        )
    users = crud.get_all_users(db)
    return [
        {"username": u.username, "role": u.role, "authorized_warehouses": u.authorized_warehouses}
        for u in users
    ]


@app.get("/api/v1/admin/master-data")
def get_master_data(
    current_user=Depends(verify_access_token),
    db: Session = Depends(get_db),
):
    return crud.get_master_data(db)


@app.get("/api/v1/admin/variance-report")
def get_variance_metrics(
    current_user=Depends(verify_access_token),
    db: Session = Depends(get_db),
):
    return crud.generate_variance_report(db)


@app.get("/api/v1/admin/audit-trail")
def get_audit_trail(
    current_user=Depends(verify_access_token),
    db: Session = Depends(get_db),
):
    if current_user.role != "CENTRAL_ADMIN":
        raise HTTPException(
            status_code=403, detail="Privilege Failure: Central Admin access required."
        )
    trails = crud.get_all_audit_trails(db)
    return [
        {
            "log_id": t.log_id,
            "timestamp": t.timestamp.isoformat() if t.timestamp else None,
            "user_id": t.user_id,
            "audit_task_id": t.audit_task_id,
            "action_executed": t.action_executed,
            "device_ip": t.device_ip,
            "device_metadata": t.device_metadata,
        }
        for t in trails
    ]


if FRONTEND_DIR.exists():
    app.mount("/static", StaticFiles(directory=str(FRONTEND_DIR)), name="static")

    @app.get("/")
    def serve_frontend():
        return FileResponse(str(FRONTEND_DIR / "index.html"))

    @app.get("/{full_path:path}")
    def serve_frontend_catchall(full_path: str):
        file_path = FRONTEND_DIR / full_path
        if file_path.is_file():
            return FileResponse(str(file_path))
        return FileResponse(str(FRONTEND_DIR / "index.html"))
