# --- START OF FILE discord_notifier.py ---
import logging
from datetime import datetime
import time

from config import CONFIG
from database import get_job_skills_from_db # To fetch skills for the embed
from manfred_api import http_session # Use the shared session for sending webhooks

logger = logging.getLogger(__name__)

def _build_discord_embed(offer_dict):
    """Builds the Discord embed message for a job offer dictionary."""
    offer_id = offer_dict.get('id')
    if not offer_id:
        logger.error("Cannot build embed: Offer dictionary missing 'id'.")
        return None

    # Extract basic info safely using .get()
    position = offer_dict.get('position', 'Unknown Position')
    company_data = offer_dict.get('company', {})
    company_name = company_data.get('name', 'Unknown Company')
    # Logo URL from the structure provided in the original code
    logo_url = company_data.get('logoDark', {}).get('url') if isinstance(company_data.get('logoDark'), dict) else None
    slug = offer_dict.get('slug', f"job-{offer_id}") # Default slug if missing
    job_url = f"https://www.getmanfred.com/es/job-offers/{offer_id}/{slug}"

    # Format salary
    salary_from = offer_dict.get('salaryFrom')
    salary_to = offer_dict.get('salaryTo')
    salary_text = ""
    if salary_from and salary_to:
        salary_text = f"💰 {salary_from:,}€ - {salary_to:,}€".replace(',', '.') # Basic localization for thousands
    elif salary_from:
        salary_text = f"💰 From {salary_from:,}€".replace(',', '.')
    elif salary_to:
        salary_text = f"💰 Up to {salary_to:,}€".replace(',', '.')

    # Format remote work
    remote_percentage = offer_dict.get('remotePercentage')
    remote_text = f"🏠 {remote_percentage}% Remote" if remote_percentage is not None else ""

    # Format locations
    locations = offer_dict.get('locations', [])
    locations_text = f"📍 {', '.join(locations)}" if locations and isinstance(locations, list) else ""

    # Fetch skills from DB
    skills_data = get_job_skills_from_db(offer_id)
    skills_fields = []

    # Helper to format skills list
    def format_skills(skill_list):
        lines = []
        for skill in skill_list:
            level_stars = "★" * skill.get('level', 0) if skill.get('level') else ""
            level_part = f" ({level_stars})" if level_stars else ""
            lines.append(f"• {skill.get('skill', 'N/A')}{level_part}")
        # Discord embed field value limit is 1024 chars
        formatted_value = "\n".join(lines)
        if len(formatted_value) > 1020: # Keep some buffer
             formatted_value = formatted_value[:1020] + "..."
        return formatted_value if formatted_value else "N/A"


    if skills_data.get('must'):
        skills_fields.append({
            "name": "🔒 Must Have",
            "value": format_skills(skills_data['must']),
            "inline": False # Prefer non-inline for readability
        })

    if skills_data.get('nice'):
        skills_fields.append({
            "name": "✨ Nice to Have",
            "value": format_skills(skills_data['nice']),
            "inline": False
        })

    if skills_data.get('extra'):
         skills_fields.append({
            "name": "➕ Extra Skills",
            "value": format_skills(skills_data['extra']),
            "inline": False
         })

    # Assemble the description string, removing empty lines
    description_parts = [part for part in [salary_text, remote_text, locations_text] if part]
    description = "\n".join(description_parts)
    description += f"\n\n[View on Manfred]({job_url})"

    embed = {
        "title": f"{position} @ {company_name}",
        "description": description.strip(),
        "color": 5814783, # Discord Blue
        "timestamp": datetime.now().isoformat(), # Use ISO format
        "footer": {"text": "Via Manfred Job Fetcher"},
        "fields": skills_fields
    }
    if logo_url:
        embed["thumbnail"] = {"url": logo_url}

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

    # Structure for Discord webhook POST request
    webhook_data = {
        "content": f"📢 New Job Offer: **{offer_dict.get('position', 'N/A')}**", # Add position to content for better mobile notification preview
        "embeds": [embed]
    }

    try:
        # Use the shared session from manfred_api to send the webhook
        response = http_session.post(
            webhook_url,
            json=webhook_data,
            headers={"Content-Type": "application/json"},
            timeout=10 # Shorter timeout for webhook sending
        )
        response.raise_for_status() # Check for HTTP errors (like 4xx, 5xx)
        logger.info(f"Sent Discord notification successfully for offer ID: {offer_dict.get('id')}")
        return True
    except Exception as e:
        # Catch potential exceptions from http_session.post or raise_for_status
        logger.error(f"Failed to send Discord webhook for offer ID {offer_dict.get('id', 'N/A')}: {e}", exc_info=True)
        return False

def send_batch_notifications(offer_dicts, batch_size=5, delay_seconds=0.5):
    """Sends a batch of new offers to Discord webhook, limited by batch_size with delays."""
    if not offer_dicts:
        logger.info("No offers provided for batch notification.")
        return 0

    webhook_url = CONFIG['DISCORD_WEBHOOK_URL']
    if not webhook_url:
        logger.warning("Discord webhook URL not configured. Skipping batch notification.")
        return 0

    sent_count = 0
    offers_to_send = offer_dicts[:batch_size] # Limit the batch size

    logger.info(f"Attempting to send {len(offers_to_send)} notifications (batch limit {batch_size})...")

    for i, offer in enumerate(offers_to_send):
        if send_discord_notification(offer):
            sent_count += 1
            if i < len(offers_to_send) - 1 and delay_seconds > 0:
                 time.sleep(delay_seconds) # Add delay between messages to avoid rate limiting
        else:
            # Optional: stop batch on first failure? Or continue? Current: Continue.
             logger.warning(f"Failed to send notification for offer ID {offer.get('id', 'N/A')} in batch.")

    logger.info(f"Finished sending batch. Successfully sent {sent_count}/{len(offers_to_send)} notifications.")
    return sent_count

# --- END OF FILE discord_notifier.py ---