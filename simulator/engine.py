from __future__ import annotations

import csv
import random
import time
from pathlib import Path
from typing import Any

from core.logic import (
  build_belief_snapshot,
  build_truth_snapshot,
  evaluate_agent_metrics,
  merge_knowledge_group,
  observe_house,
  observe_person,
  random_forget,
  write_xml_log,
)
from core.schema import Agent
from simulator.world import (
  DRINKS_6,
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


def _neighbor_left(houses_n: int, house: int) -> int:
  return house - 1 if house > 1 else houses_n


def _neighbor_right(houses_n: int, house: int) -> int:
  return house + 1 if house < houses_n else 1


def _safe_resident_by_home(agents: list[Agent]) -> dict[int, Agent]:
  by_home: dict[int, Agent] = {}
  for agent in agents:
    if agent.home not in by_home:
      by_home[agent.home] = agent
  return by_home


def run_session(session_id: str, cfg: dict[str, Any], log_dir: Path) -> dict[str, Any]:
  log_dir.mkdir(parents=True, exist_ok=True)

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

    agents.append(
      Agent(
        name=name,
        home=home,
        location=home,
        pet=pet,
        drink=drink,
        smoke=smoke,
      )
    )

  def strategy_for(agent: Agent) -> dict[str, Any]:
    base = defaults.get(
      agent.name,
      {
        "p_to": normalize_probs([1] * houses_n),
        "p_house_exch": 0,
        "p_pet_exch": 0,
      },
    )
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

  resident_map = _safe_resident_by_home(agents)
  for agent in agents:
    observe_house(agent, 0, agent.home, houses, resident_map.get(agent.home))

  event_rows: list[list[str]] = []
  xml_events: list[dict[str, Any]] = []
  event_id = 0

  def log_event(day: int, kind: str, *args: Any) -> int:
    nonlocal event_id
    event_id += 1
    event_rows.append([str(event_id), str(day), str(kind), *["" if arg is None else str(arg) for arg in args]])
    xml_events.append(
      {
        "id": event_id,
        "day": day,
        "type": kind,
        "args": ["" if arg is None else str(arg) for arg in args],
      }
    )
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
  metrics_ext_path = log_dir / f"metrics_ext_{session_id}.csv"
  events_path = log_dir / f"game_{session_id}.csv"
  xml_path = log_dir / f"game_{session_id}.xml"

  with (
    metrics_path.open("w", newline="", encoding="utf-8") as metrics_file,
    metrics_ext_path.open("w", newline="", encoding="utf-8") as metrics_ext_file,
  ):
    metrics_writer = csv.writer(metrics_file)
    metrics_ext_writer = csv.writer(metrics_ext_file)

    metrics_writer.writerow(["day"] + [agent.name for agent in agents])
    metrics_ext_writer.writerow(
      [
        "day",
        "agent",
        "m1_personal",
        "m2_zebra",
        "known_personal_facts",
        "correct_personal_facts",
        "total_personal_facts",
        "zebra_resolved",
        "zebra_owner_pred",
        "zebra_owner_true",
      ]
    )

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

      resident_map = _safe_resident_by_home(agents)
      for agent in arrivals:
        host = resident_map.get(agent.location)
        success = int(host is not None and not host.trip.active and host.location == agent.location)
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
          others = [other for other in group if other.name != agent.name]
          if not others:
            continue

          if rng.randint(1, 100) <= int(strategy["p_pet_exch"]):
            other = rng.choice(others)
            agent.pet, other.pet = other.pet, agent.pet
            log_event(day, "changePet", 2, agent.name, other.name, agent.pet, other.pet)

        if share == "meet":
          resident_map = _safe_resident_by_home(agents)
          for agent in group:
            observe_house(agent, day, location, houses, resident_map.get(location))
          for agent in group:
            for other in group:
              if agent is other:
                continue
              observe_person(agent, day, other)
          merge_knowledge_group(group)

      for agent in agents:
        if not agent.trip.active:
          agent.location = agent.home

      for agent in agents:
        if agent.trip.active:
          continue

        strategy = strategy_for(agent)
        candidates = [
          agent.home,
          _neighbor_left(houses_n, agent.home),
          _neighbor_right(houses_n, agent.home),
        ]
        probs_full = list(strategy["p_to"])
        probs = [probs_full[house - 1] for house in candidates]

        dst = pick_by_probs(rng, candidates, probs)
        if dst != agent.home:
          start_trip(day, agent, dst)

      if noise > 0.0:
        for agent in agents:
          if rng.random() < noise:
            random_forget(agent, rng)

      truth = build_truth_snapshot(houses, agents)
      day_scores: list[str] = []
      for agent in agents:
        belief = build_belief_snapshot(agent.knowledge)
        metric = evaluate_agent_metrics(truth, belief)
        day_scores.append(f"{metric.m1_personal:.6f}")
        metrics_ext_writer.writerow(
          [
            str(day),
            agent.name,
            f"{metric.m1_personal:.6f}",
            str(metric.m2_zebra),
            str(metric.known_personal_facts),
            str(metric.correct_personal_facts),
            str(metric.total_personal_facts),
            str(int(metric.zebra_resolved)),
            "" if metric.zebra_owner_pred is None else metric.zebra_owner_pred,
            "" if metric.zebra_owner_true is None else metric.zebra_owner_true,
          ]
        )
      metrics_writer.writerow([day] + day_scores)

  with events_path.open("w", newline="", encoding="utf-8") as events_file:
    events_file.write("eventID;day;event;...\n")
    for row in event_rows:
      events_file.write(";".join(row) + "\n")

  write_xml_log(xml_path, session_id, xml_events)
  return {
    "csv": events_path,
    "xml": xml_path,
    "metrics": metrics_path,
    "metrics_ext": metrics_ext_path,
    "finished_at": time.time(),
  }
