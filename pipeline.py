"""Run the whole nz-roof-solar pipeline for one site.

Steps, in order:
    find_roof -> fetch_outline -> roof_planes (crop) -> roof_from_parcel -> fetch_weather -> roof_yield

Every step reads and writes inside the output folder (``out/`` by default).
The site is described by the config file and/or the command line flags; the LINZ
API key comes from the LINZ_API_KEY environment variable.
"""
import argparse
import json
import shutil
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).parent
sys.path.insert(0, str(HERE))

from config import ConfigError, apply_args, load_config, out_dir  # noqa: E402

STEPS = ("find_roof", "fetch_outline", "roof_planes", "roof_from_parcel", "fetch_weather", "roof_yield")


def step_command(step, args, out_path):
    cmd = [sys.executable, str(HERE / f"{step}.py"), "--config", args.config, "--out-dir", str(out_path)]
    if args.lat is not None:
        cmd += ["--lat", str(args.lat)]
    if args.lon is not None:
        cmd += ["--lon", str(args.lon)]
    if args.address is not None:
        cmd += ["--address", args.address]
    return cmd


def main():
    parser = argparse.ArgumentParser(description="Run the full nz-roof-solar pipeline for a site.")
    parser.add_argument("--config", default=None, help="path to the TOML config file (default: config.toml)")
    parser.add_argument("--address", default=None, help="street address of the site")
    parser.add_argument("--lat", type=float, default=None, help="site latitude in decimal degrees")
    parser.add_argument("--lon", type=float, default=None, help="site longitude in decimal degrees")
    parser.add_argument("--out-dir", default=None, help="directory for generated files (default: out)")
    parser.add_argument("--steps", nargs="+", default=list(STEPS), choices=list(STEPS),
                        help="subset of steps to run, in order")
    parser.add_argument("--skip-existing", action="store_true",
                        help="skip a step whose output files already exist")
    args = parser.parse_args()

    try:
        cfg = apply_args(load_config(args.config), args)
    except (ConfigError, OSError) as exc:
        raise SystemExit(str(exc))
    if cfg.get("lat") is None or cfg.get("lon") is None:
        raise SystemExit(
            "latitude and longitude are required: set 'lat'/'lon' in the config file or pass --lat/--lon")

    out_path = out_dir(cfg)
    print(f"pipeline output: {out_path}")

    for step in args.steps:
        outputs = {
            "find_roof": ["gwrc_features.json"],
            "fetch_outline": ["building_outlines.json"],
            "roof_planes": ["roof.json", "dsm.npy", "dem.npy"],
            "roof_from_parcel": ["roof_point.json"],
            "fetch_weather": ["horizon_pvgis.json", "weather_hourly.json"],
            "roof_yield": ["yield.json", "daily_yield.csv"],
        }[step]
        if args.skip_existing and all((out_path / name).exists() for name in outputs):
            print(f"== {step}: outputs already present, skipping")
            continue

        print(f"== {step}")
        cmd = step_command(step, args, out_path)
        result = subprocess.run(cmd)
        if result.returncode != 0:
            raise SystemExit(f"step {step} failed with exit code {result.returncode}")

    print("pipeline complete")
    summary = out_path / "yield.json"
    if summary.exists():
        data = json.loads(summary.read_text())
        for name, values in data.get("scenarios", {}).items():
            print(f"  {name}: {values['modelled_kwh_per_kw_year']} kWh/kW/yr modelled")


if __name__ == "__main__":
    main()
