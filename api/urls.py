# api/urls.py
from django.urls import path
from .views import (
    refresh_countries_view,
    CountryListView,
    CountryDetailView,
    status_view,
    summary_image_view,
)

urlpatterns = [
    path('countries/refresh', refresh_countries_view, name='country-refresh'),
    path('countries', CountryListView.as_view(), name='country-list'),
    path('countries/<str:name>', CountryDetailView.as_view(), name='country-detail'),
    path('status', status_view, name='status'),
    path('countries/image', summary_image_view, name='country-summary-image'),
]