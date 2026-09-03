import argparse
import contextlib
import sys
from pathlib import Path

from app.const import APP_NAME, IS_FROZEN, ensure_runtime_directories
from app.version import get_version_display


def _parse_args() -> tuple[argparse.Namespace, list[str]]:
    parser = argparse.ArgumentParser(add_help=False)
    parser.add_argument("--version", action="store_true")
    parser.add_argument("--no-gui", action="store_true")
    parser.add_argument("--update-ready-file", type=Path, help=argparse.SUPPRESS)
    return parser.parse_known_args()


def main() -> None:
    args, qt_args = _parse_args()
    if args.version:
        sys.stdout.write(f"{APP_NAME} {get_version_display()}\n")
        return

    ensure_runtime_directories()

    from app.config import export_config_schema

    export_config_schema()
    sys.argv[1:] = qt_args

    with contextlib.suppress(KeyboardInterrupt):
        if args.no_gui and not IS_FROZEN:
            import anyio

            from app.wplace import run_painter

            anyio.run(run_painter)
        else:
            from app.gui import run_gui

            run_gui(ready_file=args.update_ready_file)


if __name__ == "__main__":
    main()
