from pathlib import Path

_ASSETS_DIR = Path(__file__).parent / "assets"


class _AssetsItem:
    def __set_name__(self, owner: type, name: str) -> None:
        self.__name = name

    def __get__(self, instance: object, owner: type) -> str:
        return _ASSETS_DIR.joinpath(f"{self.__name}.js").read_text("utf-8")


class Assets:
    page_init = _AssetsItem()
    paint_btn = _AssetsItem()

ASSETS = Assets()
