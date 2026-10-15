"""Material change detection and historical version preservation."""

from datetime import datetime, timezone
from typing import Optional, Dict, Any, Tuple
from company_agent.logging_config import logger


def is_material_difference(old_val: Any, new_val: Any) -> bool:
    """Determines whether a value change is substantive and material."""
    if old_val is None and new_val is None:
        return False
    if old_val is None or new_val is None:
        return True

    # Numeric comparisons
    if isinstance(old_val, (int, float)) and isinstance(new_val, (int, float)):
        # For floating point or integers, detect non-trivial delta
        return abs(float(old_val) - float(new_val)) > 1e-4

    # String comparisons (normalize case and whitespace)
    str_old = str(old_val).strip().lower()
    str_new = str(new_val).strip().lower()

    return str_old != str_new


def detect_field_change(
    field_name: str,
    old_value: Any,
    new_value: Any,
    source_name: str = "registry",
    source_date: Optional[str] = None,
) -> Tuple[bool, Optional[str]]:
    """Detects material difference and produces a factual explanation.

    Returns:
        Tuple of (is_changed: bool, explanation: Optional[str])
    """
    if not is_material_difference(old_value, new_value):
        return False, None

    date_str = f" as of {source_date}" if source_date else ""

    if field_name == "status":
        explanation = f"Company status updated from '{old_value}' to '{new_value}'{date_str} based on {source_name}."
    elif field_name == "employee_count":
        explanation = f"Registered employee count changed from {old_value} to {new_value}{date_str} according to {source_name}."
    elif field_name in ("revenue", "operating_profit", "total_assets"):
        explanation = f"Financial metric '{field_name}' updated from {old_value} to {new_value}{date_str} supported by {source_name}."
    elif field_name == "address":
        explanation = f"Registered business address relocated from '{old_value}' to '{new_value}'{date_str} according to {source_name}."
    else:
        explanation = f"Field '{field_name}' updated from '{old_value}' to '{new_value}'{date_str} via {source_name}."

    return True, explanation
