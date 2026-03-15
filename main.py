import contextlib
import multiprocessing

multiprocessing.freeze_support()

from app.config import export_config_schema


def main() -> None:
    export_config_schema()

    with contextlib.suppress(KeyboardInterrupt):
        from app.gui import run_gui

        run_gui()


if __name__ == "__main__":
    main()
