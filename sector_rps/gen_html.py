#!/usr/bin/env python3
"""Generate sector_rps.html with inline JSON data and JS data file."""
import json
from pathlib import Path

# Paths
base = Path(__file__).parent.parent
docs = base / "docs"
data_file = Path(__file__).parent / "data" / "sector_rps.json"

with open(data_file, "r") as f:
    data = json.load(f)

js_data = json.dumps(data, ensure_ascii=False)

# Read template
template_path = Path(__file__).parent / "sector_rps_template.html"
with open(template_path, "r", encoding="utf-8") as f:
    template = f.read()

# Replace placeholder
html = template.replace("__JSON_DATA__", js_data)

with open(docs / "sector_rps.html", "w", encoding="utf-8") as f:
    f.write(html)
print(f"Written {docs / 'sector_rps.html'} ({len(html)} bytes)")

# Generate JS data file
js_content = f"var SECTOR_RPS_DATA = {js_data};"
with open(docs / "sector_rps_data.js", "w", encoding="utf-8") as f:
    f.write(js_content)
print(f"Written {docs / 'sector_rps_data.js'} ({len(js_content)} bytes)")
