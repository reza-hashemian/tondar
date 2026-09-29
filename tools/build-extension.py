#!/usr/bin/env python3
"""Assemble build/extension/{chrome,firefox} and tondar-firefox.xpi from extension/.

Works on Linux and Windows (no zip/ImageMagick needed; icons are committed PNGs).
"""
import json
import os
import re
import shutil
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SRC = os.path.join(ROOT, "extension")
FILES = ["background.js", "content.js", "popup.html", "popup.css", "popup.js"]


def app_version():
    with open(os.path.join(ROOT, "src", "tondar", "__init__.py")) as f:
        return re.search(r'^VERSION = "(.+)"', f.read(), re.M).group(1)


def main(out=None):
    out = out or os.path.join(ROOT, "build", "extension")
    shutil.rmtree(out, ignore_errors=True)
    for browser in ("chrome", "firefox"):
        d = os.path.join(out, browser)
        os.makedirs(d)
        for name in FILES:
            shutil.copy(os.path.join(SRC, name), d)
        with open(os.path.join(SRC, f"manifest.{browser}.json")) as f:
            manifest = json.load(f)
        manifest["version"] = app_version()  # Mozilla signs each version only once
        with open(os.path.join(d, "manifest.json"), "w") as f:
            json.dump(manifest, f, indent=2)
        shutil.copytree(os.path.join(SRC, "icons"), os.path.join(d, "icons"))
    xpi = shutil.make_archive(os.path.join(out, "tondar-firefox"), "zip", os.path.join(out, "firefox"))
    os.replace(xpi, os.path.join(out, "tondar-firefox.xpi"))
    print("Extension built in", out)


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else None)
