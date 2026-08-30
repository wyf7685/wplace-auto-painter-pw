import functools
from datetime import datetime

import anyio
import httpx

from app.const import IS_FROZEN, REPOSITORY_ACTIONS_URL, REPOSITORY_NAME, REPOSITORY_OWNER
from app.log import logger
from app.version import get_commit_hash, run_git

BRANCH = "master"
WORKFLOW_FILE = "build.yml"
ACTIONS_URL = f"{REPOSITORY_ACTIONS_URL}/workflows/{WORKFLOW_FILE}"


@functools.cache
def is_master() -> bool:
    process = run_git("rev-parse", "--symbolic-full-name", "HEAD")
    if process is None:
        return True
    return process.returncode == 0 and process.stdout.strip() == "refs/heads/master"


def get_local_commit_hash() -> str | None:
    if IS_FROZEN:
        return get_commit_hash()

    process = run_git("status", "--porcelain")
    if process is None or process.returncode != 0 or process.stdout.strip():
        return None

    return get_commit_hash()


async def get_latest_commit_hash() -> str:
    from app.config import Config

    url = f"https://api.github.com/repos/{REPOSITORY_OWNER}/{REPOSITORY_NAME}/commits/{BRANCH}"
    headers = {
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2026-03-10",
    }
    async with httpx.AsyncClient(proxy=Config.load().proxy) as client:
        resp = await client.get(url, headers=headers, timeout=10.0)
        data = resp.raise_for_status().json()
        return data["sha"]


async def check_update() -> None:
    if not is_master():
        logger.info("未在主分支，跳过更新检查")
        return

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
    if IS_FROZEN:
        logger.opt(colors=True).warning("请前往项目 <y>Actions</> 页面下载最新构建并替换当前程序")
        logger.opt(colors=True).warning(f"<c><i>{ACTIONS_URL}</></>")
    else:
        logger.opt(colors=True).warning("请使用命令 <y>git pull</> 拉取最新代码并重新运行程序")
    logger.warning("=" * 60)


async def check_update_loop() -> None:
    if not get_local_commit_hash() or not is_master():
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
