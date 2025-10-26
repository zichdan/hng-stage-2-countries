# api/services.py
import requests
import random
import os
import asyncio
import httpx
from datetime import datetime
from django.db import transaction
from django.conf import settings
from PIL import Image, ImageDraw, ImageFont
from asgiref.sync import sync_to_async

from .models import Country, CacheStatus

COUNTRIES_API_URL = "https://restcountries.com/v2/all?fields=name,capital,region,population,flag,currencies"
EXCHANGE_RATE_API_URL = "https://open.er-api.com/v6/latest/USD"
SUMMARY_IMAGE_PATH = os.path.join(settings.MEDIA_ROOT, 'cache', 'summary.png')

class ExternalServiceError(Exception):
    def __init__(self, service_name, status_code=None):
        self.service_name = service_name
        self.status_code = status_code
        super().__init__(f"Could not fetch data from {service_name}")

# We keep the image generation synchronous as it's a CPU-bound task
def _generate_summary_image():
    """Generates and saves the summary image."""
    total_countries = Country.objects.count()
    top_5_gdp = Country.objects.order_by('-estimated_gdp').values('name', 'estimated_gdp')[:5]
    cache_status, _ = CacheStatus.objects.get_or_create(pk=1, defaults={'last_full_refresh_at': datetime.now()})
    
    # Create image
    img = Image.new('RGB', (800, 600), color = 'white')
    d = ImageDraw.Draw(img)
    
    try:
        # Use a default font or specify a path to a .ttf file
        font = ImageFont.truetype("arial.ttf", 24)
        small_font = ImageFont.truetype("arial.ttf", 18)
    except IOError:
        font = ImageFont.load_default()
        small_font = ImageFont.load_default()

    # Draw text
    d.text((50, 50), f"Country Data Summary", fill=(0,0,0), font=font)
    d.text((50, 100), f"Total Countries Cached: {total_countries}", fill=(0,0,0), font=small_font)
    d.text((50, 130), f"Last Refreshed: {cache_status.last_full_refresh_at.strftime('%Y-%m-%d %H:%M:%S UTC')}", fill=(0,0,0), font=small_font)
    
    d.text((50, 200), "Top 5 Countries by Estimated GDP:", fill=(0,0,0), font=font)
    y_pos = 250
    for i, country in enumerate(top_5_gdp):
        gdp_in_billions = country['estimated_gdp'] / 1_000_000_000 if country['estimated_gdp'] else 0
        text = f"{i+1}. {country['name']}: ${gdp_in_billions:.2f} Billion"
        d.text((70, y_pos), text, fill=(0,0,0), font=small_font)
        y_pos += 30

    # Save image
    os.makedirs(os.path.dirname(SUMMARY_IMAGE_PATH), exist_ok=True)
    img.save(SUMMARY_IMAGE_PATH)

async def _fetch_api_data():
    """Asynchronously fetches data from both external APIs concurrently."""
    async with httpx.AsyncClient(timeout=30) as client:
        try:
            countries_task = client.get(COUNTRIES_API_URL)
            rates_task = client.get(EXCHANGE_RATE_API_URL)
            
            responses = await asyncio.gather(countries_task, rates_task, return_exceptions=True)
            
            countries_response, rates_response = responses

            if isinstance(countries_response, Exception):
                raise ExternalServiceError("RestCountries API")
            countries_response.raise_for_status()

            if isinstance(rates_response, Exception):
                raise ExternalServiceError("Open Exchange Rate API")
            rates_response.raise_for_status()

            return countries_response.json(), rates_response.json().get('rates', {})

        except httpx.HTTPStatusError as e:
            service_name = "RestCountries API" if COUNTRIES_API_URL in str(e.request.url) else "Open Exchange Rate API"
            raise ExternalServiceError(service_name, e.response.status_code)
        except httpx.RequestError:
            # This catches timeouts and connection errors
            raise ExternalServiceError("One or more external APIs")


# This is the main function called by the view
def refresh_country_data():
    """
    High-performance refresh function that uses asyncio for concurrent API calls
    and bulk database operations for efficiency.
    """
    # Run the async part of our code
    countries_data, exchange_rates = asyncio.run(_fetch_api_data())
    
    # Get all existing countries from DB at once to avoid multiple queries in the loop
    existing_countries = {c.name.lower(): c for c in Country.objects.all()}
    
    countries_to_create = []
    countries_to_update = []
    
    for country_data in countries_data:
        name = country_data['name']
        population = country_data.get('population', 0)
        
        currency_code = None
        if country_data.get('currencies'):
            currency_code = country_data['currencies'][0].get('code')
        
        exchange_rate = exchange_rates.get(currency_code) if currency_code else None
        
        estimated_gdp = 0
        if population and exchange_rate and exchange_rate > 0:
            multiplier = random.uniform(1000, 2000)
            estimated_gdp = (population * multiplier) / exchange_rate

        # Check if country exists (case-insensitive)
        instance = existing_countries.get(name.lower())
        
        if instance:
            # Prepare for bulk_update
            instance.capital = country_data.get('capital')
            instance.region = country_data.get('region')
            instance.population = population
            instance.currency_code = currency_code
            instance.exchange_rate = exchange_rate
            instance.estimated_gdp = estimated_gdp
            instance.flag_url = country_data.get('flag')
            countries_to_update.append(instance)
        else:
            # Prepare for bulk_create
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
            
    # Perform all database operations in a single atomic transaction
    with transaction.atomic():
        # Create new countries in one query
        if countries_to_create:
            Country.objects.bulk_create(countries_to_create)
            
        # Update existing countries in one query
        if countries_to_update:
            Country.objects.bulk_update(
                countries_to_update,
                ['capital', 'region', 'population', 'currency_code', 'exchange_rate', 'estimated_gdp', 'flag_url']
            )
        
        # Update the global refresh timestamp
        CacheStatus.objects.update_or_create(pk=1, defaults={'last_full_refresh_at': datetime.now()})

    # Generate the summary image after the transaction is complete
    # Use sync_to_async if you were in a fully async context, but here we can call it directly.
    _generate_summary_image()
    
    return {"status": "success", "countries_processed": len(countries_data)}









































# # api/services.py
# import requests
# import random
# import os
# from datetime import datetime
# from django.db import transaction
# from django.conf import settings
# from PIL import Image, ImageDraw, ImageFont

# from .models import Country, CacheStatus

# COUNTRIES_API_URL = "https://restcountries.com/v2/all?fields=name,capital,region,population,flag,currencies"
# EXCHANGE_RATE_API_URL = "https://open.er-api.com/v6/latest/USD"
# SUMMARY_IMAGE_PATH = os.path.join(settings.MEDIA_ROOT, 'cache', 'summary.png')

# class ExternalServiceError(Exception):
#     def __init__(self, service_name):
#         self.service_name = service_name
#         super().__init__(f"Could not fetch data from {service_name}")

# def _generate_summary_image():
#     """Generates and saves the summary image."""
#     total_countries = Country.objects.count()
#     top_5_gdp = Country.objects.order_by('-estimated_gdp').values('name', 'estimated_gdp')[:5]
#     cache_status, _ = CacheStatus.objects.get_or_create(pk=1, defaults={'last_full_refresh_at': datetime.now()})
    
#     # Create image
#     img = Image.new('RGB', (800, 600), color = 'white')
#     d = ImageDraw.Draw(img)
    
#     try:
#         # Use a default font or specify a path to a .ttf file
#         font = ImageFont.truetype("arial.ttf", 24)
#         small_font = ImageFont.truetype("arial.ttf", 18)
#     except IOError:
#         font = ImageFont.load_default()
#         small_font = ImageFont.load_default()

#     # Draw text
#     d.text((50, 50), f"Country Data Summary", fill=(0,0,0), font=font)
#     d.text((50, 100), f"Total Countries Cached: {total_countries}", fill=(0,0,0), font=small_font)
#     d.text((50, 130), f"Last Refreshed: {cache_status.last_full_refresh_at.strftime('%Y-%m-%d %H:%M:%S UTC')}", fill=(0,0,0), font=small_font)
    
#     d.text((50, 200), "Top 5 Countries by Estimated GDP:", fill=(0,0,0), font=font)
#     y_pos = 250
#     for i, country in enumerate(top_5_gdp):
#         gdp_in_billions = country['estimated_gdp'] / 1_000_000_000 if country['estimated_gdp'] else 0
#         text = f"{i+1}. {country['name']}: ${gdp_in_billions:.2f} Billion"
#         d.text((70, y_pos), text, fill=(0,0,0), font=small_font)
#         y_pos += 30

#     # Save image
#     os.makedirs(os.path.dirname(SUMMARY_IMAGE_PATH), exist_ok=True)
#     img.save(SUMMARY_IMAGE_PATH)

# @transaction.atomic
# def refresh_country_data():
#     """Fetches, processes, and caches country and exchange rate data."""
#     try:
#         country_response = requests.get(COUNTRIES_API_URL, timeout=15)
#         country_response.raise_for_status()
#         countries_data = country_response.json()
#     except requests.RequestException:
#         raise ExternalServiceError("RestCountries API")

#     try:
#         rate_response = requests.get(EXCHANGE_RATE_API_URL, timeout=15)
#         rate_response.raise_for_status()
#         exchange_rates = rate_response.json().get('rates', {})
#     except requests.RequestException:
#         raise ExternalServiceError("Open Exchange Rate API")

#     for country_data in countries_data:
#         currency_code = None
#         if 'currencies' in country_data and country_data['currencies']:
#             currency_code = country_data['currencies'][0].get('code')
        
#         exchange_rate = exchange_rates.get(currency_code) if currency_code else None
        
#         estimated_gdp = 0
#         population = country_data.get('population', 0)
#         if population and exchange_rate and exchange_rate > 0:
#             multiplier = random.uniform(1000, 2000)
#             estimated_gdp = (population * multiplier) / exchange_rate

#         # Use update_or_create to handle insert/update logic
#         Country.objects.update_or_create(
#             name__iexact=country_data['name'],
#             defaults={
#                 'name': country_data['name'],
#                 'capital': country_data.get('capital'),
#                 'region': country_data.get('region'),
#                 'population': population,
#                 'currency_code': currency_code,
#                 'exchange_rate': exchange_rate,
#                 'estimated_gdp': estimated_gdp,
#                 'flag_url': country_data.get('flag'),
#             }
#         )
    
#     # Update global refresh timestamp and generate image
#     CacheStatus.objects.update_or_create(pk=1, defaults={'last_full_refresh_at': datetime.now()})
#     _generate_summary_image()
    
#     return {"status": "success", "countries_processed": len(countries_data)}



