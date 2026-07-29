# Benchmark & Auto-Tuning Guide

MinerWatch features an asynchronous, server-side benchmarking engine designed to automatically explore operating frequency and core voltage combinations on supported miners (Bitaxe, NerdQAxe/NerdOCTAXE, BitForge, NMAxe, etc.). It calculates optimal profiles for efficiency, maximum throughput, and quiet operation.

---

## Key Capabilities

* **Asynchronous Server Execution**: Benchmarks run as background tasks on the MinerWatch backend (`backend/benchmark.py`). You can close your browser or switch devices without interrupting a sweep.
* **Multi-Browser Live Synchronization**: Any browser opening or connecting to a miner's `BenchmarkTab` during a run receives real-time progress updates, active candidate leaderboards, telemetry charts, and timestamped step logs.
* **Microtuning Sub-Sweep**: Once the coarse matrix search identifies leading candidates, optional microtuning homes in on precise optimal operating points using fine increments (e.g. 5 MHz / 10 mV).
* **Auto-Fan Quiet Searching**: When using an auto fan mode (`Firmware (Auto)` or `MinerWatch Auto-Fan`), MinerWatch tracks settled acoustic fan speeds to calculate the maximum performance point under a set fan limit (e.g. $\le 65\%$).
* **Profile Comparison & Side-by-Side Overwrite**: Upon benchmark completion, results require acknowledgment. Users can review side-by-side parameter comparisons of new benchmark results against existing Guardian profiles before choosing to overwrite or save new profiles.

---

## Operating Profiles

The benchmark calculates three distinct optimal profiles from all stable telemetry sample points:

| Profile | Target Metric | Description |
|---|---|---|
| **Max Efficiency** | Lowest $J/\text{TH}$ | Sweet-spot profile minimizing energy consumption per Terahash. |
| **Max Hashrate** | Highest $\text{TH/s}$ | Peak performance profile maximizing mining throughput. |
| **Best Quiet** | Max $\text{TH/s}$ @ $\text{Fan} \le \text{Limit}\%$ | Maximum hashrate candidate where settled fan speed remains below the acoustic threshold (e.g., 65%). Only calculated when fan mode is set to an auto mode. |

---

## Microtuning Search Algorithm

The microtuning algorithm optimizes the search matrix in two phases:

```
┌─────────────────────────────────────────────────────────┐
│               1. Coarse Grid Matrix Sweep               │
│   Sweeps coarse increments (e.g. 20 MHz freq / 25 mV)   │
└────────────────────────────┬────────────────────────────┘
                             │
                             ▼
┌─────────────────────────────────────────────────────────┐
│             2. Leader Candidate Selection               │
│   Finds top candidate points:                           │
│   • Best Efficiency Candidate (lowest J/TH)             │
│   • Peak Hashrate Candidate (highest TH/s)              │
└────────────────────────────┬────────────────────────────┘
                             │
                             ▼
┌─────────────────────────────────────────────────────────┐
│            3. Local Search Box Construction             │
│   Creates a bounding box around each leader point:      │
│   • Freq:  [Cand_Freq - FreqStep, Cand_Freq + FreqStep] │
│   • Volt:  [Cand_Volt - VoltStep, Cand_Volt + VoltStep] │
└────────────────────────────┬────────────────────────────┘
                             │
                             ▼
┌─────────────────────────────────────────────────────────┐
│            4. Fine Microtuning Sub-Sweep                │
│   Samples fine sub-grid points (e.g. 5 MHz / 10 mV)     │
│   Filters out already-tested coarse grid points.        │
└────────────────────────────┬────────────────────────────┘
                             │
                             ▼
┌─────────────────────────────────────────────────────────┐
│            5. Final Leaderboard Re-Evaluation           │
│   Merges all stable coarse + fine samples to find:      │
│   • Max Efficiency Profile (Absolute lowest J/TH)       │
│   • Max Hashrate Profile (Absolute highest TH/s)        │
│   • Best Quiet Profile (Highest TH/s where Fan ≤ Max%)  │
└─────────────────────────────────────────────────────────┘
```

---

## Live Monitoring & UI Controls

* **Active Test Point Banner**: Shows the exact frequency (MHz), core voltage (mV), live settled hashrate (TH/s), and settled fan speed (%) currently under test starting from **Step 1**.
* **Live Candidate Cards**: Displays the leading candidates (**Max Efficiency**, **Max Hashrate**, **Best Quiet**) in real time as samples settle.
* **Gated Controls**: During an active sweep:
  * The configuration form is hidden to prevent input conflicts.
  * "Apply Profile" buttons in candidate cards are disabled to prevent interrupting active tuning.
  * Starting a second benchmark is gated on acknowledging the previous run.

---

## Guardian Integration

Guardian profiles created from benchmark sweeps integrate directly with MinerWatch's Guardian Governor (`backend/guardian.py`), allowing miners to automatically run under optimal efficiency or quiet thermal curves while preserving safety watchdogs.
