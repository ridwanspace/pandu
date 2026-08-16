"""Shared kernel — domain layer.

Cross-cutting, framework-free contracts: the LLM / embedding / reranker ports,
value objects (ModelRef, TokenUsage), tracing and cost-metering ports, and
domain errors. Vendor SDKs are implemented against these ports exclusively in
``app.shared.infrastructure.ai`` (CI-enforced by import-linter).
"""
