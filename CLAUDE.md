# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this repo is

A Pakistan-adapted fork of [PyAEZ v2.2](https://github.com/gicait/PyAEZ) — a Python library for Agro-Ecological Zoning (AEZ). The upstream library was developed for Lao PDR; this fork replaces input data and notebook parameters with Pakistan-specific datasets (WorldClim v2.1, SRTM DEM, GADM boundary, FAO HWSD soils).

## Installation

```bash
# Local (conda recommended for GDAL)
conda install -c conda-forge gdal rasterio numpy scipy pandas numba requests openpyxl
pip install -e .

# pip only
pip install -r requirements.txt
```

## Running the analysis

The full AEZ pipeline runs as six ordered Jupyter notebooks in `tutorials/`:

```bash
jupyter notebook tutorials/NB1_ClimateRegime.ipynb
```

Run notebooks in order (NB1→NB6); outputs of each feed into the next.

## Google Colab

Each notebook auto-detects Colab and installs dependencies. Steps:

1. Clone the repo into Colab: `!git clone https://github.com/YOUR_USERNAME/PK-PyAEZ.git /content/PK-PyAEZ`
2. Open a notebook and run all cells — the setup cell handles GDAL + pip installs automatically
3. On first run of NB1, uncomment the data download line in cell-4 to fetch the ~500 MB WorldClim dataset

`work_dir` resolves to `/content/PK-PyAEZ` in Colab and `..` (repo root) locally — all `./data_input/` paths work in both environments.

**SciPy compatibility:** `scipy>=1.10` removed `interp1d`; `UtilitiesCalc.interpMonthlyToDaily` uses `make_interp_spline` instead.

## Data preparation scripts (run once)

```bash
# Download WorldClim v2.1 climate data for Pakistan (~500 MB, no auth needed)
python scripts/download_nb1_worldclim.py

# Download DEM, admin mask, slope, and soil rasters (needs NASA EarthData ~/.netrc for SRTM)
python scripts/download_rasters_pakistan.py

# Download ERA5 reanalysis climate data
python scripts/download_era5_pakistan.py

# Re-apply Pakistan substitutions to all 6 tutorial notebooks (after upstream changes)
python scripts/update_notebooks_pk.py
```

## Architecture

### Core library (`pyaez/`)

Six modules map to the six pipeline steps:

| Class | File | Role |
|---|---|---|
| `ClimateRegime` | `ClimateRegime.py` | Module I — loads climate arrays, computes ETO, LGP, thermal indicators |
| `CropSimulation` | `CropSimulation.py` | Module II — pixel-wise crop cycle simulation to find max yield; most compute-intensive |
| `ClimaticConstraints` | `ClimaticConstraints.py` | Module III — applies fc3 reduction factors from lookup tables |
| `SoilConstraints` | `SoilConstraints.py` | Module IV — applies fc4 from soil quality parameters (HWSD v2.0) |
| `TerrainConstraints` | `TerrainConstraints.py` | Module V — applies fc5 from slope/terrain Excel sheets |
| `EconomicSuitability` | `EconomicSuitability.py` | Module VI — break-even analysis to compute net revenue maps |

Supporting classes used internally:

- `ETOCalc` — Penman-Monteith reference evapotranspiration; Numba-accelerated
- `BioMassCalc` — De Wit (1965) biomass model; SciPy cubic-spline interpolation
- `CropWatCalc` — FAO CropWat crop water requirements; Numba-accelerated
- `LGPCalc` — Length of Growing Period; `@jit(nopython=True)` Numba kernels
- `ThermalScreening` — temperature-based crop screening
- `UtilitiesCalc` — monthly→daily interpolation, latitude grid generation, GDAL I/O

### Data formats

| Type | Location | Format |
|---|---|---|
| Climate arrays | `data_input/climate/*.npy` | 3D NumPy (12 months × rows × cols) |
| Spatial rasters | `data_input/*.tif` | GeoTIFF (admin mask, DEM, slope, soil) |
| Crop parameters | `data_input/*.xlsx` | Excel (crop cycle params, constraint LUTs, soil/terrain reduction factors) |
| Raw WorldClim | `data_input/worldclim_raw/` | Zipped GeoTIFFs (not committed) |

Pakistan bounding box: `W=60.5, S=23.0, E=78.5, N=37.5` at 10 arc-min resolution → 87×108 grid.

### Key data flow

```
WorldClim .npy arrays + PK_Admin.tif + PK_Elevation.tif
        ↓ ClimateRegime (NB1)
Climate indicators (LGP, thermal zones, ETO)
        ↓ CropSimulation (NB2)  ← crop .xlsx parameters
Yield maps (kg/ha, rainfed + irrigated)
        ↓ ClimaticConstraints (NB3)  ← fc3 Excel LUTs
fc3-adjusted yield
        ↓ SoilConstraints (NB4)  ← soil .xlsx + PK_Soil.tif
fc4-adjusted yield
        ↓ TerrainConstraints (NB5)  ← terrain .xlsx + PK_Slope.tif
fc5-adjusted yield
        ↓ EconomicSuitability (NB6)
Net revenue maps
```

### Performance note

`CropSimulation` runs pixel-by-pixel across the entire grid and can take hours. `ETOCalc`, `CropWatCalc`, and `LGPCalc` use Numba JIT; first run triggers compilation. Avoid modifying Numba-decorated functions (`@jit(nopython=True)`) without checking Numba compatibility — `scipy` interpolation is intentionally excluded from Numba sections (see `BioMassCalc.py` comment).

### tutorials/A_Data_Preparation/

Contains standalone versions of the `pyaez/` module files (`code/`) alongside training PDFs and GEE data-preparation notes. These are teaching copies — the authoritative source is `pyaez/`.
