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
    from bpy import context  # pylint: disable=import-error,no-name-in-module

    if bpy.app.background:
        return Result(status="error", message="Screenshots are not available in background mode")

    window = context.window
    if window is None:
        return Result(status="error", message="No active window")

    # Use a unique temp file to avoid collisions if multiple
    # requests run concurrently.
    fd, filepath = tempfile.mkstemp(suffix=".png", prefix="blmcp_screenshot_")
    os.close(fd)
    try:
        try:
            bpy.ops.screen.screenshot(filepath=filepath)
        except RuntimeError as ex:
            return Result(status="error", message=str(ex))

        with open(filepath, "rb") as fh:
            data = base64.b64encode(fh.read()).decode("ascii")
    finally:
        # Clean up even if the screenshot or read fails.
        if os.path.exists(filepath):
            os.remove(filepath)

    return Result(status="ok", image_base64=data)
