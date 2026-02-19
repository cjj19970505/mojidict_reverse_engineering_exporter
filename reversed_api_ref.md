# MOJi辞書 – Working API Reference (reverse-engineered)

This document summarizes **MOJi APIs that were confirmed working** from the web client snapshot and live calls.

> Security note: treat `sessionToken` like a password. Do not share it or commit it.

---

## Quick glossary

- **Parse Cloud Functions (CF)**: JSON RPC-like endpoints under `https://api.mojidict.com/parse/functions/<funcName>`
- **REST API**: HTTP endpoints under `https://api.mojidict.com/app/mojidict/...`

---

## Required values (how to get them)

All of these come from the browser while logged in at `https://www.mojidict.com`.

### Parse App ID

- `APP_ID`: `E62VyFVLMiW7kvbtVq3p`

### Session token (auth)

- `sessionToken` is stored in Local Storage:
  - Key: `Parse/<APP_ID>/currentUser`
  - JSON field: `sessionToken`

Console:

```js
const APP_ID = 'E62VyFVLMiW7kvbtVq3p';
JSON.parse(localStorage.getItem(`Parse/${APP_ID}/currentUser`)).sessionToken
```

### Installation ID

- Local Storage key: `Parse/<APP_ID>/installationId`

Console:

```js
const APP_ID = 'E62VyFVLMiW7kvbtVq3p';
localStorage.getItem(`Parse/${APP_ID}/installationId`)
```

### Device ID

- Local Storage key (web): `MOJi-PC-DeviceID`

Console:

```js
localStorage.getItem('MOJi-PC-DeviceID')
```

### Root folder id

The web app uses a root folder id like:

- `ROOT#com.mojitec.mojidict#zh-CN_ja`

This may appear inside localStorage entries such as recent-folder metadata.

---

## Common “browser-like” request headers

Some requests may be blocked (e.g., `403`) unless they look like browser traffic.

Recommended:

- `User-Agent`: a normal desktop browser UA
- `Origin`: `https://www.mojidict.com`
- `Referer`: `https://www.mojidict.com/collection`
- `Accept`: `application/json, text/plain, */*`
- `Content-Type`: `application/json` (for POST)

---

## Parse Cloud Functions (confirmed working)

### Base

- Base URL: `https://api.mojidict.com/parse/functions/`
- Method: `POST`
- Content-Type: `application/json`

### Parse headers

These are the key headers used by the web client and confirmed working:

- `X-Parse-Application-Id: <APP_ID>`
- `X-Parse-Client-Version: js3.4.4` (value that was verified to work)
- `X-Parse-Session-Token: <sessionToken>` (required for user data)
- `X-Parse-Installation-Id: <installationId>` (recommended)

### CF request body shape

The web client effectively sends:

```json
{
  "_ApplicationId": "E62VyFVLMiW7kvbtVq3p",
  "_ClientVersion": "js3.4.4",
  "_InstallationId": "<installationId>",
  "_SessionToken": "<sessionToken>",
  "g_os": "PCWeb",
  "...your function params...": "..."
}
```

In practice, many CF calls work if you provide the session token via the header and mirror these fields in the body.

### CF response shape

Parse CF responses are commonly:

```json
{ "result": { "code": 200, "result": [ ... ], "totalPage": 3, ... } }
```

But some calls may return:

- `{"result": []}`
- `{"result": null}`

So client code should defensively unwrap.

---

### 1) `fetchMyFolders` (list folders)

- Endpoint: `POST https://api.mojidict.com/parse/functions/fetchMyFolders`
- Auth: **Yes** (`X-Parse-Session-Token`)

Parameters (body):

- `pfid` (optional): parent folder id. For root use something like `ROOT#com.mojitec.mojidict#zh-CN_ja`.

Example curl:

```bash
curl -sS 'https://api.mojidict.com/parse/functions/fetchMyFolders' \
  -H 'Content-Type: application/json' \
  -H 'X-Parse-Application-Id: E62VyFVLMiW7kvbtVq3p' \
  -H 'X-Parse-Client-Version: js3.4.4' \
  -H 'X-Parse-Session-Token: <SESSION_TOKEN>' \
  -H 'X-Parse-Installation-Id: <INSTALLATION_ID>' \
  -d '{"pfid":"ROOT#com.mojitec.mojidict#zh-CN_ja"}'
```

Notes:

- Some accounts have **0 custom subfolders**; the root folder still contains items.

---

### 2) `folder-fetchContentWithRelatives` (fetch folder items)

- Endpoint: `POST https://api.mojidict.com/parse/functions/folder-fetchContentWithRelatives`
- Auth: **Yes**

Parameters (body):

- `fid` (required): folder id
- `count` (required): page size (e.g. 50)
- `pageIndex` (required): page index (observed to behave like **1-based** paging in practice)
- `sortType` (optional): sort mode (0 used successfully)
- `targetTypes` (optional but important): list of targetType integers to fetch

Important behavior (confirmed):

- If you do **not** pass `targetTypes`, the server may return only sentence-like items (`103`) even when the folder contains saved words.
- To fetch saved words you must pass `targetTypes: [102]`.

Response highlights:

- The returned items list is usually in `result.result`.
- Word targets were observed with `targetType` `102`.
- Sentence-like targets were observed with `targetType` in `{103, 120}`.
- A sentence target usually contains:
  - `target.title` (JP sentence)
  - `target.trans` or `target.excerpt` (translation/snippet)
  - `target.wordId` (used to resolve the dictionary entry)
  - `target.objectId` (a stable id, useful for dedupe)

#### `targetType` mapping (observed)

MOJi does not appear to publicly document what `targetType` values mean. The meanings below are inferred from **live responses** and what fields show up for each type.

| targetType | Meaning (best current understanding) | Why we believe this | How to verify quickly |
|---:|---|---|---|
| 102 | Saved **word** (dictionary entry) | When requesting `targetTypes:[102]`, the folder content returns items that print as word entries in the exporter (spell/pron/etc). Also `GET /api/v1/folder/items/<itemId>/targets` can return `targetType:102` for a known saved word. | Run: `./run_moji_from_launch.ps1 --mode words --count 50 --limit 5` (or `--target-types 102`). You should see only type 102 in the script’s per-page type counts. |
| 103 | Saved **sentence-like** item (example sentence / sentence card) | Default / unfiltered collection fetches often return only `103`, and these items commonly contain `target.title` (JP sentence) + translation fields and `target.wordId` to resolve the dictionary entry via `/api/v1/word/detailInfo`. | Run: `./run_moji_from_launch.ps1 --mode sentences --count 50 --limit 5` (or `--target-types 103`). |
| 120 | Also **sentence-like** (a second sentence subtype) | Observed alongside `103` in some pages; payload shape looks similar (sentence text + translation/snippet). Treated the same as sentences in the exporter. | Run: `./run_moji_from_launch.ps1 --target-types 120 --count 50 --limit 5` and compare fields to a `103` page. |

Notes:

- There may be additional `targetType` values not seen in this snapshot/session.
- To discover new types, fetch with a broad allowlist (e.g. `--target-types 102,103,120`) and watch the script’s “TargetType counts (this page)” output.
- Server-side filtering matters: if you do not send `targetTypes` in the CF request body, the server may omit types entirely (e.g. only returning `103`).

Example curl:

```bash
curl -sS 'https://api.mojidict.com/parse/functions/folder-fetchContentWithRelatives' \
  -H 'Content-Type: application/json' \
  -H 'X-Parse-Application-Id: E62VyFVLMiW7kvbtVq3p' \
  -H 'X-Parse-Client-Version: js3.4.4' \
  -H 'X-Parse-Session-Token: <SESSION_TOKEN>' \
  -H 'X-Parse-Installation-Id: <INSTALLATION_ID>' \
  -d '{"fid":"ROOT#com.mojitec.mojidict#zh-CN_ja","count":50,"pageIndex":1,"sortType":0,"targetTypes":[103,120]}'
```

Example body to fetch saved words:

```json
{
  "fid": "ROOT#com.mojitec.mojidict#zh-CN_ja",
  "count": 50,
  "pageIndex": 1,
  "sortType": 0,
  "targetTypes": [102]
}
```

Pagination gotcha:

- `totalPage` was observed returning `0` even when more data existed.
- A robust client should continue fetching pages until a page yields **no new item IDs** (pages can overlap/repeat).

Pagination limits (confirmed 2026-02-18):

- For a given `(fid, sortType, targetTypes)` combination, the server appears to **clamp deep paging**:
  - Requesting `pageIndex > 20` returns the **same content as page 20**.
  - The server may report `server.pageIndex = 20` in the response when you ask for higher pages.
  - With `count=50`, this produces a hard ceiling of roughly `20 * 50 = 1000` items for that particular “view”.
- `count > 50` did not reliably increase items per page in observed runs.

Practical workaround:

- Treat `sortType` (and potentially folder splits) as a **partition key**: union results across multiple `sortType` values and/or multiple folders, then dedupe by item id.

#### `sortType` mapping (observed)

These values come from the web bundle’s sort menu plus live experiments.

| sortType | Meaning (best current understanding) | Notes |
|---:|---|---|
| 0 | default | menu value |
| 1 | spell | menu value |
| 2 | data_type | menu value |
| 3 | updated_at | menu value |
| 4 | created_at | menu value |
| 5 | created_at_ascend | menu value |
| 10 | customize | menu value |
| 100 | reverse | menu value |
| 6 | unknown (but returns a different slice) | experimentally yielded additional unique saved words beyond the 0/1/2/3/4/5/10/100 union |

---

### 3) `union-api` (connectivity test)

- Endpoint: `POST https://api.mojidict.com/parse/functions/union-api`
- Auth: Not always required for a basic “it responds” check.

This CF was used to verify that Parse requests can succeed from your environment.

---

## REST API (confirmed working)

### Base

- Base URL: `https://api.mojidict.com/app/mojidict`

### 1) Word detail

- Endpoint: `GET https://api.mojidict.com/app/mojidict/api/v1/word/detailInfo?wordId=<wordId>`

Where `wordId` comes from Parse sentence targets: `target.wordId`.

Response notes:

- Returns a JSON object containing at least `word`.
- Useful fields:
  - `word.spell`
  - `word.pron`

Recommended headers (mirroring the web client helps):

- `Origin: https://www.mojidict.com`
- `Referer: https://www.mojidict.com/collection`
- Optionally some MOJi headers seen in the bundle (not always required):
  - `X-MOJI-SESSION-ID: <SESSION_TOKEN>`
  - `X-MOJI-DEVICE-ID: <DEVICE_ID>`
  - `X-MOJI-OS: PCWeb`
  - `x-MOJI-APP-ID: com.mojitec.mojidict`
  - `X-MOJI-APP-VERSION: 4.15.4`

Example curl:

```bash
curl -sS 'https://api.mojidict.com/app/mojidict/api/v1/word/detailInfo?wordId=198910127' \
  -H 'Origin: https://www.mojidict.com' \
  -H 'Referer: https://www.mojidict.com/collection'
```

### 2) Item → folders ("updateCollected")

- Endpoint: `GET https://api.mojidict.com/app/mojidict/api/v1/folder/items/<itemId>/targets`
- Purpose: Given an item id (e.g. a `wordId`), return the list of folders that contain it.
- Web bundle behavior: treats `code` as truthy on success and reads `list`.
- Why it matters: If `fetchMyFolders` returns empty (or you don’t know which folder your saved words are in), this endpoint lets you discover the correct folder id(s) to pass as `fid` into `folder-fetchContentWithRelatives`.

---

## Working implementation in this workspace

- The script [moji_exporter.py](moji_exporter.py) implements:
  - Parse CF calls (`fetchMyFolders`, `folder-fetchContentWithRelatives`)
  - REST word detail resolution (`/api/v1/word/detailInfo`)
  - `--all` paging with dedupe (because `totalPage` may be 0)
  - `--all-folders` to union across all folders returned by `fetchMyFolders`
  - `--sort-types` to union across multiple `sortType` partitions (helps bypass the ~1000-items per-sort clamp)
  - `--expected` to stop early once you’ve printed N unique items (useful during sortType brute-force)
  - `--json` to write the output file as JSON (a dict) and rewrite it after each page iteration (progress file)
  - `--output <file>` to write UTF-8 with BOM on Windows

Suggested command (PowerShell):

```powershell
$env:MOJI_SESSION_TOKEN='<SESSION_TOKEN>'
$env:MOJI_INSTALLATION_ID='<INSTALLATION_ID>'
$env:MOJI_DEVICE_ID='<DEVICE_ID>'
$env:MOJI_ROOT_FOLDER_ID='ROOT#com.mojitec.mojidict#zh-CN_ja'
python .\moji_exporter.py --all --count 50 --output all.txt
```

Suggested command to export words beyond the ~1000-per-sort cap (PowerShell):

```powershell
$env:MOJI_SESSION_TOKEN='<SESSION_TOKEN>'
$env:MOJI_INSTALLATION_ID='<INSTALLATION_ID>'
$env:MOJI_DEVICE_ID='<DEVICE_ID>'
$env:MOJI_ROOT_FOLDER_ID='ROOT#com.mojitec.mojidict#zh-CN_ja'
python .\moji_exporter.py --all --mode words --count 50 --all-folders --sort-types 0,1,2,3,4,5,6,10,100 --output all_words_union.txt
```
