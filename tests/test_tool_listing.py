# SPDX-FileCopyrightText: 2026 Blender Authors
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""
Verify the MCP server exposes expected tools.
"""

__all__ = ()

import asyncio
import os
import sys
import unittest

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

# Root of the repository.
_REPO_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# Complete expected tool listing.
# When a tool is added, changed, or removed this must be updated.
EXPECTED_TOOLS = [
    {
        "name": "execute_blender_code",
        "description": (
            "\nExecute Python code in the connected Blender instance.\n\n"
            "The code runs in Blender's Python environment with full access to ``bpy``.\n"
            "To return data, assign a JSON-serialisable dict to a variable named ``result``.\n"
        ),
        "inputSchema": {
            "properties": {
                "code": {
                    "title": "Code",
                    "type": "string",
                },
            },
            "required": ["code"],
            "title": "execute_blender_codeArguments",
            "type": "object",
        },
    },
    {
        "name": "execute_blender_code_for_cli",
        "description": (
            "\nExecute Python code in a background Blender process.\n\n"
            "Opens *blend_file* with ``blender --background`` and runs *code*.\n"
            "Assign a dict to ``result`` to return data.\n"
        ),
        "inputSchema": {
            "properties": {
                "blend_file": {
                    "title": "Blend File",
                    "type": "string",
                },
                "code": {
                    "title": "Code",
                    "type": "string",
                },
            },
            "required": ["blend_file", "code"],
            "title": "execute_blender_code_for_cliArguments",
            "type": "object",
        },
    },
    {
        "name": "get_blendfile_summary_datablocks",
        "description": (
            "\nReturn a summary of the blend file: data-block counts, "
            "active workspace, and render engine.\n"
        ),
        "inputSchema": {
            "properties": {},
            "title": "get_blendfile_summary_datablocksArguments",
            "type": "object",
        },
    },
    {
        "name": "get_blendfile_summary_datablocks_for_cli",
        "description": (
            "\nReturn a data-block summary by opening *blend_file* in background Blender.\n"
        ),
        "inputSchema": {
            "properties": {
                "blend_file": {
                    "title": "Blend File",
                    "type": "string",
                },
            },
            "required": ["blend_file"],
            "title": "get_blendfile_summary_datablocks_for_cliArguments",
            "type": "object",
        },
    },
    {
        "name": "get_blendfile_summary_missing_files",
        "description": (
            "\nReport external file references that are missing from disk\n"
            "(images, libraries, fonts, sounds, movie clips, caches, sequences).\n"
        ),
        "inputSchema": {
            "properties": {},
            "title": "get_blendfile_summary_missing_filesArguments",
            "type": "object",
        },
    },
    {
        "name": "get_blendfile_summary_missing_files_for_cli",
        "description": (
            "\nReport missing file references by opening *blend_file* in background Blender.\n"
        ),
        "inputSchema": {
            "properties": {
                "blend_file": {
                    "title": "Blend File",
                    "type": "string",
                },
            },
            "required": ["blend_file"],
            "title": "get_blendfile_summary_missing_files_for_cliArguments",
            "type": "object",
        },
    },
    {
        "name": "get_blendfile_summary_of_linked_libraries",
        "description": (
            "\nReturn a tree of directly and indirectly linked library files.\n"
        ),
        "inputSchema": {
            "properties": {},
            "title": "get_blendfile_summary_of_linked_librariesArguments",
            "type": "object",
        },
    },
    {
        "name": "get_blendfile_summary_of_linked_libraries_for_cli",
        "description": (
            "\nReturn linked-library info by opening *blend_file* in background Blender.\n"
        ),
        "inputSchema": {
            "properties": {
                "blend_file": {
                    "title": "Blend File",
                    "type": "string",
                },
            },
            "required": ["blend_file"],
            "title": "get_blendfile_summary_of_linked_libraries_for_cliArguments",
            "type": "object",
        },
    },
    {
        "name": "get_blendfile_summary_path_info",
        "description": (
            "\nSimple/fast access to the blend file's path, save status, age, and backups.\n"
        ),
        "inputSchema": {
            "properties": {},
            "title": "get_blendfile_summary_path_infoArguments",
            "type": "object",
        },
    },
    {
        "name": "get_blendfile_summary_path_info_for_cli",
        "description": (
            "\nReturn path info by opening *blend_file* in background Blender.\n"
        ),
        "inputSchema": {
            "properties": {
                "blend_file": {
                    "title": "Blend File",
                    "type": "string",
                },
            },
            "required": ["blend_file"],
            "title": "get_blendfile_summary_path_info_for_cliArguments",
            "type": "object",
        },
    },
    {
        "name": "get_blendfile_summary_usage_guess",
        "description": (
            "\nGuess the primary use-cases of the current blend file "
            "(scored 0-100 with certainty).\n"
        ),
        "inputSchema": {
            "properties": {},
            "title": "get_blendfile_summary_usage_guessArguments",
            "type": "object",
        },
    },
    {
        "name": "get_blendfile_summary_usage_guess_for_cli",
        "description": (
            "\nGuess use-cases by opening *blend_file* in background Blender.\n"
        ),
        "inputSchema": {
            "properties": {
                "blend_file": {
                    "title": "Blend File",
                    "type": "string",
                },
            },
            "required": ["blend_file"],
            "title": "get_blendfile_summary_usage_guess_for_cliArguments",
            "type": "object",
        },
    },
    {
        "name": "get_object_detail_summary",
        "description": (
            "\nReturn a structured summary of the object identified by *name*.\n\n"
            "Includes type, transforms, parent, children, modifiers, constraints,\n"
            "materials, visibility, data-block name, and collections.\n"
        ),
        "inputSchema": {
            "properties": {
                "name": {
                    "title": "Name",
                    "type": "string",
                },
            },
            "required": ["name"],
            "title": "get_object_detail_summaryArguments",
            "type": "object",
        },
    },
    {
        "name": "get_objects_summary",
        "description": (
            "\nReturn the scene's collection hierarchy and their objects.\n\n"
            "Each collection lists its objects (name, type, parent, data name,\n"
            "selection, visibility) and nested child collections.\n"
        ),
        "inputSchema": {
            "properties": {},
            "title": "get_objects_summaryArguments",
            "type": "object",
        },
    },
    {
        "name": "get_screenshot_of_window_as_image",
        "description": (
            "\nTake a screenshot of the entire Blender window and return it as a PNG image.\n"
        ),
        "inputSchema": {
            "properties": {},
            "title": "get_screenshot_of_window_as_imageArguments",
            "type": "object",
        },
    },
    {
        "name": "get_screenshot_of_window_as_json",
        "description": (
            "\nReturn a JSON description of the Blender window layout, "
            "areas, active object, and selection.\n"
        ),
        "inputSchema": {
            "properties": {},
            "title": "get_screenshot_of_window_as_jsonArguments",
            "type": "object",
        },
    },
    {
        "name": "jump_to_tab_by_name",
        "description": (
            "\nSwitch the active workspace tab to *name*.\n"
        ),
        "inputSchema": {
            "properties": {
                "name": {
                    "title": "Name",
                    "type": "string",
                },
            },
            "required": ["name"],
            "title": "jump_to_tab_by_nameArguments",
            "type": "object",
        },
    },
    {
        "name": "jump_to_tab_by_space_type",
        "description": (
            "\nSwitch to a workspace whose main area matches *space_type*.\n\n"
            "If *allow_edits* is True and no matching workspace exists, a new one\n"
            "is created by duplicating the current workspace.\n"
        ),
        "inputSchema": {
            "properties": {
                "allow_edits": {
                    "default": False,
                    "title": "Allow Edits",
                    "type": "boolean",
                },
                "space_type": {
                    "title": "Space Type",
                    "type": "string",
                },
            },
            "required": ["space_type"],
            "title": "jump_to_tab_by_space_typeArguments",
            "type": "object",
        },
    },
    {
        "name": "jump_to_view3d_object_by_name",
        "description": (
            "\nMove the 3D viewport to focus on an object by *name*.\n\n"
            "If *allow_edits* is True the object may be un-hidden and its\n"
            "collections enabled to make it visible.\n"
        ),
        "inputSchema": {
            "properties": {
                "allow_edits": {
                    "default": False,
                    "title": "Allow Edits",
                    "type": "boolean",
                },
                "name": {
                    "title": "Name",
                    "type": "string",
                },
            },
            "required": ["name"],
            "title": "jump_to_view3d_object_by_nameArguments",
            "type": "object",
        },
    },
    {
        "name": "jump_to_view3d_object_data_by_name",
        "description": (
            "\nMove the 3D viewport to the object whose data block matches *name*.\n\n"
            "If *allow_edits* is True the object may be un-hidden and its\n"
            "collections enabled to make it visible.\n"
        ),
        "inputSchema": {
            "properties": {
                "allow_edits": {
                    "default": False,
                    "title": "Allow Edits",
                    "type": "boolean",
                },
                "name": {
                    "title": "Name",
                    "type": "string",
                },
            },
            "required": ["name"],
            "title": "jump_to_view3d_object_data_by_nameArguments",
            "type": "object",
        },
    },
    {
        "name": "render_thumbnail_to_path",
        "description": (
            "\nRender a small, low-quality thumbnail to *output_path* "
            "(temporarily overrides settings).\n"
        ),
        "inputSchema": {
            "properties": {
                "output_path": {
                    "title": "Output Path",
                    "type": "string",
                },
            },
            "required": ["output_path"],
            "title": "render_thumbnail_to_pathArguments",
            "type": "object",
        },
    },
    {
        "name": "render_viewport_to_path",
        "description": (
            "\nRender the current scene to *output_path* using current render settings.\n"
        ),
        "inputSchema": {
            "properties": {
                "output_path": {
                    "title": "Output Path",
                    "type": "string",
                },
            },
            "required": ["output_path"],
            "title": "render_viewport_to_pathArguments",
            "type": "object",
        },
    },
]


def _list_tools() -> list[dict[str, object]]:
    """
    Start the MCP server and return the full tool listing.
    """
    async def _run() -> list[dict[str, object]]:
        env = os.environ.copy()
        env["PYTHONPATH"] = os.path.join(_REPO_DIR, "mcp")
        params = StdioServerParameters(
            command=sys.executable,
            args=["-m", "blmcp"],
            env=env,
        )
        async with stdio_client(params) as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()
                result = await session.list_tools()
                return [
                    {
                        "name": t.name,
                        "description": t.description,
                        "inputSchema": t.inputSchema,
                    }
                    for t in result.tools
                ]
    return asyncio.run(_run())


class TestToolListing(unittest.TestCase):

    _tools: list[dict[str, object]]

    @classmethod
    def setUpClass(cls) -> None:
        cls._tools = _list_tools()

    def test_tools_match_expected(self) -> None:
        self.assertEqual(self._tools, EXPECTED_TOOLS)


if __name__ == "__main__":
    unittest.main()
