# Zebra Puzzle

Прототип тактической игры и симулятора для исследования situational awareness на сюжете Zebra Puzzle.

Проект можно использовать в двух режимах:

- как интерактивную игру через Telegram Bot
- как автономный исследовательский стенд без Telegram, когда симуляции запускаются пакетно, сохраняют логи и по ним строятся графики

Этот README собран так, чтобы по нему можно было:

- поднять сервер
- запустить бота
- запускать симуляции без Telegram
- делать batch-прогоны
- строить графики SA
- обрабатывать логи
- быстро понимать, какие файлы появляются после запуска

---

## 1. Что лежит в репозитории

```text
zebra/
├── analysis/              # графики, обработка логов, бенчмарки
├── core/                  # схемы, метрики, общая логика
├── docs/                  # материалы по отчету
├── optimizer/             # задел под стратегии/агентов
├── scripts/               # shell-скрипты запуска
├── server/                # FastAPI REST API
├── simulator/             # batch и interactive ядро симуляции
├── strategy/              # базовые интерфейсы стратегий
├── zebra_bot/             # Telegram Bot
├── run_all.sh             # запуск сервера и бота вместе
├── telegram_bot.py        # совместимый вход
├── requirements.txt
└── Readme.md / README.md
```

---

## 2. Что именно моделируется

В мире игры есть дома и жители с атрибутами:

- цвет дома
- национальность
- напиток
- питомец
- сигареты

В отличие от обычной статической Zebra Puzzle, здесь мир меняется по дням:

- участники перемещаются между домами
- дорога может занимать несколько дней
- при встречах открываются новые факты
- при режиме `share=meet` участники обмениваются знаниями
- в некоторых сценариях возможны обмены питомцами и домами
- можно включать шум наблюдений
- граф перемещений может быть `ring` или `full`

Проект нужен не только для самой игры, а для анализа того, как у игрока по ходу партии растет situational awareness.

---

## 3. Основные метрики

### M1
Доля корректно известных фактов о мире для конкретного участника.

### M2
Известно ли участнику, кто владелец зебры.

На практике это означает, что после симуляции можно смотреть не только на финальный исход, но и на динамику знаний по дням.

---

## 4. Зависимости

Установка зависимостей:

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

`requirements.txt` включает:

- `fastapi`
- `uvicorn[standard]`
- `requests`
- `pydantic`
- `pyyaml`
- `matplotlib`
- `aiogram`
- `python-dotenv`

---

## 5. Переменные окружения

Проект умеет подхватывать настройки из `.env`.

Пример файла `.env`:

```env
BOT_TOKEN=your_telegram_bot_token
ZEBRA_API=http://127.0.0.1:8000
ZEBRA_HOST=127.0.0.1
ZEBRA_PORT=8000

ZEBRA_PLAYERS=6
ZEBRA_HOUSES=6
ZEBRA_DAYS=50
ZEBRA_SHARE=meet
ZEBRA_NOISE=0.0
ZEBRA_GRAPH=ring
ZEBRA_LOBBY_DELAY_SEC=90
ZEBRA_TURN_DELAY_SEC=60
ZEBRA_VOTE_DELAY_SEC=45
```

Что важно:

- для запуска только сервера `BOT_TOKEN` не нужен
- для запуска бота `BOT_TOKEN` обязателен
- `ZEBRA_API` нужен боту, чтобы он знал адрес сервера

---

## 6. Быстрый запуск интерактивной версии

### 6.1. Запуск сервера

```bash
./scripts/run_server.sh
```

Что делает скрипт:

- читает `.env`, если файл есть
- берет `ZEBRA_HOST` и `ZEBRA_PORT`
- запускает `uvicorn server.main:app --reload`

По умолчанию сервер поднимается на:

```text
http://127.0.0.1:8000
```

### 6.2. Проверка, что сервер жив

```bash
curl http://127.0.0.1:8000/health
```

Ожидаемый ответ примерно такой:

```json
{"ok": true, "time": 1234567890.0}
```

### 6.3. Запуск Telegram-бота

```bash
./scripts/run_bot.sh
```

Скрипт:

- читает `.env`
- проверяет, что задан `BOT_TOKEN`
- выставляет `ZEBRA_API`
- запускает `python -m zebra_bot.main`

### 6.4. Запуск сервера и бота вместе

```bash
./run_all.sh
```

Этот вариант удобен, когда нужно быстро проверить связку целиком.

---

## 7. Работа без Telegram

Это важная часть репозитория. Без Telegram проект используется как исследовательский стенд: запускаются симуляции, сохраняются логи, после чего по ним строятся графики и сравниваются сценарии.

Ниже все основные способы запуска.

---

## 8. Способ 1 - прямая локальная симуляция через `simulator.runner`

Самый простой способ прогнать одну симуляцию без API и без Telegram:

```bash
python -m simulator.runner \
  --session-id demo_run \
  --agents 6 \
  --houses 6 \
  --days 50 \
  --share meet \
  --noise 0.0 \
  --graph ring \
  --seed 1 \
  --log-dir data/logs
```

После завершения в консоль печатается JSON с путями к файлам результатов.

### Параметры `simulator.runner`

```bash
python -m simulator.runner --help
```

Основные аргументы:

- `--session-id` - имя прогона
- `--config` - путь к JSON-конфигу
- `--agents` - число участников
- `--houses` - число домов
- `--days` - число дней
- `--share` - режим обмена знаниями
- `--noise` - шум наблюдений
- `--graph` - `ring` или `full`
- `--seed` - сид для воспроизводимости
- `--log-dir` - папка вывода

### Пример через JSON-конфиг

Создай файл `configs/demo.json`:

```json
{
  "agents": 6,
  "houses": 6,
  "days": 50,
  "share": "meet",
  "noise": 0.0,
  "graph": "ring",
  "seed": 7
}
```

Запуск:

```bash
python -m simulator.runner \
  --session-id demo_cfg \
  --config configs/demo.json \
  --log-dir data/logs
```

---

## 9. Способ 2 - batch-прогоны через `simulator.batch_sim`

Если нужно не один прогон, а серию прогонов с одинаковой схемой, удобнее использовать batch-режим.

Пример:

```bash
python -m simulator.batch_sim \
  --runs 10 \
  --agents 6 \
  --houses 6 \
  --days 50 \
  --share meet \
  --noise 0.0 \
  --graph ring \
  --seed 1 \
  --out-dir data/logs \
  --prefix batch_ring
```

### Что делает `batch_sim`

Для каждого запуска он:

- создает отдельную сессию
- выполняет симуляцию
- сохраняет обычные логи
- собирает сводный CSV-файл вида:

```text
data/logs/batch_ring_summary.csv
```

В summary пишутся:

- номер прогона
- параметры запуска
- имя агента
- `m1_personal`
- `m2_zebra`
- число известных фактов
- предсказание владельца зебры
- пути ко всем файлам прогона

### Аргументы `batch_sim`

```bash
python -m simulator.batch_sim --help
```

Основные:

- `--runs`
- `--agents`
- `--houses`
- `--days`
- `--share`
- `--noise`
- `--graph`
- `--seed`
- `--sleep-ms-per-day`
- `--out-dir`
- `--prefix`

### Пример сравнения `ring` и `full`

Сначала `ring`:

```bash
python -m simulator.batch_sim \
  --runs 10 \
  --agents 6 \
  --houses 6 \
  --days 50 \
  --share meet \
  --graph ring \
  --seed 1 \
  --out-dir data/logs \
  --prefix batch_ring
```

Потом `full`:

```bash
python -m simulator.batch_sim \
  --runs 10 \
  --agents 6 \
  --houses 6 \
  --days 50 \
  --share meet \
  --graph full \
  --seed 1 \
  --out-dir data/logs \
  --prefix batch_full
```

В результате появятся два summary-файла, которые потом удобно сравнивать отдельно.

---

## 10. Способ 3 - запуск через REST API без Telegram

Если хочется проверять именно серверный слой, можно запускать симуляцию через FastAPI.

Сначала подними сервер:

```bash
./scripts/run_server.sh
```

### 10.1. Мгновенная симуляция через `/simulate`

```bash
curl -X POST http://127.0.0.1:8000/simulate \
  -H "Content-Type: application/json" \
  -d '{
    "agents": 6,
    "houses": 6,
    "days": 50,
    "share": "meet",
    "noise": 0.0,
    "graph": "ring",
    "seed": 1,
    "sleep_ms_per_day": 0
  }'
```

Сервер сразу выполнит симуляцию и вернет `session_id` и пути к выходным файлам.

### 10.2. Создать сессию отдельно, потом запустить

Создание сессии:

```bash
curl -X POST http://127.0.0.1:8000/session/new \
  -H "Content-Type: application/json" \
  -d '{
    "agents": 6,
    "houses": 6,
    "days": 50,
    "share": "meet",
    "noise": 0.0,
    "graph": "ring",
    "seed": 1
  }'
```

Проверка сессии:

```bash
curl http://127.0.0.1:8000/session/<SESSION_ID>
```

Запуск сохраненной сессии:

```bash
curl -X POST http://127.0.0.1:8000/session/<SESSION_ID>/run
```

### 10.3. Клиент для REST API из репозитория

В проекте есть отдельная утилита `simulator.api_runner`.

Запуск мгновенной симуляции:

```bash
python -m simulator.api_runner \
  --base-url http://127.0.0.1:8000 \
  --mode simulate \
  --agents 6 \
  --houses 6 \
  --days 50 \
  --share meet \
  --noise 0.0 \
  --graph ring \
  --seed 1
```

Запуск через создание сессии и отдельный `run`:

```bash
python -m simulator.api_runner \
  --base-url http://127.0.0.1:8000 \
  --mode session \
  --agents 6 \
  --houses 6 \
  --days 50 \
  --share meet \
  --noise 0.0 \
  --graph ring \
  --seed 1
```

---

## 11. Что появляется после симуляции

Обычно все результаты складываются в `data/logs/`.

После одного прогона там появляются файлы примерно такого типа:

- `session_xxx_events.csv` - событийный лог
- `session_xxx_events.xml` - тот же лог в XML
- `session_xxx_metrics.csv` - временной ряд метрик
- `session_xxx_metrics_ext.csv` - расширенные метрики

### Что обычно лежит в `metrics_ext`

В расширенном файле могут быть поля:

- `agent`
- `day`
- `m1_personal`
- `m2_zebra`
- `known_personal_facts`
- `correct_personal_facts`
- `total_personal_facts`
- `zebra_resolved`
- `zebra_owner_pred`
- `zebra_owner_true`

Именно этот файл чаще всего удобнее использовать для анализа.

---

## 12. Построение графиков SA

В репозитории есть несколько готовых скриптов.

---

### 12.1. Один график по одному файлу - `analysis.plot_sa`

Пример для `m1_personal`:

```bash
python -m analysis.plot_sa \
  --metrics data/logs/session_demo_metrics_ext.csv \
  --metric m1_personal \
  --out data/logs/session_demo_m1.png \
  --title "M1 over time"
```

Пример для `m2_zebra`:

```bash
python -m analysis.plot_sa \
  --metrics data/logs/session_demo_metrics_ext.csv \
  --metric m2_zebra \
  --out data/logs/session_demo_m2.png \
  --title "M2 over time"
```

Если `--metric` не указать, скрипт сам попытается выбрать подходящую колонку.

---

### 12.2. Сравнение нескольких файлов - `analysis.plot_sa_compare`

Например, сравнить сценарии `ring` и `full`:

```bash
python -m analysis.plot_sa_compare \
  --metrics \
    data/logs/ring_metrics_ext.csv \
    data/logs/full_metrics_ext.csv \
  --metric m1_personal \
  --labels ring full \
  --out data/logs/sa_compare_m1.png \
  --title "M1: ring vs full"
```

Аналогично можно сравнивать `m2_zebra`:

```bash
python -m analysis.plot_sa_compare \
  --metrics \
    data/logs/ring_metrics_ext.csv \
    data/logs/full_metrics_ext.csv \
  --metric m2_zebra \
  --labels ring full \
  --out data/logs/sa_compare_m2.png \
  --title "M2: ring vs full"
```

---

### 12.3. График сразу по трем кривым - `analysis.plot_sa_3curves`

Этот скрипт пытается построить сразу три линии:

- `m1_personal`
- `m2_zebra`
- `zebra_resolved`

Пример:

```bash
python -m analysis.plot_sa_3curves \
  --metrics data/logs/session_demo_metrics_ext.csv \
  --out data/logs/session_demo_3curves.png \
  --title "SA curves"
```

Это удобный быстрый вариант для отчета, когда нужно одним рисунком показать основную динамику.

---

## 13. Бенчмарки и графики производительности

Если нужно не содержание знаний, а производительность симулятора, используется пара скриптов `analysis.bench` и `analysis.plot_bench`.

### 13.1. Запуск бенчмарка

Пример:

```bash
python -m analysis.bench \
  --max_agents 100 \
  --step 10 \
  --days 50 \
  --runs 3 \
  --houses 6 \
  --share meet \
  --graph ring \
  --noise 0.0 \
  --out_dir data/logs
```

Скрипт делает серию прогонов для разного числа агентов и пишет итог в:

```text
data/logs/bench.csv
```

В `bench.csv` сохраняются:

- число агентов
- число домов
- число дней
- время выполнения `elapsed_sec`
- усредненные финальные значения `M1`, `M2`
- пути к файлам каждого прогона

### 13.2. Построить график по `bench.csv`

Самый частый случай - время выполнения от числа агентов:

```bash
python -m analysis.plot_bench \
  --bench data/logs/bench.csv \
  --x agents \
  --y elapsed_sec \
  --out data/logs/bench_time.png \
  --title "Elapsed time vs agents"
```

Можно строить и по другим колонкам, например по средней финальной `M1`:

```bash
python -m analysis.plot_bench \
  --bench data/logs/bench.csv \
  --x agents \
  --y final_m1_avg \
  --out data/logs/bench_m1.png \
  --title "Final M1 vs agents"
```

Или по `final_m2_avg`:

```bash
python -m analysis.plot_bench \
  --bench data/logs/bench.csv \
  --x agents \
  --y final_m2_avg \
  --out data/logs/bench_m2.png \
  --title "Final M2 vs agents"
```

---

## 14. Постобработка логов - `analysis.process_log`

Этот скрипт берет файл метрик и раскладывает его в более удобные производные файлы.

Пример:

```bash
python -m analysis.process_log \
  --metrics data/logs/session_demo_metrics_ext.csv \
  --events data/logs/session_demo_events.csv \
  --metric m1_personal \
  --t 500 \
  --out_dir data/logs/processed
```

Что он делает:

- читает файл метрик
- выбирает нужную метрику
- для каждого агента делает отдельный CSV
- для каждого агента делает отдельный YAML
- формирует `metrics_summary.csv`
- если передан `--events`, дополнительно делает YAML-сводку по типам событий

### Полезные флаги

- `--metrics` - путь к файлу метрик
- `--events` - путь к событийному CSV
- `--metric` - имя метрики
- `--t` - максимальный горизонт по дням
- `--out_dir` - папка вывода
- `--only_first` - ограничить число агентов в выводе

### Пример только для первых трех агентов

```bash
python -m analysis.process_log \
  --metrics data/logs/session_demo_metrics_ext.csv \
  --metric m1_personal \
  --t 100 \
  --out_dir data/logs/processed_first3 \
  --only_first 3
```

---

## 15. Минимальные рабочие сценарии

### Сценарий A - просто получить один график без Telegram

```bash
python -m simulator.runner \
  --session-id one_run \
  --agents 6 \
  --houses 6 \
  --days 50 \
  --share meet \
  --noise 0.0 \
  --graph ring \
  --seed 1 \
  --log-dir data/logs

python -m analysis.plot_sa \
  --metrics data/logs/one_run_metrics_ext.csv \
  --metric m1_personal \
  --out data/logs/one_run_m1.png \
  --title "One run M1"
```

### Сценарий B - сравнить `ring` и `full`

```bash
python -m simulator.runner \
  --session-id ring_run \
  --agents 6 \
  --houses 6 \
  --days 50 \
  --share meet \
  --noise 0.0 \
  --graph ring \
  --seed 1 \
  --log-dir data/logs

python -m simulator.runner \
  --session-id full_run \
  --agents 6 \
  --houses 6 \
  --days 50 \
  --share meet \
  --noise 0.0 \
  --graph full \
  --seed 1 \
  --log-dir data/logs

python -m analysis.plot_sa_compare \
  --metrics \
    data/logs/ring_run_metrics_ext.csv \
    data/logs/full_run_metrics_ext.csv \
  --metric m1_personal \
  --labels ring full \
  --out data/logs/ring_vs_full_m1.png \
  --title "M1: ring vs full"
```

### Сценарий C - batch и summary

```bash
python -m simulator.batch_sim \
  --runs 20 \
  --agents 6 \
  --houses 6 \
  --days 50 \
  --share meet \
  --noise 0.0 \
  --graph ring \
  --seed 1 \
  --out-dir data/logs \
  --prefix study_ring
```

Итоговый файл:

```text
data/logs/study_ring_summary.csv
```

### Сценарий D - проверка именно REST API

```bash
./scripts/run_server.sh
```

Потом в другом терминале:

```bash
python -m simulator.api_runner \
  --base-url http://127.0.0.1:8000 \
  --mode simulate \
  --agents 6 \
  --houses 6 \
  --days 50 \
  --share meet \
  --noise 0.0 \
  --graph ring \
  --seed 1
```

---

## 16. Полезные API-эндпоинты

### Общие

```bash
curl http://127.0.0.1:8000/
curl http://127.0.0.1:8000/health
curl http://127.0.0.1:8000/debug/games
curl http://127.0.0.1:8000/debug/sessions
```

### Batch / session

Создать сессию:

```bash
curl -X POST http://127.0.0.1:8000/session/new \
  -H "Content-Type: application/json" \
  -d '{"agents":6,"houses":6,"days":50,"share":"meet","noise":0.0,"graph":"ring"}'
```

Посмотреть сессию:

```bash
curl http://127.0.0.1:8000/session/<SESSION_ID>
```

Запустить сессию:

```bash
curl -X POST http://127.0.0.1:8000/session/<SESSION_ID>/run
```

### Интерактивная игра через API

Создать игру:

```bash
curl -X POST http://127.0.0.1:8000/game/new \
  -H "Content-Type: application/json" \
  -d '{
    "cfg": {
      "agents": 6,
      "houses": 6,
      "days": 50,
      "share": "meet",
      "noise": 0.0,
      "graph": "ring"
    },
    "humans": {
      "111": "Russian",
      "222": "English"
    }
  }'
```

Получить состояние игры:

```bash
curl http://127.0.0.1:8000/game/<GAME_ID>
curl http://127.0.0.1:8000/game/<GAME_ID>/state
```

Получить состояние игрока:

```bash
curl http://127.0.0.1:8000/game/<GAME_ID>/player/<USER_ID>
```

Отправить действие игрока:

```bash
curl -X POST http://127.0.0.1:8000/game/<GAME_ID>/action/<USER_ID> \
  -H "Content-Type: application/json" \
  -d '{"kind":"stay"}'
```

Примеры действий:

```bash
{"kind":"stay"}
{"kind":"left"}
{"kind":"right"}
{"kind":"go_to","dst":4}
{"kind":"pet_offer","target":"English"}
{"kind":"pet_accept","target":"Russian"}
{"kind":"pet_decline","target":"Russian"}
```

Сделать шаг:

```bash
curl -X POST http://127.0.0.1:8000/game/<GAME_ID>/step
```

Завершить игру:

```bash
curl -X POST http://127.0.0.1:8000/game/<GAME_ID>/finish
```

Удалить игру:

```bash
curl -X DELETE http://127.0.0.1:8000/game/<GAME_ID>
```

---

## 17. Что удобно хранить для отчета

Для курсовой обычно полезно сохранять:

- один событийный CSV по демонстрационному сценарию
- один `metrics_ext.csv`
- один график `M1`
- один график сравнения `ring` и `full`
- один 3-кривой график `M1/M2/zebra_resolved`
- один `bench.csv` и график времени выполнения

Минимальный набор команд под это:

```bash
python -m simulator.runner \
  --session-id report_ring \
  --agents 6 \
  --houses 6 \
  --days 50 \
  --share meet \
  --noise 0.0 \
  --graph ring \
  --seed 1 \
  --log-dir data/logs

python -m analysis.plot_sa \
  --metrics data/logs/report_ring_metrics_ext.csv \
  --metric m1_personal \
  --out data/logs/report_ring_m1.png \
  --title "M1 over time"

python -m analysis.plot_sa_3curves \
  --metrics data/logs/report_ring_metrics_ext.csv \
  --out data/logs/report_ring_3curves.png \
  --title "SA curves"

python -m analysis.bench \
  --max_agents 60 \
  --step 10 \
  --days 50 \
  --runs 3 \
  --houses 6 \
  --share meet \
  --graph ring \
  --noise 0.0 \
  --out_dir data/logs

python -m analysis.plot_bench \
  --bench data/logs/bench.csv \
  --x agents \
  --y elapsed_sec \
  --out data/logs/bench_time.png \
  --title "Elapsed time vs agents"
```

---

## 18. Типичные проблемы

### Сервер не поднимается

Проверь:

```bash
python -m uvicorn server.main:app --host 127.0.0.1 --port 8000 --reload
```

Если так работает, значит проблема в скрипте или окружении.

### Бот пишет `BOT_TOKEN is not set`

Значит в `.env` не задан токен или файл не подхватился.

### Логи не появляются

Проверь, что существует папка:

```bash
mkdir -p data/logs
```

И что у процесса есть права записи.

### График не строится

Обычно проблема в одном из трех мест:

- указан не тот путь к `metrics` файлу
- указано неправильное имя метрики
- файл пустой или имеет другой формат колонок

Для проверки открой первые строки файла:

```bash
head -20 data/logs/<имя_файла>.csv
```

### `plot_sa_3curves` падает

Значит в выбранном файле нет нужных колонок из набора:

- `m1_personal`
- `m2_zebra`
- `zebra_resolved`

В таком случае сначала смотри заголовок CSV.

---

## 19. Набор команд, который реально удобно держать под рукой

### Поднять сервер

```bash
./scripts/run_server.sh
```

### Проверить health

```bash
curl http://127.0.0.1:8000/health
```

### Один локальный прогон

```bash
python -m simulator.runner \
  --session-id quick \
  --agents 6 \
  --houses 6 \
  --days 50 \
  --share meet \
  --noise 0.0 \
  --graph ring \
  --seed 1 \
  --log-dir data/logs
```

### Batch

```bash
python -m simulator.batch_sim \
  --runs 10 \
  --agents 6 \
  --houses 6 \
  --days 50 \
  --share meet \
  --graph ring \
  --seed 1 \
  --out-dir data/logs \
  --prefix batch
```

### График M1

```bash
python -m analysis.plot_sa \
  --metrics data/logs/quick_metrics_ext.csv \
  --metric m1_personal \
  --out data/logs/quick_m1.png
```

### Сравнение двух сценариев

```bash
python -m analysis.plot_sa_compare \
  --metrics data/logs/ring_metrics_ext.csv data/logs/full_metrics_ext.csv \
  --metric m1_personal \
  --labels ring full \
  --out data/logs/compare_m1.png
```

### 3 кривые сразу

```bash
python -m analysis.plot_sa_3curves \
  --metrics data/logs/quick_metrics_ext.csv \
  --out data/logs/quick_3curves.png
```

### Бенчмарк

```bash
python -m analysis.bench \
  --max_agents 100 \
  --step 10 \
  --days 50 \
  --runs 3 \
  --houses 6 \
  --share meet \
  --graph ring \
  --noise 0.0 \
  --out_dir data/logs
```

### График бенчмарка

```bash
python -m analysis.plot_bench \
  --bench data/logs/bench.csv \
  --x agents \
  --y elapsed_sec \
  --out data/logs/bench_time.png
```

### Постобработка логов

```bash
python -m analysis.process_log \
  --metrics data/logs/quick_metrics_ext.csv \
  --events data/logs/quick_events.csv \
  --metric m1_personal \
  --out_dir data/logs/processed
```

---

## 20. Итог

Если нужен только исследовательский контур без Telegram, рабочая цепочка обычно выглядит так:

1. запустить одну или несколько симуляций
2. получить `metrics_ext.csv`
3. построить графики `M1`, `M2` и сравнительные кривые
4. при необходимости прогнать `bench`
5. положить графики и summary-файлы в материалы отчета

Если нужен полный интерактивный сценарий, сверху к этому добавляется Telegram Bot, который работает с тем же сервером.
