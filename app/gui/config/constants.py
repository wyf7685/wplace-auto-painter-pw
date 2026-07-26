from typing import get_args

from app.config import Config

# Derived from the config model so the dropdowns can never drift from validation.
BROWSER_TYPES = list(get_args(Config.model_fields["browser"].annotation))
LOG_LEVELS = list(get_args(Config.model_fields["log_level"].annotation))
LANGUAGE_CODES = list(get_args(Config.model_fields["language"].annotation))
