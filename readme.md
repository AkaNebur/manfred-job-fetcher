# Manfred Job Fetcher

A simple Dockerized application designed to fetch active job offers from GetManfred's public API endpoints. It can be used to monitor job listings and potentially send notifications about new or relevant findings to a specified webhook URL.

---

## Features

- Fetches currently active job offers (in Spanish) from Manfred's public API.
- Can be adapted to retrieve detailed data for individual job offers.
- Runs as an isolated Docker container.
- Configurable through environment variables (API endpoints, notification webhook).
- Includes a simple SQLite database (`/app/data/history.db`) for optional logging or state persistence.
- (Example Implementation) Can be triggered via a `/trigger` HTTP endpoint using Flask.

---

## API Endpoints Used

This tool primarily interacts with the following GetManfred public API endpoints:

1. **Offers List:**  
   `https://www.getmanfred.com/api/v2/public/offers?lang=ES&onlyActive=true`  
   **Purpose:** Fetches the list of currently active job offers in Spanish. Provides basic information including the `offerId` (Job ID) needed for detailed lookups.

2. **Offer Details:**  
   `https://www.getmanfred.com/_next/data/BUILD_ID_HASH/es/job-offers/{job-id}/{job-name}.json`  
   **Purpose:** Fetches detailed information about a specific job offer.  
   **Placeholders:**
   - `BUILD_ID_HASH`: This is a dynamic hash from the website’s build (e.g., `BIDHCAYe6i8X-XyfefcMo`). This **can change without notice**, potentially breaking detail fetching.
   - `{job-id}`: The unique ID of the job offer (from the Offers List).
   - `{job-name}`: The URL-friendly slug or name of the job offer.

> ⚠️ **Note:** Due to the potentially dynamic nature of the `BUILD_ID_HASH`, relying heavily on this endpoint might require periodic maintenance. You may need to inspect the website's network traffic to find the current build hash.

---

## Prerequisites

- [Docker](https://docs.docker.com/get-docker/) installed on your system.

---

## Configuration

The application is configured using environment variables when running the Docker container:

| Variable                  | Description                                 | Default                                                                 |
|---------------------------|---------------------------------------------|-------------------------------------------------------------------------|
| `EXTERNAL_ENDPOINT_URL`   | API endpoint for job offers                 | `https://www.getmanfred.com/api/v2/public/offers?lang=ES&onlyActive=true` |
| `DISCORD_WEBHOOK_URL`     | Webhook URL for notifications               | **Required**, no default                                                |
| `BUILD_ID_HASH`           | Hash for detail API endpoints               | `BIDHCAYe6i8X-XyfefcMo`                                                 |
| `DETAIL_ENDPOINT_PATTERN` | Pattern for detail endpoints                | Uses `BUILD_ID_HASH`                                                   |
| `DB_PATH`                 | Path to SQLite database                     | `/app/data/history.db`                                                 |
| `FETCH_INTERVAL`          | Time between fetches (seconds)             | `300`                                                                   |
| `MAX_RETRIES`             | Maximum API request retries                | `3`                                                                     |
| `RETRY_BACKOFF`           | Backoff factor for retries                 | `0.5`                                                                   |

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

## Running the Container (Manual Mode)

You need to provide the necessary environment variables and mount a volume for data persistence (the SQLite database):

```bash
docker run -d \
  -p 8080:5000 \
  -e EXTERNAL_ENDPOINT_URL="https://www.getmanfred.com/api/v2/public/offers?lang=ES&onlyActive=true" \
  -e DISCORD_WEBHOOK_URL="YOUR_NOTIFICATION_WEBHOOK_URL_HERE" \
  -v $(pwd)/data:/app/data \
  --name manfred-fetcher-instance \
  manfred-job-fetcher
```