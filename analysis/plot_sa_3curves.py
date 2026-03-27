from __future__ import annotations

import argparse
import csv
from pathlib import Path

import matplotlib.pyplot as plt


def _detect_delimiter(path: Path) -> str:
  with path.open("r", encoding="utf-8") as handle:
    first_line = handle.readline()
  return ";" if first_line.count(";") >= first_line.count(",") else ","


def _read_metric_series(path: Path, metric_name: str) -> list[tuple[int, float]]:
  delimiter = _detect_delimiter(path)

  with path.open("r", encoding="utf-8", newline="") as handle:
    reader = csv.DictReader(handle, delimiter=delimiter)
    fieldnames = list(reader.fieldnames or [])
    if not fieldnames:
      return []

    if "agent" in fieldnames and "day" in fieldnames:
      if metric_name not in fieldnames:
        return []
      by_day: dict[int, list[float]] = {}
      for row in reader:
        try:
          day = int(float(row["day"]))
          value = float(row[metric_name])
        except Exception:
          continue
        by_day.setdefault(day, []).append(value)
      return [(day, sum(values) / len(values)) for day, values in sorted(by_day.items()) if values]

    if "day" in fieldnames:
      if metric_name not in fieldnames:
        return []
      series: list[tuple[int, float]] = []
      for row in reader:
        try:
          day = int(float(row["day"]))
          value = float(row[metric_name])
        except Exception:
          continue
        series.append((day, value))
      return series

    return []


def plot_three_curves(metrics_path: Path, out_path: Path, title: str | None = None) -> None:
  candidates = ["m1_personal", "m2_zebra", "zebra_resolved"]
  labels: dict[str, str] = {
    "m1_personal": "M1",
    "m2_zebra": "M2",
    "zebra_resolved": "Zebra resolved",
  }

  plt.figure(figsize=(9, 5))
  plotted = 0

  for metric_name in candidates:
    series = _read_metric_series(metrics_path, metric_name)
    if not series:
      continue
    x = [day for day, _ in series]
    y = [value for _, value in series]
    plt.plot(x, y, marker="o", linewidth=1.5, label=labels.get(metric_name, metric_name))
    plotted += 1

  if plotted == 0:
    raise RuntimeError(f"В {metrics_path} нет подходящих колонок для 3-кривой визуализации")

  plt.xlabel("Day")
  plt.ylabel("Value")
  plt.title(title or "SA curves")
  plt.grid(True, alpha=0.3)
  plt.legend()
  plt.tight_layout()
  out_path.parent.mkdir(parents=True, exist_ok=True)
  plt.savefig(out_path, dpi=150)
  plt.close()


def build_arg_parser() -> argparse.ArgumentParser:
  parser = argparse.ArgumentParser(description="Plot 3 SA-related curves from metrics file")
  parser.add_argument("--metrics", required=True)
  parser.add_argument("--out", required=True)
  parser.add_argument("--title", default=None)
  return parser


def main() -> None:
  args = build_arg_parser().parse_args()
  plot_three_curves(
    metrics_path=Path(args.metrics),
    out_path=Path(args.out),
    title=args.title,
  )
  print(args.out)


if __name__ == "__main__":
  main()