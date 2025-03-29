# --- START OF FILE scheduler.py ---
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
        result = services.fetch_and_store_offers_service()
        
        # Log the result
        status = result.get('status', 'unknown')
        new_offers = result.get('new_offers', 0)
        updated_offers = result.get('updated_offers', 0)
        
        end_time = datetime.now()
        duration = (end_time - start_time).total_seconds()
        
        logger.info(
            f"Scheduler: Completed scheduled job fetch in {duration:.2f} seconds. "
            f"Status: {status}, New: {new_offers}, Updated: {updated_offers}"
        )
        
        # Optionally process skills for any new offers
        if new_offers > 0:
            logger.info(f"Scheduler: Processing skills for {new_offers} new offers")
            skills_result = services.process_pending_details_service(limit=new_offers)
            logger.info(f"Scheduler: Processed skills for {skills_result} offers")
            
            # Send notifications if any new offers
            if CONFIG.get('DISCORD_WEBHOOK_URL'):
                logger.info(f"Scheduler: Sending notifications for new offers")
                notification_result = services.send_pending_notifications_service(limit=new_offers)
                logger.info(f"Scheduler: Sent {notification_result[0]} notifications, {notification_result[1]} remaining")
    
    except Exception as e:
        logger.error(f"Scheduler: Error during scheduled job fetch: {e}", exc_info=True)

# --- END OF FILE scheduler.py ---