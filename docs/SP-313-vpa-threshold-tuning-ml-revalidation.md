# SP-313 — Tune VPA Thresholds & Re-validate ML after VPA 0.5

**Type:** Analysis / experiment (5-point Story). No code or config change resulted.
**Project/Space:** Side Projects
**Status:** Complete — recommendation below.

## 1. Background

SP-312 measured whether VPA features have predictive edge using ML. On 10 years of daily SPY
data (2461 rows) it found a **Baseline VPA accuracy of 52.34%** and an **ML walk-forward
accuracy of 50.59% ± 3.09%**, with flat feature importance (top feature only 5.8%). It
concluded the rule-based approach is near-optimal.

SP-313 set out to pursue three avenues off the back of that:

1. **Tune VPA thresholds** using SP-312's feature-importance findings (shooting-star detection,
   accumulation/distribution scoring, period-3 weighting, and the zero-importance volume-backed
   signals).
2. **Re-run ML validation after VPA 0.5** — SP-304 (MA crossover 50/200 SMA), SP-305
   (momentum/drawdown filter) and SP-306 (RSI overbought/oversold), all complete — to see if the
   new features changed the predictive edge.
3. **Test individual S&P 500 stocks** to check whether VPA has a *stronger* edge on individual
   names than on the SPY index ETF (hypothesis: individual stocks are less efficient than SPY).

The experiment was gated on measured improvement throughout: a tuned threshold is only applied
if it beats the in-effect baseline by at least the SP-312 ML standard deviation (3.09pp), and ML
is only recommended for production if its accuracy exceeds 54%.

## 2. SPY re-validation after VPA 0.5

Window 2016-12-23 → 2026-10-08, 2460 labelled rows, seed 42.

| Metric | SP-312 baseline | SPY (now) | Signed delta | Classification |
|---|---|---|---|---|
| Baseline VPA accuracy | 52.34% | **52.64%** | +0.30pp | increased (marginal) |
| ML walk-forward accuracy | 50.59% ± 3.09% | **48.59% ± 1.77%** | -2.00pp | within-band |

The ML result falls inside the SP-312 ±1σ band (47.50%–53.68%), so the drop is **not** a
meaningful change — it is noise around chance. Feature importance remained flat and reshuffled
(top feature `dss_bearish_cross` at 0.0612; `is_shooting_star`, SP-312's #1, dropped out of the
top 5). The harness conclusion was *"Rule-based approach outperforms ML on this dataset."*

**Takeaway:** VPA 0.5 did not move the needle. ML remains below the rule-based baseline and near
a coin flip.

## 3. Pursue decision (production ML model)

The decision rule (Req 8): recommend a production ML model only if SPY ML walk-forward accuracy
is strictly greater than 54.0%.

Measured ML accuracy is **48.59%** — not above 54%, and below the rule-based baseline.

> **Recommendation: do NOT pursue a production ML model.** Supporting value: ML walk-forward
> accuracy 48.59%.

## 4. Threshold sweeps and the apply gate

Four sweeps were run on a pinned snapshot, each varying one dimension off the current config:

| Dimension | Candidates swept |
|---|---|
| Shooting-star | `shooting_star_spread_mult` = 1.5, 3.0 (default 2.0) |
| Acc/dist | `acc_dist_volume_percentile` = 55, 75 (default 65); `acc_dist_test_count` = 2, 4 (default 3) |
| Period-3 weighting | `period_weight_p3` = 2.5 (p1=p2=1.0); p3 = 1.5 (p1=p2=0.5) |
| Vol-backed | `vol_backed_mult_p1/p2` = 1.0 and 0.0 (p3 left at 2.0) |

The Req 6 apply gate requires a candidate to beat the in-effect baseline accuracy by **≥ 3.09pp**
(the SP-312 ML standard deviation) before it is applied to `config.json`.

**Result: no dimension produced a change clearing the gate.** All current thresholds are
retained — no change was beneficial, and **`config.json` is unchanged.** This matches SP-312's
finding that the rule-based approach is near-optimal.

## 5. Individual tickers vs SPY

Edge metric = rule-based **Baseline_Accuracy** vs the SPY baseline of 52.64%, classified with the
±3.09pp band (comparable = within 49.55%–55.73%). All four tickers ran clean (2460 labelled rows
each, no `InsufficientDataError`).

| Ticker | Baseline VPA | ML walk-forward | Δ baseline vs SPY | Edge | Harness conclusion |
|---|---|---|---|---|---|
| SPY (ref) | 52.64% | 48.59% ± 1.77% | — | — | Rule-based > ML |
| KO | 48.86% | 52.49% ± 1.99% | -3.78pp | **weaker** | Features have signal but scoring rules suboptimal |
| JNJ | 51.79% | 48.93% ± 0.85% | -0.85pp | comparable | No predictive edge detected |
| MSFT | 51.99% | 50.73% ± 1.85% | -0.65pp | comparable | No predictive edge detected |
| NVDA | 51.22% | 50.00% ± 2.84% | -1.42pp | comparable | No predictive edge detected |

**Hypothesis verdict: REJECTED.** SP-313 hypothesised that individual stocks might be less
efficient than SPY and show a stronger VPA edge. Three of four tickers are *comparable* to SPY
and one (KO) is *weaker*; **none is stronger.** Individual stocks do not show a stronger VPA edge
than the index.

### 5.1 Note on KO ("features have signal")

KO is the only ticker whose harness line read *"features have signal"*, which looks encouraging
at a glance. On the hypothesis's edge metric, though, KO is the **weakest** of the four — a
rule-based baseline of 48.86%, *below* a coin flip and 3.78pp worse than SPY. What actually
happened is that ML (52.49%) beat KO's own weak rule-based baseline (48.86%): the rules score KO
*badly*, not that VPA has an edge there. KO's ML is still below the 54% pursue threshold and
within noise, so it does **not** reopen the pursue decision.

## 6. Overall recommendation

> **Do not pursue a production ML model, and do not change any VPA thresholds.**

The rule-based VPA approach is near-optimal. Its edge is marginal (~50–53%, barely above a coin
flip) and that holds across VPA 0.5, across all four tuning dimensions, and across individual
stocks vs the SPY index. SP-313's three avenues — threshold tuning, ML after VPA 0.5, and an
individual-stock edge — are all **closed with evidence**.

## 7. Future work (not in scope for SP-313)

The KO result — ML beating a weak rule-based baseline on a low-volatility defensive name — hints
that the rule-based scoring may be mis-calibrated specifically for low-volatility / defensive
stocks. If this is revisited, it is worth a separate follow-up spike. It is not actionable under
SP-313 and does not change this ticket's conclusion.

## 8. Reproducibility

- **Seed:** 42 (set before dataset generation and before model training).
- **Data window:** 2016-12-23 → 2026-10-08 (~10 years daily, 2460 labelled rows per ticker).
- **Config:** `vpa/config/config.json` defaults (unchanged by this work).
- **Commands:**
  - SPY re-validation: `python -m vpa.ml_validation.run_analysis --ticker SPY`
  - Threshold sweeps: `python -m vpa.ml_validation.tuning.run_sweep --ticker SPY`
  - Individual tickers: `python -m vpa.ml_validation.run_analysis --ticker <KO|JNJ|MSFT|NVDA> --output-dir ml_validation_output/<TICKER>`
- **Artefacts:** under `ml_validation_output/` (and `ml_validation_output/<TICKER>/` per ticker)
  and `ml_validation_sweep_output/`.
- **Nuance:** the `run_analysis` runs use a "today minus ~10 years" window, so the exact window
  shifts over calendar time. For a bit-for-bit re-run, the sweep driver accepts `--end-date` to
  pin the window end (Req 1.4).
