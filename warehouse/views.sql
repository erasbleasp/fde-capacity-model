-- Analytic and calibration views over the raw FDE tables.
-- `meta` (one row: history_start, as_of, staffing_alpha) is created by warehouse/build.py.
-- Records before history_start come from the generator's warm-up period; monthly views start at history_start.
-- Definitions follow docs/metric_dictionary.md.

-- ---------------------------------------------------------------- spine
CREATE OR REPLACE VIEW v_months AS
SELECT CAST(m AS DATE) AS month
FROM meta, range(CAST(meta.history_start AS TIMESTAMP), CAST(meta.as_of AS TIMESTAMP), INTERVAL 1 MONTH) t(m);

-- ---------------------------------------------------------------- demand
CREATE OR REPLACE VIEW v_demand_monthly AS
SELECT date_trunc('month', requested_date)::DATE AS month, segment, region, type,
       count(*)                                          AS requests,
       count(*) FILTER (decision = 'accepted')           AS accepted,
       count(*) FILTER (decision = 'declined_fit')       AS declined_fit,
       count(*) FILTER (decision = 'declined_capacity')  AS declined_capacity,
       count(*) FILTER (decision = 'pending')            AS pending
FROM fde_requests
GROUP BY ALL;

CREATE OR REPLACE VIEW v_demand_summary AS
SELECT month,
       sum(requests) AS requests, sum(accepted) AS accepted,
       sum(declined_fit) AS declined_fit, sum(declined_capacity) AS declined_capacity,
       sum(pending) AS pending,
       sum(accepted) / nullif(sum(requests) - sum(pending), 0) AS attach_rate,
       sum(requests) FILTER (type = 'Greenfield') / sum(requests) AS greenfield_share
FROM v_demand_monthly
WHERE month >= (SELECT history_start FROM meta)
GROUP BY month;

-- ---------------------------------------------------------------- delivery cycle
CREATE OR REPLACE VIEW v_engagement_reuse AS
WITH saved AS (
    SELECT engagement_id, sum(effort_hours_saved) AS hours_saved, count(*) AS assets_used
    FROM asset_usage GROUP BY ALL
), fde_hours AS (
    SELECT engagement_id, sum(hours) AS hours
    FROM time_entries WHERE category = 'deploy' GROUP BY ALL
)
SELECT e.engagement_id,
       coalesce(e.partner_hours, f.hours, 0)          AS delivery_hours,
       coalesce(s.hours_saved, 0)                     AS hours_saved,
       coalesce(s.assets_used, 0)                     AS assets_used,
       -- time tracking starts at history_start, so earlier engagements have incomplete hours
       CASE WHEN e.kickoff_date >= m.history_start THEN
           coalesce(s.hours_saved, 0)
             / nullif(coalesce(e.partner_hours, f.hours, 0) + coalesce(s.hours_saved, 0), 0)
       END AS reuse_ratio
FROM engagements e
CROSS JOIN meta m
LEFT JOIN saved s USING (engagement_id)
LEFT JOIN fde_hours f USING (engagement_id);

CREATE OR REPLACE VIEW v_cycle_times AS
SELECT e.*,
       r.reuse_ratio, r.assets_used, r.hours_saved, r.delivery_hours,
       e.kickoff_date - e.signed_date                 AS queue_wait_days,
       e.prod_date - e.kickoff_date                   AS days_to_prod,
       e.closed_date - e.kickoff_date                 AS engagement_days,
       coalesce(e.prod_date - e.kickoff_date <= 90, false) AS live_by_d90,
       e.kickoff_date + 90 <= m.as_of                 AS d90_mature,
       date_trunc('month', e.kickoff_date)::DATE      AS kickoff_month
FROM engagements e
JOIN v_engagement_reuse r USING (engagement_id)
CROSS JOIN meta m;

-- Lognormal fit of kickoff -> production time, per type.
-- Uses engagements kicked off >= 180 days before as-of to limit right-censoring.
-- median_base_days strips out blockers, reuse and staffing (alpha from meta) so it
-- is comparable to the model's base duration.
CREATE OR REPLACE VIEW v_duration_fit AS
WITH ref AS (
    SELECT * FROM (VALUES ('Greenfield', 2.0), ('Pattern-based', 1.5), ('Expansion', 1.0)) t(type, ref_fdes)
), d AS (
    SELECT c.*, ref.ref_fdes, m.staffing_alpha
    FROM v_cycle_times c JOIN ref USING (type) CROSS JOIN meta m
    WHERE c.days_to_prod IS NOT NULL AND c.kickoff_date <= m.as_of - 180
      AND c.reuse_ratio IS NOT NULL
)
SELECT type, partner_led,
       count(*)                                         AS n,
       exp(avg(ln(days_to_prod)))                       AS median_days,
       stddev_samp(ln(days_to_prod))                    AS sigma_ln,
       exp(avg(ln(days_to_prod)) FILTER (NOT had_blocker)) AS median_days_unblocked,
       exp(avg(ln(days_to_prod
                  / power(ref_fdes / fdes_planned, staffing_alpha)
                  / (1 - coalesce(reuse_ratio, 0)))) FILTER (NOT had_blocker)) AS median_base_days,
       stddev_samp(ln(days_to_prod
                  / power(ref_fdes / fdes_planned, staffing_alpha)
                  / (1 - coalesce(reuse_ratio, 0)))) FILTER (NOT had_blocker)  AS sigma_base_ln
FROM d
GROUP BY ALL;

-- ---------------------------------------------------------------- day-90 productization
CREATE OR REPLACE VIEW v_day90_cohorts AS
SELECT kickoff_month AS cohort_month, type, partner_led,
       count(*)                                                      AS kicked_off,
       count(*) FILTER (days_to_prod <= 30)                          AS live_by_d30,
       count(*) FILTER (days_to_prod <= 60)                          AS live_by_d60,
       count(*) FILTER (days_to_prod <= 90)                          AS live_by_d90,
       count(*) FILTER (status = 'cancelled')                        AS cancelled,
       bool_and(d90_mature)                                          AS mature
FROM v_cycle_times
WHERE kickoff_date >= (SELECT history_start FROM meta)
GROUP BY ALL;

CREATE OR REPLACE VIEW v_day90_summary AS
SELECT cohort_month,
       sum(kicked_off) AS kicked_off,
       sum(live_by_d30) / sum(kicked_off) AS d30_rate,
       sum(live_by_d60) / sum(kicked_off) AS d60_rate,
       sum(live_by_d90) / sum(kicked_off) AS d90_rate,
       sum(cancelled)  / sum(kicked_off) AS cancel_rate,
       bool_and(mature) AS mature
FROM v_day90_cohorts
GROUP BY cohort_month;

-- ---------------------------------------------------------------- supply
CREATE OR REPLACE VIEW v_headcount_monthly AS
SELECT m.month, r.region, r.role,
       count(*) FILTER (r.hire_date < m.month AND (r.term_date IS NULL OR r.term_date >= m.month))  AS hc_start,
       count(*) FILTER (r.hire_date >= m.month AND r.hire_date < m.month + INTERVAL 1 MONTH)         AS hires,
       count(*) FILTER (r.term_date >= m.month AND r.term_date < m.month + INTERVAL 1 MONTH)         AS exits,
       count(*) FILTER (r.hire_date < m.month + INTERVAL 1 MONTH
                        AND (r.term_date IS NULL OR r.term_date >= m.month + INTERVAL 1 MONTH))     AS hc_end
FROM v_months m CROSS JOIN roster r
GROUP BY ALL;

CREATE OR REPLACE VIEW v_time_to_fill AS
SELECT q.*, coalesce(q.filled_date, m.as_of) - q.opened_date AS days_open,
       q.filled_date IS NOT NULL AS filled
FROM requisitions q CROSS JOIN meta m;

-- Deployable share (deploy + bench) of available hours by month of tenure, relative to tenured FDEs
CREATE OR REPLACE VIEW v_ramp AS
WITH w AS (
    SELECT t.fde_id, t.week_start,
           least(floor((t.week_start - r.hire_date) / 30.4) + 1, 5)::INT AS tenure_month,
           sum(hours) FILTER (category IN ('deploy', 'bench'))           AS deployable,
           sum(hours) FILTER (category <> 'pto')                         AS available
    FROM time_entries t JOIN roster r USING (fde_id)
    WHERE r.role <> 'Eng Manager'
    GROUP BY ALL
), b AS (
    SELECT tenure_month, sum(deployable) / sum(available) AS deployable_share
    FROM w WHERE available > 0 GROUP BY ALL
)
SELECT tenure_month, deployable_share,
       deployable_share / (SELECT deployable_share FROM b WHERE tenure_month = 5) AS ramp_factor
FROM b ORDER BY tenure_month;

-- ---------------------------------------------------------------- utilization & overhead
CREATE OR REPLACE VIEW v_overhead_mix AS
WITH t AS (
    SELECT date_trunc('month', week_start)::DATE AS month, category, sum(hours) AS hours
    FROM time_entries GROUP BY ALL
), tot AS (
    SELECT month, sum(hours) AS all_hours, coalesce(sum(hours) FILTER (category = 'pto'), 0) AS pto_hours
    FROM t GROUP BY month
)
SELECT t.month, t.category, t.hours,
       t.hours / tot.all_hours                                   AS share_of_all,
       CASE WHEN t.category = 'pto' THEN NULL
            ELSE t.hours / (tot.all_hours - tot.pto_hours) END   AS share_of_available
FROM t JOIN tot USING (month);

CREATE OR REPLACE VIEW v_utilization_monthly AS
SELECT date_trunc('month', t.week_start)::DATE AS month, r.region,
       count(DISTINCT t.fde_id)                                                        AS fdes_logging,
       sum(hours)                                                                      AS all_hours,
       sum(hours) FILTER (category = 'deploy')                                         AS deploy_hours,
       sum(hours) FILTER (category = 'deploy') / sum(hours) FILTER (category <> 'pto') AS utilization,
       sum(hours) FILTER (category = 'bench')  / sum(hours) FILTER (category <> 'pto') AS bench_rate
FROM time_entries t JOIN roster r USING (fde_id)
GROUP BY ALL;

-- ---------------------------------------------------------------- reuse & assets
CREATE OR REPLACE VIEW v_reuse_monthly AS
WITH closed AS (
    SELECT date_trunc('month', closed_date)::DATE AS month,
           sum(hours_saved) AS hours_saved, sum(delivery_hours) AS delivery_hours, count(*) AS closed
    FROM v_cycle_times
    WHERE status = 'closed' AND reuse_ratio IS NOT NULL
    GROUP BY ALL
), started AS (
    SELECT kickoff_month AS month, count(*) AS kicked_off,
           count(*) FILTER (assets_used > 0) / count(*) AS asset_attach_rate
    FROM v_cycle_times WHERE kickoff_date IS NOT NULL
    GROUP BY ALL
)
SELECT m.month,
       coalesce(c.closed, 0) AS engagements_closed,
       c.hours_saved / nullif(c.delivery_hours + c.hours_saved, 0) AS reuse_ratio,
       s.kicked_off, s.asset_attach_rate
FROM v_months m
LEFT JOIN closed c USING (month)
LEFT JOIN started s USING (month);

CREATE OR REPLACE VIEW v_asset_library_monthly AS
WITH me AS (SELECT month, CAST(month + INTERVAL 1 MONTH AS DATE) AS next_month FROM v_months)
SELECT me.month,
       (SELECT count(*) FROM assets a
         WHERE a.created_date < me.next_month
           AND (a.deprecated_date IS NULL OR a.deprecated_date >= me.next_month))       AS active_assets,
       (SELECT count(*) FROM assets a
         WHERE a.created_date >= me.month AND a.created_date < me.next_month)            AS created,
       (SELECT count(*) FROM assets a
         WHERE a.deprecated_date >= me.month AND a.deprecated_date < me.next_month)      AS deprecated,
       (SELECT count(*) FROM engagements e
         WHERE NOT e.partner_led AND e.status = 'closed'
           AND e.closed_date >= me.month AND e.closed_date < me.next_month)              AS fde_closed,
       -- share of active assets used by a partner-led engagement kicked off in the trailing 6 months
       (SELECT count(DISTINCT u.asset_id) FROM asset_usage u JOIN engagements e USING (engagement_id)
         JOIN assets a USING (asset_id)
         WHERE e.partner_led AND e.kickoff_date < me.next_month
           AND e.kickoff_date >= me.next_month - INTERVAL 6 MONTH
           AND (a.deprecated_date IS NULL OR a.deprecated_date >= me.next_month))
       / nullif((SELECT count(*) FROM assets a
         WHERE a.created_date < me.next_month
           AND (a.deprecated_date IS NULL OR a.deprecated_date >= me.next_month)), 0)    AS partner_adoption
FROM me;

-- ---------------------------------------------------------------- consumption
-- Spend indexed to the 3 months before kickoff, by months since first go-live.
CREATE OR REPLACE VIEW v_consumption_curve AS
WITH first_live AS (
    SELECT account_id, min(prod_date) AS golive, min(kickoff_date) AS kickoff
    FROM engagements WHERE prod_date IS NOT NULL GROUP BY ALL
), pre AS (
    SELECT f.account_id, avg(c.spend_usd) AS pre_spend
    FROM first_live f JOIN consumption c USING (account_id)
    WHERE c.month >= date_trunc('month', f.kickoff) - INTERVAL 3 MONTH
      AND c.month <  date_trunc('month', f.kickoff)
    GROUP BY ALL
)
SELECT datediff('month', date_trunc('month', f.golive), c.month) AS months_from_golive,
       count(DISTINCT c.account_id)                              AS accounts,
       avg(c.spend_usd / p.pre_spend)                            AS spend_index,
       median(c.spend_usd / p.pre_spend)                         AS spend_index_median
FROM first_live f
JOIN pre p USING (account_id)
JOIN consumption c USING (account_id)
GROUP BY ALL
ORDER BY months_from_golive;

-- ---------------------------------------------------------------- calibration
-- One row per model parameter, with the view it comes from. Feeds config/assumptions.yaml.
CREATE OR REPLACE VIEW v_calibration AS
WITH last_full AS (
    SELECT * FROM v_demand_summary
    WHERE month < (SELECT date_trunc('month', as_of) FROM meta)
), recent AS (
    SELECT * FROM last_full ORDER BY month DESC LIMIT 6
), growth AS (
    SELECT exp(regr_slope(ln(requests), datediff('month', (SELECT history_start FROM meta), month))) - 1 AS g,
           -- trend level at the as-of month: a trailing average lags a growing series by ~3 months
           exp(regr_intercept(ln(requests), datediff('month', (SELECT history_start FROM meta), month))
               + regr_slope(ln(requests), datediff('month', (SELECT history_start FROM meta), month))
                 * datediff('month', (SELECT history_start FROM meta), (SELECT date_trunc('month', as_of) FROM meta))) AS level
    FROM last_full
), hc AS (
    SELECT month, sum(hc_start) AS hc_start, sum(hc_end) AS hc_end, sum(exits) AS exits, sum(hires) AS hires
    FROM v_headcount_monthly GROUP BY month
), ttf AS (
    SELECT quantile_cont(days_open, 0.1) AS p10, quantile_cont(days_open, 0.5) AS p50,
           quantile_cont(days_open, 0.9) AS p90
    FROM v_time_to_fill WHERE filled
), oh AS (
    SELECT category, sum(hours) AS hours FROM v_overhead_mix
    WHERE month >= (SELECT date_trunc('month', as_of) - INTERVAL 3 MONTH FROM meta)
    GROUP BY ALL
), oh_tot AS (
    SELECT sum(hours) FILTER (category <> 'pto') AS avail, sum(hours) AS all_h FROM oh
), mature AS (
    SELECT * FROM v_cycle_times
    WHERE d90_mature AND kickoff_date >= (SELECT history_start FROM meta)
), recent_kick AS (
    SELECT * FROM v_cycle_times, meta
    WHERE kickoff_date IS NOT NULL AND kickoff_date > meta.as_of - 180
)
          SELECT 'requests_per_month'      AS param, avg(requests)               AS value, 'requests/mo, last 6 full months' AS unit, 'v_demand_summary' AS source FROM recent
UNION ALL SELECT 'monthly_demand_growth',    g,                                 'log-linear trend',            'v_demand_summary' FROM growth
UNION ALL SELECT 'requests_per_month_trend', level,                             'requests/mo at as-of, trend fit', 'v_demand_summary' FROM growth
UNION ALL SELECT 'attach_rate_mean',         sum(accepted) / sum(requests - pending), 'share, last 6 months',  'v_demand_summary' FROM recent
UNION ALL SELECT 'attach_rate_sd',           stddev_samp(attach_rate),          'monthly sd, last 6 months',   'v_demand_summary' FROM recent
UNION ALL SELECT 'decline_fit_rate',         sum(declined_fit) / sum(requests - pending), 'share, all history', 'v_demand_summary' FROM last_full
UNION ALL SELECT 'decline_capacity_rate',    sum(declined_capacity) / sum(requests - pending), 'share, last 6 months', 'v_demand_summary' FROM recent
UNION ALL SELECT 'greenfield_share',         sum(requests * greenfield_share) / sum(requests), 'share, last 6 months', 'v_demand_summary' FROM recent
UNION ALL SELECT 'median_days_' || lower(replace(type, '-', '_')) || '_base', median_base_days, 'days, kickoff->prod', 'v_duration_fit'
          FROM v_duration_fit WHERE NOT partner_led
UNION ALL SELECT 'sigma_ln_' || lower(replace(type, '-', '_')), sigma_base_ln, 'lognormal sigma', 'v_duration_fit'
          FROM v_duration_fit WHERE NOT partner_led
UNION ALL SELECT 'blocker_rate',             avg(had_blocker::INT),             'share of kicked-off',         'v_cycle_times' FROM mature
UNION ALL SELECT 'cancel_rate',              avg((status = 'cancelled')::INT),  'share of kicked-off',         'v_cycle_times' FROM mature
UNION ALL SELECT 'partner_share',            avg(partner_led::INT),             'share, kicked off last 180d', 'v_cycle_times' FROM recent_kick
UNION ALL SELECT 'queue_wait_days_median',   median(queue_wait_days) FILTER (NOT partner_led), 'days, kicked off last 180d', 'v_cycle_times' FROM recent_kick
UNION ALL SELECT 'day90_rate',               avg(live_by_d90::INT),             'share, mature cohorts',       'v_day90_cohorts' FROM mature
UNION ALL SELECT 'annual_attrition',         sum(exits) / avg((hc_start + hc_end) / 2.0) * 12 / count(*), 'exits / avg HC, annualized', 'v_headcount_monthly' FROM hc
UNION ALL SELECT 'hc_as_of',                 hc_end,                            'heads',                       'v_headcount_monthly'
          FROM (SELECT * FROM hc ORDER BY month DESC LIMIT 1)
UNION ALL SELECT 'hires_per_month_recent',   avg(hires),                        'hires/mo, last 6 months',     'v_headcount_monthly'
          FROM (SELECT * FROM hc ORDER BY month DESC LIMIT 6)
UNION ALL SELECT 'time_to_fill_p10', p10, 'days', 'v_time_to_fill' FROM ttf
UNION ALL SELECT 'time_to_fill_p50', p50, 'days', 'v_time_to_fill' FROM ttf
UNION ALL SELECT 'time_to_fill_p90', p90, 'days', 'v_time_to_fill' FROM ttf
UNION ALL SELECT 'open_reqs', count(*), 'reqs', 'v_time_to_fill' FROM v_time_to_fill WHERE NOT filled
UNION ALL SELECT 'ramp_m' || tenure_month, ramp_factor, 'share of ramped', 'v_ramp' FROM v_ramp WHERE tenure_month < 5
UNION ALL SELECT 'pto_share', (SELECT hours FROM oh WHERE category = 'pto') / all_h, 'of all hours, last 3 months', 'v_overhead_mix' FROM oh_tot
UNION ALL SELECT category || '_share', hours / (SELECT avail FROM oh_tot), 'of available hours, last 3 months', 'v_overhead_mix'
          FROM oh WHERE category NOT IN ('pto')
UNION ALL SELECT 'internal_share_ic', sum(t.hours) FILTER (category = 'internal') / sum(t.hours) FILTER (category <> 'pto'),
          'of available hours, ramped ICs, last 3 months', 'v_overhead_mix'
          FROM time_entries t JOIN roster r USING (fde_id), meta
          WHERE r.role <> 'Eng Manager' AND t.week_start - r.hire_date >= 150
            AND t.week_start >= date_trunc('month', meta.as_of) - INTERVAL 3 MONTH
UNION ALL SELECT 'planned_allocation', sum(t.hours) FILTER (category = 'deploy') / sum(t.hours) FILTER (category IN ('deploy', 'bench')),
          'deploy / (deploy + unassigned) hours, ramped ICs, last 6 months', 'v_overhead_mix'
          FROM time_entries t JOIN roster r USING (fde_id), meta
          WHERE r.role <> 'Eng Manager' AND t.week_start - r.hire_date >= 150
            AND t.week_start >= date_trunc('month', meta.as_of) - INTERVAL 6 MONTH
UNION ALL SELECT 'partner_weeks_per_month', sum(c.partner_hours) / 40 / 6,
          'partner hours / 40, kicked off last 6 months', 'v_cycle_times'
          FROM v_cycle_times c, meta WHERE c.partner_led AND c.kickoff_date > meta.as_of - 183
UNION ALL SELECT 'fdes_per_' || lower(replace(type, '-', '_')), avg(fdes_planned), 'FTE planned at kickoff', 'v_cycle_times'
          FROM v_cycle_times WHERE NOT partner_led GROUP BY type
UNION ALL SELECT 'consumption_lift_m6', spend_index_median, 'spend vs 3 months pre-kickoff, median', 'v_consumption_curve'
          FROM v_consumption_curve WHERE months_from_golive = 6
UNION ALL SELECT 'active_assets', active_assets, 'assets at as-of', 'v_asset_library_monthly'
          FROM (SELECT * FROM v_asset_library_monthly ORDER BY month DESC LIMIT 1)
UNION ALL SELECT 'harvest_yield', sum(created) / nullif(sum(fde_closed), 0), 'assets per closed FDE-led engagement, since 2026-01', 'v_asset_library_monthly'
          FROM v_asset_library_monthly WHERE month >= DATE '2026-01-01'
UNION ALL SELECT 'asset_monthly_decay', sum(deprecated) / nullif(sum(active_assets), 0), 'share of library per month', 'v_asset_library_monthly'
          FROM v_asset_library_monthly
UNION ALL SELECT 'reuse_ratio', sum(hours_saved) / nullif(sum(delivery_hours + hours_saved), 0), 'effort-weighted, closed last 6 months', 'v_engagement_reuse'
          FROM v_cycle_times, meta WHERE status = 'closed' AND reuse_ratio IS NOT NULL AND closed_date > meta.as_of - 183;
