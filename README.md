# Arkady Plugins

Monorepo for Arkady plugins, organized by category (matching the layout
of the upstream project these forks originate from):

- `tools/` — tool plugins
- `datasources/` — RAG pipeline datasource plugins
- `models/` — model provider plugins

Each plugin releases independently, tagged `<plugin_name>-v<version>`
(e.g. `qa_chunk-v0.0.13`), with its signed `.arkadypkg` attached to that
release.
