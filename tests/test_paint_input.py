import asyncio
from itertools import pairwise
from typing import Any, cast

import pytest

from app.wplace.page import WplacePage
from app.wplace.paint import Pixel, plan_space_drag_strokes


def _bresenham(start: tuple[int, int], end: tuple[int, int]) -> set[tuple[int, int]]:
    x, y = start
    target_x, target_y = end
    dx = abs(target_x - x)
    dy = abs(target_y - y)
    step_x = 1 if x < target_x else -1
    step_y = 1 if y < target_y else -1
    error = dx - dy
    points: set[tuple[int, int]] = set()

    while True:
        points.add((x, y))
        if (x, y) == (target_x, target_y):
            return points
        twice_error = 2 * error
        if twice_error > -dy:
            error -= dy
            x += step_x
        if twice_error < dx:
            error += dx
            y += step_y


def _expanded_stroke(stroke: list[Pixel]) -> set[tuple[int, int]]:
    points = {(stroke[0].x, stroke[0].y)}
    for previous, current in pairwise(stroke):
        points.update(_bresenham((previous.x, previous.y), (current.x, current.y)))
    return points


def test_space_drag_strokes_do_not_bridge_untargeted_pixels() -> None:
    pixels = [
        Pixel(0, 0, 1),
        Pixel(0, 1, 1),
        Pixel(4, 0, 1),
        Pixel(4, 1, 1),
        Pixel(5, 1, 2),
    ]

    strokes = plan_space_drag_strokes(pixels)

    assert strokes == [pixels[:2], pixels[2:4], pixels[4:]]
    targets = {(pixel.x, pixel.y) for pixel in pixels}
    assert set().union(*(_expanded_stroke(stroke) for stroke in strokes)) == targets


def test_space_drag_strokes_stay_within_anchor_radius() -> None:
    pixels = [Pixel(x, 0, 1) for x in range(5)]

    assert plan_space_drag_strokes(pixels, max_radius=2) == [pixels[:3], pixels[3:]]


class FakeMouse:
    def __init__(self, events: list[tuple[object, ...]], fail_on_move: int | None = None) -> None:
        self.events = events
        self.fail_on_move = fail_on_move
        self.move_count = 0

    async def up(self, *, button: str) -> None:
        self.events.append(("mouse_up", button))

    async def move(self, x: float, y: float, *, steps: int) -> None:
        self.move_count += 1
        self.events.append(("mouse_move", x, y, steps))
        if self.move_count == self.fail_on_move:
            raise RuntimeError("mouse move failed")


class FakeKeyboard:
    def __init__(self, events: list[tuple[object, ...]]) -> None:
        self.events = events

    async def down(self, key: str) -> None:
        self.events.append(("key_down", key))

    async def up(self, key: str) -> None:
        self.events.append(("key_up", key))


class BlockingKeyboard(FakeKeyboard):
    def __init__(self, events: list[tuple[object, ...]], down_started: asyncio.Event) -> None:
        super().__init__(events)
        self.down_started = down_started

    async def down(self, key: str) -> None:
        await super().down(key)
        self.down_started.set()
        await asyncio.Event().wait()


class FakeBrowserPage:
    def __init__(
        self,
        events: list[tuple[object, ...]],
        fail_on_move: int | None = None,
        keyboard: FakeKeyboard | None = None,
    ) -> None:
        self.viewport_size = {"width": 1280, "height": 720}
        self.mouse = FakeMouse(events, fail_on_move)
        self.keyboard = keyboard or FakeKeyboard(events)


def _wplace_page(
    events: list[tuple[object, ...]],
    fail_on_move: int | None = None,
    keyboard: FakeKeyboard | None = None,
) -> WplacePage:
    page = object.__new__(WplacePage)
    page.page = cast("Any", FakeBrowserPage(events, fail_on_move, keyboard))
    return page


def test_space_drag_uses_key_hold_around_mouse_movement() -> None:
    events: list[tuple[object, ...]] = []

    asyncio.run(_wplace_page(events).paint_space_drag([(0, 0), (1, 0)]))

    assert events[0] == ("mouse_up", "left")
    assert events[1][0:3] == ("mouse_move", 640.0, 360.0)
    assert events[2] == ("key_down", "Space")
    assert events[3][0:3] == ("mouse_move", 647.65, 360.0)
    assert events[4] == ("key_up", "Space")


def test_space_drag_releases_space_after_movement_failure() -> None:
    events: list[tuple[object, ...]] = []

    with pytest.raises(RuntimeError, match="mouse move failed"):
        asyncio.run(_wplace_page(events, fail_on_move=2).paint_space_drag([(0, 0), (1, 0)]))

    assert events[-1] == ("key_up", "Space")


def test_space_drag_releases_space_when_cancelled_during_key_down() -> None:
    events: list[tuple[object, ...]] = []

    async def run() -> None:
        down_started = asyncio.Event()
        keyboard = BlockingKeyboard(events, down_started)
        page = _wplace_page(events, keyboard=keyboard)
        task = asyncio.create_task(page.paint_space_drag([(0, 0)]))

        await down_started.wait()
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task

    asyncio.run(run())

    assert events[-1] == ("key_up", "Space")
