"""
Data Normalization Module for Entity Resolution.

Standardizes person identity attributes (names, emails, phone numbers)
to ensure deterministic, high-precision matching across disparate source systems.
"""

import re
from typing import Any, Dict, Optional
import pandas as pd


def normalize_email(email: Any) -> Optional[str]:
    """
    Normalize email address:
    - Strip leading/trailing whitespaces.
    - Convert to lowercase.
    - Return None if empty, null, or string representation of null.
    """
    if email is None or pd.isna(email):
        return None

    cleaned = str(email).strip().lower()

    if not cleaned or cleaned in ("nan", "none", "null", "undefined"):
        return None

    return cleaned


def normalize_name(name: Any) -> Optional[str]:
    """
    Normalize full name:
    - Strip leading/trailing whitespaces.
    - Collapse multiple internal whitespace characters into a single space.
    - Standardize to Title Case for consistent comparison.
    - Return None if empty or null.
    """
    if name is None or pd.isna(name):
        return None

    cleaned = str(name).strip()
    cleaned = re.sub(r"\s+", " ", cleaned)

    if not cleaned or cleaned.lower() in ("nan", "none", "null", "undefined"):
        return None

    return cleaned.title()


def normalize_phone(phone: Any) -> Optional[str]:
    """
    Normalize phone number:
    - Strip all non-digit characters (formatting spaces, parentheses, hyphens, plus signs).
    - Handle standard international prefixes (e.g. +91 for 10-digit numbers, +1 for US).
    - Return a clean digit string (typically 10 digits) or None if invalid/empty.
    """
    if phone is None or pd.isna(phone):
        return None

    raw = str(phone).strip()
    digits = re.sub(r"\D", "", raw)

    if not digits:
        return None

    # Handle common 11 or 12 digit prefixes (e.g. leading 0, 91 for India, 1 for North America)
    if len(digits) == 12 and digits.startswith("91"):
        digits = digits[2:]
    elif len(digits) == 11 and digits.startswith("0"):
        digits = digits[1:]
    elif len(digits) == 11 and digits.startswith("1"):
        digits = digits[1:]

    return digits if digits else None


def normalize_record(record: Dict[str, Any]) -> Dict[str, Any]:
    """
    Return a copy of the record with normalized fields added:
    - normalized_name
    - normalized_email
    - normalized_phone
    """
    normalized = dict(record)
    normalized["normalized_name"] = normalize_name(record.get("full_name"))
    normalized["normalized_email"] = normalize_email(record.get("email"))
    normalized["normalized_phone"] = normalize_phone(record.get("phone"))
    return normalized


def normalize_dataframe(df: pd.DataFrame) -> pd.DataFrame:
    """
    Apply normalization across a pandas DataFrame of source records,
    adding 'normalized_name', 'normalized_email', and 'normalized_phone' columns.
    """
    df_out = df.copy()

    if "full_name" in df_out.columns:
        df_out["normalized_name"] = df_out["full_name"].apply(normalize_name)
    else:
        df_out["normalized_name"] = None

    if "email" in df_out.columns:
        df_out["normalized_email"] = df_out["email"].apply(normalize_email)
    else:
        df_out["normalized_email"] = None

    if "phone" in df_out.columns:
        df_out["normalized_phone"] = df_out["phone"].apply(normalize_phone)
    else:
        df_out["normalized_phone"] = None

    return df_out

