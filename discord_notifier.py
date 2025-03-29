# --- START OF FILE discord_notifier.py ---
import logging
import json # Added for pretty-printing payload
from datetime import datetime
import time

# Assuming these are correctly set up in your project structure
from config import CONFIG
from database import get_job_skills_from_db, get_job_languages_from_db
from manfred_api import http_session

logger = logging.getLogger(__name__)

# --- Helper Functions (_format_skills_for_field, _format_language_for_field) ---
# (These functions remain unchanged from your original code)
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

# --- Embed Builder (_build_discord_embed) ---
# (This function remains unchanged from your original code)
def _build_discord_embed(offer_dict):
    """
    Builds the Discord embed message and extracts the job URL.
    Returns a tuple: (embed_dictionary, job_url) or (None, None) on failure.
    """
    offer_id = offer_dict.get('id')
    if not offer_id:
        logger.error("Cannot build embed: Offer dictionary missing 'id'.")
        return None, None # Return None for both embed and job_url

    position = offer_dict.get('position', 'Unknown Position')
    company_data = offer_dict.get('company', {})
    company_name = company_data.get('name', 'Unknown Company')
    logo_url = company_data.get('logoDark', {}).get('url') if isinstance(company_data.get('logoDark'), dict) else None
    slug = offer_dict.get('slug', f"job-{offer_id}")
    # Calculate job_url but don't put it in the embed's url field
    job_url = f"https://www.getmanfred.com/es/job-offers/{offer_id}/{slug}" # Assuming slug is always present if id is

    salary_from = offer_dict.get('salaryFrom')
    salary_to = offer_dict.get('salaryTo')
    salary_text = None
    if salary_from and salary_to:
        # Format with dots as thousands separators
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

    # Get skills data from DB
    skills_data = get_job_skills_from_db(offer_id)
    must_skills_text = _format_skills_for_field(skills_data.get('must', []))
    nice_skills_text = _format_skills_for_field(skills_data.get('nice', []))
    extra_skills_text = _format_skills_for_field(skills_data.get('extra', []))

    # Get language requirements from DB
    languages_data = get_job_languages_from_db(offer_id)
    languages_text = _format_language_for_field(languages_data)

    # --- Build Fields (Stacked, not inline) ---
    fields = []

    # --- Info Field (Salary, Remote, Location) ---
    info_lines = []
    if salary_text:
        info_lines.append(f"💰 **Salary:** {salary_text}")
    if remote_text:
        info_lines.append(f"🏠 **Remote:** {remote_text}")
    if locations_text:
        info_lines.append(f"📍 **Location:** {locations_text}")

    if info_lines:
        fields.append({
            "name": "📋 Job Details", # Changed name for clarity
            "value": "\n".join(info_lines),
            "inline": False
        })

    # --- Language Requirements Field ---
    if languages_text:
        fields.append({
            "name": "🌐 Language Requirements",
            "value": languages_text,
            "inline": False
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

    # --- Construct the Embed Dictionary ---
    embed = {
        "title": f"{position} @ {company_name}", # Title is now plain text
        "description": "", # Optional: Add a brief summary here if desired
        # "url": job_url, # <<< REMOVED: Link is now in a button component
        "color": 5814783, # Manfred purple-ish color (decimal)
        "timestamp": datetime.now().isoformat(),
        "footer": {"text": "Via Manfred Job Fetcher"},
        "fields": fields # Use the constructed fields list
    }
    if logo_url:
        # Use thumbnail for company logo
        embed["thumbnail"] = {"url": logo_url}

    # Return the embed dictionary and the job_url for the button
    return embed, job_url

# --- Notification Sender (Single) ---
def send_discord_notification(offer_dict):
    """
    Sends a single job offer embed with a button to the configured Discord webhook.
    Returns True on success, False on failure.
    """
    webhook_url = CONFIG.get('DISCORD_WEBHOOK_URL')
    if not webhook_url:
        logger.warning("Discord webhook URL not configured. Skipping notification.")
        return False

    # Build embed and get job_url for the button
    embed, job_url = _build_discord_embed(offer_dict)

    # Check if embed creation failed
    if not embed:
        # Error already logged in _build_discord_embed
        return False

    offer_id_str = offer_dict.get('id', 'N/A') # For logging

    # Prepare the main payload for the webhook
    webhook_data = {
        # Content provides a pingable text part outside the embed (optional)
        "content": f"📢 New Job Offer: **{offer_dict.get('position', 'N/A')}** at **{offer_dict.get('company', {}).get('name', 'N/A')}**",
        "embeds": [embed],
        "components": [] # Initialize components list
    }

    # --- Start Enhanced Logging ---
    logger.debug(f"Attempting to add button for Offer ID: {offer_id_str}. Generated job_url: '{job_url}'")

    # Add the button component only if job_url is valid (not None or empty string)
    if job_url:
        logger.debug(f"Condition 'if job_url:' is TRUE for Offer ID: {offer_id_str}. Adding button component structure.")
        webhook_data["components"] = [
            {
                "type": 1, # Action Row: Container for components
                "components": [
                    {
                        "type": 2,          # Component Type: Button
                        "style": 5,         # Style: Link button (opens URL)
                        "label": "View Job Offer", # Text displayed on the button
                        "url": job_url    # The URL the button points to
                        # "emoji": {          # Optional: Add an emoji to the button
                        #     "name": "📄"     # Example: document emoji (Unicode)
                        #  }
                        # No "custom_id" needed for link buttons (style 5)
                    }
                ]
            }
        ]
        logger.debug(f"Added 'View Job Offer' button component for Offer ID: {offer_id_str}")
    else:
        # Log why the button wasn't added
        logger.warning(f"Condition 'if job_url:' is FALSE for Offer ID: {offer_id_str}. Skipping button component. job_url value was: '{job_url}'")

    # Log the final payload being sent (useful for debugging structure issues)
    try:
        payload_json = json.dumps(webhook_data, indent=2)
        logger.debug(f"Final webhook payload for Offer ID {offer_id_str}:\n{payload_json}")
    except Exception as json_err:
        logger.error(f"Failed to serialize webhook_data to JSON for Offer ID {offer_id_str}: {json_err}")
        # Optionally return False here if serialization fails, though it's unlikely
        # return False

    # --- End Enhanced Logging ---


    # Send the request to the Discord Webhook
    try:
        response = http_session.post(
            webhook_url,
            json=webhook_data, # Send the complete payload (embeds + components)
            headers={"Content-Type": "application/json"},
            timeout=15 # Slightly longer timeout for network variance
        )
        # Raise an exception for bad status codes (4xx or 5xx)
        response.raise_for_status()
        logger.info(f"Sent Discord notification successfully for offer ID: {offer_id_str}")
        # Consider a small delay if sending many notifications rapidly, even individually
        # time.sleep(0.2)
        return True
    except Exception as e:
        # Log detailed error including potential HTTP status code from response
        status_code = getattr(e, 'response', None) and getattr(e.response, 'status_code', None)
        error_message = str(e)
        # Try to get Discord's error message if available
        discord_error_details = ""
        if getattr(e, 'response', None) is not None:
            try:
                error_json = e.response.json()
                discord_error_details = f" | Discord Response: {json.dumps(error_json)}"
            except json.JSONDecodeError:
                discord_error_details = f" | Discord Response (non-JSON): {e.response.text[:200]}..." # Log first 200 chars

        if status_code:
             error_message = f"HTTP {status_code} - {error_message}{discord_error_details}"
        else:
             error_message = f"{error_message}{discord_error_details}"

        # Log with exc_info=True during debugging if you need the full traceback
        logger.error(f"Failed to send Discord webhook for offer ID {offer_id_str}: {error_message}", exc_info=False)
        return False

# --- Notification Sender (Batch) ---
def send_batch_notifications(offer_dicts, batch_size=5, delay_seconds=1.5):
    """
    Sends a batch of new offers to Discord webhook, limited by batch_size
    with delays between each notification to avoid rate limits.
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
    # Ensure we only process up to batch_size offers from the list
    offers_to_send = offer_dicts[:batch_size]

    if not offers_to_send:
        logger.info("Offer list was provided, but resulted in an empty batch to send (potentially filtered or empty input).")
        return 0

    total_in_batch = len(offers_to_send)
    logger.info(f"Attempting to send batch of {total_in_batch} notifications (limit {batch_size})...")

    for i, offer in enumerate(offers_to_send):
        offer_id_str = 'N/A' # Default if offer is invalid
        # Basic check for valid offer structure before processing
        if not isinstance(offer, dict) or not offer.get('id'):
            logger.warning(f"Skipping invalid offer data at index {i} in batch. Offer data: {str(offer)[:100]}...") # Log snippet of bad data
            continue
        else:
            offer_id_str = offer.get('id')

        logger.info(f"Sending notification {i+1}/{total_in_batch} for offer ID: {offer_id_str}")
        if send_discord_notification(offer):
            sent_count += 1
        else:
            # Failure already logged within send_discord_notification
            logger.warning(f"Failed to send notification for offer ID {offer_id_str} in batch (attempt {i+1}/{total_in_batch}). See previous error for details.")
            # Optional: Implement different behavior on failure, e.g., break, longer delay.

        # Apply delay *after* sending, but not after the very last one in the batch
        if i < total_in_batch - 1 and delay_seconds > 0:
            logger.debug(f"Waiting {delay_seconds}s before next notification...")
            time.sleep(delay_seconds)

    logger.info(f"Finished sending batch. Successfully sent {sent_count}/{total_in_batch} notifications.")
    return sent_count

# --- END OF FILE discord_notifier.py ---