"""中文口播数字：年份逐位，数量用数词，禁止「$1美元」叠读。英文段不改。"""
from __future__ import annotations

import re

_DIG = "零一二三四五六七八九"
_FULLWIDTH = str.maketrans("０１２３４５６７８９", "0123456789")
# 这些字跟在四位数字后面时，按数量读，不按年份逐位。
_YEAR_BLOCK = "亿万千百个次台人名家倍块元分秒月天小时"

_TOKEN = re.compile(
    r"\$(?P<money>\d+(?:\.\d+)?)(?P<money_unit>\s*(?:亿美元|美元|亿|万))?"
    r"|(?P<pct>\d+(?:\.\d+)?)%"
    r"|(?<![\d.A-Za-z])(?P<year>(?:19|20)\d{2})(?![\d.])(?![" + _YEAR_BLOCK + r"])"
    r"|(?<![\d.A-Za-z])(?P<num>\d+(?:\.\d+)?)(?P<unit>\s*(?:万亿|亿美元|千万|亿|万))?"
)


def _four(n: int) -> str:
    """1..9999 → 中文数词。最高位的 2 在百/千上读「两」。"""
    units = ((1000, "千"), (100, "百"), (10, "十"), (1, ""))
    out: list[str] = []
    zero = False
    rest = n
    for base, unit in units:
        digit = rest // base
        rest %= base
        if digit == 0:
            if out:
                zero = True
            continue
        if zero:
            out.append("零")
            zero = False
        if digit == 2 and unit in ("千", "百") and not out:
            out.append("两" + unit)
        elif digit == 1 and unit == "十" and not out:
            out.append("十")
        else:
            out.append(_DIG[digit] + unit)
    return "".join(out)


def int_to_zh(n: int) -> str:
    if n == 0:
        return "零"
    if n < 0:
        return "负" + int_to_zh(-n)
    group_units = ("", "万", "亿", "兆")
    chunks: list[int] = []
    x = n
    while x:
        chunks.append(x % 10000)
        x //= 10000
    if len(chunks) > len(group_units):
        raise ValueError(f"数字过大: {n}")
    out: list[str] = []
    for i in range(len(chunks) - 1, -1, -1):
        chunk = chunks[i]
        if chunk == 0:
            continue
        if out:
            higher = i + 1
            skipped = False
            while higher < len(chunks) and chunks[higher] == 0:
                skipped = True
                higher += 1
            if skipped or chunk < 1000:
                out.append("零")
        if chunk == 2 and i > 0:
            piece = "两"
        else:
            piece = _four(chunk)
        out.append(piece + group_units[i])
    return "".join(out)


def num_to_zh(token: str, *, year: bool = False) -> str:
    token = token.translate(_FULLWIDTH)
    if year:
        return "".join(_DIG[int(c)] for c in token if c.isdigit())
    if "." in token:
        whole, frac = token.split(".", 1)
        whole_n = int(whole) if whole else 0
        # 小数的整数部分 2 读「二」，避免「两点五亿」。
        whole_s = "二" if whole_n == 2 else int_to_zh(whole_n)
        frac_s = "".join(_DIG[int(c)] for c in frac if c.isdigit())
        return f"{whole_s}点{frac_s}"
    return int_to_zh(int(token))


def _sub(match: re.Match[str]) -> str:
    if match.group("money"):
        unit = (match.group("money_unit") or "美元").strip() or "美元"
        return num_to_zh(match.group("money")) + unit
    if match.group("pct"):
        return "百分之" + num_to_zh(match.group("pct"))
    if match.group("year"):
        return num_to_zh(match.group("year"), year=True)
    unit = (match.group("unit") or "").strip()
    return num_to_zh(match.group("num")) + unit


def convert_numbers(text: str) -> str:
    """只用于中文段。英文整句不要调用。"""
    return _TOKEN.sub(_sub, text.translate(_FULLWIDTH))
