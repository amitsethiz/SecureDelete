#!/usr/bin/env python3
"""
SecureDelete - Secure File Shredder & Free Space Wiper

Commands:
  shred  - Securely delete specific files or folders (instant)
  wipe   - Wipe all free disk space to destroy previously deleted files

Usage:
    python securedelete.py shred secret.txt            # Shred a single file
    python securedelete.py shred file1.txt file2.pdf   # Shred multiple files
    python securedelete.py shred "C:\\Secrets" -r       # Shred entire folder
    python securedelete.py shred *.log                 # Shred by pattern
    python securedelete.py wipe C:                     # Wipe free space (3-pass)
    python securedelete.py wipe C: -p 7 --cipher       # Maximum security wipe
    python securedelete.py recover                     # Recover deleted files
"""

import argparse
import glob
import os
import secrets
import shutil
import string
import subprocess
import sys
import time
import stat


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------
CHUNK_SIZE = 4 * 1024 * 1024  # 4 MB write chunks
TEMP_DIR_NAME = ".securedelete_wipe"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def get_free_space(path: str) -> int:
    """Return free space in bytes for the drive containing `path`."""
    usage = shutil.disk_usage(path)
    return usage.free


def format_bytes(n: int) -> str:
    """Human-readable byte size."""
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if abs(n) < 1024:
            return f"{n:.2f} {unit}"
        n /= 1024
    return f"{n:.2f} PB"


def format_time(seconds: float) -> str:
    """Human-readable duration."""
    if seconds < 60:
        return f"{seconds:.0f}s"
    elif seconds < 3600:
        m, s = divmod(seconds, 60)
        return f"{int(m)}m {int(s)}s"
    else:
        h, rem = divmod(seconds, 3600)
        m, s = divmod(rem, 60)
        return f"{int(h)}h {int(m)}m {int(s)}s"


def progress_bar(current: int, total: int, width: int = 40) -> str:
    """Render a text progress bar."""
    if total == 0:
        pct = 100.0
    else:
        pct = min(current / total * 100, 100.0)
    filled = int(width * pct / 100)
    bar = "█" * filled + "░" * (width - filled)
    return f"[{bar}] {pct:5.1f}%"


def make_fill_data(pass_number: int, size: int) -> bytes:
    """
    Generate fill data for a given pass.
      Pass 1: all zeros   (0x00)
      Pass 2: all ones    (0xFF)
      Pass 3+: random data
    """
    if pass_number == 1:
        return b"\x00" * size
    elif pass_number == 2:
        return b"\xFF" * size
    else:
        return secrets.token_bytes(size)


def random_name(length: int = 16) -> str:
    """Generate a random filename to destroy the original name from MFT."""
    chars = string.ascii_lowercase + string.digits
    return "".join(secrets.choice(chars) for _ in range(length))


# ---------------------------------------------------------------------------
# Shred: Securely delete specific files
# ---------------------------------------------------------------------------

def shred_file(file_path: str, passes: int = 3, verbose: bool = True) -> bool:
    """
    Securely shred a single file:
      1. Overwrite contents with multiple passes (zeros, ones, random)
      2. Rename file to random name (destroys original filename in MFT)
      3. Truncate to zero length
      4. Delete the file
    """
    file_path = os.path.abspath(file_path)

    if not os.path.isfile(file_path):
        if verbose:
            print(f"  [SKIP] Not a file: {file_path}")
        return False

    try:
        # Strip read-only / system attributes so the file can be opened for writing
        try:
            os.chmod(file_path, stat.S_IWRITE | stat.S_IREAD)
        except OSError:
            pass  # Best-effort; open() below will raise PermissionError if truly locked

        file_size = os.path.getsize(file_path)
        if verbose:
            print(f"  [SHRED] {file_path} ({format_bytes(file_size)})")

        # Step 1: Overwrite file contents with multiple passes
        for p in range(1, passes + 1):
            with open(file_path, "r+b") as f:
                written = 0
                while written < file_size:
                    chunk = min(CHUNK_SIZE, file_size - written)
                    data = make_fill_data(p, chunk)
                    f.write(data)
                    written += chunk
                f.flush()
                os.fsync(f.fileno())  # Force write to disk

        # Step 2: Rename file to random name (destroys filename in MFT)
        directory = os.path.dirname(file_path)
        # Rename multiple times to overwrite MFT entries
        current_path = file_path
        for _ in range(3):
            new_name = random_name() + ".del"
            new_path = os.path.join(directory, new_name)
            try:
                os.rename(current_path, new_path)
                current_path = new_path
            except OSError:
                break

        # Step 3: Truncate to zero length
        with open(current_path, "wb") as f:
            f.flush()
            os.fsync(f.fileno())

        # Step 4: Delete
        os.remove(current_path)

        if verbose:
            print(f"           ✓ Shredded ({passes} passes + rename + delete)")
        return True

    except PermissionError:
        if verbose:
            print(f"  [ERROR] Permission denied: {file_path}")
        return False
    except Exception as e:
        if verbose:
            print(f"  [ERROR] {file_path}: {e}")
        return False


def shred_directory(dir_path: str, passes: int = 3, verbose: bool = True) -> tuple:
    """
    Recursively shred all files in a directory, then remove the directory.
    Returns (success_count, fail_count).
    """
    dir_path = os.path.abspath(dir_path)
    success = 0
    failed = 0

    if not os.path.isdir(dir_path):
        print(f"  [ERROR] Not a directory: {dir_path}")
        return 0, 1

    # Walk bottom-up so we can remove dirs after emptying them
    for root, dirs, files in os.walk(dir_path, topdown=False):
        for fname in files:
            fpath = os.path.join(root, fname)
            if shred_file(fpath, passes=passes, verbose=verbose):
                success += 1
            else:
                failed += 1

        # Remove empty directories (rename first to destroy dir name)
        for dname in dirs:
            dpath = os.path.join(root, dname)
            try:
                # Rename directory to random name before removing
                new_name = random_name()
                new_path = os.path.join(root, new_name)
                os.rename(dpath, new_path)
                os.rmdir(new_path)
            except OSError:
                try:
                    os.rmdir(dpath)
                except OSError:
                    pass

    # Remove the top-level directory
    try:
        new_name = random_name()
        new_path = os.path.join(os.path.dirname(dir_path), new_name)
        os.rename(dir_path, new_path)
        os.rmdir(new_path)
    except OSError:
        try:
            os.rmdir(dir_path)
        except OSError:
            pass

    return success, failed


def cmd_shred(args):
    """Handle the 'shred' subcommand."""
    passes = args.passes
    recursive = args.recursive
    force = args.force

    # Expand glob patterns and collect all targets
    targets = []
    for pattern in args.targets:
        expanded = glob.glob(pattern)
        if expanded:
            targets.extend(expanded)
        else:
            targets.append(pattern)  # Keep as-is so we can show an error

    if not targets:
        print("[ERROR] No files specified.")
        sys.exit(1)

    # Show what will be shredded
    print(f"\n{'=' * 60}")
    print(f"  SecureDelete — File Shredder")
    print(f"{'=' * 60}")
    print(f"  Targets      : {len(targets)} item(s)")
    print(f"  Passes       : {passes}")
    print(f"  Recursive    : {'Yes' if recursive else 'No'}")
    print(f"{'=' * 60}\n")

    # List targets
    for t in targets:
        t = os.path.abspath(t)
        if os.path.isdir(t):
            if recursive:
                count = sum(len(files) for _, _, files in os.walk(t))
                print(f"  📁 {t} ({count} files)")
            else:
                print(f"  📁 {t} (use -r to shred directories)")
        elif os.path.isfile(t):
            print(f"  📄 {t} ({format_bytes(os.path.getsize(t))})")
        else:
            print(f"  ⚠️  {t} (not found)")

    # Confirm
    if not force:
        print()
        confirm = input("  These files will be PERMANENTLY destroyed. Continue? [y/N]: ").strip().lower()
        if confirm not in ("y", "yes"):
            print("\n  Aborted.")
            return

    print()
    start = time.time()
    total_success = 0
    total_failed = 0

    for t in targets:
        t = os.path.abspath(t)
        if os.path.isdir(t):
            if recursive:
                s, f = shred_directory(t, passes=passes)
                total_success += s
                total_failed += f
            else:
                print(f"  [SKIP] Directory (use -r): {t}")
                total_failed += 1
        elif os.path.isfile(t):
            if shred_file(t, passes=passes):
                total_success += 1
            else:
                total_failed += 1
        else:
            print(f"  [SKIP] Not found: {t}")
            total_failed += 1

    elapsed = time.time() - start

    print(f"\n{'=' * 60}")
    print(f"  DONE in {format_time(elapsed)}")
    print(f"  Shredded : {total_success} file(s)")
    if total_failed:
        print(f"  Failed   : {total_failed} file(s)")
    print(f"  Files are PERMANENTLY destroyed and UNRECOVERABLE.")
    print(f"{'=' * 60}\n")


# ---------------------------------------------------------------------------
# Recover: Recover from Recycle Bin
# ---------------------------------------------------------------------------

def get_recycle_bin_items():
    import base64
    import json
    import subprocess
    ps_cmd = """
    $ErrorActionPreference = "Stop"
    $Shell = New-Object -ComObject Shell.Application
    $RecycleBin = $Shell.NameSpace(10)
    $items = @()
    foreach ($item in $RecycleBin.Items()) {
        try {
            $items += @{
                Name = $RecycleBin.GetDetailsOf($item, 0)
                OriginalLocation = $RecycleBin.GetDetailsOf($item, 1)
                DateDeleted = $RecycleBin.GetDetailsOf($item, 2)
                Size = $RecycleBin.GetDetailsOf($item, 3)
                Path = $item.Path
            }
        } catch { }
    }
    if ($items.Count -gt 0) {
        $items | ConvertTo-Json -Compress
    } else {
        "[]"
    }
    """
    try:
        encoded = base64.b64encode(ps_cmd.encode('utf-16le')).decode('utf-8')
        result = subprocess.run(["powershell", "-NoProfile", "-EncodedCommand", encoded], capture_output=True, text=True, check=True)
        out = result.stdout.strip()
        if not out or out == '[]':
            return []
        parsed = json.loads(out)
        if isinstance(parsed, dict):
            return [parsed]
        return parsed
    except Exception as e:
        print(f"Error reading Recycle Bin: {e}")
        return []

def recover_recycle_bin_item(item_path):
    """Restore item_path from the Recycle Bin via PowerShell Shell.Application.

    The item path is passed through an environment variable (SD_ITEM_PATH) rather
    than interpolated into the script string, which eliminates the PowerShell
    injection risk that existed with the previous f-string approach.
    """
    import base64
    # No f-string — path is injected via the process environment, not the script.
    ps_cmd = """
    $targetPath = $env:SD_ITEM_PATH
    $Shell = New-Object -ComObject Shell.Application
    $RecycleBin = $Shell.NameSpace(10)
    foreach ($item in $RecycleBin.Items()) {
        if ($item.Path -eq $targetPath) {
            foreach ($verb in $item.Verbs()) {
                if ($verb.Name -match "estore|Undelete") {
                    $verb.DoIt()
                    Start-Sleep -Milliseconds 500
                    exit 0
                }
            }
        }
    }
    exit 1
    """
    try:
        encoded = base64.b64encode(ps_cmd.encode('utf-16le')).decode('utf-8')
        env = os.environ.copy()
        env["SD_ITEM_PATH"] = item_path
        result = subprocess.run(
            ["powershell", "-NoProfile", "-EncodedCommand", encoded],
            capture_output=True, env=env
        )
        return result.returncode == 0
    except Exception:
        return False

def carve_drive(drive: str, out_dir: str, max_scan_bytes: int = 100 * 1024 * 1024, types: list = None, update_callback=None, stop_event=None):
    """
    Raw disk signature-based carver for permanently deleted files.
    """
    import time
    
    if not types:
        types = ['jpg', 'png', 'pdf', 'zip']
        
    os.makedirs(out_dir, exist_ok=True)
    
    if len(drive) <= 2 and drive[0].isalpha():
        raw_drive = f"\\\\.\\{drive[0].upper()}:"
    else:
        raw_drive = drive
        
    sigs = {
        'jpg': (b"\xFF\xD8\xFF", b"\xFF\xD9", 20 * 1024 * 1024),
        'png': (b"\x89PNG\r\n\x1A\n", b"IEND\xAE\x42\x60\x82", 20 * 1024 * 1024),
        'pdf': (b"%PDF-", b"%%EOF", 50 * 1024 * 1024),
        'zip': (b"PK\x03\x04", b"PK\x05\x06", 50 * 1024 * 1024)
    }
    
    active_sigs = {k: v for k, v in sigs.items() if k in types}
    if not active_sigs:
        return 0
        
    chunk_size = 4 * 1024 * 1024 # 4MB
    overlap = 2 * 1024 * 1024    # 2MB overlap
    
    scanned = 0
    found = 0
    buffer = bytearray()  # bytearray avoids O(n²) copies from repeated b"" + chunk

    try:
        with open(raw_drive, "rb") as f:
            while max_scan_bytes == 0 or scanned < max_scan_bytes:
                if stop_event and stop_event.is_set():
                    break
                    
                time.sleep(0.005) # Prevent high CPU/IOLoad from freezing system
                
                to_read = chunk_size if max_scan_bytes == 0 else min(chunk_size, max_scan_bytes - scanned)
                try:
                    chunk = f.read(to_read)
                except OSError as e:
                    print(f"  [WARNING] Read error at offset {scanned}: {e}")
                    break
                    
                if not chunk:
                    break
                    
                buffer += chunk
                i = 0
                
                while True:
                    if stop_event and stop_event.is_set():
                        break

                    if max_scan_bytes == 0:
                        search_limit = len(buffer) if len(chunk) < to_read else len(buffer) - overlap
                    else:
                        search_limit = len(buffer) if (scanned + to_read >= max_scan_bytes or len(chunk) < to_read) else len(buffer) - overlap
                        
                    if i >= search_limit or search_limit <= 0:
                        break
                        
                    best_match = None
                    best_idx = search_limit
                    
                    for ext, (start_sig, end_sig, max_file_size) in active_sigs.items():
                        idx = buffer.find(start_sig, i, search_limit + len(start_sig))
                        if idx != -1 and idx < best_idx:
                            best_idx = idx
                            best_match = ext
                            
                    if best_match:
                        i = best_idx
                        start_sig, end_sig, max_file_size = active_sigs[best_match]
                        end_idx = buffer.find(end_sig, i + len(start_sig))
                        
                        if end_idx != -1:
                            end_idx += len(end_sig)
                            if best_match == 'zip':
                                end_idx += 18
                            
                            if end_idx - i <= max_file_size:
                                fname = f"recovered_{found + 1:04d}.{best_match}"
                                with open(os.path.join(out_dir, fname), "wb") as out_f:
                                    out_f.write(buffer[i:end_idx])
                                found += 1
                                i = end_idx
                            else:
                                i += 1
                        else:
                            if len(buffer) - i > max_file_size:
                                i += 1
                            else:
                                break
                    else:
                        i = search_limit
                        
                buffer = buffer[i:]
                scanned += len(chunk)
                
                if update_callback:
                    update_callback(scanned, max_scan_bytes, found)
                    
    except KeyboardInterrupt:
        pass
    except PermissionError:
        print(f"  [ERROR] Administrator privileges needed to read {raw_drive}")
        if update_callback:
            update_callback(max_scan_bytes, max_scan_bytes, found) # Force finish
    except Exception as e:
        print(f"  [ERROR] {e}")
        
    return found

def cmd_recover(args):
    print(f"\\n{'=' * 60}")
    print(f"  SecureDelete — File Recovery")
    print(f"{'=' * 60}\\n")
    
    if args.deep:
        # DEEP CARVE MODE
        import time
        import shutil
        drive = args.deep
        limit_mb = args.limit
        if limit_mb > 0:
            print(f"  [INFO] Starting DEEP CARVE on generic drive space on '{drive}'.")
            print(f"         Scanning up to {limit_mb} MB.")
            limit_bytes = limit_mb * 1024 * 1024
            total_size_estimate = limit_bytes
        else:
            print(f"  [INFO] Starting DEEP CARVE on '{drive}'.")
            print(f"         Scanning FULL DRIVE.")
            limit_bytes = 0
            try:
                total_size_estimate = shutil.disk_usage(drive).total
            except Exception:
                total_size_estimate = 0
        
        out_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "Recovered_Files")
        
        def cli_update(current, total, found):
            import sys
            actual_total = total if total > 0 else total_size_estimate
            if actual_total > 0:
                pct = (current / actual_total) * 100
                sys.stdout.write(f"\\r  [SCANNING] {format_bytes(current)} / {format_bytes(actual_total)} ({pct:.1f}%) -- Found: {found} files")
            else:
                sys.stdout.write(f"\\r  [SCANNING] {format_bytes(current)} -- Found: {found} files")
            sys.stdout.flush()
            
        start_time = time.time()
        found = carve_drive(drive, out_dir, max_scan_bytes=limit_bytes, update_callback=cli_update)
        elapsed = time.time() - start_time
        
        print(f"\\n\\n  Done in {format_time(elapsed)}")
        print(f"  {found} files successfully recovered to -> {os.path.abspath(out_dir)}")
        return

    # RECYCLE BIN MODE
    print("  [INFO] Scanning Recycle Bin...")
    items = get_recycle_bin_items()
    if not items:
        print("  Recycle Bin is empty or unable to read.")
        return
        
    if args.list:
        print(f"  Found {len(items)} item(s) in Recycle Bin:\\n")
        for idx, item in enumerate(items, 1):
            print(f"  {idx}. {item.get('Name', 'Unknown')}")
            print(f"     Original Location: {item.get('OriginalLocation', 'Unknown')}")
            print(f"     Date Deleted: {item.get('DateDeleted', 'Unknown')}")
            print(f"     Size: {item.get('Size', 'Unknown')}\\n")
        return

    # If targets specified
    targets = items
    if args.targets:
        targets = [it for it in items if it.get("Name") in args.targets]
        if not targets:
            print("  [ERROR] None of the specified targets were found in the Recycle Bin.")
            return
            
    print(f"  Found {len(targets)} item(s) to recover.\\n")
    
    if not args.force:
        confirm = input("  Recover these items to their original locations? [y/N]: ").strip().lower()
        if confirm not in ("y", "yes"):
            print("\\n  Aborted.")
            return
            
    success = 0
    failed = 0
    for it in targets:
        print(f"  Recovering: {it.get('Name')}...")
        if recover_recycle_bin_item(it.get("Path")):
            success += 1
        else:
            failed += 1
            
    print(f"\\n{'=' * 60}")
    print(f"  Recovery Complete.")
    print(f"  Recovered: {success} item(s)")
    if failed:
        print(f"  Failed   : {failed} item(s)")
    print(f"{'=' * 60}\\n")


# ---------------------------------------------------------------------------
# System & Browser Cleaner  (feature/privacy-deep-clean)
# ---------------------------------------------------------------------------

# Browsers whose process names must be killed before cleaning.
_BROWSER_PROCS = [
    "chrome.exe", "msedge.exe", "brave.exe", "firefox.exe",
    "opera.exe", "browser.exe", "vivaldi.exe", "waterfox.exe",
    "librewolf.exe", "chromium.exe", "iexplore.exe",
]

def close_browsers():
    """Kill running instances of all supported browsers to release file locks."""
    for b in _BROWSER_PROCS:
        subprocess.run(
            ["taskkill", "/F", "/IM", b],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL
        )


def get_browser_paths() -> dict:
    """
    Return a mapping of browser display-name → profile root directory.
    Every path is resolved from environment variables so it works for any
    Windows user account without hardcoded usernames.
    """
    L = os.environ.get("LOCALAPPDATA", "")
    A = os.environ.get("APPDATA", "")
    return {
        # --- Chromium family ---
        "Chrome":       os.path.join(L, r"Google\Chrome\User Data"),
        "Edge":         os.path.join(L, r"Microsoft\Edge\User Data"),
        "Brave":        os.path.join(L, r"BraveSoftware\Brave-Browser\User Data"),
        "Opera":        os.path.join(A, r"Opera Software\Opera Stable"),
        "Opera GX":     os.path.join(A, r"Opera Software\Opera GX Stable"),
        "Vivaldi":      os.path.join(L, r"Vivaldi\User Data"),
        "Chromium":     os.path.join(L, r"Chromium\User Data"),
        # --- Firefox family ---
        "Firefox":      os.path.join(A, r"Mozilla\Firefox\Profiles"),
        "Waterfox":     os.path.join(A, r"Waterfox\Profiles"),
        "LibreWolf":    os.path.join(A, r"LibreWolf\Profiles"),
        # --- Internet Explorer / Edge Legacy ---
        "IE Legacy":    os.path.join(L, r"Microsoft\Windows\INetCache"),
    }


# ---------------------------------------------------------------------------
# Chromium artifact helpers
# ---------------------------------------------------------------------------

# Directories inside a Chromium profile that are safe to wipe entirely
# (cache, compiled code, GPU cache, network state, sessions, storage…)
_CHROMIUM_WIPE_DIRS = [
    "Cache",
    "Code Cache",
    "DawnCache",
    "GPUCache",
    "ShaderCache",
    "PnaclTranslationCache",
    "Media Cache",
    "Application Cache",
    "Service Worker",        # sub-dirs: CacheStorage, ScriptCache
    "CacheStorage",
    "Sessions",
    "Session Storage",
    "Local Storage",
    "IndexedDB",
    "databases",
    "FileSystem",
    "blob_storage",
    "Download Service",
    "GCM Store",
    "AutofillStrikeDatabase",
    "BudgetDatabase",
    "data_reduction_proxy_leveldb",
    "Feature Engagement Tracker",
    "Media Engagement",
    "Site Characteristics Database",
    "Network Action Predictor",
    "previews_opt_out.db",
    "safe_browsing",
]

# Individual files inside a Chromium profile to shred (preserving
# Login Data, Bookmarks, Preferences, Extensions, Secure Preferences).
_CHROMIUM_WIPE_FILES = [
    # History
    "History",
    "History-journal",
    "Visited Links",
    "Top Sites",
    "Shortcuts",
    "Shortcuts-journal",
    # Cookies
    "Cookies",
    "Cookies-journal",
    "Extension Cookies",
    "Extension Cookies-journal",
    # Network/Cookies (Edge-style path)
    "Network/Cookies",
    # Autofill (Web Data — NOT Login Data)
    "Web Data",
    "Web Data-journal",
    # Sessions / tabs
    "Current Session",
    "Current Tabs",
    "Last Session",
    "Last Tabs",
    # Downloads
    "DownloadMetadata",
    # Thumbnails / favicons
    "Thumbnails",
    "Favicons",
    "Favicons-journal",
    # Misc
    "heavy_ad_intervention_opt_out.db",
    "shared_proto_db",
    "TransportSecurity",
    "QuotaManager",
    "QuotaManager-journal",
]


def _collect_chromium_targets(base_path: str) -> list:
    """
    Walk every profile directory under *base_path* and return a list of
    file paths that should be shredded, honouring the preserve-list.
    """
    profiles = (
        [os.path.join(base_path, "Default")]
        + glob.glob(os.path.join(base_path, "Profile *"))
        + [base_path]          # root-level caches (e.g. Opera Stable lives here)
    )

    targets = []
    for profile in profiles:
        if not os.path.isdir(profile):
            continue

        # --- Wipe entire sub-directories (all files recursively) ---
        for dirname in _CHROMIUM_WIPE_DIRS:
            d = os.path.join(profile, dirname)
            if os.path.isdir(d):
                targets.extend(
                    glob.glob(os.path.join(d, "**", "*"), recursive=True)
                )

        # --- Wipe specific files (path separator handled for Network/ sub-path) ---
        for fname in _CHROMIUM_WIPE_FILES:
            fpath = os.path.join(profile, *fname.split("/"))
            targets.append(fpath)

    return targets


# ---------------------------------------------------------------------------
# Firefox artifact helpers
# ---------------------------------------------------------------------------

# Sub-directories inside each Firefox profile to wipe entirely.
_FIREFOX_WIPE_DIRS = [
    "cache2",
    "startupCache",
    "thumbnails",
    "sessionstore-backups",
    "storage",              # local/default/…  (IndexedDB, localStorage)
    "storage.sqlite",       # older Firefox
    "datareporting",
    "crashes",
    "minidumps",
    "saved-telemetry-pings",
]

# Individual SQLite databases to shred (places.sqlite is intentionally
# excluded to preserve bookmarks — see WAL files below for journal cleanup).
_FIREFOX_WIPE_FILES = [
    "cookies.sqlite",
    "cookies.sqlite-shm",
    "cookies.sqlite-wal",
    "formhistory.sqlite",
    "formhistory.sqlite-shm",
    "formhistory.sqlite-wal",
    "downloads.sqlite",
    "downloads.sqlite-shm",
    "downloads.sqlite-wal",
    "content-prefs.sqlite",
    "content-prefs.sqlite-shm",
    "content-prefs.sqlite-wal",
    "permissions.sqlite",
    "permissions.sqlite-shm",
    "permissions.sqlite-wal",
    # places WAL only (full DB preserved for bookmarks)
    "places.sqlite-shm",
    "places.sqlite-wal",
    # Session restore
    "sessionstore.jsonlz4",
    "sessionstore.js",
    # Misc
    "signedInUser.json",
    "healthreport.sqlite",
    "healthreport.sqlite-shm",
    "healthreport.sqlite-wal",
    "webappsstore.sqlite",
    "webappsstore.sqlite-shm",
    "webappsstore.sqlite-wal",
    "chromeappsstore.sqlite",
    "addons.json",        # add-on cache only, not extension data itself
    "addonStartup.json.lz4",
    "SiteSecurityServiceState.bin",
    "AlternateServices.txt",
]


def _collect_firefox_targets(base_path: str) -> list:
    """Walk all Firefox profile directories and collect files to shred."""
    targets = []
    for profile in glob.glob(os.path.join(base_path, "*")):
        if not os.path.isdir(profile):
            continue

        for dirname in _FIREFOX_WIPE_DIRS:
            d = os.path.join(profile, dirname)
            if os.path.isdir(d):
                targets.extend(
                    glob.glob(os.path.join(d, "**", "*"), recursive=True)
                )
            elif os.path.isfile(d):   # some entries are files (e.g. storage.sqlite)
                targets.append(d)

        for fname in _FIREFOX_WIPE_FILES:
            targets.append(os.path.join(profile, fname))

    return targets


# ---------------------------------------------------------------------------
# Public browser shred API
# ---------------------------------------------------------------------------

def get_browser_data_summary(browser_name: str) -> tuple:
    """
    Return (file_count, total_bytes) for the privacy data the named browser
    currently has on disk.  Used by the GUI to show live size estimates.
    Returns (0, 0) if the browser is not installed.
    """
    paths = get_browser_paths()
    base_path = paths.get(browser_name)
    if not base_path or not os.path.exists(base_path):
        return 0, 0

    is_firefox_family = browser_name in ("Firefox", "Waterfox", "LibreWolf")
    targets = (
        _collect_firefox_targets(base_path)
        if is_firefox_family
        else _collect_chromium_targets(base_path)
    )

    count = 0
    total = 0
    for t in targets:
        if os.path.isfile(t):
            try:
                total += os.path.getsize(t)
                count += 1
            except OSError:
                pass
    return count, total


def shred_browser_data(browser_name: str, passes: int = 3, verbose: bool = True) -> tuple:
    """
    Securely shred all privacy-sensitive data for *browser_name*.

    Preserved (never touched):
      - Login Data / key4.db / logins.json  (saved passwords)
      - Bookmarks / places.sqlite            (browsing bookmarks)
      - Extensions / extension_rules/        (installed add-ons)
      - Preferences / Secure Preferences     (browser settings)

    Shredded:
      - All cache layers (HTTP cache, GPU, shader, code, media, SW)
      - Cookies and cookie journals
      - Browsing history, visited links, top sites
      - Session / tab restore files
      - Local Storage, IndexedDB, databases
      - Form autofill (Web Data) — NOT passwords
      - Download metadata
      - Thumbnails, favicons
      - Crash dumps, telemetry, health reports
    """
    paths = get_browser_paths()
    base_path = paths.get(browser_name)
    if not base_path or not os.path.exists(base_path):
        if verbose:
            print(f"  [SKIP] {browser_name} not installed or data not found.")
        return 0, 0

    is_firefox_family = browser_name in ("Firefox", "Waterfox", "LibreWolf")
    is_ie_legacy      = browser_name == "IE Legacy"

    if is_ie_legacy:
        # INetCache root — wipe everything
        targets = glob.glob(os.path.join(base_path, "**", "*"), recursive=True)
    elif is_firefox_family:
        targets = _collect_firefox_targets(base_path)
    else:
        targets = _collect_chromium_targets(base_path)

    success = 0
    failed  = 0
    for t in targets:
        if os.path.isfile(t):
            if shred_file(t, passes=passes, verbose=False):
                success += 1
            else:
                failed += 1

    if verbose:
        print(f"  [BROWSER] {browser_name}: Shredded {success} | Failed {failed}")

    return success, failed


# ---------------------------------------------------------------------------
# System / OS privacy helpers
# ---------------------------------------------------------------------------

def shred_thumbnail_cache(passes: int = 3, verbose: bool = True) -> tuple:
    """
    Shred Windows Explorer thumbnail cache databases (thumbcache_*.db)
    and taskbar jump-list thumbnail files.
    """
    L = os.environ.get("LOCALAPPDATA", "")
    A = os.environ.get("APPDATA", "")

    paths_to_clean = [
        os.path.join(L, r"Microsoft\Windows\Explorer"),  # thumbcache DBs
        os.path.join(A, r"Microsoft\Windows\Themes\CachedFiles"),
    ]

    success, failed = 0, 0
    for path in paths_to_clean:
        if not os.path.isdir(path):
            continue
        # Only target known thumbnail cache file patterns
        patterns = ["thumbcache_*.db", "*.customDestinations-ms",
                    "*.automaticDestinations-ms", "iconcache_*.db"]
        for pat in patterns:
            for fpath in glob.glob(os.path.join(path, pat)):
                if os.path.isfile(fpath):
                    if shred_file(fpath, passes=passes, verbose=False):
                        success += 1
                    else:
                        failed += 1
    if verbose:
        print(f"  [THUMBS] Thumbnail cache: Shredded {success} | Failed {failed}")
    return success, failed


def shred_inet_cache(passes: int = 3, verbose: bool = True) -> tuple:
    """
    Shred Internet Explorer / Edge-Legacy cache stored in INetCache,
    INetCookies and the unified WebCache database.
    """
    L = os.environ.get("LOCALAPPDATA", "")
    paths = [
        os.path.join(L, r"Microsoft\Windows\INetCache"),
        os.path.join(L, r"Microsoft\Windows\INetCookies"),
        os.path.join(L, r"Microsoft\Windows\Temporary Internet Files"),
        os.path.join(L, r"Microsoft\Windows\WebCache"),
    ]
    success, failed = 0, 0
    for path in paths:
        if not os.path.isdir(path):
            continue
        file_count = sum(len(f) for _, _, f in os.walk(path))
        if verbose:
            print(f"  [INET] Cleaning {path} ({file_count} files)")
        s, f = shred_directory(path, passes=passes, verbose=False)
        os.makedirs(path, exist_ok=True)
        success += s
        failed  += f
    if verbose:
        print(f"  [INET] Total Shredded {success} | Failed {failed}")
    return success, failed


def shred_crash_dumps(passes: int = 3, verbose: bool = True) -> tuple:
    """Shred Windows and application crash-dump files."""
    L = os.environ.get("LOCALAPPDATA", "")
    A = os.environ.get("APPDATA", "")
    windir = os.environ.get("WINDIR", r"C:\Windows")

    paths = [
        os.path.join(L, "CrashDumps"),
        os.path.join(L, r"Microsoft\Windows\WER\ReportArchive"),
        os.path.join(L, r"Microsoft\Windows\WER\ReportQueue"),
        os.path.join(A, r"Microsoft\Windows\WER"),
        os.path.join(windir, "Minidump"),
    ]
    success, failed = 0, 0
    for path in paths:
        if not os.path.isdir(path):
            continue
        s, f = shred_directory(path, passes=passes, verbose=False)
        os.makedirs(path, exist_ok=True)
        success += s
        failed  += f
    if verbose:
        print(f"  [CRASH] Crash dumps: Shredded {success} | Failed {failed}")
    return success, failed


def flush_dns_cache(verbose: bool = True):
    """Flush the Windows DNS resolver cache via ipconfig /flushdns."""
    if verbose:
        print("  [DNS] Flushing DNS resolver cache...")
    try:
        subprocess.run(
            ["ipconfig", "/flushdns"],
            capture_output=True, check=True
        )
        if verbose:
            print("  [DNS] DNS cache flushed successfully.")
    except Exception as e:
        if verbose:
            print(f"  [DNS] Warning: DNS flush failed: {e}")


def shred_system_activities(
    passes: int = 3,
    include_inet: bool = False,
    include_crash_dumps: bool = False,
    verbose: bool = True,
) -> tuple:
    """
    Shred Windows temp, prefetch, recent files, and optionally
    IE/Edge legacy caches and crash dumps.
    """
    success = 0
    failed  = 0

    L      = os.environ.get("LOCALAPPDATA", "")
    A      = os.environ.get("APPDATA", "")
    windir = os.environ.get("WINDIR", r"C:\Windows")
    temp   = os.environ.get("TEMP", "")
    ltemp  = os.path.join(L, "Temp")   # per-user temp, separate from %WINDIR%\Temp

    paths_to_shred = [
        os.path.join(windir, "Temp"),
        temp,
        ltemp,
        os.path.join(windir, "Prefetch"),
        os.path.join(A, r"Microsoft\Windows\Recent"),
        os.path.join(A, r"Microsoft\Windows\Recent\AutomaticDestinations"),
        os.path.join(A, r"Microsoft\Windows\Recent\CustomDestinations"),
        os.path.join(L, r"Microsoft\Windows\Explorer"),  # thumbnail caches
    ]

    for path in paths_to_shred:
        if path and os.path.isdir(path):
            file_count = sum(len(files) for _, _, files in os.walk(path))
            if verbose:
                print(f"  [SYSTEM] Cleaning: {path} ({file_count} files)")
            s, f = shred_directory(path, passes=passes, verbose=False)
            os.makedirs(path, exist_ok=True)
            success += s
            failed  += f
            if verbose:
                print(f"           ✓ Done: {s} shredded, {f} failed")

    if include_inet:
        s, f = shred_inet_cache(passes=passes, verbose=verbose)
        success += s; failed += f

    if include_crash_dumps:
        s, f = shred_crash_dumps(passes=passes, verbose=verbose)
        success += s; failed += f

    if verbose:
        print(f"  [SYSTEM] Total Shredded {success} | Failed {failed}\n")
    return success, failed


def clear_event_logs(verbose: bool = True):
    """Clear Windows Event Logs using wevtutil (admin required for most)."""
    if verbose:
        print("  [LOGS] Clearing Windows Event Logs...")
    try:
        result = subprocess.run(
            ["wevtutil", "el"], capture_output=True, text=True, check=True
        )
        logs = result.stdout.strip().split("\n")
        success = 0
        failed  = 0
        for log in logs:
            log = log.strip()
            if not log:
                continue
            try:
                subprocess.run(
                    ["wevtutil", "cl", log], capture_output=True, check=True
                )
                success += 1
            except subprocess.CalledProcessError:
                failed += 1
        if verbose:
            print(f"  [LOGS] Cleared {success} event logs. Failed {failed}.\n")
    except Exception as e:
        if verbose:
            print(f"  [ERROR] Failed to clear event logs: {e}\n")


def cmd_clean(args):
    """Handle the 'clean' subcommand."""
    print(f"\n{'=' * 60}")
    print(f"  SecureDelete — Privacy Cleanup")
    print(f"{'=' * 60}\n")

    browsers = [
        "Chrome", "Edge", "Brave", "Firefox", "Opera",
        "Opera GX", "Vivaldi", "Chromium",
        "Waterfox", "LibreWolf", "IE Legacy",
    ]

    if args.browsers:
        print("  [INFO] Closing browsers...")
        close_browsers()
        time.sleep(1)
        for browser in browsers:
            shred_browser_data(browser, passes=args.passes, verbose=True)

    if args.system:
        shred_system_activities(
            passes=args.passes,
            include_inet=getattr(args, "inet", False),
            include_crash_dumps=getattr(args, "crash_dumps", False),
            verbose=True,
        )

    if getattr(args, "dns", False):
        flush_dns_cache(verbose=True)

    if getattr(args, "thumbnails", False):
        shred_thumbnail_cache(passes=args.passes, verbose=True)

    if args.logs:
        clear_event_logs(verbose=True)

    print(f"{'=' * 60}")
    print(f"  Cleanup Complete.")
    print(f"{'=' * 60}\n")
    

# ---------------------------------------------------------------------------
# Wipe: Free space wiper
# ---------------------------------------------------------------------------

def get_adb_path():
    """Find adb via ADB_PATH env var, system PATH, or common install locations.

    To use a non-standard ADB binary, set the ADB_PATH environment variable
    to the full path of adb.exe before launching SecureDelete.
    """
    # 1. Explicit override (no hardcoded user-specific paths)
    env_adb = os.environ.get("ADB_PATH")
    if env_adb and os.path.exists(env_adb):
        return env_adb

    # 2. System PATH (covers most developer setups)
    adb = shutil.which("adb")
    if adb:
        return adb

    # 3. Common Windows install locations
    localappdata = os.environ.get('LOCALAPPDATA', '')
    common_paths = [
        os.path.join(localappdata, r"Android\Sdk\platform-tools\adb.exe"),
        r"C:\adb\adb.exe",
        r"C:\platform-tools\adb.exe",
    ]
    for p in common_paths:
        if os.path.exists(p):
            return p
    return None

def get_android_devices():
    """Return a list of connected Android devices via ADB."""
    adb = get_adb_path()
    if not adb:
        return []
    try:
        flags = subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0
        res = subprocess.run([adb, "devices"], capture_output=True, text=True, check=True, creationflags=flags)
        lines = res.stdout.strip().split("\n")[1:] # Skip 'List of devices attached'
        devices = []
        for line in lines:
            if "\tdevice" in line:
                dev_id = line.split("\t")[0]
                model = "Android Device"
                try:
                    m_res = subprocess.run([adb, "-s", dev_id, "shell", "getprop", "ro.product.model"], capture_output=True, text=True, creationflags=flags)
                    if m_res.stdout.strip():
                        model = m_res.stdout.strip()
                except: pass
                devices.append({"id": dev_id, "name": model})
        return devices
    except Exception:
        return []

def wipe_android_free_space(device_id: str, passes: int = 3, update_callback=None):
    """
    Wipe free space on an Android device using ADB.
    """
    adb = get_adb_path()
    if not adb:
        print("[ERROR] ADB not found.")
        return

    print(f"\n{'=' * 60}")
    print(f"  SecureDelete — Android ADB Wiper")
    print(f"{'=' * 60}")
    print(f"  Target device: {device_id}")
    print(f"  Passes       : {passes}")
    print(f"{'=' * 60}\n")

    flags = subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0
    for p in range(1, passes + 1):
        pass_label = {1: "ZEROS (0x00)", 2: "RANDOM", 3: "ZEROS (0x00)"}.get(p, f"RANDOM #{p}")
        print(f"\n  ── Pass {p}/{passes}: {pass_label} ──")
        
        total_free = 0
        try:
            df_res = subprocess.run([adb, "-s", device_id, "shell", "df", "/sdcard"], capture_output=True, text=True, creationflags=flags)
            lines = df_res.stdout.strip().split("\n")
            if len(lines) > 1:
                parts = lines[1].split()
                if len(parts) >= 4:
                    total_free = int(parts[3]) * 1024
        except Exception:
            pass
            
        print(f"  Estimated free space: {format_bytes(total_free) if total_free else 'Unknown'}")
        
        wipe_file = f"/sdcard/.secure_wipe_p{p}.bin"
        if "RANDOM" in pass_label:
            cmd = f"dd if=/dev/urandom of={wipe_file} bs=1048576"
        else:
            cmd = f"dd if=/dev/zero of={wipe_file} bs=1048576"
            
        start_time = time.time()
        print(f"  [WIPING] Filling storage via ADB (this will take a while and fail with 'No space' when done)...")
        
        proc = subprocess.Popen([adb, "-s", device_id, "shell", cmd], stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, creationflags=flags)
        
        last_size = 0
        while proc.poll() is None:
            time.sleep(2)
            if update_callback and total_free > 0:
                try:
                    sz_res = subprocess.run([adb, "-s", device_id, "shell", "stat", "-c", "%s", wipe_file], capture_output=True, text=True, creationflags=flags)
                    cur_size = int(sz_res.stdout.strip())
                    if cur_size > last_size:
                        elapsed = time.time() - start_time
                        speed = cur_size / elapsed if elapsed > 0 else 0
                        update_callback(p, passes, cur_size, total_free, speed)
                        last_size = cur_size
                except Exception:
                    pass
                    
        print(f"  Cleaning up pass {p} temp file from Android...")
        subprocess.run([adb, "-s", device_id, "shell", "rm", "-f", wipe_file], capture_output=True, creationflags=flags)
        
        elapsed = time.time() - start_time
        print(f"  Pass {p} complete in {format_time(elapsed)}.")

    print(f"\n{'=' * 60}")
    print(f"  DONE — {passes} pass(es) completed.")
    print(f"{'=' * 60}\n")

def wipe_free_space(drive: str, passes: int = 3, dry_run: bool = False,
                    update_callback=None, stop_event=None):
    """
    Wipe all free space on `drive` by writing temporary files until the disk
    is full, then deleting them.  Repeats for the requested number of passes.

    Optional parameters (used by the GUI):
        update_callback(pass, total_passes, written, free, speed)
            Called after every chunk written so the GUI can update its progress bar.
        stop_event : threading.Event
            When set, aborts the wipe cleanly after the current chunk completes.
    """
    # Normalise drive path
    if not drive.endswith("\\"):
        drive += "\\"

    # Verify drive exists
    if not os.path.isdir(drive):
        print(f"[ERROR] Drive '{drive}' not found.")
        sys.exit(1)

    free = get_free_space(drive)
    print(f"\n{'=' * 60}")
    print(f"  SecureDelete — Free Space Wiper")
    print(f"{'=' * 60}")
    print(f"  Target drive : {drive}")
    print(f"  Free space   : {format_bytes(free)}")
    print(f"  Passes       : {passes}")
    print(f"  Chunk size   : {format_bytes(CHUNK_SIZE)}")
    if dry_run:
        print(f"  Mode         : DRY RUN (no data written)")
    print(f"{'=' * 60}\n")

    # Only prompt interactively when running from the CLI (GUI confirms beforehand)
    if not dry_run and update_callback is None:
        confirm = input("  This will fill ALL free space with junk data to destroy\n"
                        "  any recoverable files.  Continue? [y/N]: ").strip().lower()
        if confirm not in ("y", "yes"):
            print("\n  Aborted.")
            return

    wipe_dir = os.path.join(drive, TEMP_DIR_NAME)
    os.makedirs(wipe_dir, exist_ok=True)

    total_start = time.time()
    stopped = False

    try:
        for p in range(1, passes + 1):
            if stop_event and stop_event.is_set():
                stopped = True
                break

            pass_label = {1: "ZEROS (0x00)", 2: "ONES (0xFF)"}.get(p, f"RANDOM #{p}")
            print(f"\n  ── Pass {p}/{passes}: {pass_label} ──")

            free = get_free_space(drive)
            written = 0
            file_index = 0
            start = time.time()

            while True:
                if stop_event and stop_event.is_set():
                    stopped = True
                    break

                remaining = get_free_space(drive)
                # Stop when less than 1 MB free (leave a tiny buffer for OS)
                if remaining < 1 * 1024 * 1024:
                    break

                file_path = os.path.join(wipe_dir, f"wipe_p{p}_{file_index:06d}.bin")
                file_index += 1

                try:
                    if dry_run:
                        # Simulate writing
                        written += min(CHUNK_SIZE * 256, remaining)
                        elapsed = time.time() - start
                        speed = written / elapsed if elapsed > 0 else 0
                        eta = (free - written) / speed if speed > 0 else 0
                        sys.stdout.write(
                            f"\r  {progress_bar(written, free)} "
                            f"{format_bytes(written)}/{format_bytes(free)} "
                            f"@ {format_bytes(speed)}/s  ETA {format_time(eta)}  "
                        )
                        sys.stdout.flush()
                        break  # In dry run, one iteration is enough
                    else:
                        with open(file_path, "wb") as f:
                            while True:
                                if stop_event and stop_event.is_set():
                                    stopped = True
                                    break

                                current_free = get_free_space(drive)
                                if current_free < 1 * 1024 * 1024:
                                    break

                                to_write = min(CHUNK_SIZE, current_free - 512 * 1024)
                                if to_write <= 0:
                                    break

                                data = make_fill_data(p, to_write)
                                f.write(data)
                                f.flush()
                                written += to_write

                                elapsed = time.time() - start
                                speed = written / elapsed if elapsed > 0 else 0
                                if update_callback:
                                    update_callback(p, passes, written, free, speed)
                                else:
                                    eta = (free - written) / speed if speed > 0 else 0
                                    sys.stdout.write(
                                        f"\r  {progress_bar(written, free)} "
                                        f"{format_bytes(written)}/{format_bytes(free)} "
                                        f"@ {format_bytes(speed)}/s  ETA {format_time(eta)}  "
                                    )
                                    sys.stdout.flush()

                except OSError:
                    # Disk full or permission error — expected when space runs out
                    break

                if stopped:
                    break

            elapsed = time.time() - start
            print(f"\n  Pass {p} complete: wrote {format_bytes(written)} in {format_time(elapsed)}")

            # Delete temp files from this pass to free space for next pass
            print(f"  Cleaning up pass {p} temp files...")
            for fname in os.listdir(wipe_dir):
                if fname.startswith(f"wipe_p{p}_"):
                    try:
                        os.remove(os.path.join(wipe_dir, fname))
                    except OSError:
                        pass

            if stopped:
                break

    except KeyboardInterrupt:
        print("\n\n  [!] Interrupted by user. Cleaning up...")

    finally:
        # Always clean up temp directory
        print(f"\n  Removing temp directory...")
        try:
            shutil.rmtree(wipe_dir, ignore_errors=True)
        except Exception:
            pass

    total_elapsed = time.time() - total_start
    free_after = get_free_space(drive)

    print(f"\n{'=' * 60}")
    if stopped:
        print(f"  STOPPED by user after {format_time(total_elapsed)}")
    else:
        print(f"  DONE — {passes} pass(es) completed in {format_time(total_elapsed)}")
    print(f"  Free space now: {format_bytes(free_after)}")
    print(f"  Previously deleted files are now UNRECOVERABLE.")
    print(f"{'=' * 60}\n")


def wipe_mft_records(drive: str):
    """
    Use Windows built-in `cipher /w:` to wipe free space including
    MFT directory entries. Requires admin privileges.
    """
    print(f"\n  Running 'cipher /w:{drive}' for MFT record cleanup...")
    print(f"  (This is a Windows built-in and may take a while)\n")
    os.system(f"cipher /w:{drive}")


def cmd_wipe(args):
    """Handle the 'wipe' subcommand."""
    # Validate passes
    if args.passes < 1:
        print("[ERROR] Passes must be at least 1.")
        sys.exit(1)
    if args.passes > 35:
        print("[ERROR] Maximum 35 passes supported (Gutmann method).")
        sys.exit(1)

    # Run the wipe
    wipe_free_space(args.drive, passes=args.passes, dry_run=args.dry_run)

    # Optionally run cipher for MFT cleanup
    if args.cipher and not args.dry_run:
        wipe_mft_records(args.drive)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(
        prog="securedelete",
        description="Securely shred files or wipe free disk space to prevent data recovery.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Commands:
  shred   Securely delete specific files or folders
  wipe    Wipe all free disk space on a drive
  clean   Shred system traces, logs, and browser history
  recover Recover deleted files from the Recycle Bin

Examples:
  python securedelete.py shred secret.txt              Shred a file
  python securedelete.py shred *.log                   Shred by pattern
  python securedelete.py shred "C:\\Secrets" -r         Shred entire folder
  python securedelete.py shred file.txt -p 1 -f        Fast shred, no confirm
  python securedelete.py wipe C:                       Wipe C: drive (3-pass)
  python securedelete.py wipe C: -p 3 --cipher         Wipe + MFT cleanup
  python securedelete.py clean --system --browsers     Shred temp files & browsers
        """
    )

    subparsers = parser.add_subparsers(dest="command", help="Command to run")

    # --- shred subcommand ---
    shred_parser = subparsers.add_parser(
        "shred",
        help="Securely delete specific files or folders",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    shred_parser.add_argument(
        "targets",
        nargs="+",
        help="Files or directories to shred (supports glob patterns like *.log)"
    )
    shred_parser.add_argument(
        "-p", "--passes",
        type=int,
        default=3,
        help="Number of overwrite passes (default: 3)"
    )
    shred_parser.add_argument(
        "-r", "--recursive",
        action="store_true",
        help="Recursively shred directories"
    )
    shred_parser.add_argument(
        "-f", "--force",
        action="store_true",
        help="Skip confirmation prompt"
    )

    # --- wipe subcommand ---
    wipe_parser = subparsers.add_parser(
        "wipe",
        help="Wipe all free disk space to destroy previously deleted files",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    wipe_parser.add_argument(
        "drive",
        help="Target drive letter (e.g. C: or D:)"
    )
    wipe_parser.add_argument(
        "-p", "--passes",
        type=int,
        default=3,
        help="Number of overwrite passes (default: 3)"
    )
    wipe_parser.add_argument(
        "--cipher",
        action="store_true",
        help="Also run Windows 'cipher /w:' for MFT cleanup (admin required)"
    )
    wipe_parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Simulate the wipe without writing data"
    )

    # --- clean subcommand ---
    clean_parser = subparsers.add_parser(
        "clean",
        help="Shred system activities, logs, and browser history",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    clean_parser.add_argument(
        "--system",
        action="store_true",
        help="Shred system temp, prefetch, and recent items"
    )
    clean_parser.add_argument(
        "--browsers",
        action="store_true",
        help="Shred browser cache, history, and cookies across all supported browsers"
    )
    clean_parser.add_argument(
        "--logs",
        action="store_true",
        help="Clear Windows Event Logs (requires admin)"
    )
    clean_parser.add_argument(
        "--inet",
        action="store_true",
        help="Shred IE / Edge-Legacy INetCache and WebCache"
    )
    clean_parser.add_argument(
        "--crash-dumps",
        dest="crash_dumps",
        action="store_true",
        help="Shred Windows crash-dump and WER report files"
    )
    clean_parser.add_argument(
        "--dns",
        action="store_true",
        help="Flush the Windows DNS resolver cache (ipconfig /flushdns)"
    )
    clean_parser.add_argument(
        "--thumbnails",
        action="store_true",
        help="Shred Windows Explorer thumbnail cache (thumbcache_*.db)"
    )
    clean_parser.add_argument(
        "-p", "--passes",
        type=int,
        default=3,
        help="Number of overwrite passes (default: 3)"
    )

    # --- recover subcommand ---
    recover_parser = subparsers.add_parser(
        "recover",
        help="Recover deleted files from the Recycle Bin",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    recover_parser.add_argument(
        "targets",
        nargs="*",
        help="Specific file names to recover (omit to recover all)"
    )
    recover_parser.add_argument(
        "-l", "--list",
        action="store_true",
        help="List items in the Recycle Bin without recovering"
    )
    recover_parser.add_argument(
        "-f", "--force",
        action="store_true",
        help="Skip confirmation prompt"
    )
    recover_parser.add_argument(
        "--deep",
        metavar="DRIVE",
        help="Perform a deep raw disk signature carve on the specified drive (e.g., C:)"
    )
    recover_parser.add_argument(
        "--limit",
        type=int,
        default=1024,
        help="Maximum amount of drive space to scan in MB (default: 1024 MB, 0 for full drive)"
    )

    args = parser.parse_args()

    if args.command == "shred":
        cmd_shred(args)
    elif args.command == "wipe":
        cmd_wipe(args)
    elif args.command == "clean":
        cmd_clean(args)
    elif args.command == "recover":
        cmd_recover(args)
    else:
        parser.print_help()
        sys.exit(1)


if __name__ == "__main__":
    main()
