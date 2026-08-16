"""Shared value objects: TokenUsage arithmetic."""

from __future__ import annotations

from app.shared.domain.values import TokenUsage


class TestTokenUsage:
    def test_total_is_prompt_plus_completion(self) -> None:
        assert TokenUsage(prompt_tokens=120, completion_tokens=30).total_tokens == 150

    def test_defaults_to_zero(self) -> None:
        assert TokenUsage().total_tokens == 0

    def test_addition_sums_componentwise(self) -> None:
        total = TokenUsage(prompt_tokens=1, completion_tokens=2) + TokenUsage(
            prompt_tokens=10, completion_tokens=20
        )
        assert total == TokenUsage(prompt_tokens=11, completion_tokens=22)
