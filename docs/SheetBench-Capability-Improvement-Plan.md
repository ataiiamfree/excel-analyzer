# SheetBench Capability Improvement Plan

This document tracks the SheetBench capability-improvement branch. It is an
analysis and guardrail document only; product changes should be made in later
commits and measured against this baseline.

## Branch

- Branch: `codex/sheetbench-capability-improvements`
- Baseline commit: `909f7bb Improve spreadsheet QA answer reliability`
- Baseline run: `eval_runs/20260629_224514`
- Baseline command:

```bash
python scripts/run_eval.py --benchmark sheetbench --benchmark-variant complex-qa
```

## Baseline Result

| Metric | Count |
|---|---:|
| Total | 21 |
| Passed | 12 |
| Failed | 9 |
| Pass rate | 57.1% |

Failure categories from the eval runner:

| Category | Count |
|---|---:|
| wrong_numeric_answer | 6 |
| no_final_answer | 2 |
| wrong_answer | 1 |

Previous run before the answer-output fixes was `10/21`. The improvement to
`12/21` mainly reduced output-protocol failures; it did not solve the core
table-understanding failures.

## Failure Layers

### L0: Output contract and final-answer closure

These cases do not produce a marked final answer, but at least one also has a
real data-selection problem underneath. The first fix should guarantee a
machine-checkable final answer even when the analysis path finds empty data or
low-confidence results.

| Case | Expected | Observed | Initial diagnosis |
|---|---|---|---|
| `sheetbench-complex_mimo_hitab-104-8` | `No quarter increased; Q1 -22.7 %, Q2 -67.7 %, Q3 -143.7 %, Q4 -1001.2 %.` | no marked answer | The generated code filtered `2020` inside the `Month` column, got an empty frame, then exited without final-answer closure. |
| `sheetbench-complex_realhit-2292-1` | `163802, 6987, much higher` | no marked answer; output file said `0.0` and `0` | The model failed to resolve multi-row headers for Scotland / England-Wales-N.I. 2023 totals, then the report omitted a final answer. |

### L1: Repeated columns and multi-level header collapse

The normalized table has repeated logical columns flattened into suffixes such
as `_2` and `_3`. The current agent treats the first flattened column as the
answer too often.

| Case | Expected | Observed | Initial diagnosis |
|---|---|---|---|
| `sheetbench-complex_mimo_hitab-1106-10` | `125.0` | `115.0 kg` | `press`, `press_2`, `press_3` are three attempts. The question asks how much the athlete pressed; the expected answer is the best / final valid attempt, not the first attempt. |

### L2: Hierarchical row context and merged-cell semantics

Parent rows, contractor rows, division rows, or heading rows apply to subsequent
detail rows. The current normalized table exposes the flattened rows, but the
analysis code does not reliably forward-fill or reconstruct parent context
before filtering.

| Case | Expected | Observed | Initial diagnosis |
|---|---|---|---|
| `sheetbench-complex_mimo_hitab-101-11` | 12 sub-item names | `Earthwork Backfill; Rebar; Rebar; Rebar` | The code filtered `Serial No. = 2` without reconstructing the parent division / contractor scope, so it missed most child rows and duplicated repeated values. |
| `sheetbench-complex_realhit-515-6` | `3270` | `0` | The model did not find the mitigation-strategy section and likely failed to carry section labels down to the numeric `TOTAL` row. |

### L3: Field semantics and metric disambiguation

The model selected a plausible but wrong metric row or computed a derived value
with the wrong business definition.

| Case | Expected | Observed | Initial diagnosis |
|---|---|---|---|
| `sheetbench-complex_realhit-282-3` | `2` | `0` | It selected `Purchasing Power Parities for GDP` instead of the actual GDP row, then compared small PPP values against `95,000`. |
| `sheetbench-complex_realhit-703-4` | `4.05` | `1.735518292682798` | It interpreted "Mark Up Price" as `Price - CostMaterial - CostLabor`; the benchmark expects the table's markup-price interpretation for Painted vs Galvalume. |
| `sheetbench-complex_realhit-1135-5` | `2, 24` | `7 users, 1750 chats` | It selected the wrong chat metric / aggregation level, likely using broad totals instead of user rows with chats serviced greater than 11. |

### L4: Complex spatial matching in construction tables

This group needs table-structure support but is not the first slice unless it
falls out naturally from L1/L2 improvements.

| Case | Expected | Observed | Initial diagnosis |
|---|---|---|---|
| `sheetbench-complex_mimo_hitab-91-9` | `72.4` | `163.4` | The model matched the right material but likely summed the wrong floor scope or included extra rows. |

## First Improvement Slice

Do not start with all nine failures. The first slice should target only
general capabilities that are useful for real users:

1. Final-answer closure for empty or low-confidence analysis paths.
2. Repeated-column / multi-level-header interpretation.
3. Parent-context reconstruction for hierarchical rows when it is needed by
   the question.

Cases expected to move first:

| Target | Reason |
|---|---|
| `104-8` | Should at least become a marked, diagnosable final answer; a better column-intent check may also solve the answer. |
| `2292-1` | Should stop failing as `no_final_answer`; full correctness may require header reconstruction. |
| `1106-10` | Direct repeated-column case. |
| `101-11` | Direct parent-context case. |

Cases not targeted in the first slice:

| Case | Reason |
|---|---|
| `282-3`, `703-4`, `1135-5` | Need stronger metric disambiguation and business-definition checks. |
| `515-6` | Likely hierarchy plus section matching; may improve with L2 but should not drive the first design. |
| `91-9` | Construction-table spatial scope issue; useful later, but easy to overfit early. |

## A/B Verification Gate

Every product change on this branch should be measured against the baseline
`12/21` result.

Required checks before considering a product-change commit healthy:

```bash
pytest
python scripts/run_eval.py --benchmark sheetbench --benchmark-variant complex-qa
```

For focused iteration, run the target cases first:

```bash
python scripts/run_eval.py --benchmark sheetbench --benchmark-variant complex-qa --case-id sheetbench-complex_mimo_hitab-104-8
python scripts/run_eval.py --benchmark sheetbench --benchmark-variant complex-qa --case-id sheetbench-complex_realhit-2292-1
python scripts/run_eval.py --benchmark sheetbench --benchmark-variant complex-qa --case-id sheetbench-complex_mimo_hitab-1106-10
python scripts/run_eval.py --benchmark sheetbench --benchmark-variant complex-qa --case-id sheetbench-complex_mimo_hitab-101-11
```

Record for each run:

- run directory
- pass count and failure categories
- cases improved
- cases regressed
- whether failures moved from product ambiguity to clean `Final Answer`

Minimum bar for merging back to `main`:

- no unit-test regression
- no drop below `12/21` on SheetBench `complex-qa`
- at least one targeted failure fixed for a product-general reason
- no special-casing by benchmark case id, filename, or expected answer

## Guardrails

- Do not change product behavior only to satisfy a benchmark artifact.
- Do not add case-id, file-name, or expected-answer conditionals.
- Prefer reusable table-structure signals over prompt-only patches.
- Keep eval-layer changes separate from product capability changes.
- If a fix improves final-answer formatting but not answer correctness, record
  it as an output-contract improvement, not a reasoning improvement.
