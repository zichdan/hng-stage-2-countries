# api/models.py
from django.db import models

class Country(models.Model):
    name = models.CharField(max_length=100, unique=True)
    capital = models.CharField(max_length=100, null=True, blank=True)
    region = models.CharField(max_length=100, null=True, blank=True)
    population = models.BigIntegerField()
    currency_code = models.CharField(max_length=10, null=True, blank=True)
    exchange_rate = models.DecimalField(max_digits=15, decimal_places=4, null=True, blank=True)
    estimated_gdp = models.DecimalField(max_digits=20, decimal_places=2, null=True, blank=True)
    flag_url = models.URLField(max_length=200, null=True, blank=True)
    last_refreshed_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name_plural = "Countries"

    def __str__(self):
        return self.name

class CacheStatus(models.Model):
    # Allow this field to be null before the first refresh has happened.
    last_full_refresh_at = models.DateTimeField(null=True, blank=True)

    def __str__(self):
        # Add a check for None to avoid errors
        if self.last_full_refresh_at:
            return f"Last refreshed at {self.last_full_refresh_at}"
        return "Never refreshed"