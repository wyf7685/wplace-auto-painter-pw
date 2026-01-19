import contextlib
import subprocess
import sys
from pathlib import Path

import anyio

from app.config import CONFIG_FILE, Config, export_config_schema
from app.log import logger
from app.utils.update import check_update


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


async def main() -> None:
    export_config_schema()

    if "config" in sys.argv[1:]:
        launch_config_gui()
        return

    ensure_config_gui()

    if Config.load().check_update:
        await check_update()

    from app.browser import shutdown_idle_playwright_loop, shutdown_playwright
    from app.paint import setup_paint
    from app.utils.update import check_update_loop

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
    except* Exception:
        logger.exception("Unexpected error occurred")
    finally:
        await shutdown_playwright()


if __name__ == "__main__":
    with contextlib.suppress(KeyboardInterrupt):
        anyio.run(main)
