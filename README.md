---

## HNG Stage 2: Country Data API

This project is a robust, high-performance RESTful API built for the HNG Internship Stage 2 Backend Task. The service fetches country and currency exchange rate data from external APIs, processes and enriches this data, caches it in a persistent database, and provides a suite of endpoints for CRUD operations and data retrieval.

The application is built with a focus on performance, scalability, and robustness, utilizing asynchronous programming for I/O-bound tasks and efficient bulk database operations.

**Live API Documentation (Swagger UI):**
**[https://hng-stage-2-countries-zichdan7442-9x1yl5ab.leapcell.dev/](https://hng-stage-2-countries-zichdan7442-9x1yl5ab.leapcell.dev/)**

## Key Features

-   **Data Aggregation:** Fetches and combines data from two separate external APIs ([RestCountries](https://restcountries.com/) and [Open Exchange Rates](https://open.er-api.com/)).
-   **Database Caching:** All processed data is stored in a persistent PostgreSQL/MySQL database to ensure fast and reliable access.
-   **High-Performance Refresh:** The `POST /countries/refresh` endpoint uses `asyncio` and `httpx` to make concurrent API calls, and Django's `bulk_create` / `bulk_update` for highly efficient database writes, all within a single atomic transaction.
-   **Rich Filtering & Sorting:** The main `GET /countries` endpoint supports filtering by `region` and `currency_code`, as well as sorting by fields like `estimated_gdp`.
-   **Dynamic Image Generation:** Automatically generates and serves a summary image (`/countries/image`) displaying key statistics and country flags after each data refresh.
-   **Robust Error Handling:** Gracefully handles external API failures, timeouts, and database errors, returning appropriate HTTP status codes (503, 404, 400, etc.).
-   **Interactive API Documentation:** Includes a full Swagger UI for easy exploration and testing of all endpoints.

## Technology Stack

-   **Backend Framework:** Django & Django REST Framework
-   **Database:** PostgreSQL / MySQL
-   **Asynchronous HTTP:** `httpx`, `asyncio`
-   **Image Processing:** `Pillow`
-   **Production Server:** Gunicorn
-   **API Documentation:** `drf-yasg` (Swagger)

---

## API Documentation

All endpoints are detailed below. You can also interact with them live via the [Swagger UI](https://hng-stage-2-countries-zichdan7442-9x1yl5ab.leapcell.dev/).

### `POST /countries/refresh`

-   **Description:** The core endpoint. Fetches fresh data from the external APIs, processes it, and updates the local database cache. This is a long-running, high-performance task.
-   **Request Body:** None.
-   **Success Response (200 OK):**
    ```json
    {
        "status": "success",
        "countries_processed": 250
    }
    ```
-   **Error Response (503 Service Unavailable):**
    ```json
    {
        "error": "External data source unavailable",
        "details": "Could not fetch data from RestCountries API"
    }
    ```

### `GET /countries`

-   **Description:** Retrieves a paginated list of all countries from the database.
-   **Query Parameters:**
    -   `region` (string): Filters countries by region (e.g., `?region=Africa`).
    -   `currency_code` (string): Filters countries by currency code (e.g., `?currency_code=NGN`).
    -   `ordering` (string): Sorts the results. Use `-` for descending order (e.g., `?ordering=-estimated_gdp`).
-   **Success Response (200 OK):**
    ```json
    [
        {
            "id": 1,
            "name": "Nigeria",
            "capital": "Abuja",
            "region": "Africa",
            "population": 206139589,
            "currency_code": "NGN",
            "exchange_rate": "1600.2300",
            "estimated_gdp": "25767448125.20",
            "flag_url": "https://flagcdn.com/ng.svg",
            "last_refreshed_at": "2025-10-25T18:00:00Z"
        }
    ]
    ```

### `GET /countries/{name}`

-   **Description:** Retrieves a single country by its name.
-   **Success Response (200 OK):** A single country object (same structure as above).
-   **Error Response (404 Not Found):**
    ```json
    { "detail": "Not found." }
    ```

### `DELETE /countries/{name}`

-   **Description:** Deletes a country record from the database by its name.
-   **Success Response:** `204 No Content` with an empty body.
-   **Error Response (404 Not Found):**
    ```json
    { "detail": "Not found." }
    ```

### `GET /status`

-   **Description:** Provides a quick status check of the data cache.
-   **Success Response (200 OK):**
    ```json
    {
        "total_countries": 250,
        "last_refreshed_at": "2025-10-25T18:00:00Z"
    }
    ```

### `GET /countries/image`

-   **Description:** Serves the dynamically generated summary image.
-   **Success Response (200 OK):** An image file (`image/png`).
-   **Error Response (404 Not Found):**
    ```json
    {
        "error": "Summary image not found. Run the /countries/refresh endpoint first."
    }
    ```

---

## Local Setup Instructions

Follow these steps to run the project on your local machine.

#### 1. Prerequisites
-   Python 3.8+
-   Git
-   A running PostgreSQL or MySQL database.

#### 2. Clone the Repository
```bash
git clone https://github.com/zichdan/hng-stage-2-countries.git
cd hng-stage-2-countries
```

#### 3. Set Up a Virtual Environment
```bash
# Create and activate the virtual environment
python -m venv venv
source venv/bin/activate  # On Windows: .\venv\Scripts\activate
```

#### 4. Install Dependencies
All required packages are listed in `requirements.txt`.
```bash
pip install -r requirements.txt
```

#### 5. Configure Environment Variables
Create a `.env` file in the project root. You can copy the provided `.env.example` as a template.
```bash
cp .env.example .env
```
Now, open the `.env` file and add your database URL and a Django secret key.

#### 6. Run Database Migrations
This command will create the necessary tables in your database.
```bash
python manage.py migrate
```

#### 7. Run the Development Server
```bash
python manage.py runserver
```
The API will be available at `http://127.0.0.1:8000/`.

## Environment Variables

The following environment variables are required. They should be placed in a `.env` file for local development or set in your hosting provider's dashboard for production.

| Variable | Description | Example Value |
| :--- |:---| :--- |
| `SECRET_KEY` | A long, unique secret key for Django's security features. | `your-super-secret-django-key` |
| `DEBUG` | Toggles Django's debug mode. Must be `False` in production. | `True` |
| `DATABASE_URL`| The connection string for your database. | `postgres://user:pass@host/db` |
| `ALLOWED_HOSTS`| Comma-separated list of trusted domains for production. | `myapp.com,127.0.0.1` |

## Testing the API

After setting up the project locally:

1.  **Crucial First Step:** Send a `POST` request to the `http://127.0.0.1:8000/countries/refresh` endpoint. This will populate your database. You can do this easily from the [Swagger UI](http://127.0.0.1:8000/).
2.  Once the refresh is complete (it may take 10-20 seconds), you can test all the `GET` endpoints to retrieve the data.
3.  Test the `GET /countries/image` endpoint to see the generated summary image.

## Performance & Architectural Notes

-   **Asynchronous I/O:** The `refresh_country_data` service uses `asyncio` and `httpx` to make concurrent, non-blocking calls to the external APIs, significantly reducing the total time spent waiting for network responses.
-   **Bulk Database Operations:** Instead of inserting or updating records one by one in a loop (which is highly inefficient), the application prepares lists of new and existing countries in memory and then uses Django's `bulk_create` and `bulk_update` to commit them to the database in a minimal number of queries.
-   **Data Integrity:** All database write operations during a refresh are wrapped in a single `transaction.atomic()` block. This ensures that the entire operation succeeds or fails as a whole, preventing partial updates and maintaining data consistency.

## Author

-   **Name:** Daniel Ezichi Okorie
