# --- UPDATED FILE swagger.py ---

from flasgger import Swagger

def setup_swagger(app):
    """Configure Swagger for the Flask application."""
    # Define shared definitions used in routes.py here
    definitions = {
         "SkillDetail": {
            "type": "object",
            "properties": {
                "skill": { "type": "string", "example": "Python" },
                "icon": { "type": "string", "nullable": True, "example": "python-icon.png" },
                "level": { "type": "integer", "nullable": True, "example": 4 },
                "desc": { "type": "string", "nullable": True, "example": "Experience with Django/Flask" }
            }
         },
         "ErrorResponse": {
             "type": "object",
             "properties": {
                 "status": {"type": "string", "example": "error"},
                 "message": {"type": "string", "example": "Error details here"}
             }
         }
         # Add other common definitions if needed
    }

    swagger_config = {
        "headers": [],
        "specs": [
            {
                "endpoint": "apispec",       # Internal endpoint name for the spec
                "route": "/apispec.json",    # URL path for the JSON spec
                "rule_filter": lambda rule: True,  # Include all rules/endpoints
                "model_filter": lambda tag: True,  # Include all models/definitions
            }
        ],
        "static_url_path": "/flasgger_static", # URL path for Swagger UI static files
        "swagger_ui": True,               # Enable Swagger UI
        "specs_route": "/api/docs",        # URL path for the Swagger UI page
        "url_prefix": ""                  # Add this to ensure proper route handling
    }

    # Define the main Swagger template
    swagger_template = {
        "swagger": "2.0", # Flasgger uses Swagger 2.0 spec by default
        "info": {
            "title": "Manfred Job Fetcher API",
            "description": "API for fetching, storing, and processing job offers from GetManfred, with Discord notifications.",
            "version": "1.1.0", # Increment version for refactor
            "contact": {
                "name": "Rubén Galán Díaz",
                "email": "rubengalandiaz@gmail.com"
            }
        },
        "host": None,  # Let Swagger UI determine host (or set explicitly e.g., "localhost:8080")
        "basePath": "/",  # Base path for API endpoints (usually root if not using prefix)
        "schemes": [      # Schemes supported by the API
            "http",
            "https"
        ],
        "consumes": [     # Default content types consumed by POST/PUT requests
            "application/json"
        ],
        "produces": [     # Default content types produced by responses
            "application/json"
        ],
        "tags": [         # Define tags used in routes for organization
            { "name": "Raw Data", "description": "Endpoints for fetching raw data from external sources." },
            { "name": "Data Storage & Processing", "description": "Endpoints for storing and processing job offer data." },
            { "name": "Data Retrieval", "description": "Endpoints for retrieving stored data." },
            { "name": "Notifications", "description": "Endpoints related to sending notifications." },
            { "name": "System", "description": "Endpoints for system health and status checks." },
        ],
        "definitions": definitions # Include the shared definitions
    }

    # Initialize Swagger with the app, config, and template
    return Swagger(app, config=swagger_config, template=swagger_template)

# --- END OF UPDATED FILE swagger.py