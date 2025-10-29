import contextlib
import json
import sys
from pathlib import Path

import anyio

from app.browser import shutdown_playwright
from app.config import Config, UserConfig
from app.log import logger
from app.page import WplacePage, ZoomLevel
from app.paint import paint_loop
from app.template import get_color_location, group_adjacent
from app.utils import normalize_color_name


async def ensure_config_gui(project_root: str | None = None) -> None:
    """检查 data/config.json 与 data/templates 中的模板图片；
    若缺失或内容不合法，则启动 GUI 启动器并等待用户完成配置。
    """
    if project_root is None:
        project_root = Path(__file__).resolve().parent
    data_dir = project_root / "data"
    config_path = data_dir / "config.json"
    templates_dir = data_dir / "templates"

    need_gui = False
    # 检查 config.json 是否存在且可解析
    if not config_path.is_file():
        logger.info(f"检测到{config_path}不存在或错误，启动config生成窗口")
        need_gui = True
    else:
        try:
            with Path.open(config_path, "r", encoding="utf-8") as f:
                cfg = json.load(f)
            users = cfg.get("users")
            if not isinstance(users, list) or len(users) == 0:
                logger.info(f"检测到{config_path}内容不包含 users，启动config生成窗口")
                need_gui = True
            else:
                for user in users:
                    file_id = user.get("template", {}).get("file_id")
                    if not file_id:
                        msg = f"检测到用户 {user.get('identifier','?')} 的 template.file_id 缺失，启动config生成窗口"
                        logger.info(msg)
                        need_gui = True
                        break
                    img_path = templates_dir / f"{file_id}.png"
                    if not img_path.is_file() or img_path.stat().st_size == 0:
                        logger.info(f"检测到{img_path}不存在或错误，启动config生成窗口")
                        need_gui = True
                        break
        except Exception:
            logger.info(f"检测到{config_path}不存在或错误，启动config生成窗口")
            need_gui = True

    if need_gui:
        cfg_script = project_root / "config_init_gui.py"
        try:
            await anyio.run_process([sys.executable, cfg_script], check=True)
        except Exception as e:
            logger.exception(f"启动 config GUI 失败: {e}")


async def test_zoom(user: UserConfig, page: WplacePage) -> None:
    color_name = normalize_color_name("black")
    assert color_name is not None, "Color not found"
    coords = await get_color_location(user.template, color_name)
    if not coords:
        logger.info(f"No pixels found for color '{color_name}' in the template area.")
        return

    # find the largest group
    coords = group_adjacent(coords)[0]

    coord = user.template.coords.offset(*coords[0])
    page = WplacePage(user.credentials, color_name, coord, ZoomLevel.Z_15)
    async with page.begin() as page:
        await anyio.sleep(0.5)
        await page.find_and_click_paint_btn()
        await page.click_current_pixel()
        for idx in range(20):
            await page._move_by_pixel(1, 1)  # noqa: SLF001
            await page.click_current_pixel()
            logger.info(f"Clicked pixel #{idx + 1} at {page.current_coord.human_repr()}")

    input()


async def main() -> None:
    # 确保配置与模板存在，否则弹出 GUI 让用户初始化
    await ensure_config_gui()

    try:
        await paint_loop(Config.load().users[0], ZoomLevel.Z_16)
    except KeyboardInterrupt:
        logger.info("Shutting down...")
    await shutdown_playwright()


if __name__ == "__main__":
    with contextlib.suppress(KeyboardInterrupt):
        anyio.run(main)
