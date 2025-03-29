# --- START OF FILE database.py ---
# --- SQLAlchemy Implementation of database.py ---
import os
import logging
from datetime import datetime

from sqlalchemy import create_engine, Column, Integer, String, Boolean, Text, ForeignKey, DateTime, CheckConstraint, Index
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker, relationship, scoped_session
from sqlalchemy.exc import SQLAlchemyError

from config import CONFIG

logger = logging.getLogger(__name__)

# Create the directory for the database if it doesn't exist
db_path = CONFIG['DB_PATH']
db_dir = os.path.dirname(db_path)
if db_dir and not os.path.exists(db_dir):
    try:
        os.makedirs(db_dir, exist_ok=True)
        logger.info(f"Created database directory: {db_dir}")
    except OSError as e:
        logger.error(f"Error creating database directory {db_dir}: {e}")

# Create the SQLAlchemy engine with SQLite connection
engine = create_engine(f"sqlite:///{db_path}", connect_args={"timeout": 15})
SessionFactory = sessionmaker(bind=engine)
Session = scoped_session(SessionFactory)

Base = declarative_base()

# Define SQLAlchemy models

class FetchHistory(Base):
    __tablename__ = 'fetch_history'
    
    id = Column(Integer, primary_key=True, autoincrement=True)
    timestamp = Column(DateTime, default=datetime.now, nullable=False)
    endpoint = Column(String, nullable=False)
    status_code = Column(Integer)
    response_size = Column(Integer)
    error = Column(Text)


class JobOffer(Base):
    __tablename__ = 'job_offers'
    
    id = Column(Integer, primary_key=True, autoincrement=True)
    offer_id = Column(Integer, nullable=False, unique=True)
    position = Column(String, nullable=False)
    company_name = Column(String, nullable=False)
    remote_percentage = Column(Integer)
    salary_from = Column(Integer)
    salary_to = Column(Integer)
    locations = Column(String)
    company_logo_dark_url = Column(String)
    slug = Column(String)
    timestamp = Column(DateTime, default=datetime.now, nullable=False)
    notification_sent = Column(Boolean, default=False, nullable=False)
    skills_retrieved = Column(Boolean, default=False, nullable=False)
    
    # Relationships
    skills = relationship("JobSkill", back_populates="job_offer", cascade="all, delete-orphan")
    languages = relationship("JobLanguage", back_populates="job_offer", cascade="all, delete-orphan")
    
    # Indexes
    __table_args__ = (
        Index('idx_job_offers_offer_id', 'offer_id'),
        Index('idx_job_offers_notification_sent', 'notification_sent'),
        Index('idx_job_offers_skills_retrieved', 'skills_retrieved')
    )


class JobSkill(Base):
    __tablename__ = 'job_skills'
    
    id = Column(Integer, primary_key=True, autoincrement=True)
    offer_id = Column(Integer, ForeignKey('job_offers.offer_id', ondelete='CASCADE'), nullable=False)
    category = Column(String, nullable=False)
    skill_name = Column(String, nullable=False)
    skill_icon = Column(String)
    skill_level = Column(Integer)
    skill_desc = Column(Text)
    
    # Relationships
    job_offer = relationship("JobOffer", back_populates="skills")
    
    # Constraints and indexes
    __table_args__ = (
        CheckConstraint("category IN ('must', 'nice', 'extra')", name="check_category"),
        Index('idx_job_skills_offer_id', 'offer_id'),
        {'sqlite_autoincrement': True}
    )


class JobLanguage(Base):
    __tablename__ = 'job_languages'
    
    id = Column(Integer, primary_key=True, autoincrement=True)
    offer_id = Column(Integer, ForeignKey('job_offers.offer_id', ondelete='CASCADE'), nullable=False)
    language_name = Column(String, nullable=False)
    language_level = Column(String, nullable=False)
    
    # Relationships
    job_offer = relationship("JobOffer", back_populates="languages")
    
    # Indexes
    __table_args__ = (
        Index('idx_job_languages_offer_id', 'offer_id'),
        {'sqlite_autoincrement': True}
    )


def init_db():
    """Initialize the SQLite database and ensure schema consistency."""
    logger.info(f"Initializing database at {CONFIG['DB_PATH']}...")
    
    if CONFIG['RESET_DB'] and os.path.exists(CONFIG['DB_PATH']):
        logger.warning(f"RESET_DB is true, deleting existing database: {CONFIG['DB_PATH']}")
        try:
            os.remove(CONFIG['DB_PATH'])
            # Also remove any journal files that might exist
            if os.path.exists(f"{CONFIG['DB_PATH']}-journal"):
                os.remove(f"{CONFIG['DB_PATH']}-journal")
                logger.info("Removed database journal file")
        except OSError as e:
            logger.error(f"Error removing database file: {e}")
    
    try:
        # Create all tables
        Base.metadata.create_all(engine)
        logger.info("Database initialized/verified successfully.")
    except Exception as e:
        logger.error(f"Failed to initialize or migrate database: {e}", exc_info=True)
        raise


def check_db_connection():
    """Checks if a connection to the database can be established."""
    try:
        # Try a simple query with SQLAlchemy
        session = Session()
        session.execute("SELECT 1").scalar()
        session.close()
        return True, "connected"
    except Exception as e:
        logger.error(f"Database connection check failed: {e}", exc_info=False)
        return False, f"error: {str(e)}"


def log_fetch_attempt(endpoint, status_code=None, response_size=None, error=None):
    """Log API fetch attempts to the database."""
    session = Session()
    try:
        fetch_history = FetchHistory(
            timestamp=datetime.now(),
            endpoint=endpoint,
            status_code=status_code,
            response_size=response_size,
            error=str(error) if error else None
        )
        session.add(fetch_history)
        session.commit()
    except Exception as e:
        logger.error(f"Failed to log fetch attempt for {endpoint} due to DB error: {e}")
        session.rollback()
    finally:
        session.close()


def store_job_skills(offer_id, skills_data):
    """Stores the skills information for a job offer in the database."""
    session = Session()
    try:
        # Mark as retrieved even if no skills data
        job_offer = session.query(JobOffer).filter(JobOffer.offer_id == offer_id).first()
        if not job_offer:
            logger.warning(f"Attempted to store skills for non-existent offer ID {offer_id}")
            return False
        
        job_offer.skills_retrieved = True
        
        if not skills_data:
            logger.warning(f"No skills data provided for offer ID {offer_id}")
            session.commit()
            return True
        
        # Delete existing skills
        session.query(JobSkill).filter(JobSkill.offer_id == offer_id).delete()
        
        # Insert new skills
        skills_added = 0
        for category in ['must', 'nice', 'extra']:
            if category in skills_data and skills_data[category]:
                for skill in skills_data[category]:
                    job_skill = JobSkill(
                        offer_id=offer_id,
                        category=category,
                        skill_name=skill.get('skill', ''),
                        skill_icon=skill.get('icon', ''),
                        skill_level=skill.get('level', 0),
                        skill_desc=skill.get('desc', '')
                    )
                    session.add(job_skill)
                    skills_added += 1
        
        session.commit()
        logger.info(f"Successfully stored/updated {skills_added} skills for offer ID {offer_id}")
        return True
    except Exception as e:
        logger.error(f"Error storing skills for offer ID {offer_id}: {e}", exc_info=True)
        session.rollback()
        return False
    finally:
        session.close()


def store_job_languages(offer_id, languages_data):
    """Stores the language requirements for a job offer in the database."""
    session = Session()
    try:
        # Check if offer exists
        job_offer = session.query(JobOffer).filter(JobOffer.offer_id == offer_id).first()
        if not job_offer:
            logger.warning(f"Attempted to store languages for non-existent offer ID {offer_id}")
            return False
        
        if not languages_data:
            logger.warning(f"No language data provided for offer ID {offer_id}")
            return False
        
        # Delete existing languages
        session.query(JobLanguage).filter(JobLanguage.offer_id == offer_id).delete()
        
        # Insert new languages
        languages_added = 0
        for language in languages_data:
            job_language = JobLanguage(
                offer_id=offer_id,
                language_name=language.get('name', ''),
                language_level=language.get('level', '')
            )
            session.add(job_language)
            languages_added += 1
        
        session.commit()
        logger.info(f"Successfully stored/updated {languages_added} languages for offer ID {offer_id}")
        return True
    except Exception as e:
        logger.error(f"Error storing languages for offer ID {offer_id}: {e}", exc_info=True)
        session.rollback()
        return False
    finally:
        session.close()


def get_job_skills_from_db(offer_id):
    """Retrieves the skills for a specific job offer from the database."""
    result = {'must': [], 'nice': [], 'extra': []}
    session = Session()
    try:
        # Check if the offer exists and if skills were retrieved
        job_offer = session.query(JobOffer).filter(JobOffer.offer_id == offer_id).first()
        if not job_offer:
            logger.warning(f"Attempted to get skills for non-existent offer ID {offer_id}")
            return result
        
        if not job_offer.skills_retrieved:
            logger.debug(f"No skills found in DB for offer ID {offer_id}, skills not yet retrieved.")
            return result
        
        # Get skills
        skills = session.query(JobSkill).filter(JobSkill.offer_id == offer_id).all()
        
        if not skills:
            logger.debug(f"No skills found in DB for offer ID {offer_id}, but marked as retrieved.")
            return result
        
        for skill in skills:
            category = skill.category
            if category in result:
                result[category].append({
                    'skill': skill.skill_name,
                    'icon': skill.skill_icon,
                    'level': skill.skill_level,
                    'desc': skill.skill_desc
                })
        
        return result
    except Exception as e:
        logger.error(f"Failed to retrieve skills for offer ID {offer_id} from DB, returning empty. Error: {e}", exc_info=True)
        return result
    finally:
        session.close()


def get_job_languages_from_db(offer_id):
    """Retrieves the language requirements for a specific job offer from the database."""
    result = []
    session = Session()
    try:
        languages = session.query(JobLanguage).filter(JobLanguage.offer_id == offer_id).all()
        
        if not languages:
            logger.debug(f"No language requirements found in DB for offer ID {offer_id}")
            return result
        
        for language in languages:
            result.append({
                'name': language.language_name,
                'level': language.language_level
            })
        
        return result
    except Exception as e:
        logger.error(f"Failed to retrieve languages for offer ID {offer_id} from DB, returning empty. Error: {e}", exc_info=True)
        return result
    finally:
        session.close()


def get_pending_skill_offers(limit=10):
    """Retrieves job offers that need skills details fetched."""
    session = Session()
    try:
        offers = session.query(JobOffer.offer_id, JobOffer.slug)\
            .filter(JobOffer.skills_retrieved == False)\
            .limit(limit)\
            .all()
        
        # Convert SQLAlchemy result to list of dictionaries
        return [{'offer_id': offer.offer_id, 'slug': offer.slug} for offer in offers]
    except Exception as e:
        logger.error(f"Error fetching pending skill offers: {e}", exc_info=True)
        return []
    finally:
        session.close()


def update_notification_status(offer_ids):
    """Marks offers as notification sent in the database."""
    if not offer_ids:
        return 0
    
    session = Session()
    try:
        result = session.query(JobOffer)\
            .filter(JobOffer.offer_id.in_(offer_ids))\
            .update({JobOffer.notification_sent: True}, synchronize_session=False)
        
        session.commit()
        logger.info(f"Marked {result} offers as notification sent.")
        return result
    except Exception as e:
        logger.error(f"Failed to update notification status for offers: {offer_ids}. Error: {e}", exc_info=True)
        session.rollback()
        return 0
    finally:
        session.close()


def get_pending_notification_offers(limit=10):
    """Retrieves job offers that have not had notifications sent."""
    session = Session()
    try:
        offers = session.query(
            JobOffer.offer_id, JobOffer.position, JobOffer.company_name, 
            JobOffer.remote_percentage, JobOffer.salary_from, JobOffer.salary_to,
            JobOffer.locations, JobOffer.company_logo_dark_url, JobOffer.slug
        ).filter(JobOffer.notification_sent == False)\
        .order_by(JobOffer.timestamp.desc())\
        .limit(limit)\
        .all()
        
        # Convert SQLAlchemy result to list of dictionaries
        return [
            {
                'offer_id': offer.offer_id,
                'position': offer.position,
                'company_name': offer.company_name,
                'remote_percentage': offer.remote_percentage,
                'salary_from': offer.salary_from,
                'salary_to': offer.salary_to,
                'locations': offer.locations,
                'company_logo_dark_url': offer.company_logo_dark_url,
                'slug': offer.slug
            } 
            for offer in offers
        ]
    except Exception as e:
        logger.error(f"Error fetching pending notification offers: {e}", exc_info=True)
        return []
    finally:
        session.close()


def store_or_update_offers(offers):
    """Stores new offers or updates existing ones in the database. Returns list of new offers."""
    new_count = 0
    updated_count = 0
    new_offer_dicts = []
    
    session = Session()
    try:
        for offer_dict in offers:
            offer_id = offer_dict.get('id')
            if offer_id is None:
                logger.warning(f"Skipping offer due to missing ID: {offer_dict.get('position', 'N/A')}")
                continue
            
            # Parse the offer data
            position = offer_dict.get('position', 'Unknown Position')
            company_data = offer_dict.get('company', {})
            company_name = company_data.get('name', 'Unknown Company')
            logo_url = None
            if company_data.get('logoDark') and isinstance(company_data.get('logoDark'), dict):
                logo_url = company_data.get('logoDark').get('url')
            slug = offer_dict.get('slug', f"job-{offer_id}")
            remote = offer_dict.get('remotePercentage')
            salary_from = offer_dict.get('salaryFrom')
            salary_to = offer_dict.get('salaryTo')
            locations = offer_dict.get('locations', [])
            locations_str = ', '.join(str(loc) for loc in locations if loc is not None) if locations else None
            
            # Check if offer exists
            existing_offer = session.query(JobOffer).filter(JobOffer.offer_id == offer_id).first()
            
            if existing_offer:
                # Update existing offer
                existing_offer.position = position
                existing_offer.company_name = company_name
                existing_offer.remote_percentage = remote
                existing_offer.salary_from = salary_from
                existing_offer.salary_to = salary_to
                existing_offer.locations = locations_str
                existing_offer.company_logo_dark_url = logo_url
                existing_offer.slug = slug
                existing_offer.timestamp = datetime.now()
                updated_count += 1
                logger.debug(f"Updated existing offer ID: {offer_id}")
            else:
                # Create new offer
                new_offer = JobOffer(
                    offer_id=offer_id,
                    position=position,
                    company_name=company_name,
                    remote_percentage=remote,
                    salary_from=salary_from,
                    salary_to=salary_to,
                    locations=locations_str,
                    company_logo_dark_url=logo_url,
                    slug=slug,
                    timestamp=datetime.now(),
                    notification_sent=False,
                    skills_retrieved=False
                )
                session.add(new_offer)
                new_count += 1
                new_offer_dicts.append(offer_dict)
                logger.debug(f"Inserted new offer ID: {offer_id}")
        
        session.commit()
        logger.info(f"Database storage complete. New: {new_count}, Updated: {updated_count}")
        return new_count, updated_count, new_offer_dicts
    
    except Exception as e:
        logger.error(f"Error during offer storage: {e}", exc_info=True)
        session.rollback()
        raise
    finally:
        session.close()


def get_offer_by_id(offer_id):
    """Retrieves a single job offer by its ID."""
    session = Session()
    try:
        offer = session.query(JobOffer).filter(JobOffer.offer_id == offer_id).first()
        
        if not offer:
            return None
        
        # Convert SQLAlchemy model to dictionary
        return {
            'offer_id': offer.offer_id,
            'position': offer.position,
            'company_name': offer.company_name,
            'remote_percentage': offer.remote_percentage,
            'salary_from': offer.salary_from,
            'salary_to': offer.salary_to,
            'locations': offer.locations,
            'company_logo_dark_url': offer.company_logo_dark_url,
            'slug': offer.slug,
            'timestamp': offer.timestamp,
            'notification_sent': offer.notification_sent,
            'skills_retrieved': offer.skills_retrieved
        }
    except Exception as e:
        logger.error(f"Error fetching offer by ID {offer_id}: {e}", exc_info=True)
        return None
    finally:
        session.close()
# --- END OF FILE database.py ---