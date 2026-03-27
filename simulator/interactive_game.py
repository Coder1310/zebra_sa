from __future__ import annotations

import csv
import random
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

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
  trip: Trip = field(default_factory=Trip)
  knowledge: dict[tuple[int, str], KnowledgeEntry] = field(default_factory=dict)


@dataclass
class Action:
  kind: str
  dst: int | None = None
  target: str | None = None


@dataclass(frozen=True)
class TruthSnapshot:
  house_color: dict[int, str]
  person_home: dict[str, int]
  person_pet: dict[str, str]
  person_drink: dict[str, str]
  person_smoke: dict[str, str]
  person_location: dict[str, int]


@dataclass
class BeliefSnapshot:
  house_color: dict[int, str] = field(default_factory=dict)
  house_resident: dict[int, str] = field(default_factory=dict)
  person_home: dict[str, int] = field(default_factory=dict)
  person_pet: dict[str, str] = field(default_factory=dict)
  person_drink: dict[str, str] = field(default_factory=dict)
  person_smoke: dict[str, str] = field(default_factory=dict)


@dataclass(frozen=True)
class AgentMetrics:
  known_personal_facts: int
  correct_personal_facts: int
  total_personal_facts: int
  m1_personal: float
  zebra_owner_true: str | None
  zebra_owner_pred: str | None
  zebra_resolved: bool
  m2_zebra: int


def _write_xml(path: Path, game_id: str, events: list[dict[str, Any]]) -> None:
  root = ET.Element("log", session=game_id)
  events_node = ET.SubElement(root, "events")

  for event in events:
    event_node = ET.SubElement(
      events_node,
      "event",
      id=str(event["id"]),
      day=str(event["day"]),
      type=str(event["type"]),
    )
    for index, arg in enumerate(event.get("args", []), start=1):
      arg_node = ET.SubElement(event_node, "arg", i=str(index))
      arg_node.text = "" if arg is None else str(arg)

  tree = ET.ElementTree(root)
  tree.write(path, encoding="utf-8", xml_declaration=False)


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
    self.metrics_ext_rows: list[list[str]] = [[
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
    ]]
    self.pending_actions: dict[str, Action] = {}
    self.pet_offers: dict[str, set[str]] = {}
    self.bot_pet_offers: dict[str, set[str]] = {}
    self.house_offers: dict[str, set[str]] = {}
    self.bot_house_offers: dict[str, set[str]] = {}

    self.agents = self._init_agents()
    self._init_knowledge()

    self.finished = False
    self.finished_result: dict[str, Any] | None = None

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
    base = self.defaults.get(
      agent.name,
      {
        "p_to": normalize_probs([1] * self.houses_n),
        "p_house_exch": 0,
        "p_pet_exch": 0,
      },
    )
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
    correct = 0

    for house_id in range(1, len(self.houses) + 1):
      for category in M1_CATEGORIES:
        entry = agent.knowledge.get((house_id, category))
        if entry is None:
          continue
        if entry.value == self._fact_value(house_id, category, by_home):
          correct += 1

    return correct / float(total) if total else 0.0

  def _build_truth_snapshot(self) -> TruthSnapshot:
    house_color: dict[int, str] = {}
    person_home: dict[str, int] = {}
    person_pet: dict[str, str] = {}
    person_drink: dict[str, str] = {}
    person_smoke: dict[str, str] = {}
    person_location: dict[str, int] = {}

    for house in self.houses:
      house_color[int(house.house_id)] = str(house.color)

    for agent in self.agents:
      person_home[agent.name] = int(agent.home)
      person_pet[agent.name] = str(agent.pet)
      person_drink[agent.name] = str(agent.drink)
      person_smoke[agent.name] = str(agent.smoke)
      person_location[agent.name] = int(agent.location)

    return TruthSnapshot(
      house_color=house_color,
      person_home=person_home,
      person_pet=person_pet,
      person_drink=person_drink,
      person_smoke=person_smoke,
      person_location=person_location,
    )

  def _build_belief_snapshot(self, knowledge: dict[tuple[int, str], KnowledgeEntry]) -> BeliefSnapshot:
    belief = BeliefSnapshot()
    grouped: dict[int, dict[str, str]] = {}

    for (house_id, category), entry in knowledge.items():
      house_id = int(house_id)
      category = str(category)
      value = str(entry.value)

      grouped.setdefault(house_id, {})[category] = value

      if category == "color":
        belief.house_color[house_id] = value
      elif category == "nationality":
        belief.house_resident[house_id] = value
        belief.person_home[value] = house_id

    for house_id, row in grouped.items():
      person = row.get("nationality")
      if not person:
        continue

      if "pet" in row:
        belief.person_pet[person] = row["pet"]
      if "drink" in row:
        belief.person_drink[person] = row["drink"]
      if "smoke" in row:
        belief.person_smoke[person] = row["smoke"]

    return belief

  def _true_zebra_owner(self, truth: TruthSnapshot) -> str | None:
    for person, pet in truth.person_pet.items():
      if pet == "Zebra":
        return person
    return None

  def _predicted_zebra_owner(self, belief: BeliefSnapshot) -> str | None:
    owners = [person for person, pet in belief.person_pet.items() if pet == "Zebra"]
    if len(owners) == 1:
      return owners[0]
    return None

  def _evaluate_agent_metrics(self, truth: TruthSnapshot, belief: BeliefSnapshot) -> AgentMetrics:
    people = sorted(truth.person_home)
    known = 0
    correct = 0
    total = len(people) * 4

    for person in people:
      if person in belief.person_home:
        known += 1
        if belief.person_home[person] == truth.person_home[person]:
          correct += 1

      if person in belief.person_pet:
        known += 1
        if belief.person_pet[person] == truth.person_pet[person]:
          correct += 1

      if person in belief.person_drink:
        known += 1
        if belief.person_drink[person] == truth.person_drink[person]:
          correct += 1

      if person in belief.person_smoke:
        known += 1
        if belief.person_smoke[person] == truth.person_smoke[person]:
          correct += 1

    zebra_owner_true = self._true_zebra_owner(truth)
    zebra_owner_pred = self._predicted_zebra_owner(belief)
    zebra_resolved = zebra_owner_pred is not None
    m2_zebra = int(zebra_owner_true is not None and zebra_owner_pred == zebra_owner_true)

    return AgentMetrics(
      known_personal_facts=known,
      correct_personal_facts=correct,
      total_personal_facts=total,
      m1_personal=(correct / total) if total else 0.0,
      zebra_owner_true=zebra_owner_true,
      zebra_owner_pred=zebra_owner_pred,
      zebra_resolved=zebra_resolved,
      m2_zebra=m2_zebra,
    )

  def _append_extended_metrics(self, day: int) -> None:
    truth = self._build_truth_snapshot()

    for agent in self.agents:
      belief = self._build_belief_snapshot(agent.knowledge)
      metric = self._evaluate_agent_metrics(truth, belief)
      self.metrics_ext_rows.append(
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

  def _log_event(self, day: int, kind: str, *args: Any) -> int:
    self.event_id += 1
    row = [str(self.event_id), str(day), str(kind)]
    row.extend("" if arg is None else str(arg) for arg in args)
    self.events.append(row)
    self.xml_events.append(
      {
        "id": self.event_id,
        "day": day,
        "type": kind,
        "args": ["" if arg is None else str(arg) for arg in args],
      }
    )
    return self.event_id

  def _remove_offers_from(self, offerer: str) -> None:
    for target, offerers in list(self.pet_offers.items()):
      if offerer in offerers:
        offerers.discard(offerer)
      if not offerers:
        self.pet_offers.pop(target, None)
    for target, offerers in list(self.bot_pet_offers.items()):
      if offerer in offerers:
        offerers.discard(offerer)
      if not offerers:
        self.bot_pet_offers.pop(target, None)
    for target, offerers in list(self.house_offers.items()):
      if offerer in offerers:
        offerers.discard(offerer)
      if not offerers:
        self.house_offers.pop(target, None)
    for target, offerers in list(self.bot_house_offers.items()):
      if offerer in offerers:
        offerers.discard(offerer)
      if not offerers:
        self.bot_house_offers.pop(target, None)

  def state(self) -> dict[str, Any]:
    m1 = {agent.name: self._m1(agent) for agent in self.agents}
    by_name = self._by_name()

    pending: list[int] = []
    for uid, role in self.humans.items():
      agent = by_name.get(role)
      if agent is None or agent.trip.active:
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
    offers_in = sorted(
      name for name in self.pet_offers.get(me.name, set()) if name in human_roles
    )
    offers_in.extend(
      sorted(name for name in self.bot_pet_offers.get(me.name, set()) if name not in offers_in)
    )
    house_offers_in = sorted(
      name for name in self.house_offers.get(me.name, set()) if name in human_roles
    )
    house_offers_in.extend(
      sorted(name for name in self.bot_house_offers.get(me.name, set()) if name not in house_offers_in)
    )

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
      "all_roles": [agent.name for agent in self.agents if agent.name != me.name],
      "pet_offers_in": offers_in,
      "house_offers_in": house_offers_in,
      "knowledge": knowledge,
    }

  def set_action(self, user_id: int, action: Action) -> dict[str, Any]:
    name = self.humans.get(int(user_id))
    if not name:
      return {"ok": False, "reason": "not a human"}

    me = self._by_name().get(name)
    if me is None:
      return {"ok": False, "reason": "role not found"}

    if me.trip.active:
      return {"ok": False, "reason": "agent is traveling"}

    if action.kind in {"pet_decline", "house_decline"}:
      offerer = (action.target or "").strip()
      if offerer:
        if action.kind == "pet_decline":
          offerers = self.pet_offers.get(name)
          if offerers and offerer in offerers:
            offerers.discard(offerer)
            if not offerers:
              self.pet_offers.pop(name, None)
          bot_offerers = self.bot_pet_offers.get(name)
          if bot_offerers and offerer in bot_offerers:
            bot_offerers.discard(offerer)
            if not bot_offerers:
              self.bot_pet_offers.pop(name, None)
        else:
          offerers = self.house_offers.get(name)
          if offerers and offerer in offerers:
            offerers.discard(offerer)
            if not offerers:
              self.house_offers.pop(name, None)
          bot_offerers = self.bot_house_offers.get(name)
          if bot_offerers and offerer in bot_offerers:
            bot_offerers.discard(offerer)
            if not bot_offerers:
              self.bot_house_offers.pop(name, None)
      self.pending_actions[name] = Action(kind=action.kind, target=offerer)
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

      self.pending_actions[name] = Action(kind="pet_offer", target=target)
      if target in set(self.humans.values()):
        self.pet_offers.setdefault(target, set()).add(name)
        if target != name:
          self.pending_actions.pop(target, None)
      else:
        self.pending_actions[target] = Action(kind="pet_accept", target=name)
      return {"ok": True, "pending_user_ids": self.state()["pending_user_ids"]}

    if action.kind == "house_offer":
      target = (action.target or "").strip()
      target_agent = self._by_name().get(target)
      if not target or target_agent is None:
        return {"ok": False, "reason": "bad target"}
      if me.trip.active or target_agent.trip.active:
        return {"ok": False, "reason": "someone is traveling"}

      self.pending_actions[name] = Action(kind="house_offer", target=target)
      if target in set(self.humans.values()):
        self.house_offers.setdefault(target, set()).add(name)
        if target != name:
          self.pending_actions.pop(target, None)
      else:
        self.pending_actions[target] = Action(kind="house_accept", target=name)
      return {"ok": True, "pending_user_ids": self.state()["pending_user_ids"]}

    if action.kind in {"pet_accept", "house_accept"}:
      self.pending_actions[name] = Action(kind="pet_accept", target=action.target)
      if action.kind == "house_accept":
        self.pending_actions[name] = Action(kind="house_accept", target=action.target)
      return {"ok": True, "pending_user_ids": self.state()["pending_user_ids"]}

    self.pending_actions[name] = Action(kind=action.kind, dst=action.dst, target=action.target)
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
      return Action(kind="house_exchange")
    if self.rng.randint(1, 100) <= int(strategy["p_pet_exch"]):
      return Action(kind="pet_exchange")

    base_location = agent.home
    candidates = [
      base_location,
      self._neighbor_left(base_location),
      self._neighbor_right(base_location),
    ]
    probs_full = list(strategy["p_to"])
    probs = [probs_full[house - 1] for house in candidates]

    dst = pick_by_probs(self.rng, candidates, probs)
    if dst == base_location:
      return Action(kind="stay")

    if dst == self._neighbor_left(base_location):
      return Action(kind="left")
    if dst == self._neighbor_right(base_location):
      return Action(kind="right")
    return Action(kind="stay")

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
      if not offerer:
        continue
      offer_action = actions.get(offerer)
      has_live_offer = bool(
        offer_action is not None
        and offer_action.kind == "pet_offer"
        and (offer_action.target or "").strip() == accepter
      )
      has_bot_offer = offerer in self.bot_pet_offers.get(accepter, set())
      if not has_live_offer and not has_bot_offer:
        continue

      first = by_name.get(offerer)
      second = by_name.get(accepter)
      if first is None or second is None:
        continue
      if first.trip.active or second.trip.active:
        continue

      first.pet, second.pet = second.pet, first.pet
      self._log_event(day, "changePet", 2, first.name, second.name, first.pet, second.pet)
      swaps.append((first.name, second.name))
      self._remove_offers_from(first.name)
      self.pet_offers.pop(second.name, None)
      bot_offerers = self.bot_pet_offers.get(second.name)
      if bot_offerers and first.name in bot_offerers:
        bot_offerers.discard(first.name)
        if not bot_offerers:
          self.bot_pet_offers.pop(second.name, None)

    return swaps

  def _execute_human_house_swaps(self, day: int, actions: dict[str, Action], by_name: dict[str, Agent]) -> list[tuple[str, str]]:
    swaps: list[tuple[str, str]] = []

    for accepter, action in list(actions.items()):
      if action.kind != "house_accept":
        continue

      offerer = (action.target or "").strip()
      if not offerer:
        continue
      offer_action = actions.get(offerer)
      has_live_offer = bool(
        offer_action is not None
        and offer_action.kind == "house_offer"
        and (offer_action.target or "").strip() == accepter
      )
      has_bot_offer = offerer in self.bot_house_offers.get(accepter, set())
      if not has_live_offer and not has_bot_offer:
        continue

      first = by_name.get(offerer)
      second = by_name.get(accepter)
      if first is None or second is None:
        continue
      if first.trip.active or second.trip.active:
        continue

      first.home, second.home = second.home, first.home
      first.location = first.home
      second.location = second.home
      self._log_event(day, "changeHouse", 2, first.name, second.name, first.home, second.home)
      swaps.append((first.name, second.name))
      self._remove_offers_from(first.name)
      self.house_offers.pop(second.name, None)
      bot_offerers = self.bot_house_offers.get(second.name)
      if bot_offerers and first.name in bot_offerers:
        bot_offerers.discard(first.name)
        if not bot_offerers:
          self.bot_house_offers.pop(second.name, None)

    return swaps

  def _execute_bot_exchange(self, day: int, actor: Agent, kind: str, groups: dict[int, list[Agent]]) -> tuple[str, str] | None:
    if actor.trip.active:
      return None

    group = [member for member in groups.get(actor.location, []) if member.name != actor.name]
    human_roles = set(self.humans.values())
    if not group:
      return None

    other = self.rng.choice(group)
    if kind == "house":
      if actor.name in human_roles:
        return None
      if other.name in human_roles:
        if self.rng.randint(1, 100) <= 50:
          self.bot_house_offers.setdefault(other.name, set()).add(actor.name)
        return None
      if self.rng.randint(1, 100) > 50:
        return None
      actor.home, other.home = other.home, actor.home
      actor.location = actor.home
      other.location = other.home
      self._log_event(day, "changeHouse", 2, actor.name, other.name, actor.home, other.home)
      return (actor.name, other.name)

    if actor.name in human_roles:
      return None
    if other.name in human_roles:
      if self.rng.randint(1, 100) <= 50:
        self.bot_pet_offers.setdefault(other.name, set()).add(actor.name)
      return None
    if self.rng.randint(1, 100) > 50:
      return None

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
    executed_human_house_swaps: list[tuple[str, str]],
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

      visitors = [
        name
        for name in arrived_ok_by_house.get(loc_before.get(agent.name, agent.location), [])
        if name != agent.name
      ]
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

      for first, second in executed_human_house_swaps:
        if agent.name == first:
          lines.append(f"Обмен домами: вы обменялись с {second}.")
        if agent.name == second:
          lines.append(f"Обмен домами: вы обменялись с {first}.")

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

    for agent in self.agents:
      agent.location = agent.home
      agent.trip.active = False
      agent.trip.src = agent.home
      agent.trip.dst = agent.home
      agent.trip.remaining = 0
      agent.trip.start_event_id = 0

    arrived_ok_by_house: dict[int, list[str]] = {}

    actions: dict[str, Action] = {}
    for role, action in self.pending_actions.items():
      actions[role] = action

    for agent in self.agents:
      if agent.name in actions or agent.trip.active:
        continue
      actions[agent.name] = self._bot_decision(agent)

    by_name = self._by_name()
    started_trips: dict[str, int] = {}
    by_home = self._by_home()
    for agent in self.agents:
      action = actions.get(agent.name)
      if action is None:
        continue

      if action.kind == "left":
        dst = self._neighbor_left(agent.home)
      elif action.kind == "right":
        dst = self._neighbor_right(agent.home)
      elif action.kind == "go_to" and action.dst is not None:
        dst = int(action.dst)
        if dst not in {self._neighbor_left(agent.home), self._neighbor_right(agent.home)}:
          continue
      else:
        continue

      event_id = self._log_event(day, "startTrip", agent.name, agent.home, dst)
      agent.location = dst
      started_trips[agent.name] = dst
      host = by_home.get(dst)
      success = int(host is not None and host.location == host.home)
      self._log_event(day, "FinishTrip", event_id, agent.name, success)
      if success == 1:
        arrived_ok_by_house.setdefault(dst, []).append(agent.name)
      else:
        agent.location = agent.home

    groups_before_departure = self._groups_for_meetings()

    executed_human_swaps = self._execute_human_pet_swaps(day, actions, by_name)
    executed_human_house_swaps = self._execute_human_house_swaps(day, actions, by_name)
    executed_house_swaps_bot: list[tuple[str, str]] = []
    executed_pet_swaps_bot: list[tuple[str, str]] = []
    processed_exchange_agents: set[str] = set()
    for first, second in executed_human_swaps:
      processed_exchange_agents.add(first)
      processed_exchange_agents.add(second)
    for first, second in executed_human_house_swaps:
      processed_exchange_agents.add(first)
      processed_exchange_agents.add(second)

    for agent in self.agents:
      if agent.trip.active:
        continue
      action = actions.get(agent.name)
      if action is None:
        continue
      if agent.name in processed_exchange_agents and action.kind in {"house_exchange", "pet_exchange"}:
        continue
      if action.kind == "house_exchange":
        pair = self._execute_bot_exchange(day, agent, "house", groups_before_departure)
        if pair:
          executed_house_swaps_bot.append(pair)
          processed_exchange_agents.add(pair[0])
          processed_exchange_agents.add(pair[1])
      elif action.kind == "pet_exchange":
        pair = self._execute_bot_exchange(day, agent, "pet", groups_before_departure)
        if pair:
          executed_pet_swaps_bot.append(pair)
          processed_exchange_agents.add(pair[0])
          processed_exchange_agents.add(pair[1])

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

    for agent in self.agents:
      agent.location = agent.home
      agent.trip.active = False
      agent.trip.src = agent.home
      agent.trip.dst = agent.home
      agent.trip.remaining = 0
      agent.trip.start_event_id = 0

    self._apply_noise()

    if not self.metrics_rows:
      self.metrics_rows.append(["day"] + [agent.name for agent in self.agents])
    self.metrics_rows.append([str(day)] + [f"{self._m1(agent):.6f}" for agent in self.agents])
    self._append_extended_metrics(day)

    reports = self._collect_reports(
      day,
      know_before,
      loc_before,
      arrived_ok_by_house,
      met_today,
      executed_human_swaps,
      executed_human_house_swaps,
      executed_house_swaps_bot,
      executed_pet_swaps_bot,
      started_trips,
    )

    self.pending_actions = {}
    self.pet_offers = {}

    self.day += 1
    done = self.day > self.days_total
    files = self._finalize() if done else None
    leaderboard = sorted(
      ((agent.name, self._m1(agent)) for agent in self.agents),
      key=lambda item: item[1],
      reverse=True,
    )

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

    if len(self.metrics_rows) > 1:
      try:
        last_day = int(self.metrics_rows[-1][0])
      except Exception:
        last_day = max(1, min(self.day, self.days_total))
    else:
      last_day = max(1, min(self.day, self.days_total))
    if len(self.metrics_rows) == 1 or self.metrics_rows[-1][0] != str(last_day):
      self.metrics_rows.append([str(last_day)] + [f"{self._m1(agent):.6f}" for agent in self.agents])
      self._append_extended_metrics(last_day)

    files = self._finalize()
    leaderboard = sorted(
      ((agent.name, self._m1(agent)) for agent in self.agents),
      key=lambda item: item[1],
      reverse=True,
    )

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
    self.log_dir.mkdir(parents=True, exist_ok=True)

    metrics_path = self.log_dir / f"metrics_{self.game_id}.csv"
    metrics_ext_path = self.log_dir / f"metrics_ext_{self.game_id}.csv"
    events_path = self.log_dir / f"game_{self.game_id}.csv"
    xml_path = self.log_dir / f"game_{self.game_id}.xml"

    with metrics_path.open("w", newline="", encoding="utf-8") as handle:
      writer = csv.writer(handle)
      writer.writerows(self.metrics_rows)

    with metrics_ext_path.open("w", newline="", encoding="utf-8") as handle:
      writer = csv.writer(handle)
      writer.writerows(self.metrics_ext_rows)

    with events_path.open("w", newline="", encoding="utf-8") as handle:
      handle.write("eventID;day;event;...\n")
      for row in self.events:
        handle.write(";".join(row) + "\n")

    _write_xml(xml_path, self.game_id, self.xml_events)
    return {
      "metrics": str(metrics_path),
      "metrics_ext": str(metrics_ext_path),
      "csv": str(events_path),
      "xml": str(xml_path),
    }
