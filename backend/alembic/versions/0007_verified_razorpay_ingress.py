"""Narrow RLS lookup path for verified Razorpay events.

Revision ID: 0007
Revises: 0006
"""

from __future__ import annotations

from alembic import op
from sqlalchemy import text

revision = "0007"
down_revision = "0006"
branch_labels = None
depends_on = None

VERIFIED_CONTEXT = "verified_razorpay_webhook"


def upgrade() -> None:
    conn = op.get_bind()
    conn.execute(
        text(
            """
            DO $$
            BEGIN
              IF NOT EXISTS (
                SELECT 1 FROM pg_constraint
                WHERE conrelid = 'app.payments'::regclass
                  AND conname = 'external_order_unique'
              ) THEN
                ALTER TABLE app.payments
                  ADD CONSTRAINT external_order_unique UNIQUE (external_order_id);
              END IF;
            END
            $$;
            """
        )
    )
    conn.execute(
        text(
            f"""
            DROP POLICY IF EXISTS verified_razorpay_lookup ON app.payments;
            CREATE POLICY verified_razorpay_lookup ON app.payments
              FOR SELECT TO airevenueos_app
              USING (
                current_setting('app.platform_context', true) = '{VERIFIED_CONTEXT}'
              );

            DROP POLICY IF EXISTS verified_razorpay_event_lookup
              ON app.provider_webhook_events;
            CREATE POLICY verified_razorpay_event_lookup
              ON app.provider_webhook_events
              FOR SELECT TO airevenueos_app
              USING (
                current_setting('app.platform_context', true) = '{VERIFIED_CONTEXT}'
              );

            DROP POLICY IF EXISTS verified_razorpay_event_rebind
              ON app.provider_webhook_events;
            CREATE POLICY verified_razorpay_event_rebind
              ON app.provider_webhook_events
              FOR UPDATE TO airevenueos_app
              USING (
                tenant_id IS NULL
                AND current_setting('app.platform_context', true) = '{VERIFIED_CONTEXT}'
              )
              WITH CHECK (
                tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid
                AND current_setting('app.platform_context', true) = '{VERIFIED_CONTEXT}'
              );
            """
        )
    )


def downgrade() -> None:
    conn = op.get_bind()
    conn.execute(
        text(
            """
            DROP POLICY IF EXISTS verified_razorpay_event_rebind
              ON app.provider_webhook_events;
            DROP POLICY IF EXISTS verified_razorpay_event_lookup
              ON app.provider_webhook_events;
            DROP POLICY IF EXISTS verified_razorpay_lookup ON app.payments;
            ALTER TABLE app.payments DROP CONSTRAINT IF EXISTS external_order_unique;
            """
        )
    )
