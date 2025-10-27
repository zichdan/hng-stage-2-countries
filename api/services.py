# api/services.py
import asyncio
import httpx
import logging
import os
import random
from django.utils import timezone
from django.db import transaction, DatabaseError
from django.conf import settings
from PIL import Image, ImageDraw, ImageFont, UnidentifiedImageError
from io import BytesIO
from asgiref.sync import sync_to_async

# Import the models from the current app
from .models import Country, CacheStatus






# ==============================================================================
# CONFIGURATION AND SETUP
# ==============================================================================

# Get a logger instance specific to this 'api' app.
# The logger's behavior is configured in the main settings.py file.
logger = logging.getLogger('api')

# Define constants for external API URLs to avoid "magic strings" in the code.
COUNTRIES_API_URL = "https://restcountries.com/v2/all?fields=name,capital,region,population,flag,currencies"
EXCHANGE_RATE_API_URL = "https://open.er-api.com/v6/latest/USD"



# --- Read-Only Filesystem Fix ---
# Production environments are often read-only. The only writable directory is /tmp.
# We define the image path to be in /tmp for production, but in the local media
# folder for development, making it easy to find and view locally.
if settings.DEBUG:
    # Local development path (easy to find)
    SUMMARY_IMAGE_PATH = os.path.join(settings.MEDIA_ROOT, 'cache', 'summary.png')
else:
    # Production path (writable on serverless platforms)
    SUMMARY_IMAGE_PATH = '/tmp/cache/summary.png'






# Custom exception for handling errors from external services gracefully.
class ExternalServiceError(Exception):
    def __init__(self, service_name, status_code=None):
        self.service_name = service_name
        self.status_code = status_code
        super().__init__(f"Could not fetch data from {service_name}")




        

# ==============================================================================
# IMAGE GENERATION LOGIC
# ==============================================================================

async def _generate_summary_image():
    """
    Generates a summary image with country data and flags.
    This is an async function to allow for non-blocking fetching of flag images.
    """
    logger.debug("Starting summary image generation...")
    try:
        # Fetch data from the database. Use `sync_to_async` to run synchronous Django ORM calls
        # from within this asynchronous function. This is the standard way to bridge async/sync code.
        total_countries_task = sync_to_async(Country.objects.count)()
        top_5_gdp_task = sync_to_async(list)(Country.objects.order_by('-estimated_gdp').values('name', 'estimated_gdp', 'flag_url')[:5])
        cache_status_task = sync_to_async(CacheStatus.objects.get_or_create)(pk=1)
        
        # Run all database queries concurrently
        total_countries, top_5_gdp, (cache_status, _) = await asyncio.gather(
            total_countries_task, top_5_gdp_task, cache_status_task
        )
        logger.debug(f"Image data fetched: {total_countries} countries, Top 5 GDP list ready.")

        # --- Fetch Flag Images Concurrently ---
        async with httpx.AsyncClient() as client:
            flag_tasks = [client.get(country['flag_url']) for country in top_5_gdp if country['flag_url']]
            flag_responses = await asyncio.gather(*flag_tasks, return_exceptions=True)
        
        flag_images = []
        for response in flag_responses:
            if isinstance(response, Exception) or response.status_code != 200:
                logger.warning(f"Failed to fetch a flag image. Skipping. Error: {response}")
                flag_images.append(None) # Add a placeholder for failed flags
            else:
                try:
                    # Open the image from the binary content of the response
                    flag_image = Image.open(BytesIO(response.content))
                    flag_images.append(flag_image)
                except UnidentifiedImageError:
                    logger.warning(f"Could not identify image from response. Skipping.")
                    flag_images.append(None)
        
        logger.debug(f"Fetched {len([img for img in flag_images if img])} flag images successfully.")
        
        # --- Create and Draw on the Image ---
        img = Image.new('RGB', (1000, 800), color='white')
        d = ImageDraw.Draw(img)
        
        try:
            # Define the path to the font file included in our project.
            # This is more reliable than depending on system-installed fonts.
            font_path = os.path.join(settings.BASE_DIR, 'api', 'assets', 'Roboto-Regular.ttf')
            title_font = ImageFont.truetype(font_path, 36)
            header_font = ImageFont.truetype(font_path, 28)
            text_font = ImageFont.truetype(font_path, 22)
        except IOError:
            logger.warning(f"Font not found at {font_path}. Falling back to default font.")
            title_font = header_font = text_font = ImageFont.load_default()

        # Draw text content
        d.text((50, 40), "Country Data Summary", fill=(0,0,0), font=title_font)
        d.text((50, 110), f"Total Countries Cached: {total_countries}", fill=(50,50,50), font=text_font)
        
        refresh_time = cache_status.last_full_refresh_at
        if refresh_time:
            d.text((50, 150), f"Last Refreshed: {refresh_time.strftime('%Y-%m-%d %H:%M:%S UTC')}", fill=(50,50,50), font=text_font)
        
        d.text((50, 230), "Top 5 Countries by Estimated GDP:", fill=(0,0,0), font=header_font)
        
        # Draw each country's info with its flag
        y_pos = 300
        for i, country in enumerate(top_5_gdp):
            # Paste the flag image if it was successfully downloaded
            if i < len(flag_images) and flag_images[i]:
                flag = flag_images[i].resize((60, 40)) # Resize flag to a consistent size
                img.paste(flag, (60, y_pos))
            
            # Format the GDP value to be more readable
            gdp_in_billions = country.get('estimated_gdp', 0) / 1_000_000_000 if country.get('estimated_gdp') else 0
            text = f"{i+1}. {country.get('name', 'N/A')} - GDP: ${gdp_in_billions:,.2f} Billion"
            
            # Draw the text next to the flag
            d.text((140, y_pos + 5), text, fill=(20,20,20), font=text_font)
            y_pos += 80 # Increase vertical spacing for flags

        # Create the directory if it doesn't exist.
        os.makedirs(os.path.dirname(SUMMARY_IMAGE_PATH), exist_ok=True)
        # Save the final image to the designated path
        img.save(SUMMARY_IMAGE_PATH)
        logger.info(f"Summary image successfully generated and saved to {SUMMARY_IMAGE_PATH}")

    except Exception as e:
        # Catch any unexpected errors during image generation to prevent the whole refresh from failing.
        logger.error(f"Failed to generate summary image: {e}", exc_info=True)











# ==============================================================================
# MAIN DATA REFRESH LOGIC
# ==============================================================================

async def _fetch_api_data():
    """Asynchronously fetches data from both external APIs concurrently."""
    logger.info("Starting concurrent fetch from external APIs...")
    # Use an async context manager for the HTTP client
    async with httpx.AsyncClient(timeout=30) as client:
        try:
            # Create tasks to run the API calls in parallel
            tasks = [client.get(COUNTRIES_API_URL), client.get(EXCHANGE_RATE_API_URL)]
            # Wait for both tasks to complete
            responses = await asyncio.gather(*tasks, return_exceptions=True)
            
            countries_response, rates_response = responses

            # Handle potential failure for each request individually
            if isinstance(countries_response, Exception):
                logger.error("Failed to fetch from RestCountries API.", exc_info=countries_response)
                raise ExternalServiceError("RestCountries API")
            countries_response.raise_for_status()
            logger.debug(f"RestCountries API responded with status {countries_response.status_code}")

            if isinstance(rates_response, Exception):
                logger.error("Failed to fetch from Open Exchange Rate API.", exc_info=rates_response)
                raise ExternalServiceError("Open Exchange Rate API")
            rates_response.raise_for_status()
            logger.debug(f"Open Exchange Rate API responded with status {rates_response.status_code}")
            
            logger.info("Successfully fetched data from both APIs.")
            # Return the parsed JSON data
            return countries_response.json(), rates_response.json().get('rates', {})

        except httpx.HTTPStatusError as e:
            # Handle non-2xx responses from the APIs
            service_name = "RestCountries API" if COUNTRIES_API_URL in str(e.request.url) else "Open Exchange Rate API"
            logger.error(f"{service_name} returned non-2xx status: {e.response.status_code}")
            raise ExternalServiceError(service_name, e.response.status_code)
        except httpx.RequestError as e:
            # Handle network-level errors like timeouts or connection issues
            logger.error(f"A network error occurred: {e}", exc_info=True)
            raise ExternalServiceError("One or more external APIs")

def refresh_country_data():
    """
    High-performance main function to refresh all country data.
    It orchestrates the async fetching and bulk database operations.
    """
    logger.info("Country data refresh process initiated.")
    
    # Run the asynchronous function to get all data first.
    countries_data, exchange_rates = asyncio.run(_fetch_api_data())
    logger.info(f"Processing {len(countries_data)} countries and {len(exchange_rates)} exchange rates.")
    
    try:
        # ** Performance Optimization **
        # Fetch all existing countries from the database into a dictionary in one query.
        # `list()` forces the query to execute immediately.
        existing_countries = {c.name.lower(): c for c in list(Country.objects.all())}
        logger.debug(f"Successfully loaded {len(existing_countries)} existing countries from the database.")
    except DatabaseError as e:
        # Handle cases where the database is unavailable
        logger.error(f"Database error while fetching existing countries: {e}", exc_info=True)
        raise Exception("Could not connect to or read from the database.") from e

    # Prepare lists in memory to hold objects for creation and updating
    countries_to_create = []
    countries_to_update = []
    
    # Loop through the API data in memory, not hitting the DB in the loop
    for country_data in countries_data:
        name = country_data.get('name')
        if not name:
            logger.warning(f"Skipping country with missing name: {country_data}")
            continue

        # Make sure population is a valid integer, defaulting to 0 if missing or null.
        population = int(country_data.get('population', 0) or 0)
        
        currency_code = None
        if country_data.get('currencies'):
            currency_code = country_data['currencies'][0].get('code')
        
        exchange_rate = exchange_rates.get(currency_code) if currency_code else None
        
        estimated_gdp = 0
        # ==============================================================================
        # MODIFIED SECTION: Robust GDP Calculation
        # ==============================================================================
        # FIX: Wrap the GDP calculation in a try-except block.
        # This prevents the entire refresh from crashing if an `exchange_rate` is not a
        # valid number (e.g., a string), which would cause a TypeError.
        try:
            # We explicitly convert exchange_rate to a float to ensure the comparison is valid.
            if population and exchange_rate and float(exchange_rate) > 0:
                multiplier = random.uniform(1000, 2000)
                estimated_gdp = (population * multiplier) / float(exchange_rate)
        except (ValueError, TypeError):
            # If `exchange_rate` cannot be converted to a float, log the issue
            # and set it to None, ensuring the country is still saved without a GDP.
            logger.warning(f"Could not parse exchange rate for {name} (Currency: {currency_code}). Value: {exchange_rate}")
            exchange_rate = None
        # ==============================================================================
        # END MODIFIED SECTION
        # ==============================================================================

        # Check against our in-memory dictionary
        instance = existing_countries.get(name.lower())
        
        if instance:
            # If it exists, update its attributes and add it to the update list
            instance.capital = country_data.get('capital')
            instance.region = country_data.get('region')
            instance.population = population
            instance.currency_code = currency_code
            instance.exchange_rate = exchange_rate
            instance.estimated_gdp = estimated_gdp
            instance.flag_url = country_data.get('flag')
            countries_to_update.append(instance)
        else:
            # If it's new, create a new Country model instance and add it to the create list
            countries_to_create.append(
                Country(
                    name=name,
                    capital=country_data.get('capital'),
                    region=country_data.get('region'),
                    population=population,
                    currency_code=currency_code,
                    exchange_rate=exchange_rate,
                    estimated_gdp=estimated_gdp,
                    flag_url=country_data.get('flag'),
                )
            )
            
    logger.info(f"Prepared {len(countries_to_create)} new countries for creation.")
    logger.info(f"Prepared {len(countries_to_update)} existing countries for update.")
    
    try:
        # Use a single atomic transaction for all database writes.
        # This ensures that if any part fails, the entire operation is rolled back,
        # leaving the database in a consistent state.
        with transaction.atomic():
            logger.debug("Starting atomic database transaction...")
            if countries_to_create:
                # Use bulk_create for a single, efficient INSERT query for all new countries
                Country.objects.bulk_create(countries_to_create)
                logger.info(f"Successfully bulk-created {len(countries_to_create)} countries.")
                
            if countries_to_update:
                # Use bulk_update for a single, efficient UPDATE query for all existing countries
                Country.objects.bulk_update(
                    countries_to_update,
                    ['capital', 'region', 'population', 'currency_code', 'exchange_rate', 'estimated_gdp', 'flag_url']
                )
                logger.info(f"Successfully bulk-updated {len(countries_to_update)} countries.")
            
            # Update the global refresh timestamp
            now_aware = timezone.now()
            CacheStatus.objects.update_or_create(pk=1, defaults={'last_full_refresh_at': now_aware})
            logger.info(f"Updated cache status with new refresh time: {now_aware}")
            logger.debug("Committing database transaction.")
    except DatabaseError as e:
        # Handle failures during the bulk write operations
        logger.error(f"Database error during bulk operations: {e}", exc_info=True)
        raise Exception("Failed to save data to the database.") from e

    # After the database is successfully updated, generate the summary image
    # We run this in the background to avoid blocking the main thread
    asyncio.run(_generate_summary_image())
    
    logger.info("Country data refresh process completed successfully.")
    return {"status": "success", "countries_processed": len(countries_data)}




