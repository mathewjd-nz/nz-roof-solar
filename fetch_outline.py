"""Fetch LINZ NZ Building Outlines around the site via the LDS WFS.

The API key is read from the LINZ_API_KEY environment variable only.
Writes building_outlines.json.
"""
import json
import urllib.error
import urllib.parse
import urllib.request

from config import build_parser, linz_api_key, out_dir, resolve_config
from find_roof import search_box


def main():
    parser = build_parser("Fetch LINZ NZ Building Outlines around the site.")
    parser.add_argument("--search-radius-m", type=float, default=None,
                        help="half-width of the search box in metres")
    args = parser.parse_args()

    cfg = resolve_config(args, require_location=True)
    key = linz_api_key()
    box = search_box(float(cfg["lat"]), float(cfg["lon"]), float(cfg["search_radius_m"]))
    params = {"service": "WFS", "version": "2.0.0", "request": "GetFeature",
              "typeNames": cfg["linz_building_outlines_layer"],
              "outputFormat": "application/json", "srsName": "EPSG:4326",
              "bbox": f"{box},urn:ogc:def:crs:EPSG::4326"}
    base = cfg["linz_wfs_base"].format(key=key)
    url = f"{base}?" + urllib.parse.urlencode(params)
    try:
        d = json.load(urllib.request.urlopen(url, timeout=60))
    except urllib.error.HTTPError as e:
        raise SystemExit(f"HTTP {e.code}")  # never print the URL: it carries the key
    target = out_dir(cfg)
    (target / "building_outlines.json").write_text(json.dumps(d))
    print(len(d["features"]), "outlines")
    for f in d["features"][:3]:
        print({k: v for k, v in f["properties"].items() if v not in (None, "")})
    print("wrote", target / "building_outlines.json")


if __name__ == "__main__":
    main()
