import datetime as dt
import importlib
import inspect
from collections.abc import Awaitable, Callable, Iterator
from pathlib import Path
from types import ModuleType

import anyio

from app.log import logger

_EVENT_END_ATTRIBUTE_NAME = "EVENT_END"
_SETUP_FUNCTION_NAME = "setup"


def _iter_event_modules() -> Iterator[ModuleType]:
    for path in Path(__file__).parent.iterdir():
        if (path.is_file() and path.suffix == ".py" and path.stem != "__init__") or (
            path.is_dir() and (path / "__init__.py").exists()
        ):
            yield importlib.import_module(f".{path.stem}", __package__)


async def _run_setup_func(setup_func: Callable[[], Awaitable[object]], module_name: str) -> None:
    try:
        await setup_func()
    except Exception:
        logger.exception(f"Error in setup function of module {module_name}")


async def setup_events() -> None:
    setups: list[tuple[str, Callable[[], Awaitable[object]]]] = []
    utc_now = dt.datetime.now(dt.UTC)

    for module in _iter_event_modules():
        if not hasattr(module, _EVENT_END_ATTRIBUTE_NAME):
            logger.warning(f"Module {module.__name__} does not have attribute '{_EVENT_END_ATTRIBUTE_NAME}', skipping")
            continue

        event_end = getattr(module, _EVENT_END_ATTRIBUTE_NAME)
        assert isinstance(event_end, dt.datetime), (
            f"{_EVENT_END_ATTRIBUTE_NAME} in module {module.__name__} must be a datetime object"
        )

        if event_end <= utc_now:
            logger.debug(f"Event in module {module.__name__} has already ended, skipping")
            continue

        if not hasattr(module, _SETUP_FUNCTION_NAME):
            logger.warning(f"Module {module.__name__} does not have attribute '{_SETUP_FUNCTION_NAME}', skipping")
            continue

        setup_func = getattr(module, _SETUP_FUNCTION_NAME)
        assert callable(setup_func), f"{_SETUP_FUNCTION_NAME} in module {module.__name__} must be a callable"
        assert inspect.iscoroutinefunction(setup_func), (
            f"{_SETUP_FUNCTION_NAME} in module {module.__name__} must be an async function"
        )
        assert inspect.signature(setup_func).parameters == {}, (
            f"{_SETUP_FUNCTION_NAME} in module {module.__name__} must not take any parameters"
        )

        setups.append((module.__name__, setup_func))

    if not setups:
        logger.info("No active events found")
        return

    async with anyio.create_task_group() as tg:
        for module_name, setup_func in setups:
            tg.start_soon(_run_setup_func, setup_func, module_name)
            logger.success(f"Started event loop for module {module_name}")
