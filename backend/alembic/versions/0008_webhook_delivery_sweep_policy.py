"""Allow the scheduler to discover due outbound webhook deliveries.

Revision ID: 0008
Revises: 0007
"""

from __future__ import annotations

from alembic import op
from sqlalchemy import text

revision = "0008"
down_revision = "0007"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.get_bind().execute(
        text(
            """
            DROP POLICY IF EXISTS webhook_delivery_sweep
              ON app.outbound_webhook_deliveries;
            CREATE POLICY webhook_delivery_sweep
              ON app.outbound_webhook_deliveries
              FOR SELECT TO airevenueos_app
              USING (
                current_setting('app.platform_context', true) = 'webhook_delivery_sweep'
              );
            """
        )
    )


def downgrade() -> None:
    op.get_bind().execute(
        text("DROP POLICY IF EXISTS webhook_delivery_sweep ON app.outbound_webhook_deliveries")
    )
