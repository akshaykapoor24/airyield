"""My Profile: entities keyed by Code and GSTIN, login IDs located by their entity

MY PROFILE → ENTITIES (`user_entities`)

  * STATE IS CANONICALISED. The field was free text ("delhi", "haryana", "new delhi") and is
    now a dropdown of GST states, because a GSTIN's first two characters are checked
    against it. Existing values are mapped onto the same names the dropdown offers via
    app.core.india_tax.canonical_state; a value it cannot place is left untouched rather
    than guessed, and the Edit form asks for it.

  * CODE IS UNIQUE IGNORING CASE. `uq_user_entities_user_code` was on (user_id, code), so
    "TSI" and "tsi" could both be saved. Replaced by a unique index on
    (user_id, lower(code)).

  * GSTIN IS UNIQUE per owner. It is the one identifier that genuinely names ONE
    registration: characters 3-12 are the PAN and the 13th counts registrations of that
    PAN in that state, so a PAN — or a PAN in one state — may legitimately repeat, and a
    name certainly may (a group's entities often share it). Partial index, because rows
    saved before GST was required still carry NULL.

  GST AND PAN ARE MANDATORY FROM NOW ON, but in the API, not as NOT NULL here: rows saved
  before the rule have neither, and refusing to load them would lock their owner out of
  the page that fixes them. The API requires both on every create and on any edit that
  touches state / GST / PAN.

MY PROFILE → LOGIN IDs / IATA (`user_login_ids`)

  * AIRLINE_NAME, AIRLINE_CODE, LOB AND VENDOR_ID ARE DROPPED. A login ID / IATA number now
    belongs to an ENTITY and is located by it; nothing outside My Profile ever read these
    four, and no stored row had any of them set. Downgrade re-adds them, empty.

  * CITY IS ADDED, nullable, and NULL MEANS "THE ENTITY'S CITY". An IATA code is issued to
    an accredited LOCATION, and one entity (one GSTIN, so one state) may run offices in
    several cities of that state — so a login may name its own city. Left NULL it follows
    the entity, so correcting an entity's city corrects every login under it. There is no
    `state` column on purpose: a login's state IS its entity's, because an office in
    another state is another GST registration, i.e. another entity. Stored, it could drift.

  * LOGIN_ID IS UNIQUE per owner, ignoring case, across all of that owner's entities: an
    IATA code belongs to one office of one entity, so a second copy is always a mistake.

PRE-FLIGHT. Each new unique index is preceded by a check that names the offending values,
so a database that already holds duplicates fails with something readable instead of a
bare IntegrityError — and nothing is deduplicated automatically, because choosing which
copy to delete is not a migration's decision.

Revision ID: profile_entity_login_01
Revises: deal_vendor_agency_01
Create Date: 2026-09-18 00:00:00.000000
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

from app.core.india_tax import canonical_state


revision: str = "profile_entity_login_01"
down_revision: Union[str, None] = "deal_vendor_agency_01"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _refuse_duplicates(bind, sql: str, what: str) -> None:
    rows = bind.execute(sa.text(sql)).fetchall()
    if rows:
        listed = "; ".join(f"user {r[0]}: {r[1]!r} x{r[2]}" for r in rows[:20])
        raise RuntimeError(
            f"profile_entity_login_01: duplicate {what} must be resolved before this migration "
            f"can add its unique index — {listed}"
        )


def upgrade() -> None:
    bind = op.get_bind()

    # ── user_entities ────────────────────────────────────────────────────────
    for entity_id, state in bind.execute(sa.text(
        "SELECT id, state FROM user_entities WHERE state IS NOT NULL"
    )).fetchall():
        canon = canonical_state(state)
        if canon and canon != state:
            bind.execute(
                sa.text("UPDATE user_entities SET state = :s WHERE id = :i"),
                {"s": canon, "i": entity_id},
            )

    _refuse_duplicates(bind, """
        SELECT user_id, lower(code), count(*) FROM user_entities
         GROUP BY user_id, lower(code) HAVING count(*) > 1
    """, "entity codes (ignoring case)")
    _refuse_duplicates(bind, """
        SELECT user_id, gst_number, count(*) FROM user_entities
         WHERE gst_number IS NOT NULL
         GROUP BY user_id, gst_number HAVING count(*) > 1
    """, "entity GSTINs")

    op.drop_constraint("uq_user_entities_user_code", "user_entities", type_="unique")
    op.create_index(
        "uq_user_entities_user_code_ci", "user_entities",
        ["user_id", sa.text("lower(code)")], unique=True,
    )
    op.create_index(
        "uq_user_entities_user_gstin", "user_entities",
        ["user_id", "gst_number"], unique=True,
        postgresql_where=sa.text("gst_number IS NOT NULL"),
    )

    # ── user_login_ids ───────────────────────────────────────────────────────
    _refuse_duplicates(bind, """
        SELECT user_id, lower(login_id), count(*) FROM user_login_ids
         GROUP BY user_id, lower(login_id) HAVING count(*) > 1
    """, "login IDs (ignoring case)")

    # Dropping a column takes its index and foreign key with it in Postgres.
    for col in ("airline_name", "airline_code", "lob", "vendor_id"):
        op.drop_column("user_login_ids", col)
    op.add_column("user_login_ids", sa.Column("city", sa.String(length=100), nullable=True))
    op.create_index(
        "uq_user_login_ids_user_login_ci", "user_login_ids",
        ["user_id", sa.text("lower(login_id)")], unique=True,
    )


def downgrade() -> None:
    op.drop_index("uq_user_login_ids_user_login_ci", table_name="user_login_ids")
    op.drop_column("user_login_ids", "city")
    op.add_column("user_login_ids", sa.Column("airline_name", sa.String(length=255), nullable=True))
    op.add_column("user_login_ids", sa.Column("airline_code", sa.String(length=20), nullable=True))
    op.add_column("user_login_ids", sa.Column("lob", sa.String(length=100), nullable=True))
    op.add_column("user_login_ids", sa.Column(
        "vendor_id", sa.Integer(),
        sa.ForeignKey("suppliers.id", ondelete="SET NULL"), nullable=True,
    ))
    op.create_index("ix_user_login_ids_vendor_id", "user_login_ids", ["vendor_id"])

    op.drop_index("uq_user_entities_user_gstin", table_name="user_entities")
    op.drop_index("uq_user_entities_user_code_ci", table_name="user_entities")
    # Canonicalised states are left as they are: "Delhi" is a correct value for the old,
    # free-text column too, and the originals were not kept.
    op.create_unique_constraint("uq_user_entities_user_code", "user_entities", ["user_id", "code"])
