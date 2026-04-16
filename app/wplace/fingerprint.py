import base64
import hashlib
import math
import random
import struct
from dataclasses import dataclass

from app.log import logger
from app.utils import Highlight


@dataclass
class Features:
    is_linear_movement: bool
    is_constant_interval: bool
    has_zero_jitter: bool
    hts: bool
    navigator_webdriver: bool
    untrusted_click: bool
    cdp: bool
    odz: bool
    click_count: int
    mouse_speed_avg: float
    micro_movement_count: int
    mouse_speed_stddev: float
    movement_segments: int
    avg_segment_curvature: float
    last_click_x: int
    last_click_y: int
    lc: int
    pc: int
    mtp: int
    idle_ms: int
    focus_ms: int
    mouse_accel_avg: float
    mouse_accel_stddev: float
    angular_velocity_stddev: float
    velocity_profile_skew: float
    pre_click_pause_avg: int
    sw: int
    sh: int
    fb: int
    ptc: int
    adf: int
    a_flags: int
    Pn_100: int

    def encode(self) -> str:
        flags = (
            self.is_linear_movement
            | (self.is_constant_interval << 1)
            | (self.has_zero_jitter << 2)
            | (self.hts << 3)
            | (self.navigator_webdriver << 4)
            | (self.untrusted_click << 5)
            | (self.cdp << 6)
            | (self.odz << 7)
        )
        b = bytearray(40)
        b[0] = 1  # version
        b[1] = flags
        b[2] = self.click_count
        struct.pack_into(">H", b, 3, int(self.mouse_speed_avg * 100))
        b[5] = self.micro_movement_count & 0xFF
        b[6] = int(self.mouse_speed_stddev * 100)
        b[7] = self.movement_segments
        b[8] = int(self.avg_segment_curvature * 255)
        struct.pack_into(">H", b, 9, self.last_click_x)
        struct.pack_into(">H", b, 11, self.last_click_y)
        b[13] = self.lc
        b[14] = self.pc
        b[15] = self.mtp
        struct.pack_into(">H", b, 16, self.idle_ms)
        struct.pack_into(">H", b, 18, self.focus_ms & 0xFFFF)
        struct.pack_into(">H", b, 20, int(self.mouse_accel_avg * 100))
        struct.pack_into(">H", b, 22, int(self.mouse_accel_stddev * 100))
        struct.pack_into(">H", b, 24, int(self.angular_velocity_stddev * 1e4))
        struct.pack_into(">h", b, 26, int(self.velocity_profile_skew * 1e3))
        struct.pack_into(">H", b, 28, self.pre_click_pause_avg)
        struct.pack_into(">H", b, 30, self.sw)
        struct.pack_into(">H", b, 32, self.sh)
        b[34] = self.fb
        b[35] = self.ptc
        b[36] = self.adf
        b[37] = self.a_flags
        struct.pack_into(">H", b, 38, self.Pn_100)
        return base64.b64encode(b).decode()


def _t(count: int) -> str:
    count += random.randint(-10, 10)
    count &= 0x7F
    features = Features(
        is_linear_movement=False,
        is_constant_interval=False,
        has_zero_jitter=False,
        hts=True,
        navigator_webdriver=False,
        untrusted_click=False,
        cdp=False,
        odz=False,
        click_count=count,
        mouse_speed_avg=random.uniform(2, 5),
        micro_movement_count=random.randint(math.floor(count // 2 * 0.9), math.ceil(count // 2 * 1.1)),
        mouse_speed_stddev=random.uniform(1.5, 2.5),
        movement_segments=random.randint(1, 10),
        avg_segment_curvature=random.uniform(0.02, 0.2),
        last_click_x=random.randint(320, 960),
        last_click_y=random.randint(180, 540),
        lc=1,
        pc=5,
        mtp=10,
        idle_ms=random.randint(200, 5000),
        focus_ms=random.randint(count * 40, count * 110),
        mouse_accel_avg=random.uniform(3, 5),
        mouse_accel_stddev=random.uniform(15, 55),
        angular_velocity_stddev=random.uniform(0.8, 3),
        velocity_profile_skew=random.uniform(5, 15),
        pre_click_pause_avg=random.randint(50, 250),
        sw=1707,
        sh=960,
        fb=94,
        ptc=0,
        adf=0,
        a_flags=1,
        Pn_100=random.randint(400, 1600),
    )
    return features.encode()


def _fp(identity: object) -> str:
    return hashlib.sha256(str(identity).encode()).hexdigest()[:32]


def generate_fingerprint(identity: object, count: int) -> dict[str, str]:
    data = {"t": _t(count), "fp": _fp(identity)}
    logger.opt(colors=True).debug(f"Generated fingerprint: {Highlight.apply(data)}")
    return data
