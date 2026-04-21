import datetime as dt
import inspect
from collections.abc import Awaitable, Callable

import anyio

from app.log import logger

from . import christmas, hallowen

_EVENT_END_ATTRIBUTE_NAME = "EVENT_END"
_SETUP_FUNCTION_NAME = "setup"
_EVENT_MODULES = [hallowen, christmas]
logger = logger.opt(colors=True)


async def _run_setup_func(setup_func: Callable[[], Awaitable[object]], module_name: str) -> None:
    try:
        await setup_func()
    except Exception:
        logger.exception(f"Error in setup function of module {module_name}")


async def setup_events() -> None:
    setups: list[tuple[str, Callable[[], Awaitable[object]]]] = []
    utc_now = dt.datetime.now(dt.UTC)

    for module in _EVENT_MODULES:
        colored_name = f"<i><lm>{module.__name__}</></>"
        if not hasattr(module, _EVENT_END_ATTRIBUTE_NAME):
            logger.warning(f"Module {colored_name} does not have attribute '{_EVENT_END_ATTRIBUTE_NAME}', skipping")
            continue

        event_end = getattr(module, _EVENT_END_ATTRIBUTE_NAME)
        assert isinstance(event_end, dt.datetime), (
            f"{_EVENT_END_ATTRIBUTE_NAME} in module {colored_name} must be a datetime object"
        )

        if event_end <= utc_now:
            logger.debug(f"Event in module {colored_name} has already ended, skipping")
            continue

        if not hasattr(module, _SETUP_FUNCTION_NAME):
            logger.warning(f"Module {colored_name} does not have attribute '{_SETUP_FUNCTION_NAME}', skipping")
            continue

        setup_func = getattr(module, _SETUP_FUNCTION_NAME)
        assert callable(setup_func), f"{_SETUP_FUNCTION_NAME} in module {colored_name} must be a callable"
        assert inspect.iscoroutinefunction(setup_func), (
            f"{_SETUP_FUNCTION_NAME} in module {colored_name} must be an async function"
        )
        assert inspect.signature(setup_func).parameters == {}, (
            f"{_SETUP_FUNCTION_NAME} in module {colored_name} must not take any parameters"
        )

        setups.append((module.__name__, setup_func))

    if not setups:
        logger.info("No active events found")
        return

    async with anyio.create_task_group() as tg:
        for module_name, setup_func in setups:
            tg.start_soon(_run_setup_func, setup_func, module_name)
            logger.success(f"Started event loop for module <i><lm>{module_name}</></>")
