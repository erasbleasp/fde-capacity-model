"""FDE capacity model: monthly steps over the horizon, vectorized over trials.

    result = run_model(point_params(load_assumptions()))          # single-value (P50) view
    result = run_model(draw_params(tree, 2000, seed=7), process_noise=True, seed=7)   # Monte Carlo

Units: capacity and effort are both STAFFING WEEKS (one FDE assigned full time for one week).
Overhead (PTO, presales, internal, harvest) is already inside the measured durations, so it only
matters when it moves away from the calibration level: more overhead -> fewer delivery hours per
staffed week -> longer engagements.

Each month, in order:
  1. Supply     attrition, hires landing after time-to-fill, ramp, managers hired to hold the span
  2. Capacity   ramp-weighted ICs x 4.33 weeks x target utilization (planned allocation)
  3. Cycle time duration per type from base median, staffing, reuse, and overhead stretch; effort
  4. Demand     requests x fit rate, split by type (Greenfield share falls as reuse rises)
  5. Allocation partners take eligible work first, FDEs take the rest, unserved demand queues or walks
  6. Outcomes   coverage, gap, utilization, wait, Day-90, reuse ratio, cost
  7. Flywheel   finished engagements harvest assets; library decays; reuse rises toward its ceiling

Capacity and demand are compared as a monthly flow (FDE-weeks demanded by engagements starting
this month vs FDE-weeks available this month). That is exact in steady state and lags reality by
about one engagement length when demand or headcount changes quickly.
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd
from scipy import stats

from .params import REGIONS, ROLES, TYPES, Params, node

WEEKS_PER_MONTH = 52 / 12
# blocker delays are integrated over these quantiles of their lognormal distribution
_Z_BLOCKER = stats.norm.ppf([0.1, 0.3, 0.5, 0.7, 0.9])


@dataclass
class Result:
    """Model output. Every series is (n, T) or (n, T, k) with labels in `dims`."""
    months: list
    n: int
    series: dict[str, np.ndarray]
    dims: dict[str, list[str]]

    def __getitem__(self, name: str) -> np.ndarray:
        return self.series[name]

    def quantiles(self, name: str, qs=(0.1, 0.5, 0.9)) -> np.ndarray:
        """(len(qs), T[, k]) quantiles across trials."""
        return np.quantile(self.series[name], qs, axis=0)

    def p50(self, name: str) -> np.ndarray:
        return np.median(self.series[name], axis=0)


def lognormal_cdf(x, median, sigma):
    with np.errstate(divide="ignore", invalid="ignore"):
        z = (np.log(np.maximum(x, 1e-9)) - np.log(median)) / sigma
    return np.where(x > 0, stats.norm.cdf(z), 0.0)


def p_live_by(days, median_days, sigma, blocker_p, blocker_median_days, blocker_sigma, cancel_p):
    """P(kickoff -> production <= days) for lognormal build time plus an optional blocker delay.
    Cancelled engagements never go live (they stay in the denominator)."""
    unblocked = lognormal_cdf(days, median_days, sigma)
    blocked = np.mean([lognormal_cdf(days - blocker_median_days * np.exp(blocker_sigma * z), median_days, sigma)
                       for z in _Z_BLOCKER], axis=0)
    return (1 - cancel_p) * ((1 - blocker_p) * unblocked + blocker_p * blocked)


def delivery_terms(p: Params):
    """(deploy_frac, stretch): delivery share of non-PTO hours, and how much overhead above the
    calibration level stretches durations. Harvest above the reference level displaces delivery
    hours except for the share taken from slack (bench) time."""
    ref_h = p("overhead.reference_harvest_share")
    harvest_delivery = ref_h + (p("overhead.harvest_share") - ref_h) * (1 - p("overhead.harvest_from_slack"))
    deploy_frac = 1 - p("overhead.presales_share") - p("overhead.internal_share") - harvest_delivery
    stretch = p("overhead.reference_delivery_share") / ((1 - p("overhead.pto_share")) * deploy_frac)
    return deploy_frac, stretch


def reuse_level(library, reuse_max, half_k):
    """Effort share covered by assets for pattern-based work: R = Rmax (1 - e^(-L/k))."""
    return reuse_max * (1 - np.exp(-library / half_k))


def run_model(p: Params, process_noise: bool = False, seed: int | None = None) -> Result:
    rng = np.random.default_rng(seed)
    n, tree = p.n, p.tree
    T = int(node(tree, "horizon.months"))
    months = list(pd.date_range(node(tree, "horizon.start"), periods=T, freq="MS").date)
    col = lambda a: a[:, None]  # (n,) -> (n, 1)

    # ---------------------------------------------------------------- inputs
    # demand
    req0, growth, fit = p("demand.requests_per_month"), p("demand.monthly_growth"), p("demand.fit_rate")
    gf0, gf_shift = p("demand.greenfield_share"), p("demand.greenfield_shift_per_reuse")
    mix = p.raw("demand.type_mix")
    pattern_of_rest = mix["Pattern-based"] / (mix["Pattern-based"] + mix["Expansion"])
    abandon = p("demand.backlog_abandon_rate")
    region_mix = np.array([p.raw("demand.region_mix")[r] for r in REGIONS])

    # supply
    start_hc = p.raw("supply.starting_headcount")["by_region_role"]
    ic = np.zeros((n, len(REGIONS), len(ROLES), 4))      # ICs by region x role x ramp month (1, 2, 3, 4+)
    mgr = np.zeros((n, len(REGIONS)))
    for r, region in enumerate(REGIONS):
        for j, role in enumerate(ROLES):
            ic[:, r, j, 3] = start_hc[region][role]
        mgr[:, r] = start_hc[region]["Eng Manager"]
    # recent hires are still ramping: move them from ramped into months 1-3, pro rata by region and role
    in_ramp = p("supply.in_ramp_at_start")
    ramped = ic[..., 3].copy()
    share = ramped / ramped.sum(axis=(1, 2), keepdims=True)
    for b in range(3):
        moved = in_ramp[:, None, None] / 3 * share
        ic[..., b] += moved
        ic[..., 3] -= moved

    hires_pm = p("supply.hires_per_month")
    hire_mix = np.array([p.raw("supply.hiring_region_mix")[r] for r in REGIONS])
    senior_share = p("supply.senior_share_of_hires")
    ttf_months = p("supply.time_to_fill_days") / 30.4
    open_reqs = p("supply.open_reqs")
    ramp = np.array(p.raw("supply.ramp"), dtype=float)
    ramp_u = p("supply.ramp_uncertainty")
    ramp_eff = np.minimum(ramp[None, :] * np.where(np.arange(4) < 3, col(ramp_u), 1.0), 1.0)   # (n, 4)
    p_exit = 1 - np.exp(-p("supply.annual_attrition") / 12)   # attrition is a rate: exits / avg HC
    span = p("supply.manager_span")

    # overhead: staffable weeks per ramped IC per month, and how much overhead stretches durations
    harvest = p("overhead.harvest_share")
    deploy_frac, stretch = delivery_terms(p)          # deploy_frac is of non-PTO hours
    plannable = WEEKS_PER_MONTH * p("overhead.target_utilization")

    # cycle time
    base_median = np.array([node(tree, f"cycle_time.base_duration_days.{k}")["median"] for k in TYPES])
    sigma = np.array([node(tree, f"cycle_time.base_duration_days.{k}")["sigma"] for k in TYPES])
    fdes = np.array([p.raw("cycle_time.fdes_per_engagement")[k] for k in TYPES])
    ref = np.array([p.raw("cycle_time.ref_fdes")[k] for k in TYPES])
    staffing_factor = (ref / fdes)[None, :] ** col(p("cycle_time.staffing_alpha"))       # (n, 3)
    median_u = p("cycle_time.median_uncertainty")
    blocker_p = p("cycle_time.blocker_prob")
    bspec = node(tree, "cycle_time.blocker_delay_weeks")
    blocker_mean_w = bspec["median"] * np.exp(bspec["sigma"] ** 2 / 2)
    cancel = p("cycle_time.cancel_prob")
    handoff_w = p("cycle_time.handoff_weeks")
    lognormal_mean = np.exp(sigma ** 2 / 2)                 # mean / median of the build-time lognormal

    # partners (FDE-equivalent capacity, eligible types only)
    partner_eq = p("partners.weeks_per_month") * p("partners.efficiency")
    efficiency = p("partners.efficiency")
    eligible = np.array([k in p.raw("partners.eligible_types") for k in TYPES], dtype=float)

    # flywheel
    library = p("assets.starting_library").copy()
    yield5, decay = p("assets.yield_at_5pct_harvest"), p("assets.monthly_decay")
    rmax, half_k = p("assets.reuse_max"), p("assets.reuse_half_k")
    type_reuse = np.stack([p("assets.greenfield_reuse_factor"), np.ones(n), np.ones(n)], axis=1)   # (n, 3)
    level0 = reuse_level(library, rmax, half_k)

    fde_cost_w, partner_cost_w = p("economics.fde_loaded_cost_per_week"), p("economics.partner_cost_per_week")

    # ---------------------------------------------------------------- monthly loop
    backlog = np.zeros((n, 3))
    completions = None
    out: dict[str, list] = {}

    def rec(name, value):
        out.setdefault(name, []).append(np.array(value, dtype=float))

    for t in range(T):
        # 1. supply ----------------------------------------------------
        if process_noise:
            exits = rng.binomial(np.rint(ic).astype(int), p_exit[:, None, None, None]).astype(float)
            mgr_exits = rng.binomial(np.rint(mgr).astype(int), col(p_exit)).astype(float)
        else:
            exits = ic * p_exit[:, None, None, None]
            mgr_exits = mgr * col(p_exit)
        ic = ic - exits
        mgr = mgr - mgr_exits

        # reqs opened continuously at hires_pm/month land ttf later; open reqs land over the first ttf
        landed = lambda tau: hires_pm * np.maximum(0, tau - ttf_months) + open_reqs * np.clip(tau / ttf_months, 0, 1)
        hires = landed(t + 1) - landed(t)
        if process_noise:
            new_r = rng.poisson(col(hires) * hire_mix).astype(float)
            senior = rng.binomial(new_r.astype(int), col(senior_share)).astype(float)
        else:
            new_r = col(hires) * hire_mix
            senior = new_r * col(senior_share)
        ic[..., 3] += ic[..., 2]
        ic[..., 2] = ic[..., 1]
        ic[..., 1] = ic[..., 0]
        ic[..., 0] = np.stack([new_r - senior, senior], axis=2)

        mgr_needed = ic.sum(axis=(2, 3)) / col(span)
        mgr_hires = np.maximum(0, mgr_needed - mgr)
        if process_noise:
            mgr_hires = np.ceil(mgr_hires - 1e-9)
        mgr = mgr + mgr_hires

        # 2. capacity --------------------------------------------------
        eff_ic_r = (ic * ramp_eff[:, None, None, :]).sum(axis=(2, 3))          # (n, R)
        fde_cap_r = eff_ic_r * col(plannable)
        fde_cap = fde_cap_r.sum(axis=1)

        # 3. cycle time ------------------------------------------------
        level = reuse_level(library, rmax, half_k)
        R = col(level) * type_reuse                                             # (n, 3)
        med_days = base_median * col(median_u * stretch) * staffing_factor * (1 - R)
        build_w = med_days * lognormal_mean / 7
        effort = fdes * (build_w + col(blocker_p) * blocker_mean_w * 0.5 + col(handoff_w) * 0.5) * col(1 - 0.4 * cancel)
        build_w_no_reuse = build_w / (1 - R)

        # 4. demand ----------------------------------------------------
        gf = np.clip(gf0 - gf_shift * (level - level0), 0.2, 0.9)
        shares = np.stack([gf, (1 - gf) * pattern_of_rest, (1 - gf) * (1 - pattern_of_rest)], axis=1)
        expected_req = req0 * (1 + growth) ** t
        if process_noise:
            requests = rng.poisson(expected_req).astype(float)
            fit_n = rng.binomial(requests.astype(int), fit)
            new = rng.multinomial(fit_n, shares).astype(float)
        else:
            requests = expected_req
            new = col(requests * fit) * shares
        demand_w = (new * effort).sum(axis=1)

        # 5. allocation ------------------------------------------------
        avail = new + backlog
        w = avail * effort
        elig_w = (w * eligible).sum(axis=1)
        partner_frac = np.where(elig_w > 0, np.minimum(elig_w, partner_eq) / np.maximum(elig_w, 1e-12), 0.0)
        partner_k = avail * col(partner_frac) * eligible
        rem = avail - partner_k
        rem_w = (rem * effort).sum(axis=1)
        fde_frac = np.where(rem_w > 0, np.minimum(1.0, fde_cap / np.maximum(rem_w, 1e-12)), 1.0)
        fde_k = rem * col(fde_frac)
        left = avail - partner_k - fde_k
        declined = left * col(abandon)
        backlog = left - declined

        # 6. outcomes --------------------------------------------------
        served_k = fde_k + partner_k
        served = served_k.sum(axis=1)
        fde_served_w = (fde_k * effort).sum(axis=1)
        partner_used_w = (partner_k * effort).sum(axis=1) / efficiency
        eff_cap = fde_cap + np.minimum(partner_eq, (new * effort * eligible).sum(axis=1))
        ic_heads = ic.sum(axis=(1, 2, 3))

        d90_fde = p_live_by(90, med_days, sigma, col(blocker_p), bspec["median"] * 7, bspec["sigma"], col(cancel))
        d90_partner = p_live_by(90, med_days / col(efficiency), sigma, col(blocker_p), bspec["median"] * 7,
                                bspec["sigma"], col(cancel))
        day90 = ((fde_k * d90_fde).sum(axis=1) + (partner_k * d90_partner).sum(axis=1)) / np.maximum(served, 1e-12)
        weight = served_k * fdes * build_w_no_reuse
        reuse_ratio = (weight * R).sum(axis=1) / np.maximum(weight.sum(axis=1), 1e-12)
        cost = (ic_heads + mgr.sum(axis=1)) * fde_cost_w * WEEKS_PER_MONTH + partner_used_w * partner_cost_w

        rec("requests", requests)
        rec("demand_weeks", demand_w)
        rec("fde_capacity_weeks", fde_cap)
        rec("partner_capacity_weeks", partner_eq)
        rec("effective_capacity_weeks", eff_cap)
        rec("coverage", eff_cap / np.maximum(demand_w, 1e-12))
        rec("gap_weeks", eff_cap - demand_w)
        rec("hires_needed", np.maximum(0, demand_w - eff_cap) / plannable)
        rec("starts", served)
        rec("declined", declined.sum(axis=1))
        rec("backlog", backlog.sum(axis=1))
        rec("wait_months", backlog.sum(axis=1) / np.maximum(served, 1e-12))
        # delivery hours / non-PTO hours: a staffed week yields deploy_frac of an IC's non-PTO hours
        rec("utilization", fde_served_w * deploy_frac / (ic_heads * WEEKS_PER_MONTH))
        rec("partner_weeks_used", partner_used_w)
        rec("hc_total", ic_heads + mgr.sum(axis=1))
        rec("hc_ic", ic_heads)
        rec("hc_mgr", mgr.sum(axis=1))
        rec("effective_ic", eff_ic_r.sum(axis=1))
        rec("hires", new_r.sum(axis=1) + mgr_hires.sum(axis=1))
        rec("exits", exits.sum(axis=(1, 2, 3)) + mgr_exits.sum(axis=1))
        rec("greenfield_share", gf)
        rec("reuse_level", level)
        rec("reuse_ratio", reuse_ratio)
        rec("day90", day90)
        rec("median_days_to_prod", (served_k * med_days).sum(axis=1) / np.maximum(served, 1e-12))
        rec("cost", cost)
        rec("cost_per_engagement", cost / np.maximum(served, 1e-12))
        rec("new_by_type", new)
        rec("starts_fde_by_type", fde_k)
        rec("starts_partner_by_type", partner_k)
        rec("day90_by_type", d90_fde)
        rec("hc_ic_by_region_role", ic.sum(axis=3))
        rec("hc_mgr_by_region", mgr)
        rec("fde_capacity_by_region", fde_cap_r)
        rec("fde_coverage_by_region", fde_cap_r / np.maximum(col(demand_w) * region_mix, 1e-12))

        # 7. flywheel --------------------------------------------------
        finishing = fde_k.sum(axis=1) * (1 - cancel)
        dur_months = (fde_k * effort / fdes).sum(axis=1) / np.maximum(fde_k.sum(axis=1), 1e-12) / WEEKS_PER_MONTH
        # first-order delay: completions track starts with a lag of about one engagement length
        completions = finishing if completions is None else completions + (finishing - completions) / np.maximum(dur_months, 1.0)
        library = library * (1 - decay) + completions * yield5 * harvest / 0.05
        rec("library", library)
        rec("completions", completions)

    series = {k: np.stack(v, axis=1) for k, v in out.items()}
    dims = {k: TYPES for k in ["new_by_type", "starts_fde_by_type", "starts_partner_by_type", "day90_by_type"]}
    dims.update(hc_ic_by_region_role=[REGIONS, ROLES], hc_mgr_by_region=REGIONS,
                fde_capacity_by_region=REGIONS, fde_coverage_by_region=REGIONS)
    return Result(months, n, series, dims)
