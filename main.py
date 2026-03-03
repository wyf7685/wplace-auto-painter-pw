import contextlib
import os
import subprocess
import sys
from pathlib import Path

import anyio

from app.log import logger


def launch_config_gui() -> None:
    if getattr(sys, "frozen", False):
        gui_executable = Path(sys.executable).parent / ("config-gui" + (".exe" if sys.platform == "win32" else ""))
        if not gui_executable.is_file():
            logger.error(f"找不到配置 GUI 可执行文件: {gui_executable}")
            return
        args = [str(gui_executable)]
    else:
        gui_entry = Path(__file__).parent / "gui_main.py"
        args = [sys.executable, str(gui_entry)]

    try:
        subprocess.check_call(args)  # noqa: S603
    except Exception:
        logger.exception("启动 config GUI 失败")


def ensure_config_gui() -> None:
    from app.config import CONFIG_FILE, Config

    if not CONFIG_FILE.is_file():
        return launch_config_gui()

    try:
        cfg = Config.load()
    except Exception:
        logger.exception("加载配置文件时出错")
        logger.info("无法加载配置，启动config生成窗口")
        return launch_config_gui()

    if len(cfg.users) == 0:
        logger.info("配置文件中没有用户，启动config生成窗口")
        return launch_config_gui()

    for user in cfg.users:
        tp = user.template
        if not tp.file_id or not tp.file.is_file() or tp.file.stat().st_size == 0:
            logger.info(f"用户 {user.identifier} 的模板文件不存在或错误，启动config生成窗口")
            return launch_config_gui()

    return None


async def async_main() -> None:
    from app.config import Config, export_config_schema

    export_config_schema()

    if "config" in sys.argv[1:]:
        launch_config_gui()
        return

    ensure_config_gui()

    if Config.load().check_update:
        from app.utils.update import check_update

        await check_update()

    from app.browser import shutdown_idle_playwright_loop, shutdown_playwright
    from app.exception import AppException
    from app.utils.update import check_update_loop
    from app.wplace import setup_paint

    async def setup_loops() -> None:
        try:
            async with anyio.create_task_group() as inner:
                inner.start_soon(setup_paint)
                # inner.start_soon(...)
        finally:
            outer.cancel_scope.cancel()

    try:
        async with anyio.create_task_group() as outer:
            outer.start_soon(setup_loops)
            outer.start_soon(shutdown_idle_playwright_loop)
            if Config.load().check_update:
                outer.start_soon(check_update_loop)
    except* KeyboardInterrupt:
        logger.info("Received keyboard interrupt, shutting down...")
    except* AppException:
        logger.exception("Uncaught application exception occurred")
    except* Exception:
        logger.exception("Unexpected error occurred")
    finally:
        await shutdown_playwright()


def _should_use_tray() -> bool:
    """Return True when tray mode should be used.

    Checks (in order):
    1. ``--tray`` command-line flag (highest priority, works before config exists)
    2. Environment variable ``WPLACE_TRAY_RESPAWNED=1`` (set by the respawn logic)
    3. ``config.tray_mode`` field (requires a valid config file)
    4. Platform guard: tray mode is Windows-only.
    """
    if sys.platform != "win32":
        return False
    if "--tray" in sys.argv[1:] or os.environ.get("WPLACE_TRAY_RESPAWNED"):
        return True

    from app.config import Config

    try:
        return Config.load().tray_mode
    except Exception:
        return False


def _respawn_as_pythonw() -> None:
    """Re-launch the current process under pythonw.exe and exit.

    ``pythonw.exe`` has PE subsystem WINDOWS rather than CONSOLE, so the
    shell releases the terminal immediately after spawning it, without
    waiting for the process to exit.  The guard env-var
    ``WPLACE_TRAY_RESPAWNED=1`` prevents an infinite re-spawn loop.

    Falls through silently when:
    - the guard env-var is already set (we *are* the respawned process), or
    - ``pythonw.exe`` is not found next to ``sys.executable`` (non-Windows).
    """
    if os.environ.get("WPLACE_TRAY_RESPAWNED"):
        return
    pythonw = Path(sys.executable).with_stem("pythonw")
    if not pythonw.is_file():
        return
    env = os.environ.copy()
    env["WPLACE_TRAY_RESPAWNED"] = "1"
    p = subprocess.Popen(  # noqa: S603
        [str(pythonw), *sys.argv],
        env=env,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    logger.info(f"Respawning with pythonw.exe (PID {p.pid}), exiting current process")
    sys.exit(0)


def main() -> None:
    with contextlib.suppress(KeyboardInterrupt):
        if _should_use_tray():
            _respawn_as_pythonw()
            # Lazy import: app.tray (and PyQt6) are never loaded in normal mode.
            from app.tray import run_tray

            run_tray(async_main)
        else:
            anyio.run(async_main)


if __name__ == "__main__":
    main()
