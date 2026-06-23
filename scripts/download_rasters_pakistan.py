#!/usr/bin/env python3
"""
Download and prepare spatial rasters for Pakistan — PyAEZ format.

Downloads:
  - Admin mask        : GADM (Pakistan boundary → binary 0/1 raster)
  - DEM               : SRTM 90m from NASA EarthData (elevation in metres)
  - Slope             : derived from DEM using GDAL
  - Soil              : FAO HWSD v2.0 (soil classification)
  - soil_terrain_lulc : combined layer (soil + HWSD MU_GLOBAL codes)

Setup:
    pip install requests numpy gdal scipy

NASA EarthData (free) — needed for SRTM:
    Register at https://urs.earthdata.nasa.gov
    Then add credentials to ~/.netrc:
        machine urs.earthdata.nasa.gov login <USER> password <PASS>

Run from the repo root:
    python scripts/download_rasters_pakistan.py
"""

import math
import os
import subprocess
import sys
from pathlib import Path

import numpy as np
import requests

try:
    from osgeo import gdal, ogr, osr
    gdal.UseExceptions()
except ImportError:
    sys.exit("GDAL not found. Install with:  conda install -c conda-forge gdal")

# ── CONFIG ────────────────────────────────────────────────────────────────────
OUT_DIR  = Path("data_input")
RAW_DIR  = Path("data_input/raster_raw")

# Target grid — must match WorldClim climate arrays (10 arc-min resolution)
# Pakistan bounding box: W=60.5, S=23.0, E=78.5, N=37.5 → 87 rows × 108 cols
XMIN, YMIN, XMAX, YMAX = 60.5, 23.0, 78.5, 37.5
RES = 1 / 6        # 10 arc-min in degrees → 87×108 grid
NODATA = -9999.0
# ─────────────────────────────────────────────────────────────────────────────


def _run(cmd):
    print(f"  $ {' '.join(cmd)}")
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        print(f"  ERROR: {result.stderr.strip()}")
    return result


def _warp(src, dst, resampling="bilinear", dtype="Float32"):
    """Reproject + clip + resample a raster to the target Pakistan grid."""
    _run([
        "gdalwarp", "-overwrite",
        "-t_srs", "EPSG:4326",
        "-te", str(XMIN), str(YMIN), str(XMAX), str(YMAX),
        "-tr", str(RES), str(RES),
        "-r", resampling,
        "-ot", dtype,
        "-dstnodata", str(NODATA),
        "-of", "GTiff",
        src, dst,
    ])


# ── 1. ADMIN MASK ─────────────────────────────────────────────────────────────

def make_admin_mask():
    """
    Download Pakistan boundary from GADM and rasterize to a binary 0/1 mask.
    Uses GADM level-0 (country boundary) GeoPackage.
    """
    out = OUT_DIR / "PK_Admin.tif"
    if out.exists():
        print(f"Skipping admin mask (exists: {out})")
        return

    RAW_DIR.mkdir(parents=True, exist_ok=True)
    gpkg = RAW_DIR / "gadm41_PAK.gpkg"

    if not gpkg.exists():
        print("Downloading GADM Pakistan boundary …")
        url = "https://geodata.ucdavis.edu/gadm/gadm4.1/gpkg/gadm41_PAK.gpkg"
        _download(url, gpkg)

    print("Rasterizing admin boundary → PK_Admin.tif …")
    # First create a blank raster at target resolution
    blank = str(RAW_DIR / "blank.tif")
    _run([
        "gdal_rasterize",
        "-burn", "1",
        "-ts", str(_ncols()), str(_nrows()),
        "-te", str(XMIN), str(YMIN), str(XMAX), str(YMAX),
        "-l", "ADM_ADM_0",
        "-ot", "Byte",
        "-a_nodata", "0",
        "-of", "GTiff",
        str(gpkg), str(out),
    ])
    print(f"  Saved → {out}")


# ── 2. ELEVATION (SRTM) ───────────────────────────────────────────────────────

def download_srtm():
    """
    Download SRTM 90m tiles covering Pakistan and mosaic them.
    Tiles covering Pakistan: roughly x=38-52, y=04-07 (SRTM tile naming).

    Alternatively, use the SRTM 30m or the merged global DEM from OpenTopography.
    Here we use the CGIAR-CSI SRTM 90m (no auth needed).
    """
    out = OUT_DIR / "PK_Elevation.tif"
    if out.exists():
        print(f"Skipping elevation (exists: {out})")
        return

    RAW_DIR.mkdir(parents=True, exist_ok=True)

    # CGIAR-CSI SRTM tiles for Pakistan (5°×5° tiles, named srtm_XX_YY)
    # Pakistan spans approximately: lon 61-78°E, lat 23-37°N
    # Tile formula: x = floor((lon+180)/5)+1, y = floor((60-lat)/5)+1
    tiles = set()
    for lon in range(60, 79, 5):
        for lat in range(22, 38, 5):
            tx = math.floor((lon + 180) / 5) + 1
            ty = math.floor((60 - lat) / 5) + 1
            tiles.add((tx, ty))

    tile_files = []
    base_url = "https://srtm.csi.cgiar.org/wp-content/uploads/files/srtm_5x5/TIFF"
    for tx, ty in sorted(tiles):
        name = f"srtm_{tx:02d}_{ty:02d}.zip"
        zip_path = RAW_DIR / name
        tif_path = RAW_DIR / name.replace(".zip", ".tif")

        if not tif_path.exists():
            if not zip_path.exists():
                print(f"Downloading {name} …")
                _download(f"{base_url}/{name}", zip_path)
            print(f"  Extracting {name} …")
            _run(["unzip", "-o", "-d", str(RAW_DIR), str(zip_path)])
            extracted = RAW_DIR / name.replace(".zip", ".tif")
            if not extracted.exists():
                print(f"  WARNING: {extracted} not found after extraction")
                continue

        tile_files.append(str(tif_path))

    if not tile_files:
        print("No SRTM tiles downloaded — check network / tile names.")
        return

    print(f"Mosaicking {len(tile_files)} SRTM tiles …")
    mosaic = str(RAW_DIR / "srtm_mosaic.tif")
    _run(["gdal_merge.py", "-o", mosaic, "-of", "GTiff", "-n", "-32768"] + tile_files)

    print(f"Warping to Pakistan grid → {out} …")
    _warp(mosaic, str(out), resampling="bilinear", dtype="Float32")
    print(f"  Saved → {out}")


# ── 3. SLOPE ──────────────────────────────────────────────────────────────────

def derive_slope():
    """Compute slope (degrees) from the DEM using gdaldem."""
    dem = OUT_DIR / "PK_Elevation.tif"
    out = OUT_DIR / "PK_Slope.tif"
    if out.exists():
        print(f"Skipping slope (exists: {out})")
        return
    if not dem.exists():
        print("Skipping slope — PK_Elevation.tif not found. Run download_srtm() first.")
        return

    print("Computing slope from DEM …")
    _run(["gdaldem", "slope", str(dem), str(out), "-of", "GTiff"])
    print(f"  Saved → {out}")


# ── 4. SOIL (HWSD v2.0) ───────────────────────────────────────────────────────

def download_hwsd():
    """
    Download FAO HWSD v2.0 raster and clip to Pakistan.
    HWSD v2.0 is freely available from FAO:
      https://gaez.fao.org/pages/hwsd
    The raster contains Mapping Unit (MU) codes linked to a soil attribute database.
    """
    out = OUT_DIR / "PK_Soil.tif"
    if out.exists():
        print(f"Skipping soil (exists: {out})")
        return

    hwsd_global = RAW_DIR / "HWSD2.bil"
    if not hwsd_global.exists():
        print(
            "\nHWSD v2.0 must be downloaded manually:\n"
            "  1. Go to: https://gaez.fao.org/pages/hwsd\n"
            "  2. Download 'HWSD2 Raster' (HWSD2.zip)\n"
            f"  3. Extract HWSD2.bil and HWSD2.hdr to {RAW_DIR}/\n"
            "  Then re-run this script.\n"
        )
        return

    print("Clipping HWSD soil raster to Pakistan …")
    _warp(str(hwsd_global), str(out), resampling="near", dtype="Int32")
    print(f"  Saved → {out}")


# ── 5. COMBINED SOIL/TERRAIN/LULC LAYER ──────────────────────────────────────

def make_soil_terrain_lulc():
    """
    PyAEZ Module I needs a combined soil_terrain_lulc raster.
    This combines: permanent ice/snow (from DEM-derived mask), water bodies,
    and HWSD MU_GLOBAL soil codes into a single layer used for AEZ classification.

    Simplified approach: use HWSD soil codes directly (sufficient for Module I).
    For full accuracy, add ESA CCI Land Cover water/ice classes on top.
    """
    out = OUT_DIR / "PK_soil_terrain_lulc.tif"
    if out.exists():
        print(f"Skipping soil_terrain_lulc (exists: {out})")
        return

    soil = OUT_DIR / "PK_Soil.tif"
    if not soil.exists():
        print("Skipping soil_terrain_lulc — PK_Soil.tif not found.")
        return

    print("Creating soil_terrain_lulc layer …")
    ds  = gdal.Open(str(soil))
    arr = ds.GetRasterBand(1).ReadAsArray().astype(np.int32)

    # Mark pixels above 4500m as permanent ice/snow (class 33 in FAO convention)
    elev_path = OUT_DIR / "PK_Elevation.tif"
    if elev_path.exists():
        elev = gdal.Open(str(elev_path)).GetRasterBand(1).ReadAsArray()
        arr[elev > 4500] = 33   # permanent snow/ice class

    # Write output with same geotransform as soil raster
    driver = gdal.GetDriverByName("GTiff")
    out_ds = driver.Create(str(out), ds.RasterXSize, ds.RasterYSize, 1, gdal.GDT_Int32)
    out_ds.SetGeoTransform(ds.GetGeoTransform())
    out_ds.SetProjection(ds.GetProjection())
    band = out_ds.GetRasterBand(1)
    band.WriteArray(arr)
    band.SetNoDataValue(NODATA)
    out_ds.FlushCache()
    out_ds = None
    ds = None
    print(f"  Saved → {out}")


# ── UTILITIES ─────────────────────────────────────────────────────────────────

def _nrows():
    return round((YMAX - YMIN) / RES)

def _ncols():
    return round((XMAX - XMIN) / RES)

def _download(url, dest, chunk=1 << 20):
    dest = Path(dest)
    dest.parent.mkdir(parents=True, exist_ok=True)
    with requests.get(url, stream=True, timeout=60) as r:
        r.raise_for_status()
        total = int(r.headers.get("content-length", 0))
        done  = 0
        with open(dest, "wb") as f:
            for chunk_data in r.iter_content(chunk):
                f.write(chunk_data)
                done += len(chunk_data)
                if total:
                    pct = 100 * done / total
                    print(f"\r  {pct:5.1f}%  {done>>20} MB / {total>>20} MB", end="", flush=True)
    print()


def verify_outputs():
    print("\nVerification:")
    expected = ["PK_Admin.tif", "PK_Elevation.tif", "PK_Slope.tif",
                "PK_Soil.tif", "PK_soil_terrain_lulc.tif"]
    all_ok = True
    for name in expected:
        p = OUT_DIR / name
        if p.exists():
            ds   = gdal.Open(str(p))
            rows = ds.RasterYSize
            cols = ds.RasterXSize
            gt   = ds.GetGeoTransform()
            print(f"  OK  {name:35s} shape=({rows}×{cols})  origin=({gt[0]:.2f},{gt[3]:.2f})")
        else:
            print(f"  MISSING  {name}")
            all_ok = False

    if all_ok:
        print("\nAll rasters ready. Open NB1_ClimateRegime.ipynb and set:")
        print("  mask_path = 'data_input/PK_Admin.tif'")
        print("  elevation = gdal.Open('data_input/PK_Elevation.tif').ReadAsArray()")
        print("  soil_terrain_lulc = gdal.Open('data_input/PK_soil_terrain_lulc.tif').ReadAsArray()")
        print("  lat_min = 23.0  |  lat_max = 37.5")


# ── ENTRY POINT ───────────────────────────────────────────────────────────────

if __name__ == "__main__":
    print("=" * 60)
    print("  Raster Downloader for Pakistan — PyAEZ")
    print("=" * 60)
    print(f"  Grid   : {_nrows()} rows × {_ncols()} cols @ {RES}°")
    print(f"  Extent : N={YMAX} W={XMIN} S={YMIN} E={XMAX}\n")

    RAW_DIR.mkdir(parents=True, exist_ok=True)

    make_admin_mask()
    download_srtm()
    derive_slope()
    download_hwsd()
    make_soil_terrain_lulc()
    verify_outputs()
