FROM python:3.9-slim

WORKDIR /app

# Install curl for healthcheck and dependencies
RUN apt-get update && apt-get install -y curl && \
    apt-get clean && rm -rf /var/lib/apt/lists/*

# Install dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Create data directory for SQLite database
RUN mkdir -p /app/data

# Copy application code
COPY app.py .
COPY swagger.py .

# Create startup script to reset DB
COPY entrypoint.sh .
RUN chmod +x entrypoint.sh

# Expose the port Flask will run on
EXPOSE 5000

# Add Docker healthcheck
HEALTHCHECK --interval=30s --timeout=10s --start-period=5s --retries=3 \
  CMD curl -f http://localhost:5000/health || exit 1

# Run the entrypoint script instead of directly running the app
CMD ["./entrypoint.sh"]