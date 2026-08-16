"""Domain errors shared across modules."""

from __future__ import annotations


class PanduError(Exception):
    """Base class for all domain errors."""


class NotFoundError(PanduError):
    """A referenced aggregate does not exist."""


class InvalidInputError(PanduError):
    """Input violates a domain invariant (size, shape, or bounds)."""


class ProviderError(PanduError):
    """A vendor call failed. ``retryable`` guides the fallback chain."""

    def __init__(self, message: str, *, provider: str, model: str, retryable: bool = True) -> None:
        super().__init__(message)
        self.provider = provider
        self.model = model
        self.retryable = retryable


class AllProvidersFailedError(PanduError):
    """Primary and every fallback provider failed for one logical call."""

    def __init__(self, errors: list[ProviderError]) -> None:
        detail = "; ".join(f"{e.provider}/{e.model}: {e}" for e in errors)
        super().__init__(f"all providers failed: {detail}")
        self.errors = errors
