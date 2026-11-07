# Testing

## Running

```sh
uv run pytest --cov=generated_code_sandbox
```

## Coverage

Branch coverage of `src/generated_code_sandbox` must stay at or above 80 %.

## Existing Tests

- `tests/test_generated_code_sandbox.py`: Covers the full API, verifying policies (imports, forbidden names), syntax errors, execution limits (timeouts, output caps), and result statuses. Exercises the public API `import generated_code_sandbox` and asserts observable outcomes including return values and raised exceptions.
