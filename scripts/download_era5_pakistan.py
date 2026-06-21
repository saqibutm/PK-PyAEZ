#!/usr/bin/env python3
"""
Download ERA5 climate data for Pakistan and convert to PyAEZ .npy format.

Setup (one-time):
    pip install cdsapi netCDF4 numpy scipy

CDS account (free):
    1. Register at https://cds.climate.copernicus.eu
    2. Go to your profile → API key
    3. Create ~/.cdsapirc with:
           url: https://cds.climate.copernicus.eu/api/v2
           key: <UID>:<API-KEY>

Run from the repo root:
    python scripts/download_era5_pakistan.py
"""

import calendar
import warnings
from pathlib import Path

import cdsapi
import netCDF4 as nc
import numpy as np

warnings.filterwarnings("ignore")

# ── CONFIG ────────────────────────────────────────────────────────────────────
YEARS  = list(range(1991, 2021))           # 30-year climatology (1991–2020)
MONTHS = [f"{m:02d}" for m in range(1, 13)]
AREA   = [37.5, 60.5, 23.0, 78.5]         # [N, W, S, E] — Pakistan + buffer

OUT_DIR = Path("data_input/climate")       # final .npy files land here
RAW_DIR = Path("data_input/era5_raw")      # temporary NetCDF downloads
# ─────────────────────────────────────────────────────────────────────────────


def _client():
    return cdsapi.Client()


def download_monthly_means():
    """
    Download ERA5 monthly-averaged reanalysis for 6 variables in one request.
    Variables: mean 2m-temperature, dewpoint, precipitation, u/v wind, solar radiation.
    """
    out = RAW_DIR / "era5_monthly_means.nc"
    if out.exists():
        print(f"  Skipping monthly means (already exists: {out})")
        return

    print("Downloading ERA5 monthly means …")
    _client().retrieve(
        "reanalysis-era5-single-levels-monthly-means",
        {
            "product_type": "monthly_averaged_reanalysis",
            "variable": [
                "2m_temperature",
                "2m_dewpoint_temperature",
                "total_precipitation",
                "10m_u_component_of_wind",
                "10m_v_component_of_wind",
                "surface_solar_radiation_downwards",
            ],
            "year":  [str(y) for y in YEARS],
            "month": MONTHS,
            "time":  "00:00",
            "area":  AREA,
            "format": "netcdf",
        },
        str(out),
    )
    print(f"  Saved → {out}")


def download_temp_extremes():
    """
    Approximate monthly max/min temperature using ERA5 at fixed hours:
      15 UTC ≈ afternoon peak  (max)
       6 UTC ≈ pre-dawn trough (min)

    More accurate alternative: 'derived-era5-single-levels-daily-statistics'
    (larger download, needs extra post-processing — not used here for simplicity).
    """
    for hour, label in [("15:00", "tmax"), ("06:00", "tmin")]:
        out = RAW_DIR / f"era5_{label}.nc"
        if out.exists():
            print(f"  Skipping {label} (already exists: {out})")
            continue
        print(f"Downloading ERA5 temperature at {hour} → {label} …")
        _client().retrieve(
            "reanalysis-era5-single-levels-monthly-means",
            {
                "product_type": "monthly_averaged_reanalysis_by_hour_of_day",
                "variable": "2m_temperature",
                "year":  [str(y) for y in YEARS],
                "month": MONTHS,
                "time":  hour,
                "area":  AREA,
                "format": "netcdf",
            },
            str(out),
        )
        print(f"  Saved → {out}")


# ── PROCESSING HELPERS ────────────────────────────────────────────────────────

def _month_indices(ds):
    times = nc.num2date(ds.variables["time"][:], ds.variables["time"].units)
    return np.array([t.month for t in times])


def _climatology(data, month_idx):
    """Average over all years for each calendar month → shape (lat, lon, 12)."""
    clim = np.zeros((*data.shape[1:], 12))
    for m in range(1, 13):
        clim[..., m - 1] = np.nanmean(data[month_idx == m], axis=0)
    return clim


def _rh_from_dewpoint(T_K, Td_K):
    """
    Relative humidity [0–1] via the August-Roche-Magnus approximation.
    Both inputs in Kelvin.
    """
    T  = T_K  - 273.15
    Td = Td_K - 273.15
    es = 6.1078 * np.exp(17.27 * T  / (T  + 237.3))
    ea = 6.1078 * np.exp(17.27 * Td / (Td + 237.3))
    return np.clip(ea / es, 0.0, 1.0)


def _wind_10m_to_2m(u10, v10, z0=0.01):
    """
    Convert 10 m wind components to 2 m wind speed using logarithmic profile.
    z0 = 0.01 m (default roughness for flat/cropland).
    """
    speed_10m = np.sqrt(u10 ** 2 + v10 ** 2)
    factor    = np.log(2.0 / z0) / np.log(10.0 / z0)
    return speed_10m * factor


# ── MAIN PROCESSING ───────────────────────────────────────────────────────────

def process_to_npy():
    OUT_DIR.mkdir(parents=True, exist_ok=True)

    print("\nProcessing monthly means …")
    ds = nc.Dataset(RAW_DIR / "era5_monthly_means.nc")
    midx = _month_indices(ds)

    # ── Mean temperature (K → °C)
    t2m_raw = ds.variables["t2m"][:]          # (time, lat, lon), Kelvin
    mean_temp = _climatology(t2m_raw - 273.15, midx)

    # ── Relative humidity from dewpoint
    d2m_raw = ds.variables["d2m"][:]
    rh_full = _rh_from_dewpoint(t2m_raw, d2m_raw)
    rel_humidity = _climatology(rh_full, midx)

    # ── Precipitation: ERA5 tp is in metres (accumulated over the month).
    #    Convert to mm/month.
    tp_raw = ds.variables["tp"][:]            # metres
    precipitation = _climatology(tp_raw * 1000.0, midx)   # → mm/month

    # ── Wind speed: 10 m → 2 m
    u10 = _climatology(ds.variables["u10"][:], midx)
    v10 = _climatology(ds.variables["v10"][:], midx)
    wind_speed = _wind_10m_to_2m(u10, v10)

    # ── Shortwave radiation: ERA5 ssrd is J m⁻² (accumulated per hour in
    #    monthly-mean product). Divide by 3600 to get W m⁻².
    ssrd_raw = ds.variables["ssrd"][:]
    short_rad = _climatology(ssrd_raw / 3600.0, midx)

    ds.close()

    # ── Max / Min temperature
    print("Processing temperature extremes …")
    clim_T = {}
    for label, fallback_offset in [("tmax", +5.0), ("tmin", -5.0)]:
        f = RAW_DIR / f"era5_{label}.nc"
        if f.exists():
            ds_t  = nc.Dataset(f)
            midx_t = _month_indices(ds_t)
            clim_T[label] = _climatology(ds_t.variables["t2m"][:] - 273.15, midx_t)
            ds_t.close()
        else:
            print(f"  WARNING: {f.name} not found — using mean_temp {fallback_offset:+.0f}°C")
            clim_T[label] = mean_temp + fallback_offset

    max_temp = clim_T["tmax"]
    min_temp = clim_T["tmin"]

    # ── Save ──────────────────────────────────────────────────────────────────
    arrays = {
        "max_temp":        max_temp,
        "min_temp":        min_temp,
        "precipitation":   precipitation,
        "relative_humidity": rel_humidity,
        "wind_speed":      wind_speed,
        "short_rad":       short_rad,
    }

    print("\nSaving .npy files …")
    for name, arr in arrays.items():
        path = OUT_DIR / f"{name}.npy"
        np.save(path, arr)
        print(f"  {name}.npy  shape={arr.shape}  "
              f"range=[{np.nanmin(arr):.2f}, {np.nanmax(arr):.2f}]")

    _write_metadata(max_temp.shape)
    print(f"\nAll files saved to {OUT_DIR.resolve()}")


def _write_metadata(shape):
    rows, cols, _ = shape
    with open(OUT_DIR / "Metadata.txt", "w") as f:
        f.write(f"""\
Pakistan ERA5 Climate Data — PyAEZ Format
==========================================
Source       : ERA5 Reanalysis (ECMWF / Copernicus CDS)
Period       : {YEARS[0]}–{YEARS[-1]} (30-year monthly climatology)
Bounding box : N={AREA[0]}, W={AREA[1]}, S={AREA[2]}, E={AREA[3]}
Grid size    : {rows} rows × {cols} cols  (~0.25° resolution)
Format       : numpy .npy, shape (rows, cols, 12 months)

Variables
---------
max_temp.npy          Monthly mean of daily max 2m temperature   [°C]
min_temp.npy          Monthly mean of daily min 2m temperature   [°C]
precipitation.npy     Monthly total precipitation                [mm/month]
relative_humidity.npy Monthly mean relative humidity             [fraction 0-1]
wind_speed.npy        Monthly mean wind speed at 2m              [m/s]
short_rad.npy         Monthly mean shortwave radiation           [W/m²]

Processing notes
----------------
- RH derived from 2m temperature and 2m dewpoint (Magnus formula)
- Wind speed adjusted from 10m to 2m (log profile, z0=0.01 m)
- Max/min T from ERA5 monthly means at 15 UTC / 06 UTC respectively
- Precipitation converted from ERA5 metres (accumulated) to mm/month

PyAEZ settings for Pakistan
----------------------------
lat_min = 23.5
lat_max = 37.1
daily   = False   (monthly data)
""")
    print(f"  Metadata.txt written.")


# ── ENTRY POINT ───────────────────────────────────────────────────────────────

if __name__ == "__main__":
    print("=" * 60)
    print("  ERA5 Downloader for Pakistan — PyAEZ")
    print("=" * 60)
    print(f"  Period : {YEARS[0]}–{YEARS[-1]}")
    print(f"  Area   : N={AREA[0]} W={AREA[1]} S={AREA[2]} E={AREA[3]}")
    print(f"  Output : {OUT_DIR.resolve()}\n")

    RAW_DIR.mkdir(parents=True, exist_ok=True)

    download_monthly_means()
    download_temp_extremes()
    process_to_npy()

    print("\nNext steps:")
    print("  1. Run: python scripts/download_rasters_pakistan.py")
    print("  2. Open tutorials/NB1_ClimateRegime.ipynb")
    print("     Set lat_min=23.5, lat_max=37.1, daily=False")
    print("     Replace LAO_ paths with PK_ paths")
