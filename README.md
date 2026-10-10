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

Copy and edit `agent_config.json` values for your machine paths.

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
