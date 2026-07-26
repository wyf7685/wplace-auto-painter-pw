import hashlib

from app.log import logger
from app.utils import Highlight


def _fp(identity: object) -> str:
    return hashlib.sha256(str(identity).encode()).hexdigest()[:32]


def generate_fingerprint(identity: object) -> list[str]:
    data = [_fp(identity)]
    logger.opt(colors=True).debug(f"Generated fingerprint: {Highlight.apply(data)}")
    return data
