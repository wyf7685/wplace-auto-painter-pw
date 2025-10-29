from typing import Any


def create_user(identifier: str) -> dict[str, Any]:
    """创建一个新的用户字典（默认空字段）。"""
    return {
        "identifier": identifier,
        "template": {"file_id": "", "coords": {"tlx": 0, "tly": 0, "pxx": 0, "pxy": 0}},
        "credentials": {"token": "", "cf_clearance": ""},
    }


def remove_users_by_identifier(cfg: dict[str, Any], identifier: str) -> dict[str, Any]:
    """从配置字典中过滤掉所有 identifier 匹配的用户并返回新的配置字典。"""
    users = cfg.get("users")
    if not isinstance(users, list):
        return cfg
    new_users = [u for u in users if u.get("identifier") != identifier]
    cfg["users"] = new_users
    return cfg
