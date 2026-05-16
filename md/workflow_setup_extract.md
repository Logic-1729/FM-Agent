# Setup & Codebase Understanding

> **YOUR SOLE OBJECTIVE**: Create exactly 3 types of output files listed below. Do NOT edit any existing project files (no AGENTS.md, no README, no source code). Only create files inside `fm_agent/`.

> **CRITICAL — YOU MUST CREATE FILES IN THIS SESSION**: Do NOT only research, plan, or delegate to background/sub-agents. You MUST directly write `fm_agent/phases.json` and the domain context files yourself before this session ends.

**Required output files:**
1. `fm_agent/phases.json`
2. `fm_agent/spec_prompts/domain_context/engine_overview.txt`
3. `fm_agent/spec_prompts/domain_context/phase_NN_types.txt` (one per phase)

**Rules:**
- `fm_agent/` is NOT part of the project source code. It is a scratch workspace for storing YOUR output files only. Do NOT treat files inside `fm_agent/` as project source files. Do NOT include any `fm_agent/` paths in `phases.json`.
- Do NOT modify any existing files in the repository.
- Do NOT create or edit AGENTS.md, README.md, or any file outside `fm_agent/`.
- Do NOT run the project or install dependencies.
- Keep exploration minimal — read only what is needed to understand the module structure. Ignore the `fm_agent/` directory when analyzing the codebase.
- Start writing output files as soon as you have enough context. Do not over-analyze.
- Do NOT delegate file creation to sub-agents. Write the files directly yourself.

---

## Step 1 — Understand the Codebase & Write `phases.json`

Quickly scan the codebase structure and **immediately** write `fm_agent/phases.json` — a machine-readable description of every phase.

**Schema:**

```json
{
  "project": "<project_name>",
  "languages": ["<lang1, e.g. cpp>", "<lang2, e.g. python>"],
  "file_extensions": ["<ext1, e.g. cpp>", "<ext2, e.g. py>"],
  "phases": [
    {
      "phase": 1,
      "name": "<Human-readable phase name>",
      "description": "<One sentence: what this phase does in the data pipeline>",
      "modules": [
        {
          "name": "<module_name>",
          "source_files": ["<path/to/source>", "..."]
        }
      ],
      "depends_on_phases": []
    },
    {
      "phase": 2,
      "name": "<Phase name>",
      "description": "<One sentence>",
      "modules": [
        {
          "name": "<module_name>",
          "source_files": ["<path/to/source>"]
        }
      ],
      "depends_on_phases": [1]
    }
  ]
}
```

**Field rules:**

- `project` — name of the repo root
- `languages` — list of canonical lowercase language identifiers used in the project (e.g. `["cpp", "python"]`). For single-language projects, use a one-element list.
- `file_extensions` — list of file extensions without leading dot, one per language (e.g. `["cpp", "py"]`). Order should match `languages`.
- `phases[*].phase` — 1-indexed integer, unique, ascending
- `phases[*].name` — brief label
- `phases[*].description` — one sentence explaining what this phase does in the data pipeline
- `phases[*].modules[*].name` — matches the subdirectory name of the module
- `phases[*].modules[*].source_files` — relative paths from repo root of all source files that belong to this module. **Exclude all test files** (e.g., files in `test/`, `tests/`, `__tests__/` directories, or files named `*_test.*`, `test_*.*`, `*_spec.*`)
- `phases[*].depends_on_phases` — list of phase numbers whose outputs this phase consumes (empty list for phases with no dependencies)

Each source file must belong to **at most one phase**. If the same file appears in more than one phase's `modules[*].source_files`, the `phases.json` is invalid and must be corrected before proceeding.

Each phase must be **self-contained**: all source files for a module in that phase must be listed explicitly. No phase may silently depend on files listed in another phase's modules.

**Implementation tip:** Use a glob or `find` command to list source files per directory. Do not enumerate files by hand. Filter out test files (`test/`, `tests/`, `__tests__/`, `*_test.*`, `test_*.*`, `*_spec.*`). Write `fm_agent/phases.json` immediately after listing files — do not delay.

**IMPORTANT: After writing `fm_agent/phases.json`, proceed to Step 2 immediately. Do not revisit or refactor Step 1.**

---

## Step 2 — Write Domain Context Files

### Write `fm_agent/spec_prompts/domain_context/engine_overview.txt`

Describe the overall system:
- Architecture: what the pipeline stages are and how data flows between them
- Encoding conventions: how each data type is stored (scaled integers, date offsets, dictionary codes, string layouts)
- Key precomputed data structures and their invariants (e.g., join maps, range indices)
- Important invariants of every phase

### Write `fm_agent/spec_prompts/domain_context/phase_NN_types.txt` for each phase

For each phase, describe:
- All structs and types that functions in this phase produce or consume
- Field types and valid value ranges
- Encoding rules (with explicit formulas, e.g., `date_field[i] = actual_days - base_date_days`)
- Invariants that must hold in this phase
- Entry point function signatures

These files are given to spec-writing agents as context. Without them, agents will write generic specs that miss the domain-specific invariants.

---

## Checklist

**Before finishing, verify all of the following exist (use `ls` to confirm):**

- [ ] `fm_agent/phases.json` exists and is valid JSON
- [ ] `fm_agent/spec_prompts/domain_context/engine_overview.txt` exists
- [ ] `fm_agent/spec_prompts/domain_context/phase_NN_types.txt` exists for each phase

---

## Project-Specific Authoritative Context (BespokeOLAP TPC-H)

**Gate:** Apply this section only if the codebase under analysis is the `bespoke_tpch` C++ OLAP engine — heuristics:

- Source dir contains files like `loader_impl.cpp`, `builder_impl.cpp`, `query_q1.cpp` ... `query_q22.cpp`, `args_parser.hpp`.
- A sibling `queries.txt` enumerates 22 TPC-H queries.
- `db.cpp` / `loader_api.cpp` / `builder_api.cpp` exist either alongside or via `api_path` (typically at `/mnt/nvme2/zyx/projects/BespokeOLAP/misc/fasttest/`).

If the codebase does **not** match the above, **ignore this section entirely** and derive `engine_overview.txt` from your own exploration of the source.

If the codebase **does** match: copy the block below **verbatim** into `fm_agent/spec_prompts/domain_context/engine_overview.txt`. You may append additional notes you discover from the code, but never contradict the conventions here — they are precise contracts that downstream specs and the bug validator depend on. The `phase_NN_types.txt` files should expand on the types referenced below (DictionaryColumn, StringColumn, LineitemShard, OrderRange, QNArgs, QNResultRow, ...) with field-level details derived from the actual source.

```
## Domain Context: bespoke_tpch C++ OLAP Engine

### Engine Architecture

bespoke_tpch is a hand-optimized C++ query engine for the TPC-H benchmark.
It loads 8 Parquet tables from disk, transforms them into a custom columnar
in-memory Database, then executes TPC-H queries Q1–Q22 against it.

The pipeline has three runtime phases:
  1. Load: Parquet → ParquetTables (Apache Arrow tables, one per TPC-H table)
  2. Build: ParquetTables → Database (bespoke columnar layout with precomputed structures)
  3. Query: stdin requests → per-query execution → CSV result files + timing stdout

### Encoding Conventions

All encoding choices are driven by the hot-path scan performance requirement.

DATE ENCODING:
  - Base date: 1992-01-01 (stored in Database.base_date_days as int32_t epoch-days)
  - Stored as int16_t: value = (actual_date_days - base_date_days)
  - Fits in int16_t because TPC-H dates span ~8 years (fits in ~3000 offset values)
  - Comparison: shipdate <= cutoff becomes int16_t <= int16_t (no conversion at query time)

MONETARY/DECIMAL ENCODING:
  - extendedprice, totalprice, supplycost, acctbal: int32_t = round(decimal * 100)
  - discount, tax: uint8_t = round(fractional * 100), range [0, 100]
  - discounted_price: precomputed int32_t = round(extendedprice * (100 - discount))
  - kPriceScale = 100; kDiscountScale = 100

QUANTITY ENCODING:
  - quantity: int16_t (TPC-H quantities are integers 1–50, fits easily)

DICTIONARY ENCODING:
  - DictionaryColumn: codes is uint16_t[], dictionary is vector<string>
  - Used for low-cardinality string columns: returnflag, linestatus, shipinstruct,
    shipmode, orderstatus, orderpriority, mfgr, brand, container, type, mktsegment
  - Throw if dictionary would exceed uint16_t::max (65535 entries)
  - Enables O(1) equality filter: compare code, not string

STRING COLUMN ENCODING:
  - StringColumn: offsets (uint32_t[]), data (string), alpha_mask (uint32_t[]), bigram_mask (uint64_t[])
  - String i: data[offsets[i] .. offsets[i+1])
  - alpha_mask[i]: bit j set iff letter ('a'+j) appears (case-insensitive) in string i
    → fast LIKE filter pre-check: if (needle_alpha_mask & ~string_alpha_mask) == 0, possible match
  - bigram_mask[i]: bit hash(c[k], c[k+1]) set for each adjacent pair
    → stronger pre-check before full string comparison

### Precomputed Join Structures

orderkey_to_row: vector<int32_t> indexed by orderkey → row index in orders.orderkey
  - Enables O(1) join: given a lineitem's orderkey, find the orders row immediately
  - Required by queries that join lineitem ↔ orders (Q3, Q5, Q7, Q8, Q10, Q18, Q21)

lineitem_ranges: vector<OrderRange> indexed by orders row index → [start, end) in lineitem
  - Provides all lineitem rows for a given order without scanning the whole table
  - Requires lineitem to be sorted by orderkey (orderkey_sorted flag)

orders_by_customer: offsets + rows arrays — for each custkey, the range of orders rows
  - Required by Q13 (count orders per customer)

nationkey_by_custkey / nationkey_by_suppkey: flat arrays for O(1) nationkey lookup
  - Avoids joining to customer/supplier table for nationkey queries

phone_prefix_code: uint8_t[] where code = first 2 digits of phone number
  - Required by Q22 (filter by country code prefix)

### LineitemShard Structure

Each LineitemShard covers a contiguous (or indexed) subset of lineitem rows
with precomputed min/max metadata:
  - year, month, supp_nationkey: partition key
  - min_shipdate, max_shipdate: tight bounds on shipdate within this shard
  - min_discount, max_discount: tight bounds on discount
  - min_quantity, max_quantity: tight bounds on quantity
  - start, end: row index range [start, end) in lineitem arrays
  - row_indices: if !contiguous, explicit row index list

Shards enable partition pruning: a shard can be skipped entirely if the query's
predicate is guaranteed false given the shard's min/max bounds.

### Query Interface Contract

Each query qN exposes:
  parse_qN(QueryRequest) → QNArgs   — parse query parameters from stdin line
  run_qN(Database, QNArgs) → vector<QNResultRow>   — execute query
  write_qN_csv(filename, rows) → void   — write CSV result file

Result rows are sorted per TPC-H specification (ORDER BY clause in the standard SQL).

### TRACE Mode

All profiling/timing instrumentation is gated by #ifdef TRACE.
PROFILE_SCOPE(name) = RAII ScopedTimer that calls record_timing(name, elapsed_ns)
In production builds (TRACE not defined), all PROFILE_SCOPE macros expand to nothing.

### TPC-H Table Sizes (at SF=1)

  lineitem: ~6M rows (largest table; hottest scan path)
  orders:   ~1.5M rows
  customer: ~150K rows
  part:     ~200K rows
  supplier:  ~10K rows
  partsupp: ~800K rows
  nation:       25 rows (fits in RAM as row-struct vector)
  region:        5 rows (fits in RAM as row-struct vector)
```

**If any file is missing, create it now before ending.**