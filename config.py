# --- START OF FILE config.py ---
import os
import logging
import json
from typing import Annotated, Any, Dict, List

from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict, NoDecode

logger = logging.getLogger(__name__)


class Settings(BaseSettings):
    """Application configuration sourced from environment variables.

    Backed by pydantic-settings for type coercion and validation at startup.
    Kept dict-accessible (``CONFIG['KEY']``) and mutable at runtime for backward
    compatibility: the rest of the codebase both reads ``CONFIG['X']`` and updates
    ``CONFIG['BUILD_ID_HASH']`` when the Manfred build hash is refreshed.
    """

    model_config = SettingsConfigDict(
        case_sensitive=False,
        extra="ignore",
        validate_assignment=True,
    )

    # --- Environment-driven settings ---
    EXTERNAL_ENDPOINT_URL: str = "https://www.getmanfred.com/api/v2/public/offers?lang=ES&onlyActive=true"
    DB_PATH: str = "/app/data/history.db"
    MAX_RETRIES: int = 3
    RETRY_BACKOFF: float = 0.5
    DISCORD_WEBHOOK_URL: str = ""
    RESET_DB: bool = False
    FETCH_INTERVAL: int = 3600  # seconds; default 1 hour
    SQLALCHEMY_ECHO: bool = False
    DETAIL_ENDPOINT_PATTERN: str = (
        "https://www.getmanfred.com/_next/data/${BUILD_ID_HASH}/es/job-offers/{offer_id}/{offer_slug}.json"
    )

    # Provided as a comma-separated string ("a,b,c"); NoDecode stops pydantic-settings
    # from JSON-decoding it so the validator below can split it.
    CORS_ALLOW_ORIGINS: Annotated[List[str], NoDecode] = ["*"]

    # Relevance filter: "off" disables it, "rules" uses the criteria questionnaire,
    # "ai" uses the Claude-based scorer. FILTER_BEHAVIOR is "hard" (only notify
    # offers at/above RELEVANCE_THRESHOLD) or "annotate" (notify all, tag the score).
    FILTER_MODE: str = "off"
    FILTER_BEHAVIOR: str = "hard"
    RELEVANCE_THRESHOLD: int = 60

    # AI filter (FILTER_MODE='ai'): Claude credentials, model, and the natural-language
    # profile describing what counts as relevant. AI_USER_PROFILE takes precedence over
    # the profile file at AI_PROFILE_PATH.
    ANTHROPIC_API_KEY: str = ""
    AI_MODEL: str = "claude-haiku-4-5"
    AI_USER_PROFILE: str = ""

    # --- Derived / runtime fields (populated in load_config) ---
    BUILD_ID_HASH: str = ""
    CONFIG_FILE_PATH: str = ""
    FILTER_RULES_PATH: str = ""  # path to the rules-mode criteria JSON file
    AI_PROFILE_PATH: str = ""    # path to the ai-mode natural-language profile file

    # --- Constants (not environment-driven) ---
    SQLALCHEMY_TRACK_MODIFICATIONS: bool = False
    SQLALCHEMY_ENGINE_OPTIONS: Dict[str, Any] = {
        "pool_pre_ping": True,  # Check connection before using from pool
        "pool_recycle": 3600,   # Recycle connections after 1 hour
    }

    @field_validator("CORS_ALLOW_ORIGINS", mode="before")
    @classmethod
    def _split_cors_origins(cls, value):
        """Allow a comma-separated origins string, e.g. "https://a.com,https://b.com"."""
        if isinstance(value, str):
            return [origin.strip() for origin in value.split(",") if origin.strip()]
        return value

    # --- dict-style compatibility shims ---
    def __getitem__(self, key):
        return getattr(self, key)

    def __setitem__(self, key, value):
        setattr(self, key, value)

    def __contains__(self, key):
        return key in type(self).model_fields

    def get(self, key, default=None):
        return getattr(self, key, default)


def load_config():
    """Build a Settings instance, applying the BUILD_ID_HASH file/env resolution and
    the detail-endpoint placeholder fixups that can't be expressed declaratively."""
    settings = Settings()

    # Resolve the build-hash config file path relative to the database location.
    config_dir = os.path.join(os.path.dirname(settings.DB_PATH), "config")
    config_file = os.path.join(config_dir, "build_hash.json")
    settings.CONFIG_FILE_PATH = config_file
    settings.FILTER_RULES_PATH = os.getenv(
        "FILTER_RULES_PATH", os.path.join(config_dir, "filter_rules.json")
    )
    settings.AI_PROFILE_PATH = os.getenv(
        "AI_PROFILE_PATH", os.path.join(config_dir, "profile.md")
    )

    # 1) Try to load BUILD_ID_HASH from the JSON file first.
    build_id_hash = ""
    try:
        if os.path.exists(config_file):
            with open(config_file, "r") as f:
                build_id_hash = json.load(f).get("BUILD_ID_HASH", "")
                if build_id_hash:
                    logger.info(f"Loaded BUILD_ID_HASH from file: {build_id_hash}")
                else:
                    logger.warning("BUILD_ID_HASH in config file is empty")
    except Exception as e:
        logger.warning(f"Failed to load BUILD_ID_HASH from file: {e}")

    # 2) Fall back to the environment, persisting it to the file for next time.
    if not build_id_hash:
        env_hash = os.getenv("BUILD_ID_HASH", "")
        if env_hash:
            logger.info(f"Using BUILD_ID_HASH from environment: {env_hash}")
            build_id_hash = env_hash
            try:
                os.makedirs(config_dir, exist_ok=True)
                with open(config_file, "w") as f:
                    json.dump({"BUILD_ID_HASH": build_id_hash}, f)
                logger.info("Saved environment BUILD_ID_HASH to file for future use")
            except Exception as e:
                logger.warning(f"Failed to save environment BUILD_ID_HASH to file: {e}")

    settings.BUILD_ID_HASH = build_id_hash

    # Ensure the detail-endpoint pattern carries the expected placeholder.
    pattern = settings.DETAIL_ENDPOINT_PATTERN
    if "${BUILD_ID_HASH}" not in pattern:
        logger.warning("DETAIL_ENDPOINT_PATTERN doesn't contain ${BUILD_ID_HASH} placeholder! Fixing...")
        if "${}" in pattern:
            settings.DETAIL_ENDPOINT_PATTERN = pattern.replace("${}", "${BUILD_ID_HASH}")
            logger.info("Fixed empty placeholder in DETAIL_ENDPOINT_PATTERN")

    if not build_id_hash:
        logger.warning("No BUILD_ID_HASH found in file or environment. Will attempt to fetch from website.")

    return settings


CONFIG = load_config()

# --- END OF FILE config.py ---
