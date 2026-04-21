import anyio

from app.browser import shutdown_idle_playwright_loop, shutdown_playwright
from app.config import Config, ensure_config_ready
from app.exception import AppException
from app.log import logger
from app.utils.update import check_update_loop


async def run_painter() -> None:
    ensure_config_ready()

    if Config.load().check_update:
        from app.utils.update import check_update

        await check_update()

    from .events import setup_events
    from .paint import setup_paint

    try:
        async with anyio.create_task_group() as tg:
            tg.start_soon(setup_events)
            tg.start_soon(shutdown_idle_playwright_loop)
            if Config.load().check_update:
                tg.start_soon(check_update_loop)

            try:
                await setup_paint()
            finally:
                tg.cancel_scope.cancel()

    except* KeyboardInterrupt:
        logger.info("Received keyboard interrupt, shutting down...")
    except* AppException:
        logger.exception("Uncaught application exception occurred")
    except* Exception:
        logger.exception("Unexpected error occurred")
    finally:
        with anyio.CancelScope(shield=True):
            await shutdown_playwright()
        logger.info("Painter stopped")


__all__ = ["run_painter"]
