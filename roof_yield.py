"""Monthly PV yield for a site from its LiDAR roof planes, its horizon and its hourly weather.

Inputs (in the output folder): roof.json and dsm.npy (roof_planes.py), horizon_pvgis.json and
weather_hourly.json (fetch_weather.py), roof_point.json (roof_from_parcel.py).
Writes yield.json: kWh per kWp per day by month and season, yearly totals, and the plane split used.
Assumptions are printed and saved with the result.
"""
import json

import numpy as np
import pandas as pd
import pvlib

from config import build_parser, out_dir, reference_kwh_per_kw, resolve_config


def main():
    parser = build_parser("Model the PV yield for a site.")
    parser.add_argument("--kwp", type=float, default=None, help="installed system size in kWp")
    parser.add_argument("--string-split", type=float, nargs=2, default=None,
                        metavar=("A", "B"),
                        help="the two string voltages; the panel split is proportional to them")
    parser.add_argument("--losses", type=float, default=None, help="system losses fraction")
    parser.add_argument("--gamma", type=float, default=None, help="power temperature coefficient per degC")
    parser.add_argument("--reference-kwh-per-kw-year", type=float, default=None,
                        help="external annual yield reference (kWh per kW) used to scale the modelled year")
    parser.add_argument("--reference-annual-kwh", type=float, default=None,
                        help="external annual energy figure (kWh) used to scale the modelled year")
    parser.add_argument("--reference-system-kw", type=float, default=None,
                        help="the installed size (kW) the external annual energy figure refers to")
    args = parser.parse_args()

    cfg = resolve_config(args)
    target = out_dir(cfg)

    lat, lon = float(cfg["lat"]), float(cfg["lon"])
    KWP = float(cfg["kwp"])
    STRING_SPLIT = tuple(float(v) for v in cfg["string_split"])
    LOSSES = float(cfg["losses"])
    GAMMA = float(cfg["gamma"])

    roof = json.loads((target / "roof.json").read_text())
    dsm = np.load(target / "dsm.npy")

    # Near horizon from the DSM (trees, houses within the LiDAR window), far horizon from PVGIS terrain; take the higher.
    house = json.loads((target / "roof_point.json").read_text())
    r0, c0 = house["pixel"]
    z0 = house["roof_z"] + 0.3  # panels sit just above the roof surface
    az_grid = np.arange(0, 360, 5)
    near = []
    for az in az_grid:
        best = 0.0
        for d in range(3, 148):
            r = int(round(r0 - d * np.cos(np.radians(az))))
            c = int(round(c0 + d * np.sin(np.radians(az))))
            if not (0 <= r < dsm.shape[0] and 0 <= c < dsm.shape[1]):
                break
            best = max(best, np.degrees(np.arctan2(dsm[r, c] - z0, d)))
        near.append(best)
    far = pd.DataFrame(json.loads((target / "horizon_pvgis.json").read_text()))
    far_az = (far["A"].to_numpy() + 180) % 360  # PVGIS azimuth: 0 = south
    far_h = np.interp(az_grid, np.sort(far_az), far["H_hor"].to_numpy()[np.argsort(far_az)], period=360)
    horizon = np.maximum(near, far_h)

    # Faces measured from the LiDAR inside the parcel. Which face carries the panels is not known, so: all on the
    # north-west face, or split across both faces in proportion to the two string voltages. The year is scaled to
    # the external reference annual yield; the monthly shape comes from this model.
    REFERENCE_KWH_PER_KW = reference_kwh_per_kw(cfg)
    nw, se = house["faces"]
    split = STRING_SPLIT[0] / sum(STRING_SPLIT)
    SCENARIOS = {"north-west face": [(nw["tilt"], nw["azimuth"], 1.0)],
                 "both faces (string split)": [(nw["tilt"], nw["azimuth"], split), (se["tilt"], se["azimuth"], 1 - split)],
                 "north 25 deg (reference)": [(25, 0, 1.0)], "south-east face": [(se["tilt"], se["azimuth"], 1.0)]}

    wx = pd.DataFrame(json.loads((target / "weather_hourly.json").read_text()))
    wx.index = pd.to_datetime(wx.pop("time"), utc=True)
    wx = wx.dropna()
    # Open-Meteo hourly values are means over the preceding hour: take the sun at the half hour.
    times = wx.index - pd.Timedelta(minutes=30)
    sun = pvlib.solarposition.get_solarposition(times, lat, lon)
    sun.index = wx.index
    dni_extra = pvlib.irradiance.get_extra_radiation(wx.index)
    shaded = sun["apparent_elevation"].to_numpy() < np.interp(sun["azimuth"].to_numpy(), az_grid, horizon, period=360)
    dni = wx["direct_normal_irradiance"].where(~shaded, 0.0)
    svf = np.mean(np.cos(np.radians(horizon)) ** 2)  # sky view factor for diffuse

    season_of = {12: "Summer", 1: "Summer", 2: "Summer", 3: "Autumn", 4: "Autumn", 5: "Autumn",
                 6: "Winter", 7: "Winter", 8: "Winter", 9: "Spring", 10: "Spring", 11: "Spring"}
    results, daily_all = {}, {}
    for name, planes in SCENARIOS.items():
        ac = pd.Series(0.0, index=wx.index)
        for tilt, az, share in planes:
            poa = pvlib.irradiance.get_total_irradiance(
                tilt, az, sun["apparent_zenith"], sun["azimuth"], dni, wx["shortwave_radiation"],
                wx["diffuse_radiation"] * svf, dni_extra=dni_extra, model="haydavies")["poa_global"].fillna(0).clip(lower=0)
            tcell = pvlib.temperature.sapm_cell(poa, wx["temperature_2m"], wx["wind_speed_10m"],
                                                **pvlib.temperature.TEMPERATURE_MODEL_PARAMETERS["sapm"]["close_mount_glass_glass"])
            ac += KWP * share * poa / 1000 * (1 + GAMMA * (tcell - 25)) * (1 - LOSSES)
        local = ac.clip(upper=10.0).tz_convert("Pacific/Auckland")  # inverter rated 10 kW
        daily = local.resample("D").sum() / KWP
        yearly = local.resample("YE").sum() / KWP
        start_year = int(cfg["weather_start_date"][:4])
        end_year = int(cfg["weather_end_date"][:4])
        yearly = yearly[(yearly.index.year >= start_year) & (yearly.index.year <= end_year)]
        scale = REFERENCE_KWH_PER_KW / yearly.mean() if REFERENCE_KWH_PER_KW else 1.0
        season = daily.groupby(daily.index.month.map(season_of)).mean()
        daily_all[name] = (daily[(daily.index.year >= start_year) & (daily.index.year <= end_year)] * scale).round(3)
        results[name] = {
            "modelled_kwh_per_kw_year": round(float(yearly.mean())),
            "scale_to_reference": round(float(scale), 3),
            "season_kwh_per_kw_day_scaled": {k: round(float(v * scale), 2) for k, v in season.items()},
            "month_kwh_per_kw_day_scaled": {int(k): round(float(v * scale), 2) for k, v in daily.groupby(daily.index.month).mean().items()},
            "winter_share_of_year": round(float(season["Winter"] * 92 / (season * pd.Series({"Summer": 90, "Autumn": 92, "Winter": 92, "Spring": 91})).sum()), 3),
            "year_min_max_scaled": [round(float(yearly.min() * scale)), round(float(yearly.max() * scale))],
        }
    out = {"horizon_deg": {int(a): round(float(h), 1) for a, h in zip(az_grid, horizon)},
           "sky_view_factor": round(float(svf), 3),
           "reference_kwh_per_kw": round(float(REFERENCE_KWH_PER_KW), 3) if REFERENCE_KWH_PER_KW else None,
           "scenarios": results,
           "assumptions": f"{KWP} kWp; {LOSSES:.0%} losses; SAPM close-mount temperature; Hay-Davies sky; beam blocked below "
                          "LiDAR (150 m) and PVGIS terrain horizon; diffuse x sky view factor; Open-Meteo ERA5 hourly "
                          f"{cfg['weather_start_date']}-{cfg['weather_end_date']}; "
                          "year scaled to the configured external annual yield reference."}
    (target / "yield.json").write_text(json.dumps(out, indent=1))
    pd.DataFrame(daily_all).rename_axis("date").to_csv(target / "daily_yield.csv", date_format="%Y-%m-%d")  # kWh per kW, scaled
    print(json.dumps(results, indent=1))
    print("sky view", out["sky_view_factor"], "horizon N/NE/E/W/NW:", {a: out["horizon_deg"][a] for a in (0, 45, 90, 270, 315)})
    print("wrote", target / "yield.json", "and", target / "daily_yield.csv")


if __name__ == "__main__":
    main()
