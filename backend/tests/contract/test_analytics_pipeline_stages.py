"""The per-stage pipeline breakdown the analytics chart is drawn from."""

from __future__ import annotations

import inspect

from application.analytics import service

SOURCE = inspect.getsource(service)


class TestStageBreakdown:
    def test_the_dashboard_returns_a_per_stage_breakdown(self) -> None:
        """The chart cannot show stages if the endpoint does not send them."""
        assert '"pipeline_by_stage"' in SOURCE
        assert '"stage": name' in SOURCE
        assert '"amount_minor"' in SOURCE

    def test_lost_stages_are_excluded(self) -> None:
        """A lost column holds no pipeline; including it would make the chart
        total disagree with `pipeline_amount_minor`."""
        assert "Stage.is_lost.is_(False)" in SOURCE

    def test_the_breakdown_respects_the_caller_scope(self) -> None:
        """Joining the scoped deal subquery is what stops a Member seeing the
        whole tenant's pipeline in a chart."""
        index = SOURCE.index("pipeline_by_stage")
        query = SOURCE[SOURCE.index("stage_rows = ") : index]
        assert "deal_scope" in query

    def test_stages_come_back_in_board_order(self) -> None:
        assert "order_by(Stage.position)" in SOURCE
