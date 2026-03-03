"""Playwright environment setup and browser installation utilities.

Handles:
- Setting PLAYWRIGHT_BROWSERS_PATH to a local data directory so browsers are
  stored inside the project rather than the system-wide location.
- Probing mirror sources for connectivity and selecting the fastest one.
- Running `playwright install --with-deps <browser>` with the chosen mirror.

Ref:
https://github.com/kexue-z/nonebot-plugin-htmlrender/blob/v0.7.0.a.3/nonebot_plugin_htmlrender/install.py
"""

import asyncio
import contextlib
import os
import sys
from collections.abc import Awaitable, Callable, Iterator
from urllib.parse import urlparse

from app.log import logger

from .const import MIRRORS, PLAYWRIGHT_BROWSERS_PATH, MirrorSource


def setup_playwright_env() -> None:
    """Point Playwright at the project-local browser cache directory."""
    path = str(PLAYWRIGHT_BROWSERS_PATH.resolve())
    os.environ["PLAYWRIGHT_BROWSERS_PATH"] = path
    logger.debug(f'PLAYWRIGHT_BROWSERS_PATH="{path}"')


def clear_playwright_env() -> None:
    removed = os.environ.pop("PLAYWRIGHT_BROWSERS_PATH", None)
    if removed is not None:
        logger.debug(f'PLAYWRIGHT_BROWSERS_PATH="{removed}" removed')


async def _probe_mirror(mirror: MirrorSource, timeout: float) -> tuple[MirrorSource, float]:  # noqa: ASYNC109
    """Return (mirror, latency) or (mirror, inf) on failure."""
    try:
        parsed = urlparse(mirror.url)
        host = parsed.hostname or ""
        port = parsed.port or (443 if parsed.scheme == "https" else 80)
        loop = asyncio.get_event_loop()
        t0 = loop.time()
        _r, _w = await asyncio.wait_for(asyncio.open_connection(host, port), timeout=timeout)
        _w.close()
        return mirror, loop.time() - t0
    except Exception as exc:
        logger.debug(f"Mirror {mirror.name!r} unreachable: {exc}")
        return mirror, float("inf")


async def find_best_mirror(timeout: float = 5.0) -> MirrorSource | None:  # noqa: ASYNC109
    """Probe all known mirrors concurrently and return the fastest reachable one.

    When multiple mirrors have the same latency the one with the lower
    *priority* value is preferred (lower = higher preference).
    Returns ``None`` if no mirror is reachable.
    """
    results = await asyncio.gather(*[_probe_mirror(m, timeout) for m in MIRRORS])
    reachable = [(m, t) for m, t in results if t != float("inf")]
    if not reachable:
        logger.warning("No Playwright mirror reachable; will use default download URL.")
        return None
    best, latency = min(reachable, key=lambda x: (x[1], x[0].priority))
    logger.debug(f"Selected mirror {best.name!r} (latency={latency * 1000:.0f} ms)")
    return best


@contextlib.contextmanager
def ensure_mirror_env(mirror: MirrorSource | None) -> Iterator[None]:
    """Context manager to set PLAYWRIGHT_DOWNLOAD_HOST to the mirror URL if given."""
    env_key = "PLAYWRIGHT_DOWNLOAD_HOST"
    had_prev = env_key in os.environ
    prev_value = os.environ.get(env_key)

    if mirror is not None:
        os.environ[env_key] = mirror.url
        logger.info(f"Using download mirror: {mirror.name} ({mirror.url})")

    try:
        yield
    finally:
        if had_prev and prev_value is not None:
            os.environ[env_key] = prev_value
        else:
            os.environ.pop(env_key, None)


async def read_stream(
    stream: asyncio.StreamReader | None,
    callback: Callable[[str], Awaitable[None]] | None = None,
) -> str:
    """
    Read lines from the given stream until EOF, optionally passing each line to a callback.

    Returns the full output as a single string.
    """
    if stream is None:
        return ""

    output = []  # 存储读取到的文本内容

    while True:
        try:
            line_data = await stream.readline()
            if not line_data:
                break

            line = line_data.decode().strip()

            if callback:
                try:
                    await callback(line)
                except UnicodeEncodeError:
                    safe_text = "".join(c if ord(c) < 128 else "?" for c in line)
                    await callback(safe_text)

            if line:
                output.append(line)

        except asyncio.IncompleteReadError:
            break
        except Exception as e:
            logger.opt(exception=True).error(f"Error reading stream: {e!s}")
            break

    return "\n".join(output)


async def install_playwright_browser(browser: str, timeout: float = 300.0) -> bool:  # noqa: ASYNC109
    """Install *browser* via ``playwright install --with-deps``.

    Selects the fastest available mirror and sets ``PLAYWRIGHT_DOWNLOAD_HOST``
    before spawning the install subprocess.  The env var is always cleaned up
    on exit.

    Returns ``True`` on success, ``False`` on failure.
    """
    setup_playwright_env()
    PLAYWRIGHT_BROWSERS_PATH.mkdir(parents=True, exist_ok=True)

    mirror = await find_best_mirror()
    with ensure_mirror_env(mirror):
        logger.info(f"Installing Playwright browser: {browser!r} ...")
        try:
            process = await asyncio.create_subprocess_exec(
                sys.executable,
                "-m",
                "playwright",
                "install",
                "--with-deps",
                browser,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )

            async def stdout_callback(line: str) -> None:
                line_stripped = line.strip()
                if (
                    not line_stripped.startswith("Progress:")
                    and "|" not in line_stripped
                    and "%" not in line_stripped
                    and line_stripped
                ):
                    logger.info(line_stripped)

            async def stderr_callback(line: str) -> None:
                line_stripped = line.strip()
                if line_stripped:
                    logger.warning(f"Install error: {line_stripped}")

            stdout_task = asyncio.create_task(read_stream(process.stdout, stdout_callback))
            stderr_task = asyncio.create_task(read_stream(process.stderr, stderr_callback))

            try:
                _, stderr_data = await asyncio.wait_for(asyncio.gather(stdout_task, stderr_task), timeout=timeout)
            except TimeoutError:
                process.kill()
                await process.wait()
                logger.error(f"Playwright browser installation timed out after {timeout:.0f}s.")
                return False

            await process.wait()

            if process.returncode != 0:
                logger.error(
                    f"Playwright browser installation failed (exit {process.returncode}):\n{stderr_data.strip()}"
                )
                return False

        except Exception as exc:
            logger.error(f"Unexpected error during Playwright browser installation: {exc}")
            return False

        else:
            logger.success(f"Playwright browser {browser!r} installed successfully.")
            return True
