"""Norwegian organisation number validation and entity resolution logic.

Implements the official Norwegian Brønnøysund weighted-modulus 11 algorithm,
string normalization, identifier extraction, legal name comparison, and
strict entity resolution policies.
"""

import re
from typing import Optional, Tuple, List, Set


# Official modulus 11 weights for 9-digit Norwegian organisation numbers
MOD11_WEIGHTS: List[int] = [3, 2, 7, 6, 5, 4, 3, 2]

# Common Norwegian legal corporate entity form suffixes
NORWEGIAN_LEGAL_FORMS: Set[str] = {
    "as", "a/s", "asa", "enk", "ans", "da", "ks", "sa", "nuf", "stiftelse",
    "ba", "iiks", "fkf", "kf", "interkommunalt selskap", "allmennaksjeselskap",
    "aksjeselskap", "enkeltpersonforetak"
}


class InvalidOrganisationNumberError(ValueError):
    """Raised when an organisation number fails length, character, or checksum validation."""
    pass


def normalize_organisation_number(org_nr: str) -> str:
    """Normalizes an organisation number string by removing whitespace, dots, and hyphens.

    Args:
        org_nr: Raw input string (e.g. ' 923 609 016 ' or '923-609-016')

    Returns:
        Normalized digits string (e.g. '923609016')
    """
    if not isinstance(org_nr, (str, int)):
        raise InvalidOrganisationNumberError(f"Organisation number must be a string or integer, got {type(org_nr).__name__}")
    cleaned = re.sub(r"[\s\.\-]+", "", str(org_nr).strip())
    return cleaned


def calculate_mod11_control_digit(first_8_digits: str) -> Optional[int]:
    """Calculates the 9th control digit using the official weighted modulus 11 algorithm.

    Args:
        first_8_digits: String of exactly 8 numeric digits.

    Returns:
        The expected control digit (0-9), or None if the remainder is 1 (which would
        yield a control digit of 10, invalid under modulus 11 rules).
    """
    if len(first_8_digits) != 8 or not first_8_digits.isdigit():
        return None

    weighted_sum = sum(int(digit) * weight for digit, weight in zip(first_8_digits, MOD11_WEIGHTS))
    remainder = weighted_sum % 11

    if remainder == 0:
        return 0
    elif remainder == 1:
        # A remainder of 1 gives a control digit of 10, which cannot be represented as a single digit
        return None
    else:
        return 11 - remainder


def validate_organisation_number(org_nr: str) -> Tuple[bool, str]:
    """Validates a Norwegian organisation number.

    Validation steps:
    1. Clean whitespace and formatting.
    2. Check that length is exactly 9 digits.
    3. Calculate the modulus 11 checksum of the first 8 digits.
    4. Verify that the calculated control digit equals the 9th digit.

    Args:
        org_nr: The organisation number to validate.

    Returns:
        Tuple of (is_valid: bool, normalized_or_error_message: str)
    """
    try:
        normalized = normalize_organisation_number(org_nr)
    except InvalidOrganisationNumberError as e:
        return False, str(e)

    if len(normalized) != 9:
        return False, f"Organisation number must be exactly 9 digits, got {len(normalized)} ('{normalized}')"

    if not normalized.isdigit():
        return False, f"Organisation number must contain only numeric digits: '{normalized}'"

    first_8 = normalized[:8]
    expected_control = calculate_mod11_control_digit(first_8)

    if expected_control is None:
        return False, f"Organisation number '{normalized}' produces an invalid modulus-11 control digit (10)"

    actual_control = int(normalized[8])
    if actual_control != expected_control:
        return False, (
            f"Checksum mismatch for '{normalized}': expected control digit "
            f"{expected_control}, but got {actual_control}"
        )

    return True, normalized


def assert_valid_organisation_number(org_nr: str) -> str:
    """Validates an organisation number and returns the normalized string, or raises InvalidOrganisationNumberError."""
    is_valid, result = validate_organisation_number(org_nr)
    if not is_valid:
        raise InvalidOrganisationNumberError(result)
    return result


def extract_organisation_numbers(text: str) -> List[str]:
    """Finds and extracts all valid Norwegian organisation numbers from arbitrary text.

    Args:
        text: Free text, HTML, or document content.

    Returns:
        List of distinct valid 9-digit organisation numbers found.
    """
    if not text:
        return []

    # Look for candidate sequences: 9 digits with optional spaces or hyphens (e.g. 923 609 016 or 923-609-016)
    # Prefixed optionally by 'org', 'orgnr', 'organisasjonsnummer', 'mva', 'no'
    patterns = [
        r"\b(\d{3}[\s\.\-]?\d{3}[\s\.\-]?\d{3})\b",
        r"(?:org\.?(?:nr\.?|nummer)?|mva|foretaksregisteret)\s*[:#]?\s*(\d{3}[\s\.\-]?\d{3}[\s\.\-]?\d{3})",
    ]

    candidates: Set[str] = set()
    for pat in patterns:
        for match in re.finditer(pat, text, re.IGNORECASE):
            raw = match.group(1)
            cleaned = re.sub(r"[\s\.\-]+", "", raw)
            if len(cleaned) == 9 and cleaned.isdigit():
                candidates.add(cleaned)

    valid_numbers = []
    for candidate in candidates:
        is_valid, normalized = validate_organisation_number(candidate)
        if is_valid and normalized not in valid_numbers:
            valid_numbers.append(normalized)

    return sorted(valid_numbers)


def normalize_company_name(name: str) -> str:
    """Normalizes a company name for entity resolution comparison.

    Strips common legal suffixes (AS, ASA, etc.), special punctuation, and case.
    """
    if not name:
        return ""

    lowered = name.lower().strip()
    # Remove punctuation
    cleaned = re.sub(r"[,\.\-\/\\(\)\[\]]+", " ", lowered)
    tokens = cleaned.split()

    # Filter out corporate suffixes
    filtered_tokens = [t for t in tokens if t not in NORWEGIAN_LEGAL_FORMS]

    return " ".join(filtered_tokens).strip()


def verify_entity_resolution(
    requested_org_nr: str,
    registry_legal_name: str,
    source_org_nr: Optional[str] = None,
    source_name: Optional[str] = None,
    source_domain: Optional[str] = None,
    official_domain: Optional[str] = None,
) -> Tuple[str, str, float]:
    """Defensible entity resolution algorithm.

    Never merges companies solely because their names, addresses, or domains look similar.

    Returns:
        Tuple of (status, explanation, confidence_score)
        Statuses:
          - 'VERIFIED_MATCH': Strict match on organisation number or exact legal name + domain.
          - 'CONFLICT_MISMATCH': Source contains a conflicting valid organisation number.
          - 'SECONDARY_SUPPORTED': Secondary source without org nr, but matching verified domain & name.
          - 'UNVERIFIED': Insufficient or ambiguous proof.
          - 'QUARANTINED': Conflicting evidence that must not enter database as fact.
    """
    req_clean = assert_valid_organisation_number(requested_org_nr)

    # 1. Direct Organisation Number verification
    if source_org_nr:
        try:
            src_clean = normalize_organisation_number(source_org_nr)
            if src_clean == req_clean:
                return (
                    "VERIFIED_MATCH",
                    f"Direct organisation number match ({req_clean}) in source",
                    1.0,
                )
            else:
                return (
                    "CONFLICT_MISMATCH",
                    f"Conflict: Source mentions organisation number '{src_clean}', but requested is '{req_clean}'",
                    0.0,
                )
        except InvalidOrganisationNumberError:
            pass

    # 2. Check if official domain matches source domain
    domain_match = False
    if source_domain and official_domain:
        s_dom = source_domain.lower().replace("www.", "").strip()
        o_dom = official_domain.lower().replace("www.", "").strip()
        if s_dom == o_dom or s_dom.endswith("." + o_dom):
            domain_match = True

    # 3. Check legal name normalization
    name_match = False
    if source_name and registry_legal_name:
        norm_registry = normalize_company_name(registry_legal_name)
        norm_source = normalize_company_name(source_name)
        if norm_registry and norm_source:
            if norm_registry == norm_source:
                name_match = True
            elif norm_registry in norm_source or norm_source in norm_registry:
                # Substring match
                name_match = True

    # 4. Evaluation policy
    if domain_match and name_match:
        return (
            "SECONDARY_SUPPORTED",
            f"Secondary source verified via official domain '{official_domain}' and matching legal name '{registry_legal_name}'",
            0.85,
        )
    elif domain_match and not name_match:
        return (
            "UNVERIFIED",
            f"Domain '{source_domain}' matches official domain, but source legal name could not be definitively reconciled",
            0.4,
        )
    elif name_match and not domain_match:
        return (
            "UNVERIFIED",
            f"Name '{source_name}' resembles registered name '{registry_legal_name}', but lacks organisation number or official domain association",
            0.3,
        )
    else:
        return (
            "UNVERIFIED",
            "Neither organisation number, verified domain, nor registered legal name confirmed in source",
            0.1,
        )
