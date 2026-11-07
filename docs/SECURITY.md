# Security Policy & Threat Model

`generated-code-sandbox` provides a low-overhead, first-layer defense against runaway or accidental hazards in LLM-generated Python snippets.

## What is Defended

- **Runaway execution loops** (enforced via timeout and process group termination).
- **Output floods filling host memory** (enforced via capped stream reading and process killing).
- **Host environment secret leakage** (scrubbed environment, passing only essential OS vars).
- **Leftover scratch files in the working directory** (isolated temporary directory cleaned in finally).
- **Accidental imports and forbidden builtins outside policy**.

## What is NOT Defended (Non-Guarantees)

- **Deliberate AST-level escapes** (AST inspection is a guardrail, not a secure boundary).
- **Host filesystem access allowed to the running user account**.
- **Direct network access if the host has open network access**.
- **Grandchild processes on Windows**.
- **Virtual memory exhaustion on platforms where RLIMIT_AS is unsupported or advisory (e.g. macOS)**.

For hostile code execution, use containerized isolation, gVisor, MicroVMs, or WASM sandboxes.
