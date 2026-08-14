"""Mermaid Converter — render a Mermaid diagram to a PNG image via Mermaid Ink API.

This is a standalone Dify Tool. It is split from `md2docx.py` because the Dify
SDK's class loader (`load_single_subclass_from_source`) requires exactly one
`Tool` subclass per source file.

The Mermaid HTTP helpers live in `_mermaid_render.py` and are loaded via
`importlib.util.spec_from_file_location` because the SDK's class loader does
not add the source file's directory to `sys.path`, which would break a plain
`from _mermaid_render import ...` (no parent directory registered, no package
name on the sibling module).
"""

import importlib.util
import re
from pathlib import Path
from typing import Generator

from arkady_plugin import Tool
from arkady_plugin.entities.tool import ToolInvokeMessage

# Path-based import of the shared Mermaid renderer. Sibling file in the same
# directory as this module — resolved relative to `__file__` so it works no
# matter what the host process's CWD or `sys.path` look like.
_RENDERER_PATH = Path(__file__).resolve().parent / "_mermaid_render.py"
_spec = importlib.util.spec_from_file_location("_mermaid_render", _RENDERER_PATH)
if _spec is None or _spec.loader is None:  # pragma: no cover - defensive
    raise ImportError(f"Failed to load shared Mermaid renderer from {_RENDERER_PATH}")
_mermaid_render = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_mermaid_render)

render_mermaid_via_api = _mermaid_render.render_mermaid_via_api


class MermaidConverterTool(Tool):
    """Dify Tool: render Mermaid diagram code to a PNG image."""

    def _invoke(self, parameters: dict) -> Generator[ToolInvokeMessage, None, None]:
        code = (parameters.get("mermaid_code") or "").strip()
        if not code:
            yield self.create_text_message("Error: mermaid_code is required")
            return

        # Strip code fences if present
        if code.startswith("```"):
            code = re.sub(r"^```mermaid\s*", "", code)
            code = re.sub(r"```$", "", code).strip()

        api_url = parameters.get("mermaid_api_url") or None

        try:
            png_bytes = render_mermaid_via_api(code, api_url=api_url)
        except Exception as e:
            yield self.create_text_message(f"Mermaid rendering failed: {e}")
            return

        yield self.create_blob_message(
            blob=png_bytes,
            meta={"mime_type": "image/png", "file_name": "diagram.png"},
        )
