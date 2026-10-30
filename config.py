"""Shared configuration for nz-roof-solar.

Settings come from three places, in increasing order of precedence:

1. the defaults in ``DEFAULT_CONFIG`` below,
2. a TOML file (``config.toml`` by default, see ``config.example.toml``),
3. command line flags (which override the file).

The LINZ API key is never read from the TOML file: it comes only from the
``LINZ_API_KEY`` environment variable.
"""
import argparse
import os
import tomllib
from pathlib import Path

HERE = Path(__file__).parent

DEFAULT_CONFIG = {
    # --- site location ---
    "address": "",
    "lat": None,
    "lon": None,
    "search_radius_m": 150.0,
    # --- regional ArcGIS / WFS endpoints ---
    "arcgis_base": "https://mapping.gw.govt.nz/arcgis/rest/services/Region_basemap_P/MapServer",
    "linz_wfs_base": "https://data.linz.govt.nz/services;key={key}/wfs",
    "linz_building_outlines_layer": "layer-101290",
    # --- LiDAR elevation tile ---
    # The tile URL template must contain a {kind} placeholder (dsm_1m / dem_1m).
    # It points at the public LINZ elevation bucket; the tile id below is the
    # regional tile your site sits in (see the LINZ elevation tile index).
    "lidar_tile_url": (
        "https://nz-elevation.s3.ap-southeast-2.amazonaws.com/wellington/"
        "wellington-city_2025/{kind}/2193/YOUR_TILE_ID.tiff"
    ),
    "lidar_tile_id": "YOUR_TILE_ID",
    "lidar_half_window_m": 150,
    # --- yield model ---
    "kwp": 6.0,
    "string_split": [300.0, 300.0],
    "losses": 0.14,
    "gamma": -0.0037,
    "reference_kwh_per_kw_year": None,
    "reference_annual_kwh": None,
    "reference_system_kw": None,
    # --- weather archive window ---
    "weather_start_date": "2006-01-01",
    "weather_end_date": "2025-12-31",
    # --- outputs ---
    "out_dir": "out",
}


class ConfigError(Exception):
    """Raised when the configuration is missing or inconsistent."""


def _deep_merge(base, override):
    merged = dict(base)
    for key, value in override.items():
        if isinstance(value, dict) and isinstance(merged.get(key), dict):
            merged[key] = _deep_merge(merged[key], value)
        else:
            merged[key] = value
    return merged


def load_config(path=None):
    """Load the TOML configuration file (if any) merged over the defaults."""
    cfg = dict(DEFAULT_CONFIG)
    cfg_path = Path(path) if path else HERE / "config.toml"
    if cfg_path.is_file():
        with cfg_path.open("rb") as fh:
            cfg = _deep_merge(cfg, tomllib.load(fh))
    cfg["_config_path"] = str(cfg_path)
    return cfg


def _set_from_namespace(cfg, args, key, cast=None):
    value = getattr(args, key, None)
    if value is None:
        return
    cfg[key] = cast(value) if cast else value


def apply_args(cfg, args):
    """Apply parsed command line arguments on top of the loaded configuration."""
    _set_from_namespace(cfg, args, "address")
    _set_from_namespace(cfg, args, "lat", float)
    _set_from_namespace(cfg, args, "lon", float)
    _set_from_namespace(cfg, args, "search_radius_m", float)
    _set_from_namespace(cfg, args, "arcgis_base")
    _set_from_namespace(cfg, args, "linz_wfs_base")
    _set_from_namespace(cfg, args, "linz_building_outlines_layer")
    _set_from_namespace(cfg, args, "lidar_tile_url")
    _set_from_namespace(cfg, args, "lidar_tile_id")
    _set_from_namespace(cfg, args, "lidar_half_window_m", int)
    _set_from_namespace(cfg, args, "kwp", float)
    _set_from_namespace(cfg, args, "losses", float)
    _set_from_namespace(cfg, args, "gamma", float)
    _set_from_namespace(cfg, args, "reference_kwh_per_kw_year", float)
    _set_from_namespace(cfg, args, "reference_annual_kwh", float)
    _set_from_namespace(cfg, args, "reference_system_kw", float)
    _set_from_namespace(cfg, args, "weather_start_date")
    _set_from_namespace(cfg, args, "weather_end_date")
    _set_from_namespace(cfg, args, "out_dir")
    if getattr(args, "string_split", None):
        cfg["string_split"] = [float(v) for v in args.string_split]
    return cfg


def add_common_arguments(parser, *, include_address=True):
    """Register the flags shared by every script."""
    parser.add_argument("--config", default=None, help="path to the TOML config file (default: config.toml)")
    if include_address:
        parser.add_argument("--address", default=None, help="street address of the site")
        parser.add_argument("--lat", type=float, default=None, help="site latitude in decimal degrees")
        parser.add_argument("--lon", type=float, default=None, help="site longitude in decimal degrees")
    parser.add_argument("--out-dir", default=None, help="directory for generated files (default: out)")


def build_parser(description, *, include_address=True):
    parser = argparse.ArgumentParser(description=description)
    add_common_arguments(parser, include_address=include_address)
    return parser


def resolve_config(args, *, require_location=False):
    """Load the configuration, apply the CLI overrides and validate the result."""
    cfg = apply_args(load_config(args.config), args)
    if require_location and (cfg.get("lat") is None or cfg.get("lon") is None):
        raise ConfigError(
            "latitude and longitude are required: set 'lat'/'lon' in the config file "
            "or pass --lat/--lon"
        )
    return cfg


def out_dir(cfg):
    path = Path(cfg.get("out_dir", "out"))
    if not path.is_absolute():
        path = HERE / path
    path.mkdir(parents=True, exist_ok=True)
    return path


def linz_api_key():
    """Return the LINZ API key from the environment, or fail with a clear message."""
    key = os.environ.get("LINZ_API_KEY", "").strip()
    if not key:
        raise ConfigError(
            "LINZ_API_KEY is not set: export it in your shell or put it in a .env file "
            "(see .env.example). The key is never read from the config file."
        )
    return key


def reference_kwh_per_kw(cfg):
    """Return the external annual yield reference used to scale the modelled year.

    The reference can be given directly (``reference_kwh_per_kw_year``) or derived
    from an annual energy figure and an installed system size
    (``reference_annual_kwh`` / ``reference_system_kw``).
    """
    direct = cfg.get("reference_kwh_per_kw_year")
    if direct:
        return float(direct)
    annual = cfg.get("reference_annual_kwh")
    size_kw = cfg.get("reference_system_kw")
    if annual and size_kw:
        return float(annual) / float(size_kw)
    return None
