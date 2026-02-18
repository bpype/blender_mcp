# SPDX-FileCopyrightText: 2026 Blender Authors
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""
Toolcode for rendering the current scene.
"""

__all__ = (
    "Params",
    "Result",
    "main",
)

import contextlib
from typing import Generator, NamedTuple


class Params(NamedTuple):
    output_path: str


class Result(NamedTuple):
    status: str
    filepath: str | None = None
    message: str | None = None


@contextlib.contextmanager
def _backup_attrs(obj: object, *names: str) -> Generator[dict[str, object], None, None]:
    """
    Context manager that saves named attributes on entry and restores them on exit.
    """
    saved = {name: getattr(obj, name) for name in names}
    try:
        yield saved
    finally:
        for name, value in saved.items():
            setattr(obj, name, value)


def main(params: Params) -> Result:
    import os
    import bpy  # pylint: disable=import-error,no-name-in-module

    # Resolve the output path inside the MCP scratch directory.
    output_path = os.path.join(bpy.app.tempdir, "blender_mcp", os.path.basename(params.output_path))

    scene = bpy.context.scene

    with _backup_attrs(scene.render, "filepath"):
        scene.render.filepath = output_path
        try:
            bpy.ops.render.render(write_still=True)
        except RuntimeError as ex:
            return Result(status="error", message=str(ex))

    return Result(status="ok", filepath=output_path)
