"""
Download all static assets needed for offline use.
Thoroughly downloads JSME fragments, deferred JS, and CSS.
"""
import os
import re
import sys
import urllib.request
import urllib.error

JSME_BASE = "https://jsme-editor.github.io/dist/jsme/"
# Project root is two levels above this script (scripts/ -> chem_db_web/)
_ROOT  = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT_DIR = os.path.join(_ROOT, "static", "jsme")

def _fetch(url: str, dest: str, silent_fail=False) -> bool:
    os.makedirs(os.path.dirname(dest), exist_ok=True)
    name = os.path.relpath(dest, OUT_DIR)
    if not silent_fail:
        print(f"  {name} ... ", end="", flush=True)
    try:
        urllib.request.urlretrieve(url, dest)
        if not silent_fail:
            size = os.path.getsize(dest)
            print(f"OK ({size:,} bytes)")
        return True
    except Exception:
        if not silent_fail:
            print("FAILED")
        return False

def main():
    os.makedirs(OUT_DIR, exist_ok=True)
    print("Thoroughly downloading JSME editor assets for offline use...")
    print(f"  Destination: {OUT_DIR}\n")

    # 1. Main bootstrap
    nocache_dest = os.path.join(OUT_DIR, "jsme.nocache.js")
    if not _fetch(JSME_BASE + "jsme.nocache.js", nocache_dest):
        print("\nCould not reach JSME CDN.")
        return 1

    with open(nocache_dest, "r", encoding="utf-8", errors="replace") as f:
        js_text = f.read()

    # 2. Strong names (GWT cache fragments)
    strong_names = sorted(set(re.findall(r'\b([0-9A-F]{32})\b', js_text)))
    print(f"\nFound {len(strong_names)} GWT cache fragment(s)")

    for name in strong_names:
        cache_name = f"{name}.cache.js"
        dest = os.path.join(OUT_DIR, cache_name)
        if _fetch(JSME_BASE + cache_name, dest):
            # 3. Discovery for deferred fragments (try 1-15)
            print(f"    Scanning for deferred fragments for {name[:8]}...", end="", flush=True)
            found_d = 0
            for i in range(1, 16):
                d_rel = f"deferredjs/{name}/{i}.cache.js"
                d_url = JSME_BASE + d_rel
                d_dest = os.path.join(OUT_DIR, d_rel.replace("/", os.sep))
                if _fetch(d_url, d_dest, silent_fail=True):
                    found_d += 1
            print(f" Found {found_d}")

    # 4. Common missing assets from logs
    print("\nDownloading auxiliary assets...")
    extras = [
        "gwt/chrome/mosaic.css",
        "clear.cache.gif",
    ]
    for extra in extras:
        _fetch(JSME_BASE + extra, os.path.join(OUT_DIR, extra.replace("/", os.sep)))

    print(f"\nDone. Assets downloaded to {OUT_DIR}")
    print("Molibrary is now fully offline-ready.")
    return 0

if __name__ == "__main__":
    sys.exit(main())
