# Manfred Job Fetcher

A simple Dockerized application designed to fetch active job offers from GetManfred's public API endpoints. It can be used to monitor job listings and potentially send notifications about new or relevant findings to a specified webhook URL.

---

## Features

- Fetches currently active job offers (in Spanish) from Manfred's public API.
- Retrieves detailed data for individual job offers, including skills information.
- Dynamically manages the BUILD_ID_HASH by fetching it from the website, ensuring continuous operation.
- Runs as an isolated Docker container.
- Configurable through environment variables (API endpoints, notification webhook).
- Includes a SQLite database (`/app/data/history.db`) for job history and skills data persistence.
- Provides a web UI for database browsing via SQLite Web container.
- REST API endpoints for triggering actions and retrieving data.
- Sends custom-formatted notifications to Discord webhooks.

---

## API Endpoints

This tool provides several REST API endpoints:

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/raw-offers` | GET | Fetches raw data from the Manfred API without processing |
| `/store-offers` | POST | Fetches, stores, and processes job offers and skills |
| `/process-job-details` | POST | Processes pending job offers to retrieve skills information |
| `/job-skills/{offer_id}` | GET | Retrieves stored skills for a specific job offer |
| `/send-notifications` | POST | Sends pending notifications to the configured webhook |
| `/update-build-hash` | PUT | Manually triggers an update of the BUILD_ID_HASH from Manfred's website |
| `/health` | GET | System health check, including database connectivity |
| `/cleanup-notifications` | DELETE | Deletes messages for job offers that are no longer active |
| `/api/docs` | GET | Swagger UI documentation for all endpoints |

---

## External APIs Used

This tool primarily interacts with the following GetManfred public API endpoints:

1. **Offers List:**  
   `https://www.getmanfred.com/api/v2/public/offers?lang=ES&onlyActive=true`  
   **Purpose:** Fetches the list of currently active job offers in Spanish.

2. **Offer Details:**  
   `https://www.getmanfred.com/_next/data/BUILD_ID_HASH/es/job-offers/{job-id}/{job-name}.json`  
   **Purpose:** Fetches detailed information about a specific job offer.  
   **Placeholders:**
   - `BUILD_ID_HASH`: This is a dynamic hash from the website's build. The application automatically detects and updates this hash when it changes.
   - `{job-id}`: The unique ID of the job offer (from the Offers List).
   - `{job-name}`: The URL-friendly slug or name of the job offer.

---

## Prerequisites

- [Docker](https://docs.docker.com/get-docker/) and [Docker Compose](https://docs.docker.com/compose/install/) installed on your system.

---

## Configuration

The application is configured using environment variables when running the Docker container:

| Variable                  | Description                                 | Default                                                                 |
|---------------------------|---------------------------------------------|-------------------------------------------------------------------------|
| `EXTERNAL_ENDPOINT_URL`   | API endpoint for job offers                 | `https://www.getmanfred.com/api/v2/public/offers?lang=ES&onlyActive=true` |
| `DISCORD_WEBHOOK_URL`     | Webhook URL for notifications               | **Required**, no default                                                |
| `DETAIL_ENDPOINT_PATTERN` | Pattern for detail endpoints                | `https://www.getmanfred.com/_next/data/${BUILD_ID_HASH}/es/job-offers/{offer_id}/{offer_slug}.json` |
| `DB_PATH`                 | Path to SQLite database                     | `/app/data/history.db`                                                 |
| `RESET_DB`                | Whether to reset the database on startup    | `false`                                                                |
| `FETCH_INTERVAL`          | Time between fetches (seconds)             | `3600` (1 hour)                                                         |
| `MAX_RETRIES`             | Maximum API request retries                | `3`                                                                     |
| `RETRY_BACKOFF`           | Backoff factor for retries                 | `0.5`                                                                   |
| `FLASK_ENV`               | Flask environment setting                  | `production`                                                           |
| `FLASK_DEBUG`             | Flask debug mode                           | `0`                                                                    |

You can define these in a `.env` file.

---

## Using Environment Variables

This application is configured using environment variables. For convenience, you can use a `.env` file instead of specifying them all in the `docker run` command.

1. Copy the sample environment file to create your own:
   ```bash
   cp .env.sample .env
   ```

2. Edit the `.env` file and update the values, especially:
   ```
   DISCORD_WEBHOOK_URL=https://discord.com/api/webhooks/your-webhook-url-here
   ```

---

## Running with Docker Compose

The easiest way to run the application is with Docker Compose:

1. Make sure you've created and configured your `.env` file as described above.

2. Build and start the container:
   ```bash
   docker-compose up -d
   ```

3. To stop the container:
   ```bash
   docker-compose down
   ```

4. Access the SQLite Web UI to browse the database:
   ```
   http://localhost:8081
   ```

5. Access the API documentation:
   ```
   http://localhost:8080/docs
   ```

---

## Running with Docker CLI and .env file

If you prefer using the Docker CLI directly, you can use the `--env-file` option:

```bash
docker build -t manfred-job-fetcher .
docker run -d \
  -p 8080:5000 \
  --env-file .env \
  -v $(pwd)/data:/app/data \
  --name manfred-fetcher-instance \
  manfred-job-fetcher
```

---

## Database Schema

The application uses SQLite with the following tables:

1. **fetch_history**: Logs API requests and responses
2. **job_offers**: Stores the main job offer data
3. **job_skills**: Stores skills requirements for each job (must, nice, extra categories)

The database is persisted on the host machine in the `./data` directory.

---

## Building the Docker Image

1. Clone this repository:
   ```bash
   git clone https://github.com/your-username/manfred-job-fetcher.git
   cd manfred-job-fetcher
   ```
   *(Replace `your-username` with your actual GitHub username)*

2. Build the Docker image:
   ```bash
   docker build -t manfred-job-fetcher .
   ```

---

## Discord Notifications

The application can send notifications about new job offers to a Discord webhook. Each notification includes:

- Job position and company
- Salary information (if available)
- Remote work percentage
- Location information
- Must-have and nice-to-have skills (when available)
- Direct link to the offer on the Manfred website

Configure the webhook URL in the `.env` file:
```
DISCORD_WEBHOOK_URL=https://discord.com/api/webhooks/your-webhook-url-here
```

---

## Automatic BUILD_ID_HASH Management

The application manages the BUILD_ID_HASH dynamically, which is crucial for accessing the job details endpoint:

1. **Initial Fetch**: On first startup, the application will attempt to fetch the current hash from Manfred's website.

2. **Persistent Storage**: The hash is stored in a JSON file at `./data/config/build_hash.json` for persistence between restarts.

3. **Auto-Updates**: If a request fails due to an invalid hash, the system automatically:
   - Fetches the Manfred homepage
   - Extracts the current hash
   - Updates the JSON file 
   - Retries the original request with the updated hash

4. **Manual Updates**: You can trigger a manual update via the `/update-build-hash` endpoint if needed.

> 📝 **Note**: You do not need to set the BUILD_ID_HASH in your .env file anymore. The application will handle this automatically.