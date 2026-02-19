#!/usr/bin/env python3
"""Fetch Mojidict saved items via the same Parse Cloud Functions the web app uses.

Usage (PowerShell):
    $env:MOJI_SESSION_TOKEN='...'
    python .\\moji_fetch_saved_sentences.py --limit 10

How to obtain the required values (Edge / Chrome DevTools):

1) Parse session token (`MOJI_SESSION_TOKEN`)
     - If you're logged in on https://www.mojidict.com:
         - Option A (UI): DevTools → Application → Local Storage → find key `Parse/<APP_ID>/currentUser`.
         - Option B (Console): DevTools → Console, run:
                 localStorage.getItem('Parse/<APP_ID>/currentUser')
             It's a JSON string with a field `sessionToken`.
     - Alternative (what you observed while debugging):
         When paused in the bundle code (e.g. 01b20ae.js) where a Parse User instance is in scope,
         the session token is accessible via:
             this.get('sessionToken')
         (Parse.User stores it as an attribute.)

2) Parse installation id (`MOJI_INSTALLATION_ID`)
   - Option A (UI): DevTools → Application → Local Storage → `Parse/<APP_ID>/installationId`
   - Option B (Console):
       localStorage.getItem('Parse/<APP_ID>/installationId')

3) MOJi device id (`MOJI_DEVICE_ID`)
     - Option A (UI): DevTools → Application → Local Storage → `MOJi-PC-DeviceID`
     - Option B (Console):
             localStorage.getItem('MOJi-PC-DeviceID')
         (Sometimes also present as `moji_device_id`. Either works; the script uses whichever you set.)

4) Parse app id (`APP_ID`) and Parse server URL (`PARSE_SERVER`)
     - These are hard-coded in the web app bundles. In our snapshot, we found:
             Parse server URL: https://api.mojidict.com/parse
             Parse app id:     E62VyFVLMiW7kvbtVq3p

5) Parse client version (`--client-version` / `MOJI_PARSE_CLIENT_VERSION`)
     - This is the Parse JS SDK version string that the web app sends as `_ClientVersion`.
     - Default in this script is set to a value verified to work against the `union-api` function.

Security note:
     Treat `sessionToken` like a password. Do not commit it into git or share it.

Notes:
- We keep the session token out of the source file; pass it via env/arg.
- The web app calls Parse Cloud Functions on https://api.mojidict.com/parse.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import urllib.error
import urllib.parse
import urllib.request
from typing import Any, Dict, Iterable, List, Optional, Tuple

API_BASE = "https://api.mojidict.com/app/mojidict"
PARSE_SERVER = "https://api.mojidict.com/parse"
APP_ID = "E62VyFVLMiW7kvbtVq3p"
# NOTE: The Parse JS SDK includes its own VERSION string in requests as `_ClientVersion`
# and/or `X-Parse-Client-Version`. Some endpoints appear sensitive to this value.
# `js3.4.4` was observed to work against `union-api`.
CLIENT_VERSION = "js3.4.4"
G_OS = "PCWeb"

# Optional IDs that the real Parse JS SDK / MOJi web client sends.
# - installationId: stored under `Parse/<APP_ID>/installationId`
# - device id: MOJi web uses `MOJi-PC-DeviceID` (and sometimes `moji_device_id`)
DEFAULT_INSTALLATION_ID = os.environ.get("MOJI_INSTALLATION_ID")
DEFAULT_DEVICE_ID = os.environ.get("MOJI_DEVICE_ID") or os.environ.get("MOJI_PC_DEVICE_ID")

# Optional MOJi request headers (mirrors the axios interceptor in the bundle).
DEFAULT_MOJI_APP_ID = os.environ.get("MOJI_APP_ID", "com.mojitec.mojidict")
DEFAULT_MOJI_APP_VERSION = os.environ.get("MOJI_APP_VERSION", "4.15.4")

# These endpoints are normally called from https://www.mojidict.com.
# Some edge/WAF configs will 403 requests that don't look like a browser.
DEFAULT_ORIGIN = "https://www.mojidict.com"
DEFAULT_REFERER = "https://www.mojidict.com/collection"
DEFAULT_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/122.0.0.0 Safari/537.36"
)


def _http_post_json(url: str, payload: Dict[str, Any], headers: Dict[str, str]) -> Dict[str, Any]:
    data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    req = urllib.request.Request(url, data=data, method="POST")
    for k, v in headers.items():
        req.add_header(k, v)

    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            raw = resp.read().decode("utf-8", errors="replace")
    except urllib.error.HTTPError as e:
        raw = e.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"HTTP {e.code} calling {url}: {raw[:500]}") from e
    except urllib.error.URLError as e:
        raise RuntimeError(f"Network error calling {url}: {e}") from e

    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        raise RuntimeError(f"Non-JSON response calling {url}: {raw[:500]}")


def _http_get_json(url: str, headers: Dict[str, str]) -> Dict[str, Any]:
    req = urllib.request.Request(url, method="GET")
    for k, v in headers.items():
        req.add_header(k, v)

    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            raw = resp.read().decode("utf-8", errors="replace")
    except urllib.error.HTTPError as e:
        raw = e.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"HTTP {e.code} calling {url}: {raw[:500]}" ) from e
    except urllib.error.URLError as e:
        raise RuntimeError(f"Network error calling {url}: {e}") from e

    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        raise RuntimeError(f"Non-JSON response calling {url}: {raw[:500]}")


def fetch_word_detail(
    session_token: str,
    word_id: str,
    *,
    device_id: Optional[str] = DEFAULT_DEVICE_ID,
    moji_app_id: str = DEFAULT_MOJI_APP_ID,
    moji_app_version: str = DEFAULT_MOJI_APP_VERSION,
) -> Dict[str, Any]:
    """Fetch word entry details for a wordId.

    The example sentence items include `target.wordId`, which points to the parent word entry.
    This resolves that id into spell/pron/etc via the Mojidict REST API.
    """

    wid = urllib.parse.quote(str(word_id))
    url = f"{API_BASE}/api/v1/word/detailInfo?wordId={wid}"
    headers = {
        "Accept": "application/json",
        "Origin": DEFAULT_ORIGIN,
        "Referer": "https://www.mojidict.com/",
        "User-Agent": DEFAULT_UA,
        "X-MOJI-OS": G_OS,
        "X-MOJI-APP-VERSION": moji_app_version,
        "x-MOJI-APP-ID": moji_app_id,
        "X-MOJI-TOKEN": session_token,
        "X-MOJI-SESSION-ID": session_token,
    }
    if device_id:
        headers["X-MOJI-DEVICE-ID"] = device_id
    return _http_get_json(url, headers)


def fetch_item_targets(
    session_token: str,
    item_id: str,
    *,
    device_id: Optional[str] = DEFAULT_DEVICE_ID,
    moji_app_id: str = DEFAULT_MOJI_APP_ID,
    moji_app_version: str = DEFAULT_MOJI_APP_VERSION,
) -> Dict[str, Any]:
    """Return the folders (targets) that contain a given item.

    This is what the web app uses for `updateCollected`.
    Useful for discovering where saved words live even when folder listing is empty.
    """

    iid = urllib.parse.quote(str(item_id))
    url = f"{API_BASE}/api/v1/folder/items/{iid}/targets"
    headers = {
        "Accept": "application/json",
        "Origin": DEFAULT_ORIGIN,
        "Referer": "https://www.mojidict.com/",
        "User-Agent": DEFAULT_UA,
        "X-MOJI-OS": G_OS,
        "X-MOJI-APP-VERSION": moji_app_version,
        "x-MOJI-APP-ID": moji_app_id,
        "X-MOJI-TOKEN": session_token,
        "X-MOJI-SESSION-ID": session_token,
    }
    if device_id:
        headers["X-MOJI-DEVICE-ID"] = device_id
    return _http_get_json(url, headers)


def call_cf(
    session_token: str,
    func_name: str,
    params: Dict[str, Any],
    *,
    client_version: str = CLIENT_VERSION,
    installation_id: Optional[str] = DEFAULT_INSTALLATION_ID,
    device_id: Optional[str] = DEFAULT_DEVICE_ID,
    moji_app_id: str = DEFAULT_MOJI_APP_ID,
    moji_app_version: str = DEFAULT_MOJI_APP_VERSION,
) -> Dict[str, Any]:
    url = f"{PARSE_SERVER}/functions/{func_name}"

    # The site’s wrapper adds these fields into the request body.
    payload: Dict[str, Any] = dict(params)
    payload.setdefault("_SessionToken", session_token)
    payload.setdefault("_ApplicationId", APP_ID)
    payload.setdefault("_ClientVersion", client_version)
    payload.setdefault("g_os", G_OS)
    if installation_id:
        # The Parse JS SDK sends this as a body field.
        payload.setdefault("_InstallationId", installation_id)

    headers = {
        "Accept": "*/*",
        "Accept-Language": "ja,en-US;q=0.9,en;q=0.8",
        "Content-Type": "application/json",
        "Origin": DEFAULT_ORIGIN,
        "Referer": DEFAULT_REFERER,
        "User-Agent": DEFAULT_UA,
        # Parse headers
        "X-Parse-Application-Id": APP_ID,
        # Some Parse clients use this legacy casing; harmless if ignored.
        "X-Parse-Application-ID": APP_ID,
        "X-Parse-Client-Version": client_version,
        "X-Parse-Session-Token": session_token,
    }

    # These headers are used by the non-Parse (REST) API, but the MOJi web app
    # also tends to send them widely. Including them helps avoid edge/WAF blocks.
    if device_id:
        headers["X-MOJI-DEVICE-ID"] = device_id
    headers["X-MOJI-OS"] = G_OS
    headers["X-MOJI-APP-VERSION"] = moji_app_version
    headers["x-MOJI-APP-ID"] = moji_app_id
    headers["X-MOJI-TOKEN"] = session_token
    headers["X-MOJI-SESSION-ID"] = session_token
    if installation_id:
        # Some Parse servers accept this as a header too.
        headers["X-Parse-Installation-Id"] = installation_id

    return _http_post_json(url, payload, headers)


def _unwrap_parse_result(resp: Dict[str, Any]) -> Dict[str, Any]:
    """Parse REST /functions/<name> typically returns {"result": <cloudReturn>}"""
    if not isinstance(resp, dict):
        raise RuntimeError(f"Unexpected response type: {type(resp)}")
    if resp.get("result") is None:
        # Parse may return {"result": null} when auth/session is rejected by the edge
        # or when the cloud function returns nothing due to missing context.
        return {"code": -1, "message": "Parse returned null result", "raw": resp}
    if "result" in resp and isinstance(resp["result"], dict):
        return resp["result"]
    if "result" in resp and isinstance(resp["result"], list):
        # Some Cloud Functions (e.g., fetchMyFolders) may return a bare list.
        return {"code": 200, "result": resp["result"]}
    return resp


def _pick_folder(folders: List[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    if not folders:
        return None

    # Heuristic: folders likely containing example sentences.
    keywords = [
        "例文",
        "例句",
        "例",
        "sentence",
        "sentences",
    ]
    for kw in keywords:
        for f in folders:
            title = str(f.get("title", ""))
            if kw.lower() in title.lower():
                return f

    return folders[0]


def _folder_id_of(folder: Dict[str, Any]) -> str:
    # The web bundle maps `targetId` as the folder id.
    # Some APIs also use `objectId`.
    fid = folder.get("targetId") or folder.get("objectId") or folder.get("id") or ""
    return str(fid).strip()


def _folder_title_of(folder: Dict[str, Any]) -> str:
    return str(folder.get("title") or folder.get("name") or "").strip()


def _iter_items_from_folder_content(content: Dict[str, Any]) -> Iterable[Dict[str, Any]]:
    # In the bundle, the app expects an object like:
    # { code, result: [...], pageIndex, totalPage, size, fid, user, folder, ... }
    items = content.get("result")
    if isinstance(items, list):
        for it in items:
            if isinstance(it, dict):
                yield it


def main(argv: List[str]) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--session-token", dest="session_token", default=os.environ.get("MOJI_SESSION_TOKEN"))
    ap.add_argument("--installation-id", dest="installation_id", default=DEFAULT_INSTALLATION_ID)
    ap.add_argument("--device-id", dest="device_id", default=DEFAULT_DEVICE_ID)
    ap.add_argument(
        "--pfid",
        dest="pfid",
        default=os.environ.get("MOJI_ROOT_FOLDER_ID") or os.environ.get("MOJI_PFID"),
        help="Parent folder id for fetchMyFolders (often ROOT#com.mojitec.mojidict#zh-CN_ja)",
    )
    ap.add_argument(
        "--client-version",
        dest="client_version",
        default=os.environ.get("MOJI_PARSE_CLIENT_VERSION", CLIENT_VERSION),
        help="Parse client version string (default matches current web bundle)",
    )
    ap.add_argument("--folder-id", dest="folder_id", default=None)
    ap.add_argument(
        "--targets-for-item",
        dest="targets_for_item",
        default=None,
        help="Print the folders that contain this itemId/wordId (web: GET /api/v1/folder/items/<id>/targets) and exit.",
    )
    ap.add_argument("--page", dest="page", type=int, default=1)
    ap.add_argument("--count", dest="count", type=int, default=20)
    ap.add_argument("--sort-type", dest="sort_type", type=int, default=0)
    ap.add_argument(
        "--sort-types",
        dest="sort_types",
        default=None,
        help="Comma-separated sortType values (and/or inclusive ranges like 0-200 or 0..200) to iterate in --all mode (unions results across sorts), e.g. 0,1,2,3,4,5,10,100",
    )
    ap.add_argument("--limit", dest="limit", type=int, default=10)
    ap.add_argument(
        "--mode",
        dest="mode",
        choices=["sentences", "words", "both"],
        default="sentences",
        help="What to export from the folder: sentences (103/120), words (102), or both.",
    )
    ap.add_argument(
        "--target-types",
        dest="target_types",
        default=None,
        help="Comma-separated targetType allowlist (overrides --mode), e.g. 102,103,120",
    )
    ap.add_argument(
        "--output",
        dest="output",
        default=None,
        help="Write exported items to this file (UTF-8 with BOM). Recommended on Windows.",
    )
    ap.add_argument(
        "--json",
        dest="json_output",
        action="store_true",
        help="Write results as JSON (a dict) to --output, and rewrite it after each page iteration to show progress.",
    )
    ap.add_argument(
        "--all",
        dest="fetch_all",
        action="store_true",
        help="Fetch all pages of saved items in the selected folder",
    )
    ap.add_argument(
        "--all-folders",
        dest="all_folders",
        action="store_true",
        help="Export across ALL folders returned by fetchMyFolders (dedupes output across folders).",
    )
    ap.add_argument(
        "--max-pages",
        dest="max_pages",
        type=int,
        default=200,
        help="Safety cap for --all mode (prevents infinite loops if the server repeats pages).",
    )
    ap.add_argument(
        "--stop-after-no-new",
        dest="stop_after_no_new",
        type=int,
        default=3,
        help="In --all mode, stop after this many consecutive pages yield zero new item IDs.",
    )
    ap.add_argument(
        "--expected",
        dest="expected",
        type=int,
        default=0,
        help="In --all mode (especially with --sort-types/--all-folders), stop once this many UNIQUE items have been printed (0 disables).",
    )
    args = ap.parse_args(argv)

    # Windows consoles (and redirected stdout) may default to a legacy encoding (e.g. cp936/gbk)
    # which can't represent all Japanese punctuation (e.g. U+30FB "・").
    # Best-effort: force UTF-8 so interactive printing works reliably.
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[attr-defined]
    except Exception:
        pass
    try:
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[attr-defined]
    except Exception:
        pass

    if not args.session_token:
        print("Missing session token. Set MOJI_SESSION_TOKEN or pass --session-token.", file=sys.stderr)
        return 2

    if args.targets_for_item:
        try:
            targets_resp = fetch_item_targets(
                args.session_token,
                str(args.targets_for_item),
                device_id=args.device_id,
            )
        except Exception as e:
            print(f"Failed to fetch targets for item {args.targets_for_item!r}: {e}", file=sys.stderr)
            return 1

        # The web bundle treats `code` as truthy on success, and returns `list`.
        targets_list = targets_resp.get("list") if isinstance(targets_resp, dict) else None

        print(json.dumps(targets_resp, ensure_ascii=False, indent=2))
        if isinstance(targets_list, list) and targets_list:
            folder_ids = []
            for x in targets_list:
                if isinstance(x, dict) and x.get("parentFolderId"):
                    folder_ids.append(str(x.get("parentFolderId")))
            if folder_ids:
                print("\nFolder IDs (parentFolderId):")
                for fid in sorted(set(folder_ids)):
                    print(f"- {fid}")
        return 0

    if args.json_output and not args.output:
        print("--json requires --output <file> (so progress can be rewritten).", file=sys.stderr)
        return 2

    # Keep progress logs separate; JSON output is written to a file.
    log_fp = sys.stderr if (args.fetch_all or args.json_output) else sys.stdout

    out_fp = sys.stdout
    out_close = False
    if args.output and not args.json_output:
        # Use UTF-8 with BOM to make encoding auto-detection reliable on Windows.
        out_fp = open(args.output, "w", encoding="utf-8-sig", newline="\n")
        out_close = True

    try:
        # 1) Fetch folders
        folders_params: Dict[str, Any] = {}
        if args.pfid:
            folders_params["pfid"] = args.pfid

        folders_resp = call_cf(
            args.session_token,
            "fetchMyFolders",
            folders_params,
            client_version=args.client_version,
            installation_id=args.installation_id,
            device_id=args.device_id,
        )
        folders_payload = _unwrap_parse_result(folders_resp)
        if int(folders_payload.get("code", 0)) != 200:
            print("fetchMyFolders failed:", file=log_fp)
            print(json.dumps(folders_payload, ensure_ascii=False, indent=2), file=log_fp)
            return 1

        folders = folders_payload.get("result")
        if not isinstance(folders, list):
            print("Unexpected folders shape:", file=log_fp)
            print(json.dumps(folders_payload, ensure_ascii=False, indent=2), file=log_fp)
            return 1

        # Some accounts return an empty list when called with pfid.
        # Retry without pfid to discover user folders.
        if args.pfid and len(folders) == 0:
            folders_resp2 = call_cf(
                args.session_token,
                "fetchMyFolders",
                {},
                client_version=args.client_version,
                installation_id=args.installation_id,
                device_id=args.device_id,
            )
            folders_payload2 = _unwrap_parse_result(folders_resp2)
            if int(folders_payload2.get("code", 0)) == 200 and isinstance(folders_payload2.get("result"), list):
                folders = folders_payload2.get("result")

        print(f"Folders: {len(folders)}", file=log_fp)
        for f in folders[:30]:
            if not isinstance(f, dict):
                continue
            print(f"- {_folder_id_of(f)}  {_folder_title_of(f)}", file=log_fp)

        export_folders: List[Tuple[str, str]] = []

        if args.folder_id:
            folder = next(
                (f for f in folders if isinstance(f, dict) and _folder_id_of(f) == str(args.folder_id)),
                None,
            )
            if folder is None:
                print(f"Folder id not found in fetchMyFolders: {args.folder_id}", file=log_fp)
                return 1
            fid = _folder_id_of(folder)
            title = _folder_title_of(folder)
            export_folders = [(fid, title or "(selected)")]
            print(f"\nUsing folder: {fid}  {title}", file=log_fp)
        elif args.all_folders:
            # Export across all folders returned by fetchMyFolders.
            for f in folders:
                if not isinstance(f, dict):
                    continue
                fid = _folder_id_of(f)
                if not fid:
                    continue
                title = _folder_title_of(f)
                export_folders.append((fid, title))

            # Also include the pfid/root itself as a folder id (some accounts have items directly under it).
            if args.pfid:
                pfid_s = str(args.pfid).strip()
                if pfid_s and all(pfid_s != x[0] for x in export_folders):
                    export_folders.insert(0, (pfid_s, "(root/pfid)"))

            if not export_folders:
                print("No folders returned.", file=log_fp)
                return 1
            print(f"\nExporting across {len(export_folders)} folders (--all-folders)", file=log_fp)
        else:
            folder = _pick_folder([f for f in folders if isinstance(f, dict)])
            if not folder:
                if args.pfid:
                    fid = str(args.pfid)
                    title = "(root)"
                    export_folders = [(fid, title)]
                    print(f"\nNo folders returned; trying --pfid as folder id: {fid}", file=log_fp)
                else:
                    print("No folders returned.", file=log_fp)
                    return 1
            else:
                fid = _folder_id_of(folder)
                title = _folder_title_of(folder)
                export_folders = [(fid, title)]
                print(f"\nUsing folder: {fid}  {title}", file=log_fp)

        # 2) Fetch folder content (single page or all pages)
        # From the web bundle:
        # - 102: word
        # - 103/120: (example/voice) sentence-like targets
        # - 10: bookmark/link, 200: news, 210: article, 1000: folder, etc.
        def _parse_target_types(s: Optional[str]) -> Optional[set[int]]:
            if not s:
                return None
            out: set[int] = set()
            for part in str(s).split(","):
                part = part.strip()
                if not part:
                    continue
                try:
                    out.add(int(part))
                except ValueError:
                    raise SystemExit(f"Invalid --target-types entry: {part!r}")
            return out or None

        explicit_types = _parse_target_types(args.target_types)
        if explicit_types is not None:
            allowed_types = explicit_types
        else:
            if args.mode == "sentences":
                allowed_types = {120, 103}
            elif args.mode == "words":
                allowed_types = {102}
            else:
                allowed_types = {102, 103, 120}

        # IMPORTANT: The web client passes `targetTypes` to `folder-fetchContentWithRelatives`
        # unless the filter is in a special "reset" state. If we don't pass it, the server may
        # default to sentence-like items only (103/120), which makes `--mode words` appear empty.
        server_target_types = sorted(allowed_types)

        word_cache: Dict[str, Dict[str, Any]] = {}
        # Global output dedupe across folders.
        seen_item_ids_global: set[str] = set()
        printed_total = 0
        stop_everything = False

        # JSON mode: store results in-memory and rewrite the output file after each page.
        results_by_id: Dict[str, Dict[str, Any]] = {}

        def _rewrite_json_progress(*, folder_id: str, folder_title: str, sort_type: int, page_index: int) -> None:
            if not args.json_output:
                return
            if not args.output:
                return

            payload = {
                "meta": {
                    "mode": args.mode,
                    "targetTypes": server_target_types,
                    "expected": int(args.expected) if args.expected else 0,
                    "printedTotal": int(printed_total),
                    "uniqueItems": int(len(results_by_id)),
                    "last": {
                        "folderId": folder_id,
                        "folderTitle": folder_title,
                        "sortType": int(sort_type),
                        "pageIndex": int(page_index),
                    },
                    "stopped": bool(stop_everything),
                },
                "itemsById": results_by_id,
            }

            tmp_path = str(args.output) + ".tmp"
            with open(tmp_path, "w", encoding="utf-8", newline="\n") as fp:
                json.dump(payload, fp, ensure_ascii=False, indent=2)
                fp.write("\n")
            os.replace(tmp_path, str(args.output))

        def _parse_sort_types(s: Optional[str]) -> List[int]:
            if not s:
                return []
            out: List[int] = []
            for part in str(s).split(","):
                part = part.strip()
                if not part:
                    continue

                # Allow inclusive ranges like "0-200" or "0..200".
                if ".." in part or "-" in part:
                    raw = part.replace("..", "-")
                    a_s, sep, b_s = raw.partition("-")
                    a_s = a_s.strip()
                    b_s = b_s.strip()
                    if sep and a_s.isdigit() and b_s.isdigit():
                        a_i = int(a_s)
                        b_i = int(b_s)
                        step = 1 if a_i <= b_i else -1
                        out.extend(list(range(a_i, b_i + step, step)))
                        continue

                try:
                    out.append(int(part))
                except ValueError:
                    raise SystemExit(f"Invalid --sort-types entry: {part!r}")
            # preserve order, unique
            uniq: List[int] = []
            seen: set[int] = set()
            for x in out:
                if x in seen:
                    continue
                uniq.append(x)
                seen.add(x)
            return uniq

        sort_types_list = _parse_sort_types(args.sort_types)
        if args.fetch_all and sort_types_list:
            active_sort_types = sort_types_list
        else:
            active_sort_types = [int(args.sort_type)]

        def _export_one_folder(folder_id: str, folder_title: str, sort_type: int) -> None:
            nonlocal printed_total
            nonlocal stop_everything

            page_index = args.page
            total_pages: Optional[int] = None
            no_new_streak = 0

            # Track overlap/repeat *within* the folder for pagination logic.
            seen_item_ids_in_folder: set[str] = set()

            while True:
                if stop_everything:
                    break
                content_params = {
                    "fid": folder_id,
                    "sortType": sort_type,
                    "pageIndex": page_index,
                    "count": args.count,
                }
                if server_target_types:
                    content_params["targetTypes"] = server_target_types
                content_resp = call_cf(
                    args.session_token,
                    "folder-fetchContentWithRelatives",
                    content_params,
                    client_version=args.client_version,
                    installation_id=args.installation_id,
                    device_id=args.device_id,
                )
                content_payload = _unwrap_parse_result(content_resp)
                if int(content_payload.get("code", 0)) != 200:
                    print("folder-fetchContentWithRelatives failed:", file=log_fp)
                    print(json.dumps(content_payload, ensure_ascii=False, indent=2), file=log_fp)
                    raise RuntimeError("folder-fetchContentWithRelatives failed")

                if total_pages is None:
                    tp = content_payload.get("totalPage")
                    try:
                        tp_i = int(tp) if tp is not None else None
                    except Exception:
                        tp_i = None
                    if tp_i is not None and tp_i > 0:
                        total_pages = tp_i

                items = list(_iter_items_from_folder_content(content_payload))
                if not args.fetch_all:
                    print(f"\nItems in page: {len(items)}", file=log_fp)
                if not items:
                    break

                # Useful diagnostics for pagination overlap / repetition.
                first_item_id: Optional[str] = None
                last_item_id: Optional[str] = None

                type_counts: Dict[int, int] = {}
                new_any_in_page = 0
                new_selected_in_page = 0
                for it in items:
                    tt = it.get("targetType")
                    if isinstance(tt, int):
                        type_counts[tt] = type_counts.get(tt, 0) + 1
                    target = it.get("target")
                    if not isinstance(target, dict):
                        continue

                    item_id = target.get("objectId") or target.get("id")
                    if not item_id:
                        item_id = f"{target.get('wordId','')}::{target.get('title','')}"
                    item_id_s = f"{tt}:{item_id}"

                    if first_item_id is None:
                        first_item_id = item_id_s
                    last_item_id = item_id_s

                    if args.fetch_all:
                        if item_id_s in seen_item_ids_in_folder:
                            continue
                        seen_item_ids_in_folder.add(item_id_s)
                        new_any_in_page += 1

                    if tt not in allowed_types:
                        continue

                    # Global output dedupe (across folders)
                    if item_id_s in seen_item_ids_global:
                        continue
                    seen_item_ids_global.add(item_id_s)

                    if args.fetch_all:
                        new_selected_in_page += 1

                    if tt in (103, 120):
                        # Sentence-like items: resolve parent word via target.wordId
                        word_id = target.get("wordId")
                        word_spell = ""
                        word_pron = ""
                        word_id_s = str(word_id) if word_id is not None else ""
                        if word_id_s:
                            if word_id_s not in word_cache:
                                try:
                                    word_cache[word_id_s] = fetch_word_detail(
                                        args.session_token,
                                        word_id_s,
                                        device_id=args.device_id,
                                    )
                                except Exception as e:
                                    word_cache[word_id_s] = {"_error": str(e)}
                            wresp = word_cache.get(word_id_s) or {}
                            w = wresp.get("word") if isinstance(wresp, dict) else None
                            if isinstance(w, dict):
                                word_spell = str(w.get("spell") or "").strip()
                                word_pron = str(w.get("pron") or "").strip()

                        jp = target.get("title") or target.get("notationTitle") or ""
                        trans = target.get("trans") or target.get("excerpt") or ""

                        jp_s = str(jp).strip()
                        trans_s = str(trans).strip()

                        if jp_s:
                            if args.json_output:
                                results_by_id[item_id_s] = {
                                    "targetType": tt,
                                    "itemId": str(item_id),
                                    "wordId": word_id_s,
                                    "word": {
                                        "spell": word_spell,
                                        "pron": word_pron,
                                    },
                                    "jp": jp_s,
                                    "trans": trans_s,
                                    "folder": {"id": folder_id, "title": folder_title},
                                    "sortType": int(sort_type),
                                }
                            else:
                                print("\n---", file=out_fp)
                                if word_id_s:
                                    head = word_spell
                                    if word_pron and word_pron != head:
                                        head = f"{head} [{word_pron}]" if head else f"[{word_pron}]"
                                    head = f"{head} (wordId={word_id_s})" if head else f"wordId={word_id_s}"
                                    print(head, file=out_fp)
                                print(jp_s, file=out_fp)
                                if trans_s:
                                    print(trans_s, file=out_fp)
                            printed_total += 1
                            if args.fetch_all and int(args.expected) > 0 and printed_total >= int(args.expected):
                                stop_everything = True
                                break

                    elif tt == 102:
                        # Word entries: target itself is the word.
                        # It typically contains spell/pron/excerpt already.
                        word_id = target.get("objectId") or target.get("id")
                        word_id_s = str(word_id) if word_id is not None else ""

                        spell = str(target.get("spell") or target.get("title") or "").strip()
                        pron = str(target.get("pron") or "").strip()
                        accent = str(target.get("accent") or "").strip()
                        excerpt = str(target.get("excerpt") or "").strip()

                        # If the list item lacks details, fall back to detailInfo.
                        if word_id_s and (not spell or not pron):
                            if word_id_s not in word_cache:
                                try:
                                    word_cache[word_id_s] = fetch_word_detail(
                                        args.session_token,
                                        word_id_s,
                                        device_id=args.device_id,
                                    )
                                except Exception as e:
                                    word_cache[word_id_s] = {"_error": str(e)}
                            wresp = word_cache.get(word_id_s) or {}
                            w = wresp.get("word") if isinstance(wresp, dict) else None
                            if isinstance(w, dict):
                                spell = spell or str(w.get("spell") or "").strip()
                                pron = pron or str(w.get("pron") or "").strip()
                                accent = accent or str(w.get("accent") or "").strip()
                                excerpt = excerpt or str(w.get("excerpt") or "").strip()

                        if spell or excerpt:
                            if args.json_output:
                                results_by_id[item_id_s] = {
                                    "targetType": tt,
                                    "itemId": str(item_id),
                                    "wordId": word_id_s,
                                    "spell": spell,
                                    "pron": pron,
                                    "accent": accent,
                                    "excerpt": excerpt,
                                    "folder": {"id": folder_id, "title": folder_title},
                                    "sortType": int(sort_type),
                                }
                            else:
                                print("\n---", file=out_fp)
                                head = spell
                                if pron:
                                    head = f"{head} [{pron}]" if head else f"[{pron}]"
                                if accent:
                                    head = f"{head} {accent}".strip()
                                if word_id_s:
                                    head = f"{head} (wordId={word_id_s})" if head else f"wordId={word_id_s}"
                                if head:
                                    print(head, file=out_fp)
                                if excerpt:
                                    print(excerpt, file=out_fp)
                            printed_total += 1
                            if args.fetch_all and int(args.expected) > 0 and printed_total >= int(args.expected):
                                stop_everything = True
                                break

                    if not args.fetch_all and printed_total >= args.limit:
                        break

                if stop_everything:
                    break

                # JSON mode: rewrite progress after each page iteration.
                _rewrite_json_progress(
                    folder_id=folder_id,
                    folder_title=folder_title,
                    sort_type=sort_type,
                    page_index=page_index,
                )

                if not args.fetch_all:
                    print("\nTargetType counts (this page):", file=log_fp)
                    for k in sorted(type_counts):
                        print(f"- {k}: {type_counts[k]}", file=log_fp)
                    if printed_total == 0:
                        print("\nNo sentence-like items found in this folder page.", file=log_fp)
                        print("Try a different folder id via --folder-id <id> or increase --page/--count.", file=log_fp)
                    return

                # --all mode: advance pages
                if new_any_in_page == 0:
                    no_new_streak += 1
                else:
                    no_new_streak = 0

                types_s = " ".join(f"{k}={type_counts[k]}" for k in sorted(type_counts))
                server_page_index = content_payload.get("pageIndex")
                server_total_page = content_payload.get("totalPage")
                print(
                    f"[folder {folder_id} {folder_title!r}] [sortType {sort_type}] [page {page_index}] newAny={new_any_in_page} newSelected={new_selected_in_page} totalPrinted={printed_total} noNewStreak={no_new_streak} server.pageIndex={server_page_index} server.totalPage={server_total_page} first={first_item_id} last={last_item_id} types: {types_s}",
                    file=log_fp,
                )

                # Stop conditions:
                # - If the server repeats pages, we may see overlap; don't stop on the first 0-new page.
                #   Instead, stop after a small streak.
                if stop_everything:
                    break
                if no_new_streak >= max(1, int(args.stop_after_no_new)):
                    break
                if total_pages is not None and page_index >= total_pages:
                    break
                if int(args.max_pages) > 0 and (page_index - args.page + 1) >= int(args.max_pages):
                    break
                page_index += 1

            # Ensure we persist progress when a folder/sort finishes.
            _rewrite_json_progress(
                folder_id=folder_id,
                folder_title=folder_title,
                sort_type=sort_type,
                page_index=page_index,
            )

        for folder_id, folder_title in export_folders:
            if not folder_id:
                continue
            for st in active_sort_types:
                if args.fetch_all and len(active_sort_types) > 1:
                    print(f"\n== Folder {folder_id} {folder_title!r} sortType={st} ==", file=log_fp)
                _export_one_folder(folder_id, folder_title, st)
                if stop_everything:
                    break
            if stop_everything:
                break
            if not args.fetch_all:
                # Single-page mode exits after first folder.
                break

        print(f"\nDone. Printed items: {printed_total}", file=log_fp)

        # Final JSON rewrite (marks stopped/meta state consistently).
        if args.json_output and export_folders:
            fid0, title0 = export_folders[0]
            _rewrite_json_progress(folder_id=fid0, folder_title=title0, sort_type=active_sort_types[0], page_index=int(args.page))
        return 0
    finally:
        if out_close:
            out_fp.close()


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
