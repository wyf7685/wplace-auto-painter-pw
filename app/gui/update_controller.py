import threading
from collections.abc import Callable

from PySide6.QtCore import QObject, Signal

from app.const import IS_FROZEN
from app.log import logger
from app.update import PreparedUpdate, UpdateInfo, UpdateService


class GuiUpdateController(QObject):
    state_changed = Signal(str, str)
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
        UpdateService.cleanup_old_helpers()

    @property
    def state(self) -> str:
        return self._state

    @property
    def version(self) -> str:
        return self._info.manifest.version if self._info else ""

    def emit_current_state(self) -> None:
        self.state_changed.emit(self._state, self.version)

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
            self._set_state("error")
            self.error_occurred.emit("Prepared update is unavailable")
            return

        self._set_state("applying")
        try:
            service.launch_helper(prepared)
        except Exception as exc:
            logger.opt(exception=exc).error("Failed to launch update helper")
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
            service = UpdateService()
            info = service.check()
        except Exception as exc:
            logger.opt(exception=exc).warning("Update check failed")
            self._set_state("error")
            if notify_errors:
                self.error_occurred.emit(str(exc))
            return

        self._service = service
        self._info = info
        self._prepared = None
        self._set_state("available" if info else "current")

    def _download_worker(self, info: UpdateInfo) -> None:
        service = self._service or UpdateService()
        try:
            prepared = service.prepare(info, self.progress_changed.emit)
        except Exception as exc:
            logger.opt(exception=exc).error("Update download failed")
            self._set_state("error")
            self.error_occurred.emit(str(exc))
            return

        self._service = service
        self._prepared = prepared
        self._set_state("ready")

    def _set_state(self, state: str) -> None:
        self._state = state
        self.state_changed.emit(state, self.version)
