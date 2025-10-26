# api/services.py
import asyncio
import httpx
import logging
import os
import random
from django.utils import timezone
from django.db import transaction, DatabaseError
from django.conf import settings
from PIL import Image, ImageDraw, ImageFont

from .models import Country, CacheStatus

logger = logging.getLogger('api')

COUNTRIES_API_URL = "https://restcountries.com/v2/all?fields=name,capital,region,population,flag,currencies"
EXCHANGE_RATE_API_URL = "https://open.er-api.com/v6/latest/USD"
SUMMARY_IMAGE_PATH = os.path.join(settings.MEDIA_ROOT, 'cache', 'summary.png')

class ExternalServiceError(Exception):
    def __init__(self, service_name, status_code=None):
        self.service_name = service_name
        self.status_code = status_code
        super().__init__(f"Could not fetch data from {service_name}")

def _generate_summary_image():
    logger.debug("Starting summary image generation...")
    try:
        total_countries = Country.objects.count()
        top_5_gdp = list(Country.objects.order_by('-estimated_gdp').values('name', 'estimated_gdp')[:5])
        cache_status, _ = CacheStatus.objects.get_or_create(pk=1)
        
        img = Image.new('RGB', (800, 600), color='white')
        d = ImageDraw.Draw(img)
        
        try:
            font = ImageFont.truetype("arial.ttf", 24)
            small_font = ImageFont.truetype("arial.ttf", 18)
        except IOError:
            logger.warning("Arial font not found. Falling back to default font.")
            font = ImageFont.load_default()
            small_font = ImageFont.load_default()

        d.text((50, 50), "Country Data Summary", fill=(0,0,0), font=font)
        d.text((50, 100), f"Total Countries Cached: {total_countries}", fill=(0,0,0), font=small_font)
        
        refresh_time = cache_status.last_full_refresh_at
        if refresh_time:
            d.text((50, 130), f"Last Refreshed: {refresh_time.strftime('%Y-%m-%d %H:%M:%S UTC')}", fill=(0,0,0), font=small_font)
        
        d.text((50, 200), "Top 5 Countries by Estimated GDP:", fill=(0,0,0), font=font)
        y_pos = 250
        for i, country in enumerate(top_5_gdp):
            gdp_in_billions = country['estimated_gdp'] / 1_000_000_000 if country.get('estimated_gdp') else 0
            text = f"{i+1}. {country.get('name', 'N/A')}: ${gdp_in_billions:.2f} Billion"
            d.text((70, y_pos), text, fill=(0,0,0), font=small_font)
            y_pos += 30

        os.makedirs(os.path.dirname(SUMMARY_IMAGE_PATH), exist_ok=True)
        img.save(SUMMARY_IMAGE_PATH)
        logger.info(f"Summary image successfully generated and saved to {SUMMARY_IMAGE_PATH}")
    except Exception as e:
        logger.error(f"Failed to generate summary image: {e}", exc_info=True)


async def _fetch_api_data():
    logger.info("Starting concurrent fetch from external APIs...")
    async with httpx.AsyncClient(timeout=30) as client:
        try:
            tasks = [client.get(COUNTRIES_API_URL), client.get(EXCHANGE_RATE_API_URL)]
            responses = await asyncio.gather(*tasks, return_exceptions=True)
            
            countries_response, rates_response = responses

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
            return countries_response.json(), rates_response.json().get('rates', {})
        except httpx.HTTPStatusError as e:
            service_name = "RestCountries API" if COUNTRIES_API_URL in str(e.request.url) else "Open Exchange Rate API"
            logger.error(f"{service_name} returned non-2xx status: {e.response.status_code}")
            raise ExternalServiceError(service_name, e.response.status_code)
        except httpx.RequestError as e:
            logger.error(f"A network error occurred: {e}", exc_info=True)
            raise ExternalServiceError("One or more external APIs")


def refresh_country_data():
    """High-performance refresh function with detailed logging and robust database handling."""
    logger.info("Country data refresh process initiated.")
    
    countries_data, exchange_rates = asyncio.run(_fetch_api_data())
    logger.info(f"Processing {len(countries_data)} countries and {len(exchange_rates)} exchange rates.")
    
    try:
        # ** FIX 1: Force immediate evaluation into a dictionary **
        # This loads all data at once and releases the DB query.
        existing_countries = {c.name.lower(): c for c in list(Country.objects.all())}
        logger.debug(f"Successfully loaded {len(existing_countries)} existing countries from the database.")
    except DatabaseError as e:
        logger.error(f"Database error while fetching existing countries: {e}", exc_info=True)
        # Re-raise as a generic exception to be caught by the view
        raise Exception("Could not connect to or read from the database.") from e

    countries_to_create = []
    countries_to_update = []
    
    for country_data in countries_data:
        name = country_data.get('name')
        if not name:
            logger.warning(f"Skipping country with missing name: {country_data}")
            continue

        population = country_data.get('population', 0)
        
        currency_code = None
        if country_data.get('currencies'):
            currency_code = country_data['currencies'][0].get('code')
        
        exchange_rate = exchange_rates.get(currency_code) if currency_code else None
        
        estimated_gdp = 0
        if population and exchange_rate and exchange_rate > 0:
            multiplier = random.uniform(1000, 2000)
            estimated_gdp = (population * multiplier) / exchange_rate

        instance = existing_countries.get(name.lower())
        
        if instance:
            instance.capital = country_data.get('capital')
            instance.region = country_data.get('region')
            instance.population = population
            instance.currency_code = currency_code
            instance.exchange_rate = exchange_rate
            instance.estimated_gdp = estimated_gdp
            instance.flag_url = country_data.get('flag')
            countries_to_update.append(instance)
        else:
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
        with transaction.atomic():
            logger.debug("Starting atomic database transaction...")
            if countries_to_create:
                Country.objects.bulk_create(countries_to_create)
                logger.info(f"Successfully bulk-created {len(countries_to_create)} countries.")
                
            if countries_to_update:
                Country.objects.bulk_update(
                    countries_to_update,
                    ['capital', 'region', 'population', 'currency_code', 'exchange_rate', 'estimated_gdp', 'flag_url']
                )
                logger.info(f"Successfully bulk-updated {len(countries_to_update)} countries.")
            
            now_aware = timezone.now()
            CacheStatus.objects.update_or_create(pk=1, defaults={'last_full_refresh_at': now_aware})
            logger.info(f"Updated cache status with new refresh time: {now_aware}")
            logger.debug("Committing database transaction.")
    except DatabaseError as e:
        logger.error(f"Database error during bulk operations: {e}", exc_info=True)
        raise Exception("Failed to save data to the database.") from e

    _generate_summary_image()
    
    logger.info("Country data refresh process completed successfully.")
    return {"status": "success", "countries_processed": len(countries_data)}






