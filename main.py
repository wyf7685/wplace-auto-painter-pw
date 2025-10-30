import contextlib
import subprocess
import sys
from pathlib import Path

import anyio

from app.config import CONFIG_FILE, Config, export_config_schema
from app.log import escape_tag, logger


def launch_config_gui() -> None:
    if getattr(sys, "frozen", False):
        gui_executable = Path(sys.executable).parent / ("config-gui" + (".exe" if sys.platform == "win32" else ""))
        if not gui_executable.is_file():
            logger.error(f"找不到配置 GUI 可执行文件: {gui_executable}")
            return
        args = [str(gui_executable)]
    else:
        args = [sys.executable, "-m", "gui"]

    try:
        subprocess.check_call(args)  # noqa: S603
    except Exception:
        logger.exception("启动 config GUI 失败")


def ensure_config_gui() -> None:
    """检查 data/config.json 与 data/templates 中的模板图片；
    若缺失或内容不合法，则启动 GUI 启动器并等待用户完成配置。
    """

    # 检查 config.json 是否存在且可解析
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

    from app.browser import shutdown_playwright
    from app.paint import paint_loop

    try:
        async with anyio.create_task_group() as tg:
            for user in Config.load().users:
                logger.opt(colors=True).info(f"Starting paint loop for user: <m>{escape_tag(user.identifier)}</>")
                tg.start_soon(paint_loop, user)
    except* KeyboardInterrupt:
        logger.info("Received keyboard interrupt, shutting down...")
    except* Exception:
        logger.exception("Unexpected error occurred")
    finally:
        logger.info("Shutting down Playwright...")
        await shutdown_playwright()


if __name__ == "__main__":
    with contextlib.suppress(KeyboardInterrupt):
        anyio.run(main)
