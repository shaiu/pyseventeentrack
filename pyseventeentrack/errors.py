"""Define module exceptions."""


class SeventeenTrackError(Exception):
    """Define a base error."""


class InvalidTrackingNumberError(SeventeenTrackError):
    """Define an error for an invalid tracking number."""


class InvalidPackageDataError(SeventeenTrackError):
    """Define an error for incomplete package data returned by 17Track."""


class PackageNotFoundError(SeventeenTrackError):
    """Define an error for a package lookup miss."""


class NotLoggedInError(SeventeenTrackError):
    """Define an error for unauthenticated API responses."""


class RequestError(SeventeenTrackError):
    """Define an error for HTTP request errors."""
