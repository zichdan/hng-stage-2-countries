# api/filters.py
from django_filters import rest_framework as filters
from .models import Country

class CountryFilter(filters.FilterSet):
    class Meta:
        model = Country
        fields = {
            'region': ['iexact'],
            'currency_code': ['iexact'],
        }




        