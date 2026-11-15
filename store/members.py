"""Organization membership over PostgreSQL (see ``migrations/0005_org_members.sql``).

Not bound to a user, unlike the stores in ``store.postgres``: membership is
the one place where the question is "who is in this organization", so every
query is scoped by ``org_id`` instead. Same connection-provider seam as the
other Postgres stores.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

import psycopg

from core.errors import StorageError

from .postgres import ConnectionProvider, DEFAULT_SCHEMA, _open_connection


@dataclass(frozen=True)
class Member:
    org_id: str
    user_id: str
    role: str
    display_name: str | None
    email: str | None
    last_seen: datetime


class PostgresMemberStore:
    def __init__(self, connect: ConnectionProvider, schema: str = DEFAULT_SCHEMA) -> None:
        self._connect_fn = connect
        self._schema = schema

    @classmethod
    def from_dsn(cls, dsn: str, schema: str = DEFAULT_SCHEMA) -> "PostgresMemberStore":
        return cls(lambda: psycopg.connect(dsn), schema=schema)

    def upsert(
        self,
        org_id: str,
        user_id: str,
        role: str,
        seen_at: datetime,
        display_name: str | None = None,
        email: str | None = None,
    ) -> None:
        """Records a sighting. A missing name or email never erases a known one."""
        try:
            with _open_connection(self._connect_fn) as conn:
                conn.execute(
                    f"""
                    INSERT INTO {self._schema}.org_members
                        (org_id, user_id, role, display_name, email, last_seen)
                    VALUES (%s, %s, %s, %s, %s, %s)
                    ON CONFLICT (org_id, user_id) DO UPDATE SET
                        role = EXCLUDED.role,
                        display_name = COALESCE(EXCLUDED.display_name, {self._schema}.org_members.display_name),
                        email = COALESCE(EXCLUDED.email, {self._schema}.org_members.email),
                        last_seen = EXCLUDED.last_seen
                    """,
                    (org_id, user_id, role, display_name, email, seen_at),
                )
        except psycopg.Error as exc:
            raise StorageError(f"no se pudo guardar el miembro: {exc}") from exc

    def list_members(self, org_id: str) -> list[Member]:
        """Members of one organization, sorted by user id."""
        try:
            with _open_connection(self._connect_fn) as conn:
                rows = conn.execute(
                    f"""SELECT org_id, user_id, role, display_name, email, last_seen
                        FROM {self._schema}.org_members
                        WHERE org_id = %s ORDER BY user_id""",
                    (org_id,),
                ).fetchall()
        except psycopg.Error as exc:
            raise StorageError(f"no se pudo listar los miembros: {exc}") from exc
        return [Member(*row) for row in rows]


__all__ = ["Member", "PostgresMemberStore"]
