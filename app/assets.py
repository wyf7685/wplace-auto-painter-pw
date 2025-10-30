from .config import ASSETS_DIR


class _AssetsItem:
    def __set_name__(self, owner: type, name: str) -> None:
        self.__name = name

    def __get__(self, instance: object, owner: type) -> str:
        return ASSETS_DIR.joinpath(f"{self.__name}.js").read_text("utf-8")


class Assets:
    page_init = _AssetsItem()
    paint_btn = _AssetsItem()


assets = Assets()
