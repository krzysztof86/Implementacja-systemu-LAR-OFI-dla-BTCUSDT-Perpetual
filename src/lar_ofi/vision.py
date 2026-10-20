"""Optional vision backend.

No vision model is bundled or assumed. A backend must be configured
explicitly as `vision.backend = "package.module:ClassName"`. Its output is
stored as UNVERIFIED observations (source "vision:<name>") which the engine
ignores until the user confirms them (or sets
observations.use_unverified_vision = true, which every report discloses via
the config hash).
"""

from __future__ import annotations

import importlib
from typing import Protocol


class VisionNotConfigured(RuntimeError):
    pass


class VisionBackend(Protocol):
    name: str

    def extract(self, image_path: str, timeframe: str, indicators: list[str]) -> list[dict]:
        """Return items {"field", "value", "readability", "note"} for one screenshot."""


def get_backend(cfg: dict) -> VisionBackend:
    spec = cfg.get("vision", {}).get("backend", "none")
    if not spec or spec == "none":
        raise VisionNotConfigured("no vision backend configured (vision.backend = 'none'); "
                                  "enter observations manually with `lar-ofi observe` / `observe-file`")
    module_name, _, cls_name = spec.partition(":")
    if not cls_name:
        raise VisionNotConfigured("vision.backend must be 'module.path:ClassName'")
    module = importlib.import_module(module_name)
    return getattr(module, cls_name)()


def run_vision(conn, cfg: dict, dataset_id: str, data_dir: str) -> tuple[list[int], list[str]]:
    from pathlib import Path

    from lar_ofi.observations import add_observations_from_list, screenshots_of
    backend = get_backend(cfg)
    items = []
    for shot in screenshots_of(conn, dataset_id):
        for it in backend.extract(str(Path(data_dir) / shot["stored_path"]), shot["timeframe"], shot["indicators"]):
            items.append({**it, "screenshot": shot["screenshot_id"], "verified": False,
                          "source": f"vision:{backend.name}"})
    return add_observations_from_list(conn, dataset_id, items, source=f"vision:{backend.name}")
