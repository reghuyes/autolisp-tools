#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import queue
import re
import shutil
import sys
import threading
import time
import uuid
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Dict, Iterator, List, Optional, Set, Tuple

import pymupdf
import pandas as pd
import pytesseract
from filelock import FileLock
from PIL import Image
from watchdog.events import FileSystemEventHandler
from watchdog.observers import Observer


REQUIRED_COLUMNS = [
    "Folder No",
    "User Name",
    "Password",
    "Applicant Name",
    "Applicant Mobile Number",
    "Engineer Name",
    "Allocation Date",
]

OPTIONAL_COLUMNS = ["Folder Path", "Processed At", "Missing Fields"]
ALL_COLUMNS = REQUIRED_COLUMNS + OPTIONAL_COLUMNS
RUN_LOCK = threading.Lock()
WATCH_DEBOUNCE_SECONDS = 1.0


DEFAULT_PATTERNS = {
    "User Name": r"(?im)^\s*(?:user\s*name|username)\s*[:\-]\s*(.+?)\s*$",
    "Password": r"(?im)^\s*(?:password|pass)\s*[:\-]\s*(.+?)\s*$",
    "Applicant Name": r"(?im)^\s*applicant\s*name\s*[:\-]\s*(.+?)\s*$",
    "Applicant Mobile Number": r"(?im)^\s*(?:applicant\s*)?(?:mobile|phone|contact)\s*(?:number|no\.?)?\s*[:\-]\s*([+\d][\d\s\-()]{7,})\s*$",
    "Engineer Name": r"(?im)^\s*engineer\s*name\s*[:\-]\s*(.+?)\s*$",
    "Allocation Date": r"(?im)^\s*(?:allocation|allotment)\s*date\s*[:\-]\s*([^\n\r]+?)\s*$",
}


@dataclass
class AgentConfig:
    input_root: Path
    output_excel: Path
    processing_log: Path
    error_queue_dir: Path
    patterns: Dict[str, str]
    ocr_language: str = "eng"
    mask_password: bool = False
    min_text_length_for_no_ocr: int = 40
    watch_debounce_seconds: float = WATCH_DEBOUNCE_SECONDS

    @staticmethod
    def from_file(config_path: Path) -> "AgentConfig":
        raw = json.loads(config_path.read_text(encoding="utf-8"))
        patterns = dict(DEFAULT_PATTERNS)
        patterns.update(raw.get("extraction_patterns", {}))
        return AgentConfig(
            input_root=Path(raw["input_root"]).expanduser().resolve(),
            output_excel=Path(raw["output_excel"]).expanduser().resolve(),
            processing_log=Path(raw["processing_log"]).expanduser().resolve(),
            error_queue_dir=Path(raw["error_queue_dir"]).expanduser().resolve(),
            patterns=patterns,
            ocr_language=raw.get("ocr_language", "eng"),
            mask_password=bool(raw.get("mask_password", False)),
            min_text_length_for_no_ocr=int(raw.get("min_text_length_for_no_ocr", 40)),
            watch_debounce_seconds=float(raw.get("watch_debounce_seconds", WATCH_DEBOUNCE_SECONDS)),
        )


def normalize_mobile(value: Optional[str]) -> str:
    if not value:
        return ""
    cleaned = re.sub(r"[^\d+]", "", value)
    if cleaned.startswith("00"):
        cleaned = f"+{cleaned[2:]}"
    return cleaned


def normalize_date(value: Optional[str]) -> str:
    if not value:
        return ""
    value = value.strip()
    formats = [
        "%d-%m-%Y",
        "%d/%m/%Y",
        "%Y-%m-%d",
        "%Y/%m/%d",
        "%d-%m-%y",
        "%d/%m/%y",
    ]
    for fmt in formats:
        try:
            return datetime.strptime(value, fmt).strftime("%Y-%m-%d")
        except ValueError:
            continue
    return value


def mask_secret(value: str) -> str:
    if not value:
        return ""
    return "[REDACTED]"


def extract_text_with_ocr_fallback(pdf_path: Path, language: str, min_text_length_for_no_ocr: int) -> str:
    """Extract page text and use OCR on pages with too little direct text content."""
    chunks: List[str] = []
    with pymupdf.open(pdf_path) as doc:
        for page in doc:
            text = page.get_text("text").strip()
            if len(text) >= min_text_length_for_no_ocr:
                chunks.append(text)
                continue
            pix = page.get_pixmap(dpi=300)
            img = Image.frombytes("RGB", [pix.width, pix.height], pix.samples)
            ocr_text = pytesseract.image_to_string(img, lang=language).strip()
            if ocr_text:
                chunks.append(ocr_text)
            elif text:
                chunks.append(text)
    return "\n".join(chunks).strip()


def utc_now_iso() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds").replace("+00:00", "Z")


def parse_fields(text: str, patterns: Dict[str, str]) -> Dict[str, str]:
    result = {col: "" for col in REQUIRED_COLUMNS if col != "Folder No"}
    for key, pattern in patterns.items():
        if key not in result:
            continue
        match = re.search(pattern, text)
        if match:
            result[key] = " ".join(match.group(1).split())
    result["Applicant Mobile Number"] = normalize_mobile(result["Applicant Mobile Number"])
    result["Allocation Date"] = normalize_date(result["Allocation Date"])
    return result


def ensure_output_file(output_excel: Path) -> None:
    output_excel.parent.mkdir(parents=True, exist_ok=True)
    if not output_excel.exists():
        pd.DataFrame(columns=ALL_COLUMNS).to_excel(output_excel, index=False)
        secure_permissions(output_excel)


def secure_permissions(path: Path) -> None:
    if os.name != "nt":
        path.chmod(0o600)


def lock_file_path(target: Path) -> Path:
    return target.with_suffix(target.suffix + ".lock")


@contextmanager
def with_file_lock(target: Path) -> Iterator[None]:
    lock_path = lock_file_path(target)
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    lock_path.touch(exist_ok=True)
    secure_permissions(lock_path)
    lock = FileLock(str(lock_path))
    with lock:
        yield


def load_existing_records(output_excel: Path) -> pd.DataFrame:
    ensure_output_file(output_excel)
    try:
        df = pd.read_excel(output_excel)
    except Exception:
        df = pd.DataFrame(columns=ALL_COLUMNS)
    for col in ALL_COLUMNS:
        if col not in df.columns:
            df[col] = ""
    return df[ALL_COLUMNS]


def append_unique_rows(output_excel: Path, rows: List[Dict[str, str]]) -> Set[str]:
    if not rows:
        return set()

    with with_file_lock(output_excel):
        df = load_existing_records(output_excel)
        known_paths = set(df["Folder Path"].fillna("").astype(str))
        unique_rows: List[Dict[str, str]] = []
        for row in rows:
            folder_path = str(row["Folder Path"])
            if folder_path in known_paths:
                continue
            known_paths.add(folder_path)
            unique_rows.append(row)

        if not unique_rows:
            return set()

        new_df = pd.concat([df, pd.DataFrame(unique_rows, columns=ALL_COLUMNS)], ignore_index=True)
        new_df.to_excel(output_excel, index=False)
        secure_permissions(output_excel)
        return {str(row["Folder Path"]) for row in unique_rows}


def read_processed_folders(log_path: Path) -> Set[str]:
    if not log_path.exists():
        return set()
    processed: Set[str] = set()
    for line in log_path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        try:
            item = json.loads(line)
        except json.JSONDecodeError:
            continue
        if item.get("status") == "processed":
            processed.add(item.get("folder_path", ""))
    return processed


def log_processing(log_path: Path, payload: Dict[str, object]) -> None:
    log_path.parent.mkdir(parents=True, exist_ok=True)
    with with_file_lock(log_path):
        with log_path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(payload, ensure_ascii=False) + "\n")
        secure_permissions(log_path)


def enqueue_error(config: AgentConfig, folder: Path, reason: str) -> None:
    config.error_queue_dir.mkdir(parents=True, exist_ok=True)
    marker = config.error_queue_dir / f"{folder.name}_{time.time_ns()}_{uuid.uuid4().hex[:8]}.txt"
    marker.write_text(f"folder={folder}\nreason={reason}\n", encoding="utf-8")
    failed_folder = config.error_queue_dir / f"{folder.name}_{uuid.uuid4().hex[:8]}"
    try:
        shutil.copytree(folder, failed_folder)
    except OSError as exc:
        with marker.open("a", encoding="utf-8") as f:
            f.write(f"copy_error={exc}\n")


def process_case_folder(folder: Path, config: AgentConfig) -> Tuple[bool, Optional[Dict[str, str]], List[str], str]:
    pdf_files = sorted(folder.rglob("*.pdf"))
    if not pdf_files:
        return False, None, [], "No PDF files found"

    texts: List[str] = []
    for pdf_file in pdf_files:
        text = extract_text_with_ocr_fallback(
            pdf_path=pdf_file,
            language=config.ocr_language,
            min_text_length_for_no_ocr=config.min_text_length_for_no_ocr,
        )
        if text:
            texts.append(text)
    merged_text = "\n".join(texts).strip()
    if not merged_text:
        return False, None, [], "Could not extract text from PDFs"

    extracted = parse_fields(merged_text, config.patterns)
    password_value = mask_secret(extracted["Password"]) if config.mask_password else extracted["Password"]

    row = {
        "Folder No": folder.name,
        "User Name": extracted["User Name"],
        "Password": password_value,
        "Applicant Name": extracted["Applicant Name"],
        "Applicant Mobile Number": extracted["Applicant Mobile Number"],
        "Engineer Name": extracted["Engineer Name"],
        "Allocation Date": extracted["Allocation Date"],
        "Folder Path": str(folder.resolve()),
        "Processed At": utc_now_iso(),
        "Missing Fields": "",
    }
    missing = [key for key in REQUIRED_COLUMNS if key != "Folder No" and not row.get(key)]
    row["Missing Fields"] = ", ".join(missing)
    return True, row, missing, ""


def run_once(config: AgentConfig) -> Dict[str, int]:
    with RUN_LOCK:
        config.input_root.mkdir(parents=True, exist_ok=True)
        processed_set = read_processed_folders(config.processing_log)
        summary = {
            "processed": 0,
            "rows_added": 0,
            "skipped_already_processed": 0,
            "failed": 0,
            "with_missing_fields": 0,
        }
        successful_logs: List[Dict[str, object]] = []
        rows_to_append: List[Dict[str, str]] = []

        for folder in sorted([p for p in config.input_root.iterdir() if p.is_dir()]):
            folder_path = str(folder.resolve())
            if folder_path in processed_set:
                summary["skipped_already_processed"] += 1
                continue

            try:
                ok, row, missing, reason = process_case_folder(folder, config)
                now = utc_now_iso()
                if ok and row is not None:
                    summary["processed"] += 1
                    if missing:
                        summary["with_missing_fields"] += 1
                    successful_logs.append(
                        {
                            "timestamp": now,
                            "status": "processed",
                            "folder_path": folder_path,
                            "missing_fields": missing,
                        }
                    )
                    rows_to_append.append(row)
                else:
                    summary["failed"] += 1
                    enqueue_error(config, folder, reason)
                    log_processing(
                        config.processing_log,
                        {
                            "timestamp": now,
                            "status": "failed",
                            "folder_path": folder_path,
                            "reason": reason,
                        },
                    )
            except Exception as exc:  # noqa: BLE001
                summary["failed"] += 1
                reason = str(exc)
                enqueue_error(config, folder, reason)
                log_processing(
                    config.processing_log,
                    {
                        "timestamp": utc_now_iso(),
                        "status": "failed",
                        "folder_path": folder_path,
                        "reason": reason,
                    },
                )

        inserted_paths: Set[str] = set()
        try:
            inserted_paths = append_unique_rows(config.output_excel, rows_to_append)
        except Exception as exc:  # noqa: BLE001
            summary["failed"] += len(successful_logs)
            summary["processed"] = max(0, summary["processed"] - len(successful_logs))
            missing_in_batch = sum(1 for payload in successful_logs if payload.get("missing_fields"))
            summary["with_missing_fields"] = max(0, summary["with_missing_fields"] - missing_in_batch)
            for payload in successful_logs:
                enqueue_error(
                    config,
                    Path(str(payload["folder_path"])),
                    f"excel_write_failed: {exc}",
                )
                log_processing(
                    config.processing_log,
                    {
                        "timestamp": utc_now_iso(),
                        "status": "failed_write",
                        "folder_path": payload["folder_path"],
                        "reason": str(exc),
                    },
                )
            return summary

        summary["rows_added"] = len(inserted_paths)
        for payload in successful_logs:
            folder_path = str(payload["folder_path"])
            payload["row_added"] = folder_path in inserted_paths
            log_processing(config.processing_log, payload)
        return summary


class NewFolderHandler(FileSystemEventHandler):
    def __init__(self, config: AgentConfig, trigger_queue: queue.Queue) -> None:
        super().__init__()
        self.config = config
        self.trigger_queue = trigger_queue

    def on_created(self, event) -> None:  # type: ignore[override]
        if event.is_directory:
            folder = Path(event.src_path)
            if folder.parent.resolve() == self.config.input_root.resolve():
                self.trigger_queue.put(1)


def run_watch(config: AgentConfig) -> None:
    run_once(config)
    trigger_queue: queue.Queue = queue.Queue()
    observer = Observer()
    observer.schedule(NewFolderHandler(config, trigger_queue), str(config.input_root), recursive=False)
    observer.start()
    print(f"Watching: {config.input_root}")
    try:
        while True:
            try:
                trigger_queue.get(timeout=1)
            except queue.Empty:
                continue

            time.sleep(config.watch_debounce_seconds)
            try:
                while True:
                    trigger_queue.get_nowait()
            except queue.Empty:
                pass

            try:
                run_once(config)
            except Exception as exc:  # noqa: BLE001
                print(f"watch-run error: {exc}", file=sys.stderr)
    except KeyboardInterrupt:
        observer.stop()
    observer.join()


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Process case PDFs into one Excel row per folder.")
    parser.add_argument(
        "--config",
        default="agent_config.json",
        help="Path to JSON config file.",
    )
    parser.add_argument(
        "--watch",
        action="store_true",
        help="Watch the input root for new folders continuously.",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    config = AgentConfig.from_file(Path(args.config).expanduser().resolve())

    if args.watch:
        run_watch(config)
        return 0

    summary = run_once(config)
    print(json.dumps(summary, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
