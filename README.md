# nz-roof-solar

House-level PV yield modelling for New Zealand addresses, built from open data.

Point it at a latitude and longitude and it walks the whole chain: the site's parcel and
address point from the regional council's ArcGIS service, the house outline from LINZ
Building Outlines, the roof shape from 1 m LiDAR, a site horizon from LiDAR plus the PVGIS
terrain profile, an hourly ERA5 irradiance archive from Open-Meteo, and a pvlib yield model.
Everything is written to `out/` as JSON plus a daily CSV.

**Note:** this models a single house at a time from a location you supply. It does not geocode
an address for you — see [Running the pipeline](#running-the-pipeline).

## Pipeline

Six steps, run in this order by `pipeline.py`:

| Step | What it does | Source | Output |
| --- | --- | --- | --- |
| `find_roof` | Queries the parcel, address and building layers that intersect a box around the site | GWRC Region basemap ArcGIS REST service | `gwrc_features.json` |
| `fetch_outline` | Downloads the building outlines in the search box | LINZ Data Service WFS, NZ Building Outlines (`layer-101290`) | `building_outlines.json` |
| `roof_planes` | Windowed read of the 1 m DSM and DEM around the site, then groups the roof into planes by aspect sector | LINZ 1 m LiDAR via the public `nz-elevation` S3 bucket (COG range reads) | `roof.json`, `dsm.npy`, `dem.npy` |
| `roof_from_parcel` | Finds the LINZ building inside the parcel, erodes the eave edge, keeps locally planar pixels, and fits the two gable faces | Reads `parcel.json` (supplied by you), plus the files above | `roof_point.json` |
| `fetch_weather` | Far terrain horizon, then the hourly archive for the configured window | PVGIS `printhorizon`; Open-Meteo ERA5 archive API | `horizon_pvgis.json`, `weather_hourly.json` |
| `roof_yield` | Solar position, horizon shading, plane-of-array irradiance, cell temperature, monthly and seasonal yield | pvlib (Hay-Davies sky, SAPM close-mount cell temperature) | `yield.json`, `daily_yield.csv` |

How the yield model works (`roof_yield.py`):

- The horizon is the higher of the LiDAR-derived near horizon (trees and buildings within the
  LiDAR window) and the PVGIS far terrain horizon, sampled every 5° of azimuth. Beam irradiance
  below the horizon is zeroed; diffuse irradiance is scaled by a sky view factor computed from
  the horizon.
- Four scenarios are modelled: all panels on the north-west face, both faces split in
  proportion to the two string voltages, the south-east face alone, and a reference
  north-facing 25° array. Which face actually carries the panels is not known, so all four are
  reported.
- Losses (default 0.14, the PVWatts default) and a power temperature coefficient (default
  −0.0037 /°C) are applied, and output is clipped at a 10 kW inverter rating.
- The modelled year is scaled to an external annual yield reference if you configure one
  (`reference_kwh_per_kw_year`, or `reference_annual_kwh` ÷ `reference_system_kw`). The
  month-to-month *shape* always comes from this model; only the level is scaled. With no
  reference configured, the model output is reported unscaled.

## Requirements

- Python 3.11 or newer (the config layer uses the standard library `tomllib`).
- [uv](https://docs.astral.sh/uv/) for the environment and dependencies.
- A free LINZ Data Service API key, for the Building Outlines WFS request.
- Network access to the GWRC ArcGIS service, the LINZ Data Service and LINZ elevation bucket,
  the PVGIS API and the Open-Meteo archive API.

## Setup

```bash
uv venv
uv pip install -r requirements.txt
```

### Get a LINZ Data Service API key

Create a free key at <https://linz.data.govt.nz/> (account → API keys), then put it in the
environment. The pipeline only ever reads it from `LINZ_API_KEY`; it is never read from the
config file, and `fetch_outline.py` does not print the request URL (which carries the key) on
failure.

```bash
cp .env.example .env
# edit .env and set LINZ_API_KEY=your-key-here
set -a; . ./.env; set +a
```

`.env` is git-ignored.

### Configure the site

```bash
cp config.example.toml config.toml
```

Then edit `config.toml`. The essentials:

| Key | Meaning |
| --- | --- |
| `lat`, `lon` | Site coordinates in decimal degrees. **Required** — the pipeline exits if either is missing. |
| `address` | Optional address string, used by `find_roof` as a case-insensitive token matched against feature attributes. |
| `search_radius_m` | Half-width in metres of the parcel/building search box (default 150). |
| `lidar_tile_url` | URL template for the 1 m LiDAR tiles, with a `{kind}` placeholder filled in as `dsm_1m` / `dem_1m`. Replace `YOUR_TILE_ID` with the regional tile your site falls in. |
| `lidar_half_window_m` | Metres either side of the house read from the tiles (default 150). |
| `kwp` | Installed system size in kWp. |
| `string_split` | The two string voltages; the panel split between faces is proportional to them. |
| `reference_kwh_per_kw_year` | External annual yield reference used to scale the modelled year. Leave empty (along with the two keys below) for unscaled output. |
| `weather_start_date`, `weather_end_date` | The hourly archive window (defaults `2006-01-01` to `2025-12-31`). |
| `out_dir` | Where generated files go (default `out`). |

`config.toml` is git-ignored, so your site details stay local. Every value can also be passed
on the command line, and the flag wins.

`config.example.toml` is a worked example: set `lat` and `lon` to your own site's coordinates
before running. The Linz tile id in `lidar_tile_url` and `lidar_tile_id` likewise has to be
replaced with the tile covering your site.

## Running the pipeline

`roof_from_parcel.py` reads `parcel.json` from the output folder, and no step writes that file.
Before your first run, export the parcel polygon for your site from the council's parcel layer
(a single feature with an exterior ring) and save it as `out/parcel.json`. It is accepted either
as an ArcGIS feature with `geometry.rings` or as a GeoJSON feature with
`geometry.coordinates`. The parcel and address features for the search box are also collected
in `out/gwrc_features.json` by the `find_roof` step, which you can run first for reference.

```bash
python pipeline.py
```

Or pass the site on the command line:

```bash
python pipeline.py --lat -41.2 --lon 174.8 --address "1 Example Street" --kwp 6.0
```

Each step can also be run on its own, and each accepts `--config` and `--out-dir`:

```bash
python roof_planes.py --config config.toml --out-dir out
python roof_yield.py --kwp 6.0 --losses 0.14
```

### `pipeline.py` flags

- `--config PATH` — path to the TOML config file (default: `config.toml`).
- `--address TEXT` — street address of the site.
- `--lat DEG` — site latitude in decimal degrees.
- `--lon DEG` — site longitude in decimal degrees.
- `--out-dir PATH` — directory for generated files (default: `out`).
- `--steps STEP [STEP ...]` — subset of steps to run, in order. Choices: `find_roof`,
  `fetch_outline`, `roof_planes`, `roof_from_parcel`, `fetch_weather`, `roof_yield`.
- `--skip-existing` — skip a step whose output files already exist.

### Flags accepted by individual steps

Every step script is built on the same argument parser, so each one accepts `--config`,
`--out-dir`, `--address`, `--lat` and `--lon` in addition to the flags below.

- `find_roof.py`: `--search-radius-m`, `--address-token` (case-insensitive token matched
  against feature attributes; defaults to the configured `address`).
- `fetch_outline.py`: `--search-radius-m`.
- `roof_planes.py`: `--lidar-tile-url`, `--lidar-tile-id`, `--lidar-half-window-m`.
- `fetch_weather.py`: `--weather-start-date`, `--weather-end-date`.
- `roof_yield.py`: `--kwp`, `--string-split A B`, `--losses`, `--gamma`,
  `--reference-kwh-per-kw-year`, `--reference-annual-kwh`, `--reference-system-kw`.

## Outputs

Everything lands in `out/` (or `--out-dir`):

| File | Contents |
| --- | --- |
| `gwrc_features.json` | Every parcel/address/building feature returned for the search box, keyed by layer name. |
| `building_outlines.json` | LINZ Building Outlines features in the search box. |
| `roof.json` | Crop transform, per-plane area/tilt/azimuth, roof area and ground height. |
| `dsm.npy`, `dem.npy` | The LiDAR crops (surface and ground), used by the horizon step. |
| `roof_point.json` | Roof centre pixel and height, the fitted gable faces (`north-west`, `south-east`) and the LINZ building id. |
| `horizon_pvgis.json` | The PVGIS terrain horizon profile. |
| `weather_hourly.json` | The ERA5 hourly archive (irradiance, temperature, wind). |
| `yield.json` | Horizon by azimuth, sky view factor, the reference used, and per-scenario monthly/seasonal yield, winter share and year min/max. |
| `daily_yield.csv` | Daily kWh per kW per day for each scenario, scaled to the reference. |

`yield.json` and the CSVs are git-ignored: they describe a specific house.

## Data sources and licences

The code in this repository is MIT licensed (see [LICENSE](LICENSE)). The data it fetches is
not yours to relicense — it comes from third parties:

- **LINZ Data Service** (NZ Building Outlines, and the 1 m LiDAR elevation tiles): licensed
  under [CC BY 4.0](https://creativecommons.org/licenses/by/4.0/). Attribution: *Sourced from
  the LINZ Data Service and licensed for reuse under CC BY 4.0.*
- **Open-Meteo** (ERA5 hourly archive): licensed under
  [CC BY 4.0](https://creativecommons.org/licenses/by/4.0/). Attribution: *Weather data by
  [Open-Meteo.com](https://open-meteo.com/).*
- **PVGIS** (horizon profile), European Commission Joint Research Centre: free to use,
  subject to the PVGIS terms of use — check them before publishing results.
- **GWRC** parcel, address and building layers, from the Greater Wellington Regional Council's public
  ArcGIS service: check the council's terms before redistributing.

## Limitations

- **The gable fit assumes two faces.** `roof_from_parcel.py` fits exactly two roof faces, from
  the aspect sectors 270–360° and 90–180°. Hipped, mono-pitch, multi-gable and flat roofs are
  not represented by that fit, and the roof planes reported by `roof_planes.py` are ignored by
  the yield model.
- **The GWRC parcel layer covers the Wellington region only.** The default `arcgis_base` points
  at the Greater Wellington Regional Council service; for sites outside that region you would need a
  different parcel source, and `find_roof` matches on layer names containing "parcel",
  "address" or "building".
- **You supply the parcel.** No step downloads `parcel.json`; export it from the council's
  parcel layer yourself.
- **The LiDAR tile is not inferred.** `lidar_tile_url` ships with a `YOUR_TILE_ID` placeholder
  that you must replace with the regional tile covering your site.
- **The model reports scenarios, not a measurement.** Which face carries the panels is unknown,
  and the panel count per face is inferred from two string voltages.
- **The inverter rating is fixed** at 10 kW in `roof_yield.py`.
- **The near horizon only sees the LiDAR window** (150 m by default), so tall obstacles just
  outside it are seen only by the PVGIS terrain horizon, which excludes vegetation and
  buildings.
- **No geocoding.** Pass a latitude/longitude; the `address` value is only used as a text token
  when matching council feature attributes.

## Contributing

See [CONTRIBUTING.md](CONTRIBUTING.md).
