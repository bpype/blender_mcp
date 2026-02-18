# SPDX-FileCopyrightText: 2026 Blender Authors
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""
Toolcode for capturing a window screenshot as PNG.
"""

__all__ = (
    "Result",
    "main",
)

import base64
import os
import tempfile
from typing import NamedTuple


class Result(NamedTuple):
    status: str
    image_base64: str | None = None
    message: str | None = None


def main(params: None) -> Result:
    del params
    import bpy  # pylint: disable=import-error,no-name-in-module

    # Capture the full window via the first available area.
    window = bpy.context.window
    screen = window.screen
    if not screen.areas:
        return Result(status="error", message="No areas found in the current screen")
    area = screen.areas[0]
    if not area.regions:
        return Result(status="error", message="No regions found in the first area")
    region = area.regions[0]

    # Use a unique temp file to avoid collisions if multiple
    # requests run concurrently.
    fd, filepath = tempfile.mkstemp(suffix=".png", prefix="blmcp_screenshot_")
    os.close(fd)
    try:
        with bpy.context.temp_override(window=window, area=area, region=region):
            try:
                bpy.ops.screen.screenshot_area(filepath=filepath)
            except RuntimeError as ex:
                return Result(status="error", message=str(ex))

        with open(filepath, "rb") as fh:
            data = base64.b64encode(fh.read()).decode("ascii")
    finally:
        # Clean up even if the screenshot or read fails.
        if os.path.exists(filepath):
            os.remove(filepath)

    return Result(status="ok", image_base64=data)
