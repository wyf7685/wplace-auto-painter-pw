from app.config import Config
from app.const import IS_FROZEN
from app.log import logger

from .service import UpdateService


def _automatic_update_enabled() -> bool:
    try:
        return Config.load().check_update
    except Exception:
        return False


def try_install_headless_update() -> bool:
    """Install an available release before starting the headless painter.

    Returns whether the update helper was launched and the current process must exit.
    Update failures are non-fatal so a transient GitHub or download failure does not
    prevent the existing version from painting.
    """
    if not IS_FROZEN or not _automatic_update_enabled():
        return False

    try:
        UpdateService.cleanup_old_helpers()
        logger.info("Checking for updates before starting the headless painter")
        service = UpdateService()
        info = service.check()
        if info is None:
            logger.info("The headless painter is already up to date")
            return False

        logger.info(f"Preparing headless update to v{info.manifest.version}")
        last_reported_bucket = -1

        def report_progress(downloaded: int, total: int) -> None:
            nonlocal last_reported_bucket
            bucket = min(downloaded * 10 // total, 10)
            if bucket <= last_reported_bucket:
                return
            last_reported_bucket = bucket
            logger.info(f"Downloading headless update: {bucket * 10}%")

        prepared = service.prepare(info, report_progress)
        service.launch_helper(prepared, headless=True)
    except Exception as exc:
        logger.opt(exception=exc).warning("Headless update failed; continuing with the current version")
        return False

    logger.info("Headless update is ready; stopping for updater restart")
    return True
