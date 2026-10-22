from pathlib import Path

import pandas as pd

RAW_DIR = Path("data/raw")
PROCESSED_DIR = Path("data/processed")


def load_games(path: Path) -> pd.DataFrame:
    """Load and validate an Oracle's Elixir CSV; return team rows only (position == 'team')."""
    raise NotImplementedError


def write_processed(df: pd.DataFrame, name: str) -> Path:
    """Write df to data/processed/<name>.parquet; return the path written."""
    raise NotImplementedError


def main() -> None:
    raise NotImplementedError("ingest pipeline not wired yet")


if __name__ == "__main__":
    main()
