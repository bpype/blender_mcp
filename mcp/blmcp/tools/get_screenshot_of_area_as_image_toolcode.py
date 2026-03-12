# SPDX-FileCopyrightText: 2026 Blender Authors
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""
Toolcode for capturing a single area screenshot as PNG.
"""

__all__ = (
    "AreaUIType",
    "Params",
    "Result",
    "main",
)

import base64
import os
import tempfile
from typing import Literal, NamedTuple

# Rarely changes, regenerate with:
# `list(bpy.types.Area.bl_rna.properties["ui_type"].enum_items.keys())`
AreaUIType = Literal[
    # "EMPTY",  # Part of the enum but never visible to users.
    "VIEW_3D",
    "IMAGE_EDITOR",
    "UV",
    "ShaderNodeTree",
    "CompositorNodeTree",
    "GeometryNodeTree",
    "TextureNodeTree",
    "SEQUENCE_EDITOR",
    "CLIP_EDITOR",
    "DOPESHEET_EDITOR",
    "GRAPH_EDITOR",
    "NLA_EDITOR",
    "TEXT_EDITOR",
    "CONSOLE",
    "INFO",
    "TOPBAR",
    "STATUSBAR",
    "OUTLINER",
    "PROPERTIES",
    "FILE_BROWSER",
    "SPREADSHEET",
    "PREFERENCES",
]


class Params(NamedTuple):
    area_ui_type: AreaUIType


class Result(NamedTuple):
    status: str
    image_base64: str | None = None
    message: str | None = None


def main(params: Params) -> Result:
    import bpy  # pylint: disable=import-error,no-name-in-module
    from bpy import context  # pylint: disable=import-error,no-name-in-module

    if bpy.app.background:
        return Result(status="error", message="Screenshots are not available in background mode")

    window = context.window
    if window is None:
        return Result(status="error", message="No active window")
    screen = window.screen

    # Prefer the context's active area if it matches,
    # otherwise pick the largest matching area.
    area = context.area
    if area is None or area.ui_type != params.area_ui_type:
        area = next(iter(sorted(
            (a for a in screen.areas if a.ui_type == params.area_ui_type),
            key=lambda a: -(a.width * a.height),
        )), None)
    if area is None:
        available = sorted({a.ui_type for a in screen.areas})
        return Result(
            status="error",
            message="No area with type {!r} found. Available: {:s}".format(
                params.area_ui_type, ", ".join(available),
            ),
        )
    fd, filepath = tempfile.mkstemp(suffix=".png", prefix="blmcp_screenshot_")
    os.close(fd)
    try:
        with context.temp_override(window=window, area=area):
            try:
                bpy.ops.screen.screenshot_area(filepath=filepath)
            except RuntimeError as ex:
                return Result(status="error", message=str(ex))

        with open(filepath, "rb") as fh:
            data = base64.b64encode(fh.read()).decode("ascii")
    finally:
        if os.path.exists(filepath):
            os.remove(filepath)

    return Result(status="ok", image_base64=data)
