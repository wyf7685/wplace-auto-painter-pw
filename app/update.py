import subprocess
import sys
from datetime import datetime

import anyio
import httpx

from .assets import ASSETS_DIR
from .log import logger

IS_FROZEN = getattr(sys, "frozen", False)
OWNER = "wyf7685"
REPO = "wplace-auto-painter-pw"
BRANCH = "master"


def get_local_commit_hash() -> str | None:
    if IS_FROZEN:
        commit_hash_file = ASSETS_DIR / ".git_commit_hash"
        return commit_hash_file.read_text("utf-8").strip() if commit_hash_file.is_file() else None

    p = subprocess.run(
        ["git", "status", "--porcelain"],  # noqa: S607
        capture_output=True,
        text=True,
    )
    if p.returncode != 0 or p.stdout.strip():
        return None

    p = subprocess.run(
        ["git", "rev-parse", "HEAD"],  # noqa: S607
        capture_output=True,
        text=True,
    )
    return p.stdout.strip() if p.returncode == 0 else None


async def get_latest_commit_hash() -> str:
    url = f"https://api.github.com/repos/{OWNER}/{REPO}/commits/{BRANCH}"
    headers = {"Accept": "application/vnd.github.v3+json"}
    async with httpx.AsyncClient() as client:
        resp = await client.get(url, headers=headers, timeout=10.0)
        data = resp.raise_for_status().json()
        return data["sha"]


async def check_update() -> None:
    local_hash = get_local_commit_hash()
    if local_hash is None:
        logger.warning("无法获取本地版本信息，跳过更新检查")
        return

    try:
        latest_hash = await get_latest_commit_hash()
    except Exception:
        logger.warning("检查更新时出错，跳过更新检查")
        return

    if local_hash == latest_hash:
        logger.success("当前已是最新版本")
        return

    logger.warning("=" * 60)
    logger.opt(colors=True).warning(f"检测到有新版本可用: <y>{local_hash[:7]}</> -> <g>{latest_hash[:7]}</>")
    logger.opt(colors=True).warning(
        "请前往仓库 Actions 页面下载最新构建" if IS_FROZEN else "请使用命令 <y>git pull</> 拉取最新代码并重新运行程序"
    )
    logger.warning("=" * 60)


async def check_update_loop() -> None:
    if not get_local_commit_hash():
        return

    while True:
        now = datetime.now()
        delay = 3600 - (now.minute * 60 + now.second)
        await anyio.sleep(delay)
        try:
            await check_update()
        except Exception:
            logger.opt(exception=True).warning("自动更新检查时出错，跳过此次检查")
        await anyio.sleep(60)
