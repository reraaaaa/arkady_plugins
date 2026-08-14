"""Mermaid Ink API rendering — shared by `md2docx.py` and `mermaid_converter.py`.

Lives in its own file (no `Tool` subclass) so both tool modules can import it
without violating the Dify SDK's "exactly one Tool subclass per source file"
rule. Loaded by sibling tools via `importlib.util.spec_from_file_location`
because the SDK's class loader does not add the source file's directory to
`sys.path` for relative imports.
"""

import base64
import json
import os
import zlib

import requests

# Public base URL of the Mermaid Ink service. Operators can override at runtime
# via the `MERMAID_INK_URL` env var (e.g. for self-hosted instances).
MERMAID_INK_URL = os.environ.get("MERMAID_INK_URL", "https://mermaid.ink")

PLUGIN_USER_AGENT = "arkady-md2docx/0.0.1"

# Per-attempt timeout for a single Mermaid Ink HTTP request. Kept in sync with
# the value used in `md2docx.py` (the Dify tool entry point also has its own
# budget constants for retries/total time, but the per-request ceiling lives
# here because the standalone Mermaid tool reuses the same call).
MERMAID_REQUEST_TIMEOUT_SECONDS = 30


def _encode_mermaid_pako(diagram: str) -> str:
    """Encode a Mermaid diagram in pako format for the mermaid.ink GET API.

    Wraps the diagram in {"code":"..."} JSON, deflates with zlib (level 9),
    then base64url-encodes without padding. Matches the format produced by
    the Mermaid Live Editor's share URL.
    """
    payload = json.dumps({"code": diagram}, separators=(",", ":"))
    compressed = zlib.compress(payload.encode("utf-8"), level=9)
    return base64.urlsafe_b64encode(compressed).decode("ascii").rstrip("=")


def render_mermaid_via_api(diagram: str, api_url: str | None = None) -> bytes:
    """Render a Mermaid diagram via the Mermaid Ink API. Returns PNG bytes.

    Uses the GET /img/pako:<zlib+base64url> endpoint. If `api_url` is provided
    it overrides the default (supporting self-hosted instances).
    Raises `requests.RequestException` on HTTP / network errors.
    """
    base_url = api_url or MERMAID_INK_URL
    encoded = _encode_mermaid_pako(diagram)
    resp = requests.get(
        f"{base_url}/img/pako:{encoded}",
        headers={"User-Agent": PLUGIN_USER_AGENT},
        timeout=MERMAID_REQUEST_TIMEOUT_SECONDS,
    )
    resp.raise_for_status()
    return resp.content
