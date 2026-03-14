import anyio


def ensure_config_ready() -> None:
    from app.config import Config
    from app.const import CONFIG_FILE
    from app.exception import AppException

    if not CONFIG_FILE.is_file():
        raise AppException(f"Config file not found: {CONFIG_FILE}")

    try:
        cfg = Config.load()
    except Exception as exc:
        raise AppException("Failed to load config file") from exc

    if len(cfg.users) == 0:
        raise AppException("No users configured")

    for user in cfg.users:
        tp = user.template
        if not tp.file_id or not tp.file.is_file() or tp.file.stat().st_size == 0:
            raise AppException(f"Template image is missing or invalid for user: {user.identifier}")


async def run_painter() -> None:
    from app.config import Config, export_config_schema

    export_config_schema()
    ensure_config_ready()

    if Config.load().check_update:
        from app.utils.update import check_update

        await check_update()

    from app.browser import shutdown_idle_playwright_loop, shutdown_playwright
    from app.exception import AppException
    from app.log import logger
    from app.utils.update import check_update_loop
    from app.wplace import setup_events, setup_paint

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
        await shutdown_playwright()
