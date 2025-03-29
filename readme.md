# Manfred Job Fetcher

A simple Dockerized application designed to fetch active job offers from GetManfred's public API endpoints. It can be used to monitor job listings and potentially send notifications about new or relevant findings to a specified webhook URL.

## Features

*   Fetches currently active job offers (in Spanish) from Manfred's public API.
*   Can be adapted to retrieve detailed data for individual job offers.
*   Runs as an isolated Docker container.
*   Configurable through environment variables (API endpoints, notification webhook).
*   Includes a simple SQLite database (`/app/data/history.db`) for optional logging or state persistence.
*   (Example Implementation) Can be triggered via a `/trigger` HTTP endpoint using Flask.

## API Endpoints Used

This tool primarily interacts with the following GetManfred public API endpoints:

1.  **Offers List:** `https://www.getmanfred.com/api/v2/public/offers?lang=ES&onlyActive=true`
    *   **Purpose:** Fetches the list of currently active job offers in Spanish. Provides basic information including the `offerId` (Job ID) needed for detailed lookups.

2.  **Offer Details:** `https://www.getmanfred.com/_next/data/BUILD_ID_HASH/es/job-offers/{job-id}/{job-name}.json`
    *   **Purpose:** Fetches detailed information about a specific job offer.
    *   **Placeholders:**
        *   `BUILD_ID_HASH`: This seems to be a dynamic hash related to the website's build (e.g., `BIDHCAYe6i8X-XyfefcMo` in the example). **This might change without notice**, potentially breaking detail fetching. You may need to inspect network requests on the Manfred site to find the current hash if this endpoint fails.
        *   `{job-id}`: The unique ID of the job offer (obtained from the Offers List endpoint, e.g., `offerId`).
        *   `{job-name}`: The URL-friendly slug/name of the job offer.
    *   **Note:** Due to the potentially dynamic nature of the `BUILD_ID_HASH`, relying heavily on this endpoint might require periodic maintenance.

## Prerequisites

*   [Docker](https://docs.docker.com/get-docker/) installed on your system.

## Configuration

The application is configured using environment variables when running the Docker container:

*   `EXTERNAL_ENDPOINT_URL`: (Optional, but recommended) The primary API endpoint to fetch the list of offers from. Defaults might be present in the code, but setting it explicitly is better.
    *   Example: `https://www.getmanfred.com/api/v2/public/offers?lang=ES&onlyActive=true`
*   `DISCORD_WEBHOOK_URL`: **Required.** The Webhook URL used to send notifications (e.g., to a Discord channel, Slack, or other compatible service). **Treat this URL as a secret! Do not commit it to your repository.**
*   (Optional) You might add other variables for the detail endpoint pattern, database path, etc., as needed by your script (`app.py`).

## Building the Docker Image

1.  Clone this repository:
    ```bash
    git clone https://github.com/your-username/manfred-job-fetcher.git
    cd manfred-job-fetcher
    ```
    *(Replace `your-username` with your actual GitHub username)*

2.  Build the Docker image:
    ```bash
    docker build -t manfred-job-fetcher .
    ```
    *(Using the repo name as the image tag is a common convention)*

## Running the Container

You need to provide the necessary environment variables and mount a volume for data persistence (the SQLite database).

```bash
docker run -d \
  -p 8080:5000 \
  -e EXTERNAL_ENDPOINT_URL="https://www.getmanfred.com/api/v2/public/offers?lang=ES&onlyActive=true" \
  -e DISCORD_WEBHOOK_URL="YOUR_NOTIFICATION_WEBHOOK_URL_HERE" \
  -v $(pwd)/data:/app/data \
  --name manfred-fetcher-instance \
  manfred-job-fetcher