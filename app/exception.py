class AppException(Exception):
    """Base class for application-specific exceptions."""


class ShoudQuit(AppException):
    """Exception to signal that a loop should stop."""


class FetchFailed(AppException):
    """Exception raised when fetching data fails."""
