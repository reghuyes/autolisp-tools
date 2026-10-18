# AutoLISP + Python Sketch-to-AEC Wall Workflow

This repository contains a baseline workflow for converting hand-drawn line sketches into wall geometry that can be imported into AutoCAD/AutoCAD Architecture.

## What is implemented

- **Input support**
  - Vector line input: `JSON` and `CSV`
  - Raster sketch input: `PNG/JPG/TIFF/BMP/PDF` (requires optional `opencv-python` + `numpy`)
- **Python preprocessing pipeline**
  - Image preprocessing (grayscale, threshold, denoise)
  - Line detection from raster sketches (Hough transform)
  - Geometry cleanup:
    - minimum segment filtering
    - endpoint snapping
    - collinear segment merge
  - Loop candidate detection
  - Output export to:
    - `wall_centerlines.csv`
    - `wall_centerlines.json`
- **Wall rules and tolerances**
  - Configurable defaults and layer-specific wall thickness/height/type
  - Configurable segment tolerances and opening gap thresholds
  - Configurable units and scale factor
- **AutoLISP wall builder**
  - Command: `SKETCH2AEC`
  - Reads `wall_centerlines.csv`
  - Tries **AEC wall creation** (`AECWALLADD`) when available
  - Falls back to **wall-like closed polylines** when AEC toolset is unavailable
  - Runs wall cleanup join after import (`PEDIT` join)

## Repository layout

- `/home/runner/work/autolisp-tools/autolisp-tools/python/sketch_to_aec.py` - Python converter
- `/home/runner/work/autolisp-tools/autolisp-tools/lisp/import_walls.lsp` - AutoLISP import/build command
- `/home/runner/work/autolisp-tools/autolisp-tools/config/wall_rules.json` - configuration
- `/home/runner/work/autolisp-tools/autolisp-tools/examples/sketch_lines.json` - sample input

## Configuration

Edit `/home/runner/work/autolisp-tools/autolisp-tools/config/wall_rules.json`:

- `units`: output unit label (`mm`, `inch`, etc.)
- `scale_factor`: converts source coordinates to CAD units
- `default_wall`: default wall thickness/height/type
- `layer_rules`: per-layer wall overrides
- `geometry`: cleanup and merge tolerances
- `openings`: door/window minimum gap thresholds for downstream rules

## Run the converter

From `/home/runner/work/autolisp-tools/autolisp-tools`:

```bash
python3 /home/runner/work/autolisp-tools/autolisp-tools/python/sketch_to_aec.py \
  --input /home/runner/work/autolisp-tools/autolisp-tools/examples/sketch_lines.json \
  --config /home/runner/work/autolisp-tools/autolisp-tools/config/wall_rules.json \
  --output /home/runner/work/autolisp-tools/autolisp-tools/examples/output
```

Generated files:

- `/home/runner/work/autolisp-tools/autolisp-tools/examples/output/wall_centerlines.csv`
- `/home/runner/work/autolisp-tools/autolisp-tools/examples/output/wall_centerlines.json`

## AutoCAD / AutoCAD Architecture import

1. Copy converter output (`wall_centerlines.csv`) to an accessible location.
2. In AutoCAD, load `/home/runner/work/autolisp-tools/autolisp-tools/lisp/import_walls.lsp` using `APPLOAD`.
3. Run command `SKETCH2AEC`.
4. Select the generated `wall_centerlines.csv` file.
5. Result:
   - If AEC commands are installed, the routine attempts AEC wall creation.
   - Otherwise, it draws offset closed polylines representing wall thickness.

## Validation workflow

- Run the converter and inspect segment counts.
- Open generated CSV/JSON for QA.
- Import with `SKETCH2AEC` and visually verify joins/intersections.
- Tune tolerances in `wall_rules.json` and rerun for noisy or ambiguous sketches.

## Notes

- True AEC wall objects depend on AutoCAD Architecture AEC support.
- Raster image conversion quality depends on sketch contrast and cleanup.
- For production use, add project-specific door/window inference and room semantics.
