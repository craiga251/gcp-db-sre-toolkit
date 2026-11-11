"""Smoke-test a Cloud SQL for SQL Server instance through the Cloud SQL Python Connector.

The instance has a public IP but no authorized networks, so a direct TCP
connection is refused. Proving the connector works proves the access model
(IAM + TLS + TDS encryption), not just that the instance is up. See
cloudsql_conn.py for how the connection is made.

Usage (from the repo root, values from `terraform output`):
    python scripts/python/verify_connection.py \
        --connection-name <project:region:instance> \
        --secret-id <secret id> \
        --database sredb
"""

from __future__ import annotations

import argparse
import sys

from cloudsql_conn import add_connection_args, cloudsql_server

CHECKS = {
    "server": "SELECT @@SERVERNAME",
    "version": "SELECT CAST(SERVERPROPERTY('ProductVersion') AS nvarchar(64))",
    "edition": "SELECT CAST(SERVERPROPERTY('Edition') AS nvarchar(128))",
    "current_database": "SELECT DB_NAME()",
    "encrypted_connection": ("SELECT encrypt_option FROM sys.dm_exec_connections WHERE session_id = @@SPID"),
    "user_databases": ("SELECT STRING_AGG(name, ', ') FROM sys.databases WHERE database_id > 4"),
}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    add_connection_args(parser)
    args = parser.parse_args()

    with cloudsql_server(args.connection_name, args.secret_id, args.database, args.user) as server:
        conn = server.connect()
        try:
            cur = conn.cursor()
            for label, sql in CHECKS.items():
                cur.execute(sql)
                print(f"{label:>22}: {cur.fetchone()[0]}")
        finally:
            conn.close()

    print("OK: connected through the Cloud SQL connector.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
