# MOJi辞書 Collection Exporter

Personal backup/export tools for your MOJi辞書 (mojidict.com) **收藏 / Collection** items.

This project reverse-engineers the MOJi web client’s network calls and uses the same endpoints to export:

- Saved **words** (`targetType=102`)
- Saved **sentence-like** items (`targetType=103/120`)

> Security note: treat your `sessionToken` like a password. Don’t share it or commit it.

## What’s in this repo

- [moji_exporter.py](moji_exporter.py): main exporter (no third-party deps)
- [reversed_api_ref.md](reversed_api_ref.md): working API notes (Parse CF + REST) and observed quirks
- [run_moji_from_launch.ps1](run_moji_from_launch.ps1): helper that loads env vars from `.vscode/launch.json` and runs the exporter
- saved_webpage/: offline snapshot used for reverse engineering

## Requirements

- Windows PowerShell (examples below)
- Python 3 (recommended: 3.10+)

No extra pip packages are required.

## Getting credentials (from the browser)

While logged in on https://www.mojidict.com:

- `MOJI_SESSION_TOKEN` (Parse sessionToken)
  - Local Storage key: `Parse/<APP_ID>/currentUser` → JSON field `sessionToken`
- `MOJI_INSTALLATION_ID`
  - Local Storage key: `Parse/<APP_ID>/installationId`
- `MOJI_DEVICE_ID`
  - Local Storage key: `MOJi-PC-DeviceID`
- `MOJI_ROOT_FOLDER_ID` (often)
  - Looks like: `ROOT#com.mojitec.mojidict#zh-CN_ja`

See [reversed_api_ref.md](reversed_api_ref.md) for exact DevTools snippets.

## Quick start (PowerShell)

Set env vars and run:

```powershell
$env:MOJI_SESSION_TOKEN = '<SESSION_TOKEN>'
$env:MOJI_INSTALLATION_ID = '<INSTALLATION_ID>'
$env:MOJI_DEVICE_ID = '<DEVICE_ID>'
$env:MOJI_ROOT_FOLDER_ID = 'ROOT#com.mojitec.mojidict#zh-CN_ja'

python .\moji_exporter.py --help
```

### Export words (text)

```powershell
python .\moji_exporter.py --all --mode words --count 50 --output all_words.txt
```

### Export sentences (text)

```powershell
python .\moji_exporter.py --all --mode sentences --count 50 --output all_sentences.txt
```

## Important server behavior (paging clamp)

MOJi’s `folder-fetchContentWithRelatives` appears to clamp deep paging:

- For a given `(fid, sortType, targetTypes)` combination, requests with `pageIndex > 20` repeat page 20.
- With `count=50`, that’s an effective cap of ~1000 items per “view”.

### Workaround: union across sort types and/or folders

The exporter supports unioning multiple partitions and de-duplicating globally:

- `--all-folders`: union across all folders returned by `fetchMyFolders`
- `--sort-types`: union across multiple sort orders
  - Supports ranges: `0..200` or `0-200`

Example:

```powershell
python .\moji_exporter.py --all --mode words --count 50 --all-folders --sort-types 0,1,2,3,4,5,6,10,100 --output all_words_union.txt
```

### Stop early once you reached your goal

If you know roughly how many items you expect, you can stop once that many unique items have been printed:

```powershell
python .\moji_exporter.py --all --mode words --count 50 --all-folders --sort-types 0..200 --expected 4200 --output all_words.txt
```

## JSON progress output (rewrite-on-iteration)

`--json` makes the exporter store results in an in-memory dict and **rewrite** the JSON file after each page iteration.
This is useful for long runs where you want to inspect partial progress.

```powershell
python .\moji_exporter.py --all --mode words --count 50 --all-folders --sort-types 0..200 --expected 4200 --json --output progress_words.json
```

The output JSON contains:

- `meta`: progress info (last folder/sort/page, counts)
- `itemsById`: dictionary keyed by the exporter’s dedupe key (e.g. `102:<id>`, `103:<id>`)

## Using the launcher script

If you’ve stored the env vars inside `.vscode/launch.json`, you can run with:

```powershell
.\run_moji_from_launch.ps1 --all --mode words --count 50 --output all_words.txt
```

## Troubleshooting

- `403` / blocked requests: the exporter already sends browser-like headers, but tokens/IDs must be correct.
- Empty results for words: ensure `--mode words` (or `--target-types 102`). The server may default to sentence-like items if `targetTypes` isn’t sent.
- Excel/Notepad encoding: text output uses UTF-8 with BOM when `--output` is used.

## Disclaimer

These scripts are for personal backup/interoperability. The APIs are reverse-engineered and may change or stop working at any time.
