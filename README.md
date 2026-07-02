# FreshAudit

Inventory Quality & Cycle Counting System — a blind-count audit platform for warehouse operations with real-time variance tracking, role-based access control, and offline-capable sync.

## Tech Stack

| Layer | Technology |
|-------|-----------|
| Backend | Python 3.12, FastAPI, SQLAlchemy 2.0 |
| Database | PostgreSQL 16 |
| Frontend | Vanilla JavaScript, Tailwind CSS |
| Auth | bcrypt password hashing, JWT tokens |
| Deployment | Docker, Docker Compose |

## Features

- **Blind Count Workflow** — 3-step scan process (location → SKU → count) that never reveals expected quantities to the auditor
- **Role-Based Access** — Central Admin (cross-warehouse) and Hub Auditor (warehouse-scoped) roles
- **Real-Time Variance Analytics** — Shrinkage rate computation, overstock detection, CSV export
- **Offline Sync** — Queue submissions locally when offline, auto-sync when connection restores
- **Audit Trail** — Every action (login, scan, submit) logged with timestamp, user, and device metadata
- **Dynamic Master Data** — Warehouse, shelf, and SKU dropdowns populated from existing records with free-text entry for new items
- **Multi-Warehouse Support** — Auditors can switch between assigned warehouses

## Project Structure

```
fresh-audit/
├── backend/
│   ├── main.py          # FastAPI app, auth, all API endpoints
│   ├── models.py        # SQLAlchemy models
│   ├── crud.py          # Database operations
│   └── database.py      # Engine config, session management
├── auditor_client/
│   ├── index.html       # Single-page UI (login, auditor, admin views)
│   └── app.js           # Frontend logic, sync queue, combobox
├── docker-compose.yml   # Production deployment
├── Dockerfile           # Backend + frontend container
├── pyproject.toml       # Python dependencies
└── .env.example         # Environment configuration template
```

## Quick Start

### Option 1: Docker (Recommended)

```bash
# Clone the repository
git clone https://github.com/<your-username>/fresh-audit.git
cd fresh-audit

# Start everything
docker compose up --build

# Open in browser
open http://localhost:8000
```

This starts PostgreSQL and the backend (which also serves the frontend) in containers. The database is seeded automatically on first run.

### Option 2: Local Development

**Prerequisites:** Python 3.12+, PostgreSQL

```bash
# Clone and setup
git clone https://github.com/<your-username>/fresh-audit.git
cd fresh-audit

# Create virtual environment
python3 -m venv .venv
source .venv/bin/activate

# Install dependencies
pip install uv
uv sync

# Start PostgreSQL (using Docker for just the DB)
docker compose up -d postgres_db

# Start the backend
uvicorn backend.main:app --port 8000 --reload

# Open in browser
open http://localhost:8000
```

## Default Credentials

| Username | Password | Role | Warehouses |
|----------|----------|------|------------|
| `superadmin` | `root2026` | CENTRAL_ADMIN | WH-BLR-01, WH-MUM-02, WH-DEL-03 |
| `admin_freshaudit` | `admin` | CENTRAL_ADMIN | WH-BLR-01, WH-MUM-02, WH-DEL-03 |
| `varaprasad_01` | `123` | HUB_AUDITOR | WH-BLR-01 |
| `auditor_mumbai` | `123` | HUB_AUDITOR | WH-MUM-02 |

## API Endpoints

| Method | Endpoint | Auth | Description |
|--------|----------|------|-------------|
| POST | `/api/v1/auth/login` | No | Authenticate and get JWT token |
| GET | `/api/v1/tasks` | Yes | Get pending audit tasks for a warehouse |
| POST | `/api/v1/sync` | Yes | Submit count data and audit logs |
| POST | `/api/v1/admin/tasks` | Admin | Create new audit task with snapshot |
| POST | `/api/v1/admin/tasks/complete` | Admin | Mark task as completed |
| POST | `/api/v1/admin/users` | Admin | Register new user |
| GET | `/api/v1/admin/users` | Admin | List all users |
| GET | `/api/v1/admin/master-data` | Yes | Get warehouses, shelves, items from DB |
| GET | `/api/v1/admin/variance-report` | Yes | Get shrinkage analytics |
| GET | `/api/v1/admin/audit-trail` | Admin | Get full audit trail |

## Environment Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `DATABASE_URL` | `postgresql://...localhost:5432/freshaudit_master` | PostgreSQL connection string |
| `JWT_SECRET` | `freshaudit-change-this-in-production` | Secret key for JWT signing |
| `JWT_EXPIRY_HOURS` | `8` | Token expiry duration |
| `POSTGRES_USER` | `varaprasad_admin` | PostgreSQL username |
| `POSTGRES_PASSWORD` | `SecretAuditPassword2026` | PostgreSQL password |
| `POSTGRES_DB` | `freshaudit_master` | PostgreSQL database name |
| `APP_PORT` | `8000` | Backend port mapping |

## How It Works

1. **Admin** logs in and freezes an inventory snapshot (expected quantities per shelf/SKU)
2. **Auditor** logs in, selects a warehouse, and picks a pending task
3. The **blind count workflow** guides through 3 steps:
   - Scan location barcode
   - Scan item SKU barcode
   - Enter physical count (expected quantity is never shown)
4. Count is submitted and synced to the server
5. **Admin** sees real-time variance report with shrinkage rates
6. Completed tasks are removed from the auditor's task list
