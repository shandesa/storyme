# BASE_SPEC.md — Common Contract for All Test Scripts
**Document ID:** `SPEC-BASE-001`
**Version:** 1.0
**Location:** `tests/playground/scripts/BASE_SPEC.md`
**Purpose:** Inherited by every script in `tests/playground/scripts/`. Defines
environment, credentials, logging, cache, retry, exit codes, and dry-run.
Child specs import this by reference — they never duplicate it.

---

## Inheritance Notation

Every child spec opens with a front-matter block:

```
Document ID : SPEC-XYZ-001
Inherits    : BASE_SPEC.md (SPEC-BASE-001)
Overrides   : §BASE-N (section title) — reason
Adds        : §child-N (new section)
```

- Sections inherited without change are **referenced by ID only**.
- Sections that differ carry the tag **`[OVERRIDE]`**.
- Sections unique to the child carry the tag **`[NEW]`**.

---

## BASE §1 — Implementation Philosophy

Applies to **every script** that inherits this spec without exception.

### §1.1 — Simplicity First

- The simplest working solution is always preferred over a clever one.
- No abstractions unless the same logic appears in three or more places.
- No classes unless state genuinely needs to persist across multiple calls.
- Flat procedural flow is preferred: read inputs → validate → run → write outputs.
- If a function exceeds 40 lines, it is doing too much and must be split.

### §1.2 — Logging Is Not Optional

Every code path — success, failure, skip, cache hit, retry, warning — must produce
a log line. The rule is:

> **If something happened, it must be logged. If nothing happened (cache hit,
> skip), it must be logged too.**

A silent script is an undebuggable script. Every log line must answer:
*what happened, on which page, with which model, and why.*

### §1.3 — Fail Loudly, Early, and Clearly

- All validation (args, credentials, file paths, config structure) runs at
  startup before any API call.
- If validation fails, the script prints exactly what is wrong and on which
  input, then exits with code 1.
- Never swallow exceptions silently. Log the full traceback at `ERROR` level,
  then decide whether to continue or abort.
- Never use bare `except:`. Catch the most specific type available, with a
  fallback `except Exception as exc`.

### §1.4 — Comments and Documentation

- Every function has a one-line docstring stating what it does, not how.
- Every non-obvious constant has an inline comment explaining its value.
- Every section of the main flow is separated by a `# ──` banner comment.
- Code is written to be readable by someone unfamiliar with the project.

---

## BASE §2 — Environment

| Item           | Value                                        |
|----------------|----------------------------------------------|
| Python         | 3.11, local venv                             |
| OS target      | Windows (primary), Linux/macOS compatible    |
| Activation Win | `venv\Scripts\activate`                      |
| Activation Unix| `source venv/bin/activate`                   |
| Base packages  | `python-dotenv` (required by all scripts)    |

Additional packages are declared in each child spec.

---

## BASE §3 — Credential File

**File:** `tests/playground/env`
**Format:** `KEY=value` lines, one per line, no surrounding quotes, no inline
comments. Blank lines and `#`-prefixed lines are ignored.

```
OPENAI_API_KEY=sk-proj-...
REPLICATE_API_TOKEN=r8_...
REPLICATE_KEY=r8_...
```

**Loading rules:**

1. File must exist before any import that reads environment variables.
2. Parsed with a custom `_read_env_file()` function (not `load_dotenv`) so the
   script remains self-contained.
3. If the file does not exist: `ERROR` log with full expected path, exit code 1.
4. Each script documents which variable it reads. Never assume a variable name.
5. A variable present but empty (e.g. `REPLICATE_KEY=`) is treated as missing.

**Credential log format** — log at INFO, never log the full value:

```
REPLICATE_KEY : r8_IEPn...bUBX  (from C:\...\tests\playground\env)
```

First 8 chars, ellipsis, last 4 chars.

---

## BASE §4 — Directory Conventions

| Purpose                  | Path                                                        |
|--------------------------|-------------------------------------------------------------|
| Face photo (auto)        | `tests/playground/user_face/<child_name>/<child_name>.png`  |
| Shared Replicate cache   | `tests/playground/cache/replicate/`                         |
| Output root              | `tests/playground/output/<child_name>/`                     |
| Log files                | `tests/playground/output/logs/`                             |

All required directories are created at script start if they do not exist.
Failure to create a required directory is a startup error — log and exit code 1.

---

## BASE §5 — Log File Naming

**Format:** `<YYYYMMDD_HHMMSS>_<script_stem>.log`

`<script_stem>` is resolved at runtime via `Path(__file__).stem`. It is **never
hardcoded** in the script body. This makes every log file uniquely attributable
to its producing script even when many scripts share the same log directory.

**Examples:**
```
20260506_170000_test_replicate_models.log
20260507_090000_test_background_quality.log
20260507_141500_test_replicate_models.log   ← same script, different run
```

**Log levels:**

| Level   | Destination              |
|---------|--------------------------|
| DEBUG   | Log file only            |
| INFO    | Log file + stdout        |
| WARNING | Log file + stdout        |
| ERROR   | Log file + stdout        |

**Log format string:**
```python
"%(asctime)s  %(levelname)-8s  %(name)-32s  %(message)s"
```

**Timestamp format:** `%Y-%m-%d %H:%M:%S`

---

## BASE §6 — Retry and Backoff Policy

Applied to any external API call that may be rate-limited (HTTP 429).

```python
BACKOFF_MAX_RETRIES = 6
BACKOFF_BASE_SECS   = 10    # used when no hint present in error message
BACKOFF_MAX_SECS    = 120   # hard ceiling per sleep
```

**Algorithm:**
```
for attempt in 0 .. MAX_RETRIES-1:
    try:
        result = api_call()
        return result
    except RateLimitError as exc:
        if attempt == MAX_RETRIES - 1:
            log ERROR "max retries exceeded"
            raise
        base = parse_retry_after(exc) or BACKOFF_BASE_SECS
        wait = min(base * (2 ** attempt), BACKOFF_MAX_SECS)
        log WARNING "attempt {K}/{MAX}, backing off {W}s"
        sleep(wait)
    except Exception as exc:
        log ERROR full traceback
        raise   # non-rate-limit errors are never retried
```

`parse_retry_after(exc)` extracts N from strings like `"resets in ~7s"` using
regex `r"resets?\s+in\s+~?(\d+)\s*s"`. Returns `None` if not found.

**Required log lines per retry event:**
```
WARNING — 429 p{N} {model} — attempt {K}/{MAX}, backing off {W:.0f}s
          (hint={hint}s, base={base}s, attempt_multiplier=2^{K-1})
INFO    — p{N} {model} — succeeded on attempt {K} after {total_wait:.0f}s total wait
ERROR   — p{N} {model} — all {MAX} retries exhausted, giving up
```

---

## BASE §7 — Shared Cache Architecture

### §7.1 — Location and Stability

```
tests/playground/cache/replicate/
└── <cache_key>.png
```

This path is **outside every timestamped output directory**. It is stable across
all runs. Multiple runs with identical inputs share one cached file.

### §7.2 — Cache Key Construction

```python
face_hash8   = hashlib.sha256(face_bytes).hexdigest()[:8]
prompt_hash8 = hashlib.sha256(final_prompt.encode()).hexdigest()[:8]
cache_key    = f"{face_hash8}_{prompt_hash8}_{expression}_{model}_{quality}.png"
```

`final_prompt` is the **complete assembled SDXL prompt** after all parts are
merged. Changing any part of the prompt automatically produces a different key
and triggers a new generation.

### §7.3 — Cache Lookup Flow

```
compute cache_key
│
├─ if --force true
│    log INFO  "CACHE BYPASS (force=true) p{N} {model}"
│    → go to API call
│
├─ if cache/<key>.png exists AND size > 0
│    log INFO  "CACHE HIT  p{N} {model} — {key} ({size} KB) — skipping API call"
│    read bytes from cache
│    copy to output folder
│    record in report: from_cache=true, generation_ms=0
│    → return bytes
│
└─ cache MISS
     log DEBUG "CACHE MISS p{N} {model} — {key}"
     → call API (with backoff)
     on success:
       write bytes to cache/<key>.png
       verify file size > 0 (if zero: delete, log ERROR)
       copy to output folder
     on failure:
       log ERROR with full traceback
       do NOT write any partial file to cache
       → return None / raise
```

### §7.4 — Cache Integrity

- After writing, verify file size > 0 bytes. If zero: delete and log `ERROR`.
- Never serve a zero-byte cache file as a result.
- Cache directory created at startup if it does not exist.

---

## BASE §8 — Exit Codes

| Code | Meaning                                                         |
|------|-----------------------------------------------------------------|
| 0    | All operations completed successfully (or dry-run passed)       |
| 1    | Configuration / validation error — nothing was attempted        |
| 2    | Partial success — at least one item failed after all retries    |
| 3    | Total failure — nothing succeeded                               |

---

## BASE §9 — Dry-Run Mode

Activated by `--dry-run` flag. Makes **zero API calls** and **writes no files**.

Dry-run must validate and print:

1. Credential file path and which variables are present (masked)
2. Face photo path and file size
3. Output and cache directory paths (existence status)
4. Full generation plan: per-page, per-model, prompt preview (first 120 chars)
5. Total API call count if no cache hits
6. Estimated cost at $0.02/call (informational, not a contract)

Exit code 0 if plan is valid, 1 if any validation error found.
