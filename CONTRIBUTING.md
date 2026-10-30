# Contributing

Thanks for looking at nz-roof-solar. Bug reports, better roof-fitting and new data sources are
all welcome.

## Development setup

```bash
uv venv
uv pip install -r requirements.txt
source .venv/bin/activate

cp .env.example .env        # set LINZ_API_KEY in it
set -a; . ./.env; set +a
cp config.example.toml config.toml
```

`config.toml`, `.env` and `out/` are git-ignored. **Never commit them** — they hold your API
key, your site coordinates and the generated data for a specific house.

## Running and checking your change

Run a single step rather than the whole pipeline while iterating:

```bash
python roof_planes.py --config config.toml
python roof_yield.py --config config.toml
```

The scripts fetch live data from the council, LINZ, PVGIS and Open-Meteo, so a change to the
maths in `roof_yield.py` can be exercised against files already in `out/` without re-downloading
anything. There is no test suite yet; a change is expected to run end to end for one site, and
you should say which site shape (gable, hip, flat) you checked when you open a pull request.

## Code style

- Plain Python, standard library plus the packages in `requirements.txt`. Adding a dependency
  needs a reason in the pull request.
- Every script is a small `main()` driven by `config.build_parser()` / `resolve_config()`, so new
  options should be added to `config.py` first (a `DEFAULT_CONFIG` key, an entry in
  `apply_args`, and a flag) and then read from the config, not hard-coded.
- Everything the pipeline generates goes to `out_dir(cfg)`. Do not write next to the scripts.
- Keep the source free of site-specific details: no addresses, coordinates, lot numbers or
  personal names in code, comments, docs or examples. Use placeholder values.
- The LINZ API key comes from the `LINZ_API_KEY` environment variable only. Never read it from
  the config file, never log it, and never include it in a URL in an error message.
- Values that come with a judgement call (losses, temperature coefficient, inverter rating)
  should be configurable or clearly commented where they are fixed.

## Pull requests

1. Fork, branch off `main`, make the change.
2. Keep the diff focused; separate unrelated cleanups.
3. Describe what you ran and what you saw, including the before/after numbers if you changed the
   model.
4. Do not include generated files, `.npy` crops or CSVs from a real address.

## Reporting issues

Include the command you ran, the full traceback, your Python version, and the *shape* of the
problem — for example "the parcel contains two building outlines" or "the fitted face is
south-east". Do not paste a real street address, your API key, or coordinates of a private
house; a nearby placeholder or a description of the site is enough to reproduce most issues.
