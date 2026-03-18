from __future__ import annotations

import time

from simulator.world import KNOWLEDGE_CATEGORIES, roles_for
from zebra_bot.storage import mention


def agent_names(agents: int, houses: int) -> list[str]:
  return roles_for(agents, houses)


def format_lobby(game: dict) -> str:
  players = game.get("players", {})
  need = int(game["settings"]["players"])
  current = len(players)
  left = max(0, int(game["deadline_at"] - time.time()))
  invited = game.get("invited_usernames") or []

  lines: list[str] = []
  lines.append("🎮 ZEBRA: лобби")
  lines.append(f"Игроки: {current}/{need}")
  for player in players.values():
    lines.append(f"- {mention(player)}")
  if invited:
    lines.append("")
    lines.append("Приглашены: " + " ".join(f"@{name}" for name in invited))
  lines.append(f"Старт через: {left} сек")
  lines.append("")
  lines.append("Нажми Join. Кто не успеет - будет заменен ботом.")
  return "\n".join(lines)


def render_player_info(ps: dict) -> str:
  if not ps.get("ok"):
    return f"Ошибка: {ps.get('reason')}"

  trip = ps.get("trip") or {}
  co_located = ps.get("co_located_all") or []
  offers = ps.get("pet_offers_in") or []

  lines: list[str] = []
  lines.append(f"🗓 День {int(ps['day'])}/{int(ps['days_total'])}")
  lines.append(f"Вы: {ps['role']}. Ваш дом: {int(ps['home'])}. Сейчас: дом {int(ps['location'])}.")
  lines.append(f"Ваши атрибуты: pet={ps.get('pet')} drink={ps.get('drink')} smoke={ps.get('smoke')}")

  if bool(trip.get("active")):
    lines.append(
      f"Вы в пути: {trip.get('src')} -> {trip.get('dst')} (осталось {trip.get('remaining')} дн.)"
    )

  if co_located:
    lines.append("В вашем доме сейчас: " + ", ".join(co_located))

  if offers:
    lines.append("Входящие предложения обмена питомцами: " + ", ".join(offers))

  lines.append(f"M1 сейчас: {float(ps.get('m1', 0.0)):.3f}")
  lines.append("")
  lines.append("Ваши знания по домам:")

  for row in ps.get("knowledge") or []:
    parts: list[str] = []
    for category in KNOWLEDGE_CATEGORIES:
      value = row.get(category)
      parts.append(f"{category}={value if value is not None else '?'}")
    lines.append(f"{row['house']}: " + " ".join(parts))

  return "\n".join(lines)