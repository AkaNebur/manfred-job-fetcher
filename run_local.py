"""Run the Manfred Job Fetcher locally, without Docker.

Loads a local ``.env`` (if present), applies a local-friendly default database
path, and starts the development server with auto-reload.

Usage:
    pip install -r requirements.txt
    python run_local.py

Then open http://localhost:8080/docs
"""
import os

from dotenv import load_dotenv

# Pick up a local .env if the developer created one (does not override real env vars).
load_dotenv()

# Default to a database inside the repo's ./data directory instead of the
# container path (/app/data/history.db) used in Docker.
os.environ.setdefault("DB_PATH", os.path.join("data", "history.db"))

import uvicorn

if __name__ == "__main__":
    port = int(os.getenv("PORT", "8080"))
    uvicorn.run("app:app", host="127.0.0.1", port=port, reload=True)
