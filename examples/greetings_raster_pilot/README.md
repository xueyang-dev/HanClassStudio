# Greetings Raster Pilot

Development-only zero-beginner pilot for **你好 / 您好 / 老师好 / 早上好 / 再见**.

The builder first runs the existing State–Evidence–Activity–Presentation pipeline, then writes the reviewed pilot blueprint through the normal compatibility seam and produces local HTML, editable PPTX, ZIP, AssetManifest, provenance, and a teacher media review page.

Raster remains opt-in. A normal run uses deterministic fallback assets:

```bash
PYTHONPATH=apps/api/src apps/api/.venv/bin/python examples/greetings_raster_pilot/build_pilot.py
```

A real run additionally requires `HCS_EXPERIMENTAL_RASTER_API_KEY` and `--real-raster`. Never commit the key. Generated pilot artifacts stay under `runtime/projects/greetings_raster_pilot/` and are not production courseware fixtures.
