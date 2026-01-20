import base64
import datetime as dt
import functools
import inspect
import threading
import time
import types
from json import JSONEncoder
from typing import TYPE_CHECKING, Any, Self, cast

import anyio
import anyio.to_thread
from pydantic import BaseModel, SecretStr

from app.log import escape_tag, logger

if TYPE_CHECKING:
    from collections.abc import Callable, Coroutine

    type AsyncCallable[**P, R] = Callable[P, Coroutine[None, None, R]]


UTC8 = dt.timezone(dt.timedelta(hours=8))


def with_retry[**P, R](
    *exc: type[Exception],
    retries: int = 3,
    delay: float = 0,
) -> Callable[[AsyncCallable[P, R]], AsyncCallable[P, R]]:
    assert retries >= 1, "retries must be at least 1"
    assert delay >= 0, "delay must be non-negative"

    if not exc:
        exc_types = Exception
    elif len(exc) == 1:
        exc_types = exc[0]
    else:
        exc_types = (*exc,)

    def decorator(func: AsyncCallable[P, R]) -> AsyncCallable[P, R]:
        func_name = escape_tag(getattr(func, "__name__", repr(func)))

        @functools.wraps(func)
        async def wrapper(*args: P.args, **kwargs: P.kwargs) -> R:
            caught: list[Exception] = []

            for attempt in range(retries):
                try:
                    return await func(*args, **kwargs)
                except exc_types as e:
                    logger.opt(colors=True).debug(
                        f"函数 <g>{func_name}</> "
                        f"第 <y>{attempt + 1}</>/<y>{retries}</> 次调用失败: "
                        f"<r>{escape_tag(repr(e))}</>"
                    )
                    caught.append(cast("Exception", e))
                    await anyio.sleep(delay)

            raise ExceptionGroup(f"所有 {retries} 次尝试均失败", caught) from caught[0]

        return wrapper

    return decorator


class PerfLog:
    def __init__(self, on_start: str, on_end: str) -> None:
        self._on_start = on_start
        self._on_end = on_end
        self._start: float | None = None
        self._end: float | None = None

    def __enter__(self) -> Self:
        self._start = time.perf_counter()
        logger.opt(colors=True).debug(self._on_start.format(start=self._start))
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc_value: BaseException | None,
        exc_traceback: types.TracebackType | None,
    ) -> None:
        self._end = time.perf_counter()
        logger.opt(colors=True).debug(self._on_end.format(end=self._end, elapsed=self.elapsed))

    async def __aenter__(self) -> Self:
        return self.__enter__()

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc_value: BaseException | None,
        exc_traceback: types.TracebackType | None,
    ) -> None:
        return self.__exit__(exc_type, exc_value, exc_traceback)

    @property
    def start(self) -> float:
        if self._start is None:
            raise ValueError("Start time not set yet")
        return self._start

    @property
    def end(self) -> float:
        if self._end is None:
            raise ValueError("End time not set yet")
        return self._end

    @property
    def elapsed(self) -> float:
        return self.end - self.start

    @classmethod
    def for_action(cls, action: str) -> Self:
        return cls(
            f"Starting <i><c>{action}</></> at <c>{{start:.2f}}</>",
            f"Finished <i><c>{action}</></> at <c>{{end:.2f}}</>, elapsed <c>{{elapsed:.2f}}</>s",
        )

    @classmethod
    def for_method[**P, R](cls, method_name: str | None = None) -> Callable[[Callable[P, R]], Callable[P, R]]:
        def decorator(func: Callable[P, R]) -> Callable[P, R]:
            name = method_name or escape_tag(getattr(func, "__name__", repr(func)))

            if inspect.iscoroutinefunction(func):
                afunc = cast("AsyncCallable[P, R]", func)

                async def wrapper_async(*args: P.args, **kwargs: P.kwargs) -> R:
                    with cls.for_action(f"<y>method</> {name}"):
                        return await afunc(*args, **kwargs)

                wrapper = wrapper_async
            else:

                def wrapper_sync(*args: P.args, **kwargs: P.kwargs) -> R:
                    with cls.for_action(f"<y>method</> {name}"):
                        return func(*args, **kwargs)

                wrapper = wrapper_sync

            return cast("Callable[P, R]", functools.update_wrapper(wrapper, func))

        return decorator


def with_semaphore[T: Callable](initial_value: int) -> Callable[[T], T]:
    def decorator(func: T) -> T:
        if inspect.iscoroutinefunction(func):
            async_sem = anyio.Semaphore(initial_value)
            afunc = cast("AsyncCallable[[T], T]", func)

            @functools.wraps(func)
            async def wrapper_async(*args: Any, **kwargs: Any) -> Any:
                async with async_sem:
                    return await afunc(*args, **kwargs)

            wrapper = wrapper_async
        else:
            sync_sem = threading.Semaphore(initial_value)

            @functools.wraps(func)
            def wrapper_sync(*args: Any, **kwargs: Any) -> Any:
                with sync_sem:
                    return func(*args, **kwargs)

            wrapper = wrapper_sync

        return cast("T", functools.update_wrapper(wrapper, func))

    return decorator


def requests_proxies() -> dict[str, str] | None:
    from app.config import Config

    proxy = Config.load().proxy
    return {"http": proxy, "https": proxy} if proxy else None


class _TokenPayload(BaseModel):
    userId: int  # noqa: N815
    sessionId: str  # noqa: N815
    iss: str
    exp: int
    iat: int

    @property
    def expires_at(self) -> dt.datetime:
        return dt.datetime.fromtimestamp(self.exp, dt.UTC).astimezone(UTC8).replace(tzinfo=None)


def is_token_expired(token: str, ahead_secs: int = 60) -> bool:
    parts = token.split(".")
    if len(parts) != 3:
        return True

    payload = parts[1]
    if rem := len(payload) % 4:
        payload += "=" * (4 - rem)

    try:
        payload = _TokenPayload.model_validate_json(base64.urlsafe_b64decode(payload).decode())
    except Exception:
        return True

    return (payload.expires_at - dt.datetime.now()).total_seconds() < ahead_secs


def run_sync[**P, R](call: Callable[P, R]) -> Callable[P, Coroutine[None, None, R]]:
    """一个用于包装 sync function 为 async function 的装饰器

    参数:
        call: 被装饰的同步函数
    """

    @functools.wraps(call)
    async def _wrapper(*args: P.args, **kwargs: P.kwargs) -> R:
        return await anyio.to_thread.run_sync(functools.partial(call, *args, **kwargs), abandon_on_cancel=True)

    return _wrapper


class SecretStrEncoder(JSONEncoder):
    def default(self, o: Any) -> Any:
        if isinstance(o, SecretStr):
            return o.get_secret_value()
        return super().default(o)
