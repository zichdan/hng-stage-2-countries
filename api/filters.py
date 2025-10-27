# api/filters.py
from django_filters import rest_framework as filters
from .models import Country

# ==============================================================================
# MODIFIED SECTION: CountryFilter
# ==============================================================================
class CountryFilter(filters.FilterSet):
    """
    Defines the filters available for the Country list endpoint.
    This allows filtering by region and currency code.
    """
    # FIX: Explicitly define a 'region' filter that performs a case-insensitive match.
    # This will handle query parameters like `?region=Africa`.
    region = filters.CharFilter(field_name='region', lookup_expr='iexact')
    
    # FIX: Explicitly define a 'currency' filter.
    # The URL parameter is `?currency=NGN`, but it should filter on the `currency_code`
    # field in the database, also with a case-insensitive match.
    currency = filters.CharFilter(field_name='currency_code', lookup_expr='iexact')

    class Meta:
        model = Country
        # Define the fields that can be used for filtering.
        fields = ['region', 'currency']
# ==============================================================================
# END MODIFIED SECTION
# ==============================================================================