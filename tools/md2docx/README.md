# md2docx

Convert Markdown to polished Word documents. Built-in style profiles (including
GOST R 7.0.97-2016), Mermaid diagram rendering, and fine-grained style control.
No API key required — self-contained, no runtime network access for the
conversion itself.

## Tools

| Tool                            | Params | Use case                                    |
| -------------------------------- | ------ | -------------------------------------------- |
| **Markdown to DOCX**              | 7      | Everyday conversion — pick a profile and go |
| **Markdown to DOCX (Advanced)**   | 20     | Full control over fonts, sizes, margins     |
| **Mermaid to Image**              | 2      | Render a standalone Mermaid diagram to PNG  |

## Features

- **7 style profiles** with built-in reference DOCX templates: `technical`, `business`,
  `official` (GB/T 9704), `academic`, `thesis` (GB/T 7713), `gost` (GOST R 7.0.97-2016),
  and `template` (fully custom, bring your own reference `.docx`).
- **Real Word footnotes** — Markdown `[^1]` / `[^1]: text` footnote syntax converts to
  native Word footnotes (not inline text), via Pandoc's `footnotes` extension.
- **Auto Table of Contents** — optional (`include_toc`), inserts a real Word
  auto-updating TOC field (headings levels 1-3), not a static list.
- **Mermaid rendering** via Mermaid Ink API. Inline in DOCX or standalone via the
  `Mermaid to Image` tool.
- **Fine-grained overrides**: 13 advanced parameters for body/heading fonts, sizes,
  line spacing, and margins.
- **CJK-aware**: automatic Chinese/English detection with SimSun / SimHei / FangSong /
  KaiTi defaults for the CJK-oriented profiles.

## Style Profiles

| Profile     | Body Font        | Body Size | Headings                        | Line Spacing | Margins (mm)     | Standard                 |
| ----------- | ---------------- | --------- | -------------------------------- | ------------ | ----------------- | ------------------------ |
| `technical` | Arial            | 11 pt     | Arial 16 / 14 / 12 pt            | 1.35         | 19                | Tech blogs, API docs     |
| `business`  | Arial            | 11 pt     | Arial 18 / 14 / 12 pt            | 1.5          | 25.4              | Business reports, memos  |
| `official`  | FangSong         | 16 pt     | SimHei / KaiTi / FangSong 16 pt  | 1.75         | 37/35/28/26       | GB/T 9704                |
| `academic`  | SimSun           | 12 pt     | SimHei 16 / 14 / 12 pt           | 1.5          | 25.4              | Academic writing, CSSCI  |
| `thesis`    | SimSun           | 12 pt     | SimHei 22 / 16 / 14 pt           | 1.5          | 30                | GB/T 7713                |
| `gost`      | Times New Roman  | 12 pt     | Times New Roman 16 / 14 / 12 pt  | 1.5          | 20/10/20/20       | GOST R 7.0.97-2016       |
| `template`  | (from reference) | —         | —                                 | —            | —                 | Fully custom             |

`gost` also sets a 1.25 cm first-line paragraph indent (GOST R 7.0.97-2016, п. 3.4),
baked into `multi-templates/reference_gost.docx` — Pandoc copies paragraph formatting
from the reference document, so this isn't a style-override parameter.

## Parameters

### Markdown to DOCX (7)

| #   | Parameter            | Type    | Required | Default      | Description                                                |
| --- | --------------------- | ------- | -------- | ------------ | ------------------------------------------------------------ |
| 1   | `markdown_content`    | string  | yes      | —            | The Markdown text (max 5 MB; GFM + footnotes, tables, images, Mermaid) |
| 2   | `title`               | string  | no       | `"Document"` | Output filename without `.docx`                              |
| 3   | `style_profile`       | select  | no       | `academic`   | Style preset (see table above)                                |
| 4   | `reference_language`  | select  | no       | `auto`       | `auto` / `english` / `chinese`                                |
| 5   | `include_toc`         | boolean | no       | `false`      | Insert an auto-updating Word Table of Contents field           |
| 6   | `mermaid_enabled`     | boolean | no       | `true`       | Render Mermaid blocks to images                                |
| 7   | `mermaid_api_url`     | string  | no       | —            | Self-hosted Mermaid Ink URL                                    |

### Markdown to DOCX (Advanced)

All 7 core parameters above plus 13 style overrides: `body_font`, `body_size_pt`,
`line_spacing`, `margin_top_mm`, `margin_bottom_mm`, `margin_left_mm`, `margin_right_mm`,
`heading1_font`, `heading1_size_pt`, `heading2_font`, `heading2_size_pt`, `heading3_font`,
`heading3_size_pt`. All default to profile preset or `0` (= use default).

### Mermaid to Image (2)

| #   | Parameter         | Type   | Required | Default | Description                 |
| --- | ------------------ | ------ | -------- | ------- | ---------------------------- |
| 1   | `mermaid_code`     | string | yes      | —       | Mermaid diagram syntax       |
| 2   | `mermaid_api_url`  | string | no       | —       | Self-hosted Mermaid Ink URL  |

## Self-hosted Mermaid

Deploy your own Mermaid Ink instance if the public service is slow or unreachable:

```bash
docker run -d --restart unless-stopped -p 3000:3000 ghcr.io/jihchi/mermaid.ink
```

With `docker compose`:

```yaml
mermaid_ink:
  image: ghcr.io/jihchi/mermaid.ink
  restart: unless-stopped
  ports:
    - "3000:3000"
```

Then set `mermaid_api_url` to `http://<host>:3000` (use `http://mermaid_ink:3000` inside
compose).

## Network & Privacy

- **Mermaid Ink** (`https://mermaid.ink`): Mermaid source code is sent for PNG rendering.
  No other data is transmitted. Disable via `mermaid_enabled=false` or use a self-hosted
  instance.
- **Pandoc**: bundled in `pypandoc-binary` — no network access needed for the conversion
  itself.
- **Temp files**: cleaned up after each conversion.

Full policy: [PRIVACY.md](./PRIVACY.md).

## Development

```bash
uv sync
```
