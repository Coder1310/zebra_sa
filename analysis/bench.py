from __future__ import annotations

import argparse
import csv
import statistics
import time
from pathlib import Path
from typing import Any

from simulator.engine import run_session


def _read_metrics_ext_last(metrics_ext_path: Path) -> dict[str, dict[str, str]]:
  if not metrics_ext_path.exists():
    return {}

  with metrics_ext_path.open("r", encoding="utf-8", newline="") as handle:
    reader = csv.DictReader(handle)
    rows = list(reader)

  by_agent: dict[str, dict[str, str]] = {}
  for row in rows:
    agent = str(row.get("agent") or "")
    if not agent:
      continue
    by_agent[agent] = row
  return by_agent


def _mean(values: list[float]) -> float:
  if not values:
    return 0.0
  return float(statistics.fmean(values))


def _aggregate_agents(by_agent: dict[str, dict[str, str]]) -> dict[str, float]:
  m1_values: list[float] = []
  m2_values: list[float] = []
  resolved_values: list[float] = []

  for row in by_agent.values():
    try:
      m1_values.append(float(row.get("m1_personal", 0.0)))
    except Exception:
      pass
    try:
      m2_values.append(float(row.get("m2_zebra", 0.0)))
    except Exception:
      pass
    try:
      resolved_values.append(float(row.get("zebra_resolved", 0.0)))
    except Exception:
      pass

  return {
    "final_m1_avg": _mean(m1_values),
    "final_m2_avg": _mean(m2_values),
    "final_zebra_resolved_avg": _mean(resolved_values),
  }


def run_bench(
  max_agents: int,
  step: int,
  days: int,
  runs: int,
  houses: int,
  share: str,
  graph: str,
  noise: float,
  out_dir: Path,
) -> Path:
  out_dir.mkdir(parents=True, exist_ok=True)
  out_path = out_dir / "bench.csv"

  header = [
    "agents",
    "houses",
    "days",
    "runs",
    "share",
    "graph",
    "noise",
    "run_index",
    "seed",
    "elapsed_sec",
    "final_m1_avg",
    "final_m2_avg",
    "final_zebra_resolved_avg",
    "session_id",
    "metrics_path",
    "metrics_ext_path",
    "events_path",
    "xml_path",
  ]

  with out_path.open("w", encoding="utf-8", newline="") as handle:
    writer = csv.writer(handle)
    writer.writerow(header)

    for agents in range(step, max_agents + 1, step):
      for run_index in range(1, runs + 1):
        seed = run_index
        session_id = f"bench_a{agents}_r{run_index}"
        cfg: dict[str, Any] = {
          "agents": agents,
          "houses": houses,
          "days": days,
          "share": share,
          "graph": graph,
          "noise": noise,
          "seed": seed,
        }

        started = time.perf_counter()
        result = run_session(session_id, cfg, out_dir)
        elapsed = time.perf_counter() - started

        by_agent = _read_metrics_ext_last(Path(result["metrics_ext"]))
        agg = _aggregate_agents(by_agent)

        writer.writerow(
          [
            agents,
            houses,
            days,
            runs,
            share,
            graph,
            noise,
            run_index,
            seed,
            f"{elapsed:.6f}",
            f"{agg['final_m1_avg']:.6f}",
            f"{agg['final_m2_avg']:.6f}",
            f"{agg['final_zebra_resolved_avg']:.6f}",
            session_id,
            str(result["metrics"]),
            str(result["metrics_ext"]),
            str(result["csv"]),
            str(result["xml"]),
          ]
        )

  return out_path


def build_arg_parser() -> argparse.ArgumentParser:
  parser = argparse.ArgumentParser(description="Benchmark Zebra simulation")
  parser.add_argument("--max_agents", type=int, default=100)
  parser.add_argument("--step", type=int, default=10)
  parser.add_argument("--days", type=int, default=50)
  parser.add_argument("--runs", type=int, default=3)
  parser.add_argument("--houses", type=int, default=6)
  parser.add_argument("--share", type=str, default="meet")
  parser.add_argument("--graph", type=str, default="ring")
  parser.add_argument("--noise", type=float, default=0.0)
  parser.add_argument("--out_dir", type=str, default="data/logs")
  return parser


def main() -> None:
  args = build_arg_parser().parse_args()
  out_path = run_bench(
    max_agents=args.max_agents,
    step=args.step,
    days=args.days,
    runs=args.runs,
    houses=args.houses,
    share=args.share,
    graph=args.graph,
    noise=args.noise,
    out_dir=Path(args.out_dir),
  )
  print(out_path)


if __name__ == "__main__":
  main()