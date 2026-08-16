"""Framework-free value objects shared across modules."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class ModelRef:
    """A model identity in ``provider/model`` form, e.g. ``openai/gpt-4o-mini``.

    The provider half selects an adapter in the factory; the model half is passed
    through to the vendor API verbatim.
    """

    provider: str
    name: str

    @classmethod
    def parse(cls, value: str) -> ModelRef:
        provider, sep, name = value.partition("/")
        if not sep or not provider or not name:
            msg = f"model ref must be 'provider/model', got {value!r}"
            raise ValueError(msg)
        return cls(provider=provider.strip().lower(), name=name.strip())

    def __str__(self) -> str:
        return f"{self.provider}/{self.name}"


@dataclass(frozen=True, slots=True)
class TokenUsage:
    """Token counts for one model call. Counts are logged; prompt text never is."""

    prompt_tokens: int = 0
    completion_tokens: int = 0

    @property
    def total_tokens(self) -> int:
        return self.prompt_tokens + self.completion_tokens

    def __add__(self, other: TokenUsage) -> TokenUsage:
        return TokenUsage(
            prompt_tokens=self.prompt_tokens + other.prompt_tokens,
            completion_tokens=self.completion_tokens + other.completion_tokens,
        )
