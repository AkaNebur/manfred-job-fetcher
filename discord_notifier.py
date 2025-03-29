# --- START OF FILE discord_notifier.py ---
import logging
from datetime import datetime
import time

from config import CONFIG
from database import get_job_skills_from_db
from manfred_api import http_session

logger = logging.getLogger(__name__)

def _format_skills_for_field(skill_list):
    """Formats a list of skill dictionaries into a string for an embed field."""
    lines = []
    for skill in skill_list:
        level_stars = "★" * skill.get('level', 0) if skill.get('level') else ""
        level_part = f" ({level_stars})" if level_stars else ""
        lines.append(f"• {skill.get('skill', 'N/A')}{level_part}")
    formatted_value = "\n".join(lines)
    # Keep truncation slightly lower than 1024 to account for potential title additions within the field
    # Discord field value limit is 1024 characters
    return formatted_value[:1020] + "..." if len(formatted_value) > 1020 else (formatted_value if formatted_value else None)

def _build_discord_embed(offer_dict):
    """Builds the Discord embed message for a job offer dictionary with stacked sections."""
    offer_id = offer_dict.get('id')
    if not offer_id:
        logger.error("Cannot build embed: Offer dictionary missing 'id'.")
        return None

    position = offer_dict.get('position', 'Unknown Position')
    company_data = offer_dict.get('company', {})
    company_name = company_data.get('name', 'Unknown Company')
    logo_url = company_data.get('logoDark', {}).get('url') if isinstance(company_data.get('logoDark'), dict) else None
    slug = offer_dict.get('slug', f"job-{offer_id}")
    job_url = f"https://www.getmanfred.com/es/job-offers/{offer_id}/{slug}"

    salary_from = offer_dict.get('salaryFrom')
    salary_to = offer_dict.get('salaryTo')
    salary_text = None
    if salary_from and salary_to:
        salary_text = f"{salary_from:,}€ - {salary_to:,}€".replace(',', '.')
    elif salary_from:
        salary_text = f"From {salary_from:,}€".replace(',', '.')
    elif salary_to:
        salary_text = f"Up to {salary_to:,}€".replace(',', '.')

    remote_percentage = offer_dict.get('remotePercentage')
    remote_text = f"{remote_percentage}% Remote" if remote_percentage is not None else None

    locations = offer_dict.get('locations', [])
    # Ensure locations is a list before joining
    locations_text = f"{', '.join(locations)}" if locations and isinstance(locations, list) else None

    skills_data = get_job_skills_from_db(offer_id)
    must_skills_text = _format_skills_for_field(skills_data.get('must', []))
    nice_skills_text = _format_skills_for_field(skills_data.get('nice', []))
    extra_skills_text = _format_skills_for_field(skills_data.get('extra', []))

    # --- Build Fields (No Columns/Inline) ---
    fields = []

    # --- Info Field ---
    info_lines = []
    if salary_text:
        info_lines.append(f"💰 **Salary:** {salary_text}")
    if remote_text:
        info_lines.append(f"🏠 **Remote:** {remote_text}")
    if locations_text:
        info_lines.append(f"📍 **Location:** {locations_text}")

    if info_lines:
        fields.append({
            "value": "\n".join(info_lines),
            "inline": False # Explicitly false, or omit entirely for default non-inline
        })

    # --- Skills Fields ---
    if must_skills_text:
        fields.append({
            "name": "🔒 Must Have Skills",
            "value": must_skills_text,
            "inline": False
        })
    if nice_skills_text:
        fields.append({
            "name": "✨ Nice to Have Skills",
            "value": nice_skills_text,
            "inline": False
        })
    if extra_skills_text:
        fields.append({
            "name": "📚 Extra Skills",
            "value": extra_skills_text,
            "inline": False
        })

    embed = {
        "title": f"{position} @ {company_name}",
        "description": "", # Keep description empty or add a small intro if needed
        "url": job_url,
        "color": 5814783, # Manfred purple-ish
        "timestamp": datetime.now().isoformat(),
        "footer": {"text": "Via Manfred Job Fetcher"},
        "fields": fields # Use the constructed fields list
    }
    if logo_url:
        embed["thumbnail"] = {"url": logo_url}

    # Limit total embed length (sum of title, desc, footer, author, fields) to 6000 chars
    # Limit field name to 256 chars, field value to 1024 chars
    # Limit number of fields to 25
    # Truncate description if needed (though it's empty here)

    return embed

def send_discord_notification(offer_dict):
    """Sends a single job offer embed to the configured Discord webhook."""
    webhook_url = CONFIG['DISCORD_WEBHOOK_URL']
    if not webhook_url:
        logger.warning("Discord webhook URL not configured. Skipping notification.")
        return False

    embed = _build_discord_embed(offer_dict)
    if not embed:
        logger.error(f"Could not build Discord embed for offer ID: {offer_dict.get('id', 'N/A')}")
        return False

    webhook_data = {
        # Content provides a pingable text part outside the embed
        "content": "",
        "embeds": [embed]
    }

    try:
        response = http_session.post(
            webhook_url,
            json=webhook_data,
            headers={"Content-Type": "application/json"},
            timeout=10 # Increased timeout slightly
        )
        response.raise_for_status() # Raises HTTPError for bad responses (4xx or 5xx)
        logger.info(f"Sent Discord notification successfully for offer ID: {offer_dict.get('id')}")
        # Consider adding a small delay even for single sends if rate limits are hit
        # time.sleep(0.5)
        return True
    except Exception as e:
        logger.error(f"Failed to send Discord webhook for offer ID {offer_dict.get('id', 'N/A')}: {e}", exc_info=True)
        # Handle specific errors like rate limits (429) if necessary
        return False

def send_batch_notifications(offer_dicts, batch_size=5, delay_seconds=1):
    """Sends a batch of new offers to Discord webhook, limited by batch_size with delays."""
    if not offer_dicts:
        logger.info("No offers provided for batch notification.")
        return 0

    webhook_url = CONFIG['DISCORD_WEBHOOK_URL']
    if not webhook_url:
        logger.warning("Discord webhook URL not configured. Skipping batch notification.")
        return 0

    sent_count = 0
    # Ensure we don't try to send more than available
    offers_to_send = offer_dicts[:batch_size]

    if not offers_to_send:
        logger.info("Offer list was provided, but resulted in an empty batch to send.")
        return 0

    logger.info(f"Attempting to send {len(offers_to_send)} notifications (batch limit {batch_size})...")

    for i, offer in enumerate(offers_to_send):
        # Add extra check in case offer dict itself is None or empty somehow
        if not offer or not offer.get('id'):
            logger.warning(f"Skipping invalid offer data at index {i} in batch.")
            continue

        if send_discord_notification(offer):
            sent_count += 1
            # Apply delay *after* sending, before the next one, but not after the last one
            if i < len(offers_to_send) - 1 and delay_seconds > 0:
                logger.debug(f"Waiting {delay_seconds}s before next notification...")
                time.sleep(delay_seconds)
        else:
            logger.warning(f"Failed to send notification for offer ID {offer.get('id', 'N/A')} in batch.")
            # Optional: Add a longer delay or break if a failure occurs, depending on desired robustness
            # time.sleep(delay_seconds * 2) # e.g., wait longer after a failure

    logger.info(f"Finished sending batch. Successfully sent {sent_count}/{len(offers_to_send)} notifications.")
    return sent_count

# --- END OF FILE discord_notifier.py ---