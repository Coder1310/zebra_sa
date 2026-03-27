from __future__ import annotations

import argparse
import csv
import os
from collections import Counter
from pathlib import Path
from typing import Any

import yaml


DEFAULT_METRIC = "m1_personal"


def _ensure_dir(path: str) -> None:
  Path(path).mkdir(parents=True, exist_ok=True)


def _detect_delimiter(path: str) -> str:
  with open(path, "r", encoding="utf-8") as handle:
    first_line = handle.readline()
  return ";" if first_line.count(";") >= first_line.count(",") else ","


def _to_int(value: Any, default: int = 0) -> int:
  try:
    return int(float(value))
  except (TypeError, ValueError):
    return default


def _to_float(value: Any, default: float | None = None) -> float | None:
  try:
    return float(value)
  except (TypeError, ValueError):
    return default


def _slug(text: str) -> str:
  chars: list[str] = []
  for ch in text:
    if ch.isalnum() or ch in ("_", "-"):
      chars.append(ch)
    elif ch.isspace():
      chars.append("_")
  slug = "".join(chars).strip("_")
  return slug or "item"


def _pick_metric(fieldnames: list[str], requested: str | None) -> str:
  if requested and requested in fieldnames:
    return requested

  for candidate in ("m1_personal", "m2_zebra", "avg_sa_m1", "avg_sa_any", "avg_sa", "final_m1_avg"):
    if candidate in fieldnames:
      return candidate

  if len(fieldnames) >= 2:
    return fieldnames[-1]

  raise RuntimeError(f"cannot choose metric from header: {fieldnames}")


def _read_metrics(
  path: str,
  t_max: int,
  requested_metric: str | None,
) -> tuple[str, dict[str, list[tuple[int, float | None]]]]:
  delimiter = _detect_delimiter(path)
  with open(path, "r", encoding="utf-8", newline="") as handle:
    reader = csv.DictReader(handle, delimiter=delimiter)
    fieldnames = list(reader.fieldnames or [])
    if not fieldnames:
      raise RuntimeError(f"empty metrics file: {path}")

    metric_name = _pick_metric(fieldnames, requested_metric)

    if "agent" in fieldnames and "day" in fieldnames:
      series_by_agent: dict[str, list[tuple[int, float | None]]] = {}
      for row in reader:
        day = _to_int(row.get("day"))
        if day <= 0 or day > t_max:
          continue
        agent = str(row.get("agent") or "agent")
        series_by_agent.setdefault(agent, []).append((day, _to_float(row.get(metric_name))))
      return metric_name, series_by_agent

    if "day" in fieldnames:
      series_by_agent = {name: [] for name in fieldnames if name != "day"}
      for row in reader:
        day = _to_int(row.get("day"))
        if day <= 0 or day > t_max:
          continue
        for agent in series_by_agent:
          series_by_agent[agent].append((day, _to_float(row.get(agent))))
      return metric_name, series_by_agent

    aggregate_name = Path(path).stem
    series: list[tuple[int, float | None]] = []
    for index, row in enumerate(reader, start=1):
      if index > t_max:
        break
      series.append((index, _to_float(row.get(metric_name))))
    return metric_name, {aggregate_name: series}


def _write_series_csv(path: str, metric_name: str, series: list[tuple[int, float | None]]) -> None:
  with open(path, "w", encoding="utf-8", newline="") as handle:
    writer = csv.writer(handle, delimiter=";")
    writer.writerow(["day", metric_name])
    for day, value in series:
      writer.writerow([day, "" if value is None else value])


def _write_series_yaml(path: str, agent: str, metric_name: str, series: list[tuple[int, float | None]]) -> None:
  payload = {
    "agent": agent,
    "metric": metric_name,
    "points": [{"day": day, "value": value} for day, value in series],
  }
  with open(path, "w", encoding="utf-8") as handle:
    yaml.safe_dump(payload, handle, allow_unicode=True, sort_keys=False)


def _write_summary_csv(path: str, metric_name: str, series_by_agent: dict[str, list[tuple[int, float | None]]]) -> None:
  with open(path, "w", encoding="utf-8", newline="") as handle:
    writer = csv.writer(handle, delimiter=";")
    writer.writerow(["agent", "metric", "points", "final", "mean", "max"])
    for agent in sorted(series_by_agent):
      values = [value for _, value in series_by_agent[agent] if value is not None]
      if values:
        final_value = values[-1]
        mean_value = sum(values) / len(values)
        max_value = max(values)
      else:
        final_value = ""
        mean_value = ""
        max_value = ""
      writer.writerow([agent, metric_name, len(values), final_value, mean_value, max_value])


def _write_events_summary_yaml(path: str, events_path: str) -> None:
  delimiter = _detect_delimiter(events_path)
  counter: Counter[str] = Counter()
  days: Counter[int] = Counter()

  with open(events_path, "r", encoding="utf-8", newline="") as handle:
    reader = csv.reader(handle, delimiter=delimiter)
    next(reader, None)
    for row in reader:
      if len(row) < 3:
        continue
      day = _to_int(row[1])
      kind = str(row[2])
      counter[kind] += 1
      days[day] += 1

  payload = {
    "events_total": int(sum(counter.values())),
    "by_type": dict(counter),
    "events_per_day": dict(sorted(days.items())),
  }
  with open(path, "w", encoding="utf-8") as handle:
    yaml.safe_dump(payload, handle, allow_unicode=True, sort_keys=False)


def main() -> None:
  parser = argparse.ArgumentParser()
  parser.add_argument("--metrics", required=True)
  parser.add_argument("--events", default=None)
  parser.add_argument("--metric", default=None)
  parser.add_argument("--t", type=int, default=500)
  parser.add_argument("--out_dir", default="data/logs")
  parser.add_argument("--only_first", type=int, default=0)
  args = parser.parse_args()

  _ensure_dir(args.out_dir)
  metric_name, series_by_agent = _read_metrics(args.metrics, args.t, args.metric)

  agents = sorted(series_by_agent)
  if args.only_first > 0:
    agents = agents[:args.only_first]

  for agent in agents:
    slug = _slug(agent)
    series = series_by_agent[agent]
    _write_series_csv(os.path.join(args.out_dir, f"awareness_{slug}.csv"), metric_name, series)
    _write_series_yaml(os.path.join(args.out_dir, f"awareness_{slug}.yaml"), agent, metric_name, series)

  summary_path = os.path.join(args.out_dir, "metrics_summary.csv")
  _write_summary_csv(summary_path, metric_name, {agent: series_by_agent[agent] for agent in agents})

  if args.events:
    base = os.path.basename(args.events)
    out_yaml = os.path.join(args.out_dir, f"{os.path.splitext(base)[0]}_summary.yaml")
    _write_events_summary_yaml(out_yaml, args.events)

  print(f"ok: awareness files in {args.out_dir}")
  print(f"metric: {metric_name}")
  print(f"summary: {summary_path}")


if __name__ == "__main__":
  main()