# api/views.py
import logging
from django.http import FileResponse, Http404
from rest_framework import generics, status
from rest_framework.decorators import api_view
from rest_framework.response import Response
# --- IMPORTS FOR FIX ---
from django_filters.rest_framework import DjangoFilterBackend
from rest_framework.filters import OrderingFilter
# --- END IMPORTS FOR FIX ---


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

# ==============================================================================
# MODIFIED SECTION: CustomOrderingFilter and CountryListView
# ==============================================================================

class CustomOrderingFilter(OrderingFilter):
    """
    A custom ordering filter that uses 'sort' as the query parameter instead
    of the default 'ordering', to match the project specifications.
    It also allows mapping 'gdp_desc' to '-estimated_gdp'.
    """
    ordering_param = "sort" # Use `?sort=` for ordering.

    def get_ordering(self, request, queryset, view):
        # Allow for mapping 'gdp_desc' to '-estimated_gdp'
        params = request.query_params.get(self.ordering_param)
        if params:
            fields = [param.strip() for param in params.split(',')]
            # Custom mapping for gdp_desc
            if 'gdp_desc' in fields:
                fields[fields.index('gdp_desc')] = '-estimated_gdp'
            
            # This is the default behavior from the parent class
            ordering = self.remove_invalid_fields(queryset, fields, view, request)
            if ordering:
                return ordering

        # No ordering was specified or was invalid
        return self.get_default_ordering(view)


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
    
    # Use the custom filter class
    filter_backends = [DjangoFilterBackend, CustomOrderingFilter]

    # Defines which fields can be used for sorting with the `?ordering=` query parameter.
    # e.g., `?ordering=-estimated_gdp` for descending GDP.
    ordering_fields = ['estimated_gdp', 'name', 'population']

# ==============================================================================
# END MODIFIED SECTION
# ==============================================================================


# ==============================================================================
# MODIFIED SECTION: CountryDetailView
# ==============================================================================
class CountryDetailView(generics.RetrieveDestroyAPIView):
    """
    Handles GET /countries/:name and DELETE /countries/:name.
    Retrieves or deletes a single country instance.
    """
    queryset = Country.objects.all()
    serializer_class = CountrySerializer
    
    # Tell DRF to look up countries by their 'name' field in the URL.
    # Using 'name__iexact' would be better for case-insensitive lookups. See loopholes below.
    lookup_field = 'name'

    def get_object(self):
        """
        Override get_object to handle 404s gracefully with a custom message.
        """
        try:
            # Use filter and first() for case-insensitive lookup
            name = self.kwargs[self.lookup_field]
            obj = Country.objects.get(name__iexact=name)
            self.check_object_permissions(self.request, obj)
            return obj
        except Country.DoesNotExist:
            logger.warning(f"Country with name '{self.kwargs.get(self.lookup_field)}' not found.")
            # This will be caught by DRF's exception handler and turned into a 404
            raise Http404

    def retrieve(self, request, *args, **kwargs):
        """
        Override retrieve to add logging for GET requests.
        """
        instance = self.get_object()
        logger.info(f"Successfully retrieved country: {instance.name}")
        serializer = self.get_serializer(instance)
        return Response(serializer.data, status=status.HTTP_200_OK)

    def destroy(self, request, *args, **kwargs):
        """
        Override destroy to add logging and ensure 204 No Content is returned.
        The default behavior is already 204, but overriding makes it explicit.
        """
        instance = self.get_object()
        country_name = instance.name  # Get name before deletion
        self.perform_destroy(instance)
        logger.info(f"Successfully deleted country: {country_name}")
        # Return a 204 No Content response, which has an empty body.
        return Response(status=status.HTTP_204_NO_CONTENT)

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