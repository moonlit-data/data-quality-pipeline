"""dqcheck: declarative data quality checks on CSV / Parquet files, run in DuckDB, with a report."""
from .config import ConfigError, load, parse
from .runner import run

__all__ = ["ConfigError", "load", "parse", "run"]
__version__ = "1.0.0"
