"""PriceTable math, prefix specificity, and the warn-once unknown-model path."""

from __future__ import annotations

from decimal import Decimal

from structlog.testing import capture_logs

from app.shared.domain.values import ModelRef, TokenUsage
from app.shared.infrastructure.ai.pricing import PriceRow, PriceTable


def _ref(provider: str, name: str) -> ModelRef:
    return ModelRef(provider=provider, name=name)


class TestCostMath:
    def test_gpt_4o_mini_prompt_and_completion(self) -> None:
        table = PriceTable()
        cost = table.cost_for(
            _ref("openai", "gpt-4o-mini"),
            TokenUsage(prompt_tokens=1000, completion_tokens=500),
        )
        # 1000 * 0.15/1M + 500 * 0.60/1M
        assert cost == Decimal("0.000450")

    def test_full_million_tokens(self) -> None:
        table = PriceTable()
        cost = table.cost_for(
            _ref("openai", "gpt-4o"),
            TokenUsage(prompt_tokens=1_000_000, completion_tokens=1_000_000),
        )
        assert cost == Decimal("12.50")

    def test_embedding_is_input_only(self) -> None:
        table = PriceTable()
        cost = table.cost_for(
            _ref("openai", "text-embedding-3-small"),
            TokenUsage(prompt_tokens=1_000_000, completion_tokens=999),
        )
        assert cost == Decimal("0.02")

    def test_zero_usage_costs_zero(self) -> None:
        table = PriceTable()
        assert table.cost_for(_ref("deepseek", "deepseek-chat"), TokenUsage()) == Decimal("0")

    def test_result_quantized_to_micro_usd(self) -> None:
        table = PriceTable()
        cost = table.cost_for(_ref("openai", "gpt-4o-mini"), TokenUsage(prompt_tokens=1))
        # 0.15 / 1M = 0.00000015 rounds to 0.000000
        assert cost == Decimal("0.000000")
        assert cost.as_tuple().exponent == -6


class TestPrefixMatching:
    def test_longest_prefix_wins(self) -> None:
        table = PriceTable()
        mini = table.find(_ref("openai", "gpt-4.1-mini-2025-04-14"))
        base = table.find(_ref("openai", "gpt-4.1-2025-04-14"))
        assert mini is not None and mini.model_prefix == "gpt-4.1-mini"
        assert base is not None and base.model_prefix == "gpt-4.1"

    def test_gpt_4o_mini_not_priced_as_gpt_4o(self) -> None:
        row = PriceTable().find(_ref("openai", "gpt-4o-mini"))
        assert row is not None
        assert row.usd_per_1m_prompt == Decimal("0.15")

    def test_provider_must_match(self) -> None:
        assert PriceTable().find(_ref("gemini", "gpt-4o")) is None

    def test_custom_rows(self) -> None:
        table = PriceTable([PriceRow("compat", "llama", Decimal("1"), Decimal("2"))])
        cost = table.cost_for(
            _ref("compat", "llama-3.3-70b"),
            TokenUsage(prompt_tokens=1_000_000, completion_tokens=1_000_000),
        )
        assert cost == Decimal("3")


class TestUnknownModel:
    def test_unknown_model_costs_zero_and_warns_once(self) -> None:
        table = PriceTable()
        usage = TokenUsage(prompt_tokens=100, completion_tokens=100)
        with capture_logs() as logs:
            assert table.cost_for(_ref("openai", "mystery-model"), usage) == Decimal("0")
            assert table.cost_for(_ref("openai", "mystery-model"), usage) == Decimal("0")
        warnings = [entry for entry in logs if entry["log_level"] == "warning"]
        assert len(warnings) == 1
        assert warnings[0]["model"] == "mystery-model"

    def test_each_unknown_model_warns_separately(self) -> None:
        table = PriceTable()
        with capture_logs() as logs:
            table.cost_for(_ref("openai", "mystery-a"), TokenUsage())
            table.cost_for(_ref("openai", "mystery-b"), TokenUsage())
        assert len([e for e in logs if e["log_level"] == "warning"]) == 2
