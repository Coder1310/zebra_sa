import argparse
import csv
import os
import re
from collections import defaultdict


def _detect_delimiter(path: str) -> str:
  candidates = [",", ";", "\t", "|"]
  with open(path, "r", encoding = "utf-8") as handle:
    for raw_line in handle:
      line = raw_line.strip().lstrip("\ufeff")
      if not line:
        continue
      best = ","
      best_count = 1
      for delimiter in candidates:
        count = len(line.split(delimiter))
        if count > best_count:
          best_count = count
          best = delimiter
      return best if best_count > 1 else ","
  return ","


def _to_int(value: str, default: int = 0) -> int:
  try:
    return int(float(str(value).strip().replace(",", ".")))
  except Exception:
    return default


def _to_float(value: str):
  try:
    return float(str(value).strip().replace(",", "."))
  except Exception:
    return None


def _ensure_dir(path: str) -> None:
  os.makedirs(path, exist_ok = True)


def _slug(name: str) -> str:
  clean = re.sub(r"[^a-zA-Z0-9_-]+", "_", name.strip())
  return clean.strip("_") or "agent"


def _write_awareness_csv(path: str, series: list[tuple[int, float | None]]) -> None:
  with open(path, "w", encoding = "utf-8", newline = "") as handle:
    writer = csv.writer(handle, delimiter = ";")
    writer.writerow(["day", "m1"])
    for day, value in series:
      writer.writerow([day, "" if value is None else f"{value:.6g}"])


def _write_awareness_yaml(path: str, agent: str, series: list[tuple[int, float | None]]) -> None:
  with open(path, "w", encoding = "utf-8") as handle:
    handle.write(f"agent: {agent}\n")
    handle.write("series:\n")
    for day, value in series:
      handle.write(f"  - day: {day}\n")
      handle.write("    m1: null\n" if value is None else f"    m1: {value:.6g}\n")


def _write_events_summary_yaml(path: str, events_csv: str) -> None:
  delimiter = _detect_delimiter(events_csv)
  counts: dict[str, int] = defaultdict(int)
  days_max = 0

  with open(events_csv, "r", encoding = "utf-8", newline = "") as handle:
    reader = csv.DictReader(handle, delimiter = delimiter)
    for row in reader:
      event = (row.get("event") or row.get("Event") or "").strip()
      if event:
        counts[event] += 1
      day = _to_int(row.get("day") or row.get("Day") or "0", 0)
      days_max = max(days_max, day)

  with open(path, "w", encoding = "utf-8") as handle:
    handle.write("events_summary:\n")
    handle.write(f"  days_max: {days_max}\n")
    handle.write("  counts:\n")
    for key in sorted(counts):
      handle.write(f"    {key}: {counts[key]}\n")


def _is_long_format(fieldnames: list[str]) -> bool:
  low = {name.strip().lower() for name in fieldnames}
  return ("agent" in low or "player" in low or "name" in low) and ("m1" in low or "sa" in low)


def main() -> None:
  parser = argparse.ArgumentParser()
  parser.add_argument("--metrics", required = True)
  parser.add_argument("--events", default = None)
  parser.add_argument("--t", type = int, default = 500)
  parser.add_argument("--out_dir", default = "data/logs")
  parser.add_argument("--only_first", type = int, default = 0)
  args = parser.parse_args()

  _ensure_dir(args.out_dir)

  delimiter = _detect_delimiter(args.metrics)
  with open(args.metrics, "r", encoding = "utf-8", newline = "") as handle:
    reader = csv.DictReader(handle, delimiter = delimiter)
    if not reader.fieldnames:
      raise SystemExit("empty metrics header")

    fieldnames = list(reader.fieldnames)
    low_map = {name.strip().lower(): name for name in fieldnames}
    day_col = low_map.get("day")
    if day_col is None:
      raise SystemExit(f"no day column, columns = {fieldnames[:10]}...")

    if _is_long_format(fieldnames):
      agent_col = low_map.get("agent") or low_map.get("player") or low_map.get("name")
      m1_col = low_map.get("m1") or low_map.get("sa")
      by_agent: dict[str, list[tuple[int, float | None]]] = defaultdict(list)

      for row in reader:
        day = _to_int(row.get(day_col, "0"), 0)
        if day <= 0 or day > args.t:
          continue
        agent = (row.get(agent_col, "") or "").strip()
        if not agent:
          continue
        by_agent[agent].append((day, _to_float(row.get(m1_col, ""))))

      agents = sorted(by_agent)
      if args.only_first > 0:
        agents = agents[:args.only_first]

      for agent in agents:
        series = by_agent[agent]
        slug = _slug(agent)
        _write_awareness_csv(os.path.join(args.out_dir, f"awareness_{slug}.csv"), series)
        _write_awareness_yaml(os.path.join(args.out_dir, f"awareness_{slug}.yaml"), agent, series)

    else:
      agent_cols = [name for name in fieldnames if name != day_col]
      if args.only_first > 0:
        agent_cols = agent_cols[:args.only_first]

      series_map: dict[str, list[tuple[int, float | None]]] = {name: [] for name in agent_cols}
      for row in reader:
        day = _to_int(row.get(day_col, "0"), 0)
        if day <= 0 or day > args.t:
          continue
        for agent in agent_cols:
          series_map[agent].append((day, _to_float(row.get(agent, ""))))

      for agent in agent_cols:
        slug = _slug(agent)
        _write_awareness_csv(os.path.join(args.out_dir, f"awareness_{slug}.csv"), series_map[agent])
        _write_awareness_yaml(os.path.join(args.out_dir, f"awareness_{slug}.yaml"), agent, series_map[agent])

  if args.events:
    base = os.path.basename(args.events)
    out_yaml = os.path.join(args.out_dir, f"{os.path.splitext(base)[0]}_summary.yaml")
    _write_events_summary_yaml(out_yaml, args.events)

  print(f"ok: awareness files in {args.out_dir}")


if __name__ == "__main__":
  main()