"""Shared helpers for GCS drone-show management routes."""

import csv
import json
import math
import os
import shutil
import tempfile
import time
import zipfile
from datetime import datetime
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

from fastapi import HTTPException


CUSTOM_SHOW_REQUIRED_COLUMNS = (
    "t", "px", "py", "pz",
    "vx", "vy", "vz",
    "ax", "ay", "az",
    "yaw", "mode",
)


def copy_directory_contents(src_dir: str, dst_dir: str) -> None:
    os.makedirs(dst_dir, exist_ok=True)
    for entry in os.listdir(src_dir):
        src_path = os.path.join(src_dir, entry)
        dst_path = os.path.join(dst_dir, entry)
        if os.path.isdir(src_path):
            shutil.copytree(src_path, dst_path, dirs_exist_ok=True)
        else:
            shutil.copy2(src_path, dst_path)


def swarm_directory(shapes_dir: str) -> str:
    return os.path.join(shapes_dir, "swarm")


def saved_metrics_path(shapes_dir: str) -> str:
    return os.path.join(swarm_directory(shapes_dir), "comprehensive_metrics.json")


def count_processed_drone_files(directory: str) -> int:
    if not os.path.exists(directory):
        return 0

    return len(
        [
            filename for filename in os.listdir(directory)
            if filename.startswith("Drone ") and filename.endswith(".csv")
        ]
    )


def custom_show_csv_path(shapes_dir: str) -> str:
    return os.path.join(shapes_dir, "active.csv")


def custom_show_preview_path(shapes_dir: str) -> str:
    return os.path.join(shapes_dir, "trajectory_plot.png")


def inspect_custom_show_csv(csv_path: str) -> Dict[str, Any]:
    with open(csv_path, "r", encoding="utf-8-sig", newline="") as csv_file:
        reader = csv.DictReader(csv_file)
        fieldnames = reader.fieldnames or []
        missing_columns = [column for column in CUSTOM_SHOW_REQUIRED_COLUMNS if column not in fieldnames]
        if missing_columns:
            raise HTTPException(
                status_code=400,
                detail=(
                    "Custom CSV is missing required protocol columns: "
                    f"{', '.join(missing_columns)}"
                ),
            )

        row_count = 0
        duration_sec = 0.0
        max_altitude = 0.0
        previous_t = None
        points: List[Dict[str, float]] = []

        for line_no, row in enumerate(reader, start=2):
            if not any((value or "").strip() for value in row.values()):
                continue

            try:
                t_val = float(row["t"])
                px_val = float(row["px"])
                py_val = float(row["py"])
                pz_val = float(row["pz"])
                vx_val = float(row["vx"])
                vy_val = float(row["vy"])
                vz_val = float(row["vz"])
                ax_val = float(row["ax"])
                ay_val = float(row["ay"])
                az_val = float(row["az"])
                yaw_val = float(row["yaw"])
                mode_val = int(row["mode"])
            except (TypeError, ValueError) as exc:
                raise HTTPException(
                    status_code=400,
                    detail=f"Invalid custom CSV row {line_no}: {exc}",
                ) from exc

            trajectory_values = (
                t_val,
                px_val,
                py_val,
                pz_val,
                vx_val,
                vy_val,
                vz_val,
                ax_val,
                ay_val,
                az_val,
                yaw_val,
            )
            if not all(math.isfinite(value) for value in trajectory_values):
                raise HTTPException(
                    status_code=400,
                    detail=(
                        f"Invalid custom CSV row {line_no}: "
                        "trajectory samples must be finite numbers"
                    ),
                )

            if t_val < 0:
                raise HTTPException(status_code=400, detail=f"Invalid custom CSV row {line_no}: time must be non-negative")

            if previous_t is not None and t_val < previous_t:
                raise HTTPException(
                    status_code=400,
                    detail=f"Invalid custom CSV row {line_no}: time values must be non-decreasing",
                )

            previous_t = t_val
            row_count += 1
            duration_sec = max(duration_sec, t_val)
            max_altitude = max(max_altitude, -pz_val)
            points.append({
                "t": t_val,
                "px": px_val,
                "py": py_val,
                "pz": pz_val,
                "vx": vx_val,
                "vy": vy_val,
                "vz": vz_val,
                "ax": ax_val,
                "ay": ay_val,
                "az": az_val,
                "yaw": yaw_val,
                "mode": mode_val,
            })

        if row_count == 0:
            raise HTTPException(status_code=400, detail="Custom CSV contains no executable trajectory rows")

        return {
            "row_count": row_count,
            "duration_sec": round(duration_sec, 2),
            "max_altitude": round(max_altitude, 2),
            "points": points,
        }


def generate_custom_show_preview(points: List[Dict[str, float]], preview_path: str) -> None:
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    times = [point["t"] for point in points]
    north_values = [point["px"] for point in points]
    east_values = [point["py"] for point in points]
    altitude_values = [-point["pz"] for point in points]

    fig, (path_ax, altitude_ax) = plt.subplots(1, 2, figsize=(13, 5.5), constrained_layout=True)

    path_ax.plot(east_values, north_values, color="#2563eb", linewidth=2.4)
    path_ax.scatter(east_values[0], north_values[0], color="#16a34a", s=60, label="Start", zorder=3)
    path_ax.scatter(east_values[-1], north_values[-1], color="#dc2626", s=60, label="End", zorder=3)
    path_ax.set_title("Launch-Frame XY Path")
    path_ax.set_xlabel("East (m)")
    path_ax.set_ylabel("North (m)")
    path_ax.grid(alpha=0.25)
    path_ax.legend(loc="best")
    path_ax.set_aspect("equal", adjustable="datalim")

    altitude_ax.plot(times, altitude_values, color="#7c3aed", linewidth=2.2)
    altitude_ax.fill_between(times, altitude_values, color="#c4b5fd", alpha=0.25)
    altitude_ax.set_title("Altitude Profile")
    altitude_ax.set_xlabel("Time (s)")
    altitude_ax.set_ylabel("Altitude above launch (m)")
    altitude_ax.grid(alpha=0.25)

    fig.suptitle("Custom CSV Preview", fontsize=14, fontweight="bold")
    fig.savefig(preview_path, dpi=150, bbox_inches="tight")
    plt.close(fig)


def load_saved_metrics_if_current(
    *,
    shapes_dir: str,
    processed_dir: str,
    log_warning: Callable[[str, str], None],
) -> Optional[Dict[str, Any]]:
    metrics_file = saved_metrics_path(shapes_dir)
    if not os.path.exists(metrics_file):
        return None

    try:
        with open(metrics_file, "r", encoding="utf-8") as file_obj:
            metrics_data = json.load(file_obj)
    except Exception as exc:
        log_warning(f"Failed to read saved show metrics, recalculating: {exc}", "show")
        return None

    cached_count = metrics_data.get("basic_metrics", {}).get("drone_count")
    current_count = count_processed_drone_files(processed_dir)
    try:
        cached_count = int(cached_count)
    except (TypeError, ValueError):
        cached_count = None

    if cached_count != current_count:
        log_warning(
            f"Saved show metrics are stale (cached drones={cached_count}, current drones={current_count}); recalculating.",
            "show",
        )
        return None

    return metrics_data


def refresh_saved_show_metrics(
    *,
    processed_dir: str,
    metrics_available: bool,
    metrics_engine_cls: Any,
    show_filename: Optional[str] = None,
) -> Optional[Dict[str, Any]]:
    if not metrics_available:
        return None

    metrics_engine = metrics_engine_cls(processed_dir)
    comprehensive_metrics = metrics_engine.calculate_comprehensive_metrics()
    metrics_engine.save_metrics_to_file(
        comprehensive_metrics,
        show_filename=show_filename,
        upload_datetime=datetime.now().isoformat(),
    )
    return comprehensive_metrics


def import_show_archive(
    *,
    base_dir: str,
    filename: str,
    content: bytes,
    allowed_file_func: Callable[[str], bool],
    run_formation_process_func: Callable[..., Dict[str, Any]],
    clear_show_directories_func: Callable[[str], None],
    git_operations_func: Callable[[str, str], Dict[str, Any]],
    git_auto_push: bool,
    skybrush_dir: str,
    processed_dir: str,
    plots_directory: str,
    metrics_available: bool,
    refresh_saved_show_metrics_func: Callable[..., Optional[Dict[str, Any]]],
    log_event: Callable[[str, str, str], None],
    log_warning: Callable[[str, str], None],
) -> Dict[str, Any]:
    log_event(f"📤 Show import requested: {filename}", "INFO", "show")

    if not filename:
        raise HTTPException(status_code=400, detail="No file part or empty filename")
    if not allowed_file_func(filename):
        raise HTTPException(status_code=400, detail="Only ZIP archives are supported")

    warnings: List[str] = []
    git_result: Optional[Dict[str, Any]] = None

    temp_root = os.path.join(base_dir, "temp")
    os.makedirs(temp_root, exist_ok=True)

    with tempfile.TemporaryDirectory(prefix="show-import-", dir=temp_root) as staging_root:
        zip_path = os.path.join(staging_root, "uploaded.zip")
        extract_dir = os.path.join(staging_root, "extracted")
        staging_skybrush_dir = os.path.join(staging_root, "skybrush")
        staging_processed_dir = os.path.join(staging_root, "processed")
        staging_plots_dir = os.path.join(staging_root, "plots")

        os.makedirs(extract_dir, exist_ok=True)
        os.makedirs(staging_skybrush_dir, exist_ok=True)
        os.makedirs(staging_processed_dir, exist_ok=True)
        os.makedirs(staging_plots_dir, exist_ok=True)

        with open(zip_path, "wb") as file_obj:
            file_obj.write(content)

        if not zipfile.is_zipfile(zip_path):
            raise HTTPException(status_code=400, detail="Uploaded file is not a valid ZIP archive")

        with zipfile.ZipFile(zip_path, "r") as zip_ref:
            zip_ref.extractall(extract_dir)

        extracted_csvs = sorted(path for path in Path(extract_dir).rglob("*.csv") if path.is_file())
        if not extracted_csvs:
            raise HTTPException(status_code=400, detail="ZIP archive does not contain any SkyBrush CSV files")

        basename_map: Dict[str, List[Path]] = {}
        for csv_path in extracted_csvs:
            basename_map.setdefault(csv_path.name, []).append(csv_path)

        duplicate_names = sorted(name for name, paths in basename_map.items() if len(paths) > 1)
        if duplicate_names:
            raise HTTPException(
                status_code=400,
                detail=(
                    "ZIP archive contains duplicate CSV filenames. "
                    f"Each drone CSV must be uniquely named. Duplicates: {duplicate_names}"
                ),
            )

        nested_csv_count = sum(1 for csv_path in extracted_csvs if csv_path.parent != Path(extract_dir))
        if nested_csv_count:
            warnings.append(
                f"Detected {nested_csv_count} CSV file(s) in nested archive folders; "
                "they were flattened during import."
            )

        for csv_path in extracted_csvs:
            shutil.copy2(csv_path, os.path.join(staging_skybrush_dir, csv_path.name))

        log_event(f"⚙️ Processing show files from staged import ({len(extracted_csvs)} CSVs)", "INFO", "show")
        process_result = run_formation_process_func(
            base_dir,
            skybrush_dir=staging_skybrush_dir,
            processed_dir=staging_processed_dir,
            plots_dir=staging_plots_dir,
        )
        if not process_result.get("success"):
            raise HTTPException(status_code=400, detail=process_result.get("message", "Show processing failed"))

        clear_show_directories_func(base_dir)
        copy_directory_contents(staging_skybrush_dir, skybrush_dir)
        copy_directory_contents(staging_processed_dir, processed_dir)
        copy_directory_contents(staging_plots_dir, plots_directory)

        processed_count = count_processed_drone_files(processed_dir)
        plots_generated = len([file for file in os.listdir(plots_directory) if file.endswith(".jpg")])

        if metrics_available:
            try:
                refresh_saved_show_metrics_func(show_filename=filename)
            except Exception as metrics_error:
                warnings.append(f"Metrics refresh failed: {metrics_error}")
                log_warning(f"Failed to refresh show metrics after import: {metrics_error}", "show")

        log_event(f"✅ Show processing completed: {processed_count} drones", "INFO", "show")

        if git_auto_push:
            git_result = git_operations_func(base_dir, f"show: import {filename} ({processed_count} drones)")
            if not git_result.get("success"):
                warnings.append(f"Git auto-push failed: {git_result.get('message', 'unknown error')}")

    return {
        "success": True,
        "message": "Show imported and processed successfully",
        "show_name": filename,
        "files_processed": processed_count,
        "drones_configured": processed_count,
        "raw_files_found": len(extracted_csvs),
        "plots_generated": plots_generated,
        "warnings": warnings,
        "next_steps": [
            "Review launch positions and origin in Mission Config.",
            "Confirm telemetry and readiness in Overview before launch.",
        ],
        "git_info": git_result,
    }


def build_show_info_payload(skybrush_dir: str) -> Dict[str, Any]:
    drone_csv_files = [
        filename
        for filename in os.listdir(skybrush_dir)
        if filename.startswith("Drone ") and filename.endswith(".csv")
    ]

    if not drone_csv_files:
        raise HTTPException(status_code=404, detail="No drone CSV files found")

    drone_count = len(drone_csv_files)
    max_duration_ms = 0.0
    max_altitude = 0.0

    for csv_file in drone_csv_files:
        csv_path = os.path.join(skybrush_dir, csv_file)

        with open(csv_path, "r", encoding="utf-8") as file_obj:
            next(file_obj)
            lines = file_obj.readlines()
            if not lines:
                continue

            last_line = lines[-1].strip().split(",")
            try:
                duration_ms = float(last_line[0])
            except (TypeError, ValueError):
                duration_ms = float("nan")
            if math.isfinite(duration_ms) and duration_ms > max_duration_ms:
                max_duration_ms = duration_ms

            for line in lines:
                parts = line.strip().split(",")
                if len(parts) < 4:
                    continue
                try:
                    z_val = float(parts[3])
                except (TypeError, ValueError):
                    continue
                if math.isfinite(z_val) and z_val > max_altitude:
                    max_altitude = z_val

    duration_minutes = max_duration_ms / 60000
    duration_seconds = (max_duration_ms % 60000) / 1000

    return {
        "drone_count": drone_count,
        "duration_ms": max_duration_ms,
        "duration_minutes": round(duration_minutes, 2),
        "duration_seconds": round(duration_seconds, 2),
        "max_altitude": round(max_altitude, 2),
    }


def build_custom_show_info_payload(shapes_dir: str) -> Dict[str, Any]:
    csv_path = custom_show_csv_path(shapes_dir)
    preview_path = custom_show_preview_path(shapes_dir)

    if not os.path.exists(csv_path):
        raise HTTPException(status_code=404, detail="Custom CSV not found")

    inspected = inspect_custom_show_csv(csv_path)
    return {
        "exists": True,
        "filename": "active.csv",
        "row_count": inspected["row_count"],
        "duration_sec": inspected["duration_sec"],
        "max_altitude": inspected["max_altitude"],
        "preview_exists": os.path.exists(preview_path),
        "execution_mode": "local per-drone replay",
        "required_columns": list(CUSTOM_SHOW_REQUIRED_COLUMNS),
    }


def import_custom_show_csv(
    *,
    base_dir: str,
    shapes_dir: str,
    filename: str,
    content: bytes,
    git_auto_push: bool,
    inspect_custom_show_csv_func: Callable[[str], Dict[str, Any]],
    generate_custom_show_preview_func: Callable[[List[Dict[str, float]], str], None],
    git_operations_func: Callable[[str, str], Dict[str, Any]],
) -> Dict[str, Any]:
    if not filename:
        raise HTTPException(status_code=400, detail="No file part or empty filename")
    if not filename.lower().endswith(".csv"):
        raise HTTPException(status_code=400, detail="Only CSV files are supported for Custom CSV mode")

    warnings: List[str] = []
    git_result: Optional[Dict[str, Any]] = None
    temp_root = os.path.join(base_dir, "temp")
    os.makedirs(temp_root, exist_ok=True)
    os.makedirs(shapes_dir, exist_ok=True)

    with tempfile.TemporaryDirectory(prefix="custom-show-import-", dir=temp_root) as staging_root:
        staged_csv_path = os.path.join(staging_root, "active.csv")
        staged_preview_path = os.path.join(staging_root, "trajectory_plot.png")

        with open(staged_csv_path, "wb") as staged_csv:
            staged_csv.write(content)

        inspected = inspect_custom_show_csv_func(staged_csv_path)
        generate_custom_show_preview_func(inspected["points"], staged_preview_path)

        active_csv_path = custom_show_csv_path(shapes_dir)
        preview_path = custom_show_preview_path(shapes_dir)
        if os.path.exists(active_csv_path):
            warnings.append("Existing active custom CSV was replaced.")

        shutil.copy2(staged_csv_path, active_csv_path)
        shutil.copy2(staged_preview_path, preview_path)

        if git_auto_push:
            git_result = git_operations_func(
                base_dir,
                f"custom-show: import {filename} ({inspected['row_count']} samples)",
            )
            if not git_result.get("success"):
                warnings.append(f"Git auto-push failed: {git_result.get('message', 'unknown error')}")

    return {
        "success": True,
        "message": "Custom CSV validated and activated successfully",
        "filename": filename,
        "stored_as": "active.csv",
        "row_count": inspected["row_count"],
        "duration_sec": inspected["duration_sec"],
        "max_altitude": inspected["max_altitude"],
        "preview_generated": True,
        "warnings": warnings,
        "next_steps": [
            "Review the generated preview and confirm the path is correct.",
            "Remember: every drone will execute the same CSV in its own local launch frame.",
            "Use Mission Config and Overview to confirm spacing and readiness before launch.",
        ],
        "git_info": git_result,
    }


def build_comprehensive_metrics_payload(
    *,
    metrics_available: bool,
    load_saved_metrics_if_current_func: Callable[[], Optional[Dict[str, Any]]],
    refresh_saved_show_metrics_func: Callable[[], Optional[Dict[str, Any]]],
) -> Dict[str, Any]:
    if not metrics_available:
        raise HTTPException(status_code=503, detail="Enhanced metrics engine not available")

    metrics_data = load_saved_metrics_if_current_func()
    if metrics_data is not None:
        return metrics_data

    return refresh_saved_show_metrics_func()


def build_metrics_snapshot_payload(
    *,
    metrics_available: bool,
    load_saved_metrics_if_current_func: Callable[[], Optional[Dict[str, Any]]],
) -> Dict[str, Any]:
    """Read the current metrics cache without recalculating or writing files."""

    if not metrics_available:
        raise HTTPException(status_code=503, detail="Enhanced metrics engine not available")

    metrics_data = load_saved_metrics_if_current_func()
    if metrics_data is None:
        return {
            "available": False,
            "snapshot_only": True,
            "cache_current": False,
            "detail": (
                "No current cached SkyBrush metrics snapshot is available. "
                "Use the reviewed metrics refresh/import workflow before relying on metrics through MCP."
            ),
        }

    return {
        "available": True,
        "snapshot_only": True,
        "cache_current": True,
        "metrics": metrics_data,
    }


def build_safety_report_payload(
    *,
    metrics_available: bool,
    metrics_engine_cls: Any,
    processed_dir: str,
) -> Dict[str, Any]:
    if not metrics_available:
        raise HTTPException(status_code=503, detail="Enhanced metrics engine not available")

    metrics_engine = metrics_engine_cls(processed_dir)
    if not metrics_engine.load_drone_data():
        raise HTTPException(status_code=404, detail="No drone data available for safety analysis")

    safety_metrics = metrics_engine.calculate_safety_metrics()
    recommendations = (
        [
            "Maintain minimum 2m separation between drones",
            "Ensure ground clearance > 1m at all times",
            "Monitor collision warnings during flight",
        ]
        if safety_metrics.get("collision_warnings_count", 0) > 0
        else [
            "Safety analysis complete - no issues detected",
            "Formation maintains safe separation distances",
        ]
    )

    return {
        "safety_analysis": safety_metrics,
        "recommendations": recommendations,
    }


def build_trajectory_validation_payload(
    *,
    metrics_available: bool,
    metrics_engine_cls: Any,
    processed_dir: str,
) -> Dict[str, Any]:
    if not metrics_available:
        raise HTTPException(status_code=503, detail="Enhanced metrics engine not available")

    metrics_engine = metrics_engine_cls(processed_dir)
    if not metrics_engine.load_drone_data():
        raise HTTPException(status_code=404, detail="No drone data available for validation")

    all_metrics = metrics_engine.calculate_comprehensive_metrics()
    validation_status = "PASS"
    issues: List[str] = []

    if "safety_metrics" in all_metrics:
        safety = all_metrics["safety_metrics"]
        if safety.get("safety_status") != "SAFE":
            validation_status = "FAIL"
            issues.append(f"Safety issue: {safety.get('safety_status')}")

        if safety.get("collision_warnings_count", 0) > 0:
            if validation_status != "FAIL":
                validation_status = "WARNING"
            issues.append(f"{safety['collision_warnings_count']} collision warnings")

    if "performance_metrics" in all_metrics:
        perf = all_metrics["performance_metrics"]
        if perf.get("max_velocity_ms", 0) > 15:
            if validation_status == "PASS":
                validation_status = "WARNING"
            issues.append(f"High velocity: {perf['max_velocity_ms']} m/s")

    return {
        "validation_status": validation_status,
        "issues": issues,
        "metrics_summary": {
            "safety_status": all_metrics.get("safety_metrics", {}).get("safety_status", "Unknown"),
            "max_velocity": all_metrics.get("performance_metrics", {}).get("max_velocity_ms", 0),
            "formation_quality": all_metrics.get("formation_metrics", {}).get("formation_quality", "Unknown"),
        },
    }


def resolve_show_plot_path(plots_directory: str, filename: str) -> Path:
    plots_root = Path(plots_directory).resolve()
    candidate = (plots_root / filename).resolve()

    try:
        candidate.relative_to(plots_root)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail="Plot image not found") from exc

    return candidate


def list_show_plots_payload(plots_directory: str) -> Dict[str, Any]:
    if not os.path.exists(plots_directory):
        return {"filenames": [], "uploadTime": "unknown"}

    filenames = sorted(filename for filename in os.listdir(plots_directory) if filename.endswith(".jpg"))
    upload_time = "unknown"

    combined_path = os.path.join(plots_directory, "combined_drone_paths.jpg")
    if os.path.exists(combined_path):
        upload_time = time.ctime(os.path.getctime(combined_path))

    return {"filenames": filenames, "uploadTime": upload_time}


def resolve_custom_show_image_path(shapes_dir: str) -> str:
    image_path = custom_show_preview_path(shapes_dir)
    if not os.path.exists(image_path):
        raise HTTPException(status_code=404, detail=f"Custom show image not found at {image_path}")
    return image_path
