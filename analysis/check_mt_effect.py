from __future__ import annotations

import argparse
import csv
import json
from pathlib import Path
from statistics import fmean
from typing import Any

from simulator.engine import run_session


def _read_final_metrics_ext(path: Path) -> dict[str, dict[str, str]]:
  if not path.exists():
    return {}

  with path.open("r", encoding="utf-8", newline="") as handle:
    reader = csv.DictReader(handle)
    rows = list(reader)

  by_agent: dict[str, dict[str, str]] = {}
  for row in rows:
    agent = str(row.get("agent") or "")
    if not agent:
      continue
    by_agent[agent] = row
  return by_agent


def _as_float(value: Any, default: float = 0.0) -> float:
  try:
    return float(value)
  except Exception:
    return default


def _summary(by_agent: dict[str, dict[str, str]], mt_who: str | None = None) -> dict[str, Any]:
  if not by_agent:
    return {
      "agents": 0,
      "avg_m1": 0.0,
      "avg_m2": 0.0,
      "avg_zebra_resolved": 0.0,
      "mt_agent": mt_who,
      "mt_m1": None,
      "mt_m2": None,
      "mt_zebra_resolved": None,
    }

  m1_values = [_as_float(row.get("m1_personal")) for row in by_agent.values()]
  m2_values = [_as_float(row.get("m2_zebra")) for row in by_agent.values()]
  resolved_values = [_as_float(row.get("zebra_resolved")) for row in by_agent.values()]

  mt_row = by_agent.get(mt_who or "") if mt_who else None

  return {
    "agents": len(by_agent),
    "avg_m1": fmean(m1_values) if m1_values else 0.0,
    "avg_m2": fmean(m2_values) if m2_values else 0.0,
    "avg_zebra_resolved": fmean(resolved_values) if resolved_values else 0.0,
    "mt_agent": mt_who,
    "mt_m1": None if mt_row is None else _as_float(mt_row.get("m1_personal")),
    "mt_m2": None if mt_row is None else _as_float(mt_row.get("m2_zebra")),
    "mt_zebra_resolved": None if mt_row is None else _as_float(mt_row.get("zebra_resolved")),
  }


def _default_mt_strategy(houses: int) -> dict[str, Any]:
  weights = [1] * houses
  if houses >= 2:
    weights[0] = 2
    weights[1] = 2
  return {
    "p_to": weights,
    "p_house_exch": 10,
    "p_pet_exch": 25,
  }


def compare_mt_effect(
  cfg: dict[str, Any],
  mt_who: str,
  mt_strategy: dict[str, Any],
  out_dir: Path,
  prefix: str = "mt_effect",
) -> Path:
  out_dir.mkdir(parents=True, exist_ok=True)

  base_session_id = f"{prefix}_base"
  mt_session_id = f"{prefix}_mt"

  base_result = run_session(base_session_id, cfg, out_dir)

  mt_cfg = dict(cfg)
  mt_cfg["mt_who"] = mt_who
  mt_cfg["mt_strategy"] = mt_strategy
  mt_result = run_session(mt_session_id, mt_cfg, out_dir)

  base_metrics = _read_final_metrics_ext(Path(base_result["metrics_ext"]))
  mt_metrics = _read_final_metrics_ext(Path(mt_result["metrics_ext"]))

  base_summary = _summary(base_metrics, mt_who)
  mt_summary = _summary(mt_metrics, mt_who)

  report = {
    "cfg": cfg,
    "mt_who": mt_who,
    "mt_strategy": mt_strategy,
    "baseline": {
      "session_id": base_session_id,
      "files": {key: str(value) for key, value in base_result.items()},
      "summary": base_summary,
    },
    "mt_run": {
      "session_id": mt_session_id,
      "files": {key: str(value) for key, value in mt_result.items()},
      "summary": mt_summary,
    },
    "delta": {
      "avg_m1": mt_summary["avg_m1"] - base_summary["avg_m1"],
      "avg_m2": mt_summary["avg_m2"] - base_summary["avg_m2"],
      "avg_zebra_resolved": mt_summary["avg_zebra_resolved"] - base_summary["avg_zebra_resolved"],
      "mt_m1": None
      if base_summary["mt_m1"] is None or mt_summary["mt_m1"] is None
      else mt_summary["mt_m1"] - base_summary["mt_m1"],
      "mt_m2": None
      if base_summary["mt_m2"] is None or mt_summary["mt_m2"] is None
      else mt_summary["mt_m2"] - base_summary["mt_m2"],
      "mt_zebra_resolved": None
      if base_summary["mt_zebra_resolved"] is None or mt_summary["mt_zebra_resolved"] is None
      else mt_summary["mt_zebra_resolved"] - base_summary["mt_zebra_resolved"],
    },
  }

  report_path = out_dir / "mt_effect_report.json"
  report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
  return report_path


def build_arg_parser() -> argparse.ArgumentParser:
  parser = argparse.ArgumentParser(description="Compare baseline and MT strategy effect")
  parser.add_argument("--agents", type=int, default=6)
  parser.add_argument("--houses", type=int, default=6)
  parser.add_argument("--days", type=int, default=50)
  parser.add_argument("--share", type=str, default="meet")
  parser.add_argument("--noise", type=float, default=0.0)
  parser.add_argument("--graph", type=str, default="ring")
  parser.add_argument("--seed", type=int, default=1)
  parser.add_argument("--mt_who", type=str, default="Russian")
  parser.add_argument("--out_dir", type=str, default="data/logs")
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
  }
  mt_strategy = _default_mt_strategy(args.houses)

  report_path = compare_mt_effect(
    cfg=cfg,
    mt_who=args.mt_who,
    mt_strategy=mt_strategy,
    out_dir=Path(args.out_dir),
  )
  print(report_path)


if __name__ == "__main__":
  main()