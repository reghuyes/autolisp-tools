#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import re
import shutil
import sys
import time
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional, Set, Tuple

import fitz  # PyMuPDF
import pandas as pd
import pytesseract
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
    min_text_length_for_no_ocr: int = 40

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
            min_text_length_for_no_ocr=int(raw.get("min_text_length_for_no_ocr", 40)),
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


def extract_text_with_ocr_fallback(pdf_path: Path, language: str, min_text_length_for_no_ocr: int) -> str:
    chunks: List[str] = []
    with fitz.open(pdf_path) as doc:
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


def load_existing_records(output_excel: Path) -> pd.DataFrame:
    ensure_output_file(output_excel)
    df = pd.read_excel(output_excel)
    for col in ALL_COLUMNS:
        if col not in df.columns:
            df[col] = ""
    return df[ALL_COLUMNS]


def append_unique_row(output_excel: Path, row: Dict[str, str]) -> bool:
    df = load_existing_records(output_excel)
    folder_path = row["Folder Path"]
    if (df["Folder Path"].fillna("") == folder_path).any():
        return False
    new_df = pd.concat([df, pd.DataFrame([row], columns=ALL_COLUMNS)], ignore_index=True)
    new_df.to_excel(output_excel, index=False)
    return True


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


def log_processing(log_path: Path, payload: Dict[str, str]) -> None:
    log_path.parent.mkdir(parents=True, exist_ok=True)
    with log_path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(payload, ensure_ascii=False) + "\n")


def enqueue_error(config: AgentConfig, folder: Path, reason: str) -> None:
    config.error_queue_dir.mkdir(parents=True, exist_ok=True)
    marker = config.error_queue_dir / f"{folder.name}_{int(time.time())}.txt"
    marker.write_text(f"folder={folder}\nreason={reason}\n", encoding="utf-8")
    failed_folder = config.error_queue_dir / folder.name
    if not failed_folder.exists():
        shutil.copytree(folder, failed_folder)


def process_case_folder(folder: Path, config: AgentConfig) -> Tuple[bool, bool, List[str], str]:
    pdf_files = sorted(folder.rglob("*.pdf"))
    if not pdf_files:
        return False, False, [], "No PDF files found"

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
        return False, False, [], "Could not extract text from PDFs"

    extracted = parse_fields(merged_text, config.patterns)
    missing = [key for key in REQUIRED_COLUMNS[1:] if not extracted.get(key)]

    row = {
        "Folder No": folder.name,
        "User Name": extracted["User Name"],
        "Password": extracted["Password"],
        "Applicant Name": extracted["Applicant Name"],
        "Applicant Mobile Number": extracted["Applicant Mobile Number"],
        "Engineer Name": extracted["Engineer Name"],
        "Allocation Date": extracted["Allocation Date"],
        "Folder Path": str(folder.resolve()),
        "Processed At": datetime.utcnow().isoformat(timespec="seconds") + "Z",
        "Missing Fields": ", ".join(missing),
    }
    added = append_unique_row(config.output_excel, row)
    return True, added, missing, ""


def run_once(config: AgentConfig) -> Dict[str, int]:
    config.input_root.mkdir(parents=True, exist_ok=True)
    processed_set = read_processed_folders(config.processing_log)
    summary = {
        "processed": 0,
        "rows_added": 0,
        "skipped_already_processed": 0,
        "failed": 0,
        "with_missing_fields": 0,
    }

    for folder in sorted([p for p in config.input_root.iterdir() if p.is_dir()]):
        folder_path = str(folder.resolve())
        if folder_path in processed_set:
            summary["skipped_already_processed"] += 1
            continue

        try:
            ok, added, missing, reason = process_case_folder(folder, config)
            now = datetime.utcnow().isoformat(timespec="seconds") + "Z"
            if ok:
                summary["processed"] += 1
                if added:
                    summary["rows_added"] += 1
                if missing:
                    summary["with_missing_fields"] += 1
                log_processing(
                    config.processing_log,
                    {
                        "timestamp": now,
                        "status": "processed",
                        "folder_path": folder_path,
                        "missing_fields": missing,
                        "row_added": added,
                    },
                )
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
                    "timestamp": datetime.utcnow().isoformat(timespec="seconds") + "Z",
                    "status": "failed",
                    "folder_path": folder_path,
                    "reason": reason,
                },
            )
    return summary


class NewFolderHandler(FileSystemEventHandler):
    def __init__(self, config: AgentConfig) -> None:
        super().__init__()
        self.config = config

    def on_created(self, event) -> None:  # type: ignore[override]
        if event.is_directory:
            folder = Path(event.src_path)
            if folder.parent.resolve() == self.config.input_root.resolve():
                run_once(self.config)


def run_watch(config: AgentConfig) -> None:
    run_once(config)
    observer = Observer()
    observer.schedule(NewFolderHandler(config), str(config.input_root), recursive=False)
    observer.start()
    print(f"Watching: {config.input_root}")
    try:
        while True:
            time.sleep(1)
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
