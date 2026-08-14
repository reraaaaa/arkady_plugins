"""
md2docx — Convert Markdown to DOCX with templates, Mermaid, and style presets.

Ported from mdocx-converter VS Code extension.
"""

import importlib.util
import os
import re
import io
import time
import shutil
import tempfile
import zipfile
import threading
from pathlib import Path
from typing import Optional, Any, Generator

# ── Dify SDK (must import first — triggers gevent monkey-patch) ──
from arkady_plugin import Tool
from arkady_plugin.entities.tool import ToolInvokeMessage

# ── Third-party imports (safe now — gevent has patched stdlib) ──
import requests
import pypandoc
from docx import Document
from docx.shared import Cm
from docx.oxml.ns import qn
from lxml import etree

# Load the shared Mermaid renderer from its sibling file. The Dify SDK loads
# this module via `importlib.util.spec_from_file_location`, which sets
# `__file__` but does NOT add the parent directory to `sys.path`, so a plain
# `from _mermaid_render import ...` would fail at plugin launch.
_RENDERER_PATH = Path(__file__).resolve().parent / "_mermaid_render.py"
_spec = importlib.util.spec_from_file_location("_mermaid_render", _RENDERER_PATH)
if _spec is None or _spec.loader is None:  # pragma: no cover - defensive
    raise ImportError(f"Failed to load shared Mermaid renderer from {_RENDERER_PATH}")
_mermaid_render = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_mermaid_render)

render_mermaid_via_api = _mermaid_render.render_mermaid_via_api
MERMAID_INK_URL = _mermaid_render.MERMAID_INK_URL

# ── Tunables ────────────────────────────────────────────────

# Maximum size of markdown_content (UTF-8 bytes). Larger inputs are rejected
# with a structured error to prevent OOM in the Dify plugin sandbox.
MAX_MARKDOWN_BYTES = 5 * 1024 * 1024  # 5 MB

# Total wall-clock budget for Mermaid rendering across all diagrams. Diagrams
# still running after this are cancelled and reported as timed-out.
MERMAID_TOTAL_BUDGET_SECONDS = 120

# Per-attempt timeout for a single Mermaid Ink request.
MERMAID_REQUEST_TIMEOUT_SECONDS = 30

# Number of retry attempts for a single Mermaid Ink request (1 initial + N retries).
MERMAID_MAX_ATTEMPTS = 3

# ── Regex ───────────────────────────────────────────────────

MERMAID_BLOCK_RE = re.compile(r"(?m)^```mermaid[^\n]*\n([\s\S]*?)\n^```", re.IGNORECASE)
CJK_CHAR_RE = re.compile(r"[㐀-䶿一-鿿豈-﫿]")
LATIN_CHAR_RE = re.compile(r"[A-Za-z]")

# ── Profile defaults (ported from getProfileDocxDefaults) ───

PROFILE_DEFAULTS: dict[str, dict[str, Any]] = {
    "academic": {
        "body_font": "SimSun",
        "body_size_pt": 12,
        "heading1_font": "SimHei",
        "heading1_size_pt": 16,
        "heading2_font": "SimHei",
        "heading2_size_pt": 14,
        "heading3_font": "SimHei",
        "heading3_size_pt": 12,
        "line_spacing": 1.5,
        "margin_top_mm": 25.4,
        "margin_bottom_mm": 25.4,
        "margin_left_mm": 25.4,
        "margin_right_mm": 25.4,
    },
    "business": {
        "body_font": "Arial",
        "body_size_pt": 11,
        "heading1_font": "Arial",
        "heading1_size_pt": 18,
        "heading2_font": "Arial",
        "heading2_size_pt": 14,
        "heading3_font": "Arial",
        "heading3_size_pt": 12,
        "line_spacing": 1.5,
        "margin_top_mm": 25.4,
        "margin_bottom_mm": 25.4,
        "margin_left_mm": 25.4,
        "margin_right_mm": 25.4,
    },
    "technical": {
        "body_font": "Arial",
        "body_size_pt": 11,
        "heading1_font": "Arial",
        "heading1_size_pt": 16,
        "heading2_font": "Arial",
        "heading2_size_pt": 14,
        "heading3_font": "Arial",
        "heading3_size_pt": 12,
        "line_spacing": 1.35,
        "margin_top_mm": 19,
        "margin_bottom_mm": 19,
        "margin_left_mm": 19,
        "margin_right_mm": 19,
    },
    "official": {
        "body_font": "FangSong",
        "body_size_pt": 16,
        "heading1_font": "SimHei",
        "heading1_size_pt": 16,
        "heading2_font": "KaiTi",
        "heading2_size_pt": 16,
        "heading3_font": "FangSong",
        "heading3_size_pt": 16,
        "line_spacing": 1.75,
        "margin_top_mm": 37,
        "margin_bottom_mm": 35,
        "margin_left_mm": 28,
        "margin_right_mm": 26,
    },
    "thesis": {
        "body_font": "SimSun",
        "body_size_pt": 12,
        "heading1_font": "SimHei",
        "heading1_size_pt": 22,
        "heading2_font": "SimHei",
        "heading2_size_pt": 16,
        "heading3_font": "SimHei",
        "heading3_size_pt": 14,
        "line_spacing": 1.5,
        "margin_top_mm": 30,
        "margin_bottom_mm": 30,
        "margin_left_mm": 30,
        "margin_right_mm": 30,
    },
    # ГОСТ Р 7.0.97-2016: п. 3.4 (абзацный отступ 1,25 см, интервал 1-1.5,
    # задаётся в самом reference_gost.docx — apply_style_overrides не трогает
    # first_line_indent), п. 3.2/3.5 (поля 20/10/20/20 мм лево/право/верх/низ).
    "gost": {
        "body_font": "Times New Roman",
        "body_size_pt": 12,
        "heading1_font": "Times New Roman",
        "heading1_size_pt": 16,
        "heading2_font": "Times New Roman",
        "heading2_size_pt": 14,
        "heading3_font": "Times New Roman",
        "heading3_size_pt": 12,
        "line_spacing": 1.5,
        "margin_top_mm": 20,
        "margin_bottom_mm": 20,
        "margin_left_mm": 20,
        "margin_right_mm": 10,
    },
    "template": {},
}

# ── Pandoc metadata per profile (ported from STYLE_PROFILE_METADATA) ──

PROFILE_METADATA: dict[str, dict[str, str]] = {
    "template": {},
    "academic": {
        "mainfont": "Times New Roman",
        "CJKmainfont": "SimSun",
        "fontsize": "12pt",
        "linestretch": "1.5",
    },
    "business": {
        "mainfont": "Arial",
        "CJKmainfont": "Microsoft YaHei",
        "fontsize": "11pt",
        "linestretch": "1.5",
    },
    "technical": {
        "mainfont": "Arial",
        "CJKmainfont": "Microsoft YaHei",
        "monofont": "Consolas",
        "fontsize": "11pt",
        "linestretch": "1.35",
    },
    "official": {
        "mainfont": "Times New Roman",
        "CJKmainfont": "FangSong",
        "fontsize": "16pt",
        "linestretch": "1.75",
    },
    "thesis": {
        "mainfont": "Times New Roman",
        "CJKmainfont": "SimSun",
        "fontsize": "12pt",
        "linestretch": "1.5",
    },
    "gost": {
        "mainfont": "Times New Roman",
        "fontsize": "12pt",
        "linestretch": "1.5",
    },
}

# ── Bundled template mapping ─────────────────────────────────

TEMPLATE_MAP: dict[str, dict[str, str]] = {
    "academic": {
        "english": "reference_english_academic.docx",
        "chinese": "reference_chinese_academic.docx",
    },
    "template": {
        "english": "reference_english_academic.docx",
        "chinese": "reference_chinese_academic.docx",
    },
    "technical": {
        "english": "reference_english_technical.docx",
        "chinese": "reference_chinese_technical.docx",
    },
    "business": {
        "english": "reference_english_business.docx",
        "chinese": "reference_chinese_business.docx",
    },
    "official": {
        "english": "reference_english_official.docx",
        "chinese": "reference_chinese_official.docx",
    },
    "thesis": {
        "english": "reference_english_academic.docx",
        "chinese": "reference_chinese_academic.docx",
    },
    "gost": {
        "english": "reference_gost.docx",
        "chinese": "reference_gost.docx",
    },
}

VALID_PROFILES = {"template", "academic", "business", "technical", "official", "thesis", "gost"}

# Style name aliases used by some reference.docx templates
NORMAL_STYLE_NAMES = ("Normal", "a", "a1", "Text", "BodyText", "Body Text",
                       "FirstParagraph", "Compact")
HEADING_ALIASES = {
    "Heading 1": ("Heading 1", "1"),
    "Heading 2": ("Heading 2", "2", "21"),
    "Heading 3": ("Heading 3", "3", "31"),
}
CODE_STYLE_NAMES = ("SourceCode", "VerbatimChar", "Code")


# ── Language detection ───────────────────────────────────────

def detect_language(markdown_text: str) -> str:
    """Return 'chinese' or 'english' based on CJK character count."""
    sample = markdown_text[:20000]
    cjk_count = len(CJK_CHAR_RE.findall(sample))
    latin_count = len(LATIN_CHAR_RE.findall(sample))

    if cjk_count >= 40 or cjk_count > latin_count * 0.15:
        return "chinese"
    return "english"


def resolve_language(setting: str, markdown_text: str) -> str:
    """Resolve the reference language from the user setting and markdown content."""
    if setting in ("english", "chinese"):
        return setting
    return detect_language(markdown_text)


# ── Template resolution ──────────────────────────────────────

def resolve_template(
    style_profile: str,
    reference_language: str,
    custom_template_path: Optional[str],
    plugin_root: str,
) -> str:
    """Return path to the reference.docx to use.

    Priority: custom_template > built-in template.
    """
    if custom_template_path and os.path.exists(custom_template_path):
        return custom_template_path

    profile = style_profile if style_profile in VALID_PROFILES else "template"
    lang = reference_language if reference_language in ("english", "chinese") else "english"

    filename = TEMPLATE_MAP[profile][lang]
    template_path = os.path.join(plugin_root, "multi-templates", filename)

    if os.path.exists(template_path):
        return template_path

    raise FileNotFoundError(
        f"Built-in template {filename} not found in multi-templates/. "
        f"Profile={profile}, language={lang}"
    )


# ── Settings normalization ───────────────────────────────────

def normalize_profile(value: Optional[str]) -> str:
    """Normalize style profile to a valid value."""
    if value in VALID_PROFILES:
        return value
    return "template"


def parse_pt(value) -> Optional[float]:
    """Parse a pt value, return None if 0, negative, or non-numeric."""
    if value is None:
        return None
    # Guard against bool (subclass of int): float(True) == 1.0
    if isinstance(value, bool):
        return None
    try:
        v = float(value)
        return v if v > 0 else None
    except (TypeError, ValueError):
        return None


def parse_spacing(value) -> Optional[float]:
    """Parse line spacing, return None if 0 or invalid."""
    return parse_pt(value)


def parse_mm(value) -> Optional[float]:
    """Parse mm value, return None if 0 or invalid."""
    return parse_pt(value)


def mm_to_twips(mm: float) -> int:
    """Convert millimeters to twips (1 mm ≈ 56.69 twips)."""
    return round(mm * 56.6929133858)


# ── Title sanitization ───────────────────────────────────────

_FILENAME_BAD_CHARS_RE = re.compile(r'[<>:"/\\|?*\x00-\x1f]')


def sanitize_filename(name: str) -> str:
    """Replace characters illegal in filenames with underscores."""
    return _FILENAME_BAD_CHARS_RE.sub("_", name).strip() or "Document"


# ── Mermaid preprocessing ────────────────────────────────────

# `render_mermaid_via_api` and `MERMAID_INK_URL` are re-exported at the top of
# this module from the shared `src/_mermaid_render.py` file. See the loader
# comment above for why a path-based import is needed.


def _render_one_with_retry(index: int, diagram: str, temp_dir: str,
                            errors: list[str],
                            api_url: str | None = None) -> tuple[int, str | None]:
    """Render one Mermaid diagram with exponential-backoff retries.

    On final failure, records the error in `errors` and returns (index, None).
    """
    last_err: Exception | None = None
    for attempt in range(MERMAID_MAX_ATTEMPTS):
        try:
            png_bytes = render_mermaid_via_api(diagram, api_url=api_url)
            png_path = os.path.join(temp_dir, f"diagram-{index}.png")
            with open(png_path, "wb") as f:
                f.write(png_bytes)
            return index, png_path
        except Exception as e:  # requests.RequestException, OSError, etc.
            last_err = e
            if attempt < MERMAID_MAX_ATTEMPTS - 1:
                # 1s, 2s, 4s, ...
                time.sleep(1 * (2 ** attempt))
    errors.append(f"Diagram {index}: {last_err}")
    return index, None


def preprocess_mermaid(markdown_text: str, enabled: bool = True,
                       api_url: str | None = None) -> tuple[str, int, str, list[str]]:
    """Extract ```mermaid blocks, render to PNGs via API, replace with image refs.

    Returns (processed_markdown, mermaid_count, temp_dir, errors).
    Caller must clean up temp_dir via shutil.rmtree after pandoc conversion.

    Total wall-clock time is bounded by MERMAID_TOTAL_BUDGET_SECONDS. Diagrams
    still running after the budget are cancelled and reported as failed.
    """
    if not enabled:
        return markdown_text, 0, "", []

    matches = list(MERMAID_BLOCK_RE.finditer(markdown_text))
    if not matches:
        return markdown_text, 0, "", []

    temp_dir = tempfile.mkdtemp(prefix="mermaid-")
    errors: list[str] = []

    # Build segments interleaving non-mermaid text with mermaid-block markers.
    # The diagram index in the 4th slot is 0 for non-mermaid segments.
    segments: list[tuple[int, int, bool, int]] = []
    last_end = 0
    for i, match in enumerate(matches, 1):
        if match.start() > last_end:
            segments.append((last_end, match.start(), False, 0))
        segments.append((match.start(), match.end(), True, i))
        last_end = match.end()
    if last_end < len(markdown_text):
        segments.append((last_end, len(markdown_text), False, 0))

    # Render diagrams sequentially with retry (safe in gevent-patched envs)
    results: dict[int, str | None] = {}
    for idx, match in enumerate(matches, 1):
        _, png_path = _render_one_with_retry(idx, match.group(1).strip(), temp_dir, errors, api_url=api_url)
        results[idx] = png_path

    # Assemble output preserving original order
    parts: list[str] = []
    count = 0
    for start, end, is_mermaid, idx in segments:
        if is_mermaid:
            original_text = markdown_text[start:end]
            png_path = results.get(idx)
            if png_path is not None:
                parts.append(f"![Mermaid Diagram {idx}](<{png_path}>)\n\n")
                count += 1
            else:
                parts.append(original_text + "\n\n")
        else:
            parts.append(markdown_text[start:end])

    return "".join(parts), count, temp_dir, errors


# ── Pandoc conversion ────────────────────────────────────────

_pandoc_lock = threading.Lock()


def _ensure_pandoc() -> None:
    """Check for pandoc. With pypandoc-binary the binary is pre-installed."""
    pypandoc.get_pandoc_version()


# Note: pandoc warmup is intentionally skipped at import time.
# In a gevent-patched environment (LOAD_FROM_DIFY_PLUGIN=1), spawning a
# subprocess before Plugin.run() starts the event loop can deadlock on
# gevent-intercepted I/O. The first real conversion pays the cold-start
# cost (~0.1s) instead.


def build_pandoc_metadata(
    style_profile: str,
    body_font: Optional[str],
    body_size_pt: Optional[float],
    line_spacing: Optional[float],
    document_title: Optional[str] = None,
    subtitle: Optional[str] = None,
) -> dict[str, str]:
    """Build the pandoc --metadata dict, layering profile defaults + user overrides."""
    metadata = dict(PROFILE_METADATA.get(style_profile, {}))

    if body_font and body_font.strip():
        metadata["mainfont"] = body_font.strip()
        metadata["CJKmainfont"] = body_font.strip()
    if body_size_pt:
        metadata["fontsize"] = f"{body_size_pt}pt"
    if line_spacing:
        metadata["linestretch"] = str(line_spacing)
    # Pandoc's docx writer renders a title page (paragraphs styled "Title" /
    # "Subtitle", both present in the reference-doc's built-in styles) only
    # when this metadata is set — no markdown syntax needed for it.
    if document_title and document_title.strip():
        metadata["title"] = document_title.strip()
    if subtitle and subtitle.strip():
        metadata["subtitle"] = subtitle.strip()

    return {k: v for k, v in metadata.items() if v}


def _map_pandoc_error(message: str) -> str:
    """Map raw pandoc errors to user-friendly guidance."""
    msg_lower = message.lower()
    if any(kw in msg_lower for kw in ("permission denied", "access is denied", "eperm", "eacces")):
        return "Pandoc could not write the output file. Close the target DOCX in Word and try again."
    # Image-related errors: use specific phrases (not bare "image") to avoid
    # false positives on other pandoc messages that mention "image format" etc.
    if any(kw in msg_lower for kw in (
        "cannot decode image",
        "could not fetch resource",
        "could not find image",
        "image not found",
    )):
        return "Pandoc could not resolve one or more images. Check that all image paths in the Markdown are valid and accessible."
    if any(kw in msg_lower for kw in ("unknown reader", "unknown extension", "mermaid")):
        return "Pandoc encountered syntax it could not handle. Check for unsupported Markdown constructs or malformed Mermaid blocks."
    if any(kw in msg_lower for kw in ("not a valid docx", "reference docx", "could not read")):
        return "Pandoc could not read the reference template. The uploaded .docx may be corrupted or not in the expected format."
    return f"Pandoc conversion failed: {message}"


# A raw OOXML block (needs the `raw_attribute` extension on the *reader*
# side) is the only reliable way to force a real Word page break from
# Pandoc markdown — the LaTeX `\newpage` command is silently left as literal
# text by the docx writer, it isn't converted at all.
_OOXML_PAGE_BREAK = '\n\n```{=openxml}\n<w:p><w:r><w:br w:type="page"/></w:r></w:p>\n```\n\n'


def convert_via_pandoc(
    markdown_text: str,
    reference_docx: str,
    source_dir: str,
    mermaid_dir: str,
    metadata: dict[str, str],
    include_toc: bool = False,
    toc_depth: int = 3,
    page_break_after_front_matter: bool = False,
) -> io.BytesIO:
    """Run pandoc to convert markdown to DOCX. Returns BytesIO of the docx content.

    pypandoc requires `outputfile=<path>` for binary targets like docx (it
    cannot return the bytes directly). We write to a private temp file and
    read it back into a BytesIO.
    """
    _ensure_pandoc()

    if page_break_after_front_matter:
        # Pandoc auto-inserts the --toc block (and the title/subtitle from
        # --metadata) *before* the body content regardless of where this
        # marker sits in markdown_text, so prepending it here lands the
        # break right after title+TOC, separating them from chapter 1 —
        # confirmed by inspecting the generated document.xml byte offsets.
        markdown_text = _OOXML_PAGE_BREAK + markdown_text

    # `+footnotes` enables Pandoc's Markdown footnote syntax ([^1] / [^1]: ...)
    # on top of GFM — without it, footnote markers pass through as literal
    # text instead of becoming real Word footnotes. GFM alone doesn't include
    # this extension (it's Pandoc's own Markdown dialect feature, not GitHub's).
    # `+raw_attribute` enables the ```{=openxml} ... ``` raw-block syntax used
    # above for page breaks.
    pandoc_format = "gfm+footnotes+raw_html+raw_attribute"

    # Combine reference-docx dir and mermaid temp dir in resource-path
    resource_path = source_dir
    if mermaid_dir:
        resource_path = f"{mermaid_dir}{os.pathsep}{resource_path}"

    extra_args = [
        "--from", pandoc_format,
        "--to", "docx",
        "--reference-doc", reference_docx,
        "--resource-path", resource_path,
    ]

    if include_toc:
        extra_args.extend(["--toc", f"--toc-depth={toc_depth}"])

    for key, value in metadata.items():
        extra_args.extend(["--metadata", f"{key}={value}"])

    fd, out_path = tempfile.mkstemp(suffix=".docx", prefix="pandoc-")
    os.close(fd)
    try:
        try:
            pypandoc.convert_text(
                markdown_text,
                "docx",
                format=pandoc_format,
                extra_args=extra_args,
                outputfile=out_path,
            )
        except Exception as e:
            raise RuntimeError(_map_pandoc_error(str(e))) from e

        with open(out_path, "rb") as f:
            raw_bytes = f.read()
        # Strip dangling image/oleObject relationships from the pandoc output
        # so that downstream python-docx consumers can open the document
        # without choking on references inherited from the reference template.
        return io.BytesIO(_strip_dangling_image_rels(raw_bytes))
    finally:
        try:
            os.unlink(out_path)
        except OSError:
            pass


# ── DOCX post-processing ──────────────────────────────────────────

def _strip_dangling_image_rels(docx_bytes):
    """Remove image/oleObject relationships from word/_rels/document.xml.rels
    that have no corresponding part in the zip.

    Some bundled reference templates declare image relationships whose target
    files are missing. Pandoc copies those relationships into its output and
    python-docx then refuses to open the document. This function cleans them
    up so the produced DOCX is openable.

    Returns the cleaned bytes (input returned unchanged on any read/write error).
    """
    try:
        with zipfile.ZipFile(io.BytesIO(docx_bytes)) as zin:
            names = set(zin.namelist())
            rels_path = "word/_rels/document.xml.rels"
            if rels_path not in names:
                return docx_bytes
            rels_xml = zin.read(rels_path).decode("utf-8")
            root = etree.fromstring(rels_xml.encode("utf-8"))
            removed = 0
            for rel in list(root):
                rtype = rel.get("Type", "")
                if not rtype.endswith("/image") and not rtype.endswith("/oleObject"):
                    continue
                target = rel.get("Target", "")
                if not target:
                    continue
                # Targets in document.xml.rels are relative to word/, so
                # "media/image1.wmf" resolves to "word/media/image1.wmf".
                normalized = target.replace("\\", "/").lstrip("/")
                if normalized.startswith("word/"):
                    part_name = normalized
                else:
                    part_name = "word/" + normalized
                if part_name not in names:
                    root.remove(rel)
                    removed += 1
            if removed == 0:
                return docx_bytes
            new_rels = etree.tostring(
                root, xml_declaration=True, encoding="UTF-8", standalone=True
            )
            out_buf = io.BytesIO()
            with zipfile.ZipFile(out_buf, "w", zipfile.ZIP_DEFLATED) as zout:
                for item in zin.infolist():
                    data = zin.read(item.filename)
                    if item.filename == rels_path:
                        data = new_rels
                    zout.writestr(item, data)
            return out_buf.getvalue()
    except (zipfile.BadZipFile, etree.XMLSyntaxError, KeyError, OSError):
        return docx_bytes


# ── DOCX style overrides ─────────────────────────────────────

def _set_font(run_or_style, font_name: str) -> None:
    """Set the font on a run or style element, including east-asia."""
    rPr = run_or_style._element.get_or_add_rPr()
    rFonts = rPr.find(qn("w:rFonts"))
    if rFonts is None:
        rFonts = etree.SubElement(rPr, qn("w:rFonts"))
    rFonts.set(qn("w:ascii"), font_name)
    rFonts.set(qn("w:hAnsi"), font_name)
    rFonts.set(qn("w:eastAsia"), font_name)


def _set_font_size(run_or_style, size_pt: float) -> None:
    """Set font size on a run or style element."""
    rPr = run_or_style._element.get_or_add_rPr()
    sz = rPr.find(qn("w:sz"))
    if sz is None:
        sz = etree.SubElement(rPr, qn("w:sz"))
    half_pts = str(int(round(size_pt * 2)))
    sz.set(qn("w:val"), half_pts)


def _set_line_spacing(paragraph_format, spacing: float) -> None:
    """Set line spacing on a paragraph format."""
    line_value = int(round(spacing * 240))
    pPr = paragraph_format._element.get_or_add_pPr()
    spacing_el = pPr.find(qn("w:spacing"))
    if spacing_el is None:
        spacing_el = etree.SubElement(pPr, qn("w:spacing"))
    spacing_el.set(qn("w:line"), str(line_value))
    spacing_el.set(qn("w:lineRule"), "auto")


def _set_shading(paragraph_format, fill_color: str) -> None:
    """Set paragraph shading (background color)."""
    pPr = paragraph_format._element.get_or_add_pPr()
    shd = pPr.find(qn("w:shd"))
    if shd is None:
        shd = etree.SubElement(pPr, qn("w:shd"))
    shd.set(qn("w:val"), "clear")
    shd.set(qn("w:color"), "auto")
    shd.set(qn("w:fill"), fill_color)


def _set_font_color(run_or_style, color_hex: str) -> None:
    """Set text color on a run or style."""
    rPr = run_or_style._element.get_or_add_rPr()
    color = rPr.find(qn("w:color"))
    if color is None:
        color = etree.SubElement(rPr, qn("w:color"))
    color.set(qn("w:val"), color_hex)


def _apply_to_styles(doc: Document, names: tuple[str, ...], *, font=None, size=None,
                     color=None, line_spacing=None) -> bool:
    """Apply font/size/color/line_spacing to matching style names. Returns True
    if at least one style was found and modified.
    """
    matched = False
    for name in names:
        try:
            style = doc.styles[name]
            matched = True
            if font:
                _set_font(style, font)
            if size:
                _set_font_size(style, size)
            if color:
                _set_font_color(style, color)
            if line_spacing:
                _set_line_spacing(style.paragraph_format, line_spacing)
        except KeyError:
            pass
    return matched


def apply_style_overrides(doc: Document, style_profile: str, params: dict) -> list[str]:
    """Apply font/size/spacing overrides to Normal and Heading styles.

    Returns a list of human-readable warnings when a non-template profile
    requests overrides but the reference document does not contain the
    expected style names. Empty list on full success.
    """
    profile = PROFILE_DEFAULTS.get(style_profile, {})
    warnings: list[str] = []

    # Resolve effective values: user param > profile default > None (skip)
    body_font = params.get("body_font") or profile.get("body_font")
    body_size = parse_pt(params.get("body_size_pt")) or profile.get("body_size_pt")
    line_spacing = parse_spacing(params.get("line_spacing")) or profile.get("line_spacing")

    h1_font = params.get("heading1_font") or profile.get("heading1_font")
    h1_size = parse_pt(params.get("heading1_size_pt")) or profile.get("heading1_size_pt")
    h2_font = params.get("heading2_font") or profile.get("heading2_font")
    h2_size = parse_pt(params.get("heading2_size_pt")) or profile.get("heading2_size_pt")
    h3_font = params.get("heading3_font") or profile.get("heading3_font")
    h3_size = parse_pt(params.get("heading3_size_pt")) or profile.get("heading3_size_pt")

    # Normal style + aliases (BodyText, Compact, etc.)
    effective_color = "000000" if style_profile != "template" else None
    if not _apply_to_styles(doc, NORMAL_STYLE_NAMES, font=body_font, size=body_size,
                             color=effective_color, line_spacing=line_spacing):
        if style_profile != "template":
            warnings.append(
                f"None of the body style names {NORMAL_STYLE_NAMES} were found in the "
                f"reference template; body font/size/spacing overrides were not applied."
            )

    # Heading styles + aliases
    if not _apply_to_styles(doc, HEADING_ALIASES["Heading 1"], font=h1_font, size=h1_size,
                             color=effective_color):
        if style_profile != "template":
            warnings.append(
                f"Heading 1 style not found in reference template; heading 1 overrides were not applied."
            )
    if not _apply_to_styles(doc, HEADING_ALIASES["Heading 2"], font=h2_font, size=h2_size,
                             color=effective_color):
        if style_profile != "template":
            warnings.append(
                f"Heading 2 style not found in reference template; heading 2 overrides were not applied."
            )
    if not _apply_to_styles(doc, HEADING_ALIASES["Heading 3"], font=h3_font, size=h3_size,
                             color=effective_color):
        if style_profile != "template":
            warnings.append(
                f"Heading 3 style not found in reference template; heading 3 overrides were not applied."
            )

    # Technical profile: code styles
    if style_profile == "technical":
        any_code_style = False
        for code_style_name in CODE_STYLE_NAMES:
            try:
                cs = doc.styles[code_style_name]
                any_code_style = True
                _set_font(cs, "Consolas")
                _set_font_size(cs, 10)
                _set_font_color(cs, "000000")
                _set_shading(cs.paragraph_format, "F3F4F6")
            except KeyError:
                pass
        if not any_code_style:
            warnings.append(
                f"Technical profile: no code style ({CODE_STYLE_NAMES}) found in reference template."
            )

    # Page margins: user override > profile default > skip
    margin_top = parse_mm(params.get("margin_top_mm")) or profile.get("margin_top_mm")
    margin_bottom = parse_mm(params.get("margin_bottom_mm")) or profile.get("margin_bottom_mm")
    margin_left = parse_mm(params.get("margin_left_mm")) or profile.get("margin_left_mm")
    margin_right = parse_mm(params.get("margin_right_mm")) or profile.get("margin_right_mm")

    if any([margin_top, margin_bottom, margin_left, margin_right]):
        for section in doc.sections:
            if margin_top:
                section.top_margin = Cm(margin_top / 10)
            if margin_bottom:
                section.bottom_margin = Cm(margin_bottom / 10)
            if margin_left:
                section.left_margin = Cm(margin_left / 10)
            if margin_right:
                section.right_margin = Cm(margin_right / 10)

    return warnings


# ── Dify Tool entry point ────────────────────────────────────

# Characters that can appear in "falsy" string representations
_FALSY_STRINGS = frozenset({"false", "0", "no", "off", "disabled", "n", ""})


def _coerce_bool(value) -> bool:
    """Coerce a value to bool, handling Dify string-form booleans."""
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value.strip().lower() not in _FALSY_STRINGS
    return bool(value)


class Md2DocxTool(Tool):
    """Dify Tool: convert Markdown to DOCX."""

    def _invoke(
        self, parameters: dict
    ) -> Generator[ToolInvokeMessage, None, None]:
        custom_template_path = None
        mermaid_dir = ""
        stage = "start"
        warnings: list[str] = []

        try:
            markdown_content = parameters.get("markdown_content") or ""
            if not markdown_content.strip():
                yield self.create_json_message({"status": "error", "stage": "validation", "message": "markdown_content is empty"})
                yield self.create_text_message(
                    "Error: markdown_content is empty. Please provide Markdown text to convert."
                )
                return

            # Reject oversized inputs to avoid OOM in the Dify plugin sandbox.
            markdown_bytes_len = len(markdown_content.encode("utf-8"))
            if markdown_bytes_len > MAX_MARKDOWN_BYTES:
                size_mb = MAX_MARKDOWN_BYTES // (1024 * 1024)
                msg = (
                    f"markdown_content is {markdown_bytes_len} bytes, exceeds the "
                    f"{size_mb}MB limit. Split the document or raise the limit."
                )
                yield self.create_json_message({"status": "error", "stage": "validation", "message": msg})
                yield self.create_text_message(f"Error: {msg}")
                return

            stage = "validation"
            raw_title = parameters.get("title") or "Document"
            title = sanitize_filename(raw_title)
            style_profile = normalize_profile(parameters.get("style_profile"))
            language_setting = parameters.get("reference_language", "auto")
            mermaid_enabled = _coerce_bool(parameters.get("mermaid_enabled", True))
            include_toc = _coerce_bool(parameters.get("include_toc", False))
            include_title_page = _coerce_bool(parameters.get("include_title_page", False))
            subtitle = parameters.get("subtitle") or ""

            # Resolve language
            stage = "language_detection"
            reference_language = resolve_language(language_setting, markdown_content)

            # Resolve template
            stage = "template_resolution"
            custom_template = parameters.get("custom_template")
            if custom_template:
                fd, custom_template_path = tempfile.mkstemp(suffix=".docx", prefix="custom-template-")
                os.close(fd)
                try:
                    if isinstance(custom_template, (bytes, bytearray)):
                        with open(custom_template_path, "wb") as f:
                            f.write(custom_template)
                    elif isinstance(custom_template, str):
                        # DOCX is a binary zip; a plain str cannot be safely
                        # decoded back to its original bytes. Reject it with
                        # a clear warning rather than silently producing a
                        # corrupted file.
                        os.unlink(custom_template_path)
                        custom_template_path = None
                        warnings.append(
                            "custom_template: received a string, expected raw bytes. "
                            "The custom template was ignored; the built-in template is used."
                        )
                    else:
                        os.unlink(custom_template_path)
                        custom_template_path = None
                        warnings.append(
                            f"custom_template: unsupported type {type(custom_template).__name__}; "
                            "the custom template was ignored."
                        )
                except Exception as e:
                    # Clean up partial file and continue without custom template
                    if os.path.exists(custom_template_path):
                        try:
                            os.unlink(custom_template_path)
                        except OSError:
                            pass
                    custom_template_path = None
                    warnings.append(f"custom_template: failed to write temp file ({e}); ignored.")

            plugin_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
            reference_docx = resolve_template(
                style_profile, reference_language, custom_template_path, plugin_root
            )

            # Mermaid preprocessing
            stage = "mermaid_preprocessing"
            mermaid_api_url = parameters.get("mermaid_api_url") or None
            processed_md, mermaid_count, mermaid_dir, mermaid_errors = preprocess_mermaid(
                markdown_content, enabled=mermaid_enabled, api_url=mermaid_api_url
            )
            warnings.extend(mermaid_errors)

            # Pandoc metadata
            metadata = build_pandoc_metadata(
                style_profile,
                parameters.get("body_font"),
                parse_pt(parameters.get("body_size_pt")),
                parse_spacing(parameters.get("line_spacing")),
                document_title=raw_title if include_title_page else None,
                subtitle=subtitle if include_title_page else None,
            )

            # Convert via pandoc
            stage = "pandoc_conversion"
            source_dir = os.path.dirname(reference_docx)
            docx_io = convert_via_pandoc(
                processed_md, reference_docx, source_dir, mermaid_dir, metadata,
                include_toc=include_toc,
                page_break_after_front_matter=include_title_page or include_toc,
            )

            # Apply style overrides
            stage = "style_overrides"
            doc = Document(docx_io)
            style_warnings = apply_style_overrides(doc, style_profile, parameters)
            warnings.extend(style_warnings)

            # Save to BytesIO (and strip any dangling media rels that python-docx
            # may have re-introduced on round-trip)
            output_io = io.BytesIO()
            doc.save(output_io)
            docx_bytes = _strip_dangling_image_rels(output_io.getvalue())

            # Messages
            size_kb = len(docx_bytes) / 1024
            summary_parts = [
                f"DOCX generated: {title}.docx ({size_kb:.1f} KB)",
                f"Style: {style_profile} | Language: {reference_language}",
            ]
            if mermaid_count > 0:
                summary_parts.append(f"Mermaid diagrams rendered: {mermaid_count}")
            if mermaid_errors:
                failed = len(mermaid_errors)
                summary_parts.append(
                    f"Warning: {failed} Mermaid diagram(s) failed to render and were kept as code blocks."
                )

            yield self.create_text_message("\n".join(summary_parts))
            if warnings:
                yield self.create_json_message({"warning": warnings})
            yield self.create_json_message({"status": "success", "stage": "complete", "file": f"{title}.docx", "size_kb": round(size_kb, 1)})
            yield self.create_blob_message(
                blob=docx_bytes,
                meta={
                    "mime_type": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
                    "file_name": f"{title}.docx",
                },
            )

        except Exception as e:
            yield self.create_json_message({"status": "error", "stage": stage, "message": str(e)})
            yield self.create_text_message(
                f"md2docx conversion failed at stage '{stage}': {e}"
            )

        finally:
            if custom_template_path and os.path.exists(custom_template_path):
                try:
                    os.unlink(custom_template_path)
                except OSError:
                    pass
            if mermaid_dir and os.path.isdir(mermaid_dir):
                shutil.rmtree(mermaid_dir, ignore_errors=True)
