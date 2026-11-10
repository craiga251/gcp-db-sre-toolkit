"""Smoke-test a Cloud SQL for SQL Server instance through the Cloud SQL Python Connector.

The instance has a public IP but no authorized networks, so a direct TCP
connection is refused. The connector authenticates with IAM (Application
Default Credentials), fetches an ephemeral client certificate from the Cloud
SQL Admin API, and opens an encrypted tunnel. Proving this works proves the
access model, not just that the instance is up.

The instance also enforces encryption at the TDS layer (ssl_mode =
ENCRYPTED_ONLY), so the client must negotiate TLS inside the connector tunnel,
the same as ODBC Driver 18 / SSMS with Encrypt=Mandatory. The server CA cert is
fetched from the Cloud SQL Admin API. Host name validation is off because the
connection goes to a local tunnel endpoint, not the instance's host name.

The sqlserver admin password is read from Secret Manager, never typed or
stored locally.

Usage (from the repo root, values from `terraform output`):
    python scripts/python/verify_connection.py \
        --connection-name <project:region:instance> \
        --secret-id <secret id> \
        --database sredb
"""

from __future__ import annotations

import argparse
import os
import sys
import tempfile

import google.auth
from google.auth.transport.requests import AuthorizedSession
from google.cloud import secretmanager
from google.cloud.sql.connector import Connector

CHECKS = {
    "server": "SELECT @@SERVERNAME",
    "version": "SELECT CAST(SERVERPROPERTY('ProductVersion') AS nvarchar(64))",
    "edition": "SELECT CAST(SERVERPROPERTY('Edition') AS nvarchar(128))",
    "current_database": "SELECT DB_NAME()",
    "encrypted_connection": (
        "SELECT encrypt_option FROM sys.dm_exec_connections WHERE session_id = @@SPID"
    ),
    "user_databases": (
        "SELECT STRING_AGG(name, ', ') FROM sys.databases WHERE database_id > 4"
    ),
}


def get_secret(project_id: str, secret_id: str) -> str:
    client = secretmanager.SecretManagerServiceClient()
    name = f"projects/{project_id}/secrets/{secret_id}/versions/latest"
    return client.access_secret_version(name=name).payload.data.decode("utf-8")


def get_server_ca(connection_name: str) -> str:
    """Download the instance's server CA cert to a temp file and return its path."""
    project, _, instance = connection_name.split(":")
    creds, _ = google.auth.default(scopes=["https://www.googleapis.com/auth/sqlservice.admin"])
    url = f"https://sqladmin.googleapis.com/v1/projects/{project}/instances/{instance}"
    resp = AuthorizedSession(creds).get(url)
    resp.raise_for_status()
    fd, path = tempfile.mkstemp(suffix=".pem")
    with os.fdopen(fd, "w") as f:
        f.write(resp.json()["serverCaCert"]["cert"])
    return path


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--connection-name", required=True, help="project:region:instance")
    parser.add_argument("--secret-id", required=True, help="Secret Manager secret holding the admin password")
    parser.add_argument("--database", default="sredb")
    parser.add_argument("--user", default="sqlserver")
    args = parser.parse_args()

    project_id = args.connection_name.split(":")[0]
    _, adc_project = google.auth.default()
    print(f"ADC quota project: {adc_project}  |  target project: {project_id}")

    password = get_secret(project_id, args.secret_id)
    cafile = get_server_ca(args.connection_name)

    with Connector() as connector:
        conn = connector.connect(
            args.connection_name,
            "pytds",
            user=args.user,
            password=password,
            db=args.database,
            cafile=cafile,
            validate_host=False,
        )
        try:
            cur = conn.cursor()
            for label, sql in CHECKS.items():
                cur.execute(sql)
                print(f"{label:>22}: {cur.fetchone()[0]}")
        finally:
            conn.close()
            os.remove(cafile)

    print("OK: connected through the Cloud SQL connector.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
