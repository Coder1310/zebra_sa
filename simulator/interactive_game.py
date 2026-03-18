from __future__ import annotations

import csv
import random
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


@dataclass
class Action:
  kind: str
  dst: Optional[int] = None
  target: Optional[str] = None


def _xml_escape(text: str) -> str:
  return (
    text.replace("&", "&amp;")
    .replace("<", "&lt;")
    .replace(">", "&gt;")
    .replace('"', "&quot;")
    .replace("'", "&apos;")
  )


def _write_xml(path: Path, game_id: str, events: list[dict[str, Any]]) -> None:
  lines = [f'<log session="{game_id}">', "  <events>"]
  for event in events:
    lines.append(f'    <event id="{event["id"]}" day="{event["day"]}" type="{event["type"]}">')
    for index, arg in enumerate(event.get("args", []), start = 1):
      lines.append(f'      <arg i="{index}">{_xml_escape(str(arg))}</arg>')
    lines.append("    </event>")
  lines.append("  </events>")
  lines.append("</log>")
  path.write_text("\n".join(lines), encoding = "utf-8")


class InteractiveGame:
  def __init__(self, game_id: str, cfg: dict[str, Any], humans: dict[int, str], log_dir: Path) -> None:
    self.game_id = game_id
    self.cfg = dict(cfg)
    self.humans = dict(humans)
    self.log_dir = log_dir

    self.houses_n = int(cfg.get("houses", 6))
    self.agents_n = int(cfg.get("agents", 6))
    self.days_total = int(cfg.get("days", 50))
    self.share = str(cfg.get("share", "meet"))
    self.noise = float(cfg.get("noise", 0.0))
    self.graph = str(cfg.get("graph", "ring")).lower()

    seed = cfg.get("seed")
    self.rng = random.Random(seed)

    self.houses = houses_for(self.houses_n)
    self.dist = distances_for(self.graph, self.houses_n)
    self.defaults = default_strategies_for(self.houses_n)
    self.custom_strategies = cfg.get("strategies") if isinstance(cfg.get("strategies"), dict) else {}

    self.day = 1
    self.event_id = 0
    self.events: list[list[str]] = []
    self.xml_events: list[dict[str, Any]] = []
    self.metrics_rows: list[list[str]] = []
    self.pending_actions: dict[str, Action] = {}
    self.pet_offers: dict[str, set[str]] = {}

    self.agents = self._init_agents()
    self._init_knowledge()

    self.finished = False
    self.finished_result: Optional[dict[str, Any]] = None

  def _init_agents(self) -> list[Agent]:
    names = roles_for(self.agents_n, self.houses_n)
    agents: list[Agent] = []
    for index, name in enumerate(names):
      home = (index % self.houses_n) + 1
      if self.agents_n == 6 and self.houses_n == 6:
        pet = PETS_6[index]
        drink = DRINKS_6[index]
        smoke = SMOKES_6[index]
      else:
        pet = f"pet_{index}"
        drink = f"drink_{index}"
        smoke = f"smoke_{index}"
      agents.append(Agent(name = name, home = home, location = home, pet = pet, drink = drink, smoke = smoke))
    return agents

  def _by_name(self) -> dict[str, Agent]:
    return {agent.name: agent for agent in self.agents}

  def _by_home(self) -> dict[int, Agent]:
    return {agent.home: agent for agent in self.agents}

  def _init_knowledge(self) -> None:
    by_home = self._by_home()
    for agent in self.agents:
      self._observe_house(agent, 0, agent.home, by_home)

  def _strategy_for(self, agent: Agent) -> dict[str, Any]:
    base = self.defaults.get(agent.name, {
      "p_to": normalize_probs([1] * self.houses_n),
      "p_house_exch": 0,
      "p_pet_exch": 0,
    })
    override = self.custom_strategies.get(agent.name, {}) if isinstance(self.custom_strategies, dict) else {}

    p_to = override.get("p_to", base.get("p_to", [1] * self.houses_n))
    if not isinstance(p_to, list) or len(p_to) != self.houses_n:
      p_to = base.get("p_to", [1] * self.houses_n)

    return {
      "p_to": normalize_probs([clamp_int(value, 0, 100) for value in p_to]),
      "p_house_exch": clamp_int(override.get("p_house_exch", base.get("p_house_exch", 0)), 0, 100),
      "p_pet_exch": clamp_int(override.get("p_pet_exch", base.get("p_pet_exch", 0)), 0, 100),
    }

  def _neighbor_left(self, house: int) -> int:
    return house - 1 if house > 1 else self.houses_n

  def _neighbor_right(self, house: int) -> int:
    return house + 1 if house < self.houses_n else 1

  def _fact_value(self, house_id: int, category: str, by_home: dict[int, Agent]) -> str:
    if category == "color":
      return self.houses[house_id - 1].color
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

  def _observe_house(self, agent: Agent, day: int, house_id: int, by_home: dict[int, Agent]) -> None:
    resident = by_home[house_id]
    facts = {
      "color": self.houses[house_id - 1].color,
      "nationality": resident.name,
      "pet": resident.pet,
      "drink": resident.drink,
      "smoke": resident.smoke,
    }
    for category, value in facts.items():
      agent.knowledge[(house_id, category)] = KnowledgeEntry(str(value), day)

  def _observe_person(self, agent: Agent, day: int, other: Agent) -> None:
    for category, value in (
      ("nationality", other.name),
      ("pet", other.pet),
      ("drink", other.drink),
      ("smoke", other.smoke),
    ):
      agent.knowledge[(other.home, category)] = KnowledgeEntry(str(value), day)

  def _merge_knowledge(self, group: list[Agent]) -> None:
    merged: dict[tuple[int, str], KnowledgeEntry] = {}
    for agent in group:
      for key, entry in agent.knowledge.items():
        current = merged.get(key)
        if current is None or entry.day > current.day:
          merged[key] = entry
    for agent in group:
      agent.knowledge = dict(merged)

  def _m1(self, agent: Agent) -> float:
    by_home = self._by_home()
    total = len(self.houses) * len(M1_CATEGORIES)
    known = 0
    for house_id in range(1, len(self.houses) + 1):
      for category in M1_CATEGORIES:
        entry = agent.knowledge.get((house_id, category))
        if entry is None:
          continue
        if entry.value == self._fact_value(house_id, category, by_home):
          known += 1
    return known / float(total) if total else 0.0

  def _log_event(self, day: int, kind: str, *args: Any) -> int:
    self.event_id += 1
    row = [str(self.event_id), str(day), str(kind)]
    row.extend("" if arg is None else str(arg) for arg in args)
    self.events.append(row)
    self.xml_events.append({
      "id": self.event_id,
      "day": day,
      "type": kind,
      "args": ["" if arg is None else str(arg) for arg in args],
    })
    return self.event_id

  def _remove_offers_from(self, offerer: str) -> None:
    for target, offerers in list(self.pet_offers.items()):
      if offerer in offerers:
        offerers.discard(offerer)
      if not offerers:
        self.pet_offers.pop(target, None)

  def state(self) -> dict[str, Any]:
    m1 = {agent.name: self._m1(agent) for agent in self.agents}
    by_name = self._by_name()

    pending: list[int] = []
    for uid, role in self.humans.items():
      agent = by_name.get(role)
      if agent is None:
        continue
      if agent.trip.active:
        continue
      if role not in self.pending_actions:
        pending.append(uid)

    return {
      "game_id": self.game_id,
      "day": self.day,
      "days_total": self.days_total,
      "graph": self.graph,
      "pending_user_ids": pending,
      "m1": m1,
    }

  def player_state(self, user_id: int) -> dict[str, Any]:
    role = self.humans.get(int(user_id))
    if not role:
      return {"ok": False, "reason": "not a human in this game"}

    by_name = self._by_name()
    me = by_name.get(role)
    if me is None:
      return {"ok": False, "reason": "role not found"}

    knowledge: list[dict[str, Any]] = []
    for house_id in range(1, self.houses_n + 1):
      row = {"house": house_id}
      for category in KNOWLEDGE_CATEGORIES:
        entry = me.knowledge.get((house_id, category))
        row[category] = entry.value if entry else None
      knowledge.append(row)

    co_located_all: list[str] = []
    for agent in self.agents:
      if agent.name == me.name or agent.trip.active:
        continue
      if agent.location == me.location:
        co_located_all.append(agent.name)

    human_roles = set(self.humans.values())
    co_located_humans = [name for name in co_located_all if name in human_roles]
    offers_in = sorted(name for name in self.pet_offers.get(me.name, set()) if name in human_roles)

    return {
      "ok": True,
      "role": me.name,
      "day": self.day,
      "days_total": self.days_total,
      "home": me.home,
      "location": me.location,
      "left_house": self._neighbor_left(me.location),
      "right_house": self._neighbor_right(me.location),
      "graph": self.graph,
      "trip": {
        "active": me.trip.active,
        "src": me.trip.src,
        "dst": me.trip.dst,
        "remaining": me.trip.remaining,
      },
      "pet": me.pet,
      "drink": me.drink,
      "smoke": me.smoke,
      "m1": self._m1(me),
      "co_located_all": co_located_all,
      "co_located_humans": co_located_humans,
      "pet_offers_in": offers_in,
      "knowledge": knowledge,
    }

  def set_action(self, user_id: int, action: Action) -> dict[str, Any]:
    name = self.humans.get(int(user_id))
    if not name:
      return {"ok": False, "reason": "not a human"}

    me = self._by_name().get(name)
    if me is None:
      return {"ok": False, "reason": "role not found"}

    if action.kind == "pet_decline":
      offerer = (action.target or "").strip()
      if offerer:
        offerers = self.pet_offers.get(name)
        if offerers and offerer in offerers:
          offerers.discard(offerer)
          if not offerers:
            self.pet_offers.pop(name, None)
      return {"ok": True, "pending_user_ids": self.state()["pending_user_ids"]}

    self._remove_offers_from(name)

    if action.kind == "pet_offer":
      target = (action.target or "").strip()
      target_agent = self._by_name().get(target)
      if not target or target_agent is None:
        return {"ok": False, "reason": "bad target"}
      if me.trip.active or target_agent.trip.active:
        return {"ok": False, "reason": "someone is traveling"}
      if me.location != target_agent.location:
        return {"ok": False, "reason": "not in same house"}
      if target not in set(self.humans.values()):
        return {"ok": False, "reason": "target is not a human player"}

      self.pet_offers.setdefault(target, set()).add(name)
      self.pending_actions[name] = Action(kind = "pet_offer", target = target)
      return {"ok": True, "pending_user_ids": self.state()["pending_user_ids"]}

    if action.kind == "pet_accept":
      self.pending_actions[name] = Action(kind = "pet_accept", target = action.target)
      return {"ok": True, "pending_user_ids": self.state()["pending_user_ids"]}

    self.pending_actions[name] = Action(kind = action.kind, dst = action.dst, target = action.target)
    return {"ok": True, "pending_user_ids": self.state()["pending_user_ids"]}

  def _start_trip(self, day: int, agent: Agent, dst: int) -> None:
    if agent.trip.active or dst == agent.location:
      return
    distance = self.dist.get((agent.location, dst))
    if distance is None or distance <= 0:
      return

    agent.trip.active = True
    agent.trip.src = agent.location
    agent.trip.dst = dst
    agent.trip.remaining = int(distance)
    agent.trip.start_event_id = self._log_event(day, "startTrip", agent.name, agent.location, dst)

  def _start_return_trip(self, day: int, agent: Agent) -> None:
    home = agent.home
    if agent.location == home:
      return
    distance = self.dist.get((agent.location, home))
    if distance is None or distance <= 0:
      return
    agent.trip.active = True
    agent.trip.src = agent.location
    agent.trip.dst = home
    agent.trip.remaining = int(distance)
    agent.trip.start_event_id = self._log_event(day, "startTrip", agent.name, agent.location, home)

  def _bot_decision(self, agent: Agent) -> Action:
    strategy = self._strategy_for(agent)

    if self.rng.randint(1, 100) <= int(strategy["p_house_exch"]):
      return Action(kind = "house_exchange")
    if self.rng.randint(1, 100) <= int(strategy["p_pet_exch"]):
      return Action(kind = "pet_exchange")

    candidates = list(range(1, self.houses_n + 1))
    probs = list(strategy["p_to"])

    if self.graph != "full":
      allowed = [agent.location, self._neighbor_left(agent.location), self._neighbor_right(agent.location)]
      candidates = allowed
      probs = [probs[house - 1] for house in candidates]

    dst = pick_by_probs(self.rng, candidates, probs)
    if dst == agent.location:
      return Action(kind = "stay")
    if self.graph != "full":
      if dst == self._neighbor_left(agent.location):
        return Action(kind = "left")
      if dst == self._neighbor_right(agent.location):
        return Action(kind = "right")
      return Action(kind = "stay")
    return Action(kind = "go_to", dst = dst)

  def _groups_for_meetings(self) -> dict[int, list[Agent]]:
    groups: dict[int, list[Agent]] = {}
    for agent in self.agents:
      if agent.trip.active:
        continue
      groups.setdefault(agent.location, []).append(agent)
    return groups

  def _execute_human_pet_swaps(self, day: int, actions: dict[str, Action], by_name: dict[str, Agent]) -> list[tuple[str, str]]:
    swaps: list[tuple[str, str]] = []
    for accepter, action in list(actions.items()):
      if action.kind != "pet_accept":
        continue
      offerer = (action.target or "").strip()
      offer_action = actions.get(offerer)
      if not offerer or offer_action is None or offer_action.kind != "pet_offer":
        continue
      if (offer_action.target or "").strip() != accepter:
        continue

      first = by_name.get(offerer)
      second = by_name.get(accepter)
      if first is None or second is None:
        continue
      if first.trip.active or second.trip.active or first.location != second.location:
        continue

      first.pet, second.pet = second.pet, first.pet
      self._log_event(day, "changePet", 2, first.name, second.name, first.pet, second.pet)
      swaps.append((first.name, second.name))
      self._remove_offers_from(first.name)
      self.pet_offers.pop(second.name, None)
    return swaps

  def _execute_bot_exchange(self, day: int, actor: Agent, kind: str, groups: dict[int, list[Agent]]) -> Optional[tuple[str, str]]:
    if actor.trip.active:
      return None
    group = [member for member in groups.get(actor.location, []) if member.name != actor.name]
    if not group:
      return None

    other = self.rng.choice(group)
    if kind == "house":
      actor.home, other.home = other.home, actor.home
      self._log_event(day, "changeHouse", 2, actor.name, other.name, actor.home, other.home)
      return (actor.name, other.name)

    actor.pet, other.pet = other.pet, actor.pet
    self._log_event(day, "changePet", 2, actor.name, other.name, actor.pet, other.pet)
    return (actor.name, other.name)

  def _apply_noise(self) -> None:
    if self.noise <= 0.0:
      return
    for agent in self.agents:
      if self.rng.random() < self.noise and agent.knowledge:
        key = self.rng.choice(list(agent.knowledge.keys()))
        agent.knowledge.pop(key, None)

  def _collect_reports(
    self,
    day: int,
    know_before: dict[str, set[tuple[int, str]]],
    loc_before: dict[str, int],
    arrived_ok_by_house: dict[int, list[str]],
    met_today: dict[str, list[str]],
    executed_human_swaps: list[tuple[str, str]],
    executed_house_swaps_bot: list[tuple[str, str]],
    executed_pet_swaps_bot: list[tuple[str, str]],
    started_trips: dict[str, int],
  ) -> dict[str, list[str]]:
    reports: dict[str, list[str]] = {}
    total_facts = self.houses_n * len(M1_CATEGORIES)

    for agent in self.agents:
      lines: list[str] = []
      lines.append(f"День {day}/{self.days_total}")
      lines.append(f"Вы: {agent.name}. Ваш дом: {agent.home}. Сейчас: дом {agent.location}.")

      if agent.trip.active:
        lines.append(f"Вы начали путь в дом {agent.trip.dst} (осталось {agent.trip.remaining} дн.).")
      elif agent.name in started_trips:
        lines.append(f"Вы начали путь в дом {started_trips[agent.name]}.")

      visitors = [name for name in arrived_ok_by_house.get(loc_before.get(agent.name, agent.location), []) if name != agent.name]
      if visitors:
        lines.append("К вам сегодня пришли: " + ", ".join(visitors) + ".")

      met = met_today.get(agent.name, [])
      if met:
        lines.append("Сегодня вы встретили: " + ", ".join(met) + ".")

      for first, second in executed_human_swaps:
        if agent.name == first:
          lines.append(f"Обмен питомцами: вы обменялись с {second}.")
        if agent.name == second:
          lines.append(f"Обмен питомцами: вы обменялись с {first}.")

      for first, second in executed_pet_swaps_bot:
        if agent.name == first:
          lines.append(f"Случайный обмен питомцами: с {second}.")
        if agent.name == second:
          lines.append(f"Случайный обмен питомцами: с {first}.")

      for first, second in executed_house_swaps_bot:
        if agent.name == first:
          lines.append(f"Случайный обмен домами: с {second}.")
        if agent.name == second:
          lines.append(f"Случайный обмен домами: с {first}.")

      after_keys = set(agent.knowledge.keys())
      new_count = len(after_keys - know_before.get(agent.name, set()))
      lines.append(f"Новых фактов сегодня: {new_count}. Известно фактов: {len(after_keys)}/{total_facts}.")
      lines.append(f"Текущий M1: {self._m1(agent):.3f}")
      reports[agent.name] = lines

    return reports

  def step_day(self) -> dict[str, Any]:
    if self.finished:
      return dict(self.finished_result or {"done": True, "files": None})
    if self.day > self.days_total:
      return {"done": True, "files": None, "reports": {}}

    day = self.day
    know_before = {agent.name: set(agent.knowledge.keys()) for agent in self.agents}
    loc_before = {agent.name: agent.location for agent in self.agents}

    arrived_ok_by_house: dict[int, list[str]] = {}
    arrived: list[Agent] = []
    for agent in self.agents:
      if not agent.trip.active:
        continue
      agent.trip.remaining -= 1
      if agent.trip.remaining <= 0:
        agent.trip.active = False
        agent.location = agent.trip.dst
        arrived.append(agent)

    by_home = self._by_home()
    for agent in arrived:
      host = by_home.get(agent.location)
      success = 1 if host is not None and (not host.trip.active) and host.location == agent.location else 0
      self._log_event(day, "FinishTrip", agent.trip.start_event_id, agent.name, success)
      if success == 1:
        arrived_ok_by_house.setdefault(agent.location, []).append(agent.name)
      else:
        self._start_return_trip(day, agent)

    actions: dict[str, Action] = {}
    for role, action in self.pending_actions.items():
      actions[role] = action
    for agent in self.agents:
      if agent.name in actions or agent.trip.active:
        continue
      actions[agent.name] = self._bot_decision(agent)

    by_name = self._by_name()
    groups_before_departure = self._groups_for_meetings()

    executed_human_swaps = self._execute_human_pet_swaps(day, actions, by_name)
    executed_house_swaps_bot: list[tuple[str, str]] = []
    executed_pet_swaps_bot: list[tuple[str, str]] = []

    for agent in self.agents:
      if agent.trip.active:
        continue
      action = actions.get(agent.name)
      if action is None:
        continue
      if action.kind == "house_exchange":
        pair = self._execute_bot_exchange(day, agent, "house", groups_before_departure)
        if pair:
          executed_house_swaps_bot.append(pair)
      elif action.kind == "pet_exchange":
        pair = self._execute_bot_exchange(day, agent, "pet", groups_before_departure)
        if pair:
          executed_pet_swaps_bot.append(pair)

    met_today: dict[str, list[str]] = {agent.name: [] for agent in self.agents}
    if self.share == "meet":
      groups = self._groups_for_meetings()
      by_home_after_exchanges = self._by_home()
      for location, group in groups.items():
        if len(group) < 2:
          continue
        for member in group:
          met_today[member.name] = [other.name for other in group if other.name != member.name]
          self._observe_house(member, day, location, by_home_after_exchanges)
        for member in group:
          for other in group:
            if member is other:
              continue
            self._observe_person(member, day, other)
        self._merge_knowledge(group)

    started_trips: dict[str, int] = {}
    for agent in self.agents:
      if agent.trip.active:
        continue
      action = actions.get(agent.name)
      if action is None:
        continue

      if action.kind in ("stay", "pet_offer", "pet_accept", "pet_decline", "house_exchange", "pet_exchange"):
        continue
      if action.kind == "left":
        dst = self._neighbor_left(agent.location)
        self._start_trip(day, agent, dst)
        if agent.trip.active:
          started_trips[agent.name] = dst
        continue
      if action.kind == "right":
        dst = self._neighbor_right(agent.location)
        self._start_trip(day, agent, dst)
        if agent.trip.active:
          started_trips[agent.name] = dst
        continue
      if action.kind == "go_to" and action.dst is not None:
        dst = int(action.dst)
        if self.graph == "full" or dst in (self._neighbor_left(agent.location), self._neighbor_right(agent.location)):
          self._start_trip(day, agent, dst)
          if agent.trip.active:
            started_trips[agent.name] = dst

    self._apply_noise()

    if not self.metrics_rows:
      self.metrics_rows.append(["day"] + [agent.name for agent in self.agents])
    self.metrics_rows.append([str(day)] + [f"{self._m1(agent):.6f}" for agent in self.agents])

    reports = self._collect_reports(
      day,
      know_before,
      loc_before,
      arrived_ok_by_house,
      met_today,
      executed_human_swaps,
      executed_house_swaps_bot,
      executed_pet_swaps_bot,
      started_trips,
    )

    self.pending_actions = {}
    self.pet_offers = {}

    self.day += 1
    done = self.day > self.days_total
    files = self._finalize() if done else None
    leaderboard = sorted(((agent.name, self._m1(agent)) for agent in self.agents), key = lambda item: item[1], reverse = True)

    return {
      "done": done,
      "files": files,
      "day_finished": day,
      "leaderboard": leaderboard,
      "reports": reports,
    }

  def finish_now(self) -> dict[str, Any]:
    if self.finished:
      return dict(self.finished_result or {"done": True, "files": None})

    if not self.metrics_rows:
      self.metrics_rows.append(["day"] + [agent.name for agent in self.agents])

    last_day = max(0, self.day - 1)
    if len(self.metrics_rows) == 1 or self.metrics_rows[-1][0] != str(last_day):
      self.metrics_rows.append([str(last_day)] + [f"{self._m1(agent):.6f}" for agent in self.agents])

    files = self._finalize()
    leaderboard = sorted(((agent.name, self._m1(agent)) for agent in self.agents), key = lambda item: item[1], reverse = True)

    self.finished = True
    self.day = self.days_total + 1
    self.finished_result = {
      "done": True,
      "files": files,
      "day_finished": last_day,
      "leaderboard": leaderboard,
      "reports": {},
    }
    return dict(self.finished_result)

  def _finalize(self) -> dict[str, str]:
    self.log_dir.mkdir(parents = True, exist_ok = True)

    metrics_path = self.log_dir / f"metrics_{self.game_id}.csv"
    events_path = self.log_dir / f"game_{self.game_id}.csv"
    xml_path = self.log_dir / f"game_{self.game_id}.xml"

    with metrics_path.open("w", newline = "", encoding = "utf-8") as handle:
      writer = csv.writer(handle)
      writer.writerows(self.metrics_rows)

    with events_path.open("w", newline = "", encoding = "utf-8") as handle:
      handle.write("eventID;day;event;...\n")
      for row in self.events:
        handle.write(";".join(row) + "\n")

    _write_xml(xml_path, self.game_id, self.xml_events)
    return {"metrics": str(metrics_path), "csv": str(events_path), "xml": str(xml_path)}