"""Load config/assumptions.yaml and turn it into per-trial parameter arrays.

Every numeric input becomes an array of shape (n,):
  - single-value mode (n = 1): each node's `value`
  - Monte Carlo (n trials): uncertain nodes (those with a `dist`, not `per_engagement`) are drawn;
    levers and fixed facts are broadcast.

Draws go through a Gaussian copula so one pair of inputs (demand growth and greenfield share)
can be rank-correlated while everything else stays independent.
"""
from __future__ import annotations

import copy
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np
import yaml
from scipy import stats

ROOT = Path(__file__).resolve().parent.parent
REGIONS = ["AMER", "EMEA", "APAC"]
ROLES = ["FDE", "Senior FDE"]          # individual contributors; managers tracked separately
TYPES = ["Greenfield", "Pattern-based", "Expansion"]
CORRELATED = ("demand.monthly_growth", "demand.greenfield_share")


def load_assumptions(path: Path = ROOT / "config" / "assumptions.yaml") -> dict:
    return yaml.safe_load(Path(path).read_text())


def load_scenarios(path: Path = ROOT / "config" / "scenarios.yaml") -> dict:
    return yaml.safe_load(Path(path).read_text())


def node(tree: dict, path: str):
    for key in path.split("."):
        tree = tree[key]
    return tree


def apply_overrides(tree: dict, overrides: dict | None) -> dict:
    """Return a copy with overrides applied. Overriding an uncertain input pins it (no spread)."""
    tree = copy.deepcopy(tree)
    for path, value in (overrides or {}).items():
        parent_path, _, key = path.rpartition(".")
        parent = node(tree, parent_path) if parent_path else tree
        if isinstance(parent.get(key), dict) and ("value" in parent[key] or "dist" in parent[key]):
            spec = parent[key]
            spec["value"] = value
            if "dist" in spec and not spec.get("per_engagement"):
                spec["dist"] = "fixed"
        else:
            parent[key] = value
    return tree


def uncertain_specs(tree: dict, prefix: str = "") -> dict[str, dict]:
    """All nodes Monte Carlo draws once per trial, keyed by dotted path."""
    out = {}
    if isinstance(tree, dict):
        dist = tree.get("dist")
        if dist in ("triangular", "lognormal", "beta") and not tree.get("per_engagement"):
            out[prefix] = tree
        for k, v in tree.items():
            if isinstance(v, dict):
                out.update(uncertain_specs(v, f"{prefix}.{k}" if prefix else k))
    return out


def ppf(spec: dict, u: np.ndarray) -> np.ndarray:
    """Inverse CDF of a spec's distribution at uniform quantiles u."""
    d = spec["dist"]
    if d == "triangular":
        a, c, b = spec["low"], spec["mode"], spec["high"]
        if b == a:
            return np.full_like(u, a, dtype=float)
        fc = (c - a) / (b - a)
        return np.where(u < fc,
                        a + np.sqrt(u * (b - a) * (c - a)),
                        b - np.sqrt((1 - u) * (b - a) * (b - c)))
    if d == "lognormal":
        return spec["median"] * np.exp(spec["sigma"] * stats.norm.ppf(u))
    if d == "beta":
        m, sd = spec["mean"], spec["sd"]
        if sd == 0:
            return np.full_like(u, m, dtype=float)
        k = m * (1 - m) / sd ** 2 - 1
        return stats.beta.ppf(u, m * k, (1 - m) * k)
    raise ValueError(f"unknown dist {d}")


def quantile(spec: dict, q: float) -> float:
    if spec.get("dist", "fixed") == "fixed":
        return float(spec["value"])
    return float(ppf(spec, np.array([q]))[0])


@dataclass
class Params:
    """Assumption tree plus one array of shape (n,) per numeric input."""
    tree: dict
    n: int
    drawn: dict[str, np.ndarray] = field(default_factory=dict)

    def __call__(self, path: str) -> np.ndarray:
        """Numeric input as an (n,) array: the drawn values if uncertain, else the value broadcast."""
        if path in self.drawn:
            return self.drawn[path]
        v = node(self.tree, path)
        if isinstance(v, dict):
            v = v["value"]
        return np.full(self.n, float(v))

    def raw(self, path: str):
        """Non-numeric input (mixes, lists) as stored in the tree."""
        v = node(self.tree, path)
        return v["value"] if isinstance(v, dict) and "value" in v else v


def point_params(tree: dict, overrides: dict | None = None) -> Params:
    """Single-value mode: every input at its `value` (the P50 view)."""
    return Params(apply_overrides(tree, overrides), 1)


def draw_params(tree: dict, n: int, seed: int, overrides: dict | None = None) -> Params:
    """Monte Carlo mode: draw every uncertain input n times via a Gaussian copula."""
    tree = apply_overrides(tree, overrides)
    specs = uncertain_specs(tree)
    names = sorted(specs)
    rng = np.random.default_rng(seed)
    z = rng.standard_normal((n, len(names)))
    if all(c in names for c in CORRELATED):
        # Spearman rho -> Pearson r for normal copula: r = 2 sin(pi rho / 6)
        rho = node(tree, "demand.greenfield_growth_correlation")["value"]
        r = 2 * np.sin(np.pi * rho / 6)
        i, j = names.index(CORRELATED[0]), names.index(CORRELATED[1])
        z[:, j] = r * z[:, i] + np.sqrt(1 - r ** 2) * z[:, j]
    u = np.clip(stats.norm.cdf(z), 1e-9, 1 - 1e-9)
    drawn = {name: ppf(specs[name], u[:, k]) for k, name in enumerate(names)}
    return Params(tree, n, drawn)


def zero_spread(tree: dict) -> dict:
    """Copy with every uncertain input collapsed onto its value (for the engine equivalence test)."""
    tree = copy.deepcopy(tree)
    for path, spec in uncertain_specs(tree).items():
        v = spec["value"]
        if spec["dist"] == "triangular":
            spec.update(low=v, mode=v, high=v)
        elif spec["dist"] == "lognormal":
            spec.update(median=v, sigma=0.0)
        elif spec["dist"] == "beta":
            spec.update(mean=v, sd=0.0)
    return tree
