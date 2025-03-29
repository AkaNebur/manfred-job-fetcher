# --- START OF FILE swagger.py ---

from flasgger import Swagger

def setup_swagger(app):
    """Configure Swagger for the Flask application."""
    swagger_config = {
        "headers": [],
        "specs": [
            {
                "endpoint": "apispec",
                "route": "/apispec.json",
                "rule_filter": lambda rule: True,  # all rules
                "model_filter": lambda tag: True,  # all models
            }
        ],
        "static_url_path": "/flasgger_static",
        "swagger_ui": True,
        "specs_route": "/api/docs" # Keep the UI route
    }

    # Simplified template for remaining endpoints
    swagger_template = {
        "info": {
            "title": "Manfred Job Fetcher API (Simplified)",
            "description": "API for fetching raw data from GetManfred and checking system health.",
            "version": "1.0.0",
            "contact": {
                "email": "your.email@example.com" # Replace if needed
            },
        },
        "schemes": [
            "http",
            "https"
        ],
        "tags": [
             {
                "name": "Raw Data",
                "description": "Direct fetching from external source"
            },
            {
                "name": "Data Storage",
                "description": "Operations for persisting job offers data"
            },
            {
                "name": "Data Processing",
                "description": "Operations for processing job offers data"
            },
            {
                "name": "Notifications",
                "description": "Operations for sending notifications"
            },
            {
                "name": "System",
                "description": "System health check"
            }
        ],
        "definitions": {
             # No complex definitions needed for the remaining endpoints
        },
    }

    return Swagger(app, config=swagger_config, template=swagger_template)

# --- END OF FILE swagger.py ---