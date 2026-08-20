from __future__ import annotations

from .schemas import RichBlockCandidate


def build_candidate_prompt(candidates: list[RichBlockCandidate]) -> str:
    """Expose identifiers and descriptions only, never trusted block data."""
    if not candidates:
        return ""
    lines = [
        "STRUCTURED_CONTENT_CANDIDATES",
        "You may place a candidate exactly once using [[BLOCK:candidate_id]].",
        "Do not invent IDs, JSON, fields, values, or XML/HTML components.",
        (
            "Keep the surrounding answer useful as ordinary Markdown because "
            "the server may remove or downgrade any block."
        ),
        (
            "When you place a valuation_summary or valuation_range candidate, "
            "do not repeat its valuation rows as a Markdown table; give the "
            "takeaway in prose instead."
        ),
    ]
    for candidate in candidates:
        hint = candidate.relevance_hint or candidate.block_type
        lines.append(
            f"- {candidate.block_id} | {candidate.block_type}: {hint[:300]}"
        )
    return "\n".join(lines)
