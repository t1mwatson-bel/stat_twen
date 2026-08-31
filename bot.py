import os
import sys
import requests
import json
import re
import time
import pickle
import numpy as np
from datetime import datetime, timedelta
import pytz
from collections import deque, defaultdict
import warnings
import gc
import math

warnings.filterwarnings("ignore")


# =====================================================================
# АВТОУСТАНОВКА ЗАВИСИМОСТЕЙ
# =====================================================================

try:
    import subprocess
    import importlib

    REQUIRED_PACKAGES = [
        "numpy",
        "scikit-learn",
        "requests",
        "pytz"
    ]

    def install_package(package):
        print(f"📦 Устанавливаю: {package}...", flush=True)

        try:
            subprocess.check_call([
                sys.executable,
                "-m",
                "pip",
                "install",
                package,
                "--quiet"
            ])

            print(f"✅ {package} установлен!", flush=True)
            return True

        except Exception as e:
            print(f"❌ Ошибка установки {package}: {e}", flush=True)
            return False


    def check_and_install_dependencies():

        print("=" * 60, flush=True)
        print("🔍 ПРОВЕРКА ЗАВИСИМОСТЕЙ...", flush=True)
        print("=" * 60, flush=True)

        missing = []

        for package in REQUIRED_PACKAGES:
            try:
                importlib.import_module(package.replace("-", "_"))
                print(f"✅ {package} - уже установлен", flush=True)

            except ImportError:
                print(f"⚠️ {package} - НЕ НАЙДЕН", flush=True)
                missing.append(package)

        if missing:

            print(
                f"\n📦 Нужно установить: {', '.join(missing)}",
                flush=True
            )

            for package in missing:
                if not install_package(package):
                    return False

        print("\n✅ ВСЕ ЗАВИСИМОСТИ УСТАНОВЛЕНЫ!", flush=True)
        print("=" * 60, flush=True)

        return True


    if not check_and_install_dependencies():
        sys.exit(1)

except Exception as e:
    print(f"⚠️ Ошибка проверки зависимостей: {e}", flush=True)


# =====================================================================
# ML
# =====================================================================

ML_AVAILABLE = False
ML_LIB = None

try:
    from sklearn.ensemble import RandomForestClassifier

    ML_AVAILABLE = True
    ML_LIB = "randomforest"

    print("✅ RandomForest загружен!", flush=True)

except ImportError:

    print(
        "⚠️ RandomForest не установлен. Работаем только на истории.",
        flush=True
    )


# =====================================================================
# ПЕРЕМЕННЫЕ ОКРУЖЕНИЯ
# =====================================================================

BOT_TOKEN = os.getenv("BOT_TOKEN")

if not BOT_TOKEN:
    BOT_TOKEN = os.getenv("BOT_TOKEN_PROGNOZ")

CHANNEL_STATS = os.getenv("CHANNEL_STATS")
CHANNEL_PROGNOZ = os.getenv("CHANNEL_PROGNOZ")

if not BOT_TOKEN or not CHANNEL_STATS or not CHANNEL_PROGNOZ:
    print("❌ ОШИБКА: переменные окружения не заданы!", flush=True)
    sys.exit(1)


# =====================================================================
# НАСТРОЙКИ
# =====================================================================

MOSCOW_TZ = pytz.timezone("Europe/Moscow")

BASE_URL = "https://1xlite-0687.pro"

DATA_FILE = "cards_data.json"
HISTORY_FILE = "cards_history.json"
ML_MODEL_FILE = "cards_model.pkl"
OFFSET_FILE = "cards_offset.txt"
GAME_HISTORY_FILE = "cards_game_history.json"
GAME_LATENCY_CACHE_FILE = "game_latency_cache.json"

MAX_RECORDS = 10000

CHECK_INTERVAL = 5

MIN_TRAIN_SAMPLES = 300

MAX_HISTORY = 2000
MAX_GAME_HISTORY = 30

DOGON_GAMES = 4

ML_CONFIDENCE_THRESHOLD = 0.20

LATENCY_CACHE_MAX_SIZE = 2000


# =====================================================================
# НАСТРОЙКИ ИСТОРИЧЕСКОГО ПОИСКА
# =====================================================================

# Максимальная разница задержки для похожей игры
MAX_LATENCY_DISTANCE = 150.0

# Идеальная близость задержки
GOOD_LATENCY_DISTANCE = 30.0

# Насколько далеко искать соседние номера
GAME_NUMBER_RADIUS = 10

# Вес исторического алгоритма
HISTORICAL_WEIGHT = 0.65

# Вес ML
ML_WEIGHT = 0.35

# Минимум найденных исторических игр
MIN_HISTORICAL_MATCHES = 5

# Максимум исторических аналогов
MAX_SIMILAR_GAMES = 300


# =====================================================================
# КАРТЫ
# =====================================================================

TARGET_CARDS = [
    "J♠️", "J♣️", "J♦️", "J♥️",
    "Q♠️", "Q♣️", "Q♦️", "Q♥️",
    "K♠️", "K♣️", "K♦️", "K♥️",
    "A♠️", "A♣️", "A♦️", "A♥️"
]

SUITS = ["♠️", "♣️", "♦️", "♥️"]

SUITS_NAMES = {
    0: "♠️",
    1: "♣️",
    2: "♦️",
    3: "♥️"
}

RANKS = {
    1: "A",
    2: "2",
    3: "3",
    4: "4",
    5: "5",
    6: "6",
    7: "7",
    8: "8",
    9: "9",
    10: "10",
    11: "J",
    12: "Q",
    13: "K"
}


HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36"
    ),
    "Accept": "application/json, text/plain, */*",
    "Referer": (
        f"{BASE_URL}/ru/live/twentyone/"
        "1643503-twentyone-game"
    ),
    "Cookie": (
        "platform_type=desktop; "
        "lng=ru; "
        "cookies_agree_type=3; "
        "tzo=3; "
        "is12h=0"
    )
}


# =====================================================================
# ГЛОБАЛЬНЫЕ ПЕРЕМЕННЫЕ
# =====================================================================

ml_model = None
ml_initialized = False

collection_active = True

game_history = deque(maxlen=MAX_GAME_HISTORY)

game_latency_cache = {}

processed_games = set()
finished_games = set()

all_messages = []

predictions = []


stats = {
    "total": 0,
    "win": 0,
    "lose": 0,

    "by_dogon": {
        0: 0,
        1: 0,
        2: 0,
        3: 0
    },

    "ml_wins": 0,
    "ml_losses": 0,

    "games_collected": 0,

    "card_hits": defaultdict(int)
}


# =====================================================================
# TELEGRAM
# =====================================================================

def get_updates(offset):

    url = f"https://api.telegram.org/bot{BOT_TOKEN}/getUpdates"

    params = {
        "offset": offset,
        "timeout": 30
    }

    try:

        response = requests.get(
            url,
            params=params,
            timeout=35
        )

        return response.json()

    except Exception as e:

        print(f"❌ Ошибка getUpdates: {e}", flush=True)

        return {}


def send_message(chat_id, text):

    url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"

    payload = {
        "chat_id": chat_id,
        "text": text,
        "parse_mode": "HTML"
    }

    try:

        response = requests.post(
            url,
            json=payload,
            timeout=10
        )

        if response.status_code == 200:
            return response.json()["result"]["message_id"]

        print(
            f"❌ Ошибка отправки: {response.status_code}",
            flush=True
        )

        return None

    except Exception as e:

        print(f"❌ Ошибка отправки: {e}", flush=True)

        return None


def edit_message(message_id, text):

    url = f"https://api.telegram.org/bot{BOT_TOKEN}/editMessageText"

    payload = {
        "chat_id": CHANNEL_PROGNOZ,
        "message_id": message_id,
        "text": text,
        "parse_mode": "HTML"
    }

    try:

        response = requests.post(
            url,
            json=payload,
            timeout=10
        )

        return response.status_code == 200

    except Exception as e:

        print(
            f"❌ Ошибка редактирования: {e}",
            flush=True
        )

        return False


def send_startup_message():

    data_count = len(load_data())

    now = datetime.now(MOSCOW_TZ)

    msg = f"""
🃏 ТОЧНАЯ КАРТА — ИСТОРИЯ + ML ТОП-2

📊 Собрано игр: {data_count}/{MAX_RECORDS}
🧠 ML: {'✅ АКТИВНА' if ml_initialized else '⏳ ОЖИДАЕТ'}
📚 Исторический поиск: ✅ АКТИВЕН
🎯 Прогноз: до начала игры
📈 Догон: {DOGON_GAMES - 1} игр
⏰ {now.strftime('%d.%m.%Y %H:%M:%S')}
"""

    send_message(CHANNEL_PROGNOZ, msg)


# =====================================================================
# РАБОТА С ДАННЫМИ
# =====================================================================

def load_data():

    if os.path.exists(DATA_FILE):

        try:

            with open(
                DATA_FILE,
                "r",
                encoding="utf-8"
            ) as f:

                data = json.load(f)

                if isinstance(data, list):
                    return data

        except Exception as e:

            print(
                f"⚠️ Ошибка загрузки данных: {e}",
                flush=True
            )

    return []


def save_data(record):

    global collection_active
    global stats

    data = load_data()

    if len(data) >= MAX_RECORDS:
        collection_active = False
        return data

    existing_index = None

    for i, r in enumerate(data):

        if r.get("game_id") == record.get("game_id"):

            existing_index = i
            break

    if existing_index is not None:

        data[existing_index] = record

    else:

        data.append(record)

        stats["games_collected"] += 1

    if len(data) >= MAX_RECORDS:

        collection_active = False

        print(
            f"⏸️ Достигнут лимит {MAX_RECORDS}",
            flush=True
        )

    with open(
        DATA_FILE,
        "w",
        encoding="utf-8"
    ) as f:

        json.dump(
            data,
            f,
            indent=2,
            ensure_ascii=False
        )

    return data


def load_history():

    if os.path.exists(HISTORY_FILE):

        try:

            with open(
                HISTORY_FILE,
                "r",
                encoding="utf-8"
            ) as f:

                return json.load(f)

        except:
            pass

    return []


def save_history(history):

    if len(history) > MAX_HISTORY:
        history = history[-MAX_HISTORY:]

    with open(
        HISTORY_FILE,
        "w",
        encoding="utf-8"
    ) as f:

        json.dump(
            history,
            f,
            indent=2,
            ensure_ascii=False
        )


def get_offset():

    if os.path.exists(OFFSET_FILE):

        try:

            with open(
                OFFSET_FILE,
                "r"
            ) as f:

                return int(f.read().strip())

        except:
            return 0

    return 0


def save_offset(offset):

    with open(
        OFFSET_FILE,
        "w"
    ) as f:

        f.write(str(offset))


# =====================================================================
# ИСТОРИЯ ПОСЛЕДНИХ ЗАДЕРЖЕК
# =====================================================================

def load_game_history():

    if os.path.exists(GAME_HISTORY_FILE):

        try:

            with open(
                GAME_HISTORY_FILE,
                "r",
                encoding="utf-8"
            ) as f:

                data = json.load(f)

                return deque(
                    data,
                    maxlen=MAX_GAME_HISTORY
                )

        except:
            pass

    return deque(maxlen=MAX_GAME_HISTORY)


def save_game_history():

    try:

        with open(
            GAME_HISTORY_FILE,
            "w",
            encoding="utf-8"
        ) as f:

            json.dump(
                list(game_history),
                f,
                indent=2,
                ensure_ascii=False
            )

    except:
        pass


def update_game_history(latency, game_num):

    global game_history

    game_history.append({
        "latency": latency,
        "game_num": game_num,
        "timestamp": datetime.now(
            MOSCOW_TZ
        ).isoformat()
    })

    save_game_history()


# =====================================================================
# КЭШ ЗАДЕРЖЕК
# =====================================================================

def load_latency_cache():

    global game_latency_cache

    if os.path.exists(GAME_LATENCY_CACHE_FILE):

        try:

            with open(
                GAME_LATENCY_CACHE_FILE,
                "r",
                encoding="utf-8"
            ) as f:

                game_latency_cache = json.load(f)

                print(
                    f"📊 Загружено задержек: "
                    f"{len(game_latency_cache)}",
                    flush=True
                )

                return True

        except Exception as e:

            print(
                f"⚠️ Ошибка загрузки задержек: {e}",
                flush=True
            )

    game_latency_cache = {}

    return False


def save_latency_cache():

    global game_latency_cache

    try:

        if len(game_latency_cache) > LATENCY_CACHE_MAX_SIZE:

            sorted_items = sorted(
                game_latency_cache.items(),
                key=lambda x: x[1].get(
                    "timestamp",
                    ""
                ),
                reverse=True
            )[:LATENCY_CACHE_MAX_SIZE]

            game_latency_cache = dict(sorted_items)

        with open(
            GAME_LATENCY_CACHE_FILE,
            "w",
            encoding="utf-8"
        ) as f:

            json.dump(
                game_latency_cache,
                f,
                indent=2,
                ensure_ascii=False
            )

        return True

    except Exception as e:

        print(
            f"⚠️ Ошибка сохранения кэша: {e}",
            flush=True
        )

        return False


def cache_game_latency(
    game_id,
    latency,
    game_number
):

    global game_latency_cache

    if game_id in game_latency_cache:
        return False

    game_latency_cache[game_id] = {
        "latency": latency,
        "game_number": game_number,
        "timestamp": datetime.now(
            MOSCOW_TZ
        ).isoformat()
    }

    save_latency_cache()

    print(
        f"📊 Первая задержка "
        f"{latency:.1f}мс "
        f"для #{game_number}",
        flush=True
    )

    return True


# =====================================================================
# ПОРЯДКОВЫЙ НОМЕР ИГРЫ
#
# 03:00 = 1
# 03:01 = 2
# ...
# 02:59 = 1440
# =====================================================================

def get_game_number_by_time():

    now = datetime.now(MOSCOW_TZ)

    start = now.replace(
        hour=3,
        minute=0,
        second=0,
        microsecond=0
    )

    if now < start:
        start -= timedelta(days=1)

    diff_minutes = (
        now - start
    ).total_seconds() / 60

    game_number = (
        int(diff_minutes) % 1440
    ) + 1

    return game_number


def get_game_number_from_timestamp(timestamp):

    if not timestamp:
        return None

    try:

        if isinstance(timestamp, (int, float)):

            start_time = datetime.fromtimestamp(
                timestamp,
                MOSCOW_TZ
            )

        else:

            start_time = datetime.fromisoformat(
                str(timestamp).replace(
                    "Z",
                    "+00:00"
                )
            ).astimezone(MOSCOW_TZ)

    except:
        return None

    start_day = start_time.replace(
        hour=3,
        minute=0,
        second=0,
        microsecond=0
    )

    if start_time < start_day:
        start_day -= timedelta(days=1)

    diff_minutes = (
        start_time - start_day
    ).total_seconds() / 60

    return int(diff_minutes) % 1440 + 1


# =====================================================================
# API АКТИВНЫХ ИГР
# =====================================================================

def get_active_games():

    try:

        url = (
            f"{BASE_URL}/service-api/"
            "main-live-feed/v3/games1x2?"
            "cfView=3&count=40&fcountry=190"
            "&gr=415&grMode=4&lng=ru"
            "&ref=7"
            "&selectedMs=1.146.1643503,"
            "10.146.1643503"
        )

        response = requests.get(
            url,
            headers=HEADERS,
            timeout=10
        )

        if response.status_code != 200:
            return []

        data = response.json()

        if isinstance(data, dict):
            games = data.get("Value", [])

        elif isinstance(data, list):
            games = data

        else:
            return []

        active_games = []

        for game in games:

            if game.get(
                "liga",
                {}
            ).get("id") == 1643503:

                if game.get("id"):
                    active_games.append(game)

        return active_games

    except Exception as e:

        print(
            f"❌ Ошибка API: {e}",
            flush=True
        )

        return []


def get_game_data(game_id):

    url = (
        f"{BASE_URL}/service-api/"
        "LiveFeed/GetGameZip?"
        f"id={game_id}"
        "&isSubGames=true"
        "&GroupEvents=true"
        "&countevents=250"
        "&grMode=4"
        "&partner=7"
        "&topGroups="
        "&country=190"
        "&marketType=1"
        "&isNewBuilder=true"
    )

    try:

        start_time = time.time()

        response = requests.get(
            url,
            headers=HEADERS,
            timeout=5
        )

        end_time = time.time()

        latency = (
            end_time - start_time
        ) * 1000

        if response.status_code == 200:

            return (
                response.json(),
                latency,
                start_time,
                end_time
            )

        return None, None, None, None

    except Exception as e:

        print(
            f"❌ Ошибка игры {game_id}: {e}",
            flush=True
        )

        return None, None, None, None


# =====================================================================
# ПАРСИНГ ИГРЫ
# =====================================================================

def parse_cards_and_state(data):

    if not data or not isinstance(data, dict):
        return [], [], None

    sc = data.get("Value", {})

    if not isinstance(sc, dict):
        return [], [], None

    sc = sc.get("SC", {})

    if not isinstance(sc, dict):
        return [], [], None

    player_cards = []
    dealer_cards = []
    state = None

    for item in sc.get("S", []):

        if not isinstance(item, dict):
            continue

        if item.get("Key") == "P1":

            try:
                player_cards = json.loads(
                    item.get("Value", "[]")
                )
            except:
                player_cards = []

        if item.get("Key") == "P2":

            try:
                dealer_cards = json.loads(
                    item.get("Value", "[]")
                )
            except:
                dealer_cards = []

        if item.get("Key") == "STATE":
            state = item.get("Value")

    return (
        player_cards,
        dealer_cards,
        state
    )


# =====================================================================
# ПАРСИНГ TELEGRAM РЕЗУЛЬТАТА
# =====================================================================

def parse_game_from_text(text):

    try:

        game_match = re.search(
            r"#N(\d+)",
            text
        )

        if not game_match:
            return None

        game_number = int(
            game_match.group(1)
        )

        if "◀️" in text:
            parts = text.split("◀️")

        elif "▶️" in text:
            parts = text.split("▶️")

        elif " - " in text:
            parts = text.split(" - ")

        elif "—" in text:
            parts = text.split("—")

        else:
            return None

        if len(parts) < 2:
            return None

        def parse_cards(part):

            match = re.search(
                r"\(([^)]*)\)",
                part
            )

            if not match:
                return []

            cards_str = match.group(1)

            cards = []

            pattern = (
                r"(10|[2-9AJQK])"
                r"([♠♣♦♥])"
            )

            matches = re.findall(
                pattern,
                cards_str
            )

            for rank, suit in matches:

                suit_map = {
                    "♠": "♠️",
                    "♣": "♣️",
                    "♦": "♦️",
                    "♥": "♥️"
                }

                cards.append({
                    "rank": rank,
                    "suit": suit_map.get(
                        suit,
                        suit
                    )
                })

            return cards

        return {
            "number": game_number,
            "player_cards": parse_cards(parts[0]),
            "dealer_cards": parse_cards(parts[1]),
            "text": text
        }

    except Exception as e:

        print(
            f"❌ Ошибка парсинга: {e}",
            flush=True
        )

        return None


def is_finished_game_text(text):

    return (
        "✅" in text
        or "🔰" in text
    )


# =====================================================================
# БУДУЩИЕ ИГРЫ
# =====================================================================

def get_upcoming_games():

    try:

        url = (
            f"{BASE_URL}/service-api/"
            "main-live-feed/v3/leftMenuSports?"
            "fcountry=1"
            "&gr=415"
            "&lng=ru"
            "&ref=7"
            "&selectedMs=10.146.1643503"
        )

        response = requests.get(
            url,
            headers=HEADERS,
            timeout=10
        )

        if response.status_code != 200:
            return []

        data = response.json()

        upcoming_games = []

        now = datetime.now(MOSCOW_TZ)

        if not isinstance(data, list):
            return []

        for section in data:

            if section.get("menuSectionId") != 10:
                continue

            for sport in section.get(
                "sports",
                []
            ):

                if sport.get("id") != 146:
                    continue

                for liga in sport.get(
                    "ligas",
                    []
                ):

                    if liga.get("id") != 1643503:
                        continue

                    for game in liga.get(
                        "games",
                        []
                    ):

                        if game.get("nonStarted") != True:
                            continue

                        start_ts = game.get("startTs")

                        if not start_ts:
                            continue

                        game_num = (
                            get_game_number_from_timestamp(
                                start_ts
                            )
                        )

                        if not game_num:
                            continue

                        start_time = (
                            datetime.fromtimestamp(
                                start_ts,
                                MOSCOW_TZ
                            )
                        )

                        minutes_until = (
                            start_time - now
                        ).total_seconds() / 60

                        if 0 < minutes_until <= 5:

                            upcoming_games.append({

                                "game_id": str(
                                    game.get("id")
                                ),

                                "game_num": game_num,

                                "start_time": start_time,

                                "minutes_until": (
                                    minutes_until
                                ),

                                "start_ts": start_ts
                            })

        return upcoming_games

    except Exception as e:

        print(
            f"❌ Ошибка будущих игр: {e}",
            flush=True
        )

        return []


# =====================================================================
# ФОРМИРОВАНИЕ ПРЕМАТЧ ПРИЗНАКОВ
#
# ВАЖНО:
# НИКАКИХ КАРТ БУДУЩЕЙ ИГРЫ ЗДЕСЬ НЕТ
# =====================================================================

def extract_prematch_features(
    latency,
    game_num
):

    now = datetime.now(MOSCOW_TZ)

    features = {

        "latency": float(latency),

        "game_num": float(game_num),

        "game_num_sin": math.sin(
            2 * math.pi * game_num / 1440
        ),

        "game_num_cos": math.cos(
            2 * math.pi * game_num / 1440
        ),

        "hour": float(now.hour),

        "minute": float(now.minute),

        "day_of_week": float(
            now.weekday()
        ),

        "is_weekend": float(
            1 if now.weekday() >= 5 else 0
        ),

        "prev_latency": 0.0,

        "latency_delta": 0.0,

        "latency_trend": 0.0
    }

    if len(game_history) >= 1:

        last_latency = game_history[-1].get(
            "latency",
            latency
        )

        features[
            "prev_latency"
        ] = float(last_latency)

        features[
            "latency_delta"
        ] = float(latency - last_latency)

    if len(game_history) >= 5:

        recent = [
            x.get("latency", 0)
            for x in list(game_history)[-5:]
        ]

        if len(recent) >= 2:

            features[
                "latency_trend"
            ] = (
                recent[-1] - recent[0]
            ) / len(recent)

    return features


# =====================================================================
# ПОЛУЧЕНИЕ КАРТ ИЗ ИСТОРИЧЕСКОЙ ЗАПИСИ
# =====================================================================

def get_target_cards_from_record(record):

    cards = []

    all_cards = (
        record.get(
            "player_cards",
            []
        )
        +
        record.get(
            "dealer_cards",
            []
        )
    )

    for card in all_cards:

        rank = card.get("rank", "")
        suit = card.get("suit", "")

        card_str = rank + suit

        if card_str in TARGET_CARDS:
            cards.append(card_str)

    return list(set(cards))


# =====================================================================
# РАССТОЯНИЕ МЕЖДУ ПОРЯДКОВЫМИ НОМЕРАМИ
#
# УЧИТЫВАЕТ ЦИКЛ 1-1440
# =====================================================================

def circular_game_distance(a, b):

    diff = abs(int(a) - int(b))

    return min(
        diff,
        1440 - diff
    )


# =====================================================================
# ПОИСК ИСТОРИЧЕСКИХ АНАЛОГОВ
#
# ОСНОВА НОВОЙ ЛОГИКИ
# =====================================================================

def find_similar_historical_games(
    current_latency,
    current_game_num
):

    data = load_data()

    if not data:
        return []

    matches = []

    for record in data:

        historical_latency = record.get(
            "latency_ms",
            None
        )

        historical_game_num = record.get(
            "game_number",
            None
        )

        if historical_latency is None:
            continue

        if historical_game_num is None:
            continue

        try:

            historical_latency = float(
                historical_latency
            )

            historical_game_num = int(
                historical_game_num
            )

        except:
            continue

        cards = get_target_cards_from_record(
            record
        )

        if not cards:
            continue

        latency_distance = abs(
            current_latency -
            historical_latency
        )

        game_distance = circular_game_distance(
            current_game_num,
            historical_game_num
        )

        # Слишком далекая задержка
        if latency_distance > MAX_LATENCY_DISTANCE:
            continue

        # Номер игры далеко
        if game_distance > GAME_NUMBER_RADIUS:
            continue

        # -------------------------------------------------------------
        # ВЕС ЗАДЕРЖКИ
        # -------------------------------------------------------------

        latency_score = max(
            0.0,
            1.0 -
            latency_distance /
            MAX_LATENCY_DISTANCE
        )

        # Усиливаем очень близкие задержки
        if latency_distance <= GOOD_LATENCY_DISTANCE:

            latency_score += (
                1.0 -
                latency_distance /
                GOOD_LATENCY_DISTANCE
            ) * 0.5

        # -------------------------------------------------------------
        # ВЕС НОМЕРА ИГРЫ
        # -------------------------------------------------------------

        game_score = max(
            0.0,
            1.0 -
            game_distance /
            (GAME_NUMBER_RADIUS + 1)
        )

        # Точное совпадение номера
        if game_distance == 0:
            game_score += 0.75

        # -------------------------------------------------------------
        # ОБЩИЙ ВЕС
        #
        # задержка = 60%
        # порядковый номер = 40%
        # -------------------------------------------------------------

        similarity = (
            latency_score * 0.60
            +
            game_score * 0.40
        )

        matches.append({

            "record": record,

            "cards": cards,

            "latency_distance": (
                latency_distance
            ),

            "game_distance": (
                game_distance
            ),

            "similarity": similarity
        })

    matches.sort(
        key=lambda x: x["similarity"],
        reverse=True
    )

    return matches[
        :MAX_SIMILAR_GAMES
    ]


# =====================================================================
# ИСТОРИЧЕСКИЙ ПРОГНОЗ
# =====================================================================

def historical_prediction(
    latency,
    game_num
):

    matches = find_similar_historical_games(
        latency,
        game_num
    )

    if not matches:

        print(
            "⚠️ Исторических аналогов не найдено",
            flush=True
        )

        return None, {}, 0

    card_scores = defaultdict(float)

    total_weight = 0.0

    for match in matches:

        weight = match["similarity"]

        cards = match["cards"]

        if not cards:
            continue

        # Вес распределяем между картами игры
        per_card_weight = (
            weight / len(cards)
        )

        for card in cards:

            card_scores[card] += (
                per_card_weight
            )

        total_weight += weight

    if not card_scores:

        return None, {}, len(matches)

    total_score = sum(
        card_scores.values()
    )

    probabilities = {}

    for card, score in card_scores.items():

        probabilities[card] = (
            score / total_score
            if total_score > 0
            else 0
        )

    sorted_cards = sorted(
        probabilities.items(),
        key=lambda x: x[1],
        reverse=True
    )

    top_cards = sorted_cards[:2]

    print(
        f"\n📚 ИСТОРИЧЕСКИЙ ПОИСК",
        flush=True
    )

    print(
        f"   Найдено аналогов: {len(matches)}",
        flush=True
    )

    for i, (card, prob) in enumerate(
        top_cards,
        1
    ):

        print(
            f"   {i}. {card} — "
            f"{prob * 100:.2f}%",
            flush=True
        )

    return (
        top_cards,
        probabilities,
        len(matches)
    )


# =====================================================================
# ПОДГОТОВКА ОБУЧАЮЩИХ ДАННЫХ
#
# КАРТЫ ИГРЫ = TARGET
# КАРТЫ НИКОГДА НЕ ЯВЛЯЮТСЯ ПРИЗНАКАМИ
# =====================================================================

def build_training_features(
    record
):

    latency = record.get(
        "latency_ms",
        0
    )

    game_num = record.get(
        "game_number",
        0
    )

    if not game_num:
        return None

    timestamp_str = record.get(
        "timestamp_msk",
        ""
    )

    hour = 0
    minute = 0

    try:

        if timestamp_str:

            parts = (
                timestamp_str
                .split(":")
            )

            if len(parts) >= 2:

                hour = int(parts[0])
                minute = int(parts[1])

    except:
        pass

    features = {

        "latency": float(latency),

        "game_num": float(game_num),

        "game_num_sin": math.sin(
            2 * math.pi *
            int(game_num) / 1440
        ),

        "game_num_cos": math.cos(
            2 * math.pi *
            int(game_num) / 1440
        ),

        "hour": float(hour),

        "minute": float(minute),

        # Исторические записи могут не иметь
        # точной даты, поэтому не используем
        # weekday как обязательный признак

        "day_of_week": 0.0,

        "is_weekend": 0.0,

        "prev_latency": 0.0,

        "latency_delta": 0.0,

        "latency_trend": 0.0
    }

    return features


# =====================================================================
# ОБУЧЕНИЕ ML
# =====================================================================

def train_ml_model():

    global ml_model
    global ml_initialized

    if not ML_AVAILABLE:
        return False

    data = load_data()

    if len(data) < MIN_TRAIN_SAMPLES:

        print(
            f"⚠️ ML недостаточно игр: "
            f"{len(data)}/{MIN_TRAIN_SAMPLES}",
            flush=True
        )

        return False

    X = []
    y = []

    feature_names = None

    print(
        f"🧠 ML: обучение на "
        f"{len(data)} исторических играх...",
        flush=True
    )

    for record in data:

        features = build_training_features(
            record
        )

        if not features:
            continue

        cards = get_target_cards_from_record(
            record
        )

        if not cards:
            continue

        if feature_names is None:

            feature_names = sorted(
                features.keys()
            )

        feature_vector = [
            features[key]
            for key in feature_names
        ]

        # Каждая целевая карта становится
        # отдельным обучающим примером
        for card in cards:

            if card not in TARGET_CARDS:
                continue

            X.append(feature_vector)

            y.append(
                TARGET_CARDS.index(card)
            )

    if len(X) < MIN_TRAIN_SAMPLES:

        print(
            f"⚠️ ML недостаточно примеров: "
            f"{len(X)}",
            flush=True
        )

        return False

    X = np.array(X)
    y = np.array(y)

    print(
        f"🧠 ML обучается на {len(X)} "
        f"примерах",
        flush=True
    )

    model = RandomForestClassifier(

        n_estimators=300,

        max_depth=12,

        min_samples_leaf=3,

        random_state=42,

        n_jobs=1,

        class_weight="balanced_subsample"
    )

    model.fit(X, y)

    ml_model = model
    ml_initialized = True

    try:

        with open(
            ML_MODEL_FILE,
            "wb"
        ) as f:

            pickle.dump({

                "model": model,

                "feature_names": (
                    feature_names
                ),

                "train_samples": len(X),

                "total_games": len(data)

            }, f)

        print(
            f"✅ ML обучена "
            f"на {len(X)} примерах",
            flush=True
        )

        return True

    except Exception as e:

        print(
            f"⚠️ Ошибка сохранения ML: {e}",
            flush=True
        )

        return False


# =====================================================================
# ЗАГРУЗКА ML
# =====================================================================

def load_ml_model():

    global ml_model
    global ml_initialized

    if not ML_AVAILABLE:
        return False

    if not os.path.exists(
        ML_MODEL_FILE
    ):
        return False

    try:

        with open(
            ML_MODEL_FILE,
            "rb"
        ) as f:

            saved = pickle.load(f)

        ml_model = saved["model"]

        ml_initialized = True

        print(
            "✅ ML модель загружена",
            flush=True
        )

        return True

    except Exception as e:

        print(
            f"⚠️ Ошибка загрузки ML: {e}",
            flush=True
        )

        return False


# =====================================================================
# ML ПРОГНОЗ
# =====================================================================

def predict_ml(
    latency,
    game_num
):

    if not ml_initialized or ml_model is None:

        return None, {}

    try:

        features = extract_prematch_features(
            latency,
            game_num
        )

        vector = np.array([[
            features[key]
            for key in sorted(
                features.keys()
            )
        ]])

        raw_probs = (
            ml_model.predict_proba(
                vector
            )[0]
        )

        # Важно:
        # classes_ может содержать не все 16 карт
        class_probabilities = {}

        for class_index, probability in zip(
            ml_model.classes_,
            raw_probs
        ):

            if (
                0 <= int(class_index)
                < len(TARGET_CARDS)
            ):

                card = TARGET_CARDS[
                    int(class_index)
                ]

                class_probabilities[card] = (
                    float(probability)
                )

        sorted_cards = sorted(
            class_probabilities.items(),
            key=lambda x: x[1],
            reverse=True
        )

        return (
            sorted_cards[:2],
            class_probabilities
        )

    except Exception as e:

        print(
            f"⚠️ Ошибка ML прогноза: {e}",
            flush=True
        )

        return None, {}


# =====================================================================
# ОБЪЕДИНЕНИЕ ИСТОРИИ + ML
# =====================================================================

def get_prediction(
    latency,
    game_num
):

    # -------------------------------------------------------------
    # 1. ИСТОРИЧЕСКИЙ ПОИСК
    # -------------------------------------------------------------

    historical_top, historical_probs, matches_count = (
        historical_prediction(
            latency,
            game_num
        )
    )

    # -------------------------------------------------------------
    # 2. ML
    # -------------------------------------------------------------

    ml_top, ml_probs = predict_ml(
        latency,
        game_num
    )

    print(
        "\n🤖 ML ПРОГНОЗ",
        flush=True
    )

    if ml_top:

        for i, (card, prob) in enumerate(
            ml_top,
            1
        ):

            print(
                f"   {i}. {card} — "
                f"{prob * 100:.2f}%",
                flush=True
            )

    else:

        print(
            "   ML пока недоступна",
            flush=True
        )

    # -------------------------------------------------------------
    # 3. ОБЪЕДИНЯЕМ
    # -------------------------------------------------------------

    combined_scores = defaultdict(float)

    # История
    for card, prob in historical_probs.items():

        combined_scores[card] += (
            prob * HISTORICAL_WEIGHT
        )

    # ML
    for card, prob in ml_probs.items():

        combined_scores[card] += (
            prob * ML_WEIGHT
        )

    # Если ML нет — работаем только историей
    if not ml_probs and historical_probs:

        combined_scores = defaultdict(
            float,
            historical_probs
        )

    # Если истории нет — работаем ML
    if not historical_probs and ml_probs:

        combined_scores = defaultdict(
            float,
            ml_probs
        )

    if not combined_scores:

        return (
            None,
            None,
            None,
            matches_count
        )

    total = sum(
        combined_scores.values()
    )

    normalized = []

    for card, score in combined_scores.items():

        probability = (
            score / total
            if total > 0
            else 0
        )

        normalized.append(
            (card, probability)
        )

    normalized.sort(
        key=lambda x: x[1],
        reverse=True
    )

    top_cards = normalized[:2]

    confidence = (
        top_cards[0][1]
        if top_cards
        else 0
    )

    print(
        "\n🔥 ИТОГОВЫЙ ПРОГНОЗ",
        flush=True
    )

    for i, (card, prob) in enumerate(
        top_cards,
        1
    ):

        print(
            f"   {i}. {card} — "
            f"{prob * 100:.2f}%",
            flush=True
        )

    print(
        f"📊 Исторических аналогов: "
        f"{matches_count}",
        flush=True
    )

    return (
        top_cards,
        "history+ml",
        confidence,
        matches_count
    )


# =====================================================================
# ПРОВЕРКА БУДУЩИХ ИГР (ИСПРАВЛЕНА)
# =====================================================================

def check_upcoming_games():

    global predictions

    upcoming = get_upcoming_games()

    if not upcoming:
        return

    for game in upcoming:

        game_num = game.get("game_num")
        game_id = game.get("game_id")

        if not game_num or not game_id:
            continue

        # ============================================================
        # 🔥 ПРОВЕРКА: ЕСТЬ ЛИ УЖЕ ПРОГНОЗ НА ЭТУ ИГРУ?
        # ============================================================
        already_predicted = False
        for entry in predictions:
            if (
                entry.get("target") == game_num
                and entry.get("status") in ("pending", "win", "lose")
            ):
                already_predicted = True
                break

        if already_predicted:
            print(f"⏭️ Прогноз на #{game_num} уже существует", flush=True)
            continue

        print(
            f"\n🔥 БУДУЩАЯ ИГРА #{game_num}",
            flush=True
        )

        print(
            "📡 Замеряю первую задержку...",
            flush=True
        )

        # ---------------------------------------------------------
        # ЗАМЕРЯЕМ ЗАДЕРЖКУ
        # ---------------------------------------------------------

        _, measured_latency, _, _ = (
            get_game_data(game_id)
        )

        if measured_latency is not None:

            latency = measured_latency

            if game_id not in game_latency_cache:

                cache_game_latency(
                    game_id,
                    latency,
                    game_num
                )

        else:

            latency = 500.0

            print(
                "⚠️ Использую задержку "
                "по умолчанию 500мс",
                flush=True
            )

        # ---------------------------------------------------------
        # ОБНОВЛЯЕМ ИСТОРИЮ ЗАДЕРЖЕК
        # ---------------------------------------------------------

        update_game_history(
            latency,
            game_num
        )

        # ---------------------------------------------------------
        # ПРОГНОЗ
        #
        # ВАЖНО:
        # НИКАКИЕ КАРТЫ БУДУЩЕЙ ИГРЫ НЕ ЧИТАЕМ
        # ---------------------------------------------------------

        (
            predicted_cards,
            method,
            confidence,
            matches_count
        ) = get_prediction(
            latency,
            game_num
        )

        if (
            not predicted_cards
            or len(predicted_cards) < 2
        ):

            print(
                f"⏭️ Нет прогноза "
                f"для #{game_num}",
                flush=True
            )

            continue

        # ---------------------------------------------------------
        # ФОРМИРУЕМ TELEGRAM
        # ---------------------------------------------------------

        total_prob = sum(
            prob
            for _, prob
            in predicted_cards
        )

        msg = (
            "🔮 ТОЧНАЯ КАРТА "
            "(ИСТОРИЯ + ML ТОП-2)\n\n"
        )

        msg += f"🎯 Целевая игра: #N{game_num}\n"

        msg += (
            f"🤖 Метод: "
            f"История + ML\n"
        )

        msg += (
            f"📚 Найдено аналогов: "
            f"{matches_count}\n"
        )

        msg += (
            f"⏰ Прогноз: "
            f"{datetime.now(MOSCOW_TZ).strftime('%H:%M:%S')}"
            "\n\n"
        )

        msg += "📊 Топ-2 карты:\n\n"

        cards_list = []

        for i, (card, prob) in enumerate(
            predicted_cards,
            1
        ):

            cards_list.append(card)

            msg += (
                f"  {i}️⃣ {card} — "
                f"{prob * 100:.1f}%\n"
            )

        msg += (
            f"\n📊 Суммарная вероятность: "
            f"{total_prob * 100:.1f}%"
        )

        msg += (
            f"\n📈 Догон: "
            f"{DOGON_GAMES - 1} игр"
        )

        msg += (
            "\n📍 Ищем: любую позицию "
            "(игрок/дилер)"
        )

        # ---------------------------------------------------------
        # ОТПРАВЛЯЕМ
        # ---------------------------------------------------------

        message_id = send_message(
            CHANNEL_PROGNOZ,
            msg
        )

        if message_id:

            entry = {

                "source": game_num,

                "target": game_num,

                "cards": cards_list,

                "method": method,

                "message_id": message_id,

                "original_text": msg,

                "status": "pending",

                "latency": latency,

                "confidence": confidence,

                "historical_matches": (
                    matches_count
                ),

                "created": datetime.now(
                    MOSCOW_TZ
                ).isoformat()
            }

            predictions.append(entry)

            if len(predictions) > 200:

                predictions = predictions[-200:]

            save_history(predictions)

            print(
                f"\n✅ ПРОГНОЗ ОТПРАВЛЕН "
                f"#{game_num}",
                flush=True
            )

            print(
                f"🎯 {cards_list}",
                flush=True
            )


# =====================================================================
# ПРОВЕРКА РЕЗУЛЬТАТОВ
# =====================================================================

def check_results():

    global predictions
    global stats
    global all_messages

    if not predictions or not all_messages:
        return

    games_by_number = {}

    for msg in all_messages:

        if isinstance(msg, tuple):
            text = msg[0]
        else:
            text = msg

        if not isinstance(text, str):
            continue

        if "#N" not in text:
            continue

        if not is_finished_game_text(text):
            continue

        match = re.search(
            r"#N(\d+)",
            text
        )

        if not match:
            continue

        game_number = int(
            match.group(1)
        )

        games_by_number[
            game_number
        ] = text

    if not games_by_number:
        return

    current_game_number = (
        get_game_number_by_time()
    )

    for entry in predictions:

        if entry.get("status") != "pending":
            continue

        target = entry.get("target")

        predicted_cards = entry.get(
            "cards",
            []
        )

        message_id = entry.get(
            "message_id"
        )

        original_text = entry.get(
            "original_text",
            ""
        )

        if (
            target is None
            or not predicted_cards
            or not message_id
        ):
            continue

        # ---------------------------------------------------------
        # ПРОСРОЧКА
        # ---------------------------------------------------------

        if (
            current_game_number >
            target + DOGON_GAMES + 5
        ):

            entry["status"] = "expired"

            result_text = (
                "\n\n⏰ ПРОСРОЧЕН"
            )

            edit_message(
                message_id,
                original_text + result_text
            )

            save_history(predictions)

            continue

        found = False
        found_card = None
        found_game = None
        found_dogon = None

        games_found = 0

        last_actual_cards = []

        # ---------------------------------------------------------
        # ПРОВЕРЯЕМ ДОГОН
        # ---------------------------------------------------------

        for i in range(DOGON_GAMES):

            game_to_check = target + i

            if game_to_check > 1440:
                game_to_check -= 1440

            if game_to_check not in games_by_number:

                continue

            games_found += 1

            game_msg = games_by_number[
                game_to_check
            ]

            game_data = parse_game_from_text(
                game_msg
            )

            if not game_data:
                continue

            all_cards = (
                game_data.get(
                    "player_cards",
                    []
                )
                +
                game_data.get(
                    "dealer_cards",
                    []
                )
            )

            actual_cards = []

            for card in all_cards:

                rank = card.get(
                    "rank",
                    ""
                )

                suit = card.get(
                    "suit",
                    ""
                )

                card_str = rank + suit

                if card_str:
                    actual_cards.append(
                        card_str
                    )

                if card_str in predicted_cards:

                    found = True

                    found_card = card_str

                    found_game = game_to_check

                    found_dogon = i

                    break

            last_actual_cards = actual_cards

            if found:
                break

        # ---------------------------------------------------------
        # ЗАШЛО
        # ---------------------------------------------------------

        if found:

            print(
                f"🎯 ПРОГНОЗ ЗАШЁЛ! "
                f"{found_card} "
                f"в #{found_game}",
                flush=True
            )

            stats["total"] += 1
            stats["win"] += 1

            stats["by_dogon"][
                found_dogon
            ] = (
                stats["by_dogon"].get(
                    found_dogon,
                    0
                )
                + 1
            )

            stats["ml_wins"] += 1

            stats["card_hits"][
                found_card
            ] += 1

            result_text = "\n\n✅ ЗАШЛО"

            if found_dogon > 0:

                result_text += (
                    f" НА ДОГОНЕ "
                    f"{found_dogon}"
                )

            result_text += (
                f"\n🎯 Игра: "
                f"#{found_game}"
            )

            result_text += (
                f"\n🃏 Выпала: "
                f"{found_card}"
            )

            edit_message(
                message_id,
                original_text + result_text
            )

            entry["status"] = "win"

            entry["result_game"] = found_game

            entry["dogon"] = found_dogon

            entry["found_card"] = found_card

            entry["checked_at"] = datetime.now(
                MOSCOW_TZ
            ).isoformat()

            save_history(predictions)

            continue

        # ---------------------------------------------------------
        # ПРОВЕРЯЕМ ЗАВЕРШЕНИЕ ДОГОНА
        # ---------------------------------------------------------

        if games_found < DOGON_GAMES:

            continue

        stats["total"] += 1
        stats["lose"] += 1
        stats["ml_losses"] += 1

        last_required_game = (
            target + DOGON_GAMES - 1
        )

        if last_required_game > 1440:
            last_required_game -= 1440

        result_text = (
            "\n\n❌ НЕ ЗАШЛО"
            f"\n🔍 Проверено игр: "
            f"{DOGON_GAMES}"
        )

        edit_message(
            message_id,
            original_text + result_text
        )

        entry["status"] = "lose"

        entry["checked_at"] = datetime.now(
            MOSCOW_TZ
        ).isoformat()

        save_history(predictions)


# =====================================================================
# СБОР ДАННЫХ
# =====================================================================

def collect_game_data():

    global collection_active
    global finished_games

    if not collection_active:
        return

    active_games = get_active_games()

    if not active_games:
        return

    data = load_data()

    if len(data) >= MAX_RECORDS:

        collection_active = False

        return

    for game in active_games:

        game_id = str(
            game.get("id")
        )

        if game_id in finished_games:
            continue

        (
            game_data,
            latency,
            start_time,
            end_time
        ) = get_game_data(game_id)

        if not game_data:
            continue

        # ---------------------------------------------------------
        # ПОРЯДКОВЫЙ НОМЕР
        # ---------------------------------------------------------

        game_number = (
            get_game_number_by_time()
        )

        # ---------------------------------------------------------
        # СОХРАНЯЕМ ПЕРВУЮ ЗАДЕРЖКУ
        # ---------------------------------------------------------

        if latency is not None:

            if game_id not in game_latency_cache:

                cache_game_latency(
                    game_id,
                    latency,
                    game_number
                )

            else:

                latency = (
                    game_latency_cache[
                        game_id
                    ].get(
                        "latency",
                        latency
                    )
                )

        (
            player_cards,
            dealer_cards,
            state
        ) = parse_cards_and_state(
            game_data
        )

        if player_cards or dealer_cards:

            timestamp = datetime.fromtimestamp(
                start_time,
                MOSCOW_TZ
            )

            timestamp_msk_str = (
                timestamp.strftime(
                    "%H:%M:%S.%f"
                )[:-3]
            )

            def format_card(c):

                return {

                    "rank": RANKS.get(
                        c.get("CV", 0),
                        "?"
                    ),

                    "suit": SUITS_NAMES.get(
                        c.get("CS", 0),
                        "?"
                    )
                }

            sequence = []

            max_len = max(
                len(player_cards),
                len(dealer_cards)
            )

            for i in range(max_len):

                if i < len(player_cards):

                    pc = player_cards[i]

                    sequence.append({

                        "position": i * 2 + 1,

                        "who": "P",

                        "rank": RANKS.get(
                            pc.get("CV", 0),
                            "?"
                        ),

                        "suit": SUITS_NAMES.get(
                            pc.get("CS", 0),
                            "?"
                        )
                    })

                if i < len(dealer_cards):

                    dc = dealer_cards[i]

                    sequence.append({

                        "position": i * 2 + 2,

                        "who": "D",

                        "rank": RANKS.get(
                            dc.get("CV", 0),
                            "?"
                        ),

                        "suit": SUITS_NAMES.get(
                            dc.get("CS", 0),
                            "?"
                        )
                    })

            record = {

                "game_id": game_id,

                "timestamp_msk": (
                    timestamp_msk_str
                ),

                "latency_ms": round(
                    latency,
                    2
                ) if latency else 0,

                "state": state,

                "player_cards": [
                    format_card(c)
                    for c in player_cards
                ],

                "dealer_cards": [
                    format_card(c)
                    for c in dealer_cards
                ],

                "sequence": sequence,

                # ГЛАВНОЕ:
                # ПОРЯДКОВЫЙ НОМЕР 1-1440
                "game_number": (
                    game_number
                )
            }

            data = save_data(record)

            if state in ["4", "5"]:

                finished_games.add(
                    game_id
                )

                print(
                    f"🏁 Игра {game_id} "
                    f"(#{game_number}) "
                    f"завершена",
                    flush=True
                )

        time.sleep(0.5)


# =====================================================================
# СТАТИСТИКА
# =====================================================================

def send_stats_report():

    now = datetime.now(MOSCOW_TZ)

    win_percent = 0

    if stats["total"] > 0:

        win_percent = (
            stats["win"] /
            stats["total"] * 100
        )

    data_count = len(load_data())

    msg = f"""
📊 СТАТИСТИКА
⏰ {now.strftime('%d.%m.%Y %H:%M:%S')}

══════════════════════════

📚 Собрано игр: {data_count}/{MAX_RECORDS}

📈 Всего прогнозов: {stats['total']}
✅ Зашло: {stats['win']} ({win_percent:.1f}%)
❌ Не зашло: {stats['lose']}

📈 По догонам:

0: {stats['by_dogon'].get(0, 0)}
1: {stats['by_dogon'].get(1, 0)}
2: {stats['by_dogon'].get(2, 0)}
3: {stats['by_dogon'].get(3, 0)}

🧠 ML: {'АКТИВНА' if ml_initialized else 'ОЖИДАЕТ'}
📚 Исторический поиск: АКТИВЕН
"""

    msg += "\n🔥 Топ карт:\n"

    if stats["card_hits"]:

        sorted_cards = sorted(
            dict(
                stats["card_hits"]
            ).items(),
            key=lambda x: x[1],
            reverse=True
        )[:5]

        for card, count in sorted_cards:

            msg += (
                f"{card}: {count}\n"
            )

    send_message(
        CHANNEL_STATS,
        msg
    )


# =====================================================================
# MAIN
# =====================================================================

def main():

    global predictions
    global all_messages
    global game_history
    global collection_active

    print("=" * 60, flush=True)

    print(
        "🔮 ТОЧНАЯ КАРТА "
        "(ИСТОРИЯ + ML ТОП-2)",
        flush=True
    )

    print(
        "📌 Порядковый номер: "
        "03:00=#1 → 02:59=#1440",
        flush=True
    )

    print(
        "📚 История используется "
        "непосредственно перед прогнозом",
        flush=True
    )

    print(
        "🚫 Карты будущей игры "
        "НЕ используются",
        flush=True
    )

    print("=" * 60, flush=True)

    # -------------------------------------------------------------
    # ЗАГРУЗКА ДАННЫХ
    # -------------------------------------------------------------

    existing_data = load_data()

    print(
        f"📊 Уже собрано игр: "
        f"{len(existing_data)}",
        flush=True
    )

    if len(existing_data) >= MAX_RECORDS:

        collection_active = False

        print(
            "⏸️ Сбор отключён — "
            "лимит достигнут",
            flush=True
        )

    # -------------------------------------------------------------
    # ИСТОРИЯ ЗАДЕРЖЕК
    # -------------------------------------------------------------

    game_history = load_game_history()

    print(
        f"📈 История задержек: "
        f"{len(game_history)}",
        flush=True
    )

    # -------------------------------------------------------------
    # ПРОГНОЗЫ
    # -------------------------------------------------------------

    predictions = load_history()

    # -------------------------------------------------------------
    # КЭШ
    # -------------------------------------------------------------

    load_latency_cache()

    # -------------------------------------------------------------
    # ML
    #
    # ВСЕГДА ПЕРЕОБУЧАЕМ,
    # ЧТОБЫ СТАРАЯ НЕПРАВИЛЬНАЯ МОДЕЛЬ
    # НЕ ОСТАЛАСЬ В cards_model.pkl
    # -------------------------------------------------------------

    if len(existing_data) >= MIN_TRAIN_SAMPLES:

        train_ml_model()

    else:

        print(
            f"⏳ ML ждёт "
            f"{MIN_TRAIN_SAMPLES} игр",
            flush=True
        )

    # -------------------------------------------------------------
    # STARTUP
    # -------------------------------------------------------------

    send_startup_message()

    # -------------------------------------------------------------
    # ЗАГРУЗКА СТАРЫХ TELEGRAM РЕЗУЛЬТАТОВ
    # -------------------------------------------------------------

    try:

        url = (
            f"https://api.telegram.org/"
            f"bot{BOT_TOKEN}/getUpdates"
        )

        response = requests.get(
            url,
            params={"limit": 100},
            timeout=10
        )

        if response.status_code == 200:

            data = response.json()

            for update in data.get(
                "result",
                []
            ):

                channel_post = update.get(
                    "channel_post"
                )

                edited_post = update.get(
                    "edited_channel_post"
                )

                post = (
                    channel_post
                    if channel_post
                    else edited_post
                )

                if (
                    post
                    and post.get("text")
                ):

                    text = post.get("text")

                    if (
                        "#N" in text
                        and is_finished_game_text(
                            text
                        )
                    ):

                        all_messages.append(
                            (
                                text,
                                time.time()
                            )
                        )

        print(
            f"📥 Загружено результатов: "
            f"{len(all_messages)}",
            flush=True
        )

    except Exception as e:

        print(
            f"⚠️ Ошибка загрузки Telegram: {e}",
            flush=True
        )

    # -------------------------------------------------------------
    # ТАЙМЕРЫ
    # -------------------------------------------------------------

    last_stats_time = time.time()

    last_train_time = time.time()

    last_upcoming_check = 0

    offset = get_offset()

    print("=" * 60, flush=True)

    print(
        "🚀 БОТ ГОТОВ!",
        flush=True
    )

    print("=" * 60, flush=True)

    # =============================================================
    # ОСНОВНОЙ ЦИКЛ
    # =============================================================

    while True:

        try:

            current_time = time.time()

            # -----------------------------------------------------
            # СБОР ИГР
            # -----------------------------------------------------

            collect_game_data()

            # -----------------------------------------------------
            # БУДУЩИЕ ИГРЫ
            # -----------------------------------------------------

            if (
                current_time -
                last_upcoming_check
                >= 30
            ):

                check_upcoming_games()

                last_upcoming_check = (
                    current_time
                )

            # -----------------------------------------------------
            # TELEGRAM
            # -----------------------------------------------------

            updates = get_updates(offset)

            for update in updates.get(
                "result",
                []
            ):

                offset = (
                    update["update_id"] + 1
                )

                save_offset(offset)

                channel_post = update.get(
                    "channel_post"
                )

                edited_post = update.get(
                    "edited_channel_post"
                )

                post = (
                    channel_post
                    if channel_post
                    else edited_post
                )

                if not post:
                    continue

                text = post.get(
                    "text",
                    ""
                )

                if (
                    "#N" in text
                    and is_finished_game_text(
                        text
                    )
                ):

                    all_messages.append(
                        (
                            text,
                            time.time()
                        )
                    )

                    match = re.search(
                        r"#N(\d+)",
                        text
                    )

                    if match:

                        print(
                            f"📩 Получен результат "
                            f"#{match.group(1)}",
                            flush=True
                        )

                    if len(all_messages) > 500:

                        all_messages = (
                            all_messages[-500:]
                        )

            # -----------------------------------------------------
            # ПРОВЕРКА ПРОГНОЗОВ
            # -----------------------------------------------------

            check_results()

            # -----------------------------------------------------
            # ПЕРЕОБУЧЕНИЕ ML
            # -----------------------------------------------------

            if (
                current_time -
                last_train_time
                >= 180
            ):

                data_count = len(
                    load_data()
                )

                if (
                    data_count >=
                    MIN_TRAIN_SAMPLES
                ):

                    print(
                        "\n🔄 ПЕРЕОБУЧЕНИЕ ML...",
                        flush=True
                    )

                    train_ml_model()

                    last_train_time = (
                        current_time
                    )

                    gc.collect()

            # -----------------------------------------------------
            # СТАТИСТИКА
            # -----------------------------------------------------

            if (
                current_time -
                last_stats_time
                >= 3600
            ):

                send_stats_report()

                last_stats_time = current_time

            # -----------------------------------------------------
            # ОЧИСТКА
            # -----------------------------------------------------

            if len(predictions) > 200:

                predictions = predictions[-200:]

                save_history(predictions)

            time.sleep(CHECK_INTERVAL)

        except KeyboardInterrupt:

            print(
                "\n🛑 БОТ ОСТАНОВЛЕН",
                flush=True
            )

            break

        except Exception as e:

            print(
                f"❌ КРИТИЧЕСКАЯ ОШИБКА: {e}",
                flush=True
            )

            import traceback

            traceback.print_exc()

            time.sleep(30)


# =====================================================================
# START
# =====================================================================

if __name__ == "__main__":
    main()