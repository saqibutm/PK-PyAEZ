#!/usr/bin/env python3
"""
Download WorldClim v2.1 climate data + GADM boundary for Pakistan.
Creates every input file needed to run NB1_ClimateRegime.ipynb.

No account required. Downloads ~500 MB total.

Dependencies (already installed):
    pip install rasterio scipy

Run from repo root:
    python scripts/download_nb1_worldclim.py
"""

import io
import json
import math
import zipfile
from pathlib import Path

import numpy as np
import requests
import rasterio
from rasterio.crs import CRS
from rasterio.features import rasterize
from rasterio.transform import from_bounds
from rasterio.windows import from_bounds as win_from_bounds

# ── CONFIG ────────────────────────────────────────────────────────────────────
XMIN, YMIN = 60.5, 23.0   # west, south
XMAX, YMAX = 78.5, 37.5   # east, north  — Pakistan + small buffer
RES_MIN    = 10            # WorldClim resolution (arc-minutes)
RES_DEG    = RES_MIN / 60  # 0.1667°

OUT_DIR = Path("data_input")
RAW_DIR = Path("data_input/worldclim_raw")
CLM_DIR = Path("data_input/climate")

NCOLS = round((XMAX - XMIN) / RES_DEG)   # 108
NROWS = round((YMAX - YMIN) / RES_DEG)   # 87

TRANSFORM = from_bounds(XMIN, YMIN, XMAX, YMAX, NCOLS, NROWS)
WGS84     = CRS.from_epsg(4326)
NODATA    = -9999.0
# ─────────────────────────────────────────────────────────────────────────────


# ── DOWNLOAD ──────────────────────────────────────────────────────────────────

def _get(url: str, dest: Path, label: str = "") -> bool:
    dest.parent.mkdir(parents=True, exist_ok=True)
    tag = label or dest.name
    try:
        with requests.get(url, stream=True, timeout=300) as r:
            r.raise_for_status()
            total = int(r.headers.get("content-length", 0))
            done  = 0
            with open(dest, "wb") as f:
                for chunk in r.iter_content(1 << 20):
                    f.write(chunk)
                    done += len(chunk)
                    if total:
                        print(f"\r  {tag}: {100*done//total:3d}%  {done>>20} MB / {total>>20} MB",
                              end="", flush=True)
        print(f"\r  {tag}: done ({done>>20} MB)          ")
        return True
    except Exception as e:
        print(f"\n  ERROR {tag}: {e}")
        return False


def _wc_url(var: str) -> str:
    base = "https://geodata.ucdavis.edu/climate/worldclim/2_1/base"
    return f"{base}/wc2.1_{RES_MIN}m_{var}.zip"


# ── READ HELPERS ──────────────────────────────────────────────────────────────

def _clip_to_pk(src: rasterio.DatasetReader) -> np.ndarray:
    """Read Pakistan window from an open rasterio dataset."""
    window = win_from_bounds(XMIN, YMIN, XMAX, YMAX, transform=src.transform)
    data = src.read(1, window=window,
                    out_shape=(NROWS, NCOLS),
                    resampling=rasterio.enums.Resampling.bilinear).astype(np.float32)
    nd = src.nodata
    if nd is not None:
        data[data == nd] = np.nan
    return data


def load_monthly(var: str) -> np.ndarray:
    """Download WorldClim ZIP, read 12 monthly GeoTIFFs → (NROWS, NCOLS, 12)."""
    zip_path = RAW_DIR / f"wc2.1_{RES_MIN}m_{var}.zip"
    if not zip_path.exists():
        print(f"Downloading WorldClim '{var}' …")
        if not _get(_wc_url(var), zip_path, label=var):
            raise RuntimeError(f"Download failed: {var}")
    else:
        print(f"  Cached: {zip_path.name}")

    cube = np.full((NROWS, NCOLS, 12), np.nan, dtype=np.float32)
    with zipfile.ZipFile(zip_path) as zf:
        tifs = sorted(n for n in zf.namelist() if n.endswith(".tif"))
        assert len(tifs) == 12, f"Expected 12 TIFs in {zip_path.name}, got {len(tifs)}"
        for i, name in enumerate(tifs):
            buf = io.BytesIO(zf.read(name))
            with rasterio.open(buf) as src:
                cube[..., i] = _clip_to_pk(src)
    return cube


def load_elev() -> np.ndarray:
    zip_path = RAW_DIR / f"wc2.1_{RES_MIN}m_elev.zip"
    if not zip_path.exists():
        print("Downloading WorldClim elevation …")
        if not _get(_wc_url("elev"), zip_path, label="elev"):
            raise RuntimeError("Download failed: elev")
    else:
        print(f"  Cached: {zip_path.name}")
    with zipfile.ZipFile(zip_path) as zf:
        tifs = [n for n in zf.namelist() if n.endswith(".tif")]
        buf = io.BytesIO(zf.read(tifs[0]))
    with rasterio.open(buf) as src:
        return _clip_to_pk(src)


# ── SAVE HELPER ───────────────────────────────────────────────────────────────

def _save_tif(path: Path, arr: np.ndarray, dtype="float32", nodata=NODATA):
    out = arr.copy().astype(dtype)
    out[np.isnan(arr)] = nodata
    with rasterio.open(path, "w", driver="GTiff", crs=WGS84,
                       transform=TRANSFORM, width=NCOLS, height=NROWS,
                       count=1, dtype=dtype, nodata=nodata) as dst:
        dst.write(out, 1)


# ── CLIMATE PROCESSING ────────────────────────────────────────────────────────

def process_climate():
    CLM_DIR.mkdir(parents=True, exist_ok=True)

    print("\n── Climate variables ────────────────────────────────────────")
    tmax = load_monthly("tmax")   # °C
    tmin = load_monthly("tmin")   # °C
    prec = load_monthly("prec")   # mm / month
    wind = load_monthly("wind")   # m/s at 10 m
    srad = load_monthly("srad")   # kJ m⁻² day⁻¹
    vapr = load_monthly("vapr")   # kPa (actual vapour pressure)

    # ── Derived quantities ──
    # Wind 10 m → 2 m  (log profile, roughness z0 = 0.01 m)
    wind_2m = wind * (math.log(2 / 0.01) / math.log(10 / 0.01))

    # Shortwave radiation  kJ m⁻² day⁻¹ → W m⁻²  (÷ 86.4)
    short_rad = srad / 86.4

    # Relative humidity from vapour pressure (Tetens saturation formula)
    tmean = (tmax + tmin) / 2.0
    sat_vp = 0.6108 * np.exp(17.27 * tmean / (tmean + 237.3))   # kPa
    rel_humidity = np.clip(vapr / sat_vp, 0.0, 1.0)

    print("\nSaving .npy arrays …")
    data = [
        ("max_temp",         tmax,         "°C"),
        ("min_temp",         tmin,         "°C"),
        ("precipitation",    prec,         "mm/month"),
        ("wind_speed",       wind_2m,      "m/s @2m"),
        ("short_rad",        short_rad,    "W/m²"),
        ("relative_humidity",rel_humidity, "0–1"),
    ]
    for name, arr, unit in data:
        np.save(CLM_DIR / f"{name}.npy", arr.astype(np.float64))
        print(f"  {name}.npy  shape={arr.shape}  "
              f"[{np.nanmin(arr):.1f} – {np.nanmax(arr):.1f}] {unit}")

    # Metadata
    (CLM_DIR / "Metadata.txt").write_text(f"""\
Pakistan WorldClim v2.1 Climate Data — PyAEZ Format
====================================================
Source       : WorldClim v2.1 (Fick & Hijmans 2017, Sci Data)
Period       : 1970–2000 monthly climatology
Resolution   : {RES_MIN} arc-min (~{RES_DEG*111:.0f} km per pixel)
Bounding box : N={YMAX}, W={XMIN}, S={YMIN}, E={XMAX}
Grid         : {NROWS} rows × {NCOLS} cols

Variables
---------
max_temp.npy          Monthly max 2m temperature       [°C]
min_temp.npy          Monthly min 2m temperature       [°C]
precipitation.npy     Monthly total precipitation      [mm/month]
relative_humidity.npy Monthly relative humidity        [fraction 0-1]
wind_speed.npy        Monthly mean wind speed @2m      [m/s]
short_rad.npy         Monthly mean shortwave radiation [W/m²]

Derivations
-----------
RH    = vapr / sat_vp(Tmean)   [Tetens formula]
wind2 = wind10 × ln(2/0.01)/ln(10/0.01)
srad  = srad_kJday / 86.4

NB1 settings
------------
lat_min = 23.0  |  lat_max = 37.5  |  daily = False
""")


# ── SPATIAL RASTERS ───────────────────────────────────────────────────────────

def make_admin_mask():
    out = OUT_DIR / "PK_Admin.tif"
    if out.exists():
        print(f"  Exists: PK_Admin.tif")
        return

    gadm = RAW_DIR / "gadm41_PAK_0.json"
    if not gadm.exists():
        print("Downloading GADM Pakistan boundary …")
        _get("https://geodata.ucdavis.edu/gadm/gadm4.1/json/gadm41_PAK_0.json",
             gadm, label="GADM")

    gj = json.loads(gadm.read_text())
    shapes = [(feat["geometry"], 1) for feat in gj["features"]]
    mask = rasterize(shapes, out_shape=(NROWS, NCOLS),
                     transform=TRANSFORM, fill=0, dtype="uint8")
    _save_tif(out, mask.astype(np.float32), dtype="uint8", nodata=0)
    print(f"  Saved PK_Admin.tif  (land pixels: {int(mask.sum()):,} / {NROWS*NCOLS:,})")


def make_elevation_slope():
    elev_out  = OUT_DIR / "PK_Elevation.tif"
    slope_out = OUT_DIR / "PK_Slope.tif"
    if elev_out.exists() and slope_out.exists():
        print("  Exists: PK_Elevation.tif + PK_Slope.tif")
        return

    elev = load_elev()
    _save_tif(elev_out, elev)
    print(f"  Saved PK_Elevation.tif  [{np.nanmin(elev):.0f}–{np.nanmax(elev):.0f}] m")

    # Slope in degrees using numpy.gradient + geographic pixel sizes
    lat_centres = YMAX - (np.arange(NROWS) + 0.5) * RES_DEG
    dy_m  = RES_DEG * 111111.0                                      # ~18.5 km
    dx_m  = RES_DEG * 111111.0 * np.cos(np.radians(lat_centres))   # varies with lat

    elev_f   = np.where(np.isnan(elev), 0.0, elev)
    dz_dy_px, dz_dx_px = np.gradient(elev_f)

    dz_dy = dz_dy_px / dy_m
    dz_dx = dz_dx_px / (dx_m[:, None] * np.ones((1, NCOLS)))

    slope = np.degrees(np.arctan(np.sqrt(dz_dx**2 + dz_dy**2))).astype(np.float32)
    slope[np.isnan(elev)] = np.nan

    _save_tif(slope_out, slope)
    print(f"  Saved PK_Slope.tif      [{np.nanmin(slope):.1f}–{np.nanmax(slope):.1f}] °")


def make_soil_terrain_lulc():
    out = OUT_DIR / "PK_soil_terrain_lulc.tif"
    if out.exists():
        print("  Exists: PK_soil_terrain_lulc.tif")
        return

    with rasterio.open(OUT_DIR / "PK_Elevation.tif") as src:
        elev = src.read(1).astype(np.float32)
        elev[elev == src.nodata] = np.nan

    # 1 = general land,  33 = permanent ice/snow (FAO AEZ convention)
    lulc = np.where(np.isnan(elev), 0, 1).astype(np.int32)
    lulc[elev > 4500] = 33

    _save_tif(out, lulc.astype(np.float32), dtype="int32", nodata=-9999)
    print(f"  Saved PK_soil_terrain_lulc.tif  "
          f"(ice/snow pixels: {int((lulc==33).sum()):,})")


# ── VERIFY ────────────────────────────────────────────────────────────────────

def verify():
    print("\n── Verification ─────────────────────────────────────────────")
    ok = True
    for v in ["max_temp","min_temp","precipitation","relative_humidity","wind_speed","short_rad"]:
        p = CLM_DIR / f"{v}.npy"
        if p.exists():
            a = np.load(p)
            print(f"  OK  {v}.npy  {a.shape}")
        else:
            print(f"  MISSING  {v}.npy"); ok = False

    for r in ["PK_Admin.tif","PK_Elevation.tif","PK_Slope.tif","PK_soil_terrain_lulc.tif"]:
        p = OUT_DIR / r
        if p.exists():
            with rasterio.open(p) as s:
                print(f"  OK  {r}  ({s.height}×{s.width})")
        else:
            print(f"  MISSING  {r}"); ok = False

    if ok:
        print("\nAll NB1 inputs ready.")
        print("Next: install gdal for the notebooks → conda install -c conda-forge gdal")
        print("Then open: tutorials/NB1_ClimateRegime.ipynb")


# ── MAIN ──────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    print("=" * 60)
    print("  WorldClim Downloader for Pakistan — NB1 inputs")
    print("=" * 60)
    print(f"  Grid   : {NROWS} rows × {NCOLS} cols @ {RES_MIN} arc-min")
    print(f"  Extent : N={YMAX}  W={XMIN}  S={YMIN}  E={XMAX}")
    print(f"  ~500 MB download total\n")

    RAW_DIR.mkdir(parents=True, exist_ok=True)

    process_climate()

    print("\n── Spatial rasters ──────────────────────────────────────────")
    make_admin_mask()
    make_elevation_slope()
    make_soil_terrain_lulc()

    verify()
