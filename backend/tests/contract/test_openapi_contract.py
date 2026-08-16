"""Property-based contract testing: schemathesis fuzzes every non-LLM endpoint
of the live app and asserts two invariants — no 5xx, and documented response
schemas are honoured.

Excluded operations (they invoke the embedding/chat providers, which are
configured with a dummy key in this suite):
- POST /conversations/{id}/messages  (SSE answer stream -> LLM)
- POST /retrieval/search             (embeds the query)
- POST /evals/run                    (embeds every golden question)
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, cast

import httpx
import pytest
import schemathesis
from hypothesis import HealthCheck, settings
from schemathesis import CheckFunction
from schemathesis.checks import not_a_server_error
from schemathesis.specs.openapi.checks import response_schema_conformance

from tests.contract.conftest import API_KEY

if TYPE_CHECKING:
    from schemathesis.schemas import BaseSchema

_CHECKS = [
    cast("CheckFunction", not_a_server_error),
    cast("CheckFunction", response_schema_conformance),
]

_EXCLUDED = (
    ("POST", "/api/v1/conversations/{conversation_id}/messages"),
    ("POST", "/api/v1/retrieval/search"),
    ("POST", "/api/v1/evals/run"),
)


@pytest.fixture(scope="session")
def api_schema(api_base_url: str) -> BaseSchema:
    return schemathesis.openapi.from_url(f"{api_base_url}/openapi.json")


# Filters must be applied to the lazy schema: its filter set is what
# ``parametrize`` uses, not the one on the fixture-loaded schema.
schema = schemathesis.pytest.from_fixture("api_schema")
for _method, _path in _EXCLUDED:
    schema = schema.exclude(method=_method, path=_path)


@schema.parametrize()
@settings(
    max_examples=25,
    deadline=None,
    suppress_health_check=[HealthCheck.too_slow, HealthCheck.filter_too_much],
)
def test_api_never_500s_and_matches_schema(case: schemathesis.Case[Any]) -> None:
    case.call_and_validate(headers={"X-API-Key": API_KEY}, checks=_CHECKS)


def test_excluded_operations_still_exist(api_schema: BaseSchema, api_base_url: str) -> None:
    """The exclusions above must track the real schema: if an excluded path is
    renamed or removed, this guard fails instead of silently fuzzing nothing."""
    spec = httpx.get(f"{api_base_url}/openapi.json", timeout=30).json()
    for method, path in _EXCLUDED:
        assert method.lower() in spec["paths"][path], (method, path)
