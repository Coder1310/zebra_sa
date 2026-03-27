from __future__ import annotations

import argparse
import csv
import json
import os
import random
import time
from dataclasses import dataclass
from glob import glob
from typing import Any

import requests


@dataclass(frozen=True)
class Strategy:
  p_to: list[int]
  p_house_exch: int
  p_pet_exch: int

  def as_dict(self) -> dict[str, Any]:
    return {
      "p_to": list(self.p_to),
      "p_house_exch": int(self.p_house_exch),
      "p_pet_exch": int(self.p_pet_exch),
    }


@dataclass(frozen=True)
class TrialResult:
  score: float
  session_ids: list[str]
  metrics_path: str | None
  metrics_ext_path: str | None


def _clamp_int(value: Any, lo: int, hi: int) -> int:
  try:
    value = int(value)
  except Exception:
    return lo
  if value < lo:
    return lo
  if value > hi:
    return hi
  return value


def _normalize_int_weights(values: list[int]) -> list[int]:
  if not values:
    return []
  clipped = [max(0, int(v)) for v in values]
  total = sum(clipped)
  if total <= 0:
    out = [0] * len(clipped)
    out[0] = 100
    return out

  scaled = [int(round(100 * value / total)) for value in clipped]
  diff = 100 - sum(scaled)
  if diff != 0:
    pivot = max(range(len(scaled)), key=lambda idx: clipped[idx])
    scaled[pivot] += diff
  return scaled


def _sample_strategy(houses: int, rng: random.Random) -> Strategy:
  weights = [rng.randint(0, 100) for _ in range(houses)]
  p_to = _normalize_int_weights(weights)
  return Strategy(
    p_to=p_to,
    p_house_exch=rng.randint(0, 100),
    p_pet_exch=rng.randint(0, 100),
  )


def _mutate_strategy(base: Strategy, rng: random.Random) -> Strategy:
  weights = [max(0, value + rng.randint(-20, 20)) for value in base.p_to]
  if not any(weights):
    weights[rng.randrange(len(weights))] = 100
  return Strategy(
    p_to=_normalize_int_weights(weights),
    p_house_exch=_clamp_int(base.p_house_exch + rng.randint(-15, 15), 0, 100),
    p_pet_exch=_clamp_int(base.p_pet_exch + rng.randint(-15, 15), 0, 100),
  )


def _list_files(logs_dir: str, prefixes: list[str]) -> list[str]:
  files: list[str] = []
  for prefix in prefixes:
    files.extend(glob(os.path.join(logs_dir, f"{prefix}*.csv")))
  files = sorted(set(files), key=lambda path: os.path.getmtime(path) if os.path.exists(path) else 0.0)
  return files


def _detect_delimiter(path: str) -> str:
  with open(path, "r", encoding="utf-8") as handle:
    head = handle.readline()
  return ";" if head.count(";") >= head.count(",") else ","


def _read_metric_series(path: str, who: str, metric: str) -> tuple[list[int], list[float]]:
  delimiter = _detect_delimiter(path)
  days: list[int] = []
  values: list[float] = []

  with open(path, "r", encoding="utf-8", newline="") as handle:
    reader = csv.DictReader(handle, delimiter=delimiter)
    fieldnames = list(reader.fieldnames or [])
    lowered = {name.strip().lower(): name for name in fieldnames}
    day_col = lowered.get("day")
    if day_col is None:
      raise RuntimeError(f"no day column in {path}")

    is_long = "agent" in lowered
    if is_long:
      agent_col = lowered["agent"]
      if metric not in fieldnames:
        raise RuntimeError(f"metric '{metric}' not found in {path}: {fieldnames}")
      found_agent = False
      for row in reader:
        agent = str(row.get(agent_col, "")).strip()
        if agent != who:
          continue
        found_agent = True
        days.append(int(float(row[day_col])))
        values.append(float(row[metric]))
      if not found_agent:
        raise RuntimeError(f"cannot find agent '{who}' in {path}")
      return days, values

    if who not in fieldnames:
      raise RuntimeError(f"cannot find column '{who}' in {path}")
    for row in reader:
      days.append(int(float(row[day_col])))
      values.append(float(row[who]))
    return days, values


def _score(days: list[int], values: list[float], mode: str, tail: int, threshold: float) -> float:
  if not values:
    return 0.0
  if mode == "final":
    return float(values[-1])
  if mode == "mean_tail":
    k = min(tail, len(values))
    return float(sum(values[-k:]) / k)
  if mode == "auc":
    return float(sum(values) / len(values))
  if mode == "time_to_threshold":
    for index, value in enumerate(values, start=1):
      if value >= threshold:
        return 1.0 - (index - 1) / max(1, len(values))
    return 0.0
  raise ValueError(mode)


def _create_session(api_base: str, cfg: dict[str, Any]) -> str:
  response = requests.post(f"{api_base}/session/create", json=cfg, timeout=60)
  response.raise_for_status()

  try:
    data = response.json()
  except json.JSONDecodeError:
    text = response.text.strip().strip('"').strip("'")
    if not text:
      raise RuntimeError(f"cannot parse session id from {response.text!r}")
    return text

  for key in ("session_id", "session", "sid", "id"):
    value = data.get(key)
    if value:
      return str(value)
  raise RuntimeError(f"cannot parse session id from {data}")


def _find_new_file(logs_dir: str, sid: str, prefixes: list[str], started_at: float, seen: set[str]) -> str | None:
  candidates: list[str] = []
  for path in _list_files(logs_dir, prefixes):
    if path in seen:
      continue
    try:
      mtime = os.path.getmtime(path)
    except OSError:
      continue
    if mtime < started_at - 0.2:
      continue
    candidates.append(path)

  if not candidates:
    return None

  sid_matches = [path for path in candidates if sid in os.path.basename(path)]
  if sid_matches:
    return max(sid_matches, key=os.path.getmtime)
  return max(candidates, key=os.path.getmtime)


def _extract_paths(info: dict[str, Any]) -> tuple[str | None, str | None, str | None, str | None, str | None]:
  def _clean(value: Any) -> str | None:
    if not isinstance(value, str):
      return None
    value = value.strip()
    return value or None

  return (
    _clean(info.get("status")),
    _clean(info.get("metrics")),
    _clean(info.get("metrics_ext")),
    _clean(info.get("csv")),
    _clean(info.get("xml")),
  )


def _wait_run_done(api_base: str, sid: str, logs_dir: str, wait_sec: float) -> dict[str, str | None]:
  started_at = time.time()
  seen_metrics = set(_list_files(logs_dir, ["metrics_", "metrics-", "metrics"]))
  seen_metrics_ext = set(_list_files(logs_dir, ["metrics_ext_", "metrics_ext-"]))

  last_info: dict[str, Any] | None = None
  while time.time() - started_at < wait_sec:
    try:
      response = requests.post(f"{api_base}/session/{sid}/run", timeout=60)
      response.raise_for_status()
      data = response.json()
      last_info = data if isinstance(data, dict) else {}
    except (requests.RequestException, json.JSONDecodeError):
      data = {}

    status, metrics_path, metrics_ext_path, csv_path, xml_path = _extract_paths(data)

    if metrics_path and os.path.exists(metrics_path):
      return {
        "metrics": metrics_path,
        "metrics_ext": metrics_ext_path if metrics_ext_path and os.path.exists(metrics_ext_path) else metrics_ext_path,
        "csv": csv_path,
        "xml": xml_path,
      }

    discovered_metrics = _find_new_file(logs_dir, sid, ["metrics_", "metrics-", "metrics"], started_at, seen_metrics)
    discovered_metrics_ext = _find_new_file(logs_dir, sid, ["metrics_ext_", "metrics_ext-"], started_at, seen_metrics_ext)

    if status in {"done", "ok", "finished", "complete"} and (metrics_path or discovered_metrics):
      return {
        "metrics": metrics_path or discovered_metrics,
        "metrics_ext": metrics_ext_path or discovered_metrics_ext,
        "csv": csv_path,
        "xml": xml_path,
      }

    if discovered_metrics or discovered_metrics_ext:
      return {
        "metrics": metrics_path or discovered_metrics,
        "metrics_ext": metrics_ext_path or discovered_metrics_ext,
        "csv": csv_path,
        "xml": xml_path,
      }

    time.sleep(0.2)

  raise RuntimeError(
    "run timeout\n"
    f"sid={sid}\n"
    f"last_info={last_info}\n"
    f"metrics_tail={_list_files(logs_dir, ['metrics_', 'metrics-', 'metrics'])[-5:]}\n"
    f"metrics_ext_tail={_list_files(logs_dir, ['metrics_ext_', 'metrics_ext-'])[-5:]}"
  )


def _choose_metric_file(paths: dict[str, str | None], metric: str) -> tuple[str, str]:
  metrics_ext = paths.get("metrics_ext")
  metrics = paths.get("metrics")

  if metric == "auto":
    if metrics_ext and os.path.exists(metrics_ext):
      return metrics_ext, "m1_personal"
    if metrics and os.path.exists(metrics):
      return metrics, "m1"
    raise RuntimeError("no metrics files found")

  if metric in {"m1_personal", "m2_zebra", "known_personal_facts", "correct_personal_facts"}:
    if not metrics_ext or not os.path.exists(metrics_ext):
      raise RuntimeError("metrics_ext file is required for the selected metric")
    return metrics_ext, metric

  if metric == "m1":
    if metrics and os.path.exists(metrics):
      return metrics, metric
    if metrics_ext and os.path.exists(metrics_ext):
      return metrics_ext, "m1_personal"
    raise RuntimeError("no compatible metrics file found")

  raise RuntimeError(f"unsupported metric '{metric}'")


def _write_yaml(path: str, data: dict[str, Any]) -> None:
  lines: list[str] = []
  for key, value in data.items():
    if isinstance(value, dict):
      lines.append(f"{key}:")
      for inner_key, inner_value in value.items():
        lines.append(f"  {inner_key}: {inner_value}")
    elif isinstance(value, list):
      lines.append(f"{key}:")
      for item in value:
        lines.append(f"  - {item}")
    else:
      lines.append(f"{key}: {value}")
  with open(path, "w", encoding="utf-8") as handle:
    handle.write("\n".join(lines) + "\n")


def main() -> None:
  parser = argparse.ArgumentParser()
  parser.add_argument("--api", default="http://127.0.0.1:8000")
  parser.add_argument("--agents", type=int, default=1000)
  parser.add_argument("--houses", type=int, default=6)
  parser.add_argument("--days", type=int, default=200)
  parser.add_argument("--share", default="meet", choices=["none", "meet"])
  parser.add_argument("--noise", type=float, default=0.2)
  parser.add_argument("--graph", default="ring", choices=["ring", "full"])
  parser.add_argument("--who", default="a0")
  parser.add_argument("--iters", type=int, default=10)
  parser.add_argument("--seeds", default="1,2,3")
  parser.add_argument("--metric", default="auto", choices=["auto", "m1", "m1_personal", "m2_zebra", "known_personal_facts", "correct_personal_facts"])
  parser.add_argument("--score", default="final", choices=["final", "mean_tail", "auc", "time_to_threshold"])
  parser.add_argument("--tail", type=int, default=20)
  parser.add_argument("--threshold", type=float, default=0.8)
  parser.add_argument("--wait", type=float, default=600.0)
  parser.add_argument("--out_dir", default="data/logs")
  parser.add_argument("--logs_dir", default="data/logs")
  parser.add_argument("--rng_seed", type=int, default=42)
  args = parser.parse_args()

  os.makedirs(args.out_dir, exist_ok=True)
  trials_csv = os.path.join(args.out_dir, "mt_trials.csv")
  best_yaml = os.path.join(args.out_dir, "mt_best.yaml")
  compare_csv = os.path.join(args.out_dir, "mt_compare.csv")
  compare_png = os.path.join(args.out_dir, "mt_compare.png")

  seeds = [int(chunk) for chunk in args.seeds.split(",") if chunk.strip()]
  rng = random.Random(args.rng_seed)

  def evaluate(strategy: Strategy | None) -> TrialResult:
    scores: list[float] = []
    session_ids: list[str] = []
    last_metrics_path: str | None = None
    last_metrics_ext_path: str | None = None

    for seed in seeds:
      cfg: dict[str, Any] = {
        "agents": args.agents,
        "houses": args.houses,
        "days": args.days,
        "share": args.share,
        "noise": args.noise,
        "seed": seed,
        "graph": args.graph,
      }
      if strategy is not None:
        cfg["mt_who"] = args.who
        cfg["mt_strategy"] = strategy.as_dict()

      sid = _create_session(args.api, cfg)
      paths = _wait_run_done(args.api, sid, args.logs_dir, args.wait)
      metric_path, metric_name = _choose_metric_file(paths, args.metric)
      days, values = _read_metric_series(metric_path, args.who, metric_name)
      scores.append(_score(days, values, args.score, args.tail, args.threshold))
      session_ids.append(sid)
      last_metrics_path = paths.get("metrics")
      last_metrics_ext_path = paths.get("metrics_ext")

    return TrialResult(
      score=float(sum(scores) / len(scores)),
      session_ids=session_ids,
      metrics_path=last_metrics_path,
      metrics_ext_path=last_metrics_ext_path,
    )

  baseline_result = evaluate(None)
  best_strategy = _sample_strategy(args.houses, rng)
  best_result = evaluate(best_strategy)

  with open(trials_csv, "w", encoding="utf-8", newline="") as handle:
    writer = csv.writer(handle)
    writer.writerow([
      "kind",
      "score",
      "session_ids",
      "metrics",
      "metrics_ext",
      "p_to",
      "p_house_exch",
      "p_pet_exch",
    ])
    writer.writerow([
      "baseline",
      baseline_result.score,
      "|".join(baseline_result.session_ids),
      baseline_result.metrics_path or "",
      baseline_result.metrics_ext_path or "",
      "",
      "",
      "",
    ])
    writer.writerow([
      "trial0",
      best_result.score,
      "|".join(best_result.session_ids),
      best_result.metrics_path or "",
      best_result.metrics_ext_path or "",
      "|".join(str(value) for value in best_strategy.p_to),
      best_strategy.p_house_exch,
      best_strategy.p_pet_exch,
    ])

  for trial_index in range(1, args.iters + 1):
    if rng.random() < 0.3:
      candidate = _sample_strategy(args.houses, rng)
    else:
      candidate = _mutate_strategy(best_strategy, rng)

    candidate_result = evaluate(candidate)
    with open(trials_csv, "a", encoding="utf-8", newline="") as handle:
      writer = csv.writer(handle)
      writer.writerow([
        f"trial{trial_index}",
        candidate_result.score,
        "|".join(candidate_result.session_ids),
        candidate_result.metrics_path or "",
        candidate_result.metrics_ext_path or "",
        "|".join(str(value) for value in candidate.p_to),
        candidate.p_house_exch,
        candidate.p_pet_exch,
      ])

    if candidate_result.score > best_result.score:
      best_strategy = candidate
      best_result = candidate_result
      print(f"new best score={best_result.score:.4f} strategy={best_strategy.as_dict()}")

  _write_yaml(
    best_yaml,
    {
      "who": args.who,
      "metric": args.metric,
      "score_mode": args.score,
      "baseline_score": baseline_result.score,
      "best_score": best_result.score,
      "best_strategy": best_strategy.as_dict(),
      "baseline_session_ids": "|".join(baseline_result.session_ids),
      "best_session_ids": "|".join(best_result.session_ids),
      "baseline_metrics": baseline_result.metrics_path or "",
      "baseline_metrics_ext": baseline_result.metrics_ext_path or "",
      "best_metrics": best_result.metrics_path or "",
      "best_metrics_ext": best_result.metrics_ext_path or "",
    },
  )

  baseline_metric_path, baseline_metric_name = _choose_metric_file(
    {"metrics": baseline_result.metrics_path, "metrics_ext": baseline_result.metrics_ext_path},
    args.metric,
  )
  best_metric_path, best_metric_name = _choose_metric_file(
    {"metrics": best_result.metrics_path, "metrics_ext": best_result.metrics_ext_path},
    args.metric,
  )
  baseline_days, baseline_values = _read_metric_series(baseline_metric_path, args.who, baseline_metric_name)
  best_days, best_values = _read_metric_series(best_metric_path, args.who, best_metric_name)

  with open(compare_csv, "w", encoding="utf-8", newline="") as handle:
    writer = csv.writer(handle)
    writer.writerow(["day", "baseline", "best"])
    max_len = max(len(baseline_days), len(best_days))
    for index in range(max_len):
      writer.writerow([
        baseline_days[index] if index < len(baseline_days) else best_days[index],
        baseline_values[index] if index < len(baseline_values) else "",
        best_values[index] if index < len(best_values) else "",
      ])

  try:
    import matplotlib.pyplot as plt

    plt.figure()
    plt.plot(baseline_days, baseline_values, label="baseline")
    plt.plot(best_days, best_values, label="mt_best")
    plt.xlabel("day")
    plt.ylabel(best_metric_name)
    plt.legend()
    plt.tight_layout()
    plt.savefig(compare_png, dpi=200)
    print(f"saved {compare_png}")
  except Exception as error:
    print(f"skip plot: {error}")

  print(f"saved {best_yaml}")
  print(f"saved {trials_csv}")
  print(f"saved {compare_csv}")


if __name__ == "__main__":
  main()
