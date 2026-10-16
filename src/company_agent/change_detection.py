import html
import re
import unicodedata
from datetime import datetime, timezone
from typing import Optional, Dict, Any, Tuple, List
from company_agent.logging_config import logger


# Common web navigational / boilerplate phrases to strip during text comparison
BOILERPLATE_PATTERNS = [
    re.compile(r"^\s*skip\s+to\s+(?:main\s+)?content\s*[\.\:\-]?\s*", re.IGNORECASE),
    re.compile(r"^\s*(?:accept|manage|all)\s+cookies?\s*[\.\:\-]?\s*", re.IGNORECASE),
    re.compile(r"^\s*cookie\s+(?:policy|settings|notice)\s*[\.\:\-]?\s*", re.IGNORECASE),
    re.compile(r"^\s*menu\s+navigation\s*[\.\:\-]?\s*", re.IGNORECASE),
]


def clean_text_for_comparison(text: str) -> str:
    """Normalizes string for material comparison by removing boilerplate, unicode artifacts, and irregular spacing."""
    if not text:
        return ""
    # Unescape HTML entities
    s = html.unescape(str(text))
    # Unicode NFKC normalization (handles ligatures, special quotes, fullwidth, non-breaking spaces)
    s = unicodedata.normalize("NFKC", s)
    # Replace non-breaking spaces and other irregular spaces
    s = s.replace("\xa0", " ").replace("\u200b", "")
    # Strip known boilerplate prefixes
    for pat in BOILERPLATE_PATTERNS:
        s = pat.sub("", s)
    # Collapse multiple whitespace/newlines to single space
    s = re.sub(r"\s+", " ", s).strip().lower()
    # Strip trailing punctuation variations (.,;:)
    s = re.sub(r"[\.,;:!\?]+$", "", s).strip()
    return s


def is_material_difference(old_val: Any, new_val: Any) -> bool:
    """Determines whether a value change is substantive and material, ignoring cosmetic formatting."""
    if old_val is None and new_val is None:
        return False
    if old_val is None or new_val is None:
        return True

    # Numeric comparisons
    if isinstance(old_val, (int, float)) and isinstance(new_val, (int, float)):
        # For floating point or integers, detect non-trivial delta
        return abs(float(old_val) - float(new_val)) > 1e-4

    # List comparisons (e.g. business activities, management leadership)
    if isinstance(old_val, list) and isinstance(new_val, list):
        clean_old_list = sorted([clean_text_for_comparison(str(x)) for x in old_val if x])
        clean_new_list = sorted([clean_text_for_comparison(str(x)) for x in new_val if x])
        return clean_old_list != clean_new_list

    # String comparisons (normalize case, whitespace, boilerplate, punctuation)
    clean_old = clean_text_for_comparison(str(old_val))
    clean_new = clean_text_for_comparison(str(new_val))

    if clean_old == clean_new:
        return False

    # For longer text (e.g. descriptions > 40 chars), check if token similarity is virtually identical (>95%)
    if len(clean_old) > 40 and len(clean_new) > 40:
        old_words = set(clean_old.split())
        new_words = set(clean_new.split())
        if old_words and new_words:
            intersection = old_words & new_words
            union = old_words | new_words
            jaccard = len(intersection) / len(union)
            # If word overlap is >= 95% and length ratio is close, it's just minor formatting jitter
            len_ratio = min(len(clean_old), len(clean_new)) / max(len(clean_old), len(clean_new))
            if jaccard >= 0.95 and len_ratio >= 0.95:
                return False

    return True


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
