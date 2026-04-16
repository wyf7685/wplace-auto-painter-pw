class AppException(Exception):
    """Base class for application-specific exceptions."""


class ConfigError(AppException):
    """Exception raised for errors in the configuration."""


class ConfigNotFound(FileNotFoundError, ConfigError):
    """Exception raised when the configuration file is not found."""


class ConfigParseFailed(AppException):
    """Exception raised when parsing the configuration fails."""


class UserConfigError(AppException):
    """Exception raised for errors in user configuration."""


class NoUsersConfigured(UserConfigError):
    """Exception raised when no users are configured."""


class UserTemplateInvalid(UserConfigError):
    """Exception raised when a user's template configuration is invalid."""


class FetchFailed(AppException):
    """Exception raised when fetching data fails."""


class ShouldQuit(AppException):
    """Exception to signal that a loop should stop."""


class BrowserNotAvailable(ShouldQuit):
    """Exception raised when the configured Playwright browser is not available."""


class ResolveFailed(ShouldQuit):
    """Exception raised when resolving JS functions fails."""


class TokenExpired(ShouldQuit):
    """Exception raised when an authentication token has expired."""


class ElementNotFound(ShouldQuit):
    """Exception raised when a required page element is not found."""


class PaintFinished(ShouldQuit):
    """Exception raised when painting is finished."""


class CaptchaDetected(ShouldQuit):
    """Exception raised when a captcha is detected, indicating manual intervention may be required."""
