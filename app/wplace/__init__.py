import anyio

from app.browser import shutdown_idle_playwright_loop, shutdown_playwright
from app.config import ensure_config_ready
from app.exception import AppException
from app.log import logger
from app.version import get_app_version


async def run_painter() -> bool:
    logger.opt(colors=True).info(f"Starting painter loop (version=<c>{get_app_version()}</>)")

    ensure_config_ready()

    from .paint import setup_paint

    failed = False
    try:
        async with anyio.create_task_group() as tg:
            tg.start_soon(shutdown_idle_playwright_loop)

            try:
                await setup_paint()
            finally:
                tg.cancel_scope.cancel()

    except* KeyboardInterrupt:
        logger.info("Received keyboard interrupt, shutting down...")
    except* AppException:
        failed = True
        logger.exception("Uncaught application exception occurred")
    except* Exception:
        failed = True
        logger.exception("Unexpected error occurred")
    finally:
        with anyio.CancelScope(shield=True):
            await shutdown_playwright()
        logger.info("Painter stopped")

    return not failed


__all__ = ["run_painter"]
