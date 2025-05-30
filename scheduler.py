# --- scheduler.py ---
import logging
from datetime import datetime
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.interval import IntervalTrigger
from fastapi import FastAPI

# Import CONFIG at module level
from config import CONFIG

logger = logging.getLogger(__name__)

# Global scheduler instance
scheduler = None

# Lazy import services to avoid circular imports
def get_services():
    import services
    return services

def initialize_scheduler(app: FastAPI):
    """Initialize and start the job scheduler for FastAPI."""
    global scheduler
    
    if scheduler:
        logger.warning("Scheduler already initialized. Skipping.")
        return scheduler
    
    # Create scheduler instance
    scheduler = BackgroundScheduler(daemon=True)
    
    # Get fetch interval from config (default to 3600 seconds = 1 hour)
    fetch_interval = int(CONFIG.get('FETCH_INTERVAL', 3600))
    
    # Log the scheduler configuration
    logger.info(f"Initializing job scheduler with fetch interval of {fetch_interval} seconds ({fetch_interval/60:.1f} minutes)")
    
    # Add job to scheduler
    scheduler.add_job(
        func=scheduled_fetch_job,
        trigger=IntervalTrigger(seconds=fetch_interval),
        id='fetch_job_offers',
        name='Fetch and process Manfred job offers',
        replace_existing=True
    )
    
    # Add job to clean up obsolete notifications - runs once per day
    scheduler.add_job(
        func=cleanup_obsolete_notifications_job,
        trigger=IntervalTrigger(hours=24),  # Run once per day
        id='cleanup_obsolete_notifications',
        name='Clean up Discord messages for obsolete job offers',
        replace_existing=True
    )
    
    # Start the scheduler
    scheduler.start()
    
    # Run the job immediately at startup
    logger.info("Running initial job fetch on startup")
    scheduled_fetch_job()
    
    logger.info("Scheduler successfully initialized and started")
    return scheduler

def scheduled_fetch_job():
    """Function to be executed by the scheduler."""
    start_time = datetime.now()
    logger.info(f"Scheduler: Starting scheduled job fetch at {start_time.isoformat()}")
    
    try:
        # Lazy import services
        services = get_services()
        
        # Call the service function to fetch and process offers
        # This now handles everything in the correct order:
        # 1. Fetch offers
        # 2. Store/update them in the database
        # 3. Process skills for new offers
        # 4. Send notifications for offers with skills
        result = services.fetch_and_store_offers_service()
        
        # Log the result
        status = result.get('status', 'unknown')
        new_offers = result.get('new_offers', 0)
        updated_offers = result.get('updated_offers', 0)
        skills_processed = result.get('skills_processed', 0)
        webhook_sent = result.get('webhook_sent', 0)
        
        end_time = datetime.now()
        duration = (end_time - start_time).total_seconds()
        
        logger.info(
            f"Scheduler: Completed scheduled job fetch in {duration:.2f} seconds. "
            f"Status: {status}, New: {new_offers}, Updated: {updated_offers}, "
            f"Skills processed: {skills_processed}, Notifications sent: {webhook_sent}"
        )
        
        # Check for any pending notifications that might have failed previously
        if CONFIG.get('DISCORD_WEBHOOK_URL'):
            logger.info(f"Scheduler: Checking for any pending notifications...")
            notification_result = services.send_pending_notifications_service(limit=10)
            if notification_result[0] > 0:
                logger.info(f"Scheduler: Sent {notification_result[0]} pending notifications, {notification_result[1]} remaining")
            else:
                logger.info(f"Scheduler: No pending notifications to send")
                
        # Check for any offers still missing skills data
        pending_skills_count = services.process_pending_details_service(limit=10)
        if pending_skills_count > 0:
            logger.info(f"Scheduler: Processed skills for {pending_skills_count} offers that were pending")
    
    except Exception as e:
        logger.error(f"Scheduler: Error during scheduled job fetch: {e}", exc_info=True)

def cleanup_obsolete_notifications_job():
    """Function to be executed by the scheduler to clean up obsolete Discord notifications."""
    logger.info(f"Scheduler: Starting cleanup of obsolete Discord notifications")
    
    try:
        # Lazy import services
        services = get_services()
        
        # Call the service function to clean up obsolete notifications
        deleted_count = services.cleanup_obsolete_job_notifications_service()
        
        logger.info(f"Scheduler: Completed obsolete notifications cleanup. Deleted {deleted_count} messages.")
    
    except Exception as e:
        logger.error(f"Scheduler: Error during obsolete notifications cleanup: {e}", exc_info=True)

# --- END OF FILE scheduler.py ---