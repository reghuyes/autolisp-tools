# PDF Extraction Agent

Processes a main folder of case subfolders and writes one Excel row per subfolder.

## Output columns

- Folder No
- User Name
- Password
- Applicant Name
- Applicant Mobile Number
- Engineer Name
- Allocation Date

Additional audit columns are also written: `Folder Path`, `Processed At`, `Missing Fields`.

## Setup

```bash
pip install -r requirements.txt
```

Python 3.10+ is recommended.

Edit `agent_config.json` as needed for your environment (Windows absolute paths are supported).
`watch_debounce_seconds` controls how long watch mode waits to coalesce burst folder events.

## Run once (daily schedule/cron friendly)

```bash
python pdf_extraction_agent.py --config agent_config.json
```

## Watch mode (continuous)

```bash
python pdf_extraction_agent.py --config agent_config.json --watch
```

## Reliability behavior

- Skips already processed folders via `processing.log.jsonl`
- Uses OCR if direct PDF text extraction is insufficient
- Flags missing required fields per folder row
- Prevents duplicate row insertion by `Folder Path`
- Copies failed folders to error queue and logs reason
- Applies restricted file permissions (`600`) on output Excel and processing log on POSIX systems

## Security note

By default this workflow writes `Password` values to Excel because that column is required.
Set `"mask_password": true` in `agent_config.json` to store masked values instead.
Store output in a secured location with restricted access.
On Windows, POSIX `600` permissions are not applied by the script; use NTFS/Drive sharing controls to restrict access.
