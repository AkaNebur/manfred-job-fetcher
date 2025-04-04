FROM python:3.9-slim

WORKDIR /app

# Install curl for healthcheck and dependencies
RUN apt-get update && apt-get install -y curl dos2unix && \
    apt-get clean && rm -rf /var/lib/apt/lists/*

# Install dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Create data directory for SQLite database
RUN mkdir -p /app/data

# Copy application code
COPY app.py .
COPY models.py .
COPY routes.py .
COPY config.py .
COPY scheduler.py .
COPY database.py .
COPY services.py .
COPY manfred_api.py .
COPY discord_notifier.py .

# Create startup script to reset DB
COPY entrypoint.sh .
# Convert to Unix line endings and make executable
RUN dos2unix entrypoint.sh && chmod +x entrypoint.sh

# Expose the port FastAPI will run on
EXPOSE 5000

# Add Docker healthcheck
HEALTHCHECK --interval=30s --timeout=10s --start-period=5s --retries=3 \
  CMD curl -f http://localhost:5000/health || exit 1

# Run the entrypoint script instead of directly running the app
CMD ["/bin/bash", "/app/entrypoint.sh"]