import threading
from collections.abc import Callable
from typing import TYPE_CHECKING

from PySide6.QtCore import QObject, Signal

from app.const import INSTALL_DIR, IS_FROZEN
from app.log import logger
from app.update import PreparedUpdate, UpdateInfo
from app.version import get_version_display

if TYPE_CHECKING:
    from app.update.service import UpdateService


class GuiUpdateController(QObject):
    state_changed = Signal(str, str, str)
    progress_changed = Signal(int, int)
    error_occurred = Signal(str)
    restart_requested = Signal()

    def __init__(self) -> None:
        super().__init__()
        self._state = "idle" if IS_FROZEN else "unsupported"
        self._info: UpdateInfo | None = None
        self._prepared: PreparedUpdate | None = None
        self._service: UpdateService | None = None
        self._thread: threading.Thread | None = None
        self._lock = threading.Lock()

    @staticmethod
    def cleanup_old_helpers() -> None:
        from app.update.service import UpdateService

        UpdateService.cleanup_old_helpers()

    @property
    def state(self) -> str:
        return self._state

    @property
    def version(self) -> str:
        return self._info.manifest.version if self._info else ""

    @property
    def release_notes(self) -> str:
        return self._info.release_notes if self._info else ""

    def emit_current_state(self) -> None:
        self.state_changed.emit(self._state, self.version, self.release_notes)

    def check(self, *, notify_errors: bool) -> None:
        if not IS_FROZEN:
            self._set_state("unsupported")
            return
        self._start_operation("update-check", "checking", lambda: self._check_worker(notify_errors))

    def download(self) -> None:
        info = self._info
        if info is None:
            self.check(notify_errors=True)
            return
        self._start_operation("update-download", "downloading", lambda: self._download_worker(info))

    def install(self) -> None:
        prepared = self._prepared
        service = self._service
        if prepared is None or service is None:
            logger.error(
                "Cannot install GUI update: prepared update or service is unavailable; state={}, "
                "target_version={!r}, has_prepared_update={}, has_service={}, install_dir={!s}",
                self._state,
                self.version,
                prepared is not None,
                service is not None,
                INSTALL_DIR,
            )
            self._set_state("error")
            self.error_occurred.emit("Prepared update is unavailable")
            return

        self._set_state("applying")
        try:
            service.launch_helper(prepared)
        except Exception as exc:
            logger.opt(exception=exc).error(
                "Failed to launch update helper; state={}, current_version={}, target_version={}, "
                "install_dir={!s}, archive_path={!s}, payload_dir={!s}, executable={!r}",
                self._state,
                get_version_display(),
                prepared.info.manifest.version,
                INSTALL_DIR,
                prepared.archive_path,
                prepared.payload_dir,
                prepared.package_manifest.executable,
            )
            self._set_state("error")
            self.error_occurred.emit(str(exc))
            return
        self.restart_requested.emit()

    def _start_operation(self, name: str, state: str, target: Callable[[], None]) -> bool:
        with self._lock:
            if self._thread is not None and self._thread.is_alive():
                return False
            self._thread = threading.Thread(target=target, name=name, daemon=True)
            self._set_state(state)
            self._thread.start()
        return True

    def _check_worker(self, notify_errors: bool) -> None:
        try:
            from app.update.service import UpdateService

            service = UpdateService()
            info = service.check()
        except Exception as exc:
            logger.opt(exception=exc).error(
                "GUI update check failed; state={}, current_version={}, install_dir={!s}, notify_errors={}, thread={}",
                self._state,
                get_version_display(),
                INSTALL_DIR,
                notify_errors,
                threading.current_thread().name,
            )
            self._set_state("error")
            if notify_errors:
                self.error_occurred.emit(str(exc))
            return

        self._service = service
        self._info = info
        self._prepared = None
        self._set_state("available" if info else "current")

    def _download_worker(self, info: UpdateInfo) -> None:
        try:
            from app.update.service import UpdateService

            service = self._service or UpdateService()
            prepared = service.prepare(info, self.progress_changed.emit)
        except Exception as exc:
            logger.opt(exception=exc).error(
                "GUI update download failed; state={}, target_version={}, release_tag={}, asset_name={!r}, "
                "expected_size={}, expected_sha256={}, install_dir={!s}, thread={}",
                self._state,
                info.manifest.version,
                info.manifest.tag,
                info.asset.name,
                info.asset.size,
                info.asset.sha256,
                INSTALL_DIR,
                threading.current_thread().name,
            )
            self._set_state("error")
            self.error_occurred.emit(str(exc))
            return

        self._service = service
        self._prepared = prepared
        self._set_state("ready")

    def _set_state(self, state: str) -> None:
        self._state = state
        self.state_changed.emit(state, self.version, self.release_notes)
