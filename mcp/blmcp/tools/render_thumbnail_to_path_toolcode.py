# SPDX-FileCopyrightText: 2026 Blender Authors
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""
Toolcode for low-quality thumbnail rendering.
"""

__all__ = (
    "Params",
    "Result",
    "main",
)

import contextlib
from typing import Generator, NamedTuple

# Thumbnail render settings. Small resolution and low samples
# for a fast preview that is still useful for visual inspection.
# The longest dimension is clamped to this value, preserving aspect ratio.
_THUMB_DIMS_MAX = 320
_THUMB_SIMPLIFY_SUBDIV = 1
_THUMB_CYCLES_SAMPLES = 16


class Params(NamedTuple):
    output_path: str


class Result(NamedTuple):
    status: str
    filepath: str | None = None
    message: str | None = None


# @include_begin: _template_backup_attrs.py
@contextlib.contextmanager
def _backup_attrs(obj: object, *names: str) -> Generator[dict[str, object], None, None]:
    yield {}
# @include_end


def main(params: Params) -> Result:
    import os
    import bpy  # pylint: disable=import-error,no-name-in-module

    # Resolve the output path inside the MCP scratch directory.
    output_path = os.path.join(bpy.app.tempdir, "blender_mcp", os.path.basename(params.output_path))

    scene = bpy.context.scene
    rd = scene.render

    with _backup_attrs(
        rd,
        "filepath",
        "resolution_x",
        "resolution_y",
        "resolution_percentage",
        "use_simplify",
        "simplify_subdivision_render",
    ) as orig:
        rd.filepath = output_path
        # Clamp the longest dimension to `_THUMB_DIMS_MAX`, keeping aspect ratio.
        res_x: int = orig["resolution_x"]  # type: ignore[assignment]
        res_y: int = orig["resolution_y"]  # type: ignore[assignment]
        if res_x >= res_y:
            rd.resolution_x = _THUMB_DIMS_MAX
            rd.resolution_y = max(int(res_y * _THUMB_DIMS_MAX / res_x), 1)
        else:
            rd.resolution_y = _THUMB_DIMS_MAX
            rd.resolution_x = max(int(res_x * _THUMB_DIMS_MAX / res_y), 1)
        rd.resolution_percentage = 100
        rd.use_simplify = True
        rd.simplify_subdivision_render = _THUMB_SIMPLIFY_SUBDIV

        if rd.engine == "CYCLES":
            with _backup_attrs(scene.cycles, "samples"):
                scene.cycles.samples = _THUMB_CYCLES_SAMPLES
                try:
                    bpy.ops.render.render(write_still=True)
                except RuntimeError as ex:
                    return Result(status="error", message=str(ex))
        else:
            try:
                bpy.ops.render.render(write_still=True)
            except RuntimeError as ex:
                return Result(status="error", message=str(ex))

    return Result(status="ok", filepath=output_path)
