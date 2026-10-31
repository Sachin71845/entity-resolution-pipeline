"""
Pytest configuration and shared fixtures for Entity Resolution test suite.
"""

from pathlib import Path
import pytest
import pandas as pd

BASE_DIR = Path(__file__).resolve().parent.parent


@pytest.fixture
def sample_records_csv_path():
    return BASE_DIR / "data" / "input" / "source_records.csv"


@pytest.fixture
def expected_results_csv_path():
    return BASE_DIR / "data" / "expected" / "expected_results.csv"


@pytest.fixture
def empty_df():
    return pd.DataFrame(columns=[
        "source_system",
        "source_id",
        "full_name",
        "email",
        "phone",
        "source_updated_at"
    ])

