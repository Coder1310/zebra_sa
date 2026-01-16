import argparse
import csv
import math
from glob import glob
from typing import Dict, List, Tuple

import matplotlib.pyplot as plt


def read_sa(path: str) -> Dict[int, Tuple[float, float]]:
  out: Dict[int, Tuple[float, float]] = {}
  with open(path, "r", newline = "") as f:
    reader = csv.DictReader(f, delimiter = ";")
    for r in reader:
      day = int(r["day"])
      out[day] = (float(r["avg_sa_any"]), float(r["avg_sa_m1"]))
  return out


def mean(xs: List[float]) -> float:
  return sum(xs) / len(xs) if xs else 0.0


def std(xs: List[float]) -> float:
  if len(xs) < 2:
    return 0.0
  m = mean(xs)
  return math.sqrt(sum((x - m) ** 2 for x in xs) / (len(xs) - 1))


def agg(paths: List[str], col: int) -> Tuple[List[int], List[float], List[float]]:
  runs = [read_sa(p) for p in paths]
  days = sorted(runs[0].keys())

  y_mean: List[float] = []
  y_std: List[float] = []

  for d in days:
    vals = [r[d][col] for r in runs]
    y_mean.append(mean(vals))
    y_std.append(std(vals))

  return days, y_mean, y_std


def main() -> None:
  ap = argparse.ArgumentParser()
  ap.add_argument("--none", required = True)
  ap.add_argument("--meet", required = True)
  ap.add_argument("--metric", choices = ["any", "m1"], default = "m1")
  ap.add_argument("--out", required = True)
  args = ap.parse_args()

  col = 0 if args.metric == "any" else 1

  none_paths = sorted(glob(args.none))
  meet_paths = sorted(glob(args.meet))

  x1, y1, e1 = agg(none_paths, col)
  x2, y2, e2 = agg(meet_paths, col)

  plt.errorbar(x1, y1, yerr = e1, marker = "o", linewidth = 1, label = "none")
  plt.errorbar(x2, y2, yerr = e2, marker = "o", linewidth = 1, label = "meet")
  plt.xlabel("day")
  plt.ylabel("avg SA")
  plt.grid(True, alpha = 0.3)
  plt.legend()
  plt.savefig(args.out, dpi = 200, bbox_inches = "tight")
  print(f"saved {args.out}")


if __name__ == "__main__":
  main()
