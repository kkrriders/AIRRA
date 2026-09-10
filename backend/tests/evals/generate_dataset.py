"""
Deterministically generate the AIRRA eval incident corpus.

    python -m tests.evals.generate_dataset                 # default 240 incidents
    python -m tests.evals.generate_dataset --count 300 --seed 7

Writes JSONL to tests/evals/dataset/incidents.jsonl — one incident per line.
Committed to the repo so CI runs the benchmark without regenerating.
"""
from __future__ import annotations

import argparse
import json
import random
import sys
from pathlib import Path

BACKEND_ROOT = Path(__file__).parent.parent.parent
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from tests.evals.archetypes import ARCHETYPES, REMEDIATION  # noqa: E402

DATASET_DIR = Path(__file__).parent / "dataset"
DATASET_PATH = DATASET_DIR / "incidents.jsonl"
DEFAULT_COUNT = 240
DEFAULT_SEED = 42


def build_corpus(count: int, seed: int) -> list[dict]:
    rng = random.Random(seed)
    per_archetype = count // len(ARCHETYPES)
    incidents: list[dict] = []

    for builder in ARCHETYPES:
        for i in range(per_archetype):
            spec = builder(rng)
            incidents.append(
                {
                    "id": f"{spec.archetype}-{i:03d}",
                    "archetype": spec.archetype,
                    "service": spec.service,
                    "description": spec.description,
                    "metric_window": {
                        "metric_name": spec.metric_name,
                        "values": [round(v, 4) for v in spec.values],
                    },
                    "clean_window": {
                        "metric_name": spec.metric_name,
                        "values": [round(v, 4) for v in spec.clean_values],
                    },
                    "ground_truth": {
                        "root_cause_category": spec.category,
                        "remediation_action": REMEDIATION[spec.category],
                        "severity": spec.severity,
                        "blast_radius_services": spec.blast_radius,
                    },
                    "distractor_categories": spec.distractors,
                }
            )

    rng.shuffle(incidents)
    return incidents


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--count", type=int, default=DEFAULT_COUNT)
    parser.add_argument("--seed", type=int, default=DEFAULT_SEED)
    args = parser.parse_args()

    corpus = build_corpus(args.count, args.seed)
    DATASET_DIR.mkdir(exist_ok=True)
    with open(DATASET_PATH, "w", encoding="utf-8") as f:
        for row in corpus:
            f.write(json.dumps(row) + "\n")

    by_arch: dict[str, int] = {}
    for row in corpus:
        by_arch[row["archetype"]] = by_arch.get(row["archetype"], 0) + 1

    print(f"Wrote {len(corpus)} incidents -> {DATASET_PATH.relative_to(BACKEND_ROOT)}")
    for arch, n in sorted(by_arch.items()):
        print(f"  {arch:<28} {n}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
