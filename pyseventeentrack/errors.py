"""Define module exceptions."""


class SeventeenTrackError(Exception):
    """Define a base error."""


class InvalidTrackingNumberError(SeventeenTrackError):
    """Define an error for an invalid tracking number."""


class RequestError(SeventeenTrackError):
    """Define an error for HTTP request errors."""
