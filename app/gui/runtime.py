import threading
from collections.abc import Awaitable, Callable

import anyio
import anyio.to_thread
from PyQt6.QtCore import QObject, pyqtSignal

from app.exception import ConfigError
from app.log import logger


class RuntimeSignals(QObject):
    """Signals emitted by TaskRuntime."""

    state_changed = pyqtSignal(str)
    config_error_occurred = pyqtSignal(ConfigError)


class TaskRuntime:
    """Run task in a background thread and control it with a stop event."""

    def __init__(self, task: Callable[[], Awaitable[object]], signals: RuntimeSignals) -> None:
        self._task = task
        self._signals = signals
        self._thread: threading.Thread | None = None
        self._stop_event = threading.Event()
        self._lock = threading.Lock()

    @property
    def is_running(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

    def start(self) -> bool:
        with self._lock:
            if self.is_running:
                return False
            self._stop_event.clear()
            self._thread = threading.Thread(target=self._thread_main, name="anyio-main", daemon=True)
            self._thread.start()
        self._signals.state_changed.emit("running")
        return True

    def stop(self) -> None:
        self._stop_event.set()

    def join(self, timeout: float | None = None) -> None:
        thread = self._thread
        if thread is not None:
            thread.join(timeout=timeout)

    def _thread_main(self) -> None:
        async def _runner() -> None:
            async def _stop_waiter(scope: anyio.CancelScope) -> None:
                await anyio.to_thread.run_sync(self._stop_event.wait, abandon_on_cancel=True)
                scope.cancel()

            async with anyio.create_task_group() as tg:
                tg.start_soon(_stop_waiter, tg.cancel_scope)
                try:
                    await self._task()
                finally:
                    tg.cancel_scope.cancel()

        state = "stopped"
        try:
            anyio.run(_runner)
        except ConfigError as e:
            logger.exception("Configuration error occurred in runtime")
            self._signals.config_error_occurred.emit(e)
            state = "error"
        except BaseException:
            logger.exception("Background runtime crashed")
            state = "error"
        finally:
            self._stop_event.set()
            self._signals.state_changed.emit(state)
            with self._lock:
                self._thread = None
