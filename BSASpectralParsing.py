
# Original Code generated with Claude and edited by Sean Meehan 2026

import os
import glob
from datetime import datetime, timedelta

import pymzml
import numpy as np
import matplotlib.pyplot as plt
from openpyxl import Workbook, load_workbook

# =====================================================================
# Settings
# =====================================================================

mzml_dir = r"[Insert Path]"
output_dir = mzml_dir  # change this if you want plots/log saved elsewhere
excel_log_path = os.path.join(output_dir, "BSA_QC_Log.xlsx")

target_mz_list = [464.2507, 547.3177, 700.3501]
days_back = 7  # only process files created within this many days


# =====================================================================
# Extracted Ion Chromatogram (EIC) for a specific m/z
# =====================================================================

def extract_eic(mzml_path, target_mz, tolerance=0.01, ms_level=1):
    """
    Pull out retention time and intensity for a target m/z across all
    scans of a given MS level (an Extracted Ion Chromatogram).

    Parameters
    ----------
    mzml_path : str
        Path to the mzML file. A fresh reader is opened here, since a
        pymzml Reader can only be iterated once.
    target_mz : float
        The m/z value you want to track (e.g. 700).
    tolerance : float
        +/- window (in Da) used to match target_mz against each scan's
        peak list. Widen this if you're not finding matches; narrow it
        if you're picking up neighboring peaks.
    ms_level : int
        Which MS level to search (1 for MS1/precursor scans, 2 for
        fragment scans).

    Returns
    -------
    rt_eic : np.ndarray
        Retention time (min) for every scan at that MS level.
    intensity_eic : np.ndarray
        Intensity of the closest peak within tolerance at each scan.
        Scans with no matching peak get an intensity of 0.
    """
    reader = pymzml.run.Reader(mzml_path)
    rt_eic = []
    intensity_eic = []

    for spectrum in reader:
        if spectrum.ms_level != ms_level:
            continue

        mz_array = spectrum.mz
        i_array = spectrum.i
        rt_eic.append(spectrum.scan_time_in_minutes())

        if len(mz_array) == 0:
            intensity_eic.append(0)
            continue

        idx = np.argmin(np.abs(mz_array - target_mz))
        if abs(mz_array[idx] - target_mz) <= tolerance:
            intensity_eic.append(i_array[idx])
        else:
            intensity_eic.append(0)

    return np.array(rt_eic), np.array(intensity_eic)


def get_peak_apex(mzml_path, target_mz, tolerance=0.01, ms_level=1):
    """
    Runs extract_eic() for target_mz and returns the apex retention
    time and intensity, without generating a plot.
    """
    rt_eic, intensity_eic = extract_eic(mzml_path, target_mz, tolerance, ms_level)

    apex_rt = rt_eic[intensity_eic.argmax()]
    apex_intensity = intensity_eic.max()
    print(f"  m/z {target_mz}: apex RT = {apex_rt:.2f} min, apex intensity = {apex_intensity:.2e}")

    return apex_rt, apex_intensity


# =====================================================================
# Log QC metrics to an Excel spreadsheet (one row per file)
# =====================================================================

def get_run_date_from_filename(mzml_path):
    """
    Parse the first 6 characters of the file name as an MMDDYY date and
    return it formatted as YYYY-MM-DD.

    e.g. "072326_IQX_BSA.mzML" -> "2026-07-23"

    Falls back to today's date (with a warning printed) if the first 6
    characters aren't a valid MMDDYY date.
    """
    file_tag = os.path.splitext(os.path.basename(mzml_path))[0]
    date_prefix = file_tag[:6]

    try:
        run_date = datetime.strptime(date_prefix, "%m%d%y")
        return run_date.strftime("%Y-%m-%d")
    except ValueError:
        print(
            f"  Warning: could not parse a date from the first 6 characters "
            f"of '{file_tag}' (got '{date_prefix}'). Falling back to today's date."
        )
        return datetime.now().strftime("%Y-%m-%d")


def log_qc_to_excel(excel_path, mzml_path, qc, bpc_max, peak_results):
    """
    Append one row of QC metrics to an Excel log file, creating the
    file with headers the first time it's run.

    Parameters
    ----------
    excel_path : str
        Path to the .xlsx log file. Created if it doesn't already exist.
    mzml_path : str
        Path to the source mzML file (used to log date + file name).
    qc : dict
        The qc dict from the TIC analysis (needs at least "TIC_max").
    bpc_max : float
        Max base peak intensity, e.g. bpc.max().
    peak_results : dict
        Maps target m/z -> (apex_rt, apex_intensity), e.g.
        {464: (12.3, 5.1e6), 547: (14.1, 3.2e6), 700: (15.6, 8.9e6)}
    """
    target_mzs = sorted(peak_results.keys())

    headers = ["Date", "File Name", "Max TIC", "Max BPC"]
    for mz in target_mzs:
        headers += [f"RT @ m/z {mz}", f"Intensity @ m/z {mz}"]

    if os.path.exists(excel_path):
        wb = load_workbook(excel_path)
        ws = wb.active
    else:
        wb = Workbook()
        ws = wb.active
        ws.title = "QC Log"
        ws.append(headers)

    row = [
        get_run_date_from_filename(mzml_path),
        os.path.basename(mzml_path),
        qc["TIC_max"],
        bpc_max,
    ]
    for mz in target_mzs:
        apex_rt, apex_intensity = peak_results[mz]
        row += [apex_rt, apex_intensity]

    ws.append(row)

    # Display Max TIC, Max BPC, and all intensity columns in scientific
    # notation, while keeping them as real numbers underneath.
    last_row = ws.max_row
    sci_notation_cols = [3, 4]  # Max TIC, Max BPC
    for i in range(len(target_mzs)):
        intensity_col = 6 + (2 * i)  # 6, 8, 10, ... for each successive m/z
        sci_notation_cols.append(intensity_col)

    for col in sci_notation_cols:
        ws.cell(row=last_row, column=col).number_format = "0.00E+00"

    wb.save(excel_path)
    print(f"  Logged QC row for {os.path.basename(mzml_path)} to {excel_path}")


# =====================================================================
# Full per-file QC analysis: TIC / BPC / MS2 plots + EIC + Excel log
# =====================================================================

def process_mzml_file(mzml_path, output_dir, excel_log_path, target_mz_list):
    """
    Runs the complete QC pipeline (TIC, BPC, MS2 tracing, EIC extraction
    for each m/z in target_mz_list, and Excel logging) for a single
    mzML file.
    """
    file_tag = os.path.splitext(os.path.basename(mzml_path))[0]
    print(f"Processing {file_tag} ...")

    run = pymzml.run.Reader(mzml_path)

    rt, rt2, tic, tic2, bpc = [], [], [], [], []

    for spectrum in run:
        if spectrum.ms_level == 1:
            rt.append(spectrum.scan_time_in_minutes())
            tic.append(np.sum(spectrum.i))
            bpc.append(np.max(spectrum.i))
        elif spectrum.ms_level == 2:
            rt2.append(spectrum.scan_time_in_minutes())
            tic2.append(np.max(spectrum.i))

    rt = np.array(rt)
    tic = np.array(tic)
    rt2 = np.array(rt2)
    tic2 = np.array(tic2)
    bpc = np.array(bpc)

    qc = {}

    # Total ion current area (simple trapezoidal integration)
    qc["TIC_area"] = np.trapezoid(tic, rt)

    # Peak TIC
    qc["TIC_max"] = tic.max()
    qc["RT_at_TIC_max"] = rt[tic.argmax()]

    # Scan count
    qc["n_scans"] = len(tic)

    # Baseline proxy
    qc["TIC_median"] = np.median(tic)

    # Early vs late TIC ratio (first vs last 20%)
    n = len(tic)
    early = tic[: n // 5].sum()
    late = tic[-n // 5:].sum()
    qc["early_late_ratio"] = early / late if late > 0 else np.nan

    # ---- TIC plot ----
    plt.figure(figsize=(10, 4))
    plt.plot(rt, tic, color="black", linewidth=1)
    plt.axvline(
        qc["RT_at_TIC_max"],
        linestyle="--",
        color="red",
        alpha=0.7,
        label="Max TIC"
    )
    plt.xlabel("Retention time (min)")
    plt.ylabel("TIC (1e9)")
    plt.title(f"{file_tag} TIC Tracing with QC metrics")

    qc_text = (
        f"TIC area: {qc['TIC_area']:.2e}\n"
        f"Max TIC: {qc['TIC_max']:.2e}\n"
        f"RT @ max: {qc['RT_at_TIC_max']:.2f} min\n"
        f"Scans: {qc['n_scans']}\n"
        f"Early/Late TIC: {qc['early_late_ratio']:.2f}"
    )
    plt.text(
        0.85, 0.80, qc_text,
        transform=plt.gca().transAxes,
        verticalalignment="top",
        bbox=dict(boxstyle="round", facecolor="white", alpha=0.85),
        fontsize=9
    )
    plt.legend(loc="upper right")
    plt.tight_layout()
    plt.savefig(os.path.join(output_dir, f"{file_tag}_TIC_QC.png"), dpi=300)
    plt.close()

    # ---- BPC plot ----
    plt.figure(figsize=(10, 4))
    plt.plot(rt, bpc, label="BPC", color="red", linewidth=1, alpha=0.8)
    plt.xlabel("Retention time (min)")
    plt.ylabel("TIC")
    plt.title(f"{file_tag} Base Peak Tracing")
    plt.legend()
    plt.tight_layout()
    plt.savefig(os.path.join(output_dir, f"{file_tag}_BPC_QC.png"), dpi=300)
    plt.close()

    # ---- MS2 plot ----
    plt.figure(figsize=(10, 4))
    plt.plot(rt2, tic2, label="MS2", color="blue", linewidth=1, alpha=0.8)
    plt.xlabel("Retention time (min)")
    plt.ylabel("TIC")
    plt.title(f"{file_tag} MS2 Tracing")

    qc_ms2 = {}
    qc_ms2["TIC2_max"] = tic2.max()
    qc_ms2["RT2_at_TIC2_max"] = rt2[tic2.argmax()]
    qc_ms2["n_ms2_scans"] = len(tic2)
    qc_ms2["TIC2_median"] = np.median(tic2)

    qc_ms2_text = (
        f"Max TIC: {qc_ms2['TIC2_max']:.2e}\n"
        f"RT @ max: {qc_ms2['RT2_at_TIC2_max']:.2f} min\n"
        f"Scans: {qc_ms2['n_ms2_scans']}\n"
    )
    plt.text(
        0.85, 0.80, qc_ms2_text,
        transform=plt.gca().transAxes,
        verticalalignment="top",
        bbox=dict(boxstyle="round", facecolor="white", alpha=0.85),
        fontsize=9
    )
    plt.legend()
    plt.tight_layout()
    plt.savefig(os.path.join(output_dir, f"{file_tag}_MS2_QC.png"), dpi=300)
    plt.close()

    # ---- EIC extraction for peaks of interest (apex only, no plots) ----
    peak_results = {}
    for mz in target_mz_list:
        apex_rt_mz, apex_intensity_mz = get_peak_apex(
            mzml_path, target_mz=mz, tolerance=0.01, ms_level=1
        )
        peak_results[mz] = (apex_rt_mz, apex_intensity_mz)

    # ---- Log to Excel ----
    log_qc_to_excel(excel_log_path, mzml_path, qc, bpc.max(), peak_results)


# =====================================================================
# Find files created within the last N days and process each one
# =====================================================================

def get_recent_mzml_files(mzml_dir, days_back=7):
    """
    Return the paths of .mzML files in mzml_dir that were created
    within the last `days_back` days.

    Note: os.path.getctime() returns the file *creation* time on
    Windows. On macOS/Linux it reflects the last metadata change
    instead, so this function is written for Windows use.
    """
    cutoff = datetime.now() - timedelta(days=days_back)
    all_files = glob.glob(os.path.join(mzml_dir, "*.mzML"))

    recent_files = []
    for f in all_files:
        created = datetime.fromtimestamp(os.path.getctime(f))
        if created >= cutoff:
            recent_files.append(f)

    return recent_files


# =====================================================================
# Decide which files to process: prefer an explicit to_parse.txt list
# (written by raw_to_mzml.py after each conversion run) over the old
# days_back scan, so we only touch files that actually need parsing.
# =====================================================================

# Must match TO_PARSE_LIST in raw_to_mzml.py (one folder above mzml_dir)
to_parse_list_path = os.path.join(os.path.dirname(mzml_dir), "to_parse.txt")


def get_files_from_list(list_path, mzml_dir):
    """Read filenames from to_parse.txt and resolve them against mzml_dir."""
    with open(list_path, "r") as f:
        names = [line.strip() for line in f if line.strip()]
    return [os.path.join(mzml_dir, name) for name in names]


if os.path.exists(to_parse_list_path):
    recent_files = get_files_from_list(to_parse_list_path, mzml_dir)
    print(f"Found {len(recent_files)} file(s) listed in {to_parse_list_path}.")
else:
    recent_files = get_recent_mzml_files(mzml_dir, days_back=days_back)
    print(
        f"No to_parse.txt found at {to_parse_list_path}; falling back to "
        f"files created in the last {days_back} days."
    )
    print(f"Found {len(recent_files)} file(s) created in the last {days_back} days.")

for mzml_file in recent_files:
    if not os.path.exists(mzml_file):
        print(f"  Skipping missing file: {mzml_file}")
        continue
    process_mzml_file(mzml_file, output_dir, excel_log_path, target_mz_list)
