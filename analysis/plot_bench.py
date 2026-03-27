from __future__ import annotations

import argparse
import csv
from pathlib import Path

import matplotlib.pyplot as plt


def _detect_delimiter(path: Path) -> str:
  with path.open("r", encoding="utf-8") as handle:
    first_line = handle.readline()
  return ";" if first_line.count(";") >= first_line.count(",") else ","


def _to_float(value: str | None, default: float = 0.0) -> float:
  try:
    return float(value or default)
  except Exception:
    return default


def _to_int(value: str | None, default: int = 0) -> int:
  try:
    return int(float(value or default))
  except Exception:
    return default


def _read_bench(path: Path, x_key: str, y_key: str) -> list[tuple[int, float]]:
  delimiter = _detect_delimiter(path)

  grouped: dict[int, list[float]] = {}
  with path.open("r", encoding="utf-8", newline="") as handle:
    reader = csv.DictReader(handle, delimiter=delimiter)
    for row in reader:
      x_value = _to_int(row.get(x_key))
      y_value = _to_float(row.get(y_key))
      grouped.setdefault(x_value, []).append(y_value)

  result: list[tuple[int, float]] = []
  for x_value in sorted(grouped):
    values = grouped[x_value]
    if not values:
      continue
    result.append((x_value, sum(values) / len(values)))
  return result


def plot_bench(
  bench_path: Path,
  out_path: Path,
  x_key: str = "agents",
  y_key: str = "elapsed_sec",
  title: str | None = None,
) -> None:
  series = _read_bench(bench_path, x_key, y_key)
  if not series:
    raise RuntimeError(f"Нет данных для графика в {bench_path}")

  x = [item[0] for item in series]
  y = [item[1] for item in series]

  plt.figure(figsize=(9, 5))
  plt.plot(x, y, marker="o", linewidth=1.5)
  plt.xlabel(x_key)
  plt.ylabel(y_key)
  plt.title(title or f"{y_key} vs {x_key}")
  plt.grid(True, alpha=0.3)
  plt.tight_layout()
  out_path.parent.mkdir(parents=True, exist_ok=True)
  plt.savefig(out_path, dpi=150)
  plt.close()


def build_arg_parser() -> argparse.ArgumentParser:
  parser = argparse.ArgumentParser(description="Plot benchmark curve from bench.csv")
  parser.add_argument("--bench", required=True)
  parser.add_argument("--out", required=True)
  parser.add_argument("--x", default="agents")
  parser.add_argument("--y", default="elapsed_sec")
  parser.add_argument("--title", default=None)
  return parser


def main() -> None:
  args = build_arg_parser().parse_args()
  plot_bench(
    bench_path=Path(args.bench),
    out_path=Path(args.out),
    x_key=args.x,
    y_key=args.y,
    title=args.title,
  )
  print(args.out)


if __name__ == "__main__":
  main()