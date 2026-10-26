"""Parameter series for rough surfaces (G14a): configs that differ in RMS roughness and seed.

Pure Python (no library, no Streamlit). The runs of a series are started by ``bridge.start_series``.
"""

from __future__ import annotations

import copy
import re

MAX_RUNS = 64


def parse_numbers(text: str, *, integers: bool = False, minimum: float = 0.0) -> list[float | int]:
    """Numbers separated by commas, semicolons or blanks ("50, 100 150"); order kept, duplicates dropped.

    Raises ValueError (German message for the UI) for anything that is not a number >= ``minimum``."""
    out: list = []
    for tok in [t for t in re.split(r"[,;\s]+", text.strip()) if t]:
        try:
            x = int(tok) if integers else float(tok.replace(",", "."))
        except ValueError:
            raise ValueError(f"„{tok}“ ist keine {'ganze ' if integers else ''}Zahl") from None
        if x < minimum:
            raise ValueError(f"{tok} liegt unter {minimum:g}")
        if x not in out:
            out.append(x)
    if not out:
        raise ValueError("keine Werte angegeben")
    return out


def supports_series(cfg: dict) -> bool:
    """Series over sigma and seed need a geometry with both parameters (the Gaussian rough surface)."""
    params = cfg.get("geometry", {}).get("params", {})
    return "sigma" in params and "seed" in params


def rough_series(cfg: dict, sigmas_nm: list[float], seeds: list[int]) -> list[dict]:
    """One config per (sigma, seed), sigma-major; the names carry sigma and seed. The library rules in
    ``resolved`` do not depend on sigma (box depth, waist fraction: material, wavelength, h) and are kept."""
    if not supports_series(cfg):
        raise ValueError("Serien über σ und Seed gibt es nur für die raue Oberfläche.")
    if len(sigmas_nm) * len(seeds) > MAX_RUNS:
        raise ValueError(f"Höchstens {MAX_RUNS} Läufe pro Serie ({len(sigmas_nm)} × {len(seeds)} angefordert).")
    if any(s <= 0 for s in seeds):
        raise ValueError("Seeds müssen ≥ 1 sein (Seed 0 ist nicht reproduzierbar und ergäbe in einer Serie "
                         "unvergleichbare Läufe).")
    out = []
    for sigma in sigmas_nm:
        for seed in seeds:
            c = copy.deepcopy(cfg)
            c["geometry"]["params"]["sigma"] = float(sigma)
            c["geometry"]["params"]["seed"] = int(seed)
            c["name"] = f"{cfg.get('name', 'lauf')}_sigma{sigma:g}_seed{seed}"
            out.append(c)
    return out


def has_speckle(cfg: dict) -> bool:
    return any(o.get("type") == "speckle_statistics" for o in cfg.get("observables", []))


def ensemble_request(run_dirs: list, cfgs: list[dict], tolerance: float = 0.0) -> dict:
    """Payload of the worker command ``speckle_ensemble``: the run directories and, if every geometry has a
    ``sigma`` (display unit nm), the RMS heights in metres for the contrast-over-sigma table."""
    req: dict = {"runs": [str(d) for d in run_dirs], "tolerance": float(tolerance)}
    sig = [c.get("geometry", {}).get("params", {}).get("sigma") for c in cfgs]
    if sig and all(s is not None for s in sig):
        req["sigmas"] = [float(s) * 1e-9 for s in sig]
    return req
