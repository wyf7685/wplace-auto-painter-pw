class AppException(Exception):
    """Base class for application-specific exceptions."""


class FetchFailed(AppException):
    """Exception raised when fetching data fails."""


class ShouldQuit(AppException):
    """Exception to signal that a loop should stop."""


class ResolveFailed(ShouldQuit):
    """Exception raised when resolving JS functions fails."""


class TokenExpired(ShouldQuit):
    """Exception raised when an authentication token has expired."""


class ElementNotFound(ShouldQuit):
    """Exception raised when a required page element is not found."""


class PaintFinished(ShouldQuit):
    """Exception raised when painting is finished."""
