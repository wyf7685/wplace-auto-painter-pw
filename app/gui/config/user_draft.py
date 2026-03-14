from pathlib import Path
from typing import Any

from app.const import TEMPLATES_DIR


def default_user(identifier: str) -> dict[str, Any]:
    return {
        "identifier": identifier,
        "credentials": {"token": "", "cf_clearance": ""},
        "template": {
            "file_id": "",
            "coords": "(Tl X: 0, Tl Y: 0, Px X: 0, Px Y: 0)",
        },
        "preferred_colors": [],
        "selected_area": None,
        "auto_purchase": None,
        "min_paint_charges": 30,
        "max_paint_charges": None,
        "_template_source": "",
    }


def normalize_user(user: dict[str, Any]) -> dict[str, Any]:
    result = default_user(user.get("identifier") or "user")
    result["identifier"] = user.get("identifier") or result["identifier"]

    creds = user.get("credentials")
    if not isinstance(creds, dict):
        creds = {}
    result["credentials"] = {
        "token": str(creds.get("token") or ""),
        "cf_clearance": str(creds.get("cf_clearance") or ""),
    }

    template = user.get("template")
    if not isinstance(template, dict):
        template = {}

    coords = template.get("coords")
    coords_text = ""
    if isinstance(coords, dict):
        try:
            coords_text = (
                f"(Tl X: {int(coords['tlx'])}, Tl Y: {int(coords['tly'])}, "
                f"Px X: {int(coords['pxx'])}, Px Y: {int(coords['pxy'])})"
            )
        except Exception:
            coords_text = ""
    elif isinstance(coords, str):
        coords_text = coords

    result["template"] = {
        "file_id": str(template.get("file_id") or ""),
        "coords": coords_text,
    }

    selected_area = user.get("selected_area")
    if isinstance(selected_area, (list, tuple)) and len(selected_area) == 4:
        try:
            result["selected_area"] = tuple(int(v) for v in selected_area)
        except Exception:
            result["selected_area"] = None

    preferred = user.get("preferred_colors")
    if isinstance(preferred, list):
        result["preferred_colors"] = [str(v) for v in preferred if str(v).strip()]

    auto_purchase = user.get("auto_purchase")
    if isinstance(auto_purchase, dict):
        result["auto_purchase"] = auto_purchase

    min_charges = user.get("min_paint_charges")
    if isinstance(min_charges, int):
        result["min_paint_charges"] = min_charges

    max_charges = user.get("max_paint_charges")
    if isinstance(max_charges, int):
        result["max_paint_charges"] = max_charges

    return result


def format_selected_area(selected_area: tuple[int, int, int, int] | None) -> str:
    if selected_area is None:
        return ""
    return ",".join(str(v) for v in selected_area)


def parse_selected_area(raw: str) -> tuple[int, int, int, int] | None:
    text = raw.strip()
    if not text:
        return None

    parts = [p.strip() for p in text.split(",")]
    if len(parts) != 4:
        raise ValueError("selected_area must be x,y,w,h")

    return tuple(int(p) for p in parts)  # type: ignore[return-value]


def resolve_template_image(file_id: str) -> Path | None:
    if not file_id.strip():
        return None

    path = TEMPLATES_DIR / f"{file_id}.png"
    if path.is_file():
        return path
    return None
