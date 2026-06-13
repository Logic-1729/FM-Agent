---
name: swe-bench-incremental-benchmark
description: Build small, runnable test cases that exercise run_incremental_pipeline (this repo's incremental reasoner) from SWE-bench PR instances of a target GitHub repo. Use when asked to "generate testcases" / "build a benchmark" for the incremental pipeline from SWE-bench data, for any repo. Produces one SMALL per-case git repo (200-500 LoC, real code, multiple functions with call relations) plus per-variant modification patches, intents, and a scoring runner.
---

# SWE-bench → incremental-pipeline benchmark

Turn SWE-bench PR instances into small test cases that exercise
`run_incremental_pipeline` (`src/incremental_reasoner.py`). The real SWE-bench repo
is far too large to run the full pipeline over quickly, so you reproduce only the
relevant code and changes.

If this repo includes a worked example, such as **psf/requests** under
`testcase/cases/`, treat it as optional reference material. The skill must still be
usable without any bundled example folder: create or adapt the generator and runner
from the procedure below when no local example scripts are available.

Design choice: each case is its OWN small repo (NOT one shared base). This keeps each
codebase small (200-500 LoC) at the cost of one full pipeline run per case repo. An
earlier shared-base variant (one full run for all) exists in git history if you ever
want to trade size for fewer full runs.

## What the pipeline requires (the contract you must satisfy)

`run_incremental_pipeline(proj_dir, intent_file, old_commit)` — CLI:
`python main.py <proj_dir> --incremental <intent_file> --old-commit <commit>`

- `proj_dir` must be a **git repo**. It needs the artifacts of a prior **full run**
  (`python main.py <proj_dir>` → `fm_agent/phases.json` + specced
  `fm_agent/extracted_functions/`); otherwise it silently falls back to a full run.
- It **diffs the working tree against `old_commit`**, re-specs the changed (and
  intent-relevant / affected) functions reusing the baseline specs for everything
  else, verifies them, and writes an incremental run log under
  `fm_agent/incremental_<timestamp>.log`. A completed run logs
  `INCREMENTAL PIPELINE DONE: bug validation confirmed bugs in N function(s).`
  and confirmed bug-validation artifacts under `fm_agent/bug_validation/*.result.json`.
- Change detection (`_collect_changed_functions`) is **per source file, by function
  source text**, for extensions in `EXT_TO_LANG` (`src/extract.py`). **Test files
  are ignored** (`_is_test_file`) — only non-test source functions matter. Python
  functions are matched by `def name(` at any indent (methods included), keyed by
  name; keep names unique within a file.
- It already handles **added** functions (spec generated from scratch), **removed**
  functions (`_remove_stale_extracted`), and **multi-file / multi-function** changes.

## Core design (keep unless told otherwise)

1. **Use REAL repo code, not synthetic analogs.** The modified function lives in its
   real file among other real functions, so the pipeline must genuinely *localize*
   it. Do NOT isolate the target in a separate package/domain — that hands the scope
   away and is unrealistic.
2. **One small repo PER CASE.** Each instance gets its own git repo whose one commit
   holds that instance's target function in its **pre-fix** form. Size each to
   **200 < LoC < 500**, containing **multiple functions with real call relations**
   (so the call-graph propagation paths are exercised).
3. **Each instance → trial(s).** A trial = one modification patch on the case repo +
   an intent + an `expect_bug` flag. Minimum two per PR:
   - **positive**: the PR's real fix → expect `N == 0` (satisfies intent).
   - **negative**: a deliberately wrong fix → expect `N >= 1` (violation flagged).
4. **Method-level, reference-aware trimming.** Real target files are often >500 LoC
   (big classes). Trim at function/method granularity: keep the target + the
   transitive closure of everything it calls (functions, methods by name, classes
   referenced as bases/constructed — kept WHOLE), so no `self.method()` or name
   ever dangles. If the kept set has no internal call edge, also keep the smallest
   CALLER of the target (guarantees a caller→callee relation). Pack a few more
   siblings up to the ceiling. Files too small to reach the 200 floor get one or two
   small REAL sibling modules appended as filler.
5. **Legality is guaranteed.** The base AND every post-patch tree must have zero
   syntax errors and zero undefined names (see verification). The generator enforces
   this and raises otherwise.
6. **Intents are behavior-only.** Describe what the developer wants and the bug;
   **never** include PR/issue numbers, repo names, or "#1234".

## Procedure

Inputs you need per instance (from the SWE-bench dataset row): `instance_id`,
`base_commit`, the PR `patch` (gold patch), and `problem_statement`.

1. **Gather instances & clone.** Put each instance's metadata under
   `testcase/<instance_id>/` (e.g. `base_commit.txt`, the `*.patch`,
   `problem_statement`/`intent.txt`). Full-clone the repo once to a cache, e.g.
   `testcase/.cache/<repo>` (gitignore `testcase/.cache/`). A full clone is needed
   for history walk-back; SWE-bench base commits are often NOT fetchable as refs.

2. **Per instance, extract the change from the patch.** From the gold patch take,
   for the primary **source** file (ignore test hunks):
   - the target function name,
   - the exact **pre-fix** text (context + `-` lines) and **post-fix** text
     (context + `+` lines).
   Author a **buggy** variant: a plausible-but-wrong edit that fails the intent
   (e.g. invert a condition, normalize the wrong value, quote the wrong field,
   re-attach reversed). Keep each edit's `old` snippet unique in its file.

3. **Find a commit where the pre-fix code actually exists (walk-back).** The exact
   `base_commit` is often gone (history rewrites → 404). `find_base(find_date,
   basename, base_snip, oldest=False)` starts at the last commit before the case's
   `find_date` and walks `git rev-list <start> -- <likely-paths>`
   **newest-first** until the file contains the **pre-fix snippet exactly once**.
   Set the per-case `oldest=True` flag to walk **oldest-first** instead — use it to
   pick a SMALLER, earlier version of a large target function so the trim fits the
   500 ceiling. Do git ops in **Python** with `subprocess` + `.strip()` — bash `$()`
   can carry a stray `\r` into `git show <sha>:path` and silently fail.

4. **Build the small case repo (method-level trim).** Use the file at the walk-back
   commit. Trim it (function/method granularity, reference-aware per design point 4)
   to **200 < LoC < 500** keeping the target + its call closure (+ the smallest
   caller only if the closure has no internal edge), then packing more siblings up to
   `PACK_LO` (≈230, the floor-with-margin target) without exceeding `HI` (500). If the
   trimmed file is still under 200 (e.g. `auth.py` ~194), append whole small REAL
   sibling modules (`SMALL_FILLERS = hooks.py, status_codes.py, structures.py,
   certs.py`) until it clears 200. Auto-shim py2 builtins used in guarded code
   (`add_py2_shims` appends `unicode = str` etc.). Commit it as the case's base;
   record `base_commit.txt`.

5. **No same-function conflicts to resolve.** Because each case is its own repo, two
   instances editing the same function (e.g. requests 1724 and 2317 both on
   `Session.request`) live in separate repos and never collide. Use each PR's REAL
   target location. Ensure the fix's referenced names are importable in the chosen
   commit. If the chosen pre-fix commit predates an import or helper required by the
   fix, add that import/helper in the variant edit. Module-level edits bind names
   (keeping the tree legal) and are invisible to change detection because they are
   outside any function.

6. **Generate patches.** Apply each variant's edits to the case file, `git diff` in
   the case repo, save as `mods/<variant>.patch`, then revert. (Most patches are one
   file; the legality gate runs on the post-patch content.)

7. **Write intents & index.** One behavior-only intent per intent-key under each
   case's `intents/`. Emit `testcase/cases/index.json` listing trials (`id`, `case`,
   `variant`, `kind`, `repo`, `base_commit`, `files`, `intent`, `patch`, `expect_bug`,
   `desc`).

8. **Provide the runner.** Create or adapt `testcase/run_benchmark.py`: it does ONE
   full run per case repo, snapshots its `fm_agent/`, then per variant restores the snapshot,
   `git apply`s the patch (absolute path — `git -C repo` resolves relative to repo),
   runs the incremental CLI, reads the newest `fm_agent/incremental_*.log` to confirm
   completion / no-baseline fallback, counts confirmed bugs from fresh
   `fm_agent/bug_validation/*.result.json`, scores (`expect_bug==False → N==0`,
   `expect_bug==True → N>=1`), archives the run artifacts, and reverts. Keep its
   editable `CONFIG` block + `--case/--kind/--limit/--skip-full/--jobs` flags.
   Concurrency: distinct case repos are independent, so cases run in a thread pool
   (`--jobs J`); variants WITHIN a case stay sequential (they share one repo +
   `fm_agent/`). Each case's pipeline already spawns up to `MAX_WORKERS` opencode
   workers, so `--jobs J` ⇒ up to `J*MAX_WORKERS` concurrent LLM calls — keep J modest.

## Change-shape variants to include

Cover the pipeline's branches with a few extra trials beyond positive/negative:
- **added+modified**: a correct fix that also adds a new helper function the modified
  function calls (and a buggy version where the helper is wrong).
- **deleted**: remove an **unused** function (verify zero references first; pin it as
  a keep snippet so trimming doesn't drop it before the delete patch can remove it).
  Do not delete a function with live callers — that's just broken code, out of scope.
- (multi-file changes also work — `_collect_changed_functions` is per file — but in a
  small per-case repo a same-file 2-function change is the natural form; the
  added+modified variant already changes two functions.)

## Output layout

```
testcase/<instance_id>/         # raw SWE-bench metadata (base_commit, patch, problem)
testcase/.cache/<repo>/         # full clone (gitignored)
testcase/cases/                 # the benchmark
  index.json                    #   {trials:[{id,case,variant,kind,repo,base_commit,...}]}
  <instance_id>/
    repo/                       #     own git repo; HEAD = pre-fix (the --old-commit)
    base_commit.txt
    intents/<key>.txt           #     behavior-only intents
    mods/<variant>.patch        #     one patch per variant
testcase/run_benchmark.py       # the scoring driver (one full run per case repo)
testcase/generate_benchmark.py  # the generator (the source of truth; re-runnable)
```
For multiple target repos, namespace under `testcase/cases/<repo>/<instance_id>/`.

## Verification checklist (must pass before declaring done — no LLM needed)

Run these statically after generating (no LLM):
- **Size**: each case repo is `200 < LoC < 500`.
- **Structure**: each base has **≥2 functions** and **≥1 call edge** among them
  (AST: a function whose body calls another kept function's name). This is the
  "multiple functions and call relations" requirement.
- **Patches apply**: `git -C <case>/repo apply --check mods/*.patch` (use an
  ABSOLUTE patch path — `git -C` resolves relative paths against the repo dir).
- **Change shape**: apply each patch → `_collect_changed_functions(repo, base)` →
  confirm the expected added/modified/removed set and counts → revert.
- **Legality is enforced by the generator, not optional.** It runs a self-contained
  check (`legality_problems` / `assert_legal`: AST syntax + "name referenced but
  bound nowhere") on (a) every base file and (b) **every file of every variant AFTER
  its patch is applied**, and raises otherwise. Keep this gate. (Optionally also
  `pyflakes`.) Common fixes when it fires: the method-level trim must keep the call
  closure (no dangling `self.x()`); pin a deletion target as a keep snippet; add the
  fix's referenced import (or pick a commit where it's importable); auto-shim guarded
  py2 builtins (`unicode = str`).
- No PR/issue numbers in any `intents/*.txt` (`grep -nE '#[0-9]+|PR #|Fixes issue'`).
- `run_benchmark.py --list` shows the expected trials.

## Pitfalls (learned the hard way)

- SWE-bench `base_commit` is often unreachable (ref + raw 404) → walk-back to a
  commit containing the pre-fix snippet.
- "Nearest commit before the PR date" can land **after** the merge (fix already
  present) → keep walking until the *pre-fix* snippet is found.
- Do git plumbing in Python, not bash command-substitution (`\r` corruption).
- Naive "drop top-level blocks until it fits" trimming silently breaks the repo —
  kept code calls a dropped helper or inherits a dropped base class. Trim by call
  closure (method granularity), keep referenced classes/bases whole.
- **Dangling `self.method()` is NOT caught by an undefined-name check** (it's an
  attribute, not a name) — the method-level trimmer must itself keep the closure of
  called methods so none dangle.
- Picking the SMALLEST/oldest pre-fix commit to shrink a big function can predate an
  import the FIX needs (e.g. `to_native_string`) → add the import in the fix edit, or
  pick a later commit.
- A caller-less, callee-less target yields 0 call edges — keep the smallest caller so
  there's a real relation.
- A deletion target that's unreferenced gets trimmed away — pin it with a keep snip.
- Test-file hunks in the gold patch are irrelevant (the pipeline ignores tests).
- Keep the modified code among real siblings — don't isolate it (trivial scope).
- `git -C repo apply <patch>` needs an absolute patch path.

## Generator and runner implementation

Provide `testcase/generate_benchmark.py` and `testcase/run_benchmark.py` for the
target repo. If local reference scripts already exist, adapt them; otherwise implement
them from this skill's procedure. The generator should define per-instance case data
(`name`, `file`, `find_date`, optional `oldest`, `base_snip`, `fixed`/`buggy` edit
lists, optional `extra_keep`), extra-shape variants, and behavior-only intents, then
run the verification checklist. Keep the reusable machinery generic: `find_base`
(walk-back), `trim_methods` (method-level reference-aware trim + caller/pack),
`add_fillers` (floor-fill), `add_py2_shims`, and
`legality_problems`/`assert_legal` (the gate). Tunables: `LO`/`HI`/`PACK_LO`,
`SMALL_FILLERS`.
