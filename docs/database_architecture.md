# Database Architecture Documentation

## Overview
This document outlines the database architecture, concurrency patterns, and configuration for JobHunterKit. It bridges the gap between the intended architecture and the current production implementation.

## 1. Connection Management & Configuration

### 1.1 Connection String
The database connection string is configured via the `DB_URL` environment variable loaded from the `.env` file at the project root.
- **Native PostgreSQL Format (Primary)**: `postgresql://<user>:<password>@localhost:5432/<database>` (connecting to the native PostgreSQL host and service).
- **Custom / Managed Host**: Supports standard PostgreSQL DSNs for local native installations or configured remote database servers.

### 1.2 Connection Pooling & Lifecycle
- **Client-Side Pooling**: The system uses `psycopg2.pool.ThreadedConnectionPool` for client-side connection pooling. This optimizes performance by reusing connections across parallel worker threads.
  - **Configuration**: Minimum of 2 connections, maximum of 10 connections.
  - **Exhaustion Behavior**: On pool exhaustion, workers block up to 30 seconds waiting for an available connection rather than failing immediately.
  - **Initialization**: The pool is a module-level singleton lazily initialized upon the first call to `get_connection()`.
  - **Connection Wrapper**: Connections returned by `get_connection()` are wrapped in a `PooledConnectionWrapper` to ensure transparent compatibility with the existing public API. When existing code calls `conn.close()`, the wrapper intercepts this, rolls back any pending transaction state to prevent leaks, and returns the connection to the pool (`pool.putconn()`).
- **DNS Resolution Fallback**: `core/db_client.py` implements a custom DNS raw resolution fallback (`_patched_getaddrinfo`) using `8.8.8.8` to gracefully handle `socket.gaierror` when resolving the database host, adding resilience to network hiccups.

## 2. Transaction & Isolation Strategy

### 2.1 Transaction Boundaries
The `with_db_transaction` decorator (in `shared_platform/db.py`) is used to enforce atomic transaction boundaries:
- Injects a `conn` keyword argument into the decorated function.
- Automatically calls `conn.commit()` upon successful execution.
- Automatically calls `conn.rollback()` if an exception occurs.
- Ensures `conn.close()` is always called in the `finally` block to prevent resource leaks.

### 2.2 Isolation Level
The system relies on PostgreSQL's default **Read Committed** isolation level.

## 3. Claim-Based Concurrency (`FOR UPDATE SKIP LOCKED`)

To support multi-worker concurrent processing (such as parallel LLM scoring), the architecture uses a claim-based queueing pattern implemented in `shared_platform/db.py` (`claim_next_job()`).

### 3.1 How it Works
1. Workers query for the next pending job using `SELECT ... FOR UPDATE SKIP LOCKED`.
2. `SKIP LOCKED` ensures that if multiple workers query the table simultaneously, they immediately skip any rows already locked by other transactions, preventing deadlocks and duplicate processing.
3. The selected row is instantly marked with the active status (e.g., `scoring` or `applying`) and a `claimed_at` timestamp.

### 3.2 Stale Claim Recovery
The `claim_next_job()` query incorporates a stale interval recovery mechanism:
- If a job is marked `scoring` but its `claimed_at` timestamp is older than 15 minutes (or 30 minutes for applying), it is considered abandoned (e.g., if a worker crashed).
- The query will re-select it and allow a new worker to claim it.

### 3.3 Usage in Flows
- **Flow 2 (Scoring)**: `scripts/flow_score.py` uses this pattern (`claim_next_scoring_job`) to safely parallelize Job Description evaluations across multiple threads (up to 10 workers).

## 4. Schema Overview

All tables reside within the isolated `job_hunter` schema. 
For the full detailed schema, columns, and mermaid diagrams, please refer to the [Entity Relationship Diagram (ERD)](file:///C:/Users/user/.gemini/antigravity/skills/JobHunterKit/docs/erd.md).

**Core Tables:**
- `jobs`: Root entity for job postings.
- `scores`: LLM evaluation results (`ON DELETE CASCADE` from jobs).
- `applications`: Application history (`ON DELETE CASCADE` from jobs).
- `discovered_channels`: Domain intelligence (`ON DELETE SET NULL` from jobs).
- `pipeline_state`: Singleton daemon control table.
- `report_snapshots`: Telemetry and progress tracking.

## 5. Schema Migration Workflow

1. **Initial Setup**: Defined in `scripts/db_setup.py`, which executes idempotent `CREATE SCHEMA` and `CREATE TABLE IF NOT EXISTS` commands.
2. **Migrations**: Alterations (like adding new columns) are handled via ad-hoc scripts like `scripts/migrate_db.py` which execute `ALTER TABLE` statements safely.
- **Gap Identified**: There is no formalized migration management tool (e.g., Alembic or Flyway). Migrations are currently tracked and executed via standalone Python scripts.

## 6. Database Deployment & Infrastructure

### 6.1 Native PostgreSQL (Primary Production Environment)
The production environment utilizes a **native PostgreSQL** installation running directly as a service on the host system (or dedicated database host).
- **Service Management**: Managed via OS service infrastructure (e.g., Windows Service `postgresql-x64-XX` or Linux `systemd postgresql`).
- **Default Connection**: Listens on `localhost:5432` (or custom host/port defined via `DB_URL` in `.env`).
- **Data Persistence**: Data files are persisted natively on local storage managed directly by PostgreSQL.

### 6.2 Docker Container Setup (Development / Secondary Option)
For development, testing, or CI environments, a helper script `scripts/start_database.ps1` is provided to quickly boot an ephemeral PostgreSQL container.
- **Image**: `postgres:latest`
- **Port Mapping**: `5432:5432`
- **Credentials**: Username `postgres`, Password `postgres_local`
- **Database URL**: `postgresql://postgres:postgres_local@localhost:5432/postgres`
- **Dev Note**: `start_database.ps1` runs a container without volume mounting by default, suitable for testing/dev environments. Production deployments must use native PostgreSQL (or a volume-persisted setup).

## 7. Backup and Restore Procedures

- **Current State**: ⚠️ **Gap Identified**. There are no documented backup or restore scripts in the repository.
- **Recommendation**: Implement `pg_dump` automated scripts and set up a cron job or scheduled task to back up the `job_hunter` schema regularly.

## 8. Error Handling & Recovery

- **Scoring Resilience**: In `scripts/flow_score.py`, if scoring fails, a safe fallback block re-fetches a new DB connection to mark the job as `status_score = 'failed'`, ensuring a broken transaction doesn't leave the job perpetually locked.
- **Worker Resiliency**: The worker loop explicitly tracks consecutive database errors and intelligently backs off and retries to maintain stability.
