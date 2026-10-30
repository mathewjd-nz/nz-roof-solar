"""Crop the LiDAR DSM/DEM around the site and find the roof planes.

Reads only a window of the 1 m DSM and DEM from the public LINZ bucket (COG range reads).
Writes roof.json: per roof plane its area, tilt and azimuth, plus crops saved as .npy for the horizon step.
"""
import json
from pathlib import Path

import numpy as np
import rasterio
from pyproj import Transformer
from rasterio.windows import from_bounds
from scipy import ndimage

from config import build_parser, out_dir, resolve_config


def main():
    parser = build_parser("Crop the LiDAR around the site and find its roof planes.")
    parser.add_argument("--lidar-tile-url", default=None,
                        help="tile URL template with a {kind} placeholder")
    parser.add_argument("--lidar-tile-id", default=None, help="LiDAR tile identifier")
    parser.add_argument("--lidar-half-window-m", type=int, default=None,
                        help="metres either side of the house (default: 150)")
    args = parser.parse_args()

    cfg = resolve_config(args, require_location=True)
    lat, lon = float(cfg["lat"]), float(cfg["lon"])
    tile = cfg["lidar_tile_url"]
    half = int(cfg["lidar_half_window_m"])
    target = out_dir(cfg)

    x, y = Transformer.from_crs(4326, 2193, always_xy=True).transform(lon, lat)

    def crop(kind):
        with rasterio.open("/vsicurl/" + tile.format(kind)) as src:
            win = from_bounds(x - half, y - half, x + half, y + half, src.transform)
            return src.read(1, window=win).astype(float), src.window_transform(win)

    dsm, tf = crop("dsm_1m")
    dem, _ = crop("dem_1m")
    np.save(target / "dsm.npy", dsm)
    np.save(target / "dem.npy", dem)
    ndsm = dsm - dem

    # House pixel, then the connected raised region (>2.5 m above ground) around it within 25 m
    col, row = ~tf * (x, y)
    row, col = int(row), int(col)
    raised = ndsm > 2.5
    labels, _ = ndimage.label(raised)
    near = labels[max(0, row - 25):row + 25, max(0, col - 25):col + 25]
    ids, counts = np.unique(near[near > 0], return_counts=True)
    # the building nearest the geocode point
    dist = {i: np.min(np.hypot(*(np.argwhere(labels == i) - [row, col]).T)) for i in ids}
    bid = min(dist, key=dist.get)
    roof = labels == bid
    print(f"building pixels {roof.sum()} m2, nearest {dist[bid]:.0f} m from geocode, height {np.median(ndsm[roof]):.1f} m")

    # Per-pixel slope and aspect (azimuth clockwise from north) from 3x3 gradients
    gy, gx = np.gradient(dsm)  # rows go south as index rises
    dzdx, dzdy = gx, -gy       # east and north gradients (1 m cells)
    tilt = np.degrees(np.arctan(np.hypot(dzdx, dzdy)))
    aspect = (np.degrees(np.arctan2(-dzdx, -dzdy)) + 360) % 360  # direction the slope faces
    interior = ndimage.binary_erosion(roof, iterations=1)
    ok = interior & (tilt < 60)

    # Group into planes by aspect sector (45 deg bins); flat if tilt < 5
    planes = []
    flat = ok & (tilt < 5)
    if flat.sum() > 3:
        planes.append({"facing": "flat", "area_m2": int(flat.sum()), "tilt": round(float(np.median(tilt[flat])), 1), "azimuth": 0})
    names = ["N", "NE", "E", "SE", "S", "SW", "W", "NW"]
    sector = ((aspect + 22.5) // 45).astype(int) % 8
    for s in range(8):
        m = ok & (tilt >= 5) & (sector == s)
        if m.sum() < 6:
            continue
        az = np.degrees(np.arctan2(np.sin(np.radians(aspect[m])).mean(), np.cos(np.radians(aspect[m])).mean())) % 360
        planes.append({"facing": names[s], "area_m2": int(m.sum()), "tilt": round(float(np.median(tilt[m])), 1), "azimuth": round(float(az), 0)})
    planes.sort(key=lambda p: -p["area_m2"])
    out = {"nztm": [round(x), round(y)], "pixel": [row, col], "roof_area_m2": int(roof.sum()),
           "ground_m": round(float(np.median(dem[roof])), 1), "planes": planes, "transform": list(tf)[:6]}
    (target / "roof.json").write_text(json.dumps(out, indent=1))
    for p in planes:
        print(p)
    print("wrote", target / "roof.json")


if __name__ == "__main__":
    main()
