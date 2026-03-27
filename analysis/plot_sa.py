from __future__ import annotations

import argparse
import csv
from pathlib import Path

import matplotlib.pyplot as plt


def _detect_delimiter(path: Path) -> str:
  with path.open("r", encoding="utf-8") as handle:
    first_line = handle.readline()
  return ";" if first_line.count(";") >= first_line.count(",") else ","


def _read_series(path: Path, metric: str | None) -> tuple[str, list[tuple[int, float]]]:
  delimiter = _detect_delimiter(path)

  with path.open("r", encoding="utf-8", newline="") as handle:
    reader = csv.DictReader(handle, delimiter=delimiter)
    fieldnames = list(reader.fieldnames or [])
    if not fieldnames:
      raise RuntimeError(f"Пустой файл метрик: {path}")

    if "agent" in fieldnames and "day" in fieldnames:
      metric_name = metric or ("m1_personal" if "m1_personal" in fieldnames else fieldnames[-1])
      by_day: dict[int, list[float]] = {}
      for row in reader:
        try:
          day = int(float(row["day"]))
          value = float(row[metric_name])
        except Exception:
          continue
        by_day.setdefault(day, []).append(value)

      series = [(day, sum(values) / len(values)) for day, values in sorted(by_day.items()) if values]
      return metric_name, series

    if "day" in fieldnames:
      metric_name = metric
      if not metric_name or metric_name not in fieldnames:
        candidates = [name for name in fieldnames if name != "day"]
        if not candidates:
          raise RuntimeError(f"Не найден metric column в {path}")
        metric_name = candidates[0]

      series: list[tuple[int, float]] = []
      for row in reader:
        try:
          day = int(float(row["day"]))
          value = float(row[metric_name])
        except Exception:
          continue
        series.append((day, value))
      return metric_name, series

    raise RuntimeError(f"Неподдерживаемый формат файла: {path}")


def plot_sa(metrics_path: Path, out_path: Path, metric: str | None = None, title: str | None = None) -> None:
  metric_name, series = _read_series(metrics_path, metric)
  if not series:
    raise RuntimeError(f"Нет данных для графика в {metrics_path}")

  x = [day for day, _ in series]
  y = [value for _, value in series]

  plt.figure(figsize=(9, 5))
  plt.plot(x, y, marker="o", linewidth=1.5)
  plt.xlabel("Day")
  plt.ylabel(metric_name)
  plt.title(title or f"{metric_name} over time")
  plt.grid(True, alpha=0.3)
  plt.tight_layout()
  out_path.parent.mkdir(parents=True, exist_ok=True)
  plt.savefig(out_path, dpi=150)
  plt.close()


def build_arg_parser() -> argparse.ArgumentParser:
  parser = argparse.ArgumentParser(description="Plot SA metric from metrics.csv or metrics_ext.csv")
  parser.add_argument("--metrics", required=True)
  parser.add_argument("--out", required=True)
  parser.add_argument("--metric", default=None)
  parser.add_argument("--title", default=None)
  return parser


def main() -> None:
  args = build_arg_parser().parse_args()
  plot_sa(
    metrics_path=Path(args.metrics),
    out_path=Path(args.out),
    metric=args.metric,
    title=args.title,
  )
  print(args.out)


if __name__ == "__main__":
  main()