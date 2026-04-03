"""Static asset routes for generated operator-visible artifacts."""

from pathlib import Path
from typing import Any

from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse


def _resolve_static_plot_path(plots_dir: str, filename: str) -> Path:
    plots_root = Path(plots_dir).resolve()
    candidate = (plots_root / filename).resolve()

    try:
        candidate.relative_to(plots_root)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail="Plot not found") from exc

    return candidate


def create_static_assets_router(deps: Any) -> APIRouter:
    router = APIRouter()

    @router.get("/api/v1/swarm-trajectories/plots/{filename}", tags=["Static Files"])
    @router.get("/static/plots/{filename}", tags=["Static Files"])
    async def serve_plot(filename: str):
        """Serve generated plot images used by the dashboard."""
        try:
            folders = deps.get_swarm_trajectory_folders()
            file_path = _resolve_static_plot_path(folders["plots"], filename)

            if not file_path.exists() or not file_path.is_file():
                raise HTTPException(status_code=404, detail="Plot not found")

            return FileResponse(file_path)
        except HTTPException:
            raise
        except Exception as exc:
            raise HTTPException(status_code=500, detail=str(exc)) from exc

    return router
