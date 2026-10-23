"""Simulate 18 months of made-up FDE operations, week by week.

Each week: hires join, some FDEs leave (their engagements slip and need backfill),
inbound requests are scoped and accepted or declined, queued engagements kick off when
FDEs are free, everyone logs hours, finished engagements close and harvest assets.

All parameters come from config/synthetic_truth.yaml. Output is a dict of DataFrames
keyed by table name (see warehouse/schema.sql).
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from datetime import date, timedelta
from pathlib import Path

import numpy as np
import pandas as pd
import yaml

ROOT = Path(__file__).resolve().parent.parent
TYPES = ["Greenfield", "Pattern-based", "Expansion"]
# FDE allocation options per type and their probabilities
FDE_OPTIONS = {
    "Greenfield": ([1.5, 2.0, 2.5], [0.25, 0.50, 0.25]),
    "Pattern-based": ([1.0, 1.5, 2.0], [0.30, 0.40, 0.30]),
    "Expansion": ([0.5, 1.0, 1.5], [0.25, 0.50, 0.25]),
}


def load_truth(path: Path = ROOT / "config" / "synthetic_truth.yaml") -> dict:
    with open(path) as f:
        return yaml.safe_load(f)


def monday(d: date) -> date:
    return d - timedelta(days=d.weekday())


def chunks(fdes: float) -> list[float]:
    """Split an FDE allocation into per-person chunks: 2.5 -> [1, 1, 0.5]."""
    out = [1.0] * int(fdes)
    if fdes - int(fdes) > 1e-9:
        out.append(0.5)
    return out


@dataclass
class Fde:
    fde_id: str
    role: str
    region: str
    hire_date: date
    term_date: date | None = None
    alloc: dict = field(default_factory=dict)  # engagement_id -> allocation

    def free(self) -> float:
        return 1.0 - sum(self.alloc.values())

    def tenure_month(self, d: date) -> int:
        return int((d - self.hire_date).days / 30.4) + 1


@dataclass
class Engagement:
    engagement_id: str
    request_id: str
    account_id: str
    segment: str
    region: str
    type: str
    partner_led: bool
    partner_id: str | None
    fdes: float
    signed: date
    kickoff: date | None = None
    prod: date | None = None
    closed: date | None = None
    cancelled: bool = False
    blocker: bool = False
    reuse: float = 0.0
    ready: date | None = None  # earliest kickoff after customer mobilization
    backfill: list = field(default_factory=list)
    released: bool = False


class Sim:
    def __init__(self, truth: dict):
        self.t = truth
        self.rng = np.random.default_rng(truth["seed"])
        self.start = monday(truth["start_date"])
        # simulate a warm-up period first so the history starts with engagements in flight
        self.sim_start = self.start - timedelta(weeks=truth["burn_in_weeks"])
        self.end = truth["end_date"]
        self.months_total = (self.end - self.start).days / 30.4

        self.fdes: dict[str, Fde] = {}
        self.reqs: list[dict] = []
        self.accounts: dict[str, dict] = {}
        self.requests: list[dict] = []
        self.pending: list[dict] = []
        self.engs: dict[str, Engagement] = {}
        self.queue: list[str] = []
        self.staffing: list[dict] = []
        self.time_rows: list[tuple] = []
        self.assets: list[dict] = []
        self.usage: list[dict] = []
        self.hire_schedule: dict[date, list[Fde]] = {}

    # ---------- helpers ----------
    def pick(self, mix: dict) -> str:
        keys = list(mix)
        p = np.array([mix[k] for k in keys], dtype=float)
        return keys[self.rng.choice(len(keys), p=p / p.sum())]

    def tri(self, spec: dict) -> float:
        return self.rng.triangular(spec["low"], spec["mode"], spec["high"])

    def frac(self, d: date) -> float:
        """Fraction of the history elapsed at date d (0..1)."""
        return min(max((d - self.start).days / 30.4 / self.months_total, 0.0), 1.0)

    def harvest_share(self, d: date) -> float:
        tm = self.t["time"]
        return tm["harvest_share_after"] if d >= tm["harvest_push_date"] else tm["harvest_share_before"]

    def active_assets(self, d: date) -> list[dict]:
        return [a for a in self.assets
                if a["created_date"] <= d and (a["deprecated_date"] is None or a["deprecated_date"] > d)]

    def reuse_level(self, d: date) -> float:
        a = self.t["assets"]
        return a["reuse_max"] * (1 - math.exp(-len(self.active_assets(d)) / a["reuse_half_k"]))

    def active_fdes(self) -> list[Fde]:
        return [f for f in self.fdes.values() if f.term_date is None]

    def staffable(self, f: Fde, d: date) -> bool:
        return f.role != "Eng Manager" and f.tenure_month(d) >= 2

    # ---------- setup ----------
    def new_fde(self, hire_date: date) -> Fde:
        r = self.t["roster"]
        everyone = list(self.fdes.values()) + sum(self.hire_schedule.values(), [])
        managers = sum(f.role == "Eng Manager" for f in everyone)
        ics = len(everyone) - managers
        role = "Eng Manager" if ics >= r["manager_span"] * max(managers, 1) else self.pick(r["role_mix"])
        return Fde(f"FDE-{len(everyone) + 1:04d}", role, self.pick(self.t["regions"]), hire_date)

    def setup(self):
        r = self.t["roster"]
        for _ in range(r["starting_hc"]):
            hire = monday(self.sim_start - timedelta(days=int(self.rng.integers(180, 1100))))
            f = self.new_fde(hire)
            self.fdes[f.fde_id] = f
        # hire schedule through 4 months past the as-of date so open reqs exist at the end
        m, d = 0, self.sim_start
        horizon = self.end + timedelta(days=120)
        while d <= horizon:
            rate = r["hires_per_month_start"] + (r["hires_per_month_end"] - r["hires_per_month_start"]) * self.frac(d)
            for _ in range(self.rng.poisson(rate)):
                hire = monday(d + timedelta(days=int(self.rng.integers(0, 28))))
                if hire < self.sim_start:
                    hire += timedelta(days=7)
                f = self.new_fde(hire)
                self.hire_schedule.setdefault(hire, []).append(f)
                opened = hire - timedelta(days=int(self.tri(r["time_to_fill_days"])))
                if opened <= self.end:
                    filled = hire <= self.end
                    self.reqs.append(dict(req_id=f"REQ-{len(self.reqs) + 1:04d}", role=f.role, region=f.region,
                                          opened_date=opened, filled_date=hire if filled else None,
                                          fde_id=f.fde_id if filled else None))
            m += 1
            d = self.sim_start + timedelta(days=int(30.4 * m))
        # starting asset library
        a = self.t["assets"]
        for _ in range(a["starting_library"]):
            self.add_asset(self.sim_start - timedelta(days=int(self.rng.integers(1, 180))), None)

    def add_asset(self, created: date, source: str | None):
        self.assets.append(dict(asset_id=f"AST-{len(self.assets) + 1:04d}", asset_type=self.pick(self.t["assets"]["types"]),
                                source_engagement_id=source, created_date=created, deprecated_date=None))

    def account_for(self, req_type: str, segment: str, region: str, d: date) -> tuple[str, str, str, str]:
        """Return (account_id, segment, region, type). Expansion needs an account already live."""
        if req_type == "Expansion":
            live = sorted({e.account_id for e in self.engs.values() if e.prod and e.prod <= d})
            if live:
                acct = live[self.rng.integers(len(live))]
                a = self.accounts[acct]
                return acct, a["segment"], a["region"], req_type
            req_type = "Pattern-based"
        existing = [k for k, a in self.accounts.items() if a["segment"] == segment and a["region"] == region]
        if existing and self.rng.random() < 0.2:
            return existing[self.rng.integers(len(existing))], segment, region, req_type
        acct = f"ACC-{len(self.accounts) + 1:04d}"
        self.accounts[acct] = dict(account_id=acct, segment=segment, region=region, first_seen=d)
        return acct, segment, region, req_type

    # ---------- weekly steps ----------
    def hires(self, ws: date):
        for f in self.hire_schedule.get(ws, []):
            self.fdes[f.fde_id] = f

    def attrition(self, ws: date):
        p_week = 1 - (1 - self.t["roster"]["annual_attrition"]) ** (1 / 52)
        slip = timedelta(weeks=self.t["engagement"]["attrition_slip_weeks"])
        for f in self.active_fdes():
            if f.hire_date >= ws or self.rng.random() >= p_week:
                continue
            f.term_date = ws
            for eid, alloc in list(f.alloc.items()):
                e = self.engs[eid]
                self.end_staffing(eid, f.fde_id, ws)
                if e.prod and e.prod > ws:  # still building: slip and backfill
                    e.prod += slip
                    e.closed += slip
                    e.backfill.append(alloc)
            f.alloc.clear()

    def end_staffing(self, eid: str, fde_id: str, d: date):
        for s in self.staffing:
            if s["engagement_id"] == eid and s["fde_id"] == fde_id and s["end_date"] is None:
                s["end_date"] = d

    def load(self, d: date) -> float:
        avail = sum(1.0 for f in self.active_fdes() if self.staffable(f, d))
        used = sum(sum(f.alloc.values()) for f in self.active_fdes())
        queued = sum(self.engs[e].fdes for e in self.queue)
        return (used + queued) / max(avail, 1.0)

    def arrivals(self, ws: date):
        dm = self.t["demand"]
        months = (ws - self.start).days / 30.4
        rate = dm["requests_per_month_start"] * (1 + dm["monthly_growth"]) ** months
        for _ in range(self.rng.poisson(rate * 7 / 30.4)):
            requested = ws + timedelta(days=int(self.rng.integers(0, 5)))
            # greenfield share falls as reuse grows; the rest split by base mix
            base = dm["type_mix_base"]
            g = max(base["Greenfield"] - dm["greenfield_shift_per_reuse"] * self.reuse_level(requested), 0.2)
            rest = 1 - g
            other = base["Pattern-based"] + base["Expansion"]
            mix = {"Greenfield": g, "Pattern-based": rest * base["Pattern-based"] / other,
                   "Expansion": rest * base["Expansion"] / other}
            acct, seg, reg, typ = self.account_for(self.pick(mix), self.pick(self.t["segments"]),
                                                   self.pick(self.t["regions"]), requested)
            req = dict(request_id=f"REQ-FDE-{len(self.requests) + 1:04d}", account_id=acct, segment=seg, region=reg,
                       type=typ, requested_date=requested,
                       decision_date=requested + timedelta(days=int(self.tri(dm["scoping_days"]))),
                       decision="pending", engagement_id=None)
            self.requests.append(req)
            self.pending.append(req)

    def decisions(self, ws: date):
        dm, en = self.t["demand"], self.t["engagement"]
        week_end = ws + timedelta(days=6)
        due = [r for r in self.pending if r["decision_date"] <= week_end]
        for r in sorted(due, key=lambda r: r["decision_date"]):
            self.pending.remove(r)
            if self.rng.random() < dm["decline_fit_prob"]:
                r["decision"] = "declined_fit"
                continue
            p_partner = 0.0
            if r["type"] != "Greenfield":
                p_partner = en["partner_led_prob_start"] + (en["partner_led_prob_end"] - en["partner_led_prob_start"]) * self.frac(ws)
            partner_led = self.rng.random() < p_partner
            if not partner_led:
                load = self.load(ws)
                p_accept = next(p for below, p in dm["accept_prob_by_load"] if load < below)
                if self.rng.random() >= p_accept:
                    r["decision"] = "declined_capacity"
                    continue
            r["decision"] = "accepted"
            opts, probs = FDE_OPTIONS[r["type"]]
            e = Engagement(f"ENG-{len(self.engs) + 1:04d}", r["request_id"], r["account_id"], r["segment"], r["region"],
                           r["type"], partner_led,
                           f"PTN-{self.rng.integers(len(self.t['partners'])) + 1:02d}" if partner_led else None,
                           float(self.rng.choice(opts, p=probs)), r["decision_date"])
            r["engagement_id"] = e.engagement_id
            self.engs[e.engagement_id] = e
            e.ready = e.signed + timedelta(days=int(self.tri(dm["mobilization_days"])))
            if partner_led:
                self.kickoff(e, e.ready)
            else:
                self.queue.append(e.engagement_id)

    def kickoff(self, e: Engagement, d: date):
        en, a = self.t["engagement"], self.t["assets"]
        e.kickoff = d
        # reuse available at kickoff
        r = self.reuse_level(d) * (a["greenfield_reuse_factor"] if e.type == "Greenfield" else 1.0)
        e.reuse = float(np.clip(r * self.rng.lognormal(0, 0.3), 0, 0.6))
        weeks = (en["base_duration_weeks"][e.type]
                 * (en["ref_fdes"][e.type] / e.fdes) ** en["staffing_alpha"]
                 * (1 - e.reuse)
                 * self.rng.lognormal(0, en["duration_sigma"]))
        if e.partner_led:
            weeks *= en["partner_duration_factor"]
        if self.rng.random() < en["blocker_prob"]:
            e.blocker = True
            bd = en["blocker_delay_weeks"]
            weeks += self.rng.lognormal(math.log(bd["median"]), bd["sigma"])
        if self.rng.random() < en["cancel_prob"]:
            e.cancelled = True
            e.closed = d + timedelta(days=int(weeks * 7 * self.rng.uniform(0.3, 0.9)))
        else:
            e.prod = d + timedelta(days=int(weeks * 7))
            e.closed = e.prod + timedelta(weeks=en["handoff_weeks"])
        # assets used
        lib = self.active_assets(d)
        if e.reuse > 0.01 and lib:
            n = min(1 + self.rng.poisson(e.reuse * 8), len(lib))
            for i in self.rng.choice(len(lib), size=n, replace=False):
                self.usage.append(dict(engagement_id=e.engagement_id, asset_id=lib[i]["asset_id"], weight=self.rng.random() + 0.2))

    def assign(self, e: Engagement, need: list[float], d: date) -> list[tuple[Fde, float]] | None:
        """Find FDEs for each chunk, same region first. Returns None if any chunk can't be filled."""
        taken: dict[str, float] = {}
        picks = []
        todo = sorted(need, reverse=True)
        while todo:
            c = todo.pop(0)
            cands = [f for f in self.active_fdes()
                     if self.staffable(f, d) and f.free() - taken.get(f.fde_id, 0) >= c - 1e-9]
            if not cands and c > 0.5:
                todo += [0.5] * int(c / 0.5)
                continue
            if not cands:
                return None
            cands.sort(key=lambda f: (f.region != e.region, -(f.free() - taken.get(f.fde_id, 0)), f.fde_id))
            f = cands[0]
            taken[f.fde_id] = taken.get(f.fde_id, 0) + c
            picks.append((f, c))
        return picks

    def staff(self, ws: date):
        # backfill first, then FIFO kickoffs
        for e in self.engs.values():
            if e.backfill and not e.released:
                picks = self.assign(e, e.backfill, ws)
                if picks:
                    for f, c in picks:
                        f.alloc[e.engagement_id] = f.alloc.get(e.engagement_id, 0) + c
                        self.staffing.append(dict(engagement_id=e.engagement_id, fde_id=f.fde_id, allocation=c,
                                                  start_date=ws, end_date=None))
                    e.backfill = []
        for eid in list(self.queue):
            e = self.engs[eid]
            if e.ready > ws + timedelta(days=4):
                continue
            picks = self.assign(e, chunks(e.fdes), ws)
            if picks is None:
                continue
            self.queue.remove(eid)
            self.kickoff(e, min(max(ws + timedelta(days=int(self.rng.integers(0, 5))), e.ready), self.end))
            for f, c in picks:
                f.alloc[eid] = f.alloc.get(eid, 0) + c
                self.staffing.append(dict(engagement_id=eid, fde_id=f.fde_id, allocation=c,
                                          start_date=e.kickoff, end_date=None))

    def log_time(self, ws: date):
        tm, ramp = self.t["time"], self.t["roster"]["ramp"]
        holiday = ws.strftime("%m-%d") in tm["holiday_weeks"]
        for f in self.active_fdes():
            if f.hire_date > ws:
                continue
            pto = 40.0 if self.rng.random() < tm["pto_week_prob"] else (20.0 if holiday else 0.0)
            rows = [("pto", None, pto)]
            n = tm["hours_per_week"] - pto
            if n > 0:
                noise = lambda: self.rng.lognormal(0, 0.2)
                presales = n * tm["presales_share"] * noise()
                internal = n * tm["internal_share"] * noise()
                if f.role == "Eng Manager":
                    internal += n * tm["manager_extra_internal"]
                harvest = n * self.harvest_share(ws) * noise()
                deployable = max(n - presales - internal - harvest, 0.0)
                rf = ramp[min(f.tenure_month(ws), len(ramp)) - 1]
                internal += deployable * (1 - rf)  # ramp-up / training
                deployable *= rf
                rows += [("presales", None, presales), ("internal", None, internal), ("harvest", None, harvest)]
                for eid, alloc in f.alloc.items():
                    rows.append(("deploy", eid, deployable * alloc))
                rows.append(("bench", None, deployable * f.free()))
            for cat, eid, h in rows:
                if h > 0.05:
                    self.time_rows.append((f.fde_id, ws, cat, eid, round(h, 1)))

    def close(self, ws: date):
        a = self.t["assets"]
        week_end = ws + timedelta(days=6)
        for e in self.engs.values():
            if e.released or e.closed is None or e.closed > week_end:
                continue
            e.released = True
            e.backfill = []
            for f in self.fdes.values():
                if e.engagement_id in f.alloc:
                    del f.alloc[e.engagement_id]
                    self.end_staffing(e.engagement_id, f.fde_id, e.closed)
            if not e.cancelled and not e.partner_led:
                lam = a["yield_at_5pct"] * self.harvest_share(e.closed) / 0.05
                for _ in range(self.rng.poisson(lam)):
                    self.add_asset(e.closed + timedelta(days=int(self.rng.integers(0, 30))), e.engagement_id)

    def decay(self, ws: date):
        p_week = 1 - (1 - self.t["assets"]["monthly_decay"]) ** (12 / 52)
        for a in self.assets:
            if a["deprecated_date"] is None and a["created_date"] <= ws and self.rng.random() < p_week:
                a["deprecated_date"] = ws

    def run(self):
        self.setup()
        ws = self.sim_start
        while ws <= self.end:
            self.hires(ws)
            self.attrition(ws)
            self.arrivals(ws)
            self.decisions(ws)
            self.staff(ws)
            self.log_time(ws)
            self.close(ws)
            self.decay(ws)
            ws += timedelta(weeks=1)
        return self.tables()

    # ---------- output ----------
    def tables(self) -> dict[str, pd.DataFrame]:
        end = self.end
        clip = lambda d: d if d is not None and d <= end else None

        roster = pd.DataFrame([dict(fde_id=f.fde_id, role=f.role, region=f.region, hire_date=f.hire_date,
                                    term_date=f.term_date) for f in self.fdes.values() if f.hire_date <= end])

        engs = []
        for e in self.engs.values():
            kickoff = clip(e.kickoff)
            prod, closed = clip(e.prod), clip(e.closed)
            if kickoff is None:
                status = "queued"
            elif e.cancelled and closed:
                status = "cancelled"
            elif closed:
                status = "closed"
            elif prod:
                status = "live_handoff"
            else:
                status = "in_build"
            partner_hours = None
            if e.partner_led and kickoff:
                active_end = min(e.closed, end)
                partner_hours = round(e.fdes * 40 * 0.85 * (active_end - kickoff).days / 7, 1)
            engs.append(dict(engagement_id=e.engagement_id, request_id=e.request_id, account_id=e.account_id,
                             segment=e.segment, region=e.region, type=e.type, partner_led=e.partner_led,
                             partner_id=e.partner_id, fdes_planned=e.fdes, signed_date=e.signed,
                             kickoff_date=kickoff, prod_date=prod if not e.cancelled else None,
                             closed_date=closed, had_blocker=e.blocker if kickoff else None,
                             partner_hours=partner_hours, status=status))
        engagements = pd.DataFrame(engs)

        staffing = pd.DataFrame(self.staffing)
        staffing["end_date"] = staffing["end_date"].map(clip)

        time_entries = pd.DataFrame(self.time_rows, columns=["fde_id", "week_start", "category", "engagement_id", "hours"])
        all_deploy = time_entries[time_entries.category == "deploy"].groupby("engagement_id").hours.sum()
        # time tracking starts with the history window (warm-up weeks are not reported)
        time_entries = time_entries[time_entries.week_start >= self.t["start_date"]]

        # asset usage: split the engagement's saved hours across the assets it used so that
        # saved / (actual + saved) = the engagement's reuse share
        deploy = all_deploy
        usage = pd.DataFrame(self.usage)
        if not usage.empty:
            started = set(engagements.loc[engagements.kickoff_date.notna(), "engagement_id"])
            usage = usage[usage.engagement_id.isin(started)]
        rows = []
        if not usage.empty:
            for eid, g in usage.groupby("engagement_id"):
                e = self.engs[eid]
                actual = e_hours = deploy.get(eid, 0.0)
                if e.partner_led:
                    e_hours = engagements.loc[engagements.engagement_id == eid, "partner_hours"].fillna(0).iloc[0]
                    actual = e_hours
                saved = actual * e.reuse / (1 - e.reuse)
                w = g.weight / g.weight.sum()
                for (_, u), share in zip(g.iterrows(), w):
                    rows.append(dict(engagement_id=eid, asset_id=u.asset_id, effort_hours_saved=round(saved * share, 1)))
        asset_usage = pd.DataFrame(rows, columns=["engagement_id", "asset_id", "effort_hours_saved"])

        assets = pd.DataFrame(self.assets)
        assets = assets[assets.created_date <= end].copy()
        assets["deprecated_date"] = assets["deprecated_date"].map(clip)

        requests = pd.DataFrame(self.requests)
        requests = requests[requests.requested_date <= end].copy()
        requests.loc[requests.decision == "pending", "decision_date"] = None

        accounts = pd.DataFrame([{k: v for k, v in a.items() if k != "first_seen"} for a in self.accounts.values()])
        partners = pd.DataFrame([dict(partner_id=f"PTN-{i + 1:02d}", partner_name=n) for i, n in enumerate(self.t["partners"])])
        requisitions = pd.DataFrame(self.reqs)

        return dict(roster=roster, requisitions=requisitions, accounts=accounts, partners=partners,
                    fde_requests=requests, engagements=engagements, staffing=staffing, time_entries=time_entries,
                    assets=assets, asset_usage=asset_usage, consumption=self.consumption(engagements))

    def consumption(self, engagements: pd.DataFrame) -> pd.DataFrame:
        c = self.t["consumption"]
        months = pd.date_range(self.start.replace(day=1), self.end, freq="MS").date
        golives = engagements.dropna(subset=["prod_date"]).groupby("account_id").prod_date.apply(sorted).to_dict()
        kickoffs = engagements.dropna(subset=["kickoff_date"]).groupby("account_id").kickoff_date.min().to_dict()
        rows = []
        for acct, a in self.accounts.items():
            base = c["baseline_k"][a["segment"]] * 1000 * self.rng.lognormal(0, 0.6)
            first = a["first_seen"] - timedelta(days=180)
            mults = [self.rng.lognormal(math.log(c["post_golive_multiple"]["median"]), c["post_golive_multiple"]["sigma"])
                     for _ in golives.get(acct, [])]
            for m in months:
                if m < first:
                    continue
                level = 1.0
                k = kickoffs.get(acct)
                if k and m >= k:
                    level = c["not_live_multiple"]
                for i, g in enumerate(golives.get(acct, [])):
                    if m >= g.replace(day=1):
                        ramp = min(((m.year - g.year) * 12 + m.month - g.month + 1) / c["ramp_months"], 1.0)
                        level += (mults[i] - 1) * ramp * (1.0 if i == 0 else 0.5)
                rows.append(dict(account_id=acct, month=m,
                                 spend_usd=round(base * level * self.rng.lognormal(0, c["noise_sigma"]), 2)))
        return pd.DataFrame(rows)


def generate(truth: dict | None = None) -> dict[str, pd.DataFrame]:
    return Sim(truth or load_truth()).run()


if __name__ == "__main__":
    for name, df in generate().items():
        print(f"{name:14s} {len(df):>7,d} rows")
