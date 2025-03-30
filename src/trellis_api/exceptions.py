"""
Exceptions for the Trellis API client.
"""

class TrellisAPIError(Exception):
    """Base exception for Trellis API errors."""
    def __init__(self, message, status_code=None, response=None):
        super().__init__(message)
        self.status_code = status_code
        self.response = response


class TrellisRequestError(Exception):
    """Exception raised for errors in the HTTP request."""
    def __init__(self, message, original_error=None):
        super().__init__(message)
        self.original_error = original_error
