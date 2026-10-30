"""Find the house roof inside the site's parcel and fit its two gable faces.

Reads parcel.json (a GeoJSON feature with a single exterior ring), building_outlines.json,
roof.json and the LiDAR crops. Writes roof_point.json: roof centre pixel and height (for the
horizon), and each face's tilt, azimuth and area.
"""
import json
from pathlib import Path

import numpy as np
from matplotlib.path import Path as Poly
from pyproj import Transformer
from scipy import ndimage

from config import build_parser, out_dir, resolve_config


def plane_residual(w):
    X = np.c_[np.ones(9), np.tile([-1, 0, 1], 3), np.repeat([-1, 0, 1], 3)]
    coef, *_ = np.linalg.lstsq(X, w, rcond=None)
    return np.std(w - X @ coef)


def main():
    parser = build_parser("Find the roof inside the site's parcel and fit its gable faces.")
    args = parser.parse_args()

    cfg = resolve_config(args)
    target = out_dir(cfg)

    dsm, dem = np.load(target / "dsm.npy"), np.load(target / "dem.npy")
    nd = dsm - dem
    a, _, c, _, e, f = json.loads((target / "roof.json").read_text())["transform"]
    parcel_geojson = json.loads((target / "parcel.json").read_text())
    ring = parcel_geojson["geometry"]["rings"][0] if "rings" in parcel_geojson["geometry"] \
        else parcel_geojson["geometry"]["coordinates"][0]
    to_nztm = Transformer.from_crs(4326, 2193, always_xy=True)
    pix = [((X - c) / a, (Y - f) / e) for X, Y in (to_nztm.transform(x, y) for x, y in ring)]
    rr, cc = np.mgrid[0:dsm.shape[0], 0:dsm.shape[1]]
    parcel = Poly(pix).contains_points(np.c_[cc.ravel() + 0.5, rr.ravel() + 0.5]).reshape(dsm.shape)

    # Roof = the LINZ building outline (fetch_outline.py) whose centre lies in the parcel, less its 1 m eave edge,
    # keeping locally planar pixels
    pts = np.c_[cc.ravel() + 0.5, rr.ravel() + 0.5]
    outline = building_id = None
    for ft in json.loads((target / "building_outlines.json").read_text())["features"]:
        g = ft["geometry"]
        ring = g["coordinates"][0] if g["type"] == "Polygon" else g["coordinates"][0][0]
        opix = [((X - c) / a, (Y - f) / e) for X, Y in (to_nztm.transform(x, y) for x, y in ring)]
        if Poly(pix).contains_point(np.mean(opix, 0)):
            outline, building_id = Poly(opix).contains_points(pts).reshape(dsm.shape), ft["properties"]["building_id"]
            break
    if outline is None:
        raise SystemExit("no LINZ building outline found inside the parcel")
    rough = ndimage.generic_filter(dsm, plane_residual, 3)
    roof = ndimage.binary_erosion(outline) & (rough < 0.35)
    r, col = np.nonzero(roof)

    gy, gx = np.gradient(ndimage.gaussian_filter(dsm, 1))
    aspect = (np.degrees(np.arctan2(-gx, gy)) + 360) % 360  # direction the slope faces, clockwise from north
    faces = []
    for lo, hi, name in ((270, 360, "north-west"), (90, 180, "south-east")):
        k = (aspect[r, col] >= lo) & (aspect[r, col] < hi)
        X = np.c_[np.ones(k.sum()), col[k], -r[k]]
        coef, *_ = np.linalg.lstsq(X, dsm[r[k], col[k]], rcond=None)
        faces.append({"face": name, "area_m2": int(k.sum()),
                      "tilt": round(float(np.degrees(np.arctan(np.hypot(coef[1], coef[2])))), 1),
                      "azimuth": round(float((np.degrees(np.arctan2(-coef[1], -coef[2])) + 360) % 360))})
    out = {"pixel": [round(float(r.mean())), round(float(col.mean()))], "roof_z": round(float(np.median(dsm[r, col])), 1),
           "roof_m2_seen": int(roof.sum()), "outline_m2": int(outline.sum()), "linz_building_id": building_id, "faces": faces,
           "note": "LINZ NZ Building Outlines (layer 101290) building inside the site's parcel; "
                   "planar pixels inside it, eave edge dropped"}
    (target / "roof_point.json").write_text(json.dumps(out, indent=1))
    print(json.dumps(out, indent=1))
    print("wrote", target / "roof_point.json")


if __name__ == "__main__":
    main()
