from __future__ import annotations

import argparse
import csv
from pathlib import Path
from typing import Any

from simulator.engine import run_session


def _read_last_metrics_ext_row(path: Path) -> dict[str, str]:
  if not path.exists():
    return {}

  with path.open("r", encoding="utf-8", newline="") as handle:
    reader = csv.DictReader(handle)
    rows = list(reader)

  if not rows:
    return {}

  return rows[-1]


def run_batch(cfg: dict[str, Any], runs: int, out_dir: Path, prefix: str = "batch") -> Path:
  out_dir.mkdir(parents=True, exist_ok=True)
  summary_path = out_dir / f"{prefix}_summary.csv"

  header = [
    "run_id",
    "session_id",
    "agents",
    "houses",
    "days",
    "share",
    "noise",
    "graph",
    "seed",
    "agent",
    "m1_personal",
    "m2_zebra",
    "known_personal_facts",
    "correct_personal_facts",
    "total_personal_facts",
    "zebra_resolved",
    "zebra_owner_pred",
    "zebra_owner_true",
    "metrics_path",
    "metrics_ext_path",
    "events_path",
    "xml_path",
  ]

  with summary_path.open("w", encoding="utf-8", newline="") as handle:
    writer = csv.writer(handle)
    writer.writerow(header)

    base_seed = cfg.get("seed")
    for run_index in range(runs):
      session_id = f"{prefix}_{run_index + 1:04d}"
      run_cfg = dict(cfg)

      if base_seed is None:
        run_cfg["seed"] = None
      else:
        run_cfg["seed"] = int(base_seed) + run_index

      result = run_session(session_id, run_cfg, out_dir)
      metrics_ext_path = Path(result["metrics_ext"])

      rows: list[dict[str, str]] = []
      if metrics_ext_path.exists():
        with metrics_ext_path.open("r", encoding="utf-8", newline="") as metrics_handle:
          reader = csv.DictReader(metrics_handle)
          rows = list(reader)

      if not rows:
        writer.writerow(
          [
            str(run_index + 1),
            session_id,
            str(run_cfg.get("agents", "")),
            str(run_cfg.get("houses", "")),
            str(run_cfg.get("days", "")),
            str(run_cfg.get("share", "")),
            str(run_cfg.get("noise", "")),
            str(run_cfg.get("graph", "")),
            str(run_cfg.get("seed", "")),
            "",
            "",
            "",
            "",
            "",
            "",
            "",
            "",
            "",
            str(result["metrics"]),
            str(result["metrics_ext"]),
            str(result["csv"]),
            str(result["xml"]),
          ]
        )
        continue

      by_agent: dict[str, dict[str, str]] = {}
      for row in rows:
        by_agent[row["agent"]] = row

      for agent_name in sorted(by_agent):
        row = by_agent[agent_name]
        writer.writerow(
          [
            str(run_index + 1),
            session_id,
            str(run_cfg.get("agents", "")),
            str(run_cfg.get("houses", "")),
            str(run_cfg.get("days", "")),
            str(run_cfg.get("share", "")),
            str(run_cfg.get("noise", "")),
            str(run_cfg.get("graph", "")),
            str(run_cfg.get("seed", "")),
            agent_name,
            row.get("m1_personal", ""),
            row.get("m2_zebra", ""),
            row.get("known_personal_facts", ""),
            row.get("correct_personal_facts", ""),
            row.get("total_personal_facts", ""),
            row.get("zebra_resolved", ""),
            row.get("zebra_owner_pred", ""),
            row.get("zebra_owner_true", ""),
            str(result["metrics"]),
            str(result["metrics_ext"]),
            str(result["csv"]),
            str(result["xml"]),
          ]
        )

  return summary_path


def build_arg_parser() -> argparse.ArgumentParser:
  parser = argparse.ArgumentParser(description="Batch runner for Zebra simulation")
  parser.add_argument("--runs", type=int, default=10)
  parser.add_argument("--agents", type=int, default=6)
  parser.add_argument("--houses", type=int, default=6)
  parser.add_argument("--days", type=int, default=50)
  parser.add_argument("--share", type=str, default="meet")
  parser.add_argument("--noise", type=float, default=0.0)
  parser.add_argument("--graph", type=str, default="ring")
  parser.add_argument("--seed", type=int, default=None)
  parser.add_argument("--sleep-ms-per-day", type=int, default=0)
  parser.add_argument("--out-dir", type=str, default="data/logs")
  parser.add_argument("--prefix", type=str, default="batch")
  return parser


def main() -> None:
  args = build_arg_parser().parse_args()

  cfg = {
    "agents": args.agents,
    "houses": args.houses,
    "days": args.days,
    "share": args.share,
    "noise": args.noise,
    "graph": args.graph,
    "seed": args.seed,
    "sleep_ms_per_day": args.sleep_ms_per_day,
  }

  summary_path = run_batch(
    cfg=cfg,
    runs=args.runs,
    out_dir=Path(args.out_dir),
    prefix=args.prefix,
  )
  print(summary_path)


if __name__ == "__main__":
  main()