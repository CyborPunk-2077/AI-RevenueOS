"""Allow only the scheduler to discover due workflow executions.

Revision ID: 0009
Revises: 0008
"""

from __future__ import annotations

from alembic import op
from sqlalchemy import text

revision = "0009"
down_revision = "0008"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.get_bind().execute(
        text(
            """
            DROP POLICY IF EXISTS workflow_scheduler_select
              ON app.workflow_executions;
            DROP POLICY IF EXISTS workflow_scheduler_update
              ON app.workflow_executions;
            CREATE POLICY workflow_scheduler_select
              ON app.workflow_executions
              FOR SELECT TO airevenueos_app
              USING (
                current_setting('app.platform_context', true) = 'workflow_scheduler'
              );
            CREATE POLICY workflow_scheduler_update
              ON app.workflow_executions
              FOR UPDATE TO airevenueos_app
              USING (
                current_setting('app.platform_context', true) = 'workflow_scheduler'
              )
              WITH CHECK (
                current_setting('app.platform_context', true) = 'workflow_scheduler'
              );
            """
        )
    )


def downgrade() -> None:
    op.get_bind().execute(
        text(
            "DROP POLICY IF EXISTS workflow_scheduler_update "
            "ON app.workflow_executions; "
            "DROP POLICY IF EXISTS workflow_scheduler_select "
            "ON app.workflow_executions"
        )
    )
