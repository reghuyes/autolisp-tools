#!/usr/bin/env python3
"""Convert sketch linework into wall centerlines consumable by AutoLISP."""

from __future__ import annotations

import argparse
import csv
import json
import math
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Sequence, Tuple


IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg", ".tif", ".tiff", ".bmp", ".pdf"}


@dataclass(frozen=True)
class Point:
    x: float
    y: float


@dataclass(frozen=True)
class Segment:
    start: Point
    end: Point
    layer: str = "WALL"

    @property
    def length(self) -> float:
        return math.dist((self.start.x, self.start.y), (self.end.x, self.end.y))


@dataclass
class WallRule:
    thickness: float
    height: float
    wall_type: str = "Generic"


@dataclass
class PipelineConfig:
    units: str
    scale_factor: float
    min_segment_length: float
    snap_tolerance: float
    collinear_angle_tolerance_deg: float
    join_tolerance: float
    default_wall_rule: WallRule
    layer_wall_rules: Dict[str, WallRule]
    door_gap_min: float
    window_gap_min: float


class PipelineError(Exception):
    pass


def _float(value: object, name: str) -> float:
    try:
        return float(value)
    except (TypeError, ValueError) as exc:
        raise PipelineError(f"Invalid numeric value for '{name}': {value!r}") from exc


def load_config(config_path: Path) -> PipelineConfig:
    data = json.loads(config_path.read_text(encoding="utf-8"))
    wall_defaults = data.get("default_wall", {})
    default_rule = WallRule(
        thickness=_float(wall_defaults.get("thickness", 200.0), "default_wall.thickness"),
        height=_float(wall_defaults.get("height", 3000.0), "default_wall.height"),
        wall_type=str(wall_defaults.get("type", "Generic")),
    )

    layer_rules: Dict[str, WallRule] = {}
    for layer, rule in data.get("layer_rules", {}).items():
        layer_rules[layer.upper()] = WallRule(
            thickness=_float(rule.get("thickness", default_rule.thickness), f"layer_rules.{layer}.thickness"),
            height=_float(rule.get("height", default_rule.height), f"layer_rules.{layer}.height"),
            wall_type=str(rule.get("type", default_rule.wall_type)),
        )

    return PipelineConfig(
        units=str(data.get("units", "mm")),
        scale_factor=_float(data.get("scale_factor", 1.0), "scale_factor"),
        min_segment_length=_float(data.get("geometry", {}).get("min_segment_length", 250.0), "geometry.min_segment_length"),
        snap_tolerance=_float(data.get("geometry", {}).get("snap_tolerance", 15.0), "geometry.snap_tolerance"),
        collinear_angle_tolerance_deg=_float(
            data.get("geometry", {}).get("collinear_angle_tolerance_deg", 3.0),
            "geometry.collinear_angle_tolerance_deg",
        ),
        join_tolerance=_float(data.get("geometry", {}).get("join_tolerance", 20.0), "geometry.join_tolerance"),
        default_wall_rule=default_rule,
        layer_wall_rules=layer_rules,
        door_gap_min=_float(data.get("openings", {}).get("door_gap_min", 800.0), "openings.door_gap_min"),
        window_gap_min=_float(data.get("openings", {}).get("window_gap_min", 500.0), "openings.window_gap_min"),
    )


def load_segments(input_path: Path, config: PipelineConfig) -> List[Segment]:
    ext = input_path.suffix.lower()
    if ext in {".json"}:
        return _load_json_segments(input_path, config)
    if ext in {".csv"}:
        return _load_csv_segments(input_path, config)
    if ext in IMAGE_EXTENSIONS:
        return _load_image_segments(input_path, config)
    raise PipelineError(
        f"Unsupported input format '{ext}'. Supported: JSON, CSV, and images ({', '.join(sorted(IMAGE_EXTENSIONS))})."
    )


def _scale_point(raw: Sequence[object], scale_factor: float) -> Point:
    if len(raw) != 2:
        raise PipelineError(f"Point must have exactly two numeric values, got: {raw!r}")
    return Point(_float(raw[0], "point.x") * scale_factor, _float(raw[1], "point.y") * scale_factor)


def _load_json_segments(input_path: Path, config: PipelineConfig) -> List[Segment]:
    data = json.loads(input_path.read_text(encoding="utf-8"))
    raw_segments = data.get("segments", data)
    if not isinstance(raw_segments, list):
        raise PipelineError("JSON input must be a list of segments or an object containing a 'segments' list.")

    segments: List[Segment] = []
    for index, item in enumerate(raw_segments, start=1):
        if not isinstance(item, dict):
            raise PipelineError(f"Segment #{index} must be an object.")
        start = _scale_point(item.get("start", []), config.scale_factor)
        end = _scale_point(item.get("end", []), config.scale_factor)
        layer = str(item.get("layer", "WALL")).upper()
        segments.append(Segment(start=start, end=end, layer=layer))
    return segments


def _load_csv_segments(input_path: Path, config: PipelineConfig) -> List[Segment]:
    segments: List[Segment] = []
    with input_path.open("r", encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle)
        required = {"x1", "y1", "x2", "y2"}
        if not reader.fieldnames or not required.issubset({name.lower() for name in reader.fieldnames}):
            raise PipelineError("CSV input must include headers: x1,y1,x2,y2 (optional: layer).")
        for index, row in enumerate(reader, start=2):
            start = Point(
                _float(row.get("x1"), f"line {index} x1") * config.scale_factor,
                _float(row.get("y1"), f"line {index} y1") * config.scale_factor,
            )
            end = Point(
                _float(row.get("x2"), f"line {index} x2") * config.scale_factor,
                _float(row.get("y2"), f"line {index} y2") * config.scale_factor,
            )
            layer = str(row.get("layer") or "WALL").upper()
            segments.append(Segment(start=start, end=end, layer=layer))
    return segments


def _load_image_segments(input_path: Path, config: PipelineConfig) -> List[Segment]:
    try:
        import cv2  # type: ignore
        import numpy as np  # type: ignore
    except ImportError as exc:
        raise PipelineError(
            "Image pipeline requires optional dependencies 'opencv-python' and 'numpy'."
        ) from exc

    image = cv2.imread(str(input_path), cv2.IMREAD_GRAYSCALE)
    if image is None:
        raise PipelineError(f"Could not load image input: {input_path}")

    blur = cv2.GaussianBlur(image, (3, 3), 0)
    _, threshold = cv2.threshold(blur, 0, 255, cv2.THRESH_BINARY_INV + cv2.THRESH_OTSU)
    lines = cv2.HoughLinesP(
        threshold,
        rho=1,
        theta=np.pi / 180,
        threshold=60,
        minLineLength=max(int(config.min_segment_length / max(config.scale_factor, 1e-9)), 10),
        maxLineGap=max(int(config.join_tolerance / max(config.scale_factor, 1e-9)), 5),
    )

    if lines is None:
        return []

    segments: List[Segment] = []
    for line in lines[:, 0]:
        x1, y1, x2, y2 = line.tolist()
        segments.append(
            Segment(
                start=Point(x1 * config.scale_factor, y1 * config.scale_factor),
                end=Point(x2 * config.scale_factor, y2 * config.scale_factor),
            )
        )
    return segments


def clean_segments(segments: Iterable[Segment], config: PipelineConfig) -> List[Segment]:
    filtered = [s for s in segments if s.length >= config.min_segment_length]
    snapped = _snap_endpoints(filtered, config.snap_tolerance)
    merged = _merge_collinear_segments(snapped, config.collinear_angle_tolerance_deg, config.join_tolerance)
    return [s for s in merged if s.length >= config.min_segment_length]


def _snap_endpoints(segments: Sequence[Segment], tolerance: float) -> List[Segment]:
    if not segments:
        return []

    points: List[Point] = []
    for segment in segments:
        points.extend([segment.start, segment.end])

    clusters: List[List[Point]] = []
    for point in points:
        for cluster in clusters:
            if math.dist((cluster[0].x, cluster[0].y), (point.x, point.y)) <= tolerance:
                cluster.append(point)
                break
        else:
            clusters.append([point])

    cluster_centers: Dict[Tuple[float, float], Point] = {}
    for cluster in clusters:
        cx = sum(p.x for p in cluster) / len(cluster)
        cy = sum(p.y for p in cluster) / len(cluster)
        center = Point(cx, cy)
        for p in cluster:
            cluster_centers[(p.x, p.y)] = center

    snapped: List[Segment] = []
    for segment in segments:
        start = cluster_centers[(segment.start.x, segment.start.y)]
        end = cluster_centers[(segment.end.x, segment.end.y)]
        if math.dist((start.x, start.y), (end.x, end.y)) > 1e-6:
            snapped.append(Segment(start=start, end=end, layer=segment.layer))
    return snapped


def _segment_angle_deg(segment: Segment) -> float:
    return math.degrees(math.atan2(segment.end.y - segment.start.y, segment.end.x - segment.start.x)) % 180


def _point_on_segment_distance(point: Point, segment: Segment) -> float:
    px, py = point.x, point.y
    x1, y1 = segment.start.x, segment.start.y
    x2, y2 = segment.end.x, segment.end.y
    dx, dy = x2 - x1, y2 - y1
    if abs(dx) < 1e-9 and abs(dy) < 1e-9:
        return math.dist((px, py), (x1, y1))
    t = max(0.0, min(1.0, ((px - x1) * dx + (py - y1) * dy) / (dx * dx + dy * dy)))
    proj_x = x1 + t * dx
    proj_y = y1 + t * dy
    return math.dist((px, py), (proj_x, proj_y))


def _merge_pair(first: Segment, second: Segment) -> Optional[Segment]:
    points = [first.start, first.end, second.start, second.end]
    max_pair = None
    max_distance = -1.0
    for i in range(len(points)):
        for j in range(i + 1, len(points)):
            d = math.dist((points[i].x, points[i].y), (points[j].x, points[j].y))
            if d > max_distance:
                max_distance = d
                max_pair = (points[i], points[j])
    if not max_pair:
        return None
    return Segment(start=max_pair[0], end=max_pair[1], layer=first.layer)


def _merge_collinear_segments(
    segments: Sequence[Segment], angle_tolerance_deg: float, join_tolerance: float
) -> List[Segment]:
    pending = list(segments)
    changed = True
    while changed:
        changed = False
        result: List[Segment] = []
        used = [False] * len(pending)
        for i, base in enumerate(pending):
            if used[i]:
                continue
            merged = base
            for j in range(i + 1, len(pending)):
                if used[j]:
                    continue
                candidate = pending[j]
                if merged.layer != candidate.layer:
                    continue
                angle_diff = abs(_segment_angle_deg(merged) - _segment_angle_deg(candidate))
                angle_diff = min(angle_diff, 180 - angle_diff)
                if angle_diff > angle_tolerance_deg:
                    continue
                endpoint_distances = [
                    math.dist((merged.start.x, merged.start.y), (candidate.start.x, candidate.start.y)),
                    math.dist((merged.start.x, merged.start.y), (candidate.end.x, candidate.end.y)),
                    math.dist((merged.end.x, merged.end.y), (candidate.start.x, candidate.start.y)),
                    math.dist((merged.end.x, merged.end.y), (candidate.end.x, candidate.end.y)),
                ]
                if min(endpoint_distances) > join_tolerance:
                    continue
                if max(
                    _point_on_segment_distance(candidate.start, merged),
                    _point_on_segment_distance(candidate.end, merged),
                ) > join_tolerance:
                    continue
                merged_result = _merge_pair(merged, candidate)
                if merged_result is None:
                    continue
                merged = merged_result
                used[j] = True
                changed = True
            used[i] = True
            result.append(merged)
        pending = result
    return pending


def detect_loops(segments: Sequence[Segment], tolerance: float) -> List[List[Tuple[float, float]]]:
    node_index: Dict[Tuple[float, float], int] = {}
    points: List[Point] = []

    def _find_node(point: Point) -> int:
        for key, idx in node_index.items():
            if math.dist((key[0], key[1]), (point.x, point.y)) <= tolerance:
                return idx
        idx = len(points)
        points.append(point)
        node_index[(point.x, point.y)] = idx
        return idx

    adjacency: Dict[int, List[int]] = {}
    for segment in segments:
        a = _find_node(segment.start)
        b = _find_node(segment.end)
        adjacency.setdefault(a, []).append(b)
        adjacency.setdefault(b, []).append(a)

    visited: set[int] = set()
    loops: List[List[Tuple[float, float]]] = []

    for node in adjacency:
        if node in visited:
            continue
        stack = [node]
        component: List[int] = []
        while stack:
            current = stack.pop()
            if current in visited:
                continue
            visited.add(current)
            component.append(current)
            stack.extend(adjacency.get(current, []))

        if component and all(len(adjacency.get(n, [])) == 2 for n in component):
            loops.append([(points[n].x, points[n].y) for n in component])

    return loops


def resolve_wall_rule(layer: str, config: PipelineConfig) -> WallRule:
    return config.layer_wall_rules.get(layer.upper(), config.default_wall_rule)


def build_output_records(segments: Sequence[Segment], config: PipelineConfig) -> List[Dict[str, object]]:
    records: List[Dict[str, object]] = []
    for segment in segments:
        rule = resolve_wall_rule(segment.layer, config)
        records.append(
            {
                "x1": round(segment.start.x, 3),
                "y1": round(segment.start.y, 3),
                "x2": round(segment.end.x, 3),
                "y2": round(segment.end.y, 3),
                "layer": segment.layer,
                "thickness": round(rule.thickness, 3),
                "height": round(rule.height, 3),
                "wall_type": rule.wall_type,
            }
        )
    return records


def write_outputs(records: Sequence[Dict[str, object]], loops: Sequence[Sequence[Tuple[float, float]]], output_dir: Path) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)

    csv_path = output_dir / "wall_centerlines.csv"
    with csv_path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(
            handle,
            fieldnames=["x1", "y1", "x2", "y2", "layer", "thickness", "height", "wall_type"],
        )
        writer.writeheader()
        writer.writerows(records)

    json_path = output_dir / "wall_centerlines.json"
    json_payload = {
        "wall_centerlines": list(records),
        "loop_candidates": list(loops),
    }
    json_path.write_text(json.dumps(json_payload, indent=2), encoding="utf-8")


def parse_args(argv: Optional[Sequence[str]] = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Convert hand sketch linework into AutoLISP-ready wall centerlines.")
    parser.add_argument("--input", required=True, help="Input sketch file (JSON, CSV, image).")
    parser.add_argument("--config", required=True, help="Pipeline configuration JSON path.")
    parser.add_argument("--output", required=True, help="Directory for generated files.")
    return parser.parse_args(argv)


def main(argv: Optional[Sequence[str]] = None) -> int:
    args = parse_args(argv)
    input_path = Path(args.input)
    config_path = Path(args.config)
    output_dir = Path(args.output)

    config = load_config(config_path)
    raw_segments = load_segments(input_path, config)
    cleaned_segments = clean_segments(raw_segments, config)
    loops = detect_loops(cleaned_segments, config.join_tolerance)
    records = build_output_records(cleaned_segments, config)
    write_outputs(records, loops, output_dir)

    print(f"Processed segments: {len(raw_segments)}")
    print(f"Cleaned segments: {len(cleaned_segments)}")
    print(f"Loop candidates: {len(loops)}")
    print(f"Wrote output to: {output_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
