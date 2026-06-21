#!/usr/bin/env python3
"""
Transform all 6 PyAEZ tutorial notebooks from Lao PDR settings to Pakistan.
Also fixes output-filename inconsistencies in the original notebooks.

Run from repo root:
    python scripts/update_notebooks_pk.py
"""
import json
from pathlib import Path

TUTORIALS = Path("tutorials")
NOTEBOOKS = [
    "NB1_ClimateRegime.ipynb",
    "NB2_CropSimulation.ipynb",
    "NB3_ClimaticConstraints.ipynb",
    "NB4_SoilConstraints.ipynb",
    "NB5_TerrainConstraints.ipynb",
    "NB6_EconomicSuitability.ipynb",
]

# ---------------------------------------------------------------------------
# Substitutions applied to every code cell in every notebook.
# After json.load(), notebook source is plain Python text; backslashes appear
# as single characters, so use double-backslash in Python string literals below.
# Order matters: more-specific patterns first.
# ---------------------------------------------------------------------------
COMMON_SUBS = [

    # ── 1. Working directory ────────────────────────────────────────────────
    ("r'D:\\test_working_folder'",   "'.'"),
    ("r'D:\\PyAEZv2.1_Draft'",       "'.'"),
    ("sys.path.append('D:\\PyAEZ_iiasa')",   "sys.path.insert(0, '.')"),
    ("sys.path.append(r'D:\\PyAEZ_iiasa')",  "sys.path.insert(0, '.')"),
    ("sys.path.append('./pyaez/')",           "sys.path.insert(0, '.')"),

    # ── 2. Geographic extent ────────────────────────────────────────────────
    ("lat_min = 13.87", "lat_min = 23.0   # Pakistan southern boundary"),
    ("lat_max = 22.59", "lat_max = 37.5   # Pakistan northern boundary"),

    # ── 3. Input data paths (Windows backslash style) ───────────────────────
    # Climate arrays
    ("r'D:\\PyAEZ_iiasa\\data_input\\climate/", "'./data_input/climate/"),
    # Rasters — backslash separator
    ("r'D:\\PyAEZ_iiasa\\data_input\\",         "'./data_input/"),
    # Rasters — forward slash separator
    ("r'D:\\PyAEZ_iiasa\\data_input/",           "'./data_input/"),
    # NB2 reads NB1 outputs via test_working_folder path
    ("r'D:\\test_working_folder\\data_output\\NB1\\", "'./data_output/NB1/"),

    # ── 4. Country prefix: LAO → PK ─────────────────────────────────────────
    ("LAO_", "PK_"),
    ("Lao_", "PK_"),   # NB4 has 'Lao_Soil.tif'

    # ── 5. NB2: fix output paths (backslash → forward slash, normalize names)
    ("r'.\\data_output\\NB2\\maiz_yld_rain.tif'",  "'./data_output/NB2/maiz_yield_rain.tif'"),
    ("r'.\\data_output\\NB2\\maiz_yld_irr.tif'",   "'./data_output/NB2/maiz_yield_irr.tif'"),
    ("r'.\\data_output\\NB2\\maiz_ccd_rain.tif'",  "'./data_output/NB2/maiz_starting_date_rain.tif'"),
    ("r'.\\data_output\\NB2\\maiz_ccd_irr.tif'",   "'./data_output/NB2/maiz_starting_date_irr.tif'"),
    ("r'.\\data_output\\NB2\\maiz_fc1_rain.tif'",  "'./data_output/NB2/fc1_maiz_rain.tif'"),
    ("r'.\\data_output\\NB2\\maiz_fc1_irr.tif'",   "'./data_output/NB2/fc1_maiz_irr.tif'"),
    ("r'.\\data_output\\NB2\\maiz_fc2_rain.tif'",  "'./data_output/NB2/fc2_maiz_rain.tif'"),

    # ── 6. NB3: reads NB2 output / saves normalized names ──────────────────
    ("r'./data_output/NB2/maiz_yld_rain.tif'",          "'./data_output/NB2/maiz_yield_rain.tif'"),
    ("r'./data_output/NB2/maiz_yld_irr.tif'",           "'./data_output/NB2/maiz_yield_irr.tif'"),
    ("r'./data_output/NB3/clim_maiz_yld_rain.tif'",     "'./data_output/NB3/clim_maiz_yield_rain.tif'"),
    ("r'./data_output/NB3/clim_maiz_yld_irr.tif'",      "'./data_output/NB3/clim_maiz_yield_irr.tif'"),

    # ── 7. NB4: reads NB3 outputs; fix irrigated-save bug; normalize names ─
    # NB4 reads from NB3
    ("r'./data_output/NB3/clim_maiz_yld_rain.tif'",     "'./data_output/NB3/clim_maiz_yield_rain.tif'"),
    ("r'./data_output/NB3/clim_maiz_yld_irr.tif'",      "'./data_output/NB3/clim_maiz_yield_irr.tif'"),
    # BUG FIX: NB4 cell-35 saved irrigated yield under the rainfed filename.
    # Match on the variable name to distinguish the two save calls:
    ("'./data_output/NB4/soil_clim_yld_maiz_rain.tif', yield_map_rain_m4",
     "'./data_output/NB4/soil_clim_adj_yield_maiz_rain.tif', yield_map_rain_m4"),
    ("'./data_output/NB4/soil_clim_yld_maiz_rain.tif',yield_map_irr_m4",
     "'./data_output/NB4/soil_clim_adj_yield_maiz_irr.tif', yield_map_irr_m4"),
    ("'./data_output/NB4/maiz_fc4_rain.tif'", "'./data_output/NB4/fc4_maiz_rain.tif'"),
    ("'./data_output/NB4/maiz_fc4_irr.tif'",  "'./data_output/NB4/fc4_maiz_irr.tif'"),

    # ── 8. NB5: reads NB4; fix save names to match what NB6 actually reads ─
    ("'./data_output/NB4/soil_clim_yld_maiz_rain.tif'", "'./data_output/NB4/soil_clim_adj_yield_maiz_rain.tif'"),
    ("'./data_output/NB4/soil_clim_yld_maiz_irr.tif'",  "'./data_output/NB4/soil_clim_adj_yield_maiz_irr.tif'"),
    # NB5 saves — normalize to adj_yield naming that NB6 expects
    ("r'./data_output/NB5/terr_soil_clim_yld_maiz_rain.tif'",
     "'./data_output/NB5/terr_soil_clim_adj_yield_maiz_rain.tif'"),
    ("r'./data_output/NB5/terr_soil_clim_yld_maiz_irr.tif'",
     "'./data_output/NB5/terr_soil_clim_adj_yield_maiz_irr.tif'"),
    ("r'./data_output/NB5/fc5_maiz_rain.tif'", "'./data_output/NB5/fc5_maiz_rain.tif'"),
    ("r'./data_output/NB5/fc5_maiz_irr.tif'",  "'./data_output/NB5/fc5_maiz_irr.tif'"),
]

# Substitutions for NB6 only — update Thai Baht economics to Pakistan Rupee
NB6_SUBS = [
    (
        "cost_maize = np.array([30100, 30000,27000,25500])",
        "cost_maize = np.array([85000, 80000, 72000, 65000])  # PKR/ha — update with current values"
    ),
    (
        "farm_price_maize = np.arange(6.5,9.5,0.5)*1000 #THB/ton",
        "farm_price_maize = np.arange(40000, 65000, 5000)  # PKR/ton — update with current values"
    ),
]


def apply_subs(src: str, subs: list) -> str:
    for old, new in subs:
        src = src.replace(old, new)
    return src


def transform_notebook(path: Path) -> tuple:
    with open(path, encoding="utf-8") as f:
        nb = json.load(f)

    is_nb6 = "NB6" in path.name
    cells_changed = 0

    for cell in nb.get("cells", []):
        if cell.get("cell_type") != "code":
            continue
        original = "".join(cell.get("source", []))
        updated = apply_subs(original, COMMON_SUBS)
        if is_nb6:
            updated = apply_subs(updated, NB6_SUBS)
        if updated != original:
            # splitlines(keepends=True) preserves \n at end of each line
            cell["source"] = updated.splitlines(keepends=True)
            cells_changed += 1

    return nb, cells_changed


def main():
    print("Updating PyAEZ notebooks for Pakistan")
    print("=" * 50)
    for name in NOTEBOOKS:
        path = TUTORIALS / name
        if not path.exists():
            print(f"  SKIP    {name}  (file not found)")
            continue
        nb, n = transform_notebook(path)
        with open(path, "w", encoding="utf-8") as f:
            json.dump(nb, f, indent=1, ensure_ascii=False)
        print(f"  OK      {name}  ({n} code cells updated)")
    print("=" * 50)
    print("Done.\n")
    print("Key changes applied to all notebooks:")
    print("  - Work dir: '.' (repo root, cross-platform)")
    print("  - lat_min/lat_max: 23.0 / 37.5 (Pakistan)")
    print("  - All input paths: ./data_input/... (forward slash)")
    print("  - All LAO_ / Lao_ filenames → PK_")
    print("  - NB2: output names normalized to match existing data_output files")
    print("  - NB4: irrigated-save filename bug fixed")
    print("  - NB5: save names aligned with what NB6 reads")
    print("  - NB6: cost/price updated from Thai Baht to PKR placeholders")


if __name__ == "__main__":
    main()
