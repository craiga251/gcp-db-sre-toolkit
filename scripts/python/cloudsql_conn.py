"""Shared connection helper for Cloud SQL for SQL Server.

Connects through the Cloud SQL Python Connector:
- IAM authenticates the caller (Application Default Credentials) before any
  SQL login, and the connector wraps the session in TLS with a short-lived
  client certificate. The instance has no authorized networks, so this is the
  only way in.
- The instance enforces TDS-level encryption (ssl_mode = ENCRYPTED_ONLY), so
  the client also negotiates TLS inside the tunnel, the same as ODBC Driver 18
  / SSMS with Encrypt=Mandatory. The server CA is fetched from the Cloud SQL
  Admin API. Host name validation is off because the connection goes to a
  local tunnel endpoint, not the instance's host name.
- The sqlserver admin password comes from Secret Manager, never a file.
"""

from __future__ import annotations

import os
import tempfile
from collections.abc import Iterator
from contextlib import contextmanager

import google.auth
from google.auth.transport.requests import AuthorizedSession
from google.cloud import secretmanager
from google.cloud.sql.connector import Connector


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


class CloudSqlServer:
    """Holds one Connector plus the credentials needed to open connections."""

    def __init__(self, connection_name: str, secret_id: str, database: str, user: str = "sqlserver"):
        self.connection_name = connection_name
        self.database = database
        self.user = user
        self._password = get_secret(connection_name.split(":")[0], secret_id)
        self._cafile = get_server_ca(connection_name)
        self._connector = Connector()

    def connect(self, autocommit: bool = True):
        return self._connector.connect(
            self.connection_name,
            "pytds",
            user=self.user,
            password=self._password,
            db=self.database,
            cafile=self._cafile,
            validate_host=False,
            autocommit=autocommit,
        )

    def close(self) -> None:
        self._connector.close()
        if os.path.exists(self._cafile):
            os.remove(self._cafile)


@contextmanager
def cloudsql_server(
    connection_name: str, secret_id: str, database: str, user: str = "sqlserver"
) -> Iterator[CloudSqlServer]:
    server = CloudSqlServer(connection_name, secret_id, database, user)
    try:
        yield server
    finally:
        server.close()


def add_connection_args(parser) -> None:
    """Standard arguments; values come from `terraform output`."""
    parser.add_argument(
        "--connection-name", required=True, help="project:region:instance (terraform output sql_connection_name)"
    )
    parser.add_argument(
        "--secret-id", required=True, help="Secret Manager secret id (terraform output sql_admin_secret_id)"
    )
    parser.add_argument("--database", default="sredb")
    parser.add_argument("--user", default="sqlserver")
