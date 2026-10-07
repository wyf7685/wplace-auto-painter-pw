import logging
from pathlib import Path
from typing import TYPE_CHECKING, cast

import anyio
import pytest

import app.browser.manager as manager

if TYPE_CHECKING:
    from playwright.async_api import BrowserType, Playwright


class FakePlaywright:
    def __init__(self) -> None:
        self.stopped = False

    async def stop(self) -> None:
        await anyio.lowlevel.checkpoint()
        self.stopped = True


@pytest.fixture
def playwright_state(monkeypatch: pytest.MonkeyPatch) -> manager._PlaywrightState:
    state = manager._PlaywrightState()
    monkeypatch.setattr(manager, "_get_state", lambda: state)
    monkeypatch.setattr(manager, "logger", logging.getLogger(__name__))
    return state


@pytest.fixture
def forbid_browser_start(monkeypatch: pytest.MonkeyPatch) -> None:
    async def initialize() -> tuple[BrowserType, str, str | None]:
        pytest.fail("Browser initialization must not run without a lifecycle context")

    monkeypatch.setattr(manager, "_get_browser_type", initialize)


def test_playwright_context_finishes_cleanup_when_cancelled(playwright_state: manager._PlaywrightState) -> None:
    playwright = FakePlaywright()
    playwright_state.instance = cast("Playwright", playwright)

    async def run() -> None:
        with anyio.CancelScope() as cancel_scope:
            async with manager.create_playwright_context():
                await anyio.lowlevel.checkpoint()
                cancel_scope.cancel()
                await anyio.sleep_forever()

        assert cancel_scope.cancelled_caught
        assert playwright.stopped
        assert playwright_state.instance is None

    anyio.run(run)


@pytest.mark.usefixtures("forbid_browser_start")
@pytest.mark.parametrize("persistent", [False, True])
def test_browser_acquisition_requires_lifecycle_context(persistent: bool) -> None:
    async def run() -> None:
        context = manager.get_persistent_context(Path("profile")) if persistent else manager.get_browser()
        with pytest.raises(RuntimeError):
            async with context:
                pytest.fail("Browser acquisition must reject a missing lifecycle context")

    anyio.run(run)


@pytest.mark.usefixtures("playwright_state", "forbid_browser_start")
def test_browser_rejects_task_outside_active_lifecycle_context() -> None:
    async def run() -> None:
        owner_ready = anyio.Event()
        checked = anyio.Event()

        async def unrelated_task() -> None:
            await owner_ready.wait()
            with pytest.raises(RuntimeError):
                async with manager.get_browser():
                    pytest.fail("Another task's lifecycle context must not authorize browser acquisition")
            checked.set()

        async with anyio.create_task_group() as task_group:
            task_group.start_soon(unrelated_task)
            async with manager.create_playwright_context():
                owner_ready.set()
                await checked.wait()

    anyio.run(run)


@pytest.mark.usefixtures("playwright_state", "forbid_browser_start")
def test_browser_rejects_inherited_context_after_owner_exits() -> None:
    async def run() -> None:
        owner_exited = anyio.Event()

        async def child_task() -> None:
            await owner_exited.wait()
            with pytest.raises(RuntimeError):
                async with manager.get_browser():
                    pytest.fail("An expired lifecycle context must not authorize browser acquisition")

        async with anyio.create_task_group() as task_group:
            async with manager.create_playwright_context():
                task_group.start_soon(child_task)
            owner_exited.set()

    anyio.run(run)


def test_nested_playwright_context_stops_only_after_outer_exit(playwright_state: manager._PlaywrightState) -> None:
    playwright = FakePlaywright()
    playwright_state.instance = cast("Playwright", playwright)

    async def run() -> None:
        async with manager.create_playwright_context():
            async with manager.create_playwright_context():
                await anyio.lowlevel.checkpoint()
            assert not playwright.stopped
        assert playwright.stopped

    anyio.run(run)


def test_concurrent_playwright_context_keeps_remaining_owner_alive(playwright_state: manager._PlaywrightState) -> None:
    playwright = FakePlaywright()
    playwright_state.instance = cast("Playwright", playwright)

    async def run() -> None:
        owner_ready = anyio.Event()
        release_owner = anyio.Event()
        owner_exited = anyio.Event()

        async def other_owner() -> None:
            async with manager.create_playwright_context():
                owner_ready.set()
                await release_owner.wait()
            owner_exited.set()

        async with anyio.create_task_group() as task_group:
            task_group.start_soon(other_owner)
            await owner_ready.wait()
            async with manager.create_playwright_context():
                release_owner.set()
                await owner_exited.wait()
                assert not playwright.stopped
        assert playwright.stopped

    anyio.run(run)
