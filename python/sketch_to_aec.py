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
class ImageConfig:
    enable_deskew: bool
    gaussian_blur_ksize: int
    adaptive_threshold: bool
    adaptive_block_size: int
    adaptive_c: float
    morphology_kernel: int
    morphology_iterations: int
    canny_threshold_1: int
    canny_threshold_2: int
    hough_threshold: int
    hough_min_line_length_px: int
    hough_max_line_gap_px: int
    lsd_enabled: bool
    lsd_scale: float


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
    image: ImageConfig


class PipelineError(Exception):
    pass


def _float(value: object, name: str) -> float:
    try:
        return float(value)
    except (TypeError, ValueError) as exc:
        raise PipelineError(f"Invalid numeric value for '{name}': {value!r}") from exc


def _int(value: object, name: str) -> int:
    try:
        return int(value)
    except (TypeError, ValueError) as exc:
        raise PipelineError(f"Invalid integer value for '{name}': {value!r}") from exc


def _bool(value: object, name: str) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        lowered = value.strip().lower()
        if lowered in {"true", "1", "yes", "y", "on"}:
            return True
        if lowered in {"false", "0", "no", "n", "off"}:
            return False
    raise PipelineError(f"Invalid boolean value for '{name}': {value!r}")


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

    image = data.get("image", {})
    adaptive_block_size = _int(image.get("adaptive_block_size", 31), "image.adaptive_block_size")
    if adaptive_block_size < 3:
        adaptive_block_size = 3
    if adaptive_block_size % 2 == 0:
        adaptive_block_size += 1

    gaussian_blur_ksize = _int(image.get("gaussian_blur_ksize", 5), "image.gaussian_blur_ksize")
    if gaussian_blur_ksize < 1:
        gaussian_blur_ksize = 1
    if gaussian_blur_ksize % 2 == 0:
        gaussian_blur_ksize += 1

    morphology_kernel = max(1, _int(image.get("morphology_kernel", 3), "image.morphology_kernel"))

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
        image=ImageConfig(
            enable_deskew=_bool(image.get("enable_deskew", True), "image.enable_deskew"),
            gaussian_blur_ksize=gaussian_blur_ksize,
            adaptive_threshold=_bool(image.get("adaptive_threshold", True), "image.adaptive_threshold"),
            adaptive_block_size=adaptive_block_size,
            adaptive_c=_float(image.get("adaptive_c", 2.0), "image.adaptive_c"),
            morphology_kernel=morphology_kernel,
            morphology_iterations=max(0, _int(image.get("morphology_iterations", 1), "image.morphology_iterations")),
            canny_threshold_1=max(0, _int(image.get("canny_threshold_1", 50), "image.canny_threshold_1")),
            canny_threshold_2=max(1, _int(image.get("canny_threshold_2", 150), "image.canny_threshold_2")),
            hough_threshold=max(1, _int(image.get("hough_threshold", 35), "image.hough_threshold")),
            hough_min_line_length_px=max(5, _int(image.get("hough_min_line_length_px", 30), "image.hough_min_line_length_px")),
            hough_max_line_gap_px=max(1, _int(image.get("hough_max_line_gap_px", 12), "image.hough_max_line_gap_px")),
            lsd_enabled=_bool(image.get("lsd_enabled", True), "image.lsd_enabled"),
            lsd_scale=max(0.1, _float(image.get("lsd_scale", 0.8), "image.lsd_scale")),
        ),
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


def _deskew_image(image: "np.ndarray", cv2: object) -> "np.ndarray":
    coords = cv2.findNonZero(image)
    if coords is None:
        return image
    rect = cv2.minAreaRect(coords)
    angle = rect[2]
    if angle < -45:
        angle = 90 + angle
    if abs(angle) < 0.1:
        return image
    h, w = image.shape[:2]
    center = (w / 2.0, h / 2.0)
    matrix = cv2.getRotationMatrix2D(center, angle, 1.0)
    return cv2.warpAffine(image, matrix, (w, h), flags=cv2.INTER_CUBIC, borderMode=cv2.BORDER_REPLICATE)


def _preprocess_image(image: "np.ndarray", config: PipelineConfig, cv2: object) -> "np.ndarray":
    work = cv2.fastNlMeansDenoising(image, None, 12, 7, 21)
    work = cv2.GaussianBlur(work, (config.image.gaussian_blur_ksize, config.image.gaussian_blur_ksize), 0)

    if config.image.adaptive_threshold:
        threshold = cv2.adaptiveThreshold(
            work,
            255,
            cv2.ADAPTIVE_THRESH_GAUSSIAN_C,
            cv2.THRESH_BINARY_INV,
            config.image.adaptive_block_size,
            config.image.adaptive_c,
        )
    else:
        _, threshold = cv2.threshold(work, 0, 255, cv2.THRESH_BINARY_INV + cv2.THRESH_OTSU)

    kernel = cv2.getStructuringElement(
        cv2.MORPH_RECT,
        (config.image.morphology_kernel, config.image.morphology_kernel),
    )
    if config.image.morphology_iterations > 0:
        threshold = cv2.morphologyEx(
            threshold,
            cv2.MORPH_CLOSE,
            kernel,
            iterations=config.image.morphology_iterations,
        )
        threshold = cv2.morphologyEx(
            threshold,
            cv2.MORPH_OPEN,
            kernel,
            iterations=1,
        )

    if config.image.enable_deskew:
        threshold = _deskew_image(threshold, cv2)
    return threshold


def _extract_hough_segments(threshold: "np.ndarray", config: PipelineConfig, cv2: object, np: object) -> List[Tuple[int, int, int, int]]:
    edges = cv2.Canny(
        threshold,
        config.image.canny_threshold_1,
        config.image.canny_threshold_2,
        apertureSize=3,
    )
    min_length_scale = max(config.scale_factor, 1e-9)
    base_min_len = max(
        config.image.hough_min_line_length_px,
        int(config.min_segment_length / min_length_scale),
    )
    base_max_gap = max(
        config.image.hough_max_line_gap_px,
        int(config.join_tolerance / min_length_scale),
    )
    params = [
        (config.image.hough_threshold, base_min_len, base_max_gap),
        (max(10, int(config.image.hough_threshold * 0.75)), max(10, int(base_min_len * 0.6)), max(3, int(base_max_gap * 1.5))),
    ]
    found: List[Tuple[int, int, int, int]] = []
    for threshold_value, min_len, max_gap in params:
        lines = cv2.HoughLinesP(
            edges,
            rho=1,
            theta=np.pi / 180,
            threshold=threshold_value,
            minLineLength=min_len,
            maxLineGap=max_gap,
        )
        if lines is None:
            continue
        normalized_lines = np.asarray(lines).reshape(-1, 4)
        for line in normalized_lines:
            x1, y1, x2, y2 = line.tolist()
            found.append((int(x1), int(y1), int(x2), int(y2)))
    return found


def _extract_lsd_segments(threshold: "np.ndarray", config: PipelineConfig, cv2: object, np: object) -> List[Tuple[int, int, int, int]]:
    if not config.image.lsd_enabled:
        return []
    if not hasattr(cv2, "createLineSegmentDetector"):
        return []
    detector = cv2.createLineSegmentDetector(scale=config.image.lsd_scale)
    detected = detector.detect(threshold)[0]
    if detected is None:
        return []
    lines: List[Tuple[int, int, int, int]] = []
    normalized_segments = np.asarray(detected).reshape(-1, 4)
    for segment in normalized_segments:
        x1, y1, x2, y2 = segment.tolist()
        lines.append((int(round(x1)), int(round(y1)), int(round(x2)), int(round(y2))))
    return lines


def _normalize_line(line: Tuple[int, int, int, int]) -> Tuple[int, int, int, int]:
    x1, y1, x2, y2 = line
    if (x1, y1) <= (x2, y2):
        return line
    return (x2, y2, x1, y1)


def _deduplicate_raw_lines(
    raw_lines: Iterable[Tuple[int, int, int, int]], config: PipelineConfig
) -> List[Tuple[int, int, int, int]]:
    tolerance_px = max(2, int(config.snap_tolerance / max(config.scale_factor, 1e-9)))
    buckets: Dict[Tuple[int, int, int, int], Tuple[int, int, int, int]] = {}
    for raw in raw_lines:
        normalized = _normalize_line(raw)
        key = (
            round(normalized[0] / tolerance_px),
            round(normalized[1] / tolerance_px),
            round(normalized[2] / tolerance_px),
            round(normalized[3] / tolerance_px),
        )
        current = buckets.get(key)
        if current is None:
            buckets[key] = normalized
            continue
        current_length = math.dist((current[0], current[1]), (current[2], current[3]))
        new_length = math.dist((normalized[0], normalized[1]), (normalized[2], normalized[3]))
        if new_length > current_length:
            buckets[key] = normalized
    return list(buckets.values())


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

    threshold = _preprocess_image(image, config, cv2)
    hough_lines = _extract_hough_segments(threshold, config, cv2, np)
    lsd_lines = _extract_lsd_segments(threshold, config, cv2, np)
    merged_lines = _deduplicate_raw_lines([*hough_lines, *lsd_lines], config)
    if not merged_lines:
        return []

    segments: List[Segment] = []
    for x1, y1, x2, y2 in merged_lines:
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
