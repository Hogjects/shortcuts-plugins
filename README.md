# Shortcuts plugins

Public plugin catalog for the Shortcuts app.

Each plugin lives in `plugins/<id>/` with a `manifest.json` and its entry `.py`.
The folder name must equal the manifest `id`. Bump `version` in the manifest when a plugin changes.

On every push to `main` that touches `plugins/`, a GitHub Action builds the zips and `index.json`
and force pushes them to the `dist` branch. The app reads them from
`https://raw.githubusercontent.com/<user>/<repo>/dist/`.

Plugins are Python code that runs on the user's machine. Only add code you wrote or have reviewed.

Check a plugin locally before pushing:

    python3 tools/build_catalog.py
