# generated-code-sandbox

Run LLM-generated Python snippets in a separate isolated interpreter with an AST import policy, timeout, output caps, scrubbed environment and POSIX resource limits.

## The Problem

Agents and code-interpreter features execute model-written Python, and running it with `exec` in the host process lets one bad snippet hang the service, fill memory, or read secrets from the environment. This library runs a snippet in a fresh interpreter process with explicit limits and honest guarantees.

## Installation

```bash
pip install generated-code-sandbox
```

## Usage Example

```python
from generated_code_sandbox import run_code, Limits

# Standard execution
result = run_code("print(sum(range(10)))")
print(result.stdout.strip())  # 45

# Execution with custom limits
result = run_code("while True: pass", limits=Limits(timeout_s=0.2))
print(result.status)  # timeout
```

## API Summary

- `run_code(source: str, *, policy=Policy(), limits=Limits(), ...)`: Executes snippet in an isolated subprocess.
- `check_code(source: str, policy=Policy()) -> list[Violation]`: Statically validates code against AST policies.
- `Policy`: Dataclass for configuration (`allowed_imports`, `forbidden_names`, `max_source_chars`).
- `Limits`: Dataclass for resources (`timeout_s`, `max_output_bytes`, `memory_bytes`, `cpu_seconds`, etc.).
- `SandboxError`: Raised for configuration or interpreter errors.

## Why not `exec` with restricted globals?

Why versus `exec` with restricted globals: a separate process with hard limits and no claims of language-level sandboxing. This approach provides a low-overhead, first-layer defense.

## Security

See [docs/SECURITY.md](docs/SECURITY.md) for full threat model details.
