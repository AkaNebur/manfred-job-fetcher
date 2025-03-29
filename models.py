# --- START OF FILE models.py ---
from typing import List, Optional, Dict, Any, Union
from pydantic import BaseModel, Field, RootModel
from datetime import datetime

# Request Models (if needed)
class ProcessLimitRequest(BaseModel):
    limit: int = Field(10, description="Maximum number of offers to process")

# Response Models
class ErrorResponse(BaseModel):
    status: str = "error"
    message: str

class SkillDetail(BaseModel):
    skill: str
    icon: Optional[str] = None
    level: Optional[int] = None
    desc: Optional[str] = None

class LanguageDetail(BaseModel):
    name: str
    level: str

class JobSkillsResponse(BaseModel):
    status: str = "success"
    offer_id: int
    skills: Dict[str, List[SkillDetail]]
    languages: List[LanguageDetail]

# Define a root model for list responses
# Use this for /raw-offers endpoint
OffersList = RootModel[List[Dict[str, Any]]]

class StoreOffersResponse(BaseModel):
    status: str
    total_fetched: Optional[int] = None
    new_offers: Optional[int] = None
    updated_offers: Optional[int] = None
    skills_processed: Optional[int] = None
    webhook_sent: Optional[int] = None
    timestamp: str
    duration_seconds: Optional[float] = None
    message: Optional[str] = None

class ProcessDetailsResponse(BaseModel):
    status: str = "success"
    processed_count: int
    timestamp: str

class NotificationsResponse(BaseModel):
    status: str = "success"
    offers_sent: int
    remaining_pending: int

class HealthCheckResponse(BaseModel):
    status: str
    timestamp: str
    database_path: str
    database_status: str
    webhook_configured: bool
    config: Dict[str, Any]

# --- END OF FILE models.py ---