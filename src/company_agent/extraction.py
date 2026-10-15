"""Evidence extraction, HTML sanitization, deduplication, and prompt-injection defense."""

import re
from typing import List
from bs4 import BeautifulSoup


# Prompt injection keywords to neutralize from untrusted web pages
_PROMPT_INJECTION_PATTERNS = [
    re.compile(r"ignore\s+(all\s+)?(previous|above)\s+instructions", re.IGNORECASE),
    re.compile(r"you\s+are\s+now\s+(an?\s+)?AI", re.IGNORECASE),
    re.compile(r"system\s*prompt", re.IGNORECASE),
    re.compile(r"reveal\s+(your\s+)?(secret|key|token|instruction)", re.IGNORECASE),
    re.compile(r"<\s*script[^>]*>.*?<\s*\/\s*script\s*>", re.IGNORECASE | re.DOTALL),
]


def sanitize_untrusted_text(text: str) -> str:
    """Neutralizes potential prompt injection markers and cleans suspicious instructions."""
    if not text:
        return ""

    sanitized = text
    for pattern in _PROMPT_INJECTION_PATTERNS:
        sanitized = pattern.sub("[BLOCKED_UNTRUSTED_INSTRUCTION]", sanitized)

    return sanitized


def extract_clean_text_from_html(html: str) -> str:
    """Converts HTML to clean, readable plain text.

    Removes navigation bars, footers, headers, cookie notices, scripts, and styles.
    """
    if not html:
        return ""

    soup = BeautifulSoup(html, "html.parser")

    # Remove unwanted tags
    for tag in soup(["script", "style", "noscript", "svg", "nav", "footer", "header", "aside"]):
        tag.decompose()

    # Remove cookie / consent banners by common class or id names
    for banner in soup.find_all(attrs={"class": re.compile(r"(cookie|consent|gdpr|banner|modal)", re.I)}):
        banner.decompose()
    for banner in soup.find_all(attrs={"id": re.compile(r"(cookie|consent|gdpr|banner|modal)", re.I)}):
        banner.decompose()

    # Get plain text
    text = soup.get_text(separator=" ", strip=True)
    # Collapse multiple whitespace
    cleaned = re.sub(r"\s+", " ", text).strip()

    return sanitize_untrusted_text(cleaned)


def extract_relevant_snippets(text: str, keywords: List[str], max_snippets: int = 5) -> List[str]:
    """Extracts bounded, deduplicated sentences/passages matching company keywords."""
    if not text:
        return []

    # Split into sentences
    sentences = re.split(r"(?<=[.!?])\s+", text)
    matches: List[str] = []
    seen = set()

    for sentence in sentences:
        s_clean = sentence.strip()
        if len(s_clean) < 20 or len(s_clean) > 500:
            continue

        lower_s = s_clean.lower()
        if any(kw.lower() in lower_s for kw in keywords):
            h = lower_s[:60]
            if h not in seen:
                seen.add(h)
                matches.append(s_clean)
                if len(matches) >= max_snippets:
                    break

    # If no keyword matches found, return first few sentences
    if not matches:
        for sentence in sentences[:max_snippets]:
            s_clean = sentence.strip()
            if 20 <= len(s_clean) <= 500:
                matches.append(s_clean)

    return matches
