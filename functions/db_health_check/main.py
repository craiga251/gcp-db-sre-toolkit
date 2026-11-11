"""Scheduled health check for the Cloud SQL for SQL Server instance.

Triggered by Cloud Scheduler over authenticated HTTP. Each run:
  1. connects through the Cloud SQL Python Connector (IAM + TLS, as the
     function's own service account; the instance has no authorized networks),
  2. runs a small set of checks and times each one,
  3. writes ONE structured JSON log line per run to stdout, which Cloud Logging
     ingests as jsonPayload. Phase 4 turns these fields into log-based metrics
     and SLIs (availability = success rate, latency = connect/query time).

Returns 200 when healthy and 503 when any check fails, so Cloud Scheduler's
own job history also shows failures.

Configuration (set by Terraform):
  INSTANCE_CONNECTION_NAME  project:region:instance
  DB_NAME                   database to check
  DB_USER                   SQL login
  DB_PASSWORD               injected from Secret Manager by the platform
"""

from __future__ import annotations

import json
import os
import tempfile
import time

import functions_framework
import google.auth
from google.auth.transport.requests import AuthorizedSession
from google.cloud.sql.connector import Connector

INSTANCE = os.environ["INSTANCE_CONNECTION_NAME"]
DB_NAME = os.environ.get("DB_NAME", "sredb")
DB_USER = os.environ.get("DB_USER", "sqlserver")

# Created once per function instance and reused across warm invocations.
_connector: Connector | None = None
_cafile: str | None = None

CHECKS = {
    # name: (sql, how to interpret the single value returned)
    "select_1": "SELECT 1",
    "edition": "SELECT CAST(SERVERPROPERTY('Edition') AS nvarchar(128))",
    "db_state": "SELECT state_desc FROM sys.databases WHERE name = DB_NAME()",
    "encrypted_connection": (
        "SELECT encrypt_option FROM sys.dm_exec_connections WHERE session_id = @@SPID"
    ),
    "user_sessions": "SELECT COUNT(*) FROM sys.dm_exec_sessions WHERE is_user_process = 1",
    "blocked_requests": "SELECT COUNT(*) FROM sys.dm_exec_requests WHERE blocking_session_id <> 0",
    "db_size_mb": "SELECT CAST(SUM(size) * 8 / 1024.0 AS decimal(10,1)) FROM sys.database_files",
}


def _server_ca() -> str:
    """Instance server CA, needed because the instance enforces TDS encryption."""
    global _cafile
    if _cafile is None:
        project, _, instance = INSTANCE.split(":")
        creds, _ = google.auth.default(scopes=["https://www.googleapis.com/auth/sqlservice.admin"])
        url = f"https://sqladmin.googleapis.com/v1/projects/{project}/instances/{instance}"
        resp = AuthorizedSession(creds).get(url, timeout=10)
        resp.raise_for_status()
        fd, _cafile = tempfile.mkstemp(suffix=".pem")
        with os.fdopen(fd, "w") as f:
            f.write(resp.json()["serverCaCert"]["cert"])
    return _cafile


def _connect():
    global _connector
    if _connector is None:
        _connector = Connector()
    return _connector.connect(
        INSTANCE,
        "pytds",
        user=DB_USER,
        password=os.environ["DB_PASSWORD"],
        db=DB_NAME,
        cafile=_server_ca(),
        validate_host=False,
        autocommit=True,
        login_timeout=15,
        timeout=15,
    )


@functions_framework.http
def health_check(request):
    result = {
        "component": "db-health-check",
        "instance": INSTANCE,
        "database": DB_NAME,
        "success": False,
        "checks": {},
    }
    started = time.perf_counter()
    conn = None
    try:
        t0 = time.perf_counter()
        conn = _connect()
        result["connect_ms"] = round((time.perf_counter() - t0) * 1000, 1)

        cur = conn.cursor()
        for name, sql in CHECKS.items():
            t0 = time.perf_counter()
            cur.execute(sql)
            value = cur.fetchone()[0]
            result["checks"][name] = {
                "value": value if isinstance(value, (int, str, bool)) else str(value),
                "ms": round((time.perf_counter() - t0) * 1000, 1),
            }

        healthy = (
            result["checks"]["db_state"]["value"] == "ONLINE"
            and str(result["checks"]["encrypted_connection"]["value"]).upper() == "TRUE"
        )
        result["success"] = healthy
        if not healthy:
            result["error"] = "database not ONLINE or connection not encrypted"
    except Exception as exc:  # report every failure as a structured log, not a stack trace
        result["error"] = f"{type(exc).__name__}: {exc}"
    finally:
        if conn is not None:
            try:
                conn.close()
            except Exception:
                pass

    result["total_ms"] = round((time.perf_counter() - started) * 1000, 1)
    # Cloud Logging maps "severity" and "message" from a JSON log line.
    result["severity"] = "INFO" if result["success"] else "ERROR"
    result["message"] = (
        f"db-health-check {'OK' if result['success'] else 'FAILED'} "
        f"in {result['total_ms']} ms"
    )
    print(json.dumps(result, default=str), flush=True)

    return (json.dumps(result, default=str), 200 if result["success"] else 503,
            {"Content-Type": "application/json"})
