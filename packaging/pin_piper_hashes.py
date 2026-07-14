#!/usr/bin/env python3
"""Fetch the SHA-256 of each pinned Piper asset and print the PIPER_SHA256
block to paste into src/voxfox_gtk.py.

Run on a machine that can reach GitHub:
    python3 packaging/pin_piper_hashes.py

The hashes for a pinned release never change, so this is a one-time step per
Piper version bump. It downloads each asset to memory, hashes it, and prints
the dict — it does not modify any file, so you stay in control.
"""

import hashlib
import re
import sys
import urllib.request

# Read the pinned version and asset names straight from the app, so this
# script and the app can never disagree.
import os
HERE = os.path.dirname(os.path.abspath(__file__))
GTK = os.path.join(HERE, "..", "src", "voxfox_gtk.py")
src = open(GTK, encoding="utf-8").read()

version = re.search(r'PIPER_VERSION\s*=\s*"([^"]+)"', src).group(1)
base = ("https://github.com/rhasspy/piper/releases/download/" + version)
assets = [
    "piper_linux_x86_64.tar.gz",
    "piper_linux_aarch64.tar.gz",
    "piper_linux_armv7l.tar.gz",
]

print(f"# Piper {version}")
print("PIPER_SHA256 = {")
for asset in assets:
    url = f"{base}/{asset}"
    try:
        with urllib.request.urlopen(url, timeout=120) as r:
            data = r.read()
        digest = hashlib.sha256(data).hexdigest()
        print(f'    "{asset}": "{digest}",')
    except Exception as e:
        print(f'    # {asset}: FAILED ({e})', file=sys.stderr)
print("}")
