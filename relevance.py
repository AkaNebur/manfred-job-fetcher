# --- START OF FILE relevance.py ---
"""Relevance scoring layer.

A scorer takes an offer (Manfred API shape) plus its skills/languages and returns
a verdict dict: ``{"relevant": bool, "score": int, "reason": str}``.

Two backends are selectable via ``CONFIG['FILTER_MODE']``:
  - ``"off"``   -> no scoring (score_offer returns None; notify everything)
  - ``"rules"`` -> deterministic criteria questionnaire (this module)
  - ``"ai"``    -> Claude-based scorer (added in relevance_ai.py)
"""
import json
import logging

from config import CONFIG

logger = logging.getLogger(__name__)


# --- helpers ---------------------------------------------------------------

def _skill_names(skills):
    """Flatten the skills dict ({must, nice, extra}) into a lowercase name list."""
    names = []
    if not isinstance(skills, dict):
        return names
    for category in ("must", "nice", "extra"):
        for skill in skills.get(category, []) or []:
            name = (skill or {}).get("skill")
            if name:
                names.append(str(name).lower())
    return names


def load_rules(path):
    """Load the criteria questionnaire from a JSON file. Missing file -> empty rules."""
    if not path:
        return {}
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
            return data if isinstance(data, dict) else {}
    except FileNotFoundError:
        logger.warning(f"Filter rules file not found at {path}; treating all offers as relevant.")
        return {}
    except Exception as e:
        logger.error(f"Failed to load filter rules from {path}: {e}", exc_info=True)
        return {}


# --- rules backend ---------------------------------------------------------

def score_with_rules(offer, skills, languages, rules):
    """Score an offer against the criteria questionnaire.

    Hard criteria (any failure -> not relevant, score 0): excluded_skills,
    excluded_companies, position_excludes, min_salary, min_remote_percentage,
    required_skills_any, position_includes, locations_any. When all pass, the score
    is 60 plus 10 per matched required skill (capped at 100).
    """
    position = (offer.get("position") or "").lower()
    company = ((offer.get("company") or {}).get("name") or "").lower()
    remote = offer.get("remotePercentage")
    salary = offer.get("salaryTo") or offer.get("salaryFrom")
    locations = [str(loc).lower() for loc in (offer.get("locations") or [])]
    skill_names = _skill_names(skills)

    failures = []

    excluded_skills = [s.lower() for s in rules.get("excluded_skills", []) or []]
    hit = [s for s in excluded_skills if s in skill_names]
    if hit:
        failures.append(f"excluded skill(s): {', '.join(hit)}")

    for company_term in (rules.get("excluded_companies", []) or []):
        if company_term.lower() in company:
            failures.append(f"excluded company: {company_term}")

    for term in (rules.get("position_excludes", []) or []):
        if term.lower() in position:
            failures.append(f"excluded position term: {term}")

    min_salary = rules.get("min_salary")
    if min_salary is not None and salary is not None and salary < min_salary:
        failures.append(f"salary {salary} below minimum {min_salary}")

    min_remote = rules.get("min_remote_percentage")
    if min_remote is not None and remote is not None and remote < min_remote:
        failures.append(f"remote {remote}% below minimum {min_remote}%")

    required_any = [s.lower() for s in rules.get("required_skills_any", []) or []]
    matched_required = [s for s in required_any if s in skill_names]
    if required_any and not matched_required:
        failures.append(f"none of the required skills present: {', '.join(required_any)}")

    includes = [t.lower() for t in rules.get("position_includes", []) or []]
    if includes and not any(t in position for t in includes):
        failures.append("position does not match any required term")

    locations_any = [loc.lower() for loc in rules.get("locations_any", []) or []]
    if locations_any and not any(any(want in loc for loc in locations) for want in locations_any):
        failures.append("location does not match any allowed location")

    if failures:
        return {"relevant": False, "score": 0, "reason": "; ".join(failures)}

    score = min(100, 60 + 10 * len(matched_required))
    reason = "Passed all criteria"
    if matched_required:
        reason += f"; matched skills: {', '.join(matched_required)}"
    return {"relevant": True, "score": score, "reason": reason}


# --- dispatcher ------------------------------------------------------------

def score_offer(offer, skills, languages):
    """Score an offer using the configured backend.

    Returns the verdict dict, or None when filtering is disabled (FILTER_MODE='off').
    """
    mode = (CONFIG["FILTER_MODE"] or "off").lower()

    if mode == "off":
        return None

    if mode == "rules":
        rules = load_rules(CONFIG.get("FILTER_RULES_PATH"))
        return score_with_rules(offer, skills, languages, rules)

    if mode == "ai":
        try:
            from relevance_ai import score_with_ai
        except ImportError:
            logger.error("FILTER_MODE='ai' but the AI backend is not available; skipping filter.")
            return None
        return score_with_ai(offer, skills, languages)

    logger.warning(f"Unknown FILTER_MODE '{mode}'; skipping filter.")
    return None

# --- END OF FILE relevance.py ---
