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
        "specs_route": "/api/docs"
    }

    swagger_template = {
        "info": {
            "title": "Manfred Job Fetcher API",
            "description": "API for fetching and managing job offers from GetManfred's public API",
            "version": "1.0.0",
            "contact": {
                "email": "your.email@example.com"
            },
        },
        "schemes": [
            "http",
            "https"
        ],
        "tags": [
            {
                "name": "Job Offers",
                "description": "Operations related to job offers"
            },
            {
                "name": "System",
                "description": "System health and statistics"
            }
        ],
    }

    return Swagger(app, config=swagger_config, template=swagger_template)