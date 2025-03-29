# --- START OF FILE discord_notifier.py ---
import logging
import time
from datetime import datetime
from discord_webhook import DiscordWebhook, DiscordEmbed

from config import CONFIG
from database import get_job_skills_from_db, get_job_languages_from_db

logger = logging.getLogger(__name__)

# --- Helper Functions ---
def _format_skills_for_field(skill_list):
    """Formats a list of skill dictionaries into a string for an embed field."""
    if not skill_list:
        return None
    lines = []
    for skill in skill_list:
        level_stars = "★" * skill.get('level', 0) if skill.get('level') else ""
        level_part = f" ({level_stars})" if level_stars else ""
        skill_name = skill.get('skill', 'N/A')
        lines.append(f"• {skill_name}{level_part}")
    formatted_value = "\n".join(lines)
    # Discord field value limit is 1024 characters
    return formatted_value[:1020] + "..." if len(formatted_value) > 1020 else formatted_value

def _format_language_for_field(language_list):
    """Formats a list of language dictionaries into a string for an embed field."""
    if not language_list:
        return None

    lines = []
    for language in language_list:
        name = language.get('name', 'N/A')
        level = language.get('level', 'N/A')
        # Format level more user-friendly
        level_display = level.capitalize() if level else 'N/A'
        lines.append(f"• {name}: {level_display}")

    formatted_value = "\n".join(lines)
    # Discord field value limit is 1024 characters
    return formatted_value[:1020] + "..." if len(formatted_value) > 1020 else formatted_value

# --- Embed Builder ---
# Modified section of _build_discord_embed function in discord_notifier.py

def _build_discord_embed(offer_dict):
    """
    Builds a Discord embed for a job offer using discord-webhook library.
    Returns the embed object or None on failure.
    """
    offer_id = offer_dict.get('id')
    if not offer_id:
        logger.error("Cannot build embed: Offer dictionary missing 'id'.")
        return None

    position = offer_dict.get('position', 'Unknown Position')
    company_data = offer_dict.get('company', {})
    company_name = company_data.get('name', 'Unknown Company')
    logo_url = company_data.get('logoDark', {}).get('url') if isinstance(company_data.get('logoDark'), dict) else None
    slug = offer_dict.get('slug', f"job-{offer_id}")
    job_url = f"https://www.getmanfred.com/es/job-offers/{offer_id}/{slug}" # Calculate URL first

    # Create the embed with the DiscordEmbed class, adding the URL to the title
    embed = DiscordEmbed(
        title=f"{position} @ {company_name}",
        description="",  # Optional summary could go here
        color=5814783,  # Manfred purple-ish color
        url=job_url      # Make the title a link
    )

    # Set timestamp and footer
    embed.set_timestamp()
    embed.set_footer(text="Via Manfred Job Fetcher")

    # Set thumbnail if logo URL is available
    if logo_url:
        embed.set_thumbnail(url=logo_url)

    # Prepare job details field content
    info_lines = []

    # Salary information
    salary_from = offer_dict.get('salaryFrom')
    salary_to = offer_dict.get('salaryTo')
    if salary_from and salary_to:
        salary_text = f"{salary_from:,}€ - {salary_to:,}€".replace(',', '.')
        info_lines.append(f"💰 **Salary:** {salary_text}")
    elif salary_from:
        salary_text = f"From {salary_from:,}€".replace(',', '.')
        info_lines.append(f"💰 **Salary:** {salary_text}")
    elif salary_to:
        salary_text = f"Up to {salary_to:,}€".replace(',', '.')
        info_lines.append(f"💰 **Salary:** {salary_text}")

    # Remote work information
    remote_percentage = offer_dict.get('remotePercentage')
    if remote_percentage is not None:
        info_lines.append(f"🏠 **Remote:** {remote_percentage}% Remote")

    # Location information
    locations = offer_dict.get('locations', [])
    if locations and isinstance(locations, list):
        locations_text = f"{', '.join(locations)}"
        info_lines.append(f"📍 **Location:** {locations_text}")

    # Add job details field
    if info_lines:
        embed.add_embed_field(
            name="📋 Job Details",
            value="\n".join(info_lines),
            inline=False
        )

    # Get skills and language data from DB
    skills_data = get_job_skills_from_db(offer_id)
    languages_data = get_job_languages_from_db(offer_id)

    # Add language requirements field
    languages_text = _format_language_for_field(languages_data)
    if languages_text:
        embed.add_embed_field(
            name="🌐 Language Requirements",
            value=languages_text,
            inline=False
        )

    # Add skills fields
    must_skills_text = _format_skills_for_field(skills_data.get('must', []))
    if must_skills_text:
        embed.add_embed_field(
            name="🔒 Must Have Skills",
            value=must_skills_text,
            inline=False
        )

    nice_skills_text = _format_skills_for_field(skills_data.get('nice', []))
    if nice_skills_text:
        embed.add_embed_field(
            name="✨ Nice to Have Skills",
            value=nice_skills_text,
            inline=False
        )

    extra_skills_text = _format_skills_for_field(skills_data.get('extra', []))
    if extra_skills_text:
        embed.add_embed_field(
            name="📚 Extra Skills",
            value=extra_skills_text,
            inline=False
        )

    return embed # Return only the embed object

# --- Notification Sender (Single) ---
def send_discord_notification(offer_dict):
    """
    Sends a single job offer notification to the configured Discord webhook.
    Returns True on success, False on failure.
    """
    webhook_url = CONFIG.get('DISCORD_WEBHOOK_URL')
    if not webhook_url:
        logger.warning("Discord webhook URL not configured. Skipping notification.")
        return False

    # Get offer ID and other details early for URL, content, and logging
    offer_id = offer_dict.get('id')
    if not offer_id:
        logger.error("Cannot send notification: Offer dictionary missing 'id'.")
        return False
    offer_id_str = str(offer_id) # Use consistent string representation

    position = offer_dict.get('position', 'Unknown Position')
    company_name = offer_dict.get('company', {}).get('name', 'Unknown Company')
    slug = offer_dict.get('slug', f"job-{offer_id}")
    job_url = f"https://www.getmanfred.com/es/job-offers/{offer_id}/{slug}"

    try:
        # Build embed (URL is part of the embed title and a dedicated field)
        embed = _build_discord_embed(offer_dict)
        if not embed:
            logger.error(f"Failed to build embed for offer ID {offer_id_str}")
            return False

        # --- MODIFIED CONTENT ---
        # Create webhook content including the job title, company, and link
        content = f"📢 New Job Offer Found!"
        # --- END MODIFIED CONTENT ---

        webhook = DiscordWebhook(
            url=webhook_url,
            content=content,
            rate_limit_retry=True,
            timeout=15
        )

        # Add the embed to the webhook
        webhook.add_embed(embed)

        # Execute the webhook with built-in retry logic
        response = webhook.execute()

        # Check for success and log
        if isinstance(response, list):
            response = response[0]  # Get the first response if it's a list

        if response and 200 <= response.status_code < 300:
            logger.info(f"Successfully sent Discord notification for offer ID: {offer_id_str}")
            return True
        else:
            status_code = getattr(response, 'status_code', 'Unknown')
            logger.error(f"Failed to send Discord webhook for offer ID {offer_id_str}: HTTP {status_code}")
            # Log response content if available for debugging
            try:
                response_content = response.content.decode('utf-8')
                logger.error(f"Discord API response content: {response_content}")
            except Exception:
                pass # Ignore if decoding fails
            return False

    except Exception as e:
        logger.error(f"Failed to send Discord webhook for offer ID {offer_id_str}: {str(e)}", exc_info=True)
        return False

# --- Notification Sender (Batch) ---
def send_batch_notifications(offer_dicts, batch_size=5, delay_seconds=1.5):
    """
    Sends a batch of job offers to Discord webhook.
    Returns the number of successfully sent notifications.
    """
    if not offer_dicts:
        logger.info("No offers provided for batch notification.")
        return 0

    webhook_url = CONFIG.get('DISCORD_WEBHOOK_URL')
    if not webhook_url:
        logger.warning("Discord webhook URL not configured. Skipping batch notification.")
        return 0

    sent_count = 0
    # Process only up to batch_size offers
    offers_to_send = offer_dicts[:batch_size]

    if not offers_to_send:
        logger.info("Offer list resulted in an empty batch to send.")
        return 0

    total_in_batch = len(offers_to_send)
    logger.info(f"Attempting to send batch of {total_in_batch} notifications (limit {batch_size})...")

    for i, offer in enumerate(offers_to_send):
        # Validate offer structure
        if not isinstance(offer, dict) or not offer.get('id'):
            logger.warning(f"Skipping invalid offer data at index {i} in batch.")
            continue

        offer_id_str = offer.get('id')
        logger.info(f"Sending notification {i+1}/{total_in_batch} for offer ID: {offer_id_str}")

        if send_discord_notification(offer):
            sent_count += 1
        else:
            logger.warning(f"Failed to send notification for offer ID {offer_id_str}.")

        # Add delay between notifications (except after the last one)
        if i < total_in_batch - 1 and delay_seconds > 0:
            logger.debug(f"Waiting {delay_seconds}s before next notification...")
            time.sleep(delay_seconds)

    logger.info(f"Finished sending batch. Successfully sent {sent_count}/{total_in_batch} notifications.")
    return sent_count
# --- END OF FILE discord_notifier.py ---