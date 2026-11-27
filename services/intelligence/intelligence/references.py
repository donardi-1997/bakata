"""Opaque local review/actor references, not authentication or authorization."""
import re


def ref(value):
    if not isinstance(value, str) or not re.fullmatch(r"[A-Za-z0-9._-]{1,128}", value):
        raise ValueError("Invalid review or actor reference")
    return value
