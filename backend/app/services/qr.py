"""QR codes encode the short URL plus ?src=qr, so analytics can tell scans from clicks.
Because the QR points at the SHORT link, every rule (expiry, cap, takedown) applies to scans too,
and the destination can change later without reprinting anything."""
from __future__ import annotations

import io

import segno

from app.services.links import short_url

INK = "#16233A"


def qr_bytes(code: str, fmt: str = "png", scale: int = 10) -> tuple[bytes, str]:
    qr = segno.make(f"{short_url(code)}?src=qr", error="m")
    buf = io.BytesIO()
    if fmt == "svg":
        qr.save(buf, kind="svg", scale=scale, border=2, dark=INK, light="#ffffff")
        return buf.getvalue(), "image/svg+xml"
    qr.save(buf, kind="png", scale=scale, border=2, dark=INK, light="#ffffff")
    return buf.getvalue(), "image/png"
