from __future__ import annotations

from .types import BeliefState


DEFAULT_FACTS_PER_PLAYER = 4


def calc_sa(belief: BeliefState, players_count: int | None = None) -> float:
  if players_count is None:
    players = set(belief.houses) | set(belief.pets) | set(belief.drinks) | set(belief.smokes)
    players_count = len(players)

  if players_count <= 0:
    return 0.0

  total_facts = DEFAULT_FACTS_PER_PLAYER * players_count
  known_facts = belief.known_facts_count()
  return known_facts / total_facts if total_facts > 0 else 0.0
