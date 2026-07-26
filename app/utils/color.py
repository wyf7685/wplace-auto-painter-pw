def parse_rgb_str(s: str) -> tuple[int, int, int] | None:
    if not (s := s.removeprefix("#").lower()) or len(s) != 6:
        return None

    if any(c not in "0123456789abcdef" for c in s):
        return None

    r, g, b = (int(s[i : i + 2], 16) for i in (0, 2, 4))
    return r, g, b
