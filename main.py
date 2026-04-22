import contextlib
import sys


def main() -> None:
    from app.config import export_config_schema

    export_config_schema()

    with contextlib.suppress(KeyboardInterrupt):
        if not getattr(sys, "frozen", False) and sys.argv[-1] == "--no-gui":
            import anyio

            from app.wplace import run_painter

            anyio.run(run_painter)
        else:
            from app.gui import run_gui

            run_gui()


if __name__ == "__main__":
    main()
