"""Fetch the anonymized ULB/Worldline card fraud benchmark from OpenML."""

from pathlib import Path

from sklearn.datasets import fetch_openml


ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "data" / "raw" / "ulb_creditcard.csv"


def main() -> None:
    OUT.parent.mkdir(parents=True, exist_ok=True)
    if OUT.exists():
        print(f"Dataset already exists: {OUT}")
        return

    print("Fetching OpenML dataset 1597 (about 150 MB on first download)...")
    dataset = fetch_openml(data_id=1597, as_frame=True, parser="auto")
    frame = dataset.frame
    if frame is None or frame.empty:
        raise RuntimeError("OpenML returned an empty dataset.")

    # Normalize the target column name while preserving all source feature columns.
    target = dataset.target_names[0] if dataset.target_names else None
    if target and target in frame.columns and target != "Class":
        frame = frame.rename(columns={target: "Class"})
    if "Class" not in frame.columns:
        raise RuntimeError(f"Expected target column 'Class'; got {list(frame.columns)}")

    frame.to_csv(OUT, index=False)
    print(f"Saved {len(frame):,} rows and {len(frame.columns):,} columns to {OUT}")
    print(f"Columns: {', '.join(frame.columns)}")


if __name__ == "__main__":
    main()
