# Project record

## Objective

Run LLM-generated Python snippets in a separate isolated interpreter with an AST import policy, timeout, output caps, scrubbed environment and POSIX resource limits.

## Scope

- In scope: The public API, typed and tested execution of Python code.
- Out of scope: Package installation, notebooks, persistent sessions, file uploads, Docker integration.

## Timeline

| Date | Event |
|---|---|
| 2026 | Repository created from the factory utility template. |

## Effort metrics

| Metric | Value |
|---|---|
| Tokens (input / output) | 2690276 / 21891 |
| Hours (human) | pending measurement |
| Cost (USD) | 0.4914 |

## Factory run u161 (measured from API usage)

| Phase | Model | Batch | Input | Output | Cache write | Cache read | Cost (USD) |
|---|---|---|---|---|---|---|---|
| generation | gemini-3.8-flash | yes | 4577 | 9516 | 0 | 0 | 0.0196 |
| fix-1 | gemini-3.8-flash | no | 69919 | 2762 | 0 | 466681 | 0.0978 |
| fix-2 | gemini-3.8-flash | no | 88843 | 3171 | 0 | 704160 | 0.1313 |
| fix-3 | gemini-3.8-flash | no | 73933 | 2346 | 0 | 596260 | 0.1090 |
| fix-4 | gemini-3.8-flash | no | 55724 | 2759 | 0 | 346141 | 0.0781 |
| audit | gemini-3.1-flash-lite | no | 40994 | 157 | 0 | 77429 | 0.0124 |
| docs | gemini-3.1-flash-lite | no | 165615 | 1180 | 0 | 0 | 0.0432 |

Total: $0.4914. Prices: Anthropic list prices.
