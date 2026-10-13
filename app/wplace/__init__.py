from collections.abc import Callable

from app.browser import create_playwright_context
from app.config import ensure_config_ready
from app.exception import AppException
from app.log import logger
from app.version import get_app_version


async def run_painter(on_user_failed: Callable[[str], None] | None = None) -> bool:
    logger.opt(colors=True).info(f"Starting painter loop (version=<c>{get_app_version()}</>)")

    ensure_config_ready()

    from .paint import setup_paint

    failed = False
    try:
        async with create_playwright_context():
            failed = not await setup_paint(on_user_failed)

    except* KeyboardInterrupt:
        logger.info("Received keyboard interrupt, shutting down...")
    except* AppException:
        failed = True
        logger.exception("Uncaught application exception occurred")
    except* Exception:
        failed = True
        logger.exception("Unexpected error occurred")
    finally:
        logger.info("Painter stopped")

    return not failed


__all__ = ["run_painter"]
