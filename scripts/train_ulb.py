"""Train, compare, and evaluate ULB benchmark models."""

import argparse
import json
from pathlib import Path

from scamtrace.ml import DEFAULT_DATASET, train_models


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--dataset",
        type=Path,
        default=DEFAULT_DATASET,
        help="Path to the locally stored ULB/Worldline CSV.",
    )
    args = parser.parse_args()
    result = train_models(args.dataset)
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
