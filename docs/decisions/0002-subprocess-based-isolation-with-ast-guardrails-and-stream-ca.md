# Subprocess-based isolation with AST guardrails and stream capping

Status: accepted (generated, pending human review)

## Context

Executing LLM-generated Python snippets using in-process exec or eval risks hanging the main application, leaking host secrets, and exhausting memory.

## Decision

Use an isolated subprocess running `python -I` with a scrubbed environment, AST pre-filtering, POSIX resource limits, and chunked stream reading capped at `max_output_bytes`.

## Consequences

Provides reliable timeout enforcement, memory limit guardrails, and secret containment with standard library primitives, while clearly documenting that AST inspection is not an impenetrable sandbox.
