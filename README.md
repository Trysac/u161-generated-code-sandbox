# generated-code-sandbox

[![PyPI version](https://img.shields.io/pypi/v/trysac-generated-code-sandbox)](https://pypi.org/project/trysac-generated-code-sandbox/)
[![License: MIT](https://img.shields.io/pypi/l/trysac-generated-code-sandbox)](LICENSE)
[![CI](https://github.com/Trysac/u161-generated-code-sandbox/actions/workflows/ci.yml/badge.svg)](https://github.com/Trysac/u161-generated-code-sandbox/actions/workflows/ci.yml)

Run LLM-generated Python snippets in a separate isolated interpreter with an AST import policy, timeout, output caps, scrubbed environment and POSIX resource limits

## Problem

Describe in two or three sentences the concrete problem this utility solves, who hits it, and what
they do today without it. Replace this paragraph when the first real feature lands.

## Install

```sh
pip install trysac-generated-code-sandbox
# or
uv add trysac-generated-code-sandbox
```

Requires Python 3.10 or newer. No runtime dependencies.

## Usage

```python
import generated_code_sandbox

# normalize() trims surrounding whitespace and lower-cases the text.
print(generated_code_sandbox.normalize("  Hello World "))  # -> "hello world"

# Blank input is rejected explicitly instead of returning an empty string.
try:
    generated_code_sandbox.normalize("   ")
except ValueError as exc:
    print(f"rejected: {exc}")
```

## Documentation

- [Architecture](docs/ARCHITECTURE.md) and [decisions](docs/decisions/)
- [Testing](docs/TESTING.md) and [security](docs/SECURITY.md)
- [Project record](docs/PROJECT.md) and [stack](docs/STACK.md)
- [Changelog](CHANGELOG.md) and [contributing guide](CONTRIBUTING.md)

## License

[MIT](LICENSE) (c) 2026 Miguel Gomez
