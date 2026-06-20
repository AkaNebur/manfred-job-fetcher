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

# Default to a database inside the repo's ./data directory instead of the container
# path (/app/data/history.db) used in Docker. This is set before load_dotenv() so the
# container DB_PATH shipped in .env.sample doesn't leak into a local run; an explicit
# shell `DB_PATH` still wins.
os.environ.setdefault("DB_PATH", os.path.join("data", "history.db"))

# Pick up a local .env if the developer created one (does not override existing vars).
load_dotenv()

import uvicorn

if __name__ == "__main__":
    port = int(os.getenv("PORT", "8080"))
    uvicorn.run("app:app", host="127.0.0.1", port=port, reload=True)
