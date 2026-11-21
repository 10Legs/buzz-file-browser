#!/usr/bin/env python3
"""Build the installable plugin folder from the templates.

  python3 scripts/build_plugin.py https://files.example.net:10446

Writes dist/file-browser/{manifest.json,plugin.js}. The origin must be an exact HTTPS origin (scheme, host,
optional port; no path). Buzz asks the owner to approve it at install time.
"""
import json, os, re, sys

if len(sys.argv) != 2 or not re.fullmatch(r"https://[A-Za-z0-9.-]+(:\d{1,5})?", sys.argv[1]):
    sys.exit("usage: build_plugin.py https://host[:port]   (HTTPS origin of your file-browser server, no path)")
origin = sys.argv[1]
here = os.path.dirname(os.path.abspath(__file__))
src, out = os.path.join(here, "..", "plugin"), os.path.join(here, "..", "dist", "file-browser")
os.makedirs(out, exist_ok=True)

manifest = json.load(open(os.path.join(src, "manifest.template.json")))
manifest["host"]["networkOrigins"] = [origin]
json.dump(manifest, open(os.path.join(out, "manifest.json"), "w"), indent=2)
open(os.path.join(out, "manifest.json"), "a").write("\n")

js = open(os.path.join(src, "plugin.template.js")).read()
assert "__SERVER_ORIGIN__" in js
open(os.path.join(out, "plugin.js"), "w").write(js.replace("__SERVER_ORIGIN__", origin))
print(f"built {os.path.normpath(out)} for {origin}")
