from __future__ import annotations

from typing import Any


def _show(value: Any) -> str:
  if value is None:
    return "?"
  text = str(value).strip()
  return text if text else "?"


def format_lobby(game: dict[str, Any]) -> str:
  settings = game.get("settings") or {}
  players = game.get("players") or {}
  invited = game.get("invited_usernames") or []

  lines = [
    "🎮 Лобби ZEBRA",
    f"Игроков: {len(players)}/{int(settings.get('players', 6))}",
    f"Домов: {int(settings.get('houses', 6))}",
    f"Дней: {int(settings.get('days', 50))}",
    f"Граф: {settings.get('graph', 'ring')}",
    f"Обмен знаниями: {settings.get('share', 'meet')}",
    f"Шум: {settings.get('noise', 0.0)}",
    "",
    "Участники:",
  ]

  for uid_str, row in sorted(players.items(), key=lambda item: int(item[0])):
    name = (row.get("name") or row.get("full_name") or "игрок").strip()
    username = (row.get("username") or "").strip()
    if username:
      lines.append(f"- {name} (@{username})")
    else:
      lines.append(f"- {name}")

  if invited:
    lines.append("")
    lines.append("Приглашены:")
    lines.append(" ".join(f"@{name}" for name in invited))

  lines.append("")
  lines.append("Нажмите Join, чтобы войти в игру")
  return "\n".join(lines)


def render_player_info(player_state: dict[str, Any]) -> str:
  if not player_state.get("ok"):
    return str(player_state.get("reason") or "Не удалось получить состояние игрока")

  role = str(player_state.get("role") or "?")
  day = int(player_state.get("day", 0))
  days_total = int(player_state.get("days_total", 0))
  home = int(player_state.get("home", 0))
  location = int(player_state.get("location", 0))
  pet = _show(player_state.get("pet"))
  drink = _show(player_state.get("drink"))
  smoke = _show(player_state.get("smoke"))
  m1 = float(player_state.get("m1", 0.0))
  m2 = player_state.get("m2", 0)

  trip = player_state.get("trip") or {}
  co_located = list(player_state.get("co_located_all") or [])
  offers_in = list(player_state.get("pet_offers_in") or [])
  house_offers_in = list(player_state.get("house_offers_in") or [])
  knowledge = list(player_state.get("knowledge") or [])

  lines = [
    f"🗓 День {day}/{days_total}",
    f"Вы: {role}. Ваш дом: {home}. Сейчас: дом {location}.",
    f"Ваши атрибуты: pet = {pet}; drink = {drink}; smoke = {smoke}",
  ]

  if trip.get("active"):
    src = trip.get("src")
    dst = trip.get("dst")
    remaining = trip.get("remaining")
    lines.append(f"Вы в пути: {src} -> {dst}; осталось дней: {remaining}")

  if co_located:
    lines.append("В вашем доме сейчас: " + ", ".join(str(name) for name in co_located))
  else:
    lines.append("В вашем доме сейчас: никого")

  if offers_in:
    lines.append("Вам предлагают обмен питомцами: " + ", ".join(str(name) for name in offers_in))
  if house_offers_in:
    lines.append("Вам предлагают обмен домами: " + ", ".join(str(name) for name in house_offers_in))

  lines.append(f"M1 сейчас: {m1:.3f}")
  lines.append(f"M2 сейчас: {m2}")
  lines.append("")
  lines.append("Ваши знания по домам:")

  for row in knowledge:
    house_id = row.get("house")
    color = _show(row.get("color"))
    nationality = _show(row.get("nationality"))
    pet_value = _show(row.get("pet"))
    drink_value = _show(row.get("drink"))
    smoke_value = _show(row.get("smoke"))

    lines.append(
      f"{house_id}: "
      f"color = {color}; "
      f"nationality = {nationality}; "
      f"pet = {pet_value}; "
      f"drink = {drink_value}; "
      f"smoke = {smoke_value}"
    )

  return "\n".join(lines)
