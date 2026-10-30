"""Find a site's parcel, address point and building outlines from a regional ArcGIS service.

Writes gwrc_features.json: the features of every parcel/address/building layer
that intersect the search box around the site.
"""
import json
import math
import urllib.parse
import urllib.request
from pathlib import Path

from config import build_parser, out_dir, resolve_config

HERE = Path(__file__).parent


def get(url, **params):
    q = urllib.parse.urlencode(params)
    return json.load(urllib.request.urlopen(f"{url}?{q}", timeout=60))


def search_box(lat, lon, radius_m):
    """~180 m box around the geocode, in the ArcGIS envelope order (lon,lat,...)."""
    dlat = radius_m / 111320.0
    dlon = radius_m / (111320.0 * max(0.1, abs(math.cos(math.radians(lat)))))
    return f"{lon - dlon:.6f},{lat - dlat:.6f},{lon + dlon:.6f},{lat + dlat:.6f}"


def main():
    parser = build_parser("Find the parcel, address point and building outlines for a site.")
    parser.add_argument("--search-radius-m", type=float, default=None,
                        help="half-width of the search box in metres")
    parser.add_argument("--address-token", default=None,
                        help="case-insensitive token matched against feature attributes (default: the address)")
    args = parser.parse_args()

    cfg = resolve_config(args, require_location=True)
    base = cfg["arcgis_base"]
    box = search_box(float(cfg["lat"]), float(cfg["lon"]), float(cfg["search_radius_m"]))
    token = (args.address_token or cfg.get("address") or "").strip().lower()
    target = out_dir(cfg)

    layers = get(base, f="json")["layers"]
    print([(l["id"], l["name"]) for l in layers])
    found = {}
    for l in layers:
        if not any(w in l["name"].lower() for w in ("parcel", "address", "building")):
            continue
        d = get(f"{base}/{l['id']}/query", geometry=box, geometryType="esriGeometryEnvelope", inSR=4326, outSR=4326,
                spatialRel="esriSpatialRelIntersects", outFields="*", f="json")
        feats = d.get("features", [])
        hits = [f for f in feats if token and token in json.dumps(f["attributes"]).lower()]
        print(l["id"], l["name"], len(feats), "features,", len(hits), f"mention {token or '(no token)'}",
              d.get("error", ""))
        found[l["name"]] = feats
    (target / "gwrc_features.json").write_text(json.dumps(found))
    print("wrote", target / "gwrc_features.json")


if __name__ == "__main__":
    main()
