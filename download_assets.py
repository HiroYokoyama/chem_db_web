"""
Download all static assets needed for offline use.
Run once during setup — after this, Molibrary works with no internet.

Usage:
    python download_assets.py
"""
import os
import re
import sys
import urllib.request
import urllib.error

JSME_BASE = "https://jsme-editor.github.io/dist/JSME_2022-04-05/jsme/"
OUT_DIR   = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                         "static", "jsme")


def _fetch(url: str, dest: str) -> bool:
    name = os.path.basename(dest)
    print(f"  {name} ... ", end="", flush=True)
    try:
        urllib.request.urlretrieve(url, dest)
        size = os.path.getsize(dest)
        print(f"OK ({size:,} bytes)")
        return True
    except urllib.error.URLError as exc:
        print(f"FAILED ({exc.reason})")
        return False
    except Exception as exc:
        print(f"FAILED ({exc})")
        return False


def main():
    os.makedirs(OUT_DIR, exist_ok=True)

    print("Downloading JSME editor for offline use...")
    print(f"  Destination: {OUT_DIR}")
    print()

    # 1. Bootstrap file
    nocache_dest = os.path.join(OUT_DIR, "jsme.nocache.js")
    if not _fetch(JSME_BASE + "jsme.nocache.js", nocache_dest):
        print("\nCould not reach JSME CDN. Check your internet connection.")
        print("Molibrary will fall back to CDN at runtime if this file is missing.")
        return 1

    # 2. Parse the nocache.js to discover all GWT cache-file strong names
    with open(nocache_dest, "r", encoding="utf-8", errors="replace") as fh:
        js_text = fh.read()

    # GWT strong names are uppercase 32-char hex strings
    strong_names = sorted(set(re.findall(r'\b([0-9A-F]{32})\b', js_text)))
    print(f"  Found {len(strong_names)} GWT cache fragment(s)")

    ok = err = 0
    for name in strong_names:
        filename = f"{name}.cache.js"
        dest = os.path.join(OUT_DIR, filename)
        if os.path.exists(dest):
            print(f"  {filename} ... already present, skipping")
            ok += 1
            continue
        if _fetch(JSME_BASE + filename, dest):
            ok += 1
        else:
            err += 1

    # 3. Also try the .gwt.rpc policy files (non-fatal if missing)
    for rpc_name in ["jsme.rpc"]:
        dest = os.path.join(OUT_DIR, rpc_name)
        if not os.path.exists(dest):
            _fetch(JSME_BASE + rpc_name, dest)

    print()
    if err == 0:
        print(f"Done. {ok} file(s) downloaded — Molibrary will now work fully offline.")
    else:
        print(f"Done with {err} error(s). Some cache fragments may be missing.")
        print("Molibrary will fall back to CDN for those files at runtime.")
    return 0 if err == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
