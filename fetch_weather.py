"""Fetch the far horizon (PVGIS, terrain) and hourly irradiance (Open-Meteo ERA5 archive) for the site.

Writes horizon_pvgis.json and weather_hourly.json.
"""
import json
import urllib.request

from config import build_parser, out_dir, resolve_config


def main():
    parser = build_parser("Fetch the horizon profile and the hourly weather archive for the site.")
    parser.add_argument("--weather-start-date", default=None, help="first day of the archive window (YYYY-MM-DD)")
    parser.add_argument("--weather-end-date", default=None, help="last day of the archive window (YYYY-MM-DD)")
    args = parser.parse_args()

    cfg = resolve_config(args, require_location=True)
    lat, lon = float(cfg["lat"]), float(cfg["lon"])
    target = out_dir(cfg)

    hz = json.load(urllib.request.urlopen(
        f"https://re.jrc.ec.europa.eu/api/v5_3/printhorizon?lat={lat}&lon={lon}&outputformat=json", timeout=60))
    (target / "horizon_pvgis.json").write_text(json.dumps(hz["outputs"]["horizon_profile"]))
    print("horizon points", len(hz["outputs"]["horizon_profile"]))

    url = ("https://archive-api.open-meteo.com/v1/archive?"
           f"latitude={lat}&longitude={lon}&start_date={cfg['weather_start_date']}&end_date={cfg['weather_end_date']}"
           "&hourly=shortwave_radiation,direct_normal_irradiance,diffuse_radiation,temperature_2m,wind_speed_10m"
           "&timezone=UTC&wind_speed_unit=ms")
    wx = json.load(urllib.request.urlopen(url, timeout=300))
    (target / "weather_hourly.json").write_text(json.dumps(wx["hourly"]))
    print("hours", len(wx["hourly"]["time"]))
    print("wrote", target / "horizon_pvgis.json", "and", target / "weather_hourly.json")


if __name__ == "__main__":
    main()
