import argparse
import contextlib
import sys
from pathlib import Path
from time import perf_counter


def _parse_args() -> tuple[argparse.Namespace, list[str]]:
    parser = argparse.ArgumentParser(add_help=False)
    parser.add_argument("--version", action="store_true")
    parser.add_argument("--no-gui", action="store_true")
    parser.add_argument("--update-ready-file", type=Path, help=argparse.SUPPRESS)
    return parser.parse_known_args()


def main(startup_marks: list[tuple[str, float]] | None = None) -> None:
    if startup_marks is None:
        startup_marks = [("python_entry", perf_counter())]

    args, qt_args = _parse_args()
    if args.version:
        from app.const import APP_NAME
        from app.version import get_version_display

        sys.stdout.write(f"{APP_NAME} {get_version_display()}\n")
        return

    from app.const import IS_FROZEN, ensure_runtime_directories

    ensure_runtime_directories()
    startup_marks.append(("runtime_directories", perf_counter()))

    from app.config import Config, export_config_schema
    from app.i18n import lang

    startup_marks.append(("config_import", perf_counter()))

    export_config_schema()
    startup_marks.append(("config_schema", perf_counter()))
    lang.set_language(None)
    with contextlib.suppress(Exception):
        lang.set_language(Config.load().language)
    startup_marks.append(("language_and_config", perf_counter()))
    sys.argv[1:] = qt_args

    with contextlib.suppress(KeyboardInterrupt):
        if args.no_gui and not IS_FROZEN:
            import anyio

            from app.wplace import run_painter

            anyio.run(run_painter)
        else:
            from app.gui import run_gui

            startup_marks.append(("gui_import", perf_counter()))

            run_gui(ready_file=args.update_ready_file, startup_marks=startup_marks)


if __name__ == "__main__":
    main()
