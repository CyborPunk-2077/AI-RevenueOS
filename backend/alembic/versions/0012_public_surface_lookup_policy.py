"""Let the two anonymous surfaces resolve the row that identifies their tenant.

A published lead-capture form and an embedded chat widget are both reached by a
stranger: nobody is signed in, and the only thing naming the tenant is the id or
the public key in the embed snippet. So the first read has to happen before
`app.tenant_id` can be bound - and under the strict tenant policy that read returns
nothing at all. `get_published_form` and the webchat widget lookup therefore
answered "this is not available" for every form and every widget that had ever
been published, including their own. Twelve tests recorded it and it was read as
test drift rather than as the product saying it was broken.

This is the same shape as `0004_auth_lookup_policy`, and it takes the same shape of
fix: a **SELECT-only** second policy, gated on a deliberately bound, logged
`app.platform_context`. PostgreSQL ORs permissive policies, so:

  * with `platform_session()` bound, SELECT succeeds;
  * INSERT, UPDATE and DELETE stay governed solely by the tenant policy, so no
    caller can write across tenants;
  * with no context bound at all, nothing is visible, exactly as before.

It is narrower than 0004 in one further way that matters: the policy only exposes
rows the product has **deliberately put on the public internet** - a form that is
published, a widget that is active. Everything still in draft, unpublished or
switched off stays invisible even under platform context, so the blast radius is
"the rows that are already being served to anonymous visitors".

Revision ID: 0012
Revises: 0011
Create Date: 2026-08-14
"""

from __future__ import annotations

from alembic import op
from sqlalchemy import text

revision = "0012"
down_revision = "0011"
branch_labels = None
depends_on = None

#: (schema, table, the column that means "this row is deliberately public").
PUBLIC_SURFACES: tuple[tuple[str, str, str], ...] = (
    ("app", "forms", "is_published"),
    ("app", "webchat_widgets", "is_active"),
)

POLICY = """
DROP POLICY IF EXISTS public_surface_lookup ON {schema}.{table};
CREATE POLICY public_surface_lookup ON {schema}.{table}
  FOR SELECT
  USING (
    {live} IS TRUE
    AND coalesce(current_setting('app.platform_context', true), '') <> ''
  );
"""


def upgrade() -> None:
    conn = op.get_bind()
    for schema, table, live in PUBLIC_SURFACES:
        conn.execute(text(POLICY.format(schema=schema, table=table, live=live)))


def downgrade() -> None:
    conn = op.get_bind()
    for schema, table, _ in PUBLIC_SURFACES:
        conn.execute(text(f"DROP POLICY IF EXISTS public_surface_lookup ON {schema}.{table}"))
