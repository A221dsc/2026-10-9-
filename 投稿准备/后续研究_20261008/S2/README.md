# S2: independent-source and long-running window evidence

This stage preserves production R6 and the completed S0/S1 results. It tests the NASA July 1995 timestamp distribution using matched LIST, matched Event16, R6 and TLX; N=262144 and true common prefixes at 1, 2 and 4 turnovers. Queries and cancellations are generated operations, not a production access trace. Exact scope and statistics are in `s2_protocol.json` and the preregistration.

Git is the version identity. `s2-engineering-v1` will identify the reviewed source and executable snapshots. File digests inside receipts are integrity checks for actual executed inputs and outputs. Large raw artifacts, timestamp projection, toolchain and runtime remain local and are referenced by the absolute paths in the launch lock.

Preparation: see `README_PREPARE_NASA.md`. Build: `tools/build_engineering.py` records actual compiler commands, dependencies and native/resource tests into a new engineering directory. Never overwrite an existing build or published result. The environment record specifies the exact compiler, private Python runtime and fixed P core 3.

The launcher has no implicit execution. `engineer-lock` produces an unauthorized candidate; `plan` writes the planned matrix without running it. Formal `preflight` and `run` require a root-approved lock, independent Approved reviews, fresh GREEN evidence, a real full-capacity receipt and clean frozen Git code. Use a new ASCII `--tag` and explicit `--lock` path. The full plan contains 1080 native, 360 A/A and 120 resource children plus 33 longest-trace preparations.

Formal archive layout: `artifacts/launch/<tag>/plan.json`, `lock.json`, `command_plan.json`, `prepare/`, `caches/`, `units/`, and `attempts/`. Each child keeps actual process receipts, stdout/stderr, raw CSV, phase CSV and resource snapshots where applicable. Completed units have seals; failures remain recorded. Recovery accepts only an exact revalidated contiguous sealed prefix and never reruns an unsealed unit selectively. Native and resource batches are analyzed separately.

Before drawing conclusions, all counts and identities must be accepted. A/A envelopes, paired ten-seed effects and the frozen 54-comparison interval rule determine which timing effects are distinguishable. No result authorizes changes to R6, Event16, workloads or statistical thresholds. S3 is outside this stage.
