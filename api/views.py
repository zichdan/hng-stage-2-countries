# api/views.py
import logging
from django.http import FileResponse
from rest_framework import generics, status
from rest_framework.decorators import api_view
from rest_framework.response import Response

# Import the models, serializers, services, and filters
from .models import Country, CacheStatus
from .serializers import CountrySerializer
from .services import refresh_country_data, ExternalServiceError, SUMMARY_IMAGE_PATH
from .filters import CountryFilter

# Get a logger instance specific to this app
logger = logging.getLogger('api')

# --- Main Refresh Endpoint ---

@api_view(['POST'])
def refresh_countries_view(request):
    """
    Handles the POST /countries/refresh request.
    This view orchestrates the call to the main service function and handles
    all possible exceptions gracefully, returning appropriate HTTP status codes.
    """
    logger.info(f"Received request to {request.path} from {request.META.get('REMOTE_ADDR')}")
    try:
        # Call the main business logic function from the service layer
        result = refresh_country_data()
        # On success, return a 200 OK with the result
        return Response(result, status=status.HTTP_200_OK)
    
    except ExternalServiceError as e:
        # If the external APIs fail, return a 503 Service Unavailable
        logger.error(f"External service error during refresh: {e.service_name}", exc_info=True)
        return Response(
            {"error": "External data source unavailable", "details": str(e)},
            status=status.HTTP_503_SERVICE_UNAVAILABLE
        )
    except Exception as e:
        # For any other unexpected errors, return a generic 500 Internal Server Error
        logger.critical(f"An unexpected internal server error occurred during refresh: {e}", exc_info=True)
        return Response(
            {"error": "An internal server error occurred", "details": str(e)},
            status=status.HTTP_500_INTERNAL_SERVER_ERROR
        )

# --- Country List and Detail Views ---

class CountryListView(generics.ListAPIView):
    """
    Handles GET /countries.
    Provides a list of all countries with support for filtering and sorting.
    """
    # ** Performance Optimization **
    # Instead of `queryset = Country.objects.all()`, which can be slow, we explicitly
    # select only the fields needed for the list view. This can significantly
    # reduce database load and improve response time. `select_related` is not needed
    # here as there are no foreign key relationships to follow.
    queryset = Country.objects.all().only(
        'id', 'name', 'capital', 'region', 'population', 'currency_code', 
        'exchange_rate', 'estimated_gdp', 'flag_url', 'last_refreshed_at'
    )
    
    # The serializer to use for converting model instances to JSON
    serializer_class = CountrySerializer
    
    # The filter class that defines which query parameters can be used for filtering
    filterset_class = CountryFilter
    
    # Defines which fields can be used for sorting with the `?ordering=` query parameter.
    # e.g., `?ordering=-estimated_gdp` for descending GDP.
    ordering_fields = ['estimated_gdp', 'name', 'population']

class CountryDetailView(generics.RetrieveDestroyAPIView):
    """
    Handles GET /countries/:name and DELETE /countries/:name.
    Retrieves or deletes a single country instance.
    """
    queryset = Country.objects.all()
    serializer_class = CountrySerializer
    
    # Tell DRF to look up countries by their 'name' field in the URL, not the default 'id'.
    lookup_field = 'name'

# --- Status and Image Endpoints ---

@api_view(['GET'])
def status_view(request):
    """
    Handles GET /status.
    Returns the total number of cached countries and the last refresh timestamp.
    """
    logger.debug(f"Status endpoint requested by {request.META.get('REMOTE_ADDR')}")
    try:
        total_countries = Country.objects.count()
        # Use get_or_create to handle the case where the table is empty, preventing a crash.
        cache_status, _ = CacheStatus.objects.get_or_create(pk=1)
        
        return Response({
            "total_countries": total_countries,
            "last_refreshed_at": cache_status.last_full_refresh_at
        })
    except Exception as e:
        logger.error(f"Error in status view: {e}", exc_info=True)
        return Response({"error": "Could not retrieve status."}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

@api_view(['GET'])
def summary_image_view(request):
    """
    Handles GET /countries/image.
    Serves the generated summary image file.
    """
    logger.debug(f"Image endpoint requested by {request.META.get('REMOTE_ADDR')}")
    try:
        # Use FileResponse to efficiently stream the image file from disk.
        return FileResponse(open(SUMMARY_IMAGE_PATH, 'rb'))
    except FileNotFoundError:
        # If the file doesn't exist (e.g., before the first refresh), return a 404.
        logger.warning(f"Summary image not found at {SUMMARY_IMAGE_PATH}")
        return Response({"error": "Summary image not found. Run the /countries/refresh endpoint first."}, status=status.HTTP_404_NOT_FOUND)