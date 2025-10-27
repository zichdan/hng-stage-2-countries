# country_api/exceptions.py
from rest_framework.views import exception_handler
from rest_framework.response import Response

def custom_exception_handler(exc, context):
    """
    Custom exception handler for Django REST Framework.
    This handler ensures that error responses match the format required by the project,
    e.g., {"error": "Country not found"}.
    """
    # Call REST framework's default exception handler first,
    # to get the standard error response.
    response = exception_handler(exc, context)

    # Now, override the response data with our custom format.
    if response is not None:
        # Check for specific status codes and format the response body.
        if response.status_code == 404:
            # Custom message for 404 Not Found errors.
            response.data = {'error': 'Country not found'}
        elif response.status_code == 400:
            # Custom message for 400 Bad Request errors (validation failed).
            # The details will be in the default response if available.
            custom_data = {'error': 'Validation failed'}
            if 'details' in response.data:
                custom_data['details'] = response.data['details']
            response.data = custom_data
        elif response.status_code >= 500:
            # Generic message for 5xx server errors.
            response.data = {'error': 'Internal server error'}
        # You can add more conditions here for other status codes if needed

    return response