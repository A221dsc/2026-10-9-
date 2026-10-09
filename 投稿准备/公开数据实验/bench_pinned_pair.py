"""Pinned, interleaved paired runner for the public-data benchmark.

Two problems with the frozen protocol this fixes:

1. `run_formal.py` records `affinity: not pinned`. On this machine the 20
   logical processors are 6 P-cores (logical 0-11) plus 8 E-cores (logical
   12-19), and the E-cores are ~1.4x slower even on a pure-ALU kernel. A run
   that happens to land on an E-core differs from one on a P-core by more than
   any effect the study is trying to measure, so every run here is pinned with
   `pin_launch.exe` to an explicit mask.

2. Arms were executed in separate sweeps. Any thermal or background drift
   between sweeps enters the comparison as a difference between the arms. Here
   the arms alternate *within* each round, so drift hits both arms equally.

The same tool measures the A/A floor: pass the same method as both arms
(`--arms A1=EndpointGated,A2=EndpointGated`) and the reported ratios are pure
machine noise, which is what any claimed A/B effect must clear.

Usage
-----
  # A/A noise floor, pinned to P-core logical 3
  python bench_pinned_pair.py --mask 0x8 --rounds 10 \
      --arms A1=EndpointGated,A2=EndpointGated \
      --cells 2024-01:ordered_sparse:300,2024-01:ordered_sparse:301 \
      --out aa_floor.csv

  # A/B, interleaved
  python bench_pinned_pair.py --mask 0x8 --rounds 10 \
      --arms EG=EndpointGated,CG=CountGate \
      --cells 2024-01:ordered_sparse:300 \
      --out eg_vs_cg.csv
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
import os
import statistics
import subprocess
import sys
import tempfile
from dataclasses import dataclass

PROTOCOL = {"initial": 262144, "units": 32768}
MONTHS = {
    "2024-01": ("data/tlc_2024_01_uint64.bin", 31),
    "2024-02": ("data/tlc_2024_02_uint64.bin", 29),
}
CSV_COLUMNS = [
    "cell", "month", "workload", "seed", "arm", "round", "order_index",
    "affinity_mask", "affinity_logical", "core_kind",
    "total_ns", "build_ns", "online_ns", "tree_buckets", "promotions",
    "conversion_ns", "status", "exit_code",
]


@dataclass(frozen=True)
class Cell:
    month: str
    workload: str
    seed: int

    @property
    def key(self) -> str:
        return f"{self.month}:{self.workload}:{self.seed}"


@dataclass(frozen=True)
class Arm:
    name: str
    method: str


def parse_cells(spec: str) -> list[Cell]:
    cells = []
    for item in spec.split(","):
        item = item.strip()
        if not item:
            continue
        parts = item.split(":")
        if len(parts) != 3:
            raise SystemExit(f"cell must be month:workload:seed, got {item!r}")
        month, workload, seed = parts
        if month not in MONTHS:
            raise SystemExit(f"unknown month {month!r} (known: {sorted(MONTHS)})")
        cells.append(Cell(month, workload, int(seed)))
    if not cells:
        raise SystemExit("no cells given")
    return cells


def parse_arms(spec: str) -> list[Arm]:
    arms = []
    for item in spec.split(","):
        item = item.strip()
        if not item:
            continue
        if "=" not in item:
            raise SystemExit(f"arm must be NAME=Method, got {item!r}")
        name, method = item.split("=", 1)
        arms.append(Arm(name, method))
    if len(arms) < 2:
        raise SystemExit("need at least two arms to form pairs")
    return arms


def run_once(args, cell: Cell, arm: Arm, run_dir: str) -> dict:
    data, days = MONTHS[cell.month]
    out_path = os.path.join(run_dir, f"{cell.key.replace(':', '_')}__{arm.name}.csv")
    command = [
        args.pin_launch,
        args.mask,
        os.path.abspath(args.exe),
        "--data", data,
        "--month", cell.month,
        "--days", str(days),
        "--initial", str(PROTOCOL["initial"]),
        "--units", str(PROTOCOL["units"]),
        "--seed", str(cell.seed),
        "--reps", "1",
        "--methods", arm.method,
        "--workloads", cell.workload,
        "--out", out_path,
    ]
    completed = subprocess.run(command, capture_output=True, text=True)
    exit_code = completed.returncode
    if exit_code != 0:
        return {"status": f"FAILED(rc={exit_code}) {completed.stderr.strip()[:200]}",
                "exit_code": exit_code}
    with open(out_path, newline="") as handle:
        rows = list(csv.DictReader(handle))
    if len(rows) != 1:
        return {"status": f"EXPECTED_1_ROW_GOT_{len(rows)}", "exit_code": exit_code}
    row = rows[0]
    return {
        "status": row["status"],
        "exit_code": exit_code,
        "total_ns": int(row["total_ns"]),
        "build_ns": int(row["build_ns"]),
        "online_ns": int(row["online_ns"]),
        "tree_buckets": int(row["tree_buckets"]),
        "promotions": int(row["promotions"]),
        "conversion_ns": int(row["conversion_ns"]),
    }


def sha256_file(path: str) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def load_topology(exe: str) -> dict[int, str]:
    """logical processor -> 'P' or 'E', read from the Windows hybrid topology.

    A cheap --iters run is enough: the classification comes from
    EfficiencyClass, not from the timing.
    """
    if not os.path.exists(exe):
        return {}
    completed = subprocess.run([exe, "--iters", "1000"], capture_output=True, text=True)
    if completed.returncode != 0:
        return {}
    topology: dict[int, str] = {}
    for line in completed.stdout.splitlines():
        if line.startswith("#") or line.startswith("logical,"):
            continue
        parts = line.split(",")
        if len(parts) >= 3:
            topology[int(parts[0])] = parts[2]
    return topology


def describe_mask(mask: str, topology: dict[int, str]) -> tuple[str, str]:
    """Return (comma-joined logical processors, core kind) for an affinity mask."""
    value = int(mask, 0)
    logical = [index for index in range(64) if (value >> index) & 1]
    kinds = {topology.get(index, "?") for index in logical}
    if not topology:
        kind = "unknown"
    elif kinds == {"P"}:
        kind = "P"
    elif kinds == {"E"}:
        kind = "E"
    elif "?" in kinds:
        kind = "unknown"
    else:
        kind = "mixed"
    return ",".join(str(index) for index in logical), kind


def position_balanced_ratios(aligned: dict[int, dict[str, float]],
                             arms: list, block: int = 2,
                             numerator: int = 1) -> list[float]:
    """Arm-ratio per 2-round block, positional effect cancelled exactly.

    Counterbalanced rotation puts each arm in each position once per 2 rounds.
    If being scheduled first costs a fixed factor k, then within a block
    r0 = (A_num/A_den) * k^s and r1 = (A_num/A_den) / k^s, so the geometric mean
    sqrt(r0*r1) is the position-free ratio. Averaging per-round ratios would
    only cancel k approximately, and taking their median would not cancel it at
    all when the round count is odd.
    """
    rounds = sorted(aligned)
    ratios = []
    for start in range(0, len(rounds) - block + 1, block):
        window = [aligned[r] for r in rounds[start:start + block]]
        if not all(all(a.name in w for a in arms) for w in window):
            continue
        numerator_product = 1.0
        denominator_product = 1.0
        for w in window:
            denominator = w[arms[0].name] if numerator else w[arms[1].name]
            numerator_value = w[arms[1].name] if numerator else w[arms[0].name]
            numerator_product *= numerator_value
            denominator_product *= denominator
        ratios.append((numerator_product / denominator_product) ** (1.0 / block))
    return ratios


def sign_test_p(wins: int, n: int) -> float:
    """Exact two-sided binomial test against p=0.5, ties excluded."""
    if n == 0:
        return float("nan")
    tail = sum(math.comb(n, k) for k in range(min(wins, n - wins) + 1))
    return min(1.0, 2.0 * tail / (2 ** n))


def summarise(pairs: list[tuple[float, float]], numerator: int) -> dict:
    """pairs are (arm_values...) aligned per round; ratio = num / den."""
    ratios = []
    for values in pairs:
        den = values[0] if numerator else values[1]
        num = values[1] if numerator else values[0]
        if den > 0:
            ratios.append(num / den)
    if not ratios:
        return {}
    ratios_sorted = sorted(ratios)
    n = len(ratios)
    wins = sum(1 for r in ratios if r > 1.0)
    losses = sum(1 for r in ratios if r < 1.0)
    return {
        "n": n,
        "median": statistics.median(ratios),
        "q1": ratios_sorted[int(0.25 * (n - 1))],
        "q3": ratios_sorted[int(0.75 * (n - 1))],
        "min": min(ratios),
        "max": max(ratios),
        "max_abs_dev": max(abs(r - 1.0) for r in ratios),
        "frac_over_5pct": sum(1 for r in ratios if abs(r - 1.0) > 0.05) / n,
        "numerator_wins": wins,
        "denominator_wins": losses,
        "sign_p": sign_test_p(wins, wins + losses),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--exe", default="benchmark_public_e0.exe")
    parser.add_argument("--pin-launch", default="./pin_launch.exe")
    parser.add_argument("--core-topology", default="./core_topology.exe",
                        help="used to label each run with its P/E core class")
    parser.add_argument("--mask", default="0x8",
                        help="affinity mask, decimal or 0x-hex (P-cores are 0x1..0x800)")
    parser.add_argument("--arms", required=True, help="NAME=Method[,NAME=Method...]")
    parser.add_argument("--cells", required=True, help="month:workload:seed[,...]")
    parser.add_argument("--rounds", type=int, default=10)
    parser.add_argument("--out", required=True)
    args = parser.parse_args()

    if not os.path.exists(args.exe):
        raise SystemExit(f"missing benchmark binary {args.exe}")
    if not os.path.exists(args.pin_launch):
        raise SystemExit(f"missing {args.pin_launch} (build pin_launch.cpp)")

    cells = parse_cells(args.cells)
    arms = parse_arms(args.arms)
    run_dir = tempfile.mkdtemp(prefix="pinned_run_")

    topology = load_topology(args.core_topology)
    affinity_logical, core_kind = describe_mask(args.mask, topology)
    if core_kind in ("unknown", "mixed"):
        print(f"# WARNING: mask {args.mask} resolves to {core_kind} cores "
              f"({affinity_logical}); an E-core run is not comparable to a P-core run.",
              flush=True)
    print(f"# affinity mask {args.mask} -> logical [{affinity_logical}] {core_kind}-core",
          flush=True)

    records = []
    for cell in cells:
        for round_index in range(args.rounds):
            # Counterbalanced rotation, not a random shuffle: with a small round
            # count a shuffle can repeat the same order every round, and the
            # first arm in a round is systematically slower (cold cache after
            # the previous cell). Rotating by the round index gives every arm
            # each position an equal number of times, so the position effect
            # cancels in the paired ratio. Deterministic and reproducible.
            order = [(round_index + i) % len(arms) for i in range(len(arms))]
            for order_index, arm_index in enumerate(order):
                arm = arms[arm_index]
                result = run_once(args, cell, arm, run_dir)
                record = {
                    "cell": cell.key, "month": cell.month, "workload": cell.workload,
                    "seed": cell.seed, "arm": arm.name, "round": round_index,
                    "order_index": order_index, "affinity_mask": args.mask,
                    "affinity_logical": affinity_logical, "core_kind": core_kind,
                }
                record.update(result)
                records.append(record)
                print(f"{cell.key} r{round_index} {arm.name:>4} {args.mask:>6} "
                      f"{result['status']} {result.get('total_ns', 0)}", flush=True)

    with open(args.out, "w", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=CSV_COLUMNS, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(records)

    # Per-cell statistics, computed once so the audit sidecar and the console
    # cannot disagree about what was measured.
    cell_stats: dict[str, dict] = {}
    for cell in cells:
        subset = [r for r in records if r["cell"] == cell.key and r["status"] == "PASS"]
        aligned: dict[int, dict[str, float]] = {}
        for record in subset:
            aligned.setdefault(record["round"], {})[record["arm"]] = record["total_ns"]
        pairs = [tuple(by_arm[a.name] for a in arms)
                 for by_arm in aligned.values()
                 if all(a.name in by_arm for a in arms)]
        cell_stats[cell.key] = {
            "raw": summarise(pairs, numerator=1),
            "position_balanced": position_balanced_ratios(aligned, arms, block=2, numerator=1),
        }

    # The revised protocol (stage 3b section 3.4c/d) requires the affinity mask
    # and the execution order to travel with the numbers, and every batch to
    # carry a run of the A/A floor. Both live here rather than only in prose.
    passed = [r for r in records if r["status"] == "PASS"]
    audit = {
        "runner": "bench_pinned_pair.py",
        "runner_sha256": sha256_file(__file__),
        "exe": os.path.abspath(args.exe),
        "exe_sha256": sha256_file(args.exe),
        "pin_launch": os.path.abspath(args.pin_launch),
        "pin_launch_sha256": sha256_file(args.pin_launch),
        "affinity_mask": args.mask,
        "affinity_logical": affinity_logical,
        "core_kind": core_kind,
        "core_topology_source": os.path.abspath(args.core_topology),
        "core_topology_sha256": (sha256_file(args.core_topology)
                                 if os.path.exists(args.core_topology) else None),
        "core_topology_map": {str(k): v for k, v in sorted(topology.items())},
        "protocol": PROTOCOL,
        "days": {m: MONTHS[m][1] for m in sorted({c.month for c in cells})},
        "arms": {a.name: a.method for a in arms},
        "cells": [c.key for c in cells],
        "rounds": args.rounds,
        "order_policy": "counterbalanced rotation by round index",
        "runs_total": len(records),
        "runs_pass": len(passed),
        "runs_failed": len(records) - len(passed),
        "nonzero_exit_codes": sorted({r["exit_code"] for r in records
                                      if r.get("exit_code") not in (0, None)}),
        "is_aa_floor": len({a.method for a in arms}) == 1,
        "cell_statistics": cell_stats,
    }
    audit_path = args.out + ".audit.json"
    with open(audit_path, "w") as handle:
        json.dump(audit, handle, indent=2, sort_keys=True)
        handle.write("\n")

    if args.rounds % 2 != 0:
        print(f"\n# WARNING: --rounds {args.rounds} is odd, so the counterbalanced "
              f"rotation puts one arm first one extra time; the position-balanced "
              f"estimate drops the last round. Use an even round count.", flush=True)

    arm_ratio = f"{arms[1].name}/{arms[0].name}"
    print(f"\n=== paired ratios ({arm_ratio}; >1 means {arms[1].name} slower) ===")
    print(f"{'cell':<40} {'n':>3} {'median':>8} {'q1':>7} {'q3':>7} "
          f"{'maxdev':>7} {'>5%':>6} {'wins':>5} {'p':>8} {'pos-bal':>8}")
    for cell in cells:
        stats = cell_stats[cell.key]["raw"]
        blocked = cell_stats[cell.key]["position_balanced"]
        if not stats:
            print(f"{cell.key:<40} no complete pairs")
            continue
        blocked_text = f"{statistics.median(blocked):>8.4f}" if blocked else f"{'n/a':>8}"
        print(f"{cell.key:<40} {stats['n']:>3} {stats['median']:>8.4f} "
              f"{stats['q1']:>7.4f} {stats['q3']:>7.4f} {stats['max_abs_dev']:>7.3f} "
              f"{stats['frac_over_5pct']:>6.0%} {stats['numerator_wins']:>5} "
              f"{stats['sign_p']:>8.4f} {blocked_text}")
    print("\n'median' pools every round; 'pos-bal' releases the position effect by "
          "taking the geometric mean within each 2-round block.")
    print(f"wrote {args.out} and {audit_path}  "
          f"(arm order within round: counterbalanced rotation)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
