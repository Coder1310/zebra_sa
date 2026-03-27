from __future__ import annotations

import random
from typing import Tuple

from .types import Action, BeliefState, PlayerState


MOVE_DIRECTIONS = ("left", "right", "home")


def update_belief_from_state(player_state: PlayerState, belief_state: BeliefState) -> BeliefState:
  belief = BeliefState(
    houses=dict(belief_state.houses),
    pets=dict(belief_state.pets),
    drinks=dict(belief_state.drinks),
    smokes=dict(belief_state.smokes),
  )

  you = player_state.you
  player_id = player_state.player_id

  house_id_raw = you.get("house_id")
  if house_id_raw is not None:
    try:
      belief.houses[player_id] = int(house_id_raw)
    except (TypeError, ValueError):
      pass

  pet = you.get("pet")
  if pet:
    belief.pets[player_id] = pet

  drink = you.get("drink")
  if drink:
    belief.drinks[player_id] = drink

  smoke = you.get("smokes")
  if smoke:
    belief.smokes[player_id] = smoke

  for visible in player_state.visible_players:
    belief.houses[visible.player_id] = int(visible.house_id)

  return belief


def choose_direction(player_state: PlayerState) -> str:
  current_house = player_state.you.get("house_id")
  known_neighbors = player_state.neighbors or {}

  if current_house is not None:
    try:
      current_house_int = int(current_house)
    except (TypeError, ValueError):
      current_house_int = None
    else:
      for visible in player_state.visible_players:
        if visible.house_id != current_house_int:
          return "home"

  available = [direction for direction in MOVE_DIRECTIONS if direction in known_neighbors]
  if not available:
    available = list(MOVE_DIRECTIONS)

  return random.choice(available)


def decide_action(player_state: PlayerState, belief_state: BeliefState) -> Tuple[Action, BeliefState]:
  new_belief = update_belief_from_state(player_state, belief_state)
  direction = choose_direction(player_state)

  action = Action(
    player_id=player_state.player_id,
    day=player_state.day,
    type="move",
    direction=direction,
  )
  return action, new_belief
