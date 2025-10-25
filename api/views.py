# api/views.py
from django.http import FileResponse
from django.shortcuts import get_object_or_404
from rest_framework import generics, status
from rest_framework.decorators import api_view
from rest_framework.response import Response
from rest_framework.filters import OrderingFilter

from .models import Country, CacheStatus
from .serializers import CountrySerializer
from .services import refresh_country_data, ExternalServiceError, SUMMARY_IMAGE_PATH
from .filters import CountryFilter

@api_view(['POST'])
def refresh_countries_view(request):
    """POST /countries/refresh: Fetches and caches all country data."""
    try:
        result = refresh_country_data()
        return Response(result, status=status.HTTP_200_OK)
    except ExternalServiceError as e:
        return Response(
            {"error": "External data source unavailable", "details": str(e)},
            status=status.HTTP_503_SERVICE_UNAVAILABLE
        )
    except Exception as e:
        return Response({"error": "An internal server error occurred"}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

class CountryListView(generics.ListAPIView):
    """GET /countries: Get all countries with filtering and sorting."""
    queryset = Country.objects.all()
    serializer_class = CountrySerializer
    filterset_class = CountryFilter
    
    # Note: The prompt asks for `gdp_desc`. This is handled by the client
    # sending the query param `?ordering=-estimated_gdp`.
    ordering_fields = ['estimated_gdp']

class CountryDetailView(generics.RetrieveDestroyAPIView):
    """GET /countries/:name and DELETE /countries/:name."""
    queryset = Country.objects.all()
    serializer_class = CountrySerializer
    lookup_field = 'name'

@api_view(['GET'])
def status_view(request):
    """GET /status: Show total countries and last refresh timestamp."""
    total_countries = Country.objects.count()
    cache_status, _ = CacheStatus.objects.get_or_create(pk=1, defaults={'last_full_refresh_at': None})
    return Response({
        "total_countries": total_countries,
        "last_refreshed_at": cache_status.last_full_refresh_at
    })

@api_view(['GET'])
def summary_image_view(request):
    """GET /countries/image: Serve the generated summary image."""
    try:
        return FileResponse(open(SUMMARY_IMAGE_PATH, 'rb'))
    except FileNotFoundError:
        return Response({"error": "Summary image not found"}, status=status.HTTP_404_NOT_FOUND)