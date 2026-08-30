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

warnings.filterwarnings("ignore")


# =====================================================================
# АВТОУСТАНОВКА ЗАВИСИМОСТЕЙ
# =====================================================================

try:
    import subprocess
    import importlib

    REQUIRED_PACKAGES = [
        "numpy",
        "catboost",
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
                importlib.import_module(
                    package.replace("-", "_")
                )

                print(
                    f"✅ {package} - уже установлен",
                    flush=True
                )

            except ImportError:

                print(
                    f"⚠️ {package} - НЕ НАЙДЕН",
                    flush=True
                )

                missing.append(package)

        if missing:

            print(
                f"\n📦 Нужно установить: {', '.join(missing)}",
                flush=True
            )

            for package in missing:

                if not install_package(package):

                    print(
                        f"❌ Не удалось установить {package}",
                        flush=True
                    )

                    return False

            print(
                "\n✅ ВСЕ ЗАВИСИМОСТИ УСТАНОВЛЕНЫ!",
                flush=True
            )

        else:

            print(
                "\n✅ ВСЕ ЗАВИСИМОСТИ УСТАНОВЛЕНЫ!",
                flush=True
            )

        print("=" * 60, flush=True)

        return True


    if not check_and_install_dependencies():

        print(
            "❌ ОШИБКА: Невозможно продолжить работу",
            flush=True
        )

        sys.exit(1)

except Exception as e:

    print(
        f"⚠️ Ошибка при проверке зависимостей: {e}",
        flush=True
    )


# =====================================================================
# ML
# =====================================================================

ML_AVAILABLE = False
ML_LIB = None

try:

    from catboost import CatBoostClassifier

    ML_AVAILABLE = True
    ML_LIB = "catboost"

    print("✅ CatBoost загружен!", flush=True)

except ImportError:

    print(
        "⚠️ CatBoost не установлен. Работаем без ML.",
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


print("=" * 60, flush=True)
print("🔍 ДИАГНОСТИКА ПЕРЕМЕННЫХ:", flush=True)

print(
    f"BOT_TOKEN: {BOT_TOKEN[:5] if BOT_TOKEN else 'НЕ ЗАДАН'}...",
    flush=True
)

print(
    f"CHANNEL_STATS: {CHANNEL_STATS if CHANNEL_STATS else 'НЕ ЗАДАН'}",
    flush=True
)

print(
    f"CHANNEL_PROGNOZ: {CHANNEL_PROGNOZ if CHANNEL_PROGNOZ else 'НЕ ЗАДАН'}",
    flush=True
)

print("=" * 60, flush=True)


if not BOT_TOKEN or not CHANNEL_STATS or not CHANNEL_PROGNOZ:

    print(
        "❌ ОШИБКА: переменные окружения не заданы!",
        flush=True
    )

    sys.exit(1)


# =====================================================================
# НАСТРОЙКИ
# =====================================================================

MOSCOW_TZ = pytz.timezone("Europe/Moscow")

BASE_URL = "https://1xlite-36553.pro"

DATA_FILE = "cards_data.json"
HISTORY_FILE = "cards_history.json"
ML_MODEL_FILE = "cards_model.pkl"
OFFSET_FILE = "cards_offset.txt"
GAME_HISTORY_FILE = "cards_game_history.json"
LEARNING_ERRORS_FILE = "learning_errors.json"


MAX_RECORDS = 10000

CHECK_INTERVAL = 5

OFFSET = 1

MIN_TRAIN_SAMPLES = 300

MAX_HISTORY = 2000

MAX_GAME_HISTORY = 10

DOGON_GAMES = 4

ML_CONFIDENCE_THRESHOLD = 0.60


TARGET_CARDS = [

    "J♠️",
    "J♣️",
    "J♦️",
    "J♥️",

    "Q♠️",
    "Q♣️",
    "Q♦️",
    "Q♥️",

    "K♠️",
    "K♣️",
    "K♦️",
    "K♥️",

    "A♠️",
    "A♣️",
    "A♦️",
    "A♥️"
]


SUITS = [
    "♠️",
    "♣️",
    "♦️",
    "♥️"
]


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
        "platform_type=desktop; lng=ru; cookies_agree_type=3; "
        "cookies_agree_type=3; tzo=3; is12h=0"
}


# =====================================================================
# ГЛОБАЛЬНЫЕ ПЕРЕМЕННЫЕ
# =====================================================================

ml_model = None

ml_initialized = False

collection_active = True

game_history = deque(
    maxlen=MAX_GAME_HISTORY
)


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


processed_games = set()

finished_games = set()

all_messages = []

predictions = []


# =====================================================================
# TELEGRAM
# =====================================================================

def get_updates(offset):

    url = (
        f"https://api.telegram.org/"
        f"bot{BOT_TOKEN}/getUpdates"
    )

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

    url = (
        f"https://api.telegram.org/"
        f"bot{BOT_TOKEN}/sendMessage"
    )

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

        print(
            f"❌ Ошибка отправки: {e}",
            flush=True
        )

        return None


def edit_message(message_id, text):

    url = (
        f"https://api.telegram.org/"
        f"bot{BOT_TOKEN}/editMessageText"
    )

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
🃏 ТОЧНАЯ КАРТА (ML ТОП-2)

📊 Собрано игр: {data_count}/{MAX_RECORDS}

🧠 ML:
{'✅ АКТИВНА' if ml_initialized else '⏳ ОЖИДАЕТ'}

🎯 Смещение: +{OFFSET} игр

📈 Догон: {DOGON_GAMES - 1} игр

⚡ Порог уверенности ML:
{int(ML_CONFIDENCE_THRESHOLD * 100)}%

⏰ {now.strftime('%d.%m.%Y %H:%M:%S')}
"""

    send_message(
        CHANNEL_PROGNOZ,
        msg
    )

    print(
        "🚀 БОТ ЗАПУЩЕН!",
        flush=True
    )


# =====================================================================
# ФАЙЛЫ ДАННЫХ
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

        except Exception:

            return []

    return []


def save_data(record):

    global collection_active, stats

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
            f"⏸️ СБОР ДАННЫХ ОСТАНОВЛЕН! "
            f"Достигнут лимит {MAX_RECORDS}",
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

        except Exception:

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

        except Exception:

            return deque(
                maxlen=MAX_GAME_HISTORY
            )

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

    except Exception:

        pass


def get_offset():

    if os.path.exists(OFFSET_FILE):

        try:

            with open(
                OFFSET_FILE,
                "r"
            ) as f:

                return int(
                    f.read().strip()
                )

        except Exception:

            return 0

    return 0


def save_offset(offset):

    with open(
        OFFSET_FILE,
        "w"
    ) as f:

        f.write(str(offset))


# =====================================================================
# API
# =====================================================================

def get_active_games():

    try:

        url = (
            f"{BASE_URL}/service-api/"
            f"main-live-feed/v3/games1x2"
            f"?cfView=3"
            f"&count=40"
            f"&fcountry=190"
            f"&gr=415"
            f"&grMode=4"
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


        if (
            isinstance(data, dict)
            and "Value" in data
        ):

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

            if (
                game.get("liga", {}).get("id")
                == 1643503
            ):

                game_id = game.get("id")

                if game_id:

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
        f"{BASE_URL}/service-api/LiveFeed/GetGameZip"
        f"?id={game_id}"
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


        return (
            None,
            None,
            None,
            None
        )


    except Exception as e:

        print(
            f"❌ Ошибка игры {game_id}: {e}",
            flush=True
        )

        return (
            None,
            None,
            None,
            None
        )


# =====================================================================
# ПАРСИНГ КАРТ API
# =====================================================================

def parse_cards_and_state(data):

    if not data or not isinstance(data, dict):

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

            except Exception:

                player_cards = []


        elif item.get("Key") == "P2":

            try:

                dealer_cards = json.loads(
                    item.get(
                        "Value",
                        "[]"
                    )
                )

            except Exception:

                dealer_cards = []


        elif item.get("Key") == "STATE":

            state = item.get("Value")


    return (
        player_cards,
        dealer_cards,
        state
    )


# =====================================================================
# НОМЕР ИГРЫ
# =====================================================================

def get_game_number_by_time():

    now = datetime.now(
        MOSCOW_TZ
    )

    start = now.replace(
        hour=3,
        minute=0,
        second=0,
        microsecond=0
    )


    if now < start:

        start -= timedelta(
            days=1
        )


    diff_minutes = (
        now - start
    ).total_seconds() / 60


    game_number = (
        int(diff_minutes) % 1440
    ) + 1


    return game_number


# =====================================================================
# ПАРСИНГ ИГРЫ ИЗ TELEGRAM
# =====================================================================

def normalize_suit(suit):

    if not suit:

        return "?"

    suit = suit.strip()

    if suit in (
        "♠",
        "♠️"
    ):

        return "♠️"

    if suit in (
        "♣",
        "♣️"
    ):

        return "♣️"

    if suit in (
        "♦",
        "♦️"
    ):

        return "♦️"

    if suit in (
        "♥",
        "♥️"
    ):

        return "♥️"

    return "?"


def parse_cards_from_part(part):

    cards_match = re.search(
        r"\(([^)]*)\)",
        part
    )

    if not cards_match:

        return []


    cards_str = (
        cards_match.group(1)
        .strip()
    )


    if not cards_str:

        return []


    cards = []

    i = 0


    while i < len(cards_str):

        if cards_str[i].isspace():

            i += 1

            continue


        rank = ""


        if (
            i + 1 < len(cards_str)
            and cards_str[i:i + 2] == "10"
        ):

            rank = "10"

            i += 2


        elif cards_str[i] in "AKQJ":

            rank = cards_str[i]

            i += 1


        elif cards_str[i].isdigit():

            rank = cards_str[i]

            i += 1


        else:

            i += 1

            continue


        suit = ""


        if i < len(cards_str):

            if cards_str.startswith(
                "♠️",
                i
            ):

                suit = "♠️"

                i += 2


            elif cards_str.startswith(
                "♣️",
                i
            ):

                suit = "♣️"

                i += 2


            elif cards_str.startswith(
                "♦️",
                i
            ):

                suit = "♦️"

                i += 2


            elif cards_str.startswith(
                "♥️",
                i
            ):

                suit = "♥️"

                i += 2


            elif cards_str[i] in "♠♣♦♥":

                suit = normalize_suit(
                    cards_str[i]
                )

                i += 1


            else:

                continue


        if rank and suit:

            cards.append({
                "rank": rank,
                "suit": suit
            })


    return cards


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


        separator = None


        for candidate in (
            "◀️",
            "▶️",
            "—",
            "-"
        ):

            if candidate in text:

                separator = candidate

                break


        if separator is None:

            return None


        parts = text.split(
            separator,
            1
        )


        if len(parts) < 2:

            return None


        player_part = parts[0].strip()

        dealer_part = parts[1].strip()


        player_cards = parse_cards_from_part(
            player_part
        )

        dealer_cards = parse_cards_from_part(
            dealer_part
        )


        return {

            "number":
                game_number,

            "player_cards":
                player_cards,

            "dealer_cards":
                dealer_cards,

            "text":
                text
        }


    except Exception as e:

        print(
            f"❌ Ошибка парсинга: {e}",
            flush=True
        )

        return None


def is_finished_game_text(text):

    if not text:

        return False

    return (
        "✅" in text
        or
        "🔰" in text
    )


# =====================================================================
# ИСТОРИЯ ИГР
# =====================================================================

def update_game_history(
    latency,
    cards,
    game_num
):

    global game_history


    all_cards = []


    for card in cards:

        rank = card.get(
            "rank",
            ""
        )

        suit = card.get(
            "suit",
            ""
        )


        if (
            rank
            and suit
            and rank != "?"
            and suit != "?"
        ):

            all_cards.append(
                rank + suit
            )


    game_history.append({

        "latency":
            latency,

        "cards":
            all_cards,

        "game_num":
            game_num,

        "timestamp":
            datetime.now(
                MOSCOW_TZ
            ).isoformat()
    })


    save_game_history()


def get_history_features():

    features = {}


    if len(game_history) >= 2:

        latencies = [
            g.get("latency", 0)
            for g in game_history
        ]


        features["prev_latency"] = (
            latencies[-2]
        )

        features["latency_delta"] = (
            latencies[-1]
            -
            latencies[-2]
        )


        if len(latencies) >= 5:

            recent = latencies[-5:]

            features["latency_trend"] = (
                recent[-1]
                -
                recent[0]
            ) / 5


    if len(game_history) >= 2:

        all_cards = []

        for game in game_history:

            all_cards.extend(
                game.get(
                    "cards",
                    []
                )
            )


        if all_cards:

            last_card = all_cards[-1]

            if last_card in TARGET_CARDS:

                features["prev_card"] = (
                    TARGET_CARDS.index(
                        last_card
                    )
                )


    now = datetime.now(
        MOSCOW_TZ
    )


    features["hour"] = now.hour

    features["minute"] = now.minute

    features["day_of_week"] = (
        now.weekday()
    )

    features["is_weekend"] = (
        1
        if now.weekday() >= 5
        else 0
    )


    return features


# =====================================================================
# FEATURES
# =====================================================================

def extract_features_from_game(
    game_data,
    latency,
    game_num
):

    if not game_data:

        return None


    player_cards = game_data.get(
        "player_cards",
        []
    )

    dealer_cards = game_data.get(
        "dealer_cards",
        []
    )


    features = {

        "latency":
            latency or 0,

        "game_num":
            game_num % 100,

        "p1_rank_val":
            0,

        "p1_suit":
            -1,

        "p2_rank_val":
            0,

        "p2_suit":
            -1,

        "p3_rank_val":
            0,

        "p3_suit":
            -1,

        "d1_rank_val":
            0,

        "d1_suit":
            -1,

        "d2_rank_val":
            0,

        "d2_suit":
            -1,

        "player_total":
            0,

        "dealer_total":
            0,

        "player_count":
            len(player_cards),

        "dealer_count":
            len(dealer_cards),

        "prev_latency":
            0,

        "latency_delta":
            0,

        "latency_trend":
            0,

        "prev_card":
            -1,

        "hour":
            0,

        "minute":
            0,

        "day_of_week":
            0,

        "is_weekend":
            0
    }


    for i, card in enumerate(
        player_cards[:3]
    ):

        rank = card.get(
            "rank",
            ""
        )

        suit = card.get(
            "suit",
            ""
        )


        if rank in RANK_VALUES:

            features[
                f"p{i + 1}_rank_val"
            ] = RANK_VALUES[rank]


        if suit in SUITS:

            features[
                f"p{i + 1}_suit"
            ] = SUITS.index(suit)


    for i, card in enumerate(
        dealer_cards[:2]
    ):

        rank = card.get(
            "rank",
            ""
        )

        suit = card.get(
            "suit",
            ""
        )


        if rank in RANK_VALUES:

            features[
                f"d{i + 1}_rank_val"
            ] = RANK_VALUES[rank]


        if suit in SUITS:

            features[
                f"d{i + 1}_suit"
            ] = SUITS.index(suit)


    player_total = 0


    for card in player_cards:

        rank = card.get(
            "rank",
            ""
        )

        if rank in RANK_VALUES:

            val = RANK_VALUES[rank]

            if val >= 11:

                player_total += 10

            else:

                player_total += val


    features["player_total"] = (
        player_total
    )


    dealer_total = 0


    for card in dealer_cards:

        rank = card.get(
            "rank",
            ""
        )

        if rank in RANK_VALUES:

            val = RANK_VALUES[rank]

            if val >= 11:

                dealer_total += 10

            else:

                dealer_total += val


    features["dealer_total"] = (
        dealer_total
    )


    history_features = (
        get_history_features()
    )


    for key, value in history_features.items():

        if key in features:

            features[key] = value


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
            f"⚠️ ML: недостаточно данных "
            f"({len(data)}/{MIN_TRAIN_SAMPLES})",
            flush=True
        )

        return False


    X = []

    y = []

    feature_names = None


    print(
        f"🧠 ML: начинаю обучение "
        f"на {len(data)} играх...",
        flush=True
    )


    for game in data:

        all_cards = (
            game.get(
                "player_cards",
                []
            )
            +
            game.get(
                "dealer_cards",
                []
            )
        )


        if not all_cards:

            continue


        features = extract_features_from_game(

            game,

            game.get(
                "latency_ms",
                0
            ),

            0
        )


        if not features:

            continue


        sorted_keys = sorted(
            features.keys()
        )


        if feature_names is None:

            feature_names = sorted_keys


        feature_vector = [

            features[key]

            for key in sorted_keys
        ]


        target_card = None


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


            if card_str in TARGET_CARDS:

                target_card = card_str

                break


        if target_card is None:

            continue


        X.append(
            feature_vector
        )

        y.append(
            TARGET_CARDS.index(
                target_card
            )
        )


    if len(X) < MIN_TRAIN_SAMPLES:

        print(
            f"⚠️ ML: недостаточно примеров "
            f"({len(X)}/{MIN_TRAIN_SAMPLES})",
            flush=True
        )

        return False


    print(
        f"🧠 ML: обучение на "
        f"{len(X)} примерах "
        f"из {len(data)} игр...",
        flush=True
    )


    print(
        f"📊 Признаков: "
        f"{len(feature_names)}",
        flush=True
    )


    X = np.array(X)

    y = np.array(y)


    if ML_LIB != "catboost":

        return False


    model = CatBoostClassifier(

        iterations=200,

        depth=6,

        learning_rate=0.08,

        random_seed=42,

        verbose=False,

        loss_function="MultiClass",

        early_stopping_rounds=30,

        l2_leaf_reg=5,

        thread_count=1
    )


    model.fit(
        X,
        y
    )


    ml_model = model

    ml_initialized = True


    try:

        with open(
            ML_MODEL_FILE,
            "wb"
        ) as f:

            pickle.dump({

                "model":
                    model,

                "feature_count":
                    len(X[0]),

                "train_samples":
                    len(X),

                "total_games":
                    len(data),

                "feature_names":
                    feature_names

            }, f)


        print(
            f"✅ Модель сохранена! "
            f"Обучено на {len(X)} "
            f"примерах из {len(data)} игр",
            flush=True
        )

        return True


    except Exception as e:

        print(
            f"⚠️ Ошибка сохранения: {e}",
            flush=True
        )

        return False


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

            data = pickle.load(f)


        ml_model = data["model"]

        ml_initialized = True


        print(
            f"✅ ML модель загружена "
            f"({data.get('train_samples', 0)} примеров)",
            flush=True
        )


        return True


    except Exception as e:

        print(
            f"⚠️ Не удалось загрузить "
            f"ML модель: {e}",
            flush=True
        )

        return False


def predict_ml(features):

    global ml_model
    global ml_initialized


    if (
        not ml_initialized
        or
        ml_model is None
    ):

        return None, None


    try:

        feature_vector = []

        for key in sorted(
            features.keys()
        ):

            feature_vector.append(
                features[key]
            )


        feature_vector = np.array([
            feature_vector
        ])


        probs = ml_model.predict_proba(
            feature_vector
        )[0]


        top_indices = np.argsort(
            probs
        )[-2:][::-1]


        top_cards = [

            (
                TARGET_CARDS[i],
                probs[i]
            )

            for i in top_indices
        ]


        confidence = probs[
            top_indices[0]
        ]


        return (
            top_cards,
            confidence
        )


    except Exception as e:

        print(
            f"⚠️ Ошибка ML-прогноза: {e}",
            flush=True
        )

        return None, None


# =====================================================================
# ПРОГНОЗ
# =====================================================================

def get_prediction(
    latency,
    current_game_data
):

    if not ml_initialized:

        print(
            "⏳ ML модель не инициализирована",
            flush=True
        )

        return (
            None,
            None,
            None
        )


    if not current_game_data:

        print(
            "⏳ Нет данных о текущей игре",
            flush=True
        )

        return (
            None,
            None,
            None
        )


    features = extract_features_from_game(

        current_game_data,

        latency,

        0
    )


    if not features:

        print(
            "⏳ Не удалось извлечь признаки",
            flush=True
        )

        return (
            None,
            None,
            None
        )


    ml_cards, confidence = predict_ml(
        features
    )


    if not ml_cards or confidence is None:

        print(
            "⏭️ ML не выдал карты",
            flush=True
        )

        return (
            None,
            None,
            None
        )


    print(
        "📊 ML: TOP-2 карт:",
        flush=True
    )


    for i, (card, prob) in enumerate(
        ml_cards,
        1
    ):

        print(
            f"   {i}. {card} — "
            f"{prob * 100:.1f}%",
            flush=True
        )


    print(
        f"   Максимальная уверенность: "
        f"{confidence * 100:.1f}%",
        flush=True
    )


    print(
        f"   Порог: "
        f"{ML_CONFIDENCE_THRESHOLD * 100:.0f}%",
        flush=True
    )


    if confidence >= ML_CONFIDENCE_THRESHOLD:

        print(
            f"✅ Уверенность "
            f"{confidence * 100:.1f}% "
            f">= "
            f"{ML_CONFIDENCE_THRESHOLD * 100:.0f}% "
            f"→ ДАЮ ПРОГНОЗ!",
            flush=True
        )

        return (
            ml_cards,
            "ml",
            confidence
        )


    print(
        f"⏭️ Уверенность "
        f"{confidence * 100:.1f}% "
        f"< "
        f"{ML_CONFIDENCE_THRESHOLD * 100:.0f}% "
        f"→ ПРОПУСКАЮ",
        flush=True
    )


    return (
        None,
        None,
        None
    )


# =====================================================================
# 🔥 ПРОВЕРКА РЕЗУЛЬТАТА ПРОГНОЗА
# =====================================================================

def find_finished_game_message(game_number):

    """
    Ищет в all_messages завершённую игру #N<game_number>.

    ВАЖНО:
    Проверяется именно сообщение из канала статистики.
    Используется существующая логика:
    завершённая игра определяется по ✅ или 🔰.
    """

    target_tag = f"#N{game_number}"

    found_candidates = []


    for item in all_messages:

        if isinstance(item, tuple):

            text = item[0]

            timestamp = (
                item[1]
                if len(item) > 1
                else 0
            )

        else:

            text = item

            timestamp = 0


        if not text:

            continue


        if target_tag not in text:

            continue


        if not is_finished_game_text(text):

            continue


        found_candidates.append(
            (
                timestamp,
                text
            )
        )


    if not found_candidates:

        return None


    # Берём самое свежее подходящее сообщение.
    found_candidates.sort(
        key=lambda x: x[0]
    )


    return found_candidates[-1][1]


def get_actual_cards_from_game(game_data):

    actual_cards = []


    if not game_data:

        return actual_cards


    player_cards = game_data.get(
        "player_cards",
        []
    )

    dealer_cards = game_data.get(
        "dealer_cards",
        []
    )


    # Сначала игрок, затем дилер —
    # как в исходной логике.
    all_cards = (
        player_cards
        +
        dealer_cards
    )


    for card in all_cards:

        rank = card.get(
            "rank",
            ""
        )

        suit = card.get(
            "suit",
            ""
        )


        if (
            not rank
            or
            not suit
        ):

            continue


        if (
            rank == "?"
            or
            suit == "?"
        ):

            continue


        card_str = (
            rank
            +
            suit
        )


        actual_cards.append(
            card_str
        )


    return actual_cards


def save_learning_error(
    features,
    correct_card,
    predicted_cards,
    game_num
):

    try:

        errors = []


        if os.path.exists(
            LEARNING_ERRORS_FILE
        ):

            try:

                with open(
                    LEARNING_ERRORS_FILE,
                    "r",
                    encoding="utf-8"
                ) as f:

                    errors = json.load(f)

            except Exception:

                errors = []


        errors.append({

            "timestamp":
                datetime.now(
                    MOSCOW_TZ
                ).isoformat(),

            "features":
                features,

            "correct_card":
                correct_card,

            "predicted_cards":
                predicted_cards,

            "game_num":
                game_num
        })


        # Не даём файлу расти бесконечно.
        if len(errors) > 5000:

            errors = errors[-5000:]


        with open(
            LEARNING_ERRORS_FILE,
            "w",
            encoding="utf-8"
        ) as f:

            json.dump(
                errors,
                f,
                indent=2,
                ensure_ascii=False
            )


        print(
            f"📝 Ошибка сохранена "
            f"в {LEARNING_ERRORS_FILE}",
            flush=True
        )


    except Exception as e:

        print(
            f"⚠️ Не удалось сохранить "
            f"ошибку обучения: {e}",
            flush=True
        )


def check_results():

    """
    ПРОВЕРКА РЕЗУЛЬТАТОВ.

    Для каждого pending-прогноза:

    target
       ↓
    target + 1
       ↓
    target + 2
       ↓
    target + 3

    Если любая карта из TOP-2 найдена
    в любой позиции игрока или дилера:
        WIN

    Если после 4 завершённых игр
    карты нет:
        LOSE
    """

    global predictions
    global stats
    global ml_model


    changed = False


    for entry in predictions:

        if entry.get("status") != "pending":

            continue


        target = entry.get(
            "target"
        )


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


        method = entry.get(
            "method",
            "ml"
        )


        if (
            target is None
            or
            not predicted_cards
            or
            not message_id
        ):

            continue


        # =============================================================
        # Проверяем 4 игры:
        #
        # 0 = целевая
        # 1 = догон №1
        # 2 = догон №2
        # 3 = догон №3
        # =============================================================

        max_games_to_check = DOGON_GAMES

        result_found = False


        for dogon in range(
            max_games_to_check
        ):

            game_to_check = (
                target + dogon
            )


            game_msg = find_finished_game_message(
                game_to_check
            )


            # Игра ещё не завершена
            # или сообщение ещё не пришло.
            if not game_msg:

                print(
                    f"⏳ Для прогноза #{target} "
                    f"ещё нет завершённой игры "
                    f"#{game_to_check}",
                    flush=True
                )

                # Нельзя считать проигрыш,
                # пока последняя игра ещё не появилась.
                continue


            game_data = parse_game_from_text(
                game_msg
            )


            if not game_data:

                print(
                    f"⚠️ Не удалось распарсить "
                    f"завершённую игру #{game_to_check}",
                    flush=True
                )

                continue


            actual_cards = get_actual_cards_from_game(
                game_data
            )


            if not actual_cards:

                print(
                    f"⚠️ В игре #{game_to_check} "
                    f"нет распознанных карт",
                    flush=True
                )

                continue


            print(
                f"🔎 Проверка прогноза #{target}: "
                f"игра #{game_to_check}, "
                f"догон {dogon}",
                flush=True
            )


            print(
                f"   Прогноз: "
                f"{', '.join(predicted_cards)}",
                flush=True
            )


            print(
                f"   Реальные карты: "
                f"{', '.join(actual_cards)}",
                flush=True
            )


            # =========================================================
            # ИЩЕМ ЛЮБУЮ КАРТУ ИЗ TOP-2
            # В ЛЮБОЙ ПОЗИЦИИ:
            # игрок + дилер
            # =========================================================

            found_card = None


            for actual_card in actual_cards:

                if actual_card in predicted_cards:

                    found_card = actual_card

                    break


            # =========================================================
            # WIN
            # =========================================================

            if found_card:

                print(
                    f"🎯 КАРТА НАЙДЕНА! "
                    f"{found_card} "
                    f"в игре #{game_to_check} "
                    f"(догон {dogon})",
                    flush=True
                )


                stats["total"] += 1

                stats["win"] += 1

                stats["by_dogon"][dogon] = (
                    stats["by_dogon"].get(
                        dogon,
                        0
                    ) + 1
                )


                if method == "ml":

                    stats["ml_wins"] += 1


                stats["card_hits"][
                    found_card
                ] += 1


                if dogon == 0:

                    result_text = (
                        f"\n\n"
                        f"✅ ЗАШЛО "
                        f"в целевой игре: "
                        f"#{game_to_check}\n"
                        f"   Выпала: "
                        f"{found_card}"
                    )

                else:

                    result_text = (
                        f"\n\n"
                        f"✅ ЗАШЛО "
                        f"на догоне {dogon}: "
                        f"#{game_to_check}\n"
                        f"   Выпала: "
                        f"{found_card}"
                    )


                if message_id:

                    edit_message(
                        message_id,
                        original_text
                        +
                        result_text
                    )


                entry["status"] = "win"

                entry["result_game"] = (
                    game_to_check
                )

                entry["dogon"] = dogon

                entry["found_card"] = (
                    found_card
                )

                entry["checked_games"] = (
                    dogon + 1
                )

                entry["actual_cards"] = (
                    actual_cards
                )


                changed = True


                # ВАЖНО:
                # Не return.
                #
                # Проверяем следующие pending-прогнозы.
                break


            # =========================================================
            # Если карта не найдена в текущей игре,
            # просто переходим к следующему догону.
            # =========================================================

            print(
                f"   ❌ В игре #{game_to_check} "
                f"прогнозируемых карт нет",
                flush=True
            )


        # =============================================================
        # После проверки всех 4 игр определяем LOSE.
        #
        # НО только если ВСЕ 4 завершённые игры
        # реально существуют и были распознаны.
        # =============================================================

        if (
            entry.get("status") == "pending"
            and
            not result_found
        ):

            checked_games = 0

            all_checked = True

            last_actual_cards = []


            for dogon in range(
                max_games_to_check
            ):

                game_to_check = (
                    target + dogon
                )


                game_msg = find_finished_game_message(
                    game_to_check
                )


                if not game_msg:

                    all_checked = False

                    break


                game_data = parse_game_from_text(
                    game_msg
                )


                if not game_data:

                    all_checked = False

                    break


                actual_cards = get_actual_cards_from_game(
                    game_data
                )


                if not actual_cards:

                    all_checked = False

                    break


                checked_games += 1

                last_actual_cards = actual_cards


                # Дополнительная защита.
                if any(
                    card in predicted_cards
                    for card in actual_cards
                ):

                    all_checked = False

                    break


            # =========================================================
            # LOSE только после полноценной проверки 4 игр.
            # =========================================================

            if (
                all_checked
                and
                checked_games == max_games_to_check
            ):

                print(
                    f"❌ Карты "
                    f"{', '.join(predicted_cards)} "
                    f"НЕ НАЙДЕНЫ "
                    f"за {max_games_to_check} игр",
                    flush=True
                )


                # -----------------------------------------------------
                # Находим фактическую карту первой
                # подходящей категории J/Q/K/A.
                #
                # Это используется только для анализа ошибки.
                # Результат уже однозначно LOSE.
                # -----------------------------------------------------

                actual_target = None


                for dogon in range(
                    max_games_to_check
                ):

                    game_to_check = (
                        target + dogon
                    )

                    game_msg = (
                        find_finished_game_message(
                            game_to_check
                        )
                    )


                    if not game_msg:

                        continue


                    game_data = (
                        parse_game_from_text(
                            game_msg
                        )
                    )


                    if not game_data:

                        continue


                    actual_cards = (
                        get_actual_cards_from_game(
                            game_data
                        )
                    )


                    for card_str in actual_cards:

                        if (
                            card_str
                            in TARGET_CARDS
                        ):

                            actual_target = (
                                card_str
                            )

                            break


                    if actual_target:

                        break


                # -----------------------------------------------------
                # Статистика
                # -----------------------------------------------------

                stats["total"] += 1

                stats["lose"] += 1


                if method == "ml":

                    stats["ml_losses"] += 1


                # -----------------------------------------------------
                # Сохраняем ошибку для последующего обучения.
                #
                # CatBoost не имеет нормального partial_fit(),
                # поэтому здесь НЕ пытаемся делать:
                #
                # ml_model.partial_fit(...)
                #
                # Вместо этого сохраняем ошибку.
                # При следующем полном переобучении модель
                # обучится заново на накопленной истории игр.
                # -----------------------------------------------------

                if actual_target:

                    print(
                        f"📘 ОШИБКА: "
                        f"ждали "
                        f"{', '.join(predicted_cards)}, "
                        f"в истории появилась "
                        f"{actual_target}",
                        flush=True
                    )


                    try:

                        features = None


                        # Берём первую игру из проверенного
                        # диапазона, чтобы сохранить признаки
                        # контекста прогноза.
                        first_game_msg = (
                            find_finished_game_message(
                                target
                            )
                        )


                        if first_game_msg:

                            first_game_data = (
                                parse_game_from_text(
                                    first_game_msg
                                )
                            )


                            if first_game_data:

                                features = (
                                    extract_features_from_game(
                                        first_game_data,
                                        entry.get(
                                            "latency",
                                            0
                                        ),
                                        target
                                    )
                                )


                        if features:

                            save_learning_error(

                                features,

                                actual_target,

                                predicted_cards,

                                target
                            )


                    except Exception as e:

                        print(
                            f"⚠️ Ошибка сохранения "
                            f"данных обучения: {e}",
                            flush=True
                        )


                else:

                    print(
                        "📘 Подходящая J/Q/K/A "
                        "карта для анализа "
                        "не найдена.",
                        flush=True
                    )


                result_text = (
                    f"\n\n"
                    f"❌ НЕ ЗАШЛО "
                    f"(проверено "
                    f"{max_games_to_check} игр)"
                )


                if actual_target:

                    result_text += (
                        f"\n"
                        f"   Выпала: "
                        f"{actual_target}"
                    )

                else:

                    result_text += (
                        "\n"
                        "   Подходящая карта "
                        "не определена"
                    )


                if message_id:

                    edit_message(
                        message_id,
                        original_text
                        +
                        result_text
                    )


                entry["status"] = "lose"

                entry["checked_games"] = (
                    max_games_to_check
                )

                entry["actual_card"] = (
                    actual_target
                )


                entry["result_game"] = (
                    target + max_games_to_check - 1
                )


                changed = True


    if changed:

        save_history(
            predictions
        )


# =====================================================================
# ПЛАНИРОВАНИЕ ПРОГНОЗА
# =====================================================================

def schedule_for_game(
    game_number
):

    global predictions


    target = (
        game_number
        +
        OFFSET
    )


    for entry in predictions:

        if (
            entry.get("target")
            == target
            and
            entry.get("status")
            in (
                "scheduled",
                "pending"
            )
        ):

            return


    source = (
        target
        -
        1
    )


    predictions.append({

        "source":
            source,

        "target":
            target,

        "offset":
            OFFSET,

        "status":
            "scheduled",

        "created":
            datetime.now(
                MOSCOW_TZ
            ).isoformat()
    })


    if len(predictions) > 200:

        predictions = predictions[-200:]


    save_history(
        predictions
    )


    print(
        f"📅 Запланирован прогноз: "
        f"#{source} → #{target} "
        f"(+{OFFSET})",
        flush=True
    )


# =====================================================================
# ПРОВЕРКА УСЛОВИЙ И ОТПРАВКА ПРОГНОЗА
# =====================================================================

def check_and_predict():

    global predictions
    global all_messages
    global game_history


    current_num = get_game_number_by_time()


    for entry in predictions:

        if entry.get("status") != "scheduled":

            continue


        target = entry.get(
            "target"
        )


        if target is None:

            continue


        games_left = (
            target
            -
            current_num
        )


        if (
            games_left != 2
            and
            games_left != 1
        ):

            continue


        print(
            f"🔥 До цели #{target} "
            f"осталось {games_left} игр! "
            f"Делаю прогноз...",
            flush=True
        )


        latency = None


        active_games = get_active_games()


        for game in active_games:

            game_id = str(
                game.get("id")
            )


            data, measured_latency, _, _ = (
                get_game_data(
                    game_id
                )
            )


            if data:

                latency = measured_latency

                break


        if latency is None:

            print(
                "⏳ Не удалось получить задержку",
                flush=True
            )

            continue


        current_game_data = None


        # -------------------------------------------------------------
        # Ищем текущую игру в Telegram.
        # -------------------------------------------------------------

        for item in all_messages:

            if isinstance(item, tuple):

                text = item[0]

            else:

                text = item


            if (
                f"#N{current_num}" in text
            ):

                parsed = (
                    parse_game_from_text(
                        text
                    )
                )


                if parsed:

                    current_game_data = (
                        parsed
                    )

                    break


        if not current_game_data:

            print(
                f"⏳ Нет данных "
                f"о текущей игре "
                f"#{current_num}",
                flush=True
            )

            continue


        predicted_cards, method, confidence = (
            get_prediction(
                latency,
                current_game_data
            )
        )


        if (
            not predicted_cards
            or
            len(predicted_cards) < 2
        ):

            print(
                f"⏭️ Нет прогноза "
                f"от ML для #{target}",
                flush=True
            )

            continue


        # =============================================================
        # ПРОВЕРКА МАСТИ ПЕРВОЙ КАРТЫ
        # =============================================================

        first_predicted_card = (
            predicted_cards[0][0]
        )


        predicted_suit = None


        for suit in SUITS:

            if first_predicted_card.endswith(
                suit
            ):

                predicted_suit = suit

                break


        if predicted_suit:

            current_cards = (
                current_game_data.get(
                    "player_cards",
                    []
                )
                +
                current_game_data.get(
                    "dealer_cards",
                    []
                )
            )


            check_cards = current_cards[:4]


            blocked = False


            for card in check_cards:

                if (
                    card.get("suit")
                    == predicted_suit
                ):

                    blocked = True

                    break


            if blocked:

                print(
                    f"⏭️ Масть "
                    f"{predicted_suit} "
                    f"уже была в текущей игре "
                    f"→ пропускаю прогноз "
                    f"для #{target}",
                    flush=True
                )

                continue


        # =============================================================
        # ОБНОВЛЯЕМ ИСТОРИЮ
        # =============================================================

        all_cards = (
            current_game_data.get(
                "player_cards",
                []
            )
            +
            current_game_data.get(
                "dealer_cards",
                []
            )
        )


        update_game_history(
            latency,
            all_cards,
            current_num
        )


        # =============================================================
        # ФОРМИРУЕМ СООБЩЕНИЕ
        # =============================================================

        total_prob = 0


        msg = (
            "🔮 ТОЧНАЯ КАРТА "
            "(ML ТОП-2)\n\n"
        )


        msg += (
            f"🎯 Целевая игра: "
            f"#N{target} "
            f"(+{OFFSET})\n"
        )


        msg += (
            f"🤖 Метод: ML "
            f"(увер. "
            f"{confidence * 100:.1f}%)\n"
        )


        msg += (
            f"⏰ Прогноз: "
            f"{datetime.now(MOSCOW_TZ).strftime('%H:%M:%S')}\n\n"
        )


        msg += (
            "📊 Топ-2 карты:\n"
        )


        cards_list = []


        for i, (
            card,
            prob
        ) in enumerate(
            predicted_cards,
            1
        ):

            cards_list.append(
                card
            )


            msg += (
                f"  {i}️⃣ "
                f"{card} — "
                f"{prob * 100:.1f}%\n"
            )


            total_prob += prob


        msg += (
            f"\n📊 Суммарная вероятность: "
            f"{total_prob * 100:.1f}%\n"
        )


        msg += (
            f"📈 Догон: "
            f"{DOGON_GAMES - 1} игр\n"
        )


        msg += (
            "📍 Ищем: любую позицию "
            "(игрок/дилер)"
        )


        # =============================================================
        # ПОКАЗЫВАЕМ ТЕКУЩУЮ ПОСЛЕДОВАТЕЛЬНОСТЬ
        # =============================================================

        p1 = (
            current_game_data
            .get("player_cards", [])
        )


        d1 = (
            current_game_data
            .get("dealer_cards", [])
        )


        seq_str = ""


        if len(p1) > 0:

            card = p1[0]

            seq_str += (
                f"P1:{card['rank']}"
                f"{card['suit']} "
            )


        if len(d1) > 0:

            card = d1[0]

            seq_str += (
                f"D1:{card['rank']}"
                f"{card['suit']} "
            )


        if len(p1) > 1:

            card = p1[1]

            seq_str += (
                f"P2:{card['rank']}"
                f"{card['suit']}"
            )


        if seq_str:

            msg += (
                f"\n📌 {seq_str}"
            )


        # =============================================================
        # ОТПРАВКА
        # =============================================================

        message_id = send_message(
            CHANNEL_PROGNOZ,
            msg
        )


        if message_id:

            entry["cards"] = (
                cards_list
            )

            entry["method"] = (
                method
            )

            entry["message_id"] = (
                message_id
            )

            entry["original_text"] = (
                msg
            )

            entry["status"] = (
                "pending"
            )

            entry["latency"] = (
                latency
            )

            entry["confidence"] = (
                confidence
            )

            entry["checked_games"] = 0


            save_history(
                predictions
            )


            print(
                f"✅ ПРОГНОЗ ОТПРАВЛЕН: "
                f"#{target} → "
                f"{', '.join(cards_list)} "
                f"(ML, уверенность "
                f"{confidence * 100:.1f}%)",
                flush=True
            )


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


        game_data, latency, start_time, end_time = (
            get_game_data(
                game_id
            )
        )


        if (
            not game_data
            or
            not isinstance(
                game_data,
                dict
            )
        ):

            continue


        player_cards, dealer_cards, state = (
            parse_cards_and_state(
                game_data
            )
        )


        if (
            player_cards
            or
            dealer_cards
        ):

            timestamp = (

                datetime.fromtimestamp(
                    start_time,
                    MOSCOW_TZ
                )

                if start_time

                else

                datetime.now(
                    MOSCOW_TZ
                )
            )


            timestamp_msk_str = (
                timestamp.strftime(
                    "%H:%M:%S.%f"
                )[:-3]
            )


            def format_card(c):

                return {

                    "rank":
                        RANKS.get(
                            c.get(
                                "CV",
                                0
                            ),
                            "?"
                        ),

                    "suit":
                        SUITS_NAMES.get(
                            c.get(
                                "CS",
                                0
                            ),
                            "?"
                        )
                }


            sequence = []


            max_len = max(
                len(player_cards),
                len(dealer_cards)
            )


            for i in range(max_len):

                if i < len(
                    player_cards
                ):

                    pc = player_cards[i]


                    rank = RANKS.get(
                        pc.get(
                            "CV",
                            0
                        ),
                        "?"
                    )


                    suit = SUITS_NAMES.get(
                        pc.get(
                            "CS",
                            0
                        ),
                        "?"
                    )


                    sequence.append({

                        "position":
                            i * 2 + 1,

                        "who":
                            "P",

                        "rank":
                            rank,

                        "suit":
                            suit
                    })


                if i < len(
                    dealer_cards
                ):

                    dc = dealer_cards[i]


                    rank = RANKS.get(
                        dc.get(
                            "CV",
                            0
                        ),
                        "?"
                    )


                    suit = SUITS_NAMES.get(
                        dc.get(
                            "CS",
                            0
                        ),
                        "?"
                    )


                    sequence.append({

                        "position":
                            i * 2 + 2,

                        "who":
                            "D",

                        "rank":
                            rank,

                        "suit":
                            suit
                    })


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

                "player_cards":
                    [
                        format_card(c)
                        for c in player_cards
                    ],

                "dealer_cards":
                    [
                        format_card(c)
                        for c in dealer_cards
                    ],

                "sequence":
                    sequence
            }


            data = save_data(
                record
            )


            if state in [
                "4",
                "5"
            ]:

                finished_games.add(
                    game_id
                )


                print(
                    f"🏁 Игра {game_id} "
                    f"завершена "
                    f"(state={state}), "
                    f"сохранена",
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
📊 СТАТИСТИКА
(ТОЧНАЯ КАРТА — ML ТОП-2)

⏰ {now.strftime('%d.%m.%Y %H:%M:%S')}

══════════════════════════════════════════

📊 Собрано игр:
{data_count}/{MAX_RECORDS}

📈 Всего прогнозов:
{stats["total"]}

✅ Зашло:
{stats["win"]} ({win_percent:.1f}%)

❌ Не зашло:
{stats["lose"]}

🤖 ML:
{stats["ml_wins"]}✅ / {stats["ml_losses"]}❌

По догонам ({DOGON_GAMES - 1} игр):

  Догон 0:
  {stats["by_dogon"].get(0, 0)}

  Догон 1:
  {stats["by_dogon"].get(1, 0)}

  Догон 2:
  {stats["by_dogon"].get(2, 0)}

  Догон 3:
  {stats["by_dogon"].get(3, 0)}
"""


    msg += "\n\nТоп-5 карт:\n"


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
            "  (пока нет данных)\n"
        )


    if ml_initialized:

        msg += (
            "\n🤖 ML: АКТИВНА"
        )

    else:

        msg += (
            f"\n🤖 ML: ОЖИДАЕТ "
            f"({data_count}/"
            f"{MIN_TRAIN_SAMPLES})"
        )


    send_message(
        CHANNEL_STATS,
        msg
    )


# =====================================================================
# ЗАГРУЗКА СТАРЫХ TELEGRAM СООБЩЕНИЙ
# =====================================================================

def load_initial_messages():

    global all_messages


    try:

        url = (
            f"https://api.telegram.org/"
            f"bot{BOT_TOKEN}/getUpdates"
        )


        params = {

            "chat_id":
                CHANNEL_STATS,

            "limit":
                100
        }


        response = requests.get(

            url,

            params=params,

            timeout=10
        )


        if response.status_code != 200:

            return


        data = response.json()


        for update in data.get(
            "result",
            []
        ):

            post = update.get(
                "channel_post"
            )


            if (
                post
                and
                post.get("text")
            ):

                all_messages.append((

                    post.get("text"),

                    time.time()

                ))


    except Exception as e:

        print(
            f"⚠️ Ошибка загрузки "
            f"старых сообщений: {e}",
            flush=True
        )


# =====================================================================
# ОСНОВНОЙ ЦИКЛ
# =====================================================================

def main():

    global predictions
    global all_messages
    global stats
    global game_history
    global collection_active


    print(
        "🔄 ТОЧНАЯ КАРТА "
        "(ML ТОП-2) ЗАПУЩЕН",
        flush=True
    )


    print(
        f"📁 Данные: {DATA_FILE}",
        flush=True
    )


    print(
        f"📊 Максимум записей: "
        f"{MAX_RECORDS}",
        flush=True
    )


    print(
        f"🎯 Смещение: +{OFFSET} игр",
        flush=True
    )


    print(
        f"📈 Догон: "
        f"{DOGON_GAMES - 1} игр",
        flush=True
    )


    print(
        f"⚡ Порог уверенности ML: "
        f"{int(ML_CONFIDENCE_THRESHOLD * 100)}%",
        flush=True
    )


    print(
        f"🃏 Карт для прогноза: "
        f"{len(TARGET_CARDS)}",
        flush=True
    )


    print("=" * 60, flush=True)


    existing_data = load_data()


    print(
        f"📊 Уже собрано записей: "
        f"{len(existing_data)}",
        flush=True
    )


    if len(existing_data) >= MAX_RECORDS:

        collection_active = False


        print(
            f"⏸️ СБОР ДАННЫХ ОТКЛЮЧЁН "
            f"(лимит {MAX_RECORDS})",
            flush=True
        )


    game_history = load_game_history()


    print(
        f"📈 Загружено истории: "
        f"{len(game_history)} игр",
        flush=True
    )


    predictions = load_history()


    print(
        f"📋 Загружено прогнозов: "
        f"{len(predictions)}",
        flush=True
    )


    # -------------------------------------------------------------
    # Показываем pending после рестарта
    # -------------------------------------------------------------

    pending_count = sum(

        1

        for entry in predictions

        if entry.get("status")
        == "pending"

    )


    print(
        f"⏳ Незавершённых прогнозов: "
        f"{pending_count}",
        flush=True
    )


    load_ml_model()


    stats["games_collected"] = (
        len(existing_data)
    )


    send_startup_message()


    load_initial_messages()


    print(
        f"📥 Загружено сообщений: "
        f"{len(all_messages)}",
        flush=True
    )


    last_stats_time = time.time()

    last_train_time = time.time()

    last_check_time = time.time()


    offset = get_offset()


    print(
        "🚀 БОТ ГОТОВ К РАБОТЕ!",
        flush=True
    )

    print("=" * 60, flush=True)


    while True:

        try:

            current_time = time.time()


            # =========================================================
            # 1. СОБИРАЕМ ИГРЫ
            # =========================================================

            collect_game_data()


            # =========================================================
            # 2. TELEGRAM UPDATES
            # =========================================================

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


                chat_id = (
                    post
                    .get("chat", {})
                    .get("id")
                )


                if str(chat_id) != str(
                    CHANNEL_STATS
                ):

                    continue


                text = post.get(
                    "text",
                    ""
                )


                if (
                    not text
                    or
                    "#N" not in text
                ):

                    continue


                # -----------------------------------------------------
                # Сохраняем ВСЕ сообщения.
                # -----------------------------------------------------

                all_messages.append((

                    text,

                    time.time()

                ))


                if len(all_messages) > 1000:

                    all_messages = (
                        all_messages[-1000:]
                    )


                game_id_match = re.search(
                    r"#N(\d+)",
                    text
                )


                if game_id_match:

                    game_number = int(
                        game_id_match.group(1)
                    )


                    print(
                        f"📥 Получена игра "
                        f"#{game_number}",
                        flush=True
                    )


                    # -------------------------------------------------
                    # Планируем прогноз.
                    # -------------------------------------------------

                    schedule_for_game(
                        game_number
                    )


                    # -------------------------------------------------
                    # СРАЗУ ПРОВЕРЯЕМ СТАРЫЕ
                    # PENDING-ПРОГНОЗЫ.
                    # -------------------------------------------------

                    check_results()


            # =========================================================
            # 3. ПЕРИОДИЧЕСКИЙ ПРОГНОЗ
            # =========================================================

            if (
                current_time
                -
                last_check_time
                >=
                CHECK_INTERVAL
            ):

                check_and_predict()

                last_check_time = (
                    current_time
                )


            # =========================================================
            # 4. ПРОВЕРКА РЕЗУЛЬТАТОВ
            #
            # ВАЖНО:
            # Это выполняется постоянно.
            # Поэтому прогноз не зависит от того,
            # пришёл ли результат именно в момент
            # получения Telegram update.
            # =========================================================

            check_results()


            # =========================================================
            # 5. ПЕРЕОБУЧЕНИЕ КАЖДЫЕ 3 МИНУТЫ
            # =========================================================

            if (
                current_time
                -
                last_train_time
                >
                180
            ):

                data_count = len(
                    load_data()
                )


                if data_count >= (
                    MIN_TRAIN_SAMPLES
                ):

                    print(
                        f"🔄 ЗАПУСК "
                        f"ПЕРЕОБУЧЕНИЯ "
                        f"(всего игр: "
                        f"{data_count})...",
                        flush=True
                    )


                    train_ml_model()


                    last_train_time = (
                        current_time
                    )


                    gc.collect()


            # =========================================================
            # 6. СТАТИСТИКА
            # =========================================================

            if (
                current_time
                -
                last_stats_time
                >
                3600
            ):

                send_stats_report()


                last_stats_time = (
                    current_time
                )


            # =========================================================
            # 7. ОЧИСТКА
            # =========================================================

            if len(processed_games) > 500:

                processed_games.clear()


            if len(predictions) > 200:

                predictions = (
                    predictions[-200:]
                )


                save_history(
                    predictions
                )


            # =========================================================
            # 8. ПАУЗА
            # =========================================================

            time.sleep(
                CHECK_INTERVAL
            )


        except KeyboardInterrupt:

            print(
                "🛑 Бот остановлен",
                flush=True
            )


            data_count = len(
                load_data()
            )


            print(
                f"📊 Всего собрано "
                f"записей: {data_count}",
                flush=True
            )


            break


        except Exception as e:

            print(
                f"❌ Ошибка: {e}",
                flush=True
            )


            import traceback


            traceback.print_exc()


            time.sleep(
                30
            )


# =====================================================================
# START
# =====================================================================

if __name__ == "__main__":

    main()