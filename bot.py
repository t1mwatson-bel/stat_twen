import os
import sys
import json
import time
import requests
import pytz
import re

from datetime import datetime, timedelta
from collections import defaultdict, Counter


# =====================================================================
# ENV
# =====================================================================

BOT_TOKEN = os.getenv("BOT_TOKEN")
if not BOT_TOKEN:
    BOT_TOKEN = os.getenv("BOT_TOKEN_PROGNOZ")

CHANNEL_PROGNOZ = os.getenv("CHAT_ID_21")
if not CHANNEL_PROGNOZ:
    CHANNEL_PROGNOZ = os.getenv("CHANNEL_PROGNOZ")

CHANNEL_STATS = os.getenv("CHANNEL_STATS")

if not BOT_TOKEN or not CHANNEL_PROGNOZ or not CHANNEL_STATS:
    print(
        "❌ Ошибка: не заданы BOT_TOKEN, CHANNEL_PROGNOZ или CHANNEL_STATS!",
        flush=True
    )
    sys.exit(1)

CHANNEL_PROGNOZ = str(CHANNEL_PROGNOZ).strip()
CHANNEL_STATS = str(CHANNEL_STATS).strip()


# =====================================================================
# CONFIG
# =====================================================================

MOSCOW_TZ = pytz.timezone("Europe/Moscow")

BASE_URL = "https://1xlite-36553.pro"
LEAGUE_ID = 1643503

DATA_FILE = "twentyone_data_full.json"
PREDICTIONS_FILE = "twentyone_predictions.json"
OFFSET_FILE = "hybrid_offset.txt"

MAX_HISTORY_GAMES = 3000
DOGON_GAMES = 4
POLL_INTERVAL = 2.0

TARGET_RANKS = {"J", "Q", "K", "A"}

TARGET_CARDS = [
    "J♠️", "J♣️", "J♦️", "J♥️",
    "Q♠️", "Q♣️", "Q♦️", "Q♥️",
    "K♠️", "K♣️", "K♦️", "K♥️",
    "A♠️", "A♣️", "A♦️", "A♥️"
]


# =====================================================================
# HYBRID WEIGHTS
# =====================================================================

WEIGHT_MS = 1.00
WEIGHT_ID1 = 0.80
WEIGHT_ID2 = 1.20
WEIGHT_SEQUENCE = 1.10
WEIGHT_FREQUENCY = 0.50

MIN_MS_MATCHES = 2
MIN_ID1_MATCHES = 3
MIN_ID2_MATCHES = 2
MIN_SEQUENCE_MATCHES = 2

MIN_FORECAST_PROBABILITY = 0.10
MIN_LEADER_GAP = 0.01
MIN_ACTIVE_METHODS = 1

PREDICTION_COOLDOWN_SECONDS = 2


# =====================================================================
# TELEGRAM
# =====================================================================

TELEGRAM_API = f"https://api.telegram.org/bot{BOT_TOKEN}"


# =====================================================================
# HEADERS / SESSION
# =====================================================================

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36"
    ),
    "Accept": "application/json, text/plain, */*",
    "Referer": f"{BASE_URL}/ru/live/twentyone/1643503-twentyone-game",
    "Cookie": (
        "platform_type=desktop; lng=ru; cookies_agree_type=3; "
        "tzo=3; is12h=0"
    )
}

SESSION = requests.Session()
SESSION.headers.update(HEADERS)


# =====================================================================
# CARD MAPS
# =====================================================================

SUITS_NAMES = {
    0: "♠️",
    1: "♣️",
    2: "♦️",
    3: "♥️"
}

RANKS = {
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
    13: "K",
    14: "A"
}


# =====================================================================
# GLOBALS
# =====================================================================

history = []
predictions = []
games_cache = {}
last_prediction_time = 0
processed_numbers = set()


# =====================================================================
# NORMALIZATION
# =====================================================================

def normalize_suit(v):
    if v is None or isinstance(v, bool):
        return None

    if isinstance(v, int):
        s = SUITS_NAMES.get(v)
        if s:
            return s.replace("\ufe0f", "")

    t = str(v).strip().replace("\ufe0f", "")

    mapping = {
        "0": "♠",
        "♠": "♠",
        "spade": "♠",
        "spades": "♠",
        "s": "♠",

        "1": "♣",
        "♣": "♣",
        "club": "♣",
        "clubs": "♣",
        "c": "♣",

        "2": "♦",
        "♦": "♦",
        "diamond": "♦",
        "diamonds": "♦",
        "d": "♦",

        "3": "♥",
        "♥": "♥",
        "heart": "♥",
        "hearts": "♥",
        "h": "♥"
    }

    return mapping.get(t)


def normalize_rank(v):
    if v is None or isinstance(v, bool):
        return None

    if isinstance(v, int):
        return RANKS.get(v)

    t = str(v).strip().upper().replace("А", "A")

    if t in {
        "2", "3", "4", "5", "6",
        "7", "8", "9", "10",
        "J", "Q", "K", "A"
    }:
        return t

    try:
        return RANKS.get(int(t))
    except Exception:
        return None


def card_to_text(card):
    if not card:
        return ""

    rank = normalize_rank(card.get("rank"))
    suit = normalize_suit(card.get("suit"))

    if not rank or not suit:
        return ""

    return f"{rank}{suit}\ufe0f"


def card_dict_to_target(card):
    text = card_to_text(card)
    return text if text in TARGET_CARDS else None


# =====================================================================
# JSON
# =====================================================================

def load_json_file(filename, default):
    try:
        if not os.path.exists(filename):
            return default

        with open(filename, "r", encoding="utf-8") as f:
            return json.load(f)

    except Exception as e:
        print(f"⚠️ Ошибка чтения {filename}: {e}", flush=True)
        return default


def atomic_save_json(filename, data):
    tmp = filename + ".tmp"

    try:
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(
                data,
                f,
                ensure_ascii=False,
                indent=2
            )

        os.replace(tmp, filename)
        return True

    except Exception as e:
        print(f"⚠️ Ошибка сохранения {filename}: {e}", flush=True)

        try:
            if os.path.exists(tmp):
                os.remove(tmp)
        except Exception:
            pass

        return False


# =====================================================================
# HISTORY
# =====================================================================

def load_history():
    data = load_json_file(DATA_FILE, [])

    if not isinstance(data, list):
        data = []

    clean = []

    for g in data:
        if isinstance(g, dict):
            clean.append(g)

    if len(clean) > MAX_HISTORY_GAMES:
        clean = clean[-MAX_HISTORY_GAMES:]
        atomic_save_json(DATA_FILE, clean)

    return clean


def load_predictions():
    data = load_json_file(PREDICTIONS_FILE, [])
    return data if isinstance(data, list) else []


def find_game_index(gid):
    gid = str(gid)

    for i, game in enumerate(history):
        if str(game.get("game_id")) == gid:
            return i

    return -1


def game_exists(gid):
    return find_game_index(gid) != -1


# =====================================================================
# ADD GAME TO HISTORY
# =====================================================================

def add_game_to_history(game_data):
    global history

    MAX_GAMES = 2880

    game_id = str(game_data.get("game_id", ""))

    # Обновляем игру только если есть настоящий game_id
    if game_id and game_id != "None":

        for i, game in enumerate(history):
            if str(game.get("game_id", "")) == game_id:
                history[i] = game_data

                atomic_save_json(DATA_FILE, history)

                print(
                    f"🔄 Обновлена игра | ID={game_id}",
                    flush=True
                )

                return

    history.append(game_data)

    if len(history) > MAX_GAMES:
        removed = len(history) - MAX_GAMES
        history = history[removed:]

        print(
            f"🧹 Удалено {removed} старых игр "
            f"(осталось {MAX_GAMES})",
            flush=True
        )

    atomic_save_json(DATA_FILE, history)

    print(
        f"💾 Добавлена игра | "
        f"Всего: {len(history)} | "
        f"ID={game_id}",
        flush=True
    )


# =====================================================================
# DEEP PARSING
# =====================================================================

def deep_find_value(obj, keys):
    wanted = {str(x).lower() for x in keys}

    if isinstance(obj, dict):

        for k, v in obj.items():
            if str(k).lower() in wanted:
                return v

        for v in obj.values():
            result = deep_find_value(v, keys)

            if result is not None:
                return result

    elif isinstance(obj, list):

        for item in obj:
            result = deep_find_value(item, keys)

            if result is not None:
                return result

    return None


def extract_card_from_dict(obj):
    if not isinstance(obj, dict):
        return None

    rank = None
    suit = None

    rank_keys = {
        "rank",
        "value",
        "v",
        "cardvalue",
        "card_value",
        "nominal",
        "denomination"
    }

    suit_keys = {
        "suit",
        "s",
        "card_suit",
        "cardsuit",
        "mast",
        "color"
    }

    for k, v in obj.items():

        kl = str(k).strip().lower()

        if kl in rank_keys:
            r = normalize_rank(v)

            if r:
                rank = r

        if kl in suit_keys:
            s = normalize_suit(v)

            if s:
                suit = s

    if rank and suit:
        return {
            "rank": rank,
            "suit": f"{suit}\ufe0f"
        }

    return None


def classify_key(key):
    key = str(key).strip().lower()

    if (
        key in ["p", "pcards", "playercards"]
        or key.startswith("player")
        or "playercard" in key
    ):
        return "player"

    if (
        key in ["d", "dcards", "dealercards"]
        or key.startswith("dealer")
        or "dealercard" in key
    ):
        return "dealer"

    return None


def find_cards_recursive(
    obj,
    context=None,
    player=None,
    dealer=None
):

    if player is None:
        player = []

    if dealer is None:
        dealer = []

    if isinstance(obj, dict):

        own = extract_card_from_dict(obj)

        if own:

            if context == "player":
                player.append(own)

            elif context == "dealer":
                dealer.append(own)

        for k, v in obj.items():

            ctx = context

            detected = classify_key(k)

            if detected:
                ctx = detected

            kl = str(k).strip().lower()

            if kl in {
                "p", "p1", "p2", "p3", "p4",
                "p5", "p6", "p7", "p8", "p9"
            }:
                ctx = "player"

            if kl in {
                "d", "d1", "d2", "d3", "d4",
                "d5", "d6", "d7", "d8", "d9"
            }:
                ctx = "dealer"

            find_cards_recursive(
                v,
                ctx,
                player,
                dealer
            )

    elif isinstance(obj, list):

        for item in obj:
            find_cards_recursive(
                item,
                context,
                player,
                dealer
            )

    return player, dealer


def clean_cards(cards):

    result = []
    seen = set()

    for card in cards:

        if not card:
            continue

        rank = normalize_rank(card.get("rank"))
        suit = normalize_suit(card.get("suit"))

        if not rank or not suit:
            continue

        key = f"{rank}{suit}"

        if key in seen:
            continue

        seen.add(key)

        result.append({
            "rank": rank,
            "suit": f"{suit}\ufe0f"
        })

    return result


# =====================================================================
# PARSE GAME
# =====================================================================

def parse_game_data(game_id, raw):

    if not raw:
        return None

    player, dealer = find_cards_recursive(raw)

    player = clean_cards(player)
    dealer = clean_cards(dealer)

    if not player:
        return None

    now = datetime.now(MOSCOW_TZ)

    state = deep_find_value(
        raw,
        ["state", "STATE", "status", "STATUS"]
    )

    if state is not None:
        state = str(state)

    all_cards = []
    sequence = []

    pos = 1

    for i in range(max(len(player), len(dealer))):

        if i < len(player):

            card = player[i]

            all_cards.append(card)

            sequence.append({
                "position": pos,
                "who": "P",
                "rank": card["rank"],
                "suit": card["suit"]
            })

            pos += 1

        if i < len(dealer):

            card = dealer[i]

            all_cards.append(card)

            sequence.append({
                "position": pos,
                "who": "D",
                "rank": card["rank"],
                "suit": card["suit"]
            })

            pos += 1

    return {
        "game_id": str(game_id),

        "timestamp_msk": (
            now.strftime("%H:%M:%S.%f")[:-3]
        ),

        "state": state,

        "player_cards": player,
        "dealer_cards": dealer,

        "player_suits": [
            c["suit"] for c in player
        ],

        "player_ranks": [
            c["rank"] for c in player
        ],

        "dealer_suits": [
            c["suit"] for c in dealer
        ],

        "dealer_ranks": [
            c["rank"] for c in dealer
        ],

        "all_suits": [
            c["suit"] for c in all_cards
        ],

        "all_ranks": [
            c["rank"] for c in all_cards
        ],

        "sequence": sequence,

        "total_cards": len(all_cards),

        "first_player_card": (
            player[0] if player else None
        ),

        "id_last_digit": str(game_id)[-1],

        "id_last_two": (
            str(game_id)[-2:]
            if len(str(game_id)) >= 2
            else ""
        )
    }


# =====================================================================
# MERGE / SAVE GAME
# =====================================================================

def add_or_update_game(game):

    gid = str(game.get("game_id", ""))

    if not gid:
        return False

    add_game_to_history(game)

    return True


# =====================================================================
# TARGET CARDS
# =====================================================================

def get_target_cards_from_record(record):

    result = []

    # Поддержка API-формата
    all_cards = (
        record.get("player_cards", [])
        + record.get("dealer_cards", [])
    )

    for card in all_cards:

        target = card_dict_to_target(card)

        if target:
            result.append(target)

    # Поддержка Telegram-формата
    if not result:

        telegram_cards = record.get("all_cards", [])

        for card in telegram_cards:

            if isinstance(card, str):

                if card in TARGET_CARDS:
                    result.append(card)

            elif isinstance(card, dict):

                target = card_dict_to_target(card)

                if target:
                    result.append(target)

    return result


# =====================================================================
# DISTRIBUTION
# =====================================================================

def normalize_distribution(counter):

    if not counter:
        return {}

    total = sum(counter.values())

    if total <= 0:
        return {}

    return {
        card: count / total
        for card, count in counter.items()
    }


def get_top_from_distribution(dist):

    if not dist:
        return None, 0.0

    sorted_items = sorted(
        dist.items(),
        key=lambda x: x[1],
        reverse=True
    )

    return sorted_items[0]


# =====================================================================
# METHOD 1 — MILLISECONDS
# =====================================================================

def method_milliseconds(timestamp_msk):

    if not timestamp_msk:
        return {}

    try:

        if "." not in timestamp_msk:
            return {}

        target_ms = int(
            timestamp_msk.split(".")[1]
        )

    except Exception:
        return {}

    counter = Counter()
    matches = 0

    for record in history:

        record_time = record.get(
            "timestamp_msk",
            ""
        )

        if "." not in record_time:
            continue

        try:
            ms = int(
                record_time.split(".")[1]
            )
        except Exception:
            continue

        if ms != target_ms:
            continue

        cards = get_target_cards_from_record(
            record
        )

        if not cards:
            continue

        matches += 1

        for card in cards:
            counter[card] += 1

    if matches < MIN_MS_MATCHES:
        return {}

    return {
        "name": "MS",
        "weight": WEIGHT_MS,
        "matches": matches,
        "distribution": normalize_distribution(
            counter
        )
    }


# =====================================================================
# METHOD 2 — LAST ID DIGIT
# =====================================================================

def method_id1(game_id):

    game_id = str(game_id)

    if not game_id:
        return {}

    digit = game_id[-1]

    counter = Counter()
    matches = 0

    for record in history:

        rid = str(
            record.get("game_id", "")
        )

        if not rid or rid == "None":
            continue

        if rid == game_id:
            continue

        if rid[-1] != digit:
            continue

        cards = get_target_cards_from_record(
            record
        )

        if not cards:
            continue

        matches += 1

        for card in cards:
            counter[card] += 1

    if matches < MIN_ID1_MATCHES:
        return {}

    return {
        "name": "ID1",
        "weight": WEIGHT_ID1,
        "matches": matches,
        "distribution": normalize_distribution(
            counter
        )
    }


# =====================================================================
# METHOD 3 — LAST 2 ID DIGITS
# =====================================================================

def method_id2(game_id):

    game_id = str(game_id)

    if len(game_id) < 2:
        return {}

    suffix = game_id[-2:]

    counter = Counter()
    matches = 0

    for record in history:

        rid = str(
            record.get("game_id", "")
        )

        if len(rid) < 2 or rid == "None":
            continue

        if rid == game_id:
            continue

        if rid[-2:] != suffix:
            continue

        cards = get_target_cards_from_record(
            record
        )

        if not cards:
            continue

        matches += 1

        for card in cards:
            counter[card] += 1

    if matches < MIN_ID2_MATCHES:
        return {}

    return {
        "name": "ID2",
        "weight": WEIGHT_ID2,
        "matches": matches,
        "distribution": normalize_distribution(
            counter
        )
    }


# =====================================================================
# METHOD 4 — FREQUENCY
# =====================================================================

def method_frequency():

    counter = Counter()

    recent = history[-150:]

    matches = 0

    for record in recent:

        cards = get_target_cards_from_record(
            record
        )

        if not cards:
            continue

        matches += 1

        for card in cards:
            counter[card] += 1

    if not counter:
        return {}

    return {
        "name": "FREQ",
        "weight": WEIGHT_FREQUENCY,
        "matches": matches,
        "distribution": normalize_distribution(
            counter
        )
    }


# =====================================================================
# METHOD 5 — SEQUENCE
# =====================================================================

def get_game_signature(game):

    sequence = game.get("sequence", [])

    if not sequence:
        return ()

    signature = []

    for item in sequence[:4]:

        who = item.get("who", "")
        rank = normalize_rank(
            item.get("rank")
        )

        if who and rank:
            signature.append(
                f"{who}:{rank}"
            )

    return tuple(signature)


def method_sequence():

    if len(history) < 10:
        return {}

    recent = history[-5:]

    if not recent:
        return {}

    pattern_counter = Counter()

    for g in recent:

        sig = get_game_signature(g)

        if sig:
            pattern_counter[sig] += 1

    if not pattern_counter:
        return {}

    counter = Counter()
    matches = 0

    for record in history[:-5]:

        sig = get_game_signature(record)

        if not sig:
            continue

        if sig not in pattern_counter:
            continue

        cards = get_target_cards_from_record(
            record
        )

        if not cards:
            continue

        matches += 1

        for card in cards:
            counter[card] += 1

    if matches < MIN_SEQUENCE_MATCHES:
        return {}

    return {
        "name": "SEQ",
        "weight": WEIGHT_SEQUENCE,
        "matches": matches,
        "distribution": normalize_distribution(
            counter
        )
    }


# =====================================================================
# HYBRID ENGINE
# =====================================================================

def build_hybrid_prediction(
    game_id,
    timestamp_msk
):

    results = [
        method_milliseconds(timestamp_msk),
        method_id1(game_id),
        method_id2(game_id),
        method_frequency(),
        method_sequence()
    ]

    active = []
    scores = defaultdict(float)
    method_details = {}

    for result in results:

        if not result:
            continue

        dist = result.get(
            "distribution",
            {}
        )

        if not dist:
            continue

        name = result["name"]
        weight = result["weight"]

        top_card, top_prob = (
            get_top_from_distribution(dist)
        )

        method_details[name] = {
            "top": top_card,
            "probability": top_prob,
            "matches": result.get(
                "matches",
                0
            )
        }

        active.append(name)

        for card, probability in dist.items():

            scores[card] += (
                probability * weight
            )

    if len(active) < MIN_ACTIVE_METHODS:

        print(
            f"⏭️ Недостаточно методов: {active}",
            flush=True
        )

        return None

    if not scores:
        return None

    total_score = sum(scores.values())

    probabilities = {
        card: score / total_score
        for card, score in scores.items()
    }

    ranking = sorted(
        probabilities.items(),
        key=lambda x: x[1],
        reverse=True
    )

    if not ranking:
        return None

    best_card, best_probability = ranking[0]

    second_card = None
    second_probability = 0.0

    if len(ranking) > 1:
        second_card = ranking[1][0]
        second_probability = ranking[1][1]

    gap = (
        best_probability
        - second_probability
    )

    supporters = []

    for name, info in method_details.items():

        if info.get("top") == best_card:
            supporters.append(name)

    return {
        "card": best_card,
        "probability": best_probability,

        "second_card": second_card,
        "second_probability": second_probability,

        "gap": gap,

        "active_methods": active,
        "supporters": supporters,

        "method_details": method_details,

        "ranking": ranking[:5]
    }


# =====================================================================
# FILTER
# =====================================================================

def prediction_passes_filter(result):

    if not result:
        return False

    probability = result.get(
        "probability",
        0
    )

    gap = result.get(
        "gap",
        0
    )

    supporters = result.get(
        "supporters",
        []
    )

    if probability < MIN_FORECAST_PROBABILITY:

        print(
            f"🚫 Лидер слабый: {probability:.1%}",
            flush=True
        )

        return False

    if gap < MIN_LEADER_GAP:

        print(
            f"🚫 Нет преимущества: gap={gap:.1%}",
            flush=True
        )

        return False

    if len(supporters) < MIN_ACTIVE_METHODS:

        print(
            f"🚫 Мало поддержки: {supporters}",
            flush=True
        )

        return False

    return True


# =====================================================================
# GAME NUMBER
# =====================================================================

def get_game_number():

    now = datetime.now(MOSCOW_TZ)

    start = now.replace(
        hour=3,
        minute=0,
        second=0,
        microsecond=0
    )

    if now < start:
        start -= timedelta(days=1)

    return (
        int(
            (now - start).total_seconds()
            // 60
        ) % 1440
    ) + 1


def add_game_offset(number, offset):

    return (
        (
            int(number)
            - 1
            + int(offset)
        ) % 1440
    ) + 1


# =====================================================================
# TELEGRAM SEND
# =====================================================================

def telegram_send(text, chat_id=None):

    if not chat_id:
        chat_id = CHANNEL_PROGNOZ

    try:

        response = SESSION.post(
            f"{TELEGRAM_API}/sendMessage",
            json={
                "chat_id": chat_id,
                "text": text,
                "parse_mode": "HTML",
                "disable_web_page_preview": True
            },
            timeout=10
        )

        data = response.json()

        if data.get("ok"):
            return data["result"]["message_id"]

        print(
            f"❌ Telegram: {data}",
            flush=True
        )

    except Exception as e:

        print(
            f"❌ Telegram ошибка: {e}",
            flush=True
        )

    return None


def telegram_edit(
    message_id,
    text,
    chat_id=None
):

    if not message_id:
        return False

    if not chat_id:
        chat_id = CHANNEL_PROGNOZ

    try:

        response = SESSION.post(
            f"{TELEGRAM_API}/editMessageText",
            json={
                "chat_id": chat_id,
                "message_id": message_id,
                "text": text,
                "parse_mode": "HTML"
            },
            timeout=10
        )

        return bool(
            response.json().get("ok")
        )

    except Exception:
        return False


# =====================================================================
# TELEGRAM INIT
# =====================================================================

def init_telegram():

    print(
        "\n══════════════════════════════════════"
    )
    print("🤖 ПРОВЕРКА TELEGRAM")
    print(
        "══════════════════════════════════════"
    )

    try:

        response = SESSION.get(
            f"{TELEGRAM_API}/getMe",
            timeout=10
        )

        data = response.json()

        if not data.get("ok"):

            print(
                f"❌ getMe ошибка: {data}",
                flush=True
            )

            return False

        bot = data.get("result", {})

        print(
            f"🤖 Запущен бот: "
            f"@{bot.get('username')} "
            f"| ID={bot.get('id')}",
            flush=True
        )

        print(
            f"📤 CHANNEL_PROGNOZ = "
            f"{CHANNEL_PROGNOZ}",
            flush=True
        )

        print(
            f"📥 CHANNEL_STATS = "
            f"{CHANNEL_STATS}",
            flush=True
        )

        # Проверяем webhook
        response = SESSION.get(
            f"{TELEGRAM_API}/getWebhookInfo",
            timeout=10
        )

        webhook_data = response.json()

        if webhook_data.get("ok"):

            webhook = webhook_data.get(
                "result",
                {}
            )

            webhook_url = webhook.get(
                "url",
                ""
            )

            print(
                f"🔗 Webhook: "
                f"{webhook_url if webhook_url else 'НЕТ'}",
                flush=True
            )

            # Если webhook есть — удаляем,
            # чтобы getUpdates мог работать
            if webhook_url:

                print(
                    "🗑️ Удаляем webhook...",
                    flush=True
                )

                delete_response = SESSION.post(
                    f"{TELEGRAM_API}/deleteWebhook",
                    json={
                        "drop_pending_updates": False
                    },
                    timeout=10
                )

                print(
                    f"🗑️ Ответ: "
                    f"{delete_response.json()}",
                    flush=True
                )

        print(
            "══════════════════════════════════════\n"
        )

        return True

    except Exception as e:

        print(
            f"❌ Ошибка Telegram init: {e}",
            flush=True
        )

        return False


# =====================================================================
# MESSAGES
# =====================================================================

def make_prediction_message(entry):

    result = entry["hybrid"]

    card1 = result["card"]
    prob1 = result["probability"]

    card2 = (
        result.get("second_card")
        or "—"
    )

    prob2 = result.get(
        "second_probability",
        0.0
    )

    return (
        f"🎯 Игра: #N{entry['target_number']}\n"
        f"🃏 {card1} — {prob1 * 100:.1f}%\n"
        f"🥈 {card2} — {prob2 * 100:.1f}%"
    )


# =====================================================================
# PARSE CARDS FROM TELEGRAM MESSAGE
# =====================================================================

def parse_cards_from_message(text):

    if not text:
        return None

    if not re.search(
        r"[✅🔰]",
        text
    ):
        return None

    match = re.search(
        r"#N(\d+)",
        text
    )

    if not match:
        return None

    game_number = int(
        match.group(1)
    )

    found = re.findall(
        r"(10|[2-9AJQK])([♠♣♦♥])\ufe0f?",
        text
    )

    cards = [
        f"{rank}{suit}\ufe0f"
        for rank, suit in found
    ]

    cards = list(
        dict.fromkeys(cards)
    )

    return {
        "game_number": game_number,
        "cards": cards
    }


# =====================================================================
# OFFSET
# =====================================================================

def get_offset():

    try:

        if os.path.exists(OFFSET_FILE):

            with open(
                OFFSET_FILE,
                "r"
            ) as f:

                value = f.read().strip()

                if value:
                    return int(value)

    except Exception:
        pass

    return 0


def save_offset(offset):

    try:

        with open(
            OFFSET_FILE,
            "w"
        ) as f:

            f.write(str(offset))

    except Exception as e:

        print(
            f"⚠️ Ошибка сохранения offset: {e}",
            flush=True
        )


# =====================================================================
# PROCESS TELEGRAM UPDATES
# =====================================================================

def process_telegram_updates(offset):

    global predictions, games_cache

    if not CHANNEL_STATS:

        print(
            "❌ CHANNEL_STATS не задан!",
            flush=True
        )

        return offset

    print(
        "📥 Проверяем обновления Telegram...",
        flush=True
    )

    try:

        params = {
            "timeout": 3,
            "limit": 50,
            "allowed_updates": json.dumps([
                "channel_post",
                "edited_channel_post"
            ])
        }

        if offset and int(offset) > 0:
            params["offset"] = int(offset)

        response = SESSION.get(
            f"{TELEGRAM_API}/getUpdates",
            params=params,
            timeout=10
        )

        data = response.json()

        if not data.get("ok"):

            print(
                f"❌ Ошибка Telegram API: {data}",
                flush=True
            )

            return offset

        updates = data.get(
            "result",
            []
        )

        print(
            f"📥 Получено обновлений: "
            f"{len(updates)}",
            flush=True
        )

        if not updates:
            return offset

        for update in updates:

            update_id = update.get(
                "update_id"
            )

            # Всегда подтверждаем update,
            # чтобы очередь не зацикливалась
            if update_id is not None:

                offset = int(update_id) + 1
                save_offset(offset)

            post = (
                update.get("channel_post")
                or update.get(
                    "edited_channel_post"
                )
            )

            if not post:
                continue

            chat = post.get(
                "chat",
                {}
            )

            chat_id = str(
                chat.get("id", "")
            ).strip()

            chat_title = chat.get(
                "title",
                ""
            )

            # СТРОГО ТОЛЬКО НУЖНЫЙ КАНАЛ
            if chat_id != CHANNEL_STATS:

                print(
                    f"⏭️ Пропуск другого канала: "
                    f"{chat_title} | {chat_id}",
                    flush=True
                )

                continue

            text = (
                post.get("text", "")
                or ""
            )

            print(
                f"\n✅ НУЖНЫЙ КАНАЛ: "
                f"{chat_title}",
                flush=True
            )

            print(
                f"📩 {text[:500]}",
                flush=True
            )

            # =========================================================
            # СОХРАНЯЕМ ЗАВЕРШЕННЫЕ ИГРЫ
            # =========================================================

            parsed = parse_cards_from_message(
                text
            )

            if parsed:

                games_cache[
                    parsed["game_number"]
                ] = text

                print(
                    f"💾 КЭШ: "
                    f"#{parsed['game_number']} "
                    f"-> {parsed['cards']}",
                    flush=True
                )

                id_match = re.search(
                    r"ID:\s*(\d+)",
                    text
                )

                game_id = (
                    id_match.group(1)
                    if id_match
                    else ""
                )

                game_data = {
                    "game_id": game_id,

                    "game_number": (
                        parsed["game_number"]
                    ),

                    "timestamp_msk": (
                        datetime.now(
                            MOSCOW_TZ
                        ).strftime(
                            "%H:%M:%S.%f"
                        )[:-3]
                    ),

                    "state": "finished",

                    "player_cards": [],
                    "dealer_cards": [],

                    "all_cards": (
                        parsed["cards"]
                    ),

                    "total_cards": len(
                        parsed["cards"]
                    ),

                    "source": "telegram"
                }

                # Не сохраняем дубли
                if game_id:

                    exists = any(
                        str(
                            g.get(
                                "game_id",
                                ""
                            )
                        ) == game_id
                        for g in history
                    )

                    if not exists:

                        add_game_to_history(
                            game_data
                        )

                print(
                    f"💾 Получен результат "
                    f"#N{parsed['game_number']}",
                    flush=True
                )

            # =========================================================
            # ИЩЕМ НОВУЮ ИГРУ ДЛЯ ПРОГНОЗА
            # =========================================================

            if "⏳ Ожидание игры" not in text:
                continue

            print(
                "🔍 Найдено сообщение "
                "'⏳ Ожидание игры'",
                flush=True
            )

            id_match = re.search(
                r"ID:\s*(\d+)",
                text
            )

            num_match = re.search(
                r"#N(\d+)",
                text
            )

            if not id_match or not num_match:

                print(
                    "⚠️ Не найден ID или номер игры",
                    flush=True
                )

                continue

            game_id = id_match.group(1)

            game_number = int(
                num_match.group(1)
            )

            print(
                f"🆕 Новая игра: "
                f"#N{game_number} | "
                f"ID={game_id}",
                flush=True
            )

            has_prediction = any(
                entry.get("target_number")
                == game_number
                and entry.get("status")
                == "pending"
                for entry in predictions
            )

            if has_prediction:

                print(
                    f"⏭️ Прогноз на "
                    f"#N{game_number} уже есть",
                    flush=True
                )

                continue

            prediction = create_hybrid_prediction(
                game_id,
                game_number
            )

            if not prediction:
                continue

            message = make_prediction_message(
                prediction
            )

            prediction["original_text"] = message

            message_id = telegram_send(
                message
            )

            if message_id:

                prediction["message_id"] = (
                    message_id
                )

                atomic_save_json(
                    PREDICTIONS_FILE,
                    predictions
                )

                print(
                    f"📤 ПРОГНОЗ ОТПРАВЛЕН: "
                    f"{prediction['predicted_card']} "
                    f"на #N{game_number}",
                    flush=True
                )

    except Exception as e:

        print(
            f"⚠️ Updates error: {e}",
            flush=True
        )

    return offset


# =====================================================================
# CHECK PREDICTIONS
# =====================================================================

def check_predictions():

    global predictions

    if not predictions:

        print(
            "📭 Нет прогнозов для проверки",
            flush=True
        )

        return

    print(
        f"🔍 Проверяем {len(predictions)} "
        f"прогнозов | кэш: "
        f"{len(games_cache)}",
        flush=True
    )

    changed = False

    for entry in predictions:

        if entry.get("status") != "pending":
            continue

        target = entry.get(
            "target_number"
        )

        predicted_cards = [
            card
            for card in entry.get(
                "predicted_cards",
                []
            )
            if card
        ]

        msg_id = entry.get(
            "message_id"
        )

        original_text = entry.get(
            "original_text",
            ""
        )

        if (
            not target
            or not predicted_cards
        ):
            continue

        found = None
        all_available = True

        for dogon in range(
            DOGON_GAMES + 1
        ):

            num = add_game_offset(
                target,
                dogon
            )

            text = games_cache.get(num)

            if not text:

                all_available = False
                continue

            parsed = parse_cards_from_message(
                text
            )

            if not parsed:
                continue

            actual_cards = parsed.get(
                "cards",
                []
            )

            for card in predicted_cards:

                if card in actual_cards:

                    found = {
                        "num": num,
                        "dogon": dogon,
                        "card": card
                    }

                    break

            if found:
                break

        if found:

            entry["status"] = "win"

            entry["result_game"] = (
                found["num"]
            )

            entry["found_card"] = (
                found["card"]
            )

            entry["current_dogon"] = (
                found["dogon"]
            )

            changed = True

            print(
                f"✅ ЗАШЛО на "
                f"#{found['num']} | "
                f"догон {found['dogon']} | "
                f"{found['card']}",
                flush=True
            )

            if msg_id and original_text:

                lines = (
                    original_text.split("\n")
                )

                lines[0] = (
                    f"🎯 Игра: "
                    f"#N{target} ✅"
                )

                telegram_edit(
                    msg_id,
                    "\n".join(lines)
                )

            continue

        if not all_available:

            print(
                f"⏳ Ожидание результатов "
                f"для #{target}",
                flush=True
            )

            continue

        entry["status"] = "lose"

        changed = True

        print(
            f"❌ НЕ ЗАШЛО: "
            f"догоны 0-{DOGON_GAMES} "
            f"для #{target}",
            flush=True
        )

        if msg_id and original_text:

            lines = original_text.split("\n")

            lines[0] = (
                f"🎯 Игра: "
                f"#N{target} ❌"
            )

            telegram_edit(
                msg_id,
                "\n".join(lines)
            )

    if changed:

        atomic_save_json(
            PREDICTIONS_FILE,
            predictions
        )

        print(
            "💾 Прогнозы обновлены",
            flush=True
        )


# =====================================================================
# CREATE PREDICTION
# =====================================================================

def create_hybrid_prediction(
    game_id,
    game_number
):

    global last_prediction_time

    game_id = str(game_id)

    for entry in predictions:

        if (
            entry.get("target_number")
            == game_number
            and entry.get("status")
            == "pending"
        ):

            print(
                f"⏭️ Прогноз на "
                f"#N{game_number} уже существует",
                flush=True
            )

            return None

    now_ts = time.time()

    if (
        now_ts - last_prediction_time
        < PREDICTION_COOLDOWN_SECONDS
    ):

        print(
            f"⏭️ Cooldown "
            f"{PREDICTION_COOLDOWN_SECONDS} сек",
            flush=True
        )

        return None

    now = datetime.now(MOSCOW_TZ)

    timestamp_msk = (
        now.strftime("%H:%M:%S.%f")[:-3]
    )

    print(
        "\n══════════════════════════════════",
        flush=True
    )

    print(
        f"🧠 HYBRID АНАЛИЗ | "
        f"ID={game_id} | "
        f"#N{game_number}",
        flush=True
    )

    result = build_hybrid_prediction(
        game_id,
        timestamp_msk
    )

    if not result:

        print(
            "⏭️ Гибрид не дал результата",
            flush=True
        )

        return None

    print(
        f"🥇 {result['card']} "
        f"{result['probability']:.1%}",
        flush=True
    )

    print(
        f"🥈 {result['second_card']} "
        f"{result['second_probability']:.1%}",
        flush=True
    )

    print(
        f"📏 Gap: {result['gap']:.1%}",
        flush=True
    )

    print(
        f"🤝 Поддержка: "
        f"{result['supporters']}",
        flush=True
    )

    if not prediction_passes_filter(result):

        print(
            "🚫 ПРОГНОЗ ОТМЕНЁН ФИЛЬТРОМ",
            flush=True
        )

        return None

    entry = {
        "target_game_id": game_id,

        "target_number": game_number,

        "timestamp_msk": timestamp_msk,

        "hybrid": result,

        "predicted_card": result["card"],

        "predicted_cards": [
            result["card"],
            result.get("second_card")
        ],

        "status": "pending",

        "current_dogon": 0,

        "created_at": (
            datetime.now(
                MOSCOW_TZ
            ).isoformat()
        ),

        "message_id": None,

        "original_text": "",

        "result_game": None,

        "found_card": None
    }

    predictions.append(entry)

    atomic_save_json(
        PREDICTIONS_FILE,
        predictions
    )

    last_prediction_time = now_ts

    print(
        f"🔮 ПРОГНОЗ СОЗДАН: "
        f"{result['card']} "
        f"для #N{game_number}",
        flush=True
    )

    return entry


# =====================================================================
# API GET GAME
# =====================================================================

def get_game_data(game_id):

    url = (
        f"{BASE_URL}/service-api/"
        "LiveFeed/GetGameZip"
        f"?id={game_id}"
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

        response = SESSION.get(
            url,
            timeout=7
        )

        if response.status_code == 200:
            return response.json()

    except Exception:
        pass

    return None


# =====================================================================
# API ACTIVE GAMES
# =====================================================================

def get_active_games():

    url = (
        f"{BASE_URL}/service-api/"
        "main-live-feed/v3/games1x2"
        "?cfView=3"
        "&count=40"
        "&fcountry=190"
        "&gr=415"
        "&grMode=4"
        "&lng=ru"
        "&ref=7"
        "&selectedMs=10.146.1643503"
    )

    try:

        response = SESSION.get(
            url,
            timeout=10
        )

        if response.status_code != 200:
            return []

        data = response.json()

        if isinstance(data, list):
            games = data

        elif isinstance(data, dict):
            games = data.get(
                "Value",
                []
            )

        else:
            games = []

        result = []

        for game in games:

            if not isinstance(game, dict):
                continue

            liga = game.get(
                "liga",
                {}
            )

            if (
                str(
                    liga.get("id", "")
                )
                != str(LEAGUE_ID)
            ):
                continue

            if not game.get("id"):
                continue

            result.append(game)

        return result

    except Exception as e:

        print(
            f"❌ API games: {e}",
            flush=True
        )

        return []


# =====================================================================
# PROCESS GAME
# =====================================================================

def process_game(active_game):

    gid = str(
        active_game.get("id", "")
    )

    if not gid:
        return

    game_number = None

    if "gameNumber" in active_game:

        game_number = int(
            active_game["gameNumber"]
        )

    elif "number" in active_game:

        game_number = int(
            active_game["number"]
        )

    else:

        game_number = get_game_number()

    raw = get_game_data(gid)

    if raw:

        parsed = parse_game_data(
            gid,
            raw
        )

        if parsed:

            parsed["game_number"] = (
                game_number
            )

            add_game_to_history(
                parsed
            )


# =====================================================================
# CLEANUP
# =====================================================================

def cleanup_predictions():

    global predictions

    if len(predictions) > 1000:

        predictions = predictions[-1000:]

        atomic_save_json(
            PREDICTIONS_FILE,
            predictions
        )


# =====================================================================
# MAIN
# =====================================================================

def main():

    global history, predictions

    print(
        "\n=================================================="
    )

    print(
        "🚀 БОТ — ПРОГНОЗЫ ПО ID ИЗ КАНАЛА + ИСТОРИЯ ИЗ API"
    )

    print(
        "=================================================="
    )

    history = load_history()
    predictions = load_predictions()

    print(
        f"📚 История: "
        f"{len(history)} игр"
    )

    print(
        f"📊 Прогнозов: "
        f"{len(predictions)}"
    )

    print(
        f"📥 CHANNEL_STATS: "
        f"{CHANNEL_STATS}"
    )

    print(
        f"📤 CHANNEL_PROGNOZ: "
        f"{CHANNEL_PROGNOZ}"
    )

    print(
        "==================================================\n"
    )

    # Проверяем Telegram перед запуском
    if not init_telegram():

        print(
            "❌ Telegram не прошёл проверку",
            flush=True
        )

        return

    offset = get_offset()

    print(
        f"📌 Telegram offset: {offset}",
        flush=True
    )

    while True:

        start = time.time()

        try:

            # =========================================================
            # 1. API
            # =========================================================

            games = get_active_games()

            if games:

                print(
                    f"📡 API: "
                    f"{len(games)} игр",
                    flush=True
                )

            for game in games:

                try:

                    process_game(game)

                except Exception as e:

                    print(
                        f"❌ Ошибка API: {e}",
                        flush=True
                    )

            # =========================================================
            # 2. TELEGRAM CHANNEL
            # =========================================================

            offset = process_telegram_updates(
                offset
            )

            # =========================================================
            # 3. CHECK PREDICTIONS
            # =========================================================

            check_predictions()

            # =========================================================
            # 4. CLEANUP
            # =========================================================

            cleanup_predictions()

            elapsed = time.time() - start

            time.sleep(
                max(
                    0.1,
                    POLL_INTERVAL - elapsed
                )
            )

        except KeyboardInterrupt:

            print(
                "\n🛑 Бот остановлен",
                flush=True
            )

            break

        except Exception as e:

            print(
                f"❌ Критическая ошибка: {e}",
                flush=True
            )

            time.sleep(3)


# =====================================================================
# START
# =====================================================================

if __name__ == "__main__":
    main()