# Bug Validator Agent Instructions (BespokeOLAP TPC-H Edition)

You are a bug validation agent operating in **single-file mode**. A target result file and bug ID are provided in the prompt header that precedes this document. Your job is to read that single bug report, attempt to confirm the bug by writing and running a concrete test case against the **bespoke_tpch C++ OLAP engine**, and persist the result to disk.

**Target system:** `bespoke_tpch` — a hand-optimized C++ query engine for TPC-H Q1–Q22. It is driven from Python via `BespokeOLAP.tools.fasttest.run.RunTool`. There is **no** standalone CLI; you must use the Python API described below.

---

## Overview

The target result file is a JSON file produced by a logic verification step. It carries a `"verdict"` field (`"MATCH"` or `"MISMATCH"`) and a `"gaps"` object with supporting evidence. You operate only when `"verdict"` is `"MISMATCH"` **and** `"gaps"` is non-null and non-empty. If the file does not meet these conditions, write a detail file noting the skip and exit.

At the end of your run you must produce:

1. One **detailed Markdown file** at `fm_agent/bug_validation/<bug_id>.md` documenting the result.
2. One **test case file** at `fm_agent/bug_validation/_probe_<bug_id>.py` containing the final probe script.
3. A **single-line result file** at `fm_agent/bug_validation/<bug_id>.result.json` recording the confirmation status (see Step 3).

---

## Environment & Paths (Authoritative)

| Path | Purpose |
|---|---|
| `/mnt/nvme2/zyx/projects/BespokeOLAP_Artifacts/bespoke_tpch/` | C++ source of the engine — the `cwd` for `RunTool`. Result CSVs land here. |
| `/mnt/nvme2/zyx/projects/BespokeOLAP/` | Generator repo — provides `RunTool`, `format_args_string`, and the venv. Your Python script runs **from here** so imports resolve. |
| `/mnt/nvme2/zyx/projects/BespokeOLAP/misc/fasttest/` | C++ API templates (`loader_api.cpp`, `builder_api.cpp`, `query_api.cpp`, `db.cpp`, headers). Passed as `api_path` to `RunTool`. |
| `/mnt/nvme2/zyx/projects/BespokeOLAP/.venv/bin/python` | Interpreter to use. Has duckdb + RunTool + Arrow Python bindings. |
| `/mnt/nvme2/zyx/projects/BespokeOLAP_Artifacts/env.sh` | `source` this before `python` calls. Sets `PKG_CONFIG_PATH` + `LD_LIBRARY_PATH` for Arrow/Parquet. |
| `/mnt/nvme2/zyx/data/bespoke_olap/tpch_parquet/sf1/` | TPC-H sf=1 parquet (8 tables). Pre-generated. |

**Never** use any path under `/home/dhr/` or `/mnt/labstore/` — those are leftover from a different machine.

---

## Step 1 — Read the Target Result File

Read the JSON file specified in the prompt header. Extract:

- `source_file` — value of the top-level `"function"` key. If the prefix is `"fm_agent/extracted_functions"`, remove that prefix.
- `spec_claim` — value of `gaps.spec_claim`.
- `actual_behavior` — value of `gaps.actual_behavior`.
- `code_evidence` — value of `gaps.code_evidence`.
- `trigger_condition` — value of `gaps.trigger_condition`.

Also infer which **TPC-H phase** the function belongs to from its path:

| Path contains | Phase | Bug manifests during |
|---|---|---|
| `trace/` | 1 — Profiling | TRACE-only; usually unreachable in production builds |
| `loader/` | 2 — Parquet ingestion | `loader.load()` — visible only if downstream queries see wrong data |
| `builder/` | 3 — Database construction | `builder.build()` — wrong precomputed values, visible in any query result |
| `args/` | 4 — Query arg parsing | `parse_qN()` — wrong rejection or wrong acceptance of input |
| `queries/qN/` | 5 — Per-query execution | `run_qN()` — wrong result rows / wrong order / wrong count |
| `query_dispatch/` | 6 — Dispatch / output | Unknown id, timing, CSV write path |

---

## Step 2 — Attempt to Trigger the Bug

**Attempt budget:** make up to **3 attempts** to produce a confirming test case before giving up.

### 2a. Read the Source File

Open the source file. Read enough context to understand the control-flow around the lines cited in `code_evidence`.

If the function is downstream of other phases (e.g. a Phase 5 query function), also check `fm_agent/spec_prompts/domain_context/engine_overview.txt` for encoding conventions (DATE base = 1992-01-01 stored as int16 offsets, prices as `int32 = round(value * 100)`, etc.) so your expected outputs use the correct units.

### 2b. Classify the Gap

Pick **one** `gap_category` based on what kind of evidence you need to confirm the bug:

| `gap_category` | Confirmation requires | Examples |
|---|---|---|
| `wrong_output` | **DuckDB oracle comparison** | Aggregate value differs from reference |
| `wrong_count` | **DuckDB oracle comparison** | Row count differs from reference |
| `wrong_sort` | **DuckDB oracle comparison** | Order of rows violates spec ORDER BY |
| `wrong_encoding` | **DuckDB oracle comparison** | Date/price column has wrong scale or base |
| `missing_error` | Direct observation (engine should `throw` but doesn't) | Invalid input not rejected |
| `false_error` | Direct observation (engine throws on valid input) | Valid input wrongly rejected |
| `structural_invariant` | Direct observation (offsets / monotonicity violated) | `offsets[i] > offsets[i+1]` |

**Categories tagged "DuckDB oracle comparison" REQUIRE you to run the same query against DuckDB on the same sf=1 data** and prove the engine value differs. Observing an unexpected value alone (e.g. `0.00` when you expected empty) is **NOT** sufficient.

### 2c. Design a Minimal Test Case

Construct a probe script that:

1. Imports `RunTool` and `format_args_string` from BespokeOLAP.
2. Calls the engine on a single TPC-H query with parameters chosen to hit `trigger_condition`.
3. Reads the result CSV.
4. **If gap_category requires DuckDB:** runs the same TPC-H query against duckdb on the same parquet data and compares the values.
5. Prints `CONFIRMED` or `NOT CONFIRMED` to stdout.

#### Probe script template

```python
#!/usr/bin/env python3
"""
Gap: <spec_claim — one line>
Trigger: <trigger_condition — one line>
Category: <gap_category>
"""
import os, sys
from pathlib import Path

SRC = Path("/mnt/nvme2/zyx/projects/BespokeOLAP_Artifacts/bespoke_tpch")
API = Path("/mnt/nvme2/zyx/projects/BespokeOLAP/misc/fasttest")
DATA = "/mnt/nvme2/zyx/data/bespoke_olap"

# Imports must run from /mnt/nvme2/zyx/projects/BespokeOLAP so sys.path resolves.
sys.path.insert(0, "/mnt/nvme2/zyx/projects/BespokeOLAP")
from tools.fasttest.run import RunTool
from tools.validate_tool.query_validator_class import format_args_string

engine = RunTool(
    cwd=SRC,
    dataset_name="tpch",
    base_parquet_dir=DATA,
    api_path=Path(os.path.relpath(API, SRC)),
    parse_out_and_validate_output=False,
)

# --- Engine run ---------------------------------------------------------
# Pick the query that exercises the buggy unit (see "Query Parameters" below).
args_list = format_args_string(
    ["<query_id>"],                          # e.g. "6"
    [{"<PARAM>": "<value>", ...}],           # e.g. {"DATE": "1994-01-01", "DISCOUNT": "0.06", "QUANTITY": "24"}
)
result = engine.run_worker(scale_factor=1, optimize=True, stdin_args_data=args_list)

engine_csv = (SRC / "result1.csv").read_text() if (SRC / "result1.csv").exists() else ""
print("--- engine stdout ---");  print(result.out or "")
print("--- engine stderr ---");  print(result.err or "")
print("--- engine result1.csv (first 500 chars) ---");  print(engine_csv[:500])

# --- DuckDB oracle (REQUIRED for wrong_output/wrong_count/wrong_sort/wrong_encoding) ---
import duckdb
con = duckdb.connect()
for tbl in ["customer","lineitem","nation","orders","part","partsupp","region","supplier"]:
    con.execute(f"CREATE VIEW {tbl} AS SELECT * FROM read_parquet('{DATA}/tpch_parquet/sf1/{tbl}.parquet')")
duckdb_rows = con.execute("""
    <equivalent TPC-H SQL with parameters substituted>
""").fetchall()
print("--- duckdb output ---");  print(duckdb_rows[:10])

# --- Compare -----------------------------------------------------------
# Parse engine CSV rows, then compare element-wise against duckdb_rows.
# Numeric tolerance: abs(a - b) <= max(1e-6, 1e-6 * abs(b))
# String: exact match.
match = (... element-wise check ...)

if not match:
    print("CONFIRMED — engine output differs from duckdb reference")
else:
    print("NOT CONFIRMED — engine matches duckdb")
```

#### Probe script template (for `missing_error` / `false_error` / `structural_invariant`)

```python
import sys
sys.path.insert(0, "/mnt/nvme2/zyx/projects/BespokeOLAP")
from tools.fasttest.run import RunTool
from tools.validate_tool.query_validator_class import format_args_string
# ... same RunTool setup ...

# For missing_error: pass an input that the spec says must throw.
# Read engine.err and result.resp — bug confirmed if exit_code == 0 (no throw).

# For structural_invariant: query at the boundary, then post-process the
# result CSV / engine stderr to check the invariant directly.

# Print CONFIRMED / NOT CONFIRMED.
```

### 2d. Write & Run the Probe

Write to `fm_agent/bug_validation/_probe_<bug_id>.py`. Run it via:

```bash
cd /mnt/nvme2/zyx/projects/BespokeOLAP
source /mnt/nvme2/zyx/projects/BespokeOLAP_Artifacts/env.sh
.venv/bin/python <abs path to _probe_<bug_id>.py>
```

`env.sh` is **mandatory** — without it the engine's `dlopen` of `libloader.so` will fail to resolve Arrow symbols.

Capture stdout and exit code.

### 2e. Classify and Retry

| stdout contains | Classification |
|---|---|
| `CONFIRMED` | **confirmed** — stop retrying |
| `NOT CONFIRMED` | **not_confirmed** — retry with different parameters |
| `ERROR` / non-zero exit | **error** — retry after fixing the script |

Retry rules:

- After **3 attempts** without `confirmed`, stop. Record the final classification.
- Each attempt overwrites the same `_probe_<bug_id>.py`.
- Retry strategy: try boundary dates (1994-01-01, 1998-12-31), edge quantities (1, 50), extreme discount (0.00, 0.10), empty result regions (DATE > 1998-12-31), high-cardinality strings.

---

## Step 3 — Write Detail and Result Files

### Detail Markdown file at `fm_agent/bug_validation/<bug_id>.md`

````markdown
# Bug Report: <FunctionName>

**Source file:** `<value of "function" field>`
**TPC-H phase:** <1..6>
**Verdict:** MISMATCH
**Gap category:** <gap_category>
**Confirmation status:** confirmed | not_confirmed | error

---

## Reasoning Process

### Specification Claim
<verbatim>

### Actual Behavior
<verbatim>

## Code Evidence
<verbatim>

## Trigger Condition
<verbatim>

---

## How to trigger the bug

### Query & Parameters
| Field | Value |
|---|---|
| Query ID | Q<N> |
| <PARAM> | <value> |
| ... | ... |

### Expected (spec-correct) Output
`<expected value, with units>`

### Actual (buggy) Output
`<engine value, with units>`

### DuckDB Reference (if applicable)
```sql
<SQL run against duckdb>
```
Reference output: `<duckdb result>`

### How to Reproduce
```bash
cd /mnt/nvme2/zyx/projects/BespokeOLAP
source /mnt/nvme2/zyx/projects/BespokeOLAP_Artifacts/env.sh
.venv/bin/python fm_agent/bug_validation/_probe_<bug_id>.py
```

## Probe Script
```python
<full probe contents>
```

### Probe Output
```
<raw stdout from last attempt>
```
````

### Result JSON file at `fm_agent/bug_validation/<bug_id>.result.json`

```json
{
  "id": "<bug_id>",
  "source_file": "<value of function field>",
  "function_name": "<basename without extension>",
  "tpch_phase": 1|2|3|4|5|6,
  "gap_category": "wrong_output|wrong_count|wrong_sort|wrong_encoding|missing_error|false_error|structural_invariant",
  "confirmation_status": "confirmed|not_confirmed|error",
  "attempts": <int 1-3>,
  "probe_script": "fm_agent/bug_validation/_probe_<bug_id>.py",
  "detail_file": "fm_agent/bug_validation/<bug_id>.md",
  "probe_stdout": "<single line, escape newlines as \\n>",
  "trigger_summary": "<one sentence>",
  "duckdb_reference_run": {
    "sql": "<SQL or null>",
    "duckdb_output": "<truncated reference rows or null>",
    "engine_output": "<truncated engine rows or null>",
    "match": true|false|null
  }
}
```

**`duckdb_reference_run` rules:**

- **Required** (`sql`, `duckdb_output`, `engine_output`, `match` all non-null) when `gap_category` ∈ {`wrong_output`, `wrong_count`, `wrong_sort`, `wrong_encoding`}.
- **Set to `null` or omit** when `gap_category` ∈ {`missing_error`, `false_error`, `structural_invariant`}.
- A result-correctness gap with null `duckdb_reference_run` **cannot** be `"confirmation_status": "confirmed"`.

---

## Query Parameter Quick Reference

| Q | Parameters |
|---|---|
| Q1 | `DELTA` |
| Q3 | `SEGMENT`, `DATE` |
| Q4 | `DATE` |
| Q5 | `REGION`, `DATE` |
| Q6 | `DATE`, `DISCOUNT`, `QUANTITY` |
| Q7 | `NATION1`, `NATION2` |
| Q8 | `NATION`, `REGION`, `TYPE` |
| Q9 | `COLOR` |
| Q10 | `DATE` |
| Q11 | `NATION`, `FRACTION` |
| Q12 | `SHIPMODE1`, `SHIPMODE2`, `DATE` |
| Q13 | `WORD1`, `WORD2` |
| Q14 | `DATE` |
| Q15 | `DATE`, `STREAM_ID` |
| Q16 | `BRAND`, `TYPE`, `SIZE1`..`SIZE8` |
| Q17 | `BRAND`, `CONTAINER` |
| Q18 | `QUANTITY` |
| Q19 | `QUANTITY1..3`, `BRAND1..3` |
| Q20 | `COLOR`, `DATE`, `NATION` |
| Q21 | `NATION` |
| Q22 | `I1`..`I7` (country code prefixes) |

Reference SQL for each query: `/mnt/nvme2/zyx/projects/BespokeOLAP_Artifacts/bespoke_tpch/queries.txt`.

---

## Constraints

1. Use the `bug_id` from the prompt header for all filenames.
2. **Do not modify** any source file in `BespokeOLAP_Artifacts/bespoke_tpch/` or `BespokeOLAP/`. You are read-only.
3. **Do not modify** anything under `fm_agent/logic_verification_results/`.
4. Always `source env.sh` and `cd /mnt/nvme2/zyx/projects/BespokeOLAP` before running the probe.
5. The probe must be **self-contained Python** — no `pytest`/`unittest`, no network.
6. For result-correctness gaps, the probe **must** include a DuckDB oracle block; the `match` field is your truth.
7. Numeric comparison tolerance: `abs(a - b) <= max(1e-6, 1e-6 * abs(b))`. Strings: exact.
8. If `trigger_condition` requires data absent at sf=1 (e.g. nation `"BURUNDI"` which isn't in the 25 TPC-H nations), record this in `actual_output`, mark `not_confirmed`, and explain in the detail Markdown.
9. Result CSV file: `bespoke_tpch/result<N>.csv` where `<N>` is the position in `args_list` (1-based).
10. Compile cache is shared — the first probe in a run may take ~30s, subsequent probes reuse the cached `.so` files (~1s).
