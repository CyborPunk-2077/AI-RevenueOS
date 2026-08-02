"""Give each execution node one durable approval request.

Revision ID: 0010
Revises: 0009
"""

from __future__ import annotations

from alembic import op

revision = "0010"
down_revision = "0009"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_unique_constraint(
        "execution_node_approval",
        "workflow_approvals",
        ["execution_id", "node_id"],
        schema="app",
    )


def downgrade() -> None:
    op.drop_constraint(
        "execution_node_approval",
        "workflow_approvals",
        schema="app",
        type_="unique",
    )
