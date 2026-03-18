from __future__ import annotations

import csv
import random
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional

from simulator.world import (
  DRINKS_6,
  KNOWLEDGE_CATEGORIES,
  M1_CATEGORIES,
  PETS_6,
  SMOKES_6,
  clamp_int,
  default_strategies_for,
  distances_for,
  houses_for,
  normalize_probs,
  pick_by_probs,
  roles_for,
)


@dataclass
class KnowledgeEntry:
  value: str
  day: int


@dataclass
class Trip:
  active: bool = False
  src: int = 1
  dst: int = 1
  remaining: int = 0
  start_event_id: int = 0


@dataclass
class Agent:
  name: str
  home: int
  location: int
  pet: str
  drink: str
  smoke: str
  trip: Trip = field(default_factory = Trip)
  knowledge: dict[tuple[int, str], KnowledgeEntry] = field(default_factory = dict)


def _xml_escape(text: str) -> str:
  return (
    text.replace("&", "&amp;")
    .replace("<", "&lt;")
    .replace(">", "&gt;")
    .replace('"', "&quot;")
    .replace("'", "&apos;")
  )


def _write_xml(path: Path, session_id: str, events: list[dict[str, Any]]) -> None:
  lines = [f'<log session="{session_id}">', "  <events>"]
  for event in events:
    lines.append(f'    <event id="{event["id"]}" day="{event["day"]}" type="{event["type"]}">')
    for index, arg in enumerate(event.get("args", []), start = 1):
      lines.append(f'      <arg i="{index}">{_xml_escape(str(arg))}</arg>')
    lines.append("    </event>")
  lines.append("  </events>")
  lines.append("</log>")
  path.write_text("\n".join(lines), encoding = "utf-8")


def _fact_value(houses: list[Any], by_home: dict[int, Agent], house_id: int, category: str) -> str:
  if category == "color":
    return houses[house_id - 1].color
  resident = by_home[house_id]
  if category == "nationality":
    return resident.name
  if category == "pet":
    return resident.pet
  if category == "drink":
    return resident.drink
  if category == "smoke":
    return resident.smoke
  return ""


def _observe_house(agent: Agent, day: int, house_id: int, houses: list[Any], by_home: dict[int, Agent]) -> None:
  resident = by_home[house_id]
  facts = {
    "color": houses[house_id - 1].color,
    "nationality": resident.name,
    "pet": resident.pet,
    "drink": resident.drink,
    "smoke": resident.smoke,
  }
  for category, value in facts.items():
    agent.knowledge[(house_id, category)] = KnowledgeEntry(str(value), day)


def _observe_person(agent: Agent, day: int, other: Agent) -> None:
  for category, value in (
    ("nationality", other.name),
    ("pet", other.pet),
    ("drink", other.drink),
    ("smoke", other.smoke),
  ):
    agent.knowledge[(other.home, category)] = KnowledgeEntry(str(value), day)


def _merge_knowledge(group: list[Agent]) -> None:
  merged: dict[tuple[int, str], KnowledgeEntry] = {}
  for agent in group:
    for key, entry in agent.knowledge.items():
      current = merged.get(key)
      if current is None or entry.day > current.day:
        merged[key] = entry
  for agent in group:
    agent.knowledge = dict(merged)


def _m1(agent: Agent, houses: list[Any], by_home: dict[int, Agent]) -> float:
  total = len(houses) * len(M1_CATEGORIES)
  known = 0
  for house_id in range(1, len(houses) + 1):
    for category in M1_CATEGORIES:
      entry = agent.knowledge.get((house_id, category))
      if entry is None:
        continue
      if entry.value == _fact_value(houses, by_home, house_id, category):
        known += 1
  return known / float(total) if total else 0.0


def _neighbor_left(houses_n: int, house: int) -> int:
  return house - 1 if house > 1 else houses_n


def _neighbor_right(houses_n: int, house: int) -> int:
  return house + 1 if house < houses_n else 1


def run_session(session_id: str, cfg: dict[str, Any], log_dir: Path) -> dict[str, Any]:
  log_dir.mkdir(parents = True, exist_ok = True)

  agents_n = int(cfg.get("agents", 6))
  houses_n = int(cfg.get("houses", 6))
  days = int(cfg.get("days", 50))
  share = str(cfg.get("share", "meet"))
  noise = float(cfg.get("noise", 0.0))
  seed = cfg.get("seed")
  graph = str(cfg.get("graph", "ring")).lower()
  sleep_ms_per_day = clamp_int(cfg.get("sleep_ms_per_day", 0), 0, 60000)

  mt_who = cfg.get("mt_who")
  mt_strategy = cfg.get("mt_strategy")
  custom_strategies = cfg.get("strategies") if isinstance(cfg.get("strategies"), dict) else {}

  rng = random.Random(seed)
  houses = houses_for(houses_n)
  dist = distances_for(graph, houses_n)
  defaults = default_strategies_for(houses_n)

  names = roles_for(agents_n, houses_n)
  agents: list[Agent] = []
  for index, name in enumerate(names):
    home = (index % houses_n) + 1
    if agents_n == 6 and houses_n == 6:
      pet = PETS_6[index]
      drink = DRINKS_6[index]
      smoke = SMOKES_6[index]
    else:
      pet = f"pet_{index}"
      drink = f"drink_{index}"
      smoke = f"smoke_{index}"
    agents.append(Agent(name = name, home = home, location = home, pet = pet, drink = drink, smoke = smoke))

  def by_home() -> dict[int, Agent]:
    return {agent.home: agent for agent in agents}

  def strategy_for(agent: Agent) -> dict[str, Any]:
    base = defaults.get(agent.name, {
      "p_to": normalize_probs([1] * houses_n),
      "p_house_exch": 0,
      "p_pet_exch": 0,
    })
    override = custom_strategies.get(agent.name, {}) if isinstance(custom_strategies, dict) else {}
    if mt_who is not None and mt_strategy is not None and agent.name == mt_who:
      try:
        override = dict(override)
        override.update(dict(mt_strategy))
      except Exception:
        pass

    p_to = override.get("p_to", base.get("p_to", [1] * houses_n))
    if not isinstance(p_to, list) or len(p_to) != houses_n:
      p_to = base.get("p_to", [1] * houses_n)

    return {
      "p_to": normalize_probs([clamp_int(value, 0, 100) for value in p_to]),
      "p_house_exch": clamp_int(override.get("p_house_exch", base.get("p_house_exch", 0)), 0, 100),
      "p_pet_exch": clamp_int(override.get("p_pet_exch", base.get("p_pet_exch", 0)), 0, 100),
    }

  for agent in agents:
    _observe_house(agent, 0, agent.home, houses, by_home())

  event_rows: list[list[str]] = []
  xml_events: list[dict[str, Any]] = []
  event_id = 0

  def log_event(day: int, kind: str, *args: Any) -> int:
    nonlocal event_id
    event_id += 1
    row = [str(event_id), str(day), str(kind)]
    row.extend("" if arg is None else str(arg) for arg in args)
    event_rows.append(row)
    xml_events.append({
      "id": event_id,
      "day": day,
      "type": kind,
      "args": ["" if arg is None else str(arg) for arg in args],
    })
    return event_id

  def start_trip(day: int, agent: Agent, dst: int) -> None:
    if agent.trip.active or dst == agent.location:
      return
    distance = dist.get((agent.location, dst))
    if distance is None or distance <= 0:
      return
    agent.trip.active = True
    agent.trip.src = agent.location
    agent.trip.dst = dst
    agent.trip.remaining = int(distance)
    agent.trip.start_event_id = log_event(day, "startTrip", agent.name, agent.location, dst)

  def start_return_trip(day: int, agent: Agent) -> None:
    if agent.location == agent.home:
      return
    distance = dist.get((agent.location, agent.home))
    if distance is None or distance <= 0:
      return
    agent.trip.active = True
    agent.trip.src = agent.location
    agent.trip.dst = agent.home
    agent.trip.remaining = int(distance)
    agent.trip.start_event_id = log_event(day, "startTrip", agent.name, agent.location, agent.home)

  metrics_path = log_dir / f"metrics_{session_id}.csv"
  events_path = log_dir / f"game_{session_id}.csv"
  xml_path = log_dir / f"game_{session_id}.xml"

  with metrics_path.open("w", newline = "", encoding = "utf-8") as metrics_file:
    metrics_writer = csv.writer(metrics_file)
    metrics_writer.writerow(["day"] + [agent.name for agent in agents])

    for day in range(1, days + 1):
      if sleep_ms_per_day > 0:
        time.sleep(sleep_ms_per_day / 1000.0)

      arrivals: list[Agent] = []
      for agent in agents:
        if not agent.trip.active:
          continue
        agent.trip.remaining -= 1
        if agent.trip.remaining <= 0:
          agent.trip.active = False
          agent.location = agent.trip.dst
          arrivals.append(agent)

      home_map = by_home()
      for agent in arrivals:
        host = home_map.get(agent.location)
        success = 1 if host is not None and (not host.trip.active) and host.location == agent.location else 0
        log_event(day, "FinishTrip", agent.trip.start_event_id, agent.name, success)
        if success == 0:
          start_return_trip(day, agent)

      groups: dict[int, list[Agent]] = {}
      for agent in agents:
        if agent.trip.active:
          continue
        groups.setdefault(agent.location, []).append(agent)

      for location, group in groups.items():
        if len(group) < 2:
          continue

        for agent in group:
          strategy = strategy_for(agent)
          if rng.randint(1, 100) <= int(strategy["p_house_exch"]):
            others = [other for other in group if other.name != agent.name]
            if others:
              other = rng.choice(others)
              agent.home, other.home = other.home, agent.home
              log_event(day, "changeHouse", 2, agent.name, other.name, agent.home, other.home)

          if rng.randint(1, 100) <= int(strategy["p_pet_exch"]):
            others = [other for other in group if other.name != agent.name]
            if others:
              other = rng.choice(others)
              agent.pet, other.pet = other.pet, agent.pet
              log_event(day, "changePet", 2, agent.name, other.name, agent.pet, other.pet)

        if share == "meet":
          updated_home_map = by_home()
          for agent in group:
            _observe_house(agent, day, location, houses, updated_home_map)
          for agent in group:
            for other in group:
              if agent is other:
                continue
              _observe_person(agent, day, other)
          _merge_knowledge(group)

      for agent in agents:
        if agent.trip.active:
          continue

        strategy = strategy_for(agent)
        candidates = list(range(1, houses_n + 1))
        probs = list(strategy["p_to"])

        if graph != "full":
          allowed = [agent.location, _neighbor_left(houses_n, agent.location), _neighbor_right(houses_n, agent.location)]
          candidates = allowed
          probs = [probs[house - 1] for house in candidates]

        dst = pick_by_probs(rng, candidates, probs)
        if dst == agent.location:
          continue
        start_trip(day, agent, dst)

      if noise > 0.0:
        for agent in agents:
          if rng.random() < noise and agent.knowledge:
            key = rng.choice(list(agent.knowledge.keys()))
            agent.knowledge.pop(key, None)

      current_home_map = by_home()
      metrics_writer.writerow([day] + [f"{_m1(agent, houses, current_home_map):.6f}" for agent in agents])

  with events_path.open("w", newline = "", encoding = "utf-8") as events_file:
    events_file.write("eventID;day;event;...\n")
    for row in event_rows:
      events_file.write(";".join(row) + "\n")

  _write_xml(xml_path, session_id, xml_events)
  return {
    "csv": events_path,
    "xml": xml_path,
    "metrics": metrics_path,
    "finished_at": time.time(),
  }