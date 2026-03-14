import contextlib
import multiprocessing

multiprocessing.freeze_support()


def main() -> None:
    with contextlib.suppress(KeyboardInterrupt):
        from app.gui import run_gui

        run_gui()


if __name__ == "__main__":
    main()
