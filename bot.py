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
from collections import deque, defaultdict, Counter
import warnings
import gc

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

        print("✅ ВСЕ ЗАВИСИМОСТИ УСТАНОВЛЕНЫ!", flush=True)
        print("=" * 60, flush=True)

        return True


    if not check_and_install_dependencies():

        print("❌ Невозможно продолжить работу", flush=True)
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

    print("⚠️ RandomForest недоступен", flush=True)


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

# Сколько прошлых игр использует ML
MAX_GAME_HISTORY = 10

DOGON_GAMES = 4

ML_CONFIDENCE_THRESHOLD = 0.45

LATENCY_CACHE_MAX_SIZE = 1000


# =====================================================================
# ЦЕЛЕВЫЕ КАРТЫ
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


RANK_VALUES = {

    "6": 6,
    "7": 7,
    "8": 8,
    "9": 9,
    "10": 10,

    "J": 11,
    "Q": 12,
    "K": 13,
    "A": 14

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

    "User-Agent":
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36",

    "Accept":
        "application/json, text/plain, */*",

    "Referer":
        f"{BASE_URL}/ru/live/twentyone/1643503-twentyone-game",

    "Cookie":
        "platform_type=desktop; "
        "lng=ru; "
        "cookies_agree_type=3; "
        "tzo=3; "
        "is12h=0"

}


# =====================================================================
# ГЛОБАЛЬНЫЕ ПЕРЕМЕННЫЕ
# =====================================================================

ml_model = None
ml_initialized = False
ml_feature_names = []

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

    "last_report": time.time(),

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

        print(
            f"❌ Ошибка getUpdates: {e}",
            flush=True
        )

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
            f"❌ Ошибка Telegram: {response.status_code}",
            flush=True
        )

        return None

    except Exception as e:

        print(
            f"❌ Ошибка отправки: {e}",
            flush=True
        )

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
🃏 ТОЧНАЯ КАРТА (PREMATCH ML ТОП-2)

📊 Собрано игр: {data_count}/{MAX_RECORDS}
🧠 ML: {'✅ АКТИВНА' if ml_initialized else '⏳ ОЖИДАЕТ'}

🎯 Режим: ЧЕСТНЫЙ PREMATCH
🚫 Карты будущей игры ML не видит

📈 Догон: {DOGON_GAMES - 1} игр
⚡ Порог ML: {int(ML_CONFIDENCE_THRESHOLD * 100)}%

⏰ {now.strftime('%d.%m.%Y %H:%M:%S')}
"""

    send_message(
        CHANNEL_PROGNOZ,
        msg
    )

    print("🚀 БОТ ЗАПУЩЕН!", flush=True)


# =====================================================================
# ФАЙЛЫ
# =====================================================================

def load_data():

    if os.path.exists(DATA_FILE):

        try:

            with open(
                DATA_FILE,
                "r",
                encoding="utf-8"
            ) as f:

                return json.load(f)

        except:
            return []

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

        if r.get("game_id") == record["game_id"]:

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
            f"⏸️ Лимит {MAX_RECORDS} достигнут",
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
            return []

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


    return deque(
        maxlen=MAX_GAME_HISTORY
    )


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
# КЭШ ЗАДЕРЖЕК
# =====================================================================

def load_latency_cache():

    global game_latency_cache

    if not os.path.exists(
        GAME_LATENCY_CACHE_FILE
    ):
        return False


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
            f"⚠️ Ошибка кэша задержек: {e}",
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

                key=lambda x:
                    x[1].get("timestamp", ""),

                reverse=True

            )[:LATENCY_CACHE_MAX_SIZE]


            game_latency_cache = dict(
                sorted_items
            )


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

    except:

        return False


def get_game_latency(
    game_id,
    game_number=None
):

    if game_id in game_latency_cache:

        return game_latency_cache[
            game_id
        ].get("latency")


    if game_number is not None:

        for gid, item in game_latency_cache.items():

            if item.get(
                "game_number"
            ) == game_number:

                return item.get(
                    "latency"
                )


    return None


def cache_game_latency(
    game_id,
    latency,
    game_number,
    timestamp=None
):

    global game_latency_cache


    if game_id in game_latency_cache:
        return False


    if timestamp is None:

        timestamp = datetime.now(
            MOSCOW_TZ
        ).isoformat()


    game_latency_cache[game_id] = {

        "latency": latency,
        "game_number": game_number,
        "timestamp": timestamp

    }


    save_latency_cache()


    print(
        f"📊 Первая задержка "
        f"{latency:.1f}мс "
        f"для игры #{game_number}",
        flush=True
    )


    return True


# =====================================================================
# НОМЕР ИГРЫ
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


    return (
        int(diff_minutes) % 1440
    ) + 1


def get_game_number_from_timestamp(
    timestamp
):

    if not timestamp:
        return None


    try:

        if isinstance(
            timestamp,
            (int, float)
        ):

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
            )

            start_time = start_time.astimezone(
                MOSCOW_TZ
            )


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


    return (
        int(diff_minutes) % 1440
    ) + 1


# =====================================================================
# API АКТИВНЫХ ИГР
# =====================================================================

def get_active_games():

    try:

        url = (

            f"{BASE_URL}/service-api/"
            f"main-live-feed/v3/games1x2?"

            f"cfView=3"
            f"&count=40"
            f"&fcountry=190"
            f"&gr=415"
            f"&grMode=4"
            f"&lng=ru"
            f"&ref=7"
            f"&selectedMs="
            f"1.146.1643503,"
            f"10.146.1643503"

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

            games = data.get(
                "Value",
                []
            )

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

                    active_games.append(
                        game
                    )


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
        f"LiveFeed/GetGameZip?"

        f"id={game_id}"
        f"&isSubGames=true"
        f"&GroupEvents=true"
        f"&countevents=250"
        f"&grMode=4"
        f"&partner=7"
        f"&topGroups="
        f"&country=190"
        f"&marketType=1"
        f"&isNewBuilder=true"

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
# ПАРСИНГ КАРТ
# =====================================================================

def parse_cards_and_state(data):

    if not data:
        return [], [], None


    if not isinstance(data, dict):
        return [], [], None


    sc = data.get(
        "Value",
        {}
    )


    if not isinstance(sc, dict):
        return [], [], None


    sc = sc.get(
        "SC",
        {}
    )


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
                    item.get(
                        "Value",
                        "[]"
                    )
                )

            except:
                player_cards = []


        if item.get("Key") == "P2":

            try:

                dealer_cards = json.loads(
                    item.get(
                        "Value",
                        "[]"
                    )
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
# ПАРСИНГ TELEGRAM РЕЗУЛЬТАТОВ
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

        elif "-" in text:

            parts = text.split("-")

        elif "—" in text:

            parts = text.split("—")

        else:

            return None


        if len(parts) < 2:
            return None


        def parse_cards(part):

            cards_match = re.search(
                r"\(([^)]*)\)",
                part
            )


            if not cards_match:
                return []


            cards_str = cards_match.group(1)

            cards = []

            pattern = (
                r"(10|[2-9AJQK])"
                r"(♠️|♣️|♦️|♥️|♠|♣|♦|♥)"
            )


            matches = re.findall(
                pattern,
                cards_str
            )


            for rank, suit in matches:

                suit = (
                    suit.replace("♠", "♠️")
                    .replace("♣", "♣️")
                    .replace("♦", "♦️")
                    .replace("♥", "♥️")
                )


                cards.append({

                    "rank": rank,
                    "suit": suit

                })


            return cards


        return {

            "number": game_number,

            "player_cards":
                parse_cards(parts[0]),

            "dealer_cards":
                parse_cards(parts[1]),

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
# ПОЛУЧЕНИЕ БУДУЩИХ ИГР
# =====================================================================

def get_upcoming_games():

    try:

        url = (

            f"{BASE_URL}/service-api/"
            f"main-live-feed/v3/"
            f"leftMenuSports?"

            f"fcountry=1"
            f"&gr=415"
            f"&lng=ru"
            f"&ref=7"
            f"&selectedMs=10.146.1643503"

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

        now = datetime.now(
            MOSCOW_TZ
        )


        if not isinstance(data, list):
            return []


        for section in data:

            if section.get(
                "menuSectionId"
            ) != 10:
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

                        if game.get(
                            "nonStarted"
                        ) != True:
                            continue


                        start_ts = game.get(
                            "startTs"
                        )


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


                        if (
                            0 < minutes_until <= 5
                        ):

                            upcoming_games.append({

                                "game_id":
                                    str(game.get("id")),

                                "game_num":
                                    game_num,

                                "start_time":
                                    start_time,

                                "minutes_until":
                                    minutes_until,

                                "start_ts":
                                    start_ts

                            })


        return upcoming_games


    except Exception as e:

        print(
            f"❌ Ошибка будущих игр: {e}",
            flush=True
        )

        return []


# =====================================================================
# ML - ВСПОМОГАТЕЛЬНЫЕ ФУНКЦИИ
# =====================================================================

def card_to_index(card):

    if not card:
        return -1

    rank = card.get("rank", "")
    suit = card.get("suit", "")

    card_str = rank + suit

    if card_str in TARGET_CARDS:
        return TARGET_CARDS.index(card_str)

    return -1


def get_target_card_from_game(game):
    """
    Берём первую целевую карту J/Q/K/A из игры.

    Это ТОЛЬКО ОТВЕТ ДЛЯ ОБУЧЕНИЯ.
    В признаки самой игры эта карта НЕ попадает.
    """

    all_cards = (

        game.get("player_cards", [])
        +
        game.get("dealer_cards", [])

    )


    for card in all_cards:

        rank = card.get("rank", "")
        suit = card.get("suit", "")

        card_str = rank + suit

        if card_str in TARGET_CARDS:

            return card_str


    return None


def get_all_cards_from_game(game):

    cards = []

    for card in (

        game.get("player_cards", [])
        +
        game.get("dealer_cards", [])

    ):

        rank = card.get("rank", "")
        suit = card.get("suit", "")

        card_str = rank + suit

        if card_str:
            cards.append(card_str)


    return cards


# =====================================================================
# ГЛАВНАЯ PREMATCH FEATURE LOGIC
# =====================================================================

def build_prematch_features(
    current_latency,
    game_num,
    current_time,
    previous_games
):
    """
    ВАЖНО:

    Эта функция НЕ получает карты будущей игры.

    Она использует только:

    - задержку будущей игры
    - номер будущей игры
    - время будущей игры
    - прошлые игры

    Именно это делает прогноз честным PREMATCH.
    """

    features = {}


    # ================================================================
    # 1. ТЕКУЩАЯ ЗАДЕРЖКА БУДУЩЕЙ ИГРЫ
    # ================================================================

    features["current_latency"] = (
        float(current_latency)
        if current_latency else 0.0
    )


    # ================================================================
    # 2. ВРЕМЯ / НОМЕР ИГРЫ
    # ================================================================

    features["game_num"] = (
        game_num % 1440
    )

    features["game_num_mod_100"] = (
        game_num % 100
    )

    features["hour"] = (
        current_time.hour
    )

    features["minute"] = (
        current_time.minute
    )

    features["day_of_week"] = (
        current_time.weekday()
    )

    features["is_weekend"] = (

        1
        if current_time.weekday() >= 5
        else 0

    )


    # ================================================================
    # 3. ФИЧИ ПО ЗАДЕРЖКАМ ПРОШЛЫХ ИГР
    # ================================================================

    previous_latencies = []


    for game in previous_games:

        latency = game.get(
            "latency_ms",
            game.get(
                "latency",
                0
            )
        )

        try:
            previous_latencies.append(
                float(latency)
            )
        except:
            previous_latencies.append(0.0)


    # Фиксированное количество прошлых задержек

    for i in range(MAX_GAME_HISTORY):

        key = f"prev_latency_{i+1}"

        if i < len(previous_latencies):

            features[key] = (
                previous_latencies[-(i + 1)]
            )

        else:

            features[key] = 0.0


    if previous_latencies:

        features["prev_latency_mean"] = float(
            np.mean(previous_latencies)
        )

        features["prev_latency_std"] = float(
            np.std(previous_latencies)
        )

        features["prev_latency_min"] = float(
            np.min(previous_latencies)
        )

        features["prev_latency_max"] = float(
            np.max(previous_latencies)
        )

        features["latency_delta"] = (

            float(current_latency)
            -
            previous_latencies[-1]

        )

    else:

        features["prev_latency_mean"] = 0.0
        features["prev_latency_std"] = 0.0
        features["prev_latency_min"] = 0.0
        features["prev_latency_max"] = 0.0
        features["latency_delta"] = 0.0


    # ================================================================
    # 4. КАРТЫ ПРОШЛЫХ ИГР
    #
    # ВАЖНО:
    # Только ПРОШЛЫЕ.
    # Карты текущей будущей игры здесь отсутствуют.
    # ================================================================

    recent_cards = []


    for game in previous_games:

        cards = get_all_cards_from_game(game)

        recent_cards.extend(cards)


    # Последние 20 карт

    recent_cards = recent_cards[-20:]


    for i in range(20):

        key = f"history_card_{i+1}"

        if i < len(recent_cards):

            card = recent_cards[
                -(i + 1)
            ]

            if card in TARGET_CARDS:

                features[key] = (
                    TARGET_CARDS.index(card)
                )

            else:

                features[key] = -1

        else:

            features[key] = -1


    # ================================================================
    # 5. ЧАСТОТА ЦЕЛЕВЫХ КАРТ В ПРОШЛЫХ ИГРАХ
    # ================================================================

    card_counter = Counter()


    for card in recent_cards:

        if card in TARGET_CARDS:

            card_counter[card] += 1


    for card in TARGET_CARDS:

        features[
            f"freq_{card}"
        ] = card_counter.get(
            card,
            0
        )


    # ================================================================
    # 6. СКОЛЬКО J / Q / K / A В ПОСЛЕДНИХ ИГРАХ
    # ================================================================

    ranks_counter = Counter()


    for card in recent_cards:

        if card:

            rank = card[0]

            if card.startswith("10"):
                rank = "10"

            if rank in ["J", "Q", "K", "A"]:

                ranks_counter[rank] += 1


    features["recent_j"] = (
        ranks_counter.get("J", 0)
    )

    features["recent_q"] = (
        ranks_counter.get("Q", 0)
    )

    features["recent_k"] = (
        ranks_counter.get("K", 0)
    )

    features["recent_a"] = (
        ranks_counter.get("A", 0)
    )


    # ================================================================
    # 7. СТАТИСТИКА ПОСЛЕДНИХ ИГР
    # ================================================================

    features["history_games_count"] = (
        len(previous_games)
    )

    features["history_cards_count"] = (
        len(recent_cards)
    )


    return features


# =====================================================================
# СОЗДАНИЕ DATASET ДЛЯ ОБУЧЕНИЯ
# =====================================================================

def prepare_training_dataset():

    data = load_data()


    if len(data) < MIN_TRAIN_SAMPLES:

        return None, None, None


    # Сортируем по времени/порядку

    def sort_key(game):

        return game.get(
            "timestamp_msk",
            ""
        )


    try:
        data = sorted(
            data,
            key=sort_key
        )
    except:
        pass


    X = []
    y = []


    print(
        f"🧠 Создаю PREMATCH dataset "
        f"из {len(data)} игр...",
        flush=True
    )


    for index, game in enumerate(data):

        # ------------------------------------------------------------
        # Для текущей игры берём ТОЛЬКО ответ
        # ------------------------------------------------------------

        target_card = (
            get_target_card_from_game(
                game
            )
        )


        if not target_card:
            continue


        # ------------------------------------------------------------
        # Берём ТОЛЬКО ИГРЫ ДО ТЕКУЩЕЙ
        # ------------------------------------------------------------

        start_index = max(
            0,
            index - MAX_GAME_HISTORY
        )


        previous_games = data[
            start_index:index
        ]


        # Нужно хотя бы немного истории

        if len(previous_games) < 2:
            continue


        # ------------------------------------------------------------
        # Метаданные текущей игры
        #
        # КАРТЫ ТЕКУЩЕЙ ИГРЫ НЕ БЕРЁМ
        # ------------------------------------------------------------

        latency = game.get(
            "latency_ms",
            0
        )

        game_num = game.get(
            "game_number",
            index
        )


        # Время

        now = datetime.now(MOSCOW_TZ)


        timestamp_str = game.get(
            "timestamp_msk"
        )


        if timestamp_str:

            try:

                time_parts = (
                    timestamp_str.split(":")
                )

                if len(time_parts) >= 2:

                    now = now.replace(

                        hour=int(time_parts[0]),

                        minute=int(time_parts[1]),

                        second=0,

                        microsecond=0

                    )

            except:
                pass


        # ------------------------------------------------------------
        # СОЗДАЁМ ЧЕСТНЫЕ PREMATCH FEATURES
        # ------------------------------------------------------------

        features = build_prematch_features(

            current_latency=latency,

            game_num=game_num,

            current_time=now,

            previous_games=previous_games

        )


        X.append(features)

        y.append(
            TARGET_CARDS.index(
                target_card
            )
        )


    if len(X) < MIN_TRAIN_SAMPLES:

        print(
            f"⚠️ Недостаточно примеров: "
            f"{len(X)}",
            flush=True
        )

        return None, None, None


    # Фиксированный порядок признаков

    feature_names = sorted(
        X[0].keys()
    )


    X_matrix = []


    for row in X:

        vector = [

            row.get(
                feature,
                0
            )

            for feature in feature_names

        ]

        X_matrix.append(vector)


    return (

        np.array(X_matrix),

        np.array(y),

        feature_names

    )


# =====================================================================
# ОБУЧЕНИЕ ML
# =====================================================================

def train_ml_model():

    global ml_model
    global ml_initialized
    global ml_feature_names


    if not ML_AVAILABLE:
        return False


    X, y, feature_names = (
        prepare_training_dataset()
    )


    if X is None:

        print(
            "⚠️ Dataset не готов",
            flush=True
        )

        return False


    print(
        "=" * 60,
        flush=True
    )

    print(
        "🧠 НАЧИНАЮ ОБУЧЕНИЕ PREMATCH ML",
        flush=True
    )

    print(
        f"📊 Примеров: {len(X)}",
        flush=True
    )

    print(
        f"📊 Признаков: {len(feature_names)}",
        flush=True
    )

    print(
        "🚫 Карты целевой игры "
        "в признаки НЕ передаются",
        flush=True
    )

    print(
        "=" * 60,
        flush=True
    )


    if ML_LIB == "randomforest":

        model = RandomForestClassifier(

            n_estimators=300,

            max_depth=12,

            min_samples_split=4,

            min_samples_leaf=2,

            class_weight="balanced",

            random_state=42,

            n_jobs=1

        )

    else:

        return False


    try:

        model.fit(
            X,
            y
        )


        ml_model = model

        ml_initialized = True

        ml_feature_names = feature_names


        with open(
            ML_MODEL_FILE,
            "wb"
        ) as f:

            pickle.dump({

                "model": model,

                "feature_names":
                    feature_names,

                "train_samples":
                    len(X),

                "feature_count":
                    len(feature_names),

                "mode":
                    "PREMATCH_NO_TARGET_CARDS"

            }, f)


        print(
            "✅ PREMATCH ML ОБУЧЕНА!",
            flush=True
        )

        print(
            f"📊 Обучено на "
            f"{len(X)} примерах",
            flush=True
        )

        return True


    except Exception as e:

        print(
            f"❌ Ошибка обучения: {e}",
            flush=True
        )

        return False


# =====================================================================
# ЗАГРУЗКА ML
# =====================================================================

def load_ml_model():

    global ml_model
    global ml_initialized
    global ml_feature_names


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


        # Проверяем что это новая prematch модель

        if saved.get(
            "mode"
        ) != "PREMATCH_NO_TARGET_CARDS":

            print(
                "⚠️ Найдена старая ML модель",
                flush=True
            )

            print(
                "🔄 Будет создана новая "
                "PREMATCH модель",
                flush=True
            )

            return False


        ml_model = saved["model"]

        ml_feature_names = saved.get(
            "feature_names",
            []
        )

        ml_initialized = True


        print(
            f"✅ PREMATCH ML загружена",
            flush=True
        )

        print(
            f"📊 Примеров: "
            f"{saved.get('train_samples', 0)}",
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

def predict_ml_prematch(features):

    global ml_model
    global ml_initialized
    global ml_feature_names


    if not ml_initialized:

        return None, None


    if ml_model is None:

        return None, None


    try:

        # ------------------------------------------------------------
        # Используем ТОЧНО тот же порядок признаков,
        # что был во время обучения
        # ------------------------------------------------------------

        vector = [

            features.get(
                feature,
                0
            )

            for feature in ml_feature_names

        ]


        vector = np.array(
            [vector]
        )


        probs = ml_model.predict_proba(
            vector
        )[0]


        # ------------------------------------------------------------
        # classes_ может содержать не все 16 карт
        # ------------------------------------------------------------

        classes = ml_model.classes_


        full_probs = np.zeros(
            len(TARGET_CARDS)
        )


        for i, class_index in enumerate(classes):

            if (
                0 <= class_index
                < len(TARGET_CARDS)
            ):

                full_probs[
                    class_index
                ] = probs[i]


        top_indices = np.argsort(
            full_probs
        )[-2:][::-1]


        top_cards = [

            (
                TARGET_CARDS[i],
                float(full_probs[i])
            )

            for i in top_indices

        ]


        confidence = (
            top_cards[0][1]
        )


        return (
            top_cards,
            confidence
        )


    except Exception as e:

        print(
            f"⚠️ Ошибка прогноза ML: {e}",
            flush=True
        )

        return None, None


# =====================================================================
# ИСТОРИЯ ДЛЯ PREMATCH
# =====================================================================

def get_recent_games_for_prediction():

    data = load_data()


    if not data:
        return []


    # Берём последние игры

    return data[
        -MAX_GAME_HISTORY:
    ]


# =====================================================================
# ПРОВЕРКА БУДУЩИХ ИГР И ПРОГНОЗ
# =====================================================================

def check_upcoming_games():

    global predictions


    upcoming = get_upcoming_games()


    if not upcoming:
        return


    for game in upcoming:

        game_num = game.get(
            "game_num"
        )

        game_id = game.get(
            "game_id"
        )

        start_time = game.get(
            "start_time"
        )


        if not game_num:
            continue


        # ------------------------------------------------------------
        # Проверяем, был ли уже прогноз
        # ------------------------------------------------------------

        already_predicted = False


        for entry in predictions:

            if (
                entry.get("target") == game_num
                and entry.get("status") == "pending"
            ):

                already_predicted = True

                break


        if already_predicted:
            continue


        print(
            "=" * 60,
            flush=True
        )

        print(
            f"🔥 БУДУЩАЯ ИГРА #{game_num}",
            flush=True
        )

        print(
            "🔍 PREMATCH РЕЖИМ",
            flush=True
        )

        print(
            "🚫 Карты игры ещё не используются",
            flush=True
        )

        print(
            "=" * 60,
            flush=True
        )


        # ------------------------------------------------------------
        # ЗАМЕРЯЕМ ЗАДЕРЖКУ БУДУЩЕЙ ИГРЫ
        # ------------------------------------------------------------

        _, measured_latency, _, _ = (
            get_game_data(game_id)
        )


        if measured_latency is not None:

            latency = measured_latency


            cache_game_latency(

                game_id,

                latency,

                game_num

            )


        else:

            latency = 500.0


            print(
                f"⚠️ Использую задержку "
                f"по умолчанию {latency}мс",
                flush=True
            )


        print(
            f"⚡ Задержка будущей игры: "
            f"{latency:.2f}мс",
            flush=True
        )


        # ------------------------------------------------------------
        # ПОЛУЧАЕМ ТОЛЬКО ПРОШЛЫЕ ИГРЫ
        # ------------------------------------------------------------

        previous_games = (
            get_recent_games_for_prediction()
        )


        if len(previous_games) < 2:

            print(
                "⏳ Недостаточно истории",
                flush=True
            )

            continue


        # ------------------------------------------------------------
        # СОЗДАЁМ PREMATCH FEATURES
        # ------------------------------------------------------------

        prediction_time = (

            start_time
            if start_time
            else datetime.now(MOSCOW_TZ)

        )


        features = build_prematch_features(

            current_latency=latency,

            game_num=game_num,

            current_time=prediction_time,

            previous_games=previous_games

        )


        # ------------------------------------------------------------
        # ПРОГНОЗ
        # ------------------------------------------------------------

        predicted_cards, confidence = (
            predict_ml_prematch(
                features
            )
        )


        if not predicted_cards:

            print(
                "⏭️ ML не выдала прогноз",
                flush=True
            )

            continue


        print(
            "🤖 ML ТОП-2:",
            flush=True
        )


        for i, (
            card,
            probability
        ) in enumerate(
            predicted_cards,
            1
        ):

            print(
                f"{i}. {card} — "
                f"{probability * 100:.2f}%",
                flush=True
            )


        if confidence < ML_CONFIDENCE_THRESHOLD:

            print(
                f"⏭️ Уверенность "
                f"{confidence * 100:.1f}% "
                f"ниже порога",
                flush=True
            )

            continue


        # ------------------------------------------------------------
        # ФОРМИРУЕМ СООБЩЕНИЕ
        # ------------------------------------------------------------

        total_probability = sum(

            prob

            for _, prob
            in predicted_cards

        )


        msg = (
            "🔮 ТОЧНАЯ КАРТА "
            "(PREMATCH ML ТОП-2)\n\n"
        )


        msg += (
            f"🎯 Целевая игра: "
            f"#N{game_num}\n"
        )


        msg += (
            f"🤖 Метод: PREMATCH ML "
            f"(увер. {confidence * 100:.1f}%)\n"
        )


        msg += (
            f"⏰ Прогноз: "
            f"{datetime.now(MOSCOW_TZ).strftime('%H:%M:%S')}\n\n"
        )


        msg += (
            "📊 Топ-2 карты:\n\n"
        )


        cards_list = []


        for i, (
            card,
            probability
        ) in enumerate(
            predicted_cards,
            1
        ):

            cards_list.append(card)


            msg += (
                f"  {i}️⃣ {card} — "
                f"{probability * 100:.1f}%\n"
            )


        msg += (
            f"\n📊 Суммарная вероятность: "
            f"{total_probability * 100:.1f}%\n"
        )


        msg += (
            f"📈 Догон: "
            f"{DOGON_GAMES - 1} игр\n"
        )


        msg += (
            "📍 Ищем: любую позицию "
            "(игрок/дилер)\n"
        )


        msg += (
            "\n🧠 Анализ: предыдущие игры + "
            "задержка + временной слот"
        )


        # ------------------------------------------------------------
        # ОТПРАВЛЯЕМ
        # ------------------------------------------------------------

        message_id = send_message(

            CHANNEL_PROGNOZ,

            msg

        )


        if message_id:

            entry = {

                "source":
                    game_num,

                "target":
                    game_num,

                "offset":
                    0,

                "cards":
                    cards_list,

                "method":
                    "prematch_ml",

                "message_id":
                    message_id,

                "original_text":
                    msg,

                "status":
                    "pending",

                "latency":
                    latency,

                "confidence":
                    confidence,

                "created":
                    datetime.now(
                        MOSCOW_TZ
                    ).isoformat()

            }


            predictions.append(
                entry
            )


            if len(predictions) > 200:

                predictions = predictions[
                    -200:
                ]


            save_history(
                predictions
            )


            print(
                f"✅ PREMATCH ПРОГНОЗ "
                f"#{game_num}: "
                f"{', '.join(cards_list)}",
                flush=True
            )


# =====================================================================
# ПРОВЕРКА РЕЗУЛЬТАТОВ
# =====================================================================

def check_results():

    global predictions
    global stats
    global all_messages


    if not predictions:
        return


    if not all_messages:
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


        if not target:
            continue


        if not predicted_cards:
            continue


        if not message_id:
            continue


        # ------------------------------------------------------------
        # ПРОСРОЧКА
        # ------------------------------------------------------------

        if current_game_number > (
            target + DOGON_GAMES + 5
        ):

            entry["status"] = "expired"

            entry["checked_at"] = (
                datetime.now(
                    MOSCOW_TZ
                ).isoformat()
            )


            edit_message(

                message_id,

                original_text
                +
                "\n\n⏰ ПРОСРОЧЕН"

            )


            save_history(
                predictions
            )

            continue


        # ------------------------------------------------------------
        # ПРОВЕРЯЕМ ОСНОВНУЮ ИГРУ + ДОГОН
        # ------------------------------------------------------------

        found = False

        found_card = None

        found_game = None

        found_dogon = None


        games_found = 0

        last_actual_cards = []


        for i in range(DOGON_GAMES):

            game_to_check = (
                target + i
            )


            if game_to_check not in games_by_number:

                continue


            games_found += 1


            game_data = (
                parse_game_from_text(
                    games_by_number[
                        game_to_check
                    ]
                )
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


                card_str = (
                    rank + suit
                )


                if not rank or not suit:
                    continue


                actual_cards.append(
                    card_str
                )


                if card_str in predicted_cards:

                    found = True

                    found_card = card_str

                    found_game = (
                        game_to_check
                    )

                    found_dogon = i

                    break


            last_actual_cards = (
                actual_cards
            )


            if found:
                break


        # ------------------------------------------------------------
        # ЗАШЛО
        # ------------------------------------------------------------

        if found:

            stats["total"] += 1

            stats["win"] += 1

            stats["ml_wins"] += 1


            stats["by_dogon"][
                found_dogon
            ] = (

                stats["by_dogon"].get(
                    found_dogon,
                    0
                )

                + 1

            )


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

                f"\n🃏 Выпала: "
                f"{found_card}"

            )


            edit_message(

                message_id,

                original_text
                +
                result_text

            )


            entry["status"] = "win"

            entry["result_game"] = (
                found_game
            )

            entry["dogon"] = (
                found_dogon
            )

            entry["found_card"] = (
                found_card
            )

            entry["checked_at"] = (
                datetime.now(
                    MOSCOW_TZ
                ).isoformat()
            )


            save_history(
                predictions
            )


            print(
                f"🎯 ЗАШЛО: "
                f"{found_card} "
                f"в #{found_game}",
                flush=True
            )


            continue


        # ------------------------------------------------------------
        # ЖДЁМ ДО КОНЦА ДОГОНА
        # ------------------------------------------------------------

        last_required_game = (

            target
            +
            DOGON_GAMES
            -
            1

        )


        if (
            last_required_game
            not in games_by_number
        ):

            continue


        # ------------------------------------------------------------
        # НЕ ЗАШЛО
        # ------------------------------------------------------------

        stats["total"] += 1

        stats["lose"] += 1

        stats["ml_losses"] += 1


        actual_target = None


        for card in last_actual_cards:

            if card in TARGET_CARDS:

                actual_target = card

                break


        result_text = (

            "\n\n❌ НЕ ЗАШЛО"

            f"\n🔍 Проверено игр: "
            f"{DOGON_GAMES}"

            f"\n📊 Диапазон: "
            f"#{target} → "
            f"#{last_required_game}"

        )


        if actual_target:

            result_text += (
                f"\n🃏 Последняя карта: "
                f"{actual_target}"
            )


        edit_message(

            message_id,

            original_text
            +
            result_text

        )


        entry["status"] = "lose"

        entry["actual_card"] = (
            actual_target
        )

        entry["result_game"] = (
            last_required_game
        )

        entry["checked_at"] = (
            datetime.now(
                MOSCOW_TZ
            ).isoformat()
        )


        save_history(
            predictions
        )


        print(
            f"❌ НЕ ЗАШЛО: "
            f"#{target}",
            flush=True
        )


# =====================================================================
# СБОР ИГР
# =====================================================================

def collect_game_data():

    global collection_active
    global finished_games


    if not collection_active:
        return


    active_games = (
        get_active_games()
    )


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


        game_data, latency, start_time, end_time = (
            get_game_data(
                game_id
            )
        )


        if not game_data:
            continue


        game_number = (
            get_game_number_by_time()
        )


        # ------------------------------------------------------------
        # СОХРАНЯЕМ ПЕРВУЮ ЗАДЕРЖКУ
        # ------------------------------------------------------------

        if latency is not None:

            if game_id not in game_latency_cache:

                cache_game_latency(

                    game_id,

                    latency,

                    game_number

                )


        # ------------------------------------------------------------
        # ПАРСИНГ
        # ------------------------------------------------------------

        player_cards, dealer_cards, state = (
            parse_cards_and_state(
                game_data
            )
        )


        # Сохраняем игру только когда есть карты

        if not player_cards and not dealer_cards:

            continue


        timestamp = (

            datetime.fromtimestamp(
                start_time,
                MOSCOW_TZ
            )

            if start_time

            else datetime.now(
                MOSCOW_TZ
            )

        )


        timestamp_msk_str = (
            timestamp.strftime(
                "%H:%M:%S.%f"
            )[:-3]
        )


        def format_card(card):

            return {

                "rank":
                    RANKS.get(
                        card.get("CV", 0),
                        "?"
                    ),

                "suit":
                    SUITS_NAMES.get(
                        card.get("CS", 0),
                        "?"
                    )

            }


        # ------------------------------------------------------------
        # ПОСЛЕДОВАТЕЛЬНОСТЬ
        # ------------------------------------------------------------

        sequence = []


        max_len = max(

            len(player_cards),

            len(dealer_cards)

        )


        for i in range(max_len):

            if i < len(player_cards):

                pc = player_cards[i]

                sequence.append({

                    "position":
                        i * 2 + 1,

                    "who":
                        "P",

                    "rank":
                        RANKS.get(
                            pc.get("CV", 0),
                            "?"
                        ),

                    "suit":
                        SUITS_NAMES.get(
                            pc.get("CS", 0),
                            "?"
                        )

                })


            if i < len(dealer_cards):

                dc = dealer_cards[i]

                sequence.append({

                    "position":
                        i * 2 + 2,

                    "who":
                        "D",

                    "rank":
                        RANKS.get(
                            dc.get("CV", 0),
                            "?"
                        ),

                    "suit":
                        SUITS_NAMES.get(
                            dc.get("CS", 0),
                            "?"
                        )

                })


        # ------------------------------------------------------------
        # RECORD
        # ------------------------------------------------------------

        record = {

            "game_id":
                game_id,

            "timestamp_msk":
                timestamp_msk_str,

            "latency_ms":
                round(
                    latency,
                    2
                )
                if latency
                else 0,

            "state":
                state,

            "player_cards": [

                format_card(card)

                for card
                in player_cards

            ],

            "dealer_cards": [

                format_card(card)

                for card
                in dealer_cards

            ],

            "sequence":
                sequence,

            "game_number":
                game_number

        }


        data = save_data(
            record
        )


        # ------------------------------------------------------------
        # ЗАВЕРШЕНИЕ
        # ------------------------------------------------------------

        if state in ["4", "5"]:

            finished_games.add(
                game_id
            )


            print(
                f"🏁 Игра завершена "
                f"#{game_number}",
                flush=True
            )


        if len(data) >= MAX_RECORDS:

            collection_active = False

            return


        time.sleep(0.5)


# =====================================================================
# СТАТИСТИКА
# =====================================================================

def send_stats_report():

    now = datetime.now(
        MOSCOW_TZ
    )


    win_percent = 0


    if stats["total"] > 0:

        win_percent = (

            stats["win"]
            /
            stats["total"]
            *
            100

        )


    data_count = len(
        load_data()
    )


    msg = f"""
📊 СТАТИСТИКА PREMATCH ML

⏰ {now.strftime('%d.%m.%Y %H:%M:%S')}

════════════════════════════

📊 Собрано игр: {data_count}/{MAX_RECORDS}

📈 Всего прогнозов: {stats['total']}

✅ Зашло: {stats['win']} ({win_percent:.1f}%)

❌ Не зашло: {stats['lose']}

🤖 ML: {stats['ml_wins']}✅ / {stats['ml_losses']}❌

📈 По догонам:

Догон 0: {stats['by_dogon'].get(0, 0)}
Догон 1: {stats['by_dogon'].get(1, 0)}
Догон 2: {stats['by_dogon'].get(2, 0)}
Догон 3: {stats['by_dogon'].get(3, 0)}

🧠 Режим:
PREMATCH
Без карт целевой игры
"""


    msg += "\n🏆 ТОП-5 ЗАШЕДШИХ КАРТ:\n"


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
                f"  {card}: "
                f"{count}\n"
            )

    else:

        msg += (
            "  Пока нет данных\n"
        )


    msg += (

        "\n🤖 ML: "

        + (
            "АКТИВНА"
            if ml_initialized
            else "ОЖИДАЕТ"
        )

    )


    send_message(
        CHANNEL_STATS,
        msg
    )


# =====================================================================
# ОСНОВНОЙ ЦИКЛ
# =====================================================================

def main():

    global predictions
    global all_messages
    global game_history
    global collection_active


    print("=" * 60, flush=True)

    print(
        "🔮 PREMATCH ML ТОЧНАЯ КАРТА",
        flush=True
    )

    print(
        "=" * 60,
        flush=True
    )

    print(
        f"📊 Максимум игр: "
        f"{MAX_RECORDS}",
        flush=True
    )

    print(
        f"🧠 История ML: "
        f"{MAX_GAME_HISTORY} игр",
        flush=True
    )

    print(
        "🚫 ML НЕ ВИДИТ КАРТЫ "
        "БУДУЩЕЙ ИГРЫ",
        flush=True
    )

    print(
        f"🎯 Целевых карт: "
        f"{len(TARGET_CARDS)}",
        flush=True
    )

    print(
        "=" * 60,
        flush=True
    )


    # ------------------------------------------------------------
    # ДАННЫЕ
    # ------------------------------------------------------------

    existing_data = load_data()


    print(
        f"📊 Уже собрано: "
        f"{len(existing_data)}",
        flush=True
    )


    if len(existing_data) >= MAX_RECORDS:

        collection_active = False


    # ------------------------------------------------------------
    # HISTORY
    # ------------------------------------------------------------

    game_history = (
        load_game_history()
    )


    # ------------------------------------------------------------
    # ПРОГНОЗЫ
    # ------------------------------------------------------------

    predictions = (
        load_history()
    )


    # ------------------------------------------------------------
    # КЭШ ЗАДЕРЖЕК
    # ------------------------------------------------------------

    load_latency_cache()


    # ------------------------------------------------------------
    # ML
    # ------------------------------------------------------------

    loaded = load_ml_model()


    # ВСЕГДА переобучаем если есть данные.
    # Это гарантирует новую честную PREMATCH логику.

    if len(existing_data) >= MIN_TRAIN_SAMPLES:

        print(
            "🔄 Проверяю/обновляю "
            "PREMATCH ML...",
            flush=True
        )

        train_ml_model()


    else:

        print(
            f"⏳ ML ожидает данные: "
            f"{len(existing_data)}/"
            f"{MIN_TRAIN_SAMPLES}",
            flush=True
        )


    stats["games_collected"] = (
        len(existing_data)
    )


    # ------------------------------------------------------------
    # START MESSAGE
    # ------------------------------------------------------------

    send_startup_message()


    # ------------------------------------------------------------
    # ЗАГРУЗКА ПОСЛЕДНИХ TELEGRAM UPDATE
    # ------------------------------------------------------------

    try:

        url = (
            f"https://api.telegram.org/"
            f"bot{BOT_TOKEN}/getUpdates"
        )


        response = requests.get(

            url,

            params={
                "limit": 100
            },

            timeout=10

        )


        if response.status_code == 200:

            response_data = (
                response.json()
            )


            for update in response_data.get(
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
                        and is_finished_game_text(text)
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


        check_results()


    except Exception as e:

        print(
            f"⚠️ Ошибка загрузки Telegram: "
            f"{e}",
            flush=True
        )


    # ------------------------------------------------------------
    # ТАЙМЕРЫ
    # ------------------------------------------------------------

    last_stats_time = time.time()

    last_train_time = time.time()

    last_upcoming_check = time.time()


    offset = get_offset()


    print("=" * 60, flush=True)

    print(
        "🚀 БОТ ГОТОВ!",
        flush=True
    )

    print("=" * 60, flush=True)


    # ================================================================
    # MAIN LOOP
    # ================================================================

    while True:

        try:

            current_time = time.time()


            # --------------------------------------------------------
            # СБОР ИГР
            # --------------------------------------------------------

            collect_game_data()


            # --------------------------------------------------------
            # PREMATCH ПРОВЕРКА
            # --------------------------------------------------------

            if (

                current_time
                -
                last_upcoming_check

                > 30

            ):

                check_upcoming_games()

                last_upcoming_check = (
                    current_time
                )


            # --------------------------------------------------------
            # TELEGRAM
            # --------------------------------------------------------

            updates = get_updates(
                offset
            )


            for update in updates.get(
                "result",
                []
            ):

                offset = (
                    update["update_id"]
                    + 1
                )


                save_offset(
                    offset
                )


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

                    and is_finished_game_text(text)

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
                            f"📩 Результат "
                            f"#{match.group(1)}",
                            flush=True
                        )


                    if len(all_messages) > 500:

                        all_messages = (
                            all_messages[-500:]
                        )


            # --------------------------------------------------------
            # ПРОВЕРКА ПРОГНОЗОВ
            # --------------------------------------------------------

            check_results()


            # --------------------------------------------------------
            # ПЕРЕОБУЧЕНИЕ
            # --------------------------------------------------------

            if (

                current_time
                -
                last_train_time

                > 180

            ):

                data_count = len(
                    load_data()
                )


                if (
                    data_count
                    >= MIN_TRAIN_SAMPLES
                ):

                    print(
                        "=" * 60,
                        flush=True
                    )

                    print(
                        f"🔄 ПЕРЕОБУЧЕНИЕ "
                        f"PREMATCH ML",
                        flush=True
                    )

                    print(
                        f"📊 Игр: "
                        f"{data_count}",
                        flush=True
                    )

                    print(
                        "=" * 60,
                        flush=True
                    )


                    train_ml_model()


                    last_train_time = (
                        current_time
                    )


                    gc.collect()


            # --------------------------------------------------------
            # СТАТИСТИКА
            # --------------------------------------------------------

            if (

                current_time
                -
                last_stats_time

                > 3600

            ):

                send_stats_report()

                last_stats_time = (
                    current_time
                )


            # --------------------------------------------------------
            # ОЧИСТКА
            # --------------------------------------------------------

            if len(processed_games) > 500:

                processed_games.clear()


            if len(predictions) > 200:

                predictions = (
                    predictions[-200:]
                )

                save_history(
                    predictions
                )


            time.sleep(
                CHECK_INTERVAL
            )


        except KeyboardInterrupt:

            print(
                "🛑 БОТ ОСТАНОВЛЕН",
                flush=True
            )

            break


        except Exception as e:

            print(
                f"❌ КРИТИЧЕСКАЯ ОШИБКА: "
                f"{e}",
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