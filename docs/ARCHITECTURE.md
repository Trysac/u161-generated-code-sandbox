# Architecture

## Overview

`trysac-generated-code-sandbox` isolates the execution of dynamically generated Python snippets.

### Pipeline

1. **Pre-execution AST Check (`check_code`)**:
   - Verifies source code size (`max_source_chars`).
   - Parses code with `ast.parse`.
   - Catches syntax errors.
   - Validates all `ast.Import` and `ast.ImportFrom` nodes against `allowed_imports`.
   - Checks identifier references against `forbidden_names`.
   - Flags attribute access starting and ending with `__` (`dunder_attribute`).
2. **Process Spawn & Environment Isolation**:
   - Writes snippet to `main.py` in an ephemeral temporary directory.
   - Invokes Python in isolated mode: `[python, '-I', '-B', '-X', 'utf8', 'main.py']`.
   - Strips environment variables (scrubbed `env`).
   - Sets POSIX limits via `resource.setrlimit` in `preexec_fn` (`RLIMIT_CPU`, `RLIMIT_AS`, `RLIMIT_FSIZE`, `RLIMIT_NOFILE`).
3. **Capped Stream Consumption**:
   - Reads `stdout` and `stderr` concurrently in worker threads.
   - Capped at `max_output_bytes`.
   - Terminates the process immediately upon exceeding limits.
4. **Cleanup**:
   - Guarantees termination via process group signals (`os.killpg`).
   - Deletes temporary directories in a `finally` block.
