# --- START OF FILE relevance_ai.py ---
"""AI relevance backend: scores an offer against a natural-language profile with Claude.

Used when CONFIG['FILTER_MODE'] == 'ai'. A single Messages API call per offer with
structured outputs returns a validated verdict. On any failure (no API key, network
error) it returns None so the pipeline degrades gracefully to "no filter".
"""
import logging
import os

from pydantic import BaseModel, Field

from config import CONFIG

logger = logging.getLogger(__name__)

_DEFAULT_PROFILE = (
    "No specific preferences provided; treat technically solid software roles as relevant."
)

_RUBRIC = (
    "You are a job-offer relevance filter. Given the user's preferences and a single job "
    "offer, decide whether the offer is relevant to the user. Return:\n"
    "- relevant: true if the user would likely want to be notified about it, else false.\n"
    "- score: 0-100, how well the offer matches the preferences (0 = irrelevant, 100 = ideal).\n"
    "- reason: one concise sentence explaining the decision.\n"
    "Be strict: if the offer clearly conflicts with the stated preferences (wrong stack, "
    "excluded company type, too little remote, salary far below target), score it low."
)

# Lazily-built client, memoised across calls.
_client = None


class RelevanceVerdict(BaseModel):
    relevant: bool
    score: int = Field(ge=0, le=100)
    reason: str


def _get_client():
    """Return a memoised Anthropic client, or None if no API key is configured."""
    global _client
    if _client is not None:
        return _client
    api_key = CONFIG.get("ANTHROPIC_API_KEY") or os.getenv("ANTHROPIC_API_KEY")
    if not api_key:
        return None
    import anthropic

    _client = anthropic.Anthropic(api_key=api_key)
    return _client


def _load_profile():
    if CONFIG.get("AI_USER_PROFILE"):
        return CONFIG["AI_USER_PROFILE"]
    path = CONFIG.get("AI_PROFILE_PATH")
    if path and os.path.exists(path):
        try:
            with open(path, "r", encoding="utf-8") as f:
                content = f.read().strip()
                if content:
                    return content
        except Exception as e:
            logger.warning(f"Failed to read AI profile from {path}: {e}")
    return _DEFAULT_PROFILE


def _format_offer(offer, skills, languages):
    """Render the offer + its skills/languages as a compact text block for the model."""
    company = (offer.get("company") or {}).get("name", "Unknown")
    lines = [
        f"Position: {offer.get('position', 'Unknown')}",
        f"Company: {company}",
        f"Remote: {offer.get('remotePercentage')}%",
        f"Salary: {offer.get('salaryFrom')} - {offer.get('salaryTo')}",
        f"Locations: {', '.join(str(l) for l in (offer.get('locations') or [])) or 'N/A'}",
    ]
    if isinstance(skills, dict):
        for category in ("must", "nice", "extra"):
            names = [s.get("skill") for s in (skills.get(category) or []) if s.get("skill")]
            if names:
                lines.append(f"{category.capitalize()} skills: {', '.join(names)}")
    if languages:
        langs = [f"{l.get('name')} ({l.get('level')})" for l in languages if l.get("name")]
        if langs:
            lines.append(f"Languages: {', '.join(langs)}")
    return "\n".join(lines)


def score_with_ai(offer, skills, languages):
    """Score an offer with Claude. Returns the verdict dict, or None on failure."""
    client = _get_client()
    if client is None:
        logger.error("FILTER_MODE='ai' but ANTHROPIC_API_KEY is not set; skipping filter.")
        return None

    system = [
        {"type": "text", "text": _RUBRIC},
        {
            "type": "text",
            "text": f"User preferences (what counts as relevant):\n{_load_profile()}",
            "cache_control": {"type": "ephemeral"},
        },
    ]
    try:
        response = client.messages.parse(
            model=CONFIG["AI_MODEL"],
            max_tokens=256,
            system=system,
            messages=[{"role": "user", "content": _format_offer(offer, skills, languages)}],
            output_format=RelevanceVerdict,
        )
        verdict = response.parsed_output
        return {
            "relevant": bool(verdict.relevant),
            "score": int(verdict.score),
            "reason": verdict.reason,
        }
    except Exception as e:
        logger.error(f"AI relevance scoring failed for offer {offer.get('id')}: {e}", exc_info=True)
        return None

# --- END OF FILE relevance_ai.py ---
