import os
import sys
import json
import time
import re
import requests
import pytz

from datetime import datetime, timedelta
from collections import Counter, defaultdict

# ============================================================
# ENV
# ============================================================

BOT_TOKEN = os.getenv("BOT_TOKEN") or os.getenv("BOT_TOKEN_PROGNOZ")
CHANNEL_PROGNOZ = os.getenv("CHAT_ID_21") or os.getenv("CHANNEL_PROGNOZ")
CHANNEL_PROGNOZ = "-1001234567890"  # Твой канал с прогнозами
CHANNEL_STATS = "-1003477065559"    # Канал статистики

if not BOT_TOKEN:
    print("❌ BOT_TOKEN не задан", flush=True)
    sys.exit(1)

if not CHANNEL_PROGNOZ:
    print("❌ CHAT_ID_21 / CHANNEL_PROGNOZ не задан", flush=True)
    sys.exit(1)

# ============================================================
# CONFIG
# ============================================================

MOSCOW_TZ = pytz.timezone("Europe/Moscow")

BASE_URL = "https://1xlite-36553.pro"
LEAGUE_ID = 1643503

DATA_FILE = "twentyone_data_full.json"
PREDICTIONS_FILE = "twentyone_predictions_scanner.json"
OFFSET_FILE = "scanner_offset.txt"

MAX_HISTORY_GAMES = 3000
DOGON_GAMES = 4
POLL_INTERVAL = 2.0
PREDICTION_COOLDOWN_SECONDS = 15

TARGET_RANKS = {"J", "Q", "K", "A"}
TARGET_CARDS = [
    "J♠️", "J♣️", "J♦️", "J♥️",
    "Q♠️", "Q♣️", "Q♦️", "Q♥️",
    "K♠️", "K♣️", "K♦️", "K♥️",
    "A♠️", "A♣️", "A♦️", "A♥️",
]

WEIGHT_MS = 1.00
WEIGHT_ID1 = 0.80
WEIGHT_ID2 = 1.20
WEIGHT_FREQUENCY = 0.50
WEIGHT_PATTERN = 1.60

MIN_MS_MATCHES = 2
MIN_ID1_MATCHES = 3
MIN_ID2_MATCHES = 2
MIN_PATTERN_MATCHES = 3

MIN_FORECAST_PROBABILITY = 0.17
MIN_ACTIVE_METHODS = 2

PATTERN_LENGTHS = (2, 3, 4, 5)
PATTERN_LOOKBACK = 2500
PATTERN_MAX_MATCHES = 150

TELEGRAM_API = f"https://api.telegram.org/bot{BOT_TOKEN}"

HEADERS = {
    "User-Agent": "Mozilla/5.0",
    "Accept": "application/json, text/plain, */*",
    "Referer": f"{BASE_URL}/ru/live/twentyone/1643503-twentyone-game",
}

SESSION = requests.Session()
SESSION.headers.update(HEADERS)

SUITS = {
    0: "♠",
    1: "♣",
    2: "♦",
    3: "♥",
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
    14: "A",
}

history = []
predictions = []
games_cache = {}
last_prediction_time = 0


# ============================================================
# NORMALIZE
# ============================================================

def normalize_suit(value):
    if value is None or isinstance(value, bool):
        return None

    if isinstance(value, int):
        return SUITS.get(value)

    value = str(value).strip().replace("\ufe0f", "").lower()

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
        "h": "♥",
    }

    return mapping.get(value)


def normalize_rank(value):
    if value is None or isinstance(value, bool):
        return None

    if isinstance(value, int):
        return RANKS.get(value)

    value = str(value).strip().upper().replace("А", "A")

    if value in {
        "2", "3", "4", "5", "6", "7",
        "8", "9", "10", "J", "Q", "K", "A"
    }:
        return value

    try:
        return RANKS.get(int(value))
    except Exception:
        return None


def card_text(card):
    if not isinstance(card, dict):
        return ""

    rank = normalize_rank(card.get("rank"))
    suit = normalize_suit(card.get("suit"))

    if not rank or not suit:
        return ""

    return f"{rank}{suit}\ufe0f"


def target_card(card):
    value = card_text(card)
    return value if value in TARGET_CARDS else None


# ============================================================
# FILES
# ============================================================

def load_json(filename, default):
    try:
        if not os.path.exists(filename):
            return default

        with open(filename, "r", encoding="utf-8") as f:
            data = json.load(f)

        return data

    except Exception as e:
        print(f"⚠️ Ошибка чтения {filename}: {e}", flush=True)
        return default


def save_json(filename, data):
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
        return False


def load_history():
    data = load_json(DATA_FILE, [])

    if not isinstance(data, list):
        return []

    clean = [
        x for x in data
        if isinstance(x, dict) and x.get("game_id")
    ]

    return clean[-MAX_HISTORY_GAMES:]


def load_predictions():
    data = load_json(PREDICTIONS_FILE, [])

    return data if isinstance(data, list) else []


# ============================================================
# GAME HELPERS
# ============================================================

def find_game_index(game_id):
    game_id = str(game_id)

    for i, game in enumerate(history):
        if str(game.get("game_id")) == game_id:
            return i

    return -1


def game_exists(game_id):
    return find_game_index(game_id) >= 0


def get_record_targets(record):
    result = []

    for card in (
        record.get("player_cards", [])
        + record.get("dealer_cards", [])
    ):
        value = target_card(card)

        if value:
            result.append(value)

    return result


def get_game_tokens(game):
    tokens = []
    sequence = game.get("sequence", [])

    if sequence:
        for item in sequence:
            who = str(item.get("who", "")).upper()
            rank = normalize_rank(item.get("rank"))
            suit = normalize_suit(item.get("suit"))

            if who and rank and suit:
                tokens.append(
                    f"{who}:{rank}{suit}"
                )

        if tokens:
            return tuple(tokens)

    for card in game.get("player_cards", []):
        text = card_text(card)

        if text:
            tokens.append(
                f"P:{text.replace(chr(65039), '')}"
            )

    for card in game.get("dealer_cards", []):
        text = card_text(card)

        if text:
            tokens.append(
                f"D:{text.replace(chr(65039), '')}"
            )

    return tuple(tokens)


def get_game_signature(game):
    tokens = get_game_tokens(game)

    return "|".join(tokens[:6])


# ============================================================
# DISTRIBUTIONS
# ============================================================

def normalize_distribution(counter):
    total = sum(counter.values())

    if total <= 0:
        return {}

    return {
        key: value / total
        for key, value in counter.items()
    }


def top_item(distribution):
    if not distribution:
        return None, 0.0

    return max(
        distribution.items(),
        key=lambda x: x[1]
    )


# ============================================================
# HYBRID METHODS
# ============================================================

def method_milliseconds(timestamp_msk):
    if "." not in str(timestamp_msk):
        return {}

    try:
        target_ms = int(
            str(timestamp_msk).split(".")[-1]
        )
    except Exception:
        return {}

    counter = Counter()
    matches = 0

    for record in history:
        ts = str(
            record.get("timestamp_msk", "")
        )

        if "." not in ts:
            continue

        try:
            ms = int(ts.split(".")[-1])
        except Exception:
            continue

        if ms != target_ms:
            continue

        cards = get_record_targets(record)

        if cards:
            matches += 1
            counter.update(cards)

    if matches < MIN_MS_MATCHES:
        return {}

    return {
        "name": "MS",
        "weight": WEIGHT_MS,
        "matches": matches,
        "distribution": normalize_distribution(counter),
    }


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

        if (
            rid == game_id
            or not rid
            or rid[-1] != digit
        ):
            continue

        cards = get_record_targets(record)

        if cards:
            matches += 1
            counter.update(cards)

    if matches < MIN_ID1_MATCHES:
        return {}

    return {
        "name": "ID1",
        "weight": WEIGHT_ID1,
        "matches": matches,
        "distribution": normalize_distribution(counter),
    }


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

        if (
            rid == game_id
            or len(rid) < 2
            or rid[-2:] != suffix
        ):
            continue

        cards = get_record_targets(record)

        if cards:
            matches += 1
            counter.update(cards)

    if matches < MIN_ID2_MATCHES:
        return {}

    return {
        "name": "ID2",
        "weight": WEIGHT_ID2,
        "matches": matches,
        "distribution": normalize_distribution(counter),
    }


def method_frequency():
    counter = Counter()

    recent = history[-150:]
    matches = 0

    for record in recent:
        cards = get_record_targets(record)

        if cards:
            matches += 1
            counter.update(cards)

    if not counter:
        return {}

    return {
        "name": "FREQ",
        "weight": WEIGHT_FREQUENCY,
        "matches": matches,
        "distribution": normalize_distribution(counter),
    }


# ============================================================
# PATTERN SCANNER
# ============================================================

def method_pattern_scanner():
    if len(history) < 30:
        return {}

    current_games = history[-5:]
    current_sequence = []

    for game in current_games:
        tokens = get_game_tokens(game)

        if tokens:
            current_sequence.append(tokens)

    if len(current_sequence) < 2:
        return {}

    scan_records = history[-PATTERN_LOOKBACK:]

    counter = Counter()
    total_matches = 0
    patterns_found = []

    for pattern_len in PATTERN_LENGTHS:

        if len(current_sequence) < pattern_len:
            continue

        pattern = current_sequence[-pattern_len:]

        local_counter = Counter()
        local_matches = 0

        max_start = (
            len(scan_records)
            - pattern_len
            - 1
        )

        for start in range(max_start):

            candidate = []
            valid = True

            for j in range(pattern_len):

                tokens = get_game_tokens(
                    scan_records[start + j]
                )

                if not tokens:
                    valid = False
                    break

                candidate.append(tokens)

            if not valid:
                continue

            if candidate != pattern:
                continue

            next_game = scan_records[
                start + pattern_len
            ]

            cards = get_record_targets(
                next_game
            )

            if not cards:
                continue

            local_matches += 1
            local_counter.update(cards)

            if local_matches >= PATTERN_MAX_MATCHES:
                break

        if local_matches >= MIN_PATTERN_MATCHES:

            strength = (
                1.0
                + (pattern_len - 2) * 0.35
            )

            for card, count in local_counter.items():
                counter[card] += (
                    count * strength
                )

            total_matches += local_matches

            top, prob = top_item(
                normalize_distribution(
                    local_counter
                )
            )

            patterns_found.append({
                "length": pattern_len,
                "matches": local_matches,
                "top": top,
                "probability": prob,
            })

    if (
        not counter
        or total_matches < MIN_PATTERN_MATCHES
    ):
        return {}

    return {
        "name": "SCAN",
        "weight": WEIGHT_PATTERN,
        "matches": total_matches,
        "distribution": normalize_distribution(counter),
        "patterns": patterns_found,
    }


# ============================================================
# HYBRID ENGINE
# ============================================================

def build_prediction(game_id, timestamp_msk):

    results = [
        method_milliseconds(timestamp_msk),
        method_id1(game_id),
        method_id2(game_id),
        method_frequency(),
        method_pattern_scanner(),
    ]

    scores = defaultdict(float)
    active = []
    details = {}

    for result in results:

        if not result:
            continue

        dist = result.get("distribution", {})

        if not dist:
            continue

        name = result["name"]

        active.append(name)

        top, probability = top_item(dist)

        details[name] = {
            "top": top,
            "probability": probability,
            "matches": result.get(
                "matches",
                0
            ),
        }

        if name == "SCAN":
            details[name]["patterns"] = (
                result.get("patterns", [])
            )

        for card, probability in dist.items():
            scores[card] += (
                probability
                * result["weight"]
            )

    if (
        len(active) < MIN_ACTIVE_METHODS
        or not scores
    ):
        print(
            f"⏭️ Недостаточно методов: {active}",
            flush=True
        )
        return None

    total = sum(scores.values())

    ranking = sorted(
        (
            (
                card,
                score / total
            )
            for card, score in scores.items()
        ),
        key=lambda x: x[1],
        reverse=True,
    )

    if not ranking:
        return None

    best_card, best_probability = ranking[0]

    second_card, second_probability = (
        ranking[1]
        if len(ranking) > 1
        else (None, 0.0)
    )

    supporters = [
        name
        for name, info in details.items()
        if info.get("top") == best_card
    ]

    return {
        "card": best_card,
        "probability": best_probability,
        "second_card": second_card,
        "second_probability": second_probability,
        "gap": (
            best_probability
            - second_probability
        ),
        "active_methods": active,
        "supporters": supporters,
        "method_details": details,
        "ranking": ranking[:10],
    }


def prediction_passes(result):
    if not result:
        return False

    probability = float(
        result.get(
            "probability",
            0.0
        )
    )

    second_card = result.get(
        "second_card"
    )

    second_probability = float(
        result.get(
            "second_probability",
            0.0
        )
    )

    if probability < MIN_FORECAST_PROBABILITY:
        print(
            f"🚫 Лидер слабый: "
            f"{probability:.1%}",
            flush=True
        )
        return False

    if (
        not second_card
        or second_probability <= 0
    ):
        print(
            "🚫 TOP-2 недоступен",
            flush=True
        )
        return False

    print(
        f"✅ TOP-2 ПРОШЁЛ ФИЛЬТР | "
        f"TOP-1={probability:.1%} | "
        f"TOP-2={second_probability:.1%}",
        flush=True,
    )

    return True


# ============================================================
# GAME NUMBER
# ============================================================

def get_game_number():
    now = datetime.now(MOSCOW_TZ)
    start = now.replace(hour=3, minute=0, second=0, microsecond=0)
    if now < start:
        start -= timedelta(days=1)
    return (int((now - start).total_seconds() // 60) % 1440) + 1


def get_lobby_game_number():
    current_number = get_game_number()
    return add_game_offset(current_number, 1)


def add_game_offset(number, offset):
    return ((int(number) - 1 + int(offset)) % 1440) + 1


# ============================================================
# TELEGRAM
# ============================================================

def telegram_send(text, chat_id=None):
    chat_id = chat_id or CHANNEL_PROGNOZ

    try:
        response = SESSION.post(
            f"{TELEGRAM_API}/sendMessage",
            json={
                "chat_id": chat_id,
                "text": text,
                "parse_mode": "HTML",
                "disable_web_page_preview": True,
            },
            timeout=10,
        )

        data = response.json()

        if data.get("ok"):
            return data["result"]["message_id"]

        print(f"❌ Telegram: {data}", flush=True)

    except Exception as e:
        print(f"❌ Telegram error: {e}", flush=True)

    return None


def telegram_edit(message_id, text, chat_id=None):
    if not message_id:
        return False

    chat_id = chat_id or CHANNEL_PROGNOZ

    try:
        response = SESSION.post(
            f"{TELEGRAM_API}/editMessageText",
            json={
                "chat_id": chat_id,
                "message_id": message_id,
                "text": text,
                "parse_mode": "HTML",
            },
            timeout=10,
        )

        return bool(response.json().get("ok"))

    except Exception:
        return False


# ============================================================
# MESSAGES
# ============================================================

def make_prediction_message(entry):
    """Минимальный прогноз — только номер игры и TOP-2"""
    result = entry["hybrid"]
    
    card1 = result["card"]
    prob1 = result["probability"]
    card2 = result.get("second_card") or "—"
    prob2 = result.get("second_probability", 0.0)
    
    text = (
        f"🎯 #N{entry['target_number']}\n"
        f"🥇 {card1} {prob1*100:.1f}%\n"
        f"🥈 {card2} {prob2*100:.1f}%"
    )
    
    return text


def make_result_message(entry, status, found_card=None, result_game=None):
    """Формируем результат после проверки"""
    if status == "win":
        return (
            f"🎯 #N{entry['target_number']}\n"
            f"✅ ЗАШЛО на #{result_game}\n"
            f"🃏 {found_card}"
        )
    else:
        return (
            f"🎯 #N{entry['target_number']}\n"
            f"❌ НЕ ЗАШЛО"
        )


# ============================================================
# PREDICTIONS
# ============================================================

def has_pending_prediction():
    """НИКОГДА НЕ БЛОКИРУЕМ - даем прогноз на КАЖДУЮ новую игру"""
    return False


def prediction_exists(game_id):
    game_id = str(game_id)
    return any(str(x.get("target_game_id")) == game_id for x in predictions)


def create_prediction(game_id, game_number):
    global last_prediction_time

    game_id = str(game_id)

    if prediction_exists(game_id):
        print(f"⏭️ Прогноз уже существует для ID={game_id}", flush=True)
        return None

    now_ts = time.time()

    if now_ts - last_prediction_time < PREDICTION_COOLDOWN_SECONDS:
        print("⏭️ Cooldown прогноза", flush=True)
        return None

    timestamp = datetime.now(MOSCOW_TZ).strftime("%H:%M:%S.%f")[:-3]

    print("\n══════════════════════════════════", flush=True)
    print(f"🧠 HYBRID + SCANNER | ID={game_id}", flush=True)
    print(f"🎯 ЦЕЛЕВАЯ ИГРА = #N{game_number} | ДОГОН 0", flush=True)
    print(f"⏱ Timestamp={timestamp}", flush=True)

    result = build_prediction(game_id, timestamp)

    if not result:
        print("⏭️ Гибрид не дал результата", flush=True)
        return None

    print(f"🥇 {result['card']} {result['probability']:.1%}", flush=True)
    print(f"🥈 {result['second_card']} {result['second_probability']:.1%}", flush=True)

    if not prediction_passes(result):
        print("🚫 ПРОГНОЗ ОТМЕНЁН ФИЛЬТРОМ", flush=True)
        return None

    entry = {
        "target_game_id": game_id,
        "target_number": game_number,
        "timestamp_msk": timestamp,
        "hybrid": result,
        "predicted_card": result["card"],
        "predicted_cards": [result["card"], result.get("second_card")],
        "status": "pending",
        "current_dogon": 0,
        "created_at": datetime.now(MOSCOW_TZ).isoformat(),
        "message_id": None,
        "original_text": "",
        "result_game": None,
        "found_card": None,
    }

    predictions.append(entry)
    save_json(PREDICTIONS_FILE, predictions)
    last_prediction_time = now_ts

    return entry


# ============================================================
# PARSE CARDS
# ============================================================

def parse_cards_from_message(text):
    """Парсит номер игры и все карты из сообщения"""
    if not text:
        return None

    match = re.search(r"#N(\d+)", text)
    if not match:
        return None

    game_number = int(match.group(1))

    # Ищем все карты в формате: 6♦️, K♥️, J♣️, 10♦️
    found = re.findall(r"(10|[2-9AJQK])([♠♣♦♥])\ufe0f?", text)
    if not found:
        found = re.findall(r"(10|[2-9AJQK])([♠♣♦♥])", text)

    cards = [f"{rank}{suit}\ufe0f" for rank, suit in found]

    # Если карт нет - ищем в скобках
    if not cards:
        matches = re.findall(r"\((.*?)\)", text)
        for match in matches:
            found_inner = re.findall(r"(10|[2-9AJQK])([♠♣♦♥])\ufe0f?", match)
            for rank, suit in found_inner:
                cards.append(f"{rank}{suit}\ufe0f")

    cards = list(dict.fromkeys(cards))

    return {
        "game_number": game_number,
        "cards": cards,
    }


# ============================================================
# CHECK PREDICTIONS - НОВАЯ ВЕРСИЯ
# ============================================================

def check_predictions():
    """Проверяет прогнозы через кэш игр из канала статистики"""
    global predictions

    if not predictions:
        return

    changed = False

    for entry in predictions:
        if entry.get("status") != "pending":
            continue

        target = entry.get("target_number")
        predicted_cards = entry.get("predicted_cards", [])
        msg_id = entry.get("message_id")
        api_game_id = entry.get("target_game_id")

        if not target or not predicted_cards or not msg_id:
            continue

        found = None
        all_available = True

        # Перебираем догоны от 0 до DOGON_GAMES
        for dogon in range(DOGON_GAMES + 1):
            num = add_game_offset(target, dogon)
            text = games_cache.get(num)

            if not text:
                all_available = False
                continue

            # Парсим карты из текста
            parsed = parse_cards_from_message(text)
            if not parsed:
                continue

            actual_cards = parsed.get("cards", [])

            # Проверяем, есть ли совпадение с predicted_cards
            hit_card = next(
                (card for card in predicted_cards if card in actual_cards),
                None
            )

            if hit_card:
                found = {
                    "num": num,
                    "dogon": dogon,
                    "card": hit_card,
                    "text": text,
                }
                break

        # ============================================================
        # WIN
        # ============================================================
        if found:
            entry["status"] = "win"
            entry["result_game"] = found["num"]
            entry["found_card"] = found["card"]
            entry["current_dogon"] = found["dogon"]
            changed = True

            print(
                f"✅ ЗАШЛО на #{found['num']} | "
                f"догон {found['dogon']} | "
                f"карта {found['card']}",
                flush=True
            )

            # Редактируем сообщение
            if msg_id:
                telegram_edit(
                    msg_id,
                    make_result_message(entry, "win", found["card"], found["num"])
                )

            save_json(PREDICTIONS_FILE, predictions)
            continue

        # ============================================================
        # НЕ ВСЕ ИГРЫ ДОСТУПНЫ → ЖДЁМ
        # ============================================================
        if not all_available:
            print(f"⏳ Ожидание результатов для #{target} (не все догоны доступны)", flush=True)
            continue

        # ============================================================
        # LOSE (все догоны проверены, ничего не зашло)
        # ============================================================
        entry["status"] = "lose"
        changed = True

        print(
            f"❌ НЕ ЗАШЛО: исчерпаны догоны 0-{DOGON_GAMES} для #{target}",
            flush=True
        )

        if msg_id:
            telegram_edit(
                msg_id,
                make_result_message(entry, "lose")
            )

        save_json(PREDICTIONS_FILE, predictions)

    if changed:
        print("💾 Прогнозы обновлены", flush=True)


# ============================================================
# PROCESS UPDATES
# ============================================================

def process_updates(offset):
    """Читает канал статистики и заполняет games_cache"""
    if not CHANNEL_STATS:
        return offset

    try:
        response = SESSION.get(
            f"{TELEGRAM_API}/getUpdates",
            params={
                "offset": offset,
                "timeout": 3,
                "limit": 50
            },
            timeout=10,
        )

        data = response.json()

        if not data.get("ok"):
            return offset

        for update in data.get("result", []):
            update_id = update.get("update_id")
            if update_id is not None:
                offset = update_id + 1
                save_offset(offset)

            post = update.get("channel_post") or update.get("edited_channel_post")
            if not post:
                continue

            chat_id = str(post.get("chat", {}).get("id", ""))
            if chat_id != str(CHANNEL_STATS):
                continue

            text = post.get("text", "")
            parsed = parse_cards_from_message(text)

            if not parsed:
                continue

            games_cache[parsed["game_number"]] = text
            print(
                f"💾 CHANNEL_STATS -> #{parsed['game_number']} | "
                f"карты={parsed['cards']}",
                flush=True
            )

    except Exception as e:
        print(f"⚠️ Updates error: {e}", flush=True)

    return offset


# ============================================================
# OFFSET
# ============================================================

def load_offset():
    try:
        if os.path.exists(OFFSET_FILE):
            with open(OFFSET_FILE, "r", encoding="utf-8") as f:
                return int(f.read().strip())
    except Exception:
        pass
    return 0


def save_offset(offset):
    try:
        with open(OFFSET_FILE, "w", encoding="utf-8") as f:
            f.write(str(offset))
    except Exception:
        pass


# ============================================================
# API
# ============================================================

def get_active_games():
    url = (
        f"{BASE_URL}"
        f"/service-api/main-live-feed/v3/"
        f"games1x2"
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
        response = SESSION.get(url, timeout=10)

        if response.status_code != 200:
            return []

        data = response.json()

        games = data if isinstance(data, list) else data.get("Value", [])
        result = []

        for game in games:
            if not isinstance(game, dict):
                continue

            league = game.get("liga", {})
            if str(league.get("id", "")) != str(LEAGUE_ID):
                continue

            if game.get("id"):
                result.append(game)

        return result

    except Exception as e:
        print(f"❌ API games: {e}", flush=True)
        return []


def get_game_data(game_id):
    url = (
        f"{BASE_URL}"
        f"/service-api/LiveFeed/GetGameZip"
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
        response = SESSION.get(url, timeout=7)
        if response.status_code == 200:
            return response.json()
    except Exception:
        pass

    return None


# ============================================================
# API PARSER
# ============================================================

def extract_card(obj):
    if not isinstance(obj, dict):
        return None

    rank = None
    suit = None

    rank_keys = {"rank", "value", "v", "cardvalue", "card_value", "nominal"}
    suit_keys = {"suit", "s", "card_suit", "cardsuit", "mast"}

    for key, value in obj.items():
        key = str(key).lower()

        if key in rank_keys:
            rank = normalize_rank(value) or rank

        if key in suit_keys:
            suit = normalize_suit(value) or suit

    if rank and suit:
        return {"rank": rank, "suit": f"{suit}\ufe0f"}

    return None


def classify_context(key):
    key = str(key).lower()

    if key in {"p", "p1", "p2", "p3", "p4", "pcards", "playercards"}:
        return "player"
    if key.startswith("player") or "playercard" in key:
        return "player"
    if key in {"d", "d1", "d2", "d3", "d4", "dcards", "dealercards"}:
        return "dealer"
    if key.startswith("dealer") or "dealercard" in key:
        return "dealer"

    return None


def find_cards(obj, context=None, player=None, dealer=None):
    if player is None:
        player = []
    if dealer is None:
        dealer = []

    if isinstance(obj, dict):
        card = extract_card(obj)
        if card:
            if context == "player":
                player.append(card)
            elif context == "dealer":
                dealer.append(card)

        for key, value in obj.items():
            new_context = classify_context(key) or context
            find_cards(value, new_context, player, dealer)

    elif isinstance(obj, list):
        for item in obj:
            find_cards(item, context, player, dealer)

    return player, dealer


def unique_cards(cards):
    result = []
    seen = set()

    for card in cards:
        text = card_text(card)
        if not text or text in seen:
            continue

        seen.add(text)
        result.append({
            "rank": normalize_rank(card.get("rank")),
            "suit": f"{normalize_suit(card.get('suit'))}\ufe0f",
        })

    return result


def parse_game_data(game_id, raw):
    if not raw:
        return None

    player, dealer = find_cards(raw)
    player = unique_cards(player)
    dealer = unique_cards(dealer)

    if not player and not dealer:
        return None

    sequence = []
    pos = 1

    for i in range(max(len(player), len(dealer))):
        if i < len(player):
            sequence.append({
                "position": pos,
                "who": "P",
                "rank": player[i]["rank"],
                "suit": player[i]["suit"],
            })
            pos += 1

        if i < len(dealer):
            sequence.append({
                "position": pos,
                "who": "D",
                "rank": dealer[i]["rank"],
                "suit": dealer[i]["suit"],
            })
            pos += 1

    now = datetime.now(MOSCOW_TZ)

    return {
        "game_id": str(game_id),
        "timestamp_msk": now.strftime("%H:%M:%S.%f")[:-3],
        "player_cards": player,
        "dealer_cards": dealer,
        "sequence": sequence,
        "total_cards": len(player) + len(dealer),
        "first_player_card": player[0] if player else None,
        "id_last_digit": str(game_id)[-1],
        "id_last_two": str(game_id)[-2:],
    }


def add_or_update_game(game):
    global history

    game_id = str(game.get("game_id", ""))
    if not game_id:
        return False

    index = find_game_index(game_id)

    if index >= 0:
        old = history[index]
        old_count = len(old.get("player_cards", [])) + len(old.get("dealer_cards", []))
        new_count = len(game.get("player_cards", [])) + len(game.get("dealer_cards", []))

        if new_count >= old_count:
            history[index] = game
            save_json(DATA_FILE, history)

        return False

    history.append(game)
    history = history[-MAX_HISTORY_GAMES:]
    save_json(DATA_FILE, history)

    print(
        f"💾 Новая игра | ID={game_id} | "
        f"P1={card_text(game.get('first_player_card'))} | "
        f"История={len(history)}",
        flush=True
    )

    return True


# ============================================================
# PROCESS GAME
# ============================================================

def process_game(active_game):
    game_id = str(active_game.get("id", ""))
    if not game_id:
        return

    # Если уже есть прогноз на эту игру - пропускаем
    if prediction_exists(game_id):
        return

    print("\n══════════════════════════════════", flush=True)
    print(f"🆕 НОВАЯ ИГРА / ЛОББИ | ID={game_id}", flush=True)

    current_number = get_game_number()
    target_number = get_lobby_game_number()

    print(f"🕐 Текущий номер: #N{current_number}", flush=True)
    print(f"🎯 Lobby является следующей игрой: #N{target_number}", flush=True)

    prediction = create_prediction(game_id, target_number)

    if prediction:
        message = make_prediction_message(prediction)
        prediction["original_text"] = message
        message_id = telegram_send(message)

        if message_id:
            prediction["message_id"] = message_id
            save_json(PREDICTIONS_FILE, predictions)
            print(f"📤 ПРОГНОЗ ОТПРАВЛЕН | #N{prediction['target_number']}", flush=True)

    # Всегда пытаемся получить карты для истории
    raw = get_game_data(game_id)
    if raw:
        parsed = parse_game_data(game_id, raw)
        if parsed:
            add_or_update_game(parsed)


# ============================================================
# MAIN
# ============================================================

def main():
    global history, predictions

    history = load_history()
    predictions = load_predictions()
    offset = load_offset()

    print("\n==================================================", flush=True)
    print("🚀 OLD BOT — HYBRID + PATTERN SCANNER", flush=True)
    print("==================================================", flush=True)
    print(f"📚 История: {len(history)} игр", flush=True)
    print("🤖 Методы: MS + ID1 + ID2 + FREQ + PATTERN SCANNER", flush=True)
    print(f"🎯 Мин. вероятность: {MIN_FORECAST_PROBABILITY:.0%}", flush=True)
    print("🃏 Режим: TOP-2", flush=True)
    print(f"📈 Догон: 0 → {DOGON_GAMES}", flush=True)
    print("📡 Прогноз: на КАЖДУЮ Lobby", flush=True)
    print("📊 Проверка: CHANNEL_STATS", flush=True)
    print("==================================================\n", flush=True)

    while True:
        started = time.time()

        try:
            # 1. Ищем новые Lobby
            games = get_active_games()
            if games:
                print(f"📡 API игр: {len(games)}", flush=True)

            for game in games:
                try:
                    process_game(game)
                except Exception as e:
                    print(f"❌ Ошибка игры: {e}", flush=True)

            # 2. Читаем канал статистики
            offset = process_updates(offset)

            # 3. Проверяем прогнозы
            check_predictions()

            # 4. Ограничиваем файл прогнозов
            if len(predictions) > 1000:
                predictions[:] = predictions[-1000:]
                save_json(PREDICTIONS_FILE, predictions)

            elapsed = time.time() - started
            time.sleep(max(0.1, POLL_INTERVAL - elapsed))

        except KeyboardInterrupt:
            print("🛑 Бот остановлен", flush=True)
            break

        except Exception as e:
            print(f"❌ Критическая ошибка: {e}", flush=True)
            time.sleep(3)


if __name__ == "__main__":
    main()