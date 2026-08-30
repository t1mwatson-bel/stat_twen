```python
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
warnings.filterwarnings('ignore')

# =====================================================================
# АВТОУСТАНОВКА ЗАВИСИМОСТЕЙ
# =====================================================================
try:
    import subprocess
    import importlib

    REQUIRED_PACKAGES = [
        'numpy',
        'scikit-learn',
        'requests',
        'pytz'
    ]

    def install_package(package):
        print(f"📦 Устанавливаю: {package}...", flush=True)
        try:
            subprocess.check_call([
                sys.executable, "-m", "pip", "install",
                package, "--quiet"
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
                importlib.import_module(package.replace('-', '_'))
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
# ML-БИБЛИОТЕКА
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
        "⚠️ RandomForest не установлен. Работаем без ML.",
        flush=True
    )

# =====================================================================
# ПЕРЕМЕННЫЕ ОКРУЖЕНИЯ
# =====================================================================
BOT_TOKEN = os.getenv('BOT_TOKEN')

if not BOT_TOKEN:
    BOT_TOKEN = os.getenv('BOT_TOKEN_PROGNOZ')

CHANNEL_STATS = os.getenv('CHANNEL_STATS')
CHANNEL_PROGNOZ = os.getenv('CHANNEL_PROGNOZ')

print("=" * 60, flush=True)
print("🔍 ДИАГНОСТИКА ПЕРЕМЕННЫХ:", flush=True)
print(
    f"BOT_TOKEN: {BOT_TOKEN[:5] if BOT_TOKEN else 'НЕ ЗАДАН'}...",
    flush=True
)
print(
    f"CHANNEL_STATS: "
    f"{CHANNEL_STATS if CHANNEL_STATS else 'НЕ ЗАДАН'}",
    flush=True
)
print(
    f"CHANNEL_PROGNOZ: "
    f"{CHANNEL_PROGNOZ if CHANNEL_PROGNOZ else 'НЕ ЗАДАН'}",
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
MOSCOW_TZ = pytz.timezone('Europe/Moscow')
BASE_URL = "https://1xlite-0687.pro"

DATA_FILE = "cards_data.json"
HISTORY_FILE = "cards_history.json"
ML_MODEL_FILE = "cards_model.pkl"
OFFSET_FILE = "cards_offset.txt"
GAME_HISTORY_FILE = "cards_game_history.json"

MAX_RECORDS = 10000
CHECK_INTERVAL = 5
OFFSET = 1
MIN_TRAIN_SAMPLES = 300
MAX_HISTORY = 2000
MAX_GAME_HISTORY = 10
DOGON_GAMES = 4
ML_CONFIDENCE_THRESHOLD = 0.45

TARGET_CARDS = [
    "J♠️", "J♣️", "J♦️", "J♥️",
    "Q♠️", "Q♣️", "Q♦️", "Q♥️",
    "K♠️", "K♣️", "K♦️", "K♥️",
    "A♠️", "A♣️", "A♦️", "A♥️"
]

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
        "platform_type=desktop; lng=ru; "
        "cookies_agree_type=3; tzo=3; is12h=0"
    )
}

SUITS = ["♠️", "♣️", "♦️", "♥️"]

SUITS_NAMES = {
    0: "♠️",
    1: "♣️",
    2: "♦️",
    3: "♥️"
}

RANK_VALUES = {
    '6': 6,
    '7': 7,
    '8': 8,
    '9': 9,
    '10': 10,
    'J': 11,
    'Q': 12,
    'K': 13,
    'A': 14
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

# =====================================================================
# ГЛОБАЛЬНЫЕ ПЕРЕМЕННЫЕ
# =====================================================================
ml_model = None
ml_initialized = False
collection_active = True
game_history = deque(maxlen=MAX_GAME_HISTORY)

stats = {
    "total": 0,
    "win": 0,
    "lose": 0,
    "by_dogon": {0: 0, 1: 0, 2: 0, 3: 0},
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
# ФУНКЦИИ ТЕЛЕГРАМ
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

        else:
            print(
                f"❌ Ошибка отправки: "
                f"{response.status_code}",
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
        f"https://api.telegram.org/bot{BOT_TOKEN}/"
        "editMessageText"
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
🧠 ML: {'✅ АКТИВНА' if ml_initialized else '⏳ ОЖИДАЕТ'}
🎯 Смещение: +{OFFSET} игр
📈 Догон: {DOGON_GAMES - 1} игр
⚡ Порог уверенности ML: {int(ML_CONFIDENCE_THRESHOLD * 100)}%
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
# ФУНКЦИИ ДЛЯ РАБОТЫ С ДАННЫМИ
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

    if len(data) >= MAX_RECORDS and collection_active:
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
# ФУНКЦИИ API
# =====================================================================
def get_active_games():
    try:
        url = (
            f"{BASE_URL}/service-api/main-live-feed/"
            "v3/games1x2?"
            "cfView=3&count=40&fcountry=190&gr=415&"
            "grMode=4&lng=ru&ref=7&selectedMs="
            "1.146.1643503,10.146.1643503"
        )

        response = requests.get(
            url,
            headers=HEADERS,
            timeout=10
        )

        if response.status_code == 200:
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
                    game.get(
                        "liga",
                        {}
                    ).get("id") == 1643503
                ):
                    game_id = game.get("id")

                    if game_id:
                        active_games.append(game)

            return active_games

        else:
            return []

    except Exception as e:
        print(
            f"❌ Ошибка API: {e}",
            flush=True
        )
        return []


def get_game_data(game_id):
    url = (
        f"{BASE_URL}/service-api/LiveFeed/"
        f"GetGameZip?id={game_id}&"
        "isSubGames=true&"
        "GroupEvents=true&"
        "countevents=250&"
        "grMode=4&"
        "partner=7&"
        "topGroups=&"
        "country=190&"
        "marketType=1&"
        "isNewBuilder=true"
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

        else:
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


def get_game_number_by_time():
    now = datetime.now(MOSCOW_TZ)

    start = now.replace(
        hour=3,
        minute=0,
        second=0,
        microsecond=0
    )

    if now < start:
        start = start - timedelta(days=1)

    diff_minutes = (
        now - start
    ).total_seconds() / 60

    game_number = (
        int(diff_minutes) % 1440
    ) + 1

    return game_number


def parse_game_from_text(text):
    try:
        game_match = re.search(
            r'#N(\d+)',
            text
        )

        if not game_match:
            return None

        game_number = int(
            game_match.group(1)
        )

        parts = None

        if '◀️' in text:
            parts = text.split('◀️')

        elif '▶️' in text:
            parts = text.split('▶️')

        elif '-' in text:
            parts = text.split('-')

        elif '—' in text:
            parts = text.split('—')

        else:
            return None

        if not parts or len(parts) < 2:
            return None

        player_part = parts[0].strip()
        dealer_part = parts[1].strip()

        def parse_cards_from_part(part):
            cards_match = re.search(
                r'\(([^)]+)\)',
                part
            )

            if not cards_match:
                return []

            cards_str = cards_match.group(1).strip()

            cards = []
            i = 0

            while i < len(cards_str):

                if cards_str[i] == ' ':
                    i += 1
                    continue

                rank = ''

                if (
                    i + 1 < len(cards_str)
                    and cards_str[i:i+2] == '10'
                ):
                    rank = '10'
                    i += 2

                elif cards_str[i] in 'AKQJ':
                    rank = cards_str[i]
                    i += 1

                elif cards_str[i].isdigit():
                    rank = cards_str[i]
                    i += 1

                else:
                    i += 1
                    continue

                suit = ''

                if i < len(cards_str):

                    if cards_str[i:i+2] == '♠️':
                        suit = '♠️'
                        i += 2

                    elif cards_str[i:i+2] == '♣️':
                        suit = '♣️'
                        i += 2

                    elif cards_str[i:i+2] == '♦️':
                        suit = '♦️'
                        i += 2

                    elif cards_str[i:i+2] == '♥️':
                        suit = '♥️'
                        i += 2

                    elif cards_str[i] in '♠♣♦♥':
                        suit = (
                            cards_str[i]
                            .replace('♠', '♠️')
                            .replace('♣', '♣️')
                            .replace('♦', '♦️')
                            .replace('♥', '♥️')
                        )
                        i += 1

                    else:
                        i += 1
                        continue

                if rank and suit:
                    cards.append({
                        "rank": rank,
                        "suit": suit
                    })

            return cards

        player_cards = parse_cards_from_part(
            player_part
        )

        dealer_cards = parse_cards_from_part(
            dealer_part
        )

        return {
            "number": game_number,
            "player_cards": player_cards,
            "dealer_cards": dealer_cards,
            "text": text
        }

    except Exception as e:
        print(
            f"❌ Ошибка парсинга: {e}",
            flush=True
        )
        return None


def is_finished_game_text(text):
    return '✅' in text or '🔰' in text

# =====================================================================
# ИСТОРИЯ ИГР
# =====================================================================
def update_game_history(latency, cards, game_num):
    global game_history

    all_cards = []

    for card in cards:
        rank = card.get("rank", "")
        suit = card.get("suit", "")

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
        "latency": latency,
        "cards": all_cards,
        "game_num": game_num,
        "timestamp": datetime.now(
            MOSCOW_TZ
        ).isoformat()
    })

    save_game_history()


def get_history_features():
    features = {}

    if len(game_history) >= 2:

        latencies = [
            g["latency"]
            for g in game_history
        ]

        features["prev_latency"] = (
            latencies[-2]
        )

        features["latency_delta"] = (
            latencies[-1]
            - latencies[-2]
        )

        if len(latencies) >= 5:
            recent = latencies[-5:]

            features["latency_trend"] = (
                recent[-1]
                - recent[0]
            ) / 5

    if len(game_history) >= 2:

        all_cards = []

        for g in game_history:
            all_cards.extend(
                g.get("cards", [])
            )

        if all_cards:

            last_card = (
                all_cards[-1]
                if all_cards
                else ""
            )

            if last_card in TARGET_CARDS:
                features["prev_card"] = (
                    TARGET_CARDS.index(
                        last_card
                    )
                )

    now = datetime.now(MOSCOW_TZ)

    features["hour"] = now.hour
    features["minute"] = now.minute
    features["day_of_week"] = now.weekday()
    features["is_weekend"] = (
        1
        if now.weekday() >= 5
        else 0
    )

    return features

# =====================================================================
# ML-ФУНКЦИИ
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
        "latency": latency,
        "game_num": game_num % 100,

        "p1_rank_val": 0,
        "p1_suit": -1,

        "p2_rank_val": 0,
        "p2_suit": -1,

        "p3_rank_val": 0,
        "p3_suit": -1,

        "d1_rank_val": 0,
        "d1_suit": -1,

        "d2_rank_val": 0,
        "d2_suit": -1,

        "player_total": 0,
        "dealer_total": 0,

        "player_count": len(player_cards),
        "dealer_count": len(dealer_cards),

        "prev_latency": 0,
        "latency_delta": 0,
        "latency_trend": 0,
        "prev_card": -1,

        "hour": 0,
        "minute": 0,
        "day_of_week": 0,
        "is_weekend": 0,
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
                f"p{i+1}_rank_val"
            ] = RANK_VALUES[rank]

        if suit in SUITS:
            features[
                f"p{i+1}_suit"
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
                f"d{i+1}_rank_val"
            ] = RANK_VALUES[rank]

        if suit in SUITS:
            features[
                f"d{i+1}_suit"
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

    features["player_total"] = player_total

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

    features["dealer_total"] = dealer_total

    history_features = get_history_features()

    for key, value in history_features.items():

        if key in features:
            features[key] = value

    return features

# =====================================================================
# ОБУЧЕНИЕ ML
# =====================================================================
def train_ml_model():
    global ml_model, ml_initialized

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
            game.get("latency_ms", 0),
            0
        )

        if not features:
            continue

        feature_vector = []

        sorted_keys = sorted(
            features.keys()
        )

        if not feature_names:
            feature_names = sorted_keys

        for key in sorted_keys:
            feature_vector.append(
                features[key]
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

            card_str = rank + suit

            if card_str in TARGET_CARDS:

                X.append(
                    feature_vector
                )

                y.append(
                    TARGET_CARDS.index(
                        card_str
                    )
                )

                break

    if len(X) < MIN_TRAIN_SAMPLES:

        print(
            f"⚠️ ML: недостаточно примеров "
            f"({len(X)}/{MIN_TRAIN_SAMPLES})",
            flush=True
        )

        return False

    print(
        f"🧠 ML: обучение на {len(X)} "
        f"примерах из {len(data)} игр...",
        flush=True
    )

    print(
        f"📊 Признаков: {len(feature_names)}",
        flush=True
    )

    X = np.array(X)
    y = np.array(y)

    if ML_LIB == "randomforest":

        model = RandomForestClassifier(
            n_estimators=200,
            max_depth=10,
            random_state=42,
            n_jobs=1
        )

    else:
        return False

    model.fit(
        X,
        y
    )

    ml_model = model
    ml_initialized = True

    try:

        with open(
            ML_MODEL_FILE,
            'wb'
        ) as f:

            pickle.dump(
                {
                    'model': model,
                    'feature_count': len(X[0]),
                    'train_samples': len(X),
                    'total_games': len(data),
                    'feature_names': feature_names
                },
                f
            )

        print(
            f"✅ Модель сохранена! "
            f"Обучено на {len(X)} примерах "
            f"из {len(data)} игр",
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
    global ml_model, ml_initialized

    if not ML_AVAILABLE:
        return False

    if not os.path.exists(
        ML_MODEL_FILE
    ):
        return False

    try:

        with open(
            ML_MODEL_FILE,
            'rb'
        ) as f:

            data = pickle.load(f)

            ml_model = data['model']
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
    global ml_model, ml_initialized

    if not ml_initialized or not ml_model:
        return None, None

    try:

        feature_vector = []

        for key in sorted(
            features.keys()
        ):
            feature_vector.append(
                features[key]
            )

        feature_vector = np.array(
            [feature_vector]
        )

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
    global game_history

    if not ml_initialized:

        print(
            "⏳ ML модель не инициализирована",
            flush=True
        )

        return None, None, None

    if not current_game_data:

        print(
            "⏳ Нет данных о текущей игре",
            flush=True
        )

        return None, None, None

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

        return None, None, None

    ml_cards, confidence = predict_ml(
        features
    )

    if ml_cards and confidence:

        print(
            "📊 ML: топ-2 карт:",
            flush=True
        )

        for i, (card, prob) in enumerate(
            ml_cards,
            1
        ):

            print(
                f"   {i}. {card} — "
                f"{prob*100:.1f}%",
                flush=True
            )

        print(
            f"   Максимальная уверенность: "
            f"{confidence*100:.1f}%",
            flush=True
        )

        print(
            f"   Порог: "
            f"{ML_CONFIDENCE_THRESHOLD*46:.0f}%",
            flush=True
        )

        if confidence >= ML_CONFIDENCE_THRESHOLD:

            print(
                f"✅ Уверенность "
                f"{confidence*100:.1f}% >= "
                f"{ML_CONFIDENCE_THRESHOLD*100:.0f}% "
                f"→ ДАЮ ПРОГНОЗ!",
                flush=True
            )

            return (
                ml_cards,
                "ml",
                confidence
            )

        else:

            print(
                f"⏭️ Уверенность "
                f"{confidence*100:.1f}% < "
                f"{ML_CONFIDENCE_THRESHOLD*100:.0f}% "
                f"→ ПРОПУСКАЮ",
                flush=True
            )

            return None, None, None

    else:

        print(
            "⏭️ ML не выдал карты",
            flush=True
        )

        return None, None, None

# =====================================================================
# ПРОВЕРКА РЕЗУЛЬТАТОВ
# =====================================================================
def check_results():
    global predictions, stats, all_messages, ml_model

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

        method = entry.get(
            "method",
            "ml"
        )

        original_text = entry.get(
            "original_text",
            ""
        )

        if not predicted_cards or not message_id:
            continue

        max_games_to_check = DOGON_GAMES

        for i in range(
            max_games_to_check
        ):

            game_to_check = target + i

            game_msg = None

            for msg in all_messages:

                if isinstance(msg, tuple):
                    text = msg[0]
                else:
                    text = msg

                if (
                    f"#N{game_to_check}" in text
                    and (
                        '✅' in text
                        or '🔰' in text
                    )
                ):
                    game_msg = text
                    break

            if not game_msg:
                continue

            game_data = parse_game_from_text(
                game_msg
            )

            if not game_data:
                continue

            found = False
            found_card = None

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

                if rank == "?" or suit == "?":
                    continue

                card_str = rank + suit

                actual_cards.append(
                    card_str
                )

                if card_str in predicted_cards:

                    found = True
                    found_card = card_str
                    break

            if found:

                print(
                    f"🎯 КАРТА НАЙДЕНА! "
                    f"{found_card} в игре "
                    f"#{game_to_check} "
                    f"(догон {i})",
                    flush=True
                )

                stats["total"] += 1
                stats["win"] += 1

                stats["by_dogon"][i] = (
                    stats["by_dogon"].get(i, 0)
                    + 1
                )

                stats["ml_wins"] += 1

                stats["card_hits"][
                    found_card
                ] += 1

                if i == 0:

                    result_text = (
                        f"\n\n✅ ЗАШЛО "
                        f"в целевой игре: "
                        f"#{game_to_check}\n"
                        f"   Выпала: {found_card}"
                    )

                else:

                    result_text = (
                        f"\n\n✅ ЗАШЛО "
                        f"на догоне {i}: "
                        f"#{game_to_check}\n"
                        f"   Выпала: {found_card}"
                    )

                edit_message(
                    message_id,
                    original_text + result_text
                )

                entry["status"] = "win"
                entry["result_game"] = game_to_check
                entry["dogon"] = i
                entry["found_card"] = found_card

                save_history(
                    predictions
                )

                return

            if (
                i == max_games_to_check - 1
                and not found
            ):

                print(
                    f"❌ Карты "
                    f"{', '.join(predicted_cards)} "
                    f"НЕ НАЙДЕНЫ за "
                    f"{max_games_to_check} игр",
                    flush=True
                )

                actual_target = None

                for card_str in actual_cards:

                    if card_str in TARGET_CARDS:
                        actual_target = card_str
                        break

                if actual_target:

                    print(
                        f"📘 ОШИБКА: ждали "
                        f"{predicted_cards}, "
                        f"выпала {actual_target}",
                        flush=True
                    )

                    stats["total"] += 1
                    stats["lose"] += 1
                    stats["ml_losses"] += 1

                    try:

                        features = extract_features_from_game(
                            game_data,
                            game_data.get(
                                "latency_ms",
                                0
                            ),
                            target
                        )

                        if features and ml_initialized:

                            feature_vector = []

                            for key in sorted(
                                features.keys()
                            ):
                                feature_vector.append(
                                    features[key]
                                )

                            X_new = np.array(
                                [feature_vector]
                            )

                            y_new = TARGET_CARDS.index(
                                actual_target
                            )

                            if hasattr(
                                ml_model,
                                'partial_fit'
                            ):

                                ml_model.partial_fit(
                                    X_new,
                                    [y_new]
                                )

                                print(
                                    f"✅ Мгновенное обучение: "
                                    f"запомнил "
                                    f"{actual_target}",
                                    flush=True
                                )

                            else:

                                error_file = (
                                    "learning_errors.json"
                                )

                                errors = []

                                if os.path.exists(
                                    error_file
                                ):

                                    with open(
                                        error_file,
                                        'r'
                                    ) as f:
                                        errors = json.load(f)

                                errors.append({
                                    "timestamp": datetime.now(
                                        MOSCOW_TZ
                                    ).isoformat(),
                                    "features": features,
                                    "correct_card": actual_target,
                                    "predicted_cards": predicted_cards,
                                    "game_num": target
                                })

                                with open(
                                    error_file,
                                    'w'
                                ) as f:

                                    json.dump(
                                        errors,
                                        f,
                                        indent=2
                                    )

                                print(
                                    f"📝 Ошибка сохранена "
                                    f"в {error_file}",
                                    flush=True
                                )

                    except Exception as e:

                        print(
                            f"⚠️ Ошибка при "
                            f"дообучении: {e}",
                            flush=True
                        )

                    result_text = (
                        f"\n\n❌ НЕ ЗАШЛО "
                        f"(проверено "
                        f"{max_games_to_check} игр)"
                        f"\n   Выпала: "
                        f"{actual_target} "
                        f"(ошибка проанализирована)"
                    )

                    edit_message(
                        message_id,
                        original_text + result_text
                    )

                    entry["status"] = "lose"
                    entry["actual_card"] = actual_target

                    save_history(
                        predictions
                    )

                    return

                else:

                    stats["total"] += 1
                    stats["lose"] += 1
                    stats["ml_losses"] += 1

                    result_text = (
                        f"\n\n❌ НЕ ЗАШЛО "
                        f"(целевых карт не было)"
                    )

                    edit_message(
                        message_id,
                        original_text + result_text
                    )

                    entry["status"] = "lose"

                    save_history(
                        predictions
                    )

                    return

# =====================================================================
# ПЛАНИРОВЩИК
# =====================================================================
def schedule_for_game(game_number):
    global predictions

    target = game_number + OFFSET

    for entry in predictions:

        if (
            entry.get("target") == target
            and entry.get("status")
            in ("scheduled", "pending")
        ):
            return

    source = target - 1

    predictions.append({
        "source": source,
        "target": target,
        "offset": OFFSET,
        "status": "scheduled",
        "created": datetime.now(
            MOSCOW_TZ
        ).isoformat(),
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
# ПРОГНОЗ ИЗ API
# =====================================================================
def check_and_predict():
    global predictions, all_messages, game_history

    for entry in predictions:

        if entry.get("status") != "scheduled":
            continue

        target = entry.get("target")

        current_num = get_game_number_by_time()

        games_left = target - current_num

        if games_left != 2 and games_left != 1:
            continue

        print(
            f"🔥 До цели #{target} "
            f"осталось {games_left} игр! "
            f"Делаю прогноз...",
            flush=True
        )

        latency = None
        current_game_data = None

        # ============================================================
        # ДАННЫЕ ТЕКУЩЕЙ ИГРЫ БЕРЁМ ИЗ API
        # ============================================================
        active_games = get_active_games()

        for game in active_games:

            game_id = str(
                game.get("id")
            )

            data, measured_latency, _, _ = get_game_data(
                game_id
            )

            if not data:
                continue

            (
                player_cards_raw,
                dealer_cards_raw,
                state
            ) = parse_cards_and_state(
                data
            )

            if (
                not player_cards_raw
                and not dealer_cards_raw
            ):
                continue

            player_cards = []
            dealer_cards = []

            for card in player_cards_raw:

                player_cards.append({
                    "rank": RANKS.get(
                        card.get("CV", 0),
                        "?"
                    ),
                    "suit": SUITS_NAMES.get(
                        card.get("CS", 0),
                        "?"
                    )
                })

            for card in dealer_cards_raw:

                dealer_cards.append({
                    "rank": RANKS.get(
                        card.get("CV", 0),
                        "?"
                    ),
                    "suit": SUITS_NAMES.get(
                        card.get("CS", 0),
                        "?"
                    )
                })

            current_game_data = {
                "number": current_num,
                "player_cards": player_cards,
                "dealer_cards": dealer_cards
            }

            latency = measured_latency

            break

        if latency is None:

            print(
                "⏳ Не удалось получить задержку",
                flush=True
            )

            continue

        if not current_game_data:

            print(
                f"⏳ Нет данных API "
                f"о текущей игре #{current_num}",
                flush=True
            )

            continue

        # Получаем прогноз
        predicted_cards, method, confidence = get_prediction(
            latency,
            current_game_data
        )

        if (
            not predicted_cards
            or len(predicted_cards) < 2
        ):

            print(
                f"⏭️ Нет прогноза от ML "
                f"для #{target}",
                flush=True
            )

            continue

        # ============================================================
        # ПРОВЕРКА:
        #
        # ИГРОК:
        #   1-я карта → БЛОК
        #   2-я карта → БЛОК
        #   3-я карта → НЕ БЛОК
        #   4-я и далее → НЕ БЛОК
        #
        # ДИЛЕР:
        #   1-я карта → БЛОК
        #   2-я карта → БЛОК
        #   3-я карта → НЕ БЛОК
        #   4-я и далее → НЕ БЛОК
        #
        # ============================================================

        predicted_card_names = [
            card
            for card, prob in predicted_cards
        ]

        player_cards = current_game_data.get(
            "player_cards",
            []
        )

        dealer_cards = current_game_data.get(
            "dealer_cards",
            []
        )

        blocked = False
        blocked_card = None
        blocked_position = None

        # ------------------------------------------------------------
        # ИГРОК — ТОЛЬКО ПЕРВЫЕ 2 КАРТЫ
        # ------------------------------------------------------------
        for i, card in enumerate(
            player_cards[:2]
        ):

            card_str = (
                card.get("rank", "")
                +
                card.get("suit", "")
            )

            if card_str in predicted_card_names:

                blocked = True
                blocked_card = card_str
                blocked_position = f"P{i + 1}"

                break

        # ------------------------------------------------------------
        # ДИЛЕР — ТОЛЬКО ПЕРВЫЕ 2 КАРТЫ
        # ------------------------------------------------------------
        if not blocked:

            for i, card in enumerate(
                dealer_cards[:2]
            ):

                card_str = (
                    card.get("rank", "")
                    +
                    card.get("suit", "")
                )

                if card_str in predicted_card_names:

                    blocked = True
                    blocked_card = card_str
                    blocked_position = f"D{i + 1}"

                    break

        # ------------------------------------------------------------
        # ЕСЛИ КАРТА НА ПЕРВЫХ ДВУХ
        # КАРТАХ УЧАСТНИКА — БЛОКИРУЕМ
        # ------------------------------------------------------------
        if blocked:

            print(
                f"⏭️ ПРОГНОЗ ЗАБЛОКИРОВАН: "
                f"{blocked_card} уже есть "
                f"на позиции {blocked_position} "
                f"→ #{target}",
                flush=True
            )

            continue

        # ============================================================
        # ЕСЛИ ПРОВЕРКА ПРОЙДЕНА → ОТПРАВЛЯЕМ ПРОГНОЗ
        # ============================================================
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

        total_prob = 0

        msg = (
            "🔮 ТОЧНАЯ КАРТА "
            "(ML ТОП-2)\n\n"
        )

        msg += (
            f"🎯 Целевая игра: "
            f"#N{target} (+{OFFSET})\n"
        )

        msg += (
            f"🤖 Метод: ML "
            f"(увер. {confidence*100:.1f}%)\n"
        )

        msg += (
            f"⏰ Прогноз: "
            f"{datetime.now(MOSCOW_TZ).strftime('%H:%M:%S')}\n\n"
        )

        msg += (
            "📊 Топ-2 карты:\n"
        )

        cards_list = []

        for i, (card, prob) in enumerate(
            predicted_cards,
            1
        ):

            cards_list.append(
                card
            )

            msg += (
                f"  {i}️⃣ {card} — "
                f"{prob*100:.1f}%\n"
            )

            total_prob += prob

        msg += (
            f"\n📊 Суммарная вероятность: "
            f"{total_prob*100:.1f}%\n"
        )

        msg += (
            f"📈 Догон: "
            f"{DOGON_GAMES - 1} игр\n"
        )

        msg += (
            "📍 Ищем: любую позицию "
            "(игрок/дилер)"
        )

        p1 = (
            current_game_data.get(
                "player_cards",
                []
            )[0]
            if current_game_data.get(
                "player_cards"
            )
            else None
        )

        p2 = (
            current_game_data.get(
                "dealer_cards",
                []
            )[0]
            if current_game_data.get(
                "dealer_cards"
            )
            else None
        )

        p3 = (
            current_game_data.get(
                "player_cards",
                []
            )[1]
            if len(
                current_game_data.get(
                    "player_cards",
                    []
                )
            ) > 1
            else None
        )

        seq_str = ""

        if p1:
            seq_str += (
                f"P1:{p1['rank']}"
                f"{p1['suit']} "
            )

        if p2:
            seq_str += (
                f"D2:{p2['rank']}"
                f"{p2['suit']} "
            )

        if p3:
            seq_str += (
                f"P3:{p3['rank']}"
                f"{p3['suit']}"
            )

        if seq_str:
            msg += (
                f"\n📌 {seq_str}"
            )

        message_id = send_message(
            CHANNEL_PROGNOZ,
            msg
        )

        if message_id:

            entry["cards"] = cards_list
            entry["method"] = method
            entry["message_id"] = message_id
            entry["original_text"] = msg
            entry["status"] = "pending"
            entry["latency"] = latency
            entry["confidence"] = confidence

            save_history(
                predictions
            )

            print(
                f"✅ ПРОГНОЗ ОТПРАВЛЕН: "
                f"#{target} → "
                f"{', '.join(cards_list)} "
                f"(ML, уверенность "
                f"{confidence*100:.1f}%)",
                flush=True
            )

# =====================================================================
# СБОР ДАННЫХ ИЗ API
# =====================================================================
def collect_game_data():
    global collection_active, finished_games

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
        ) = get_game_data(
            game_id
        )

        if (
            not game_data
            or not isinstance(
                game_data,
                dict
            )
        ):
            continue

        (
            player_cards,
            dealer_cards,
            state
        ) = parse_cards_and_state(
            game_data
        )

        if player_cards or dealer_cards:

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
                    '%H:%M:%S.%f'
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

                    rank = RANKS.get(
                        pc.get("CV", 0),
                        "?"
                    )

                    suit = SUITS_NAMES.get(
                        pc.get("CS", 0),
                        "?"
                    )

                    sequence.append({
                        "position": i * 2 + 1,
                        "who": "P",
                        "rank": rank,
                        "suit": suit
                    })

                if i < len(dealer_cards):

                    dc = dealer_cards[i]

                    rank = RANKS.get(
                        dc.get("CV", 0),
                        "?"
                    )

                    suit = SUITS_NAMES.get(
                        dc.get("CS", 0),
                        "?"
                    )

                    sequence.append({
                        "position": i * 2 + 2,
                        "who": "D",
                        "rank": rank,
                        "suit": suit
                    })

            record = {
                "game_id": game_id,
                "timestamp_msk": timestamp_msk_str,
                "latency_ms": (
                    round(latency, 2)
                    if latency
                    else 0
                ),
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
            }

            data = save_data(
                record
            )

            # ========================================================
            # ЗАВЕРШЁННАЯ ИГРА API
            # → ЗАПУСКАЕМ ПЛАНИРОВАНИЕ ПРОГНОЗА
            # ========================================================
            if state in ["4", "5"]:

                finished_games.add(
                    game_id
                )

                print(
                    f"🏁 Игра {game_id} "
                    f"завершена (state={state}), "
                    f"сохранена",
                    flush=True
                )

                game_number = (
                    get_game_number_by_time()
                )

                print(
                    f"📥 API: получена "
                    f"игра #{game_number}",
                    flush=True
                )

                schedule_for_game(
                    game_number
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

    if stats['total'] > 0:
        win_percent = (
            stats['win']
            /
            stats['total']
            *
            100
        )

    data_count = len(
        load_data()
    )

    msg = f"""
📊 СТАТИСТИКА (ТОЧНАЯ КАРТА — ML ТОП-2)
⏰ {now.strftime('%d.%m.%Y %H:%M:%S')}
══════════════════════════════════════════
📊 Собрано игр: {data_count}/{MAX_RECORDS}
📈 Всего прогнозов: {stats['total']}
✅ Зашло: {stats['win']} ({win_percent:.1f}%)
❌ Не зашло: {stats['lose']}

🤖 ML: {stats['ml_wins']}✅ / {stats['ml_losses']}❌

По догонам ({DOGON_GAMES - 1} игр):
  Догон 0: {stats['by_dogon'].get(0, 0)}
  Догон 1: {stats['by_dogon'].get(1, 0)}
  Догон 2: {stats['by_dogon'].get(2, 0)}
  Догон 3: {stats['by_dogon'].get(3, 0)}"""

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
                f"  {card}: {count}\n"
            )

    else:
        msg += (
            "  (пока нет данных)\n"
        )

    if ml_initialized:
        msg += "\n🤖 ML: АКТИВНА"

    else:
        msg += (
            f"\n🤖 ML: ОЖИДАЕТ "
            f"({data_count}/{MIN_TRAIN_SAMPLES})"
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
    global stats
    global game_history
    global collection_active

    print(
        "🔄 ТОЧНАЯ КАРТА "
        "(ML ТОП-2) ЗАПУЩЕН",
        flush=True
    )

    print(
        f"📁 Данные в {DATA_FILE}",
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

    print(
        "=" * 60,
        flush=True
    )

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

    load_ml_model()
    train_ml_model()

    stats["games_collected"] = (
        len(existing_data)
    )

    send_startup_message()

    try:

        url = (
            f"https://api.telegram.org/"
            f"bot{BOT_TOKEN}/getUpdates"
        )

        params = {
            "chat_id": CHANNEL_STATS,
            "limit": 100
        }

        response = requests.get(
            url,
            params=params,
            timeout=10
        )

        if response.status_code == 200:

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
                    and post.get("text")
                ):

                    all_messages.append(
                        (
                            post.get("text"),
                            time.time()
                        )
                    )

    except:
        pass

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

    print(
        "=" * 60,
        flush=True
    )

    while True:

        try:

            current_time = time.time()

            # ========================================================
            # ОСНОВНОЙ ИСТОЧНИК ИГР — API
            # ========================================================
            collect_game_data()

            # ========================================================
            # TELEGRAM — ТОЛЬКО ПРОВЕРКА РЕЗУЛЬТАТОВ
            # ========================================================
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

                chat_id = post.get(
                    "chat",
                    {}
                ).get(
                    "id"
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
                    or "#N" not in text
                ):
                    continue

                all_messages.append(
                    (
                        text,
                        time.time()
                    )
                )

                if len(all_messages) > 500:
                    all_messages = (
                        all_messages[-500:]
                    )

                # Telegram больше НЕ запускает
                # schedule_for_game()
                # Канал используется только
                # для check_results()

                check_results()

            if (
                current_time
                - last_check_time
                >= CHECK_INTERVAL
            ):

                check_and_predict()

                last_check_time = (
                    current_time
                )

            check_results()

            # ========================================================
            # ПЕРЕОБУЧЕНИЕ КАЖДЫЕ 3 МИНУТЫ
            # ========================================================
            if (
                current_time
                - last_train_time
                > 180
            ):

                data_count = len(
                    load_data()
                )

                if data_count >= MIN_TRAIN_SAMPLES:

                    print(
                        f"🔄 ЗАПУСК ПЕРЕОБУЧЕНИЯ "
                        f"(всего игр: "
                        f"{data_count})...",
                        flush=True
                    )

                    train_ml_model()

                    last_train_time = (
                        current_time
                    )

                    gc.collect()

            if (
                current_time
                - last_stats_time
                > 3600
            ):

                send_stats_report()

                last_stats_time = (
                    current_time
                )

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
                "🛑 Бот остановлен",
                flush=True
            )

            data_count = len(
                load_data()
            )

            print(
                f"📊 Всего собрано записей: "
                f"{data_count}",
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

            time.sleep(30)


if __name__ == "__main__":
    main()
```
