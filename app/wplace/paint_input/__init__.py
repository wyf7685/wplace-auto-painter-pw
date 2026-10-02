from . import click, space_drag, space_drag_retrace

PAINT_INPUT_HANDLERS = {
    "click": click.paint_pixels,
    "space_drag": space_drag.paint_pixels,
    "space_drag_retrace": space_drag_retrace.paint_pixels,
}
