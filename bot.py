import os
import sys
import json
import time
import requests
import pytz
import re

from datetime import datetime


# ==================================================
# ENV
# ==================================================

BOT_TOKEN = os.getenv("BOT_TOKEN")
if not BOT_TOKEN:
    BOT_TOKEN = os.getenv("BOT_TOKEN_PROGNOZ")

CHANNEL_PROGNOZ = os.getenv("CHAT_ID_21")
if not CHANNEL_PROGNOZ:
    CHANNEL_PROGNOZ = os.getenv("CHANNEL_PROGNOZ")

if not BOT_TOKEN:
    print("❌ BOT_TOKEN не задан!", flush=True)
    sys.exit(1)

if not CHANNEL_PROGNOZ:
    print("❌ CHANNEL_PROGNOZ не задан!", flush=True)
    sys.exit(1)


# ==================================================
# CONFIG
# ==================================================

MOSCOW_TZ = pytz.timezone("Europe/Moscow")

# ФАЙЛЫ
DATA_FILE = "twentyone_data_full.json"
PREDICTIONS_FILE = "twentyone_predictions.json"

# Храним только последние 100 игр
MAX_HISTORY_GAMES = 100

# ПРОГНОЗ
PREDICTION_OFFSET = 11
DOGON_GAMES = 4

# API
BASE_URL = "https://1xlite-36553.pro"

BACCARAT_LEAGUE_ID = 2050671

GAMES_URL = (
    f"{BASE_URL}/service-api/main-live-feed/v3/games1x2"
    "?cfView=3"
    "&count=40"
    "&fcountry=190"
    "&gr=415"
    "&grMode=4"
    "&lng=ru"
    "&ref=7"
    "&selectedMs=1.146.1643503,10.146.1643503"
)

GAME_URL = (
    f"{BASE_URL}/LiveFeed/GetGameZip"
)

POLL_INTERVAL = 2.0

TELEGRAM_API = f"https://api.telegram.org/bot{BOT_TOKEN}"


# ==================================================
# ЦЕЛЕВЫЕ РАНГИ
# ==================================================

SOURCE_RANKS = {"J", "Q", "K", "A"}


# ==================================================
# ЗЕРКАЛЬНЫЕ РАНГИ
# ==================================================

RANK_MIRROR = {
    "J": "K",
    "K": "J",
    "Q": "A",
    "A": "Q"
}


# ==================================================
# ЗЕРКАЛЬНЫЕ МАСТИ
# ==================================================

SUIT_MIRROR = {
    "♣": "♥",
    "♥": "♣",
    "♠": "♦",
    "♦": "♠"
}


# ==================================================
# HTTP
# ==================================================

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 "
        "(Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36"
    ),
    "Accept": "application/json, text/plain, */*"
}

SESSION = requests.Session()
SESSION.headers.update(HEADERS)


# ==================================================
# GLOBALS
# ==================================================

history_data = []
predictions = []

last_seen_game_ids = set()
last_prediction_time = 0


# ==================================================
# JSON
# ==================================================

def load_json_file(filename, default):
    try:

        if not os.path.exists(filename):
            return default

        with open(filename, "r", encoding="utf-8") as f:
            return json.load(f)

    except Exception as e:

        print(
            f"⚠️ Ошибка чтения {filename}: {e}",
            flush=True
        )

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

        print(
            f"⚠️ Ошибка сохранения {filename}: {e}",
            flush=True
        )

        try:

            if os.path.exists(tmp):
                os.remove(tmp)

        except Exception:
            pass

        return False


# ==================================================
# LOAD HISTORY
# ==================================================

def load_history():

    data = load_json_file(
        DATA_FILE,
        []
    )

    if not isinstance(data, list):
        return []

    cleaned = []

    for item in data:

        if not isinstance(item, dict):
            continue

        if not item.get("game_id"):
            continue

        cleaned.append(item)

    cleaned.sort(
        key=lambda x: int(
            x.get("game_number", 0)
        )
    )

    if len(cleaned) > MAX_HISTORY_GAMES:
        cleaned = cleaned[-MAX_HISTORY_GAMES:]

    return cleaned


# ==================================================
# LOAD PREDICTIONS
# ==================================================

def load_predictions():

    data = load_json_file(
        PREDICTIONS_FILE,
        []
    )

    if not isinstance(data, list):
        return []

    return data


# ==================================================
# NORMALIZE
# ==================================================

def normalize_suit(suit):

    if not suit:
        return None

    suit = str(suit)

    suit = suit.replace(
        "\ufe0f",
        ""
    )

    mapping = {
        "♠": "♠",
        "♣": "♣",
        "♦": "♦",
        "♥": "♥"
    }

    return mapping.get(suit)


def normalize_rank(rank):

    if not rank:
        return None

    rank = str(rank).upper().strip()

    rank = rank.replace(
        "А",
        "A"
    )

    allowed = {
        "2", "3", "4", "5",
        "6", "7", "8", "9",
        "10", "J", "Q", "K", "A"
    }

    if rank in allowed:
        return rank

    return None


def normalize_card(rank, suit):

    rank = normalize_rank(rank)
    suit = normalize_suit(suit)

    if not rank or not suit:
        return None

    return f"{rank}{suit}\ufe0f"


# ==================================================
# GAME NUMBER
# ==================================================

def get_next_game_number():

    global history_data

    if not history_data:
        return 1

    numbers = []

    for item in history_data:

        try:
            numbers.append(
                int(item.get("game_number", 0))
            )

        except Exception:
            pass

    if not numbers:
        return 1

    return max(numbers) + 1


# ==================================================
# ADD GAME OFFSET
# ==================================================

def add_game_offset(number, offset):

    try:
        return int(number) + int(offset)

    except Exception:
        return None


# ==================================================
# TELEGRAM SEND
# ==================================================

def telegram_send(text):

    try:

        response = SESSION.post(
            f"{TELEGRAM_API}/sendMessage",
            json={
                "chat_id": CHANNEL_PROGNOZ,
                "text": text,
                "parse_mode": "HTML",
                "disable_web_page_preview": True
            },
            timeout=10
        )

        data = response.json()

        if data.get("ok"):

            return data[
                "result"
            ].get("message_id")

        print(
            f"❌ Telegram send: {data}",
            flush=True
        )

    except Exception as e:

        print(
            f"❌ Telegram send error: {e}",
            flush=True
        )

    return None


# ==================================================
# TELEGRAM EDIT
# ==================================================

def telegram_edit(message_id, text):

    if not message_id:
        return False

    try:

        response = SESSION.post(
            f"{TELEGRAM_API}/editMessageText",
            json={
                "chat_id": CHANNEL_PROGNOZ,
                "message_id": message_id,
                "text": text,
                "parse_mode": "HTML"
            },
            timeout=10
        )

        data = response.json()

        if not data.get("ok"):

            print(
                f"⚠️ Telegram edit: {data}",
                flush=True
            )

        return bool(data.get("ok"))

    except Exception as e:

        print(
            f"❌ Telegram edit error: {e}",
            flush=True
        )

        return False


# ==================================================
# GET LIVE GAMES
# ==================================================

def get_live_games():

    try:

        response = SESSION.get(
            GAMES_URL,
            timeout=10
        )

        data = response.json()

        games = []

        if isinstance(data, dict):

            for key in [
                "Value",
                "value",
                "Games",
                "games",
                "Items",
                "items"
            ]:

                value = data.get(key)

                if isinstance(value, list):
                    games = value
                    break

        elif isinstance(data, list):
            games = data

        return games

    except Exception as e:

        print(
            f"❌ Ошибка получения списка игр: {e}",
            flush=True
        )

        return []


# ==================================================
# EXTRACT GAME ID
# ==================================================

def extract_game_id(game):

    possible_keys = [
        "I",
        "id",
        "ID",
        "gameId",
        "GameId"
    ]

    for key in possible_keys:

        value = game.get(key)

        if value is not None:
            return str(value)

    return None


# ==================================================
# EXTRACT LEAGUE
# ==================================================

def extract_league_id(game):

    possible_keys = [
        "LI",
        "leagueId",
        "LeagueId",
        "L"
    ]

    for key in possible_keys:

        value = game.get(key)

        if value is not None:

            try:
                return int(value)
            except Exception:
                pass

    return None


# ==================================================
# GET GAME DETAILS
# ==================================================

def get_game_details(game_id):

    try:

        response = SESSION.get(
            GAME_URL,
            params={
                "id": game_id,
                "isSubGames": "true",
                "GroupEvents": "true",
                "countevents": 250,
                "grMode": 4,
                "partner": 7,
                "topGroups": "",
                "country": 190,
                "marketType": 1,
                "isNewBuilder": "true"
            },
            timeout=10
        )

        return response.json()

    except Exception as e:

        print(
            f"❌ Ошибка GetGameZip {game_id}: {e}",
            flush=True
        )

        return None


# ==================================================
# FIND CARDS RECURSIVELY
# ==================================================

def find_cards_recursive(obj, found=None):

    if found is None:
        found = []

    if isinstance(obj, dict):

        rank = None
        suit = None

        for key in [
            "rank",
            "Rank",
            "R"
        ]:

            if key in obj:
                rank = obj[key]
                break

        for key in [
            "suit",
            "Suit",
            "S"
        ]:

            if key in obj:
                suit = obj[key]
                break

        if rank and suit:

            card = normalize_card(
                rank,
                suit
            )

            if card:
                found.append(card)

        for value in obj.values():
            find_cards_recursive(
                value,
                found
            )

    elif isinstance(obj, list):

        for item in obj:
            find_cards_recursive(
                item,
                found
            )

    return found


# ==================================================
# PARSE CARD STRING
# ==================================================

def parse_cards_from_string(text):

    if not text:
        return []

    text = str(text)

    cards = re.findall(
        r"(10|[2-9AJQK])([♠♣♦♥])",
        text,
        flags=re.IGNORECASE
    )

    result = []

    for rank, suit in cards:

        card = normalize_card(
            rank,
            suit
        )

        if card:
            result.append(card)

    return result


# ==================================================
# EXTRACT SCORE
# ==================================================

def extract_score(obj):

    if isinstance(obj, (int, float)):
        return int(obj)

    if isinstance(obj, str):

        match = re.search(
            r"\b(\d{1,2})\b",
            obj
        )

        if match:
            return int(match.group(1))

    return None


# ==================================================
# PARSE GAME DATA
#
# Поддерживает структуру старого API,
# где P1/P2 содержат данные игрока/дилера
# ==================================================

def parse_api_game(game_id, raw_data):

    if not raw_data:
        return None

    data = raw_data

    # Иногда ответ лежит внутри Value
    if isinstance(data, dict):

        for key in ["Value", "value"]:

            if isinstance(data.get(key), dict):
                data = data[key]
                break

    if not isinstance(data, dict):
        return None

    player_cards = []
    dealer_cards = []

    player_score = None
    dealer_score = None

    # ----------------------------------------------
    # ИЩЕМ P1 / P2
    # ----------------------------------------------

    p1 = None
    p2 = None

    def find_p1_p2(obj):

        nonlocal p1
        nonlocal p2

        if isinstance(obj, dict):

            if p1 is None and "P1" in obj:
                p1 = obj.get("P1")

            if p2 is None and "P2" in obj:
                p2 = obj.get("P2")

            for value in obj.values():
                find_p1_p2(value)

        elif isinstance(obj, list):

            for item in obj:
                find_p1_p2(item)

    find_p1_p2(data)

    # ----------------------------------------------
    # ПАРСИМ P1
    # ----------------------------------------------

    if p1 is not None:

        if isinstance(p1, str):

            player_cards = parse_cards_from_string(
                p1
            )

        elif isinstance(p1, dict):

            for key in [
                "cards",
                "Cards",
                "C",
                "SC",
                "S"
            ]:

                value = p1.get(key)

                if value:

                    if isinstance(value, str):
                        player_cards.extend(
                            parse_cards_from_string(
                                value
                            )
                        )
                    else:
                        player_cards.extend(
                            find_cards_recursive(
                                value
                            )
                        )

            for key in [
                "score",
                "Score",
                "points",
                "Points",
                "value",
                "V"
            ]:

                if key in p1:

                    score = extract_score(
                        p1[key]
                    )

                    if score is not None:
                        player_score = score
                        break

    # ----------------------------------------------
    # ПАРСИМ P2
    # ----------------------------------------------

    if p2 is not None:

        if isinstance(p2, str):

            dealer_cards = parse_cards_from_string(
                p2
            )

        elif isinstance(p2, dict):

            for key in [
                "cards",
                "Cards",
                "C",
                "SC",
                "S"
            ]:

                value = p2.get(key)

                if value:

                    if isinstance(value, str):
                        dealer_cards.extend(
                            parse_cards_from_string(
                                value
                            )
                        )
                    else:
                        dealer_cards.extend(
                            find_cards_recursive(
                                value
                            )
                        )

            for key in [
                "score",
                "Score",
                "points",
                "Points",
                "value",
                "V"
            ]:

                if key in p2:

                    score = extract_score(
                        p2[key]
                    )

                    if score is not None:
                        dealer_score = score
                        break

    # ----------------------------------------------
    # FALLBACK:
    # ИЩЕМ КАРТЫ ВО ВСЁМ JSON
    # ----------------------------------------------

    if not player_cards and not dealer_cards:

        all_cards = find_cards_recursive(
            data
        )

        # Если API отдаёт последовательность
        # без P1/P2 — пока не можем точно
        # разделить игрока и дилера
        if all_cards:
            print(
                f"⚠️ {game_id}: найдены карты, "
                f"но не удалось разделить P1/P2",
                flush=True
            )

    # ----------------------------------------------
    # FALLBACK SCORES
    # ----------------------------------------------

    if player_score is None:

        for key in [
            "P1Score",
            "p1Score",
            "playerScore"
        ]:

            if key in data:

                player_score = extract_score(
                    data[key]
                )

                if player_score is not None:
                    break

    if dealer_score is None:

        for key in [
            "P2Score",
            "p2Score",
            "dealerScore"
        ]:

            if key in data:

                dealer_score = extract_score(
                    data[key]
                )

                if dealer_score is not None:
                    break

    # ----------------------------------------------
    # ПРОВЕРКА
    # ----------------------------------------------

    if not player_cards:
        return None

    if player_score is None:
        return None

    if dealer_score is None:
        return None

    return {
        "game_id": str(game_id),
        "player_score": int(player_score),
        "dealer_score": int(dealer_score),
        "player_cards": player_cards,
        "dealer_cards": dealer_cards,
        "raw_received_at": datetime.now(
            MOSCOW_TZ
        ).isoformat()
    }


# ==================================================
# SAVE NEW GAME
# ==================================================

def save_new_game(game):

    global history_data

    game_id = str(
        game.get("game_id")
    )

    # Уже существует?
    for item in history_data:

        if str(item.get("game_id")) == game_id:
            return None

    # Новый последовательный номер
    game_number = get_next_game_number()

    game["game_number"] = game_number

    history_data.append(game)

    # Только последние 100
    history_data.sort(
        key=lambda x: int(
            x.get("game_number", 0)
        )
    )

    if len(history_data) > MAX_HISTORY_GAMES:
        history_data = history_data[
            -MAX_HISTORY_GAMES:
        ]

    atomic_save_json(
        DATA_FILE,
        history_data
    )

    print(
        f"\n💾 НОВАЯ ИГРА СОХРАНЕНА",
        flush=True
    )

    print(
        f"🎮 #N{game_number}",
        flush=True
    )

    print(
        f"🆔 ID: {game_id}",
        flush=True
    )

    print(
        f"👤 Игрок: "
        f"{game['player_score']} "
        f"{game['player_cards']}",
        flush=True
    )

    print(
        f"🎩 Дилер: "
        f"{game['dealer_score']} "
        f"{game['dealer_cards']}",
        flush=True
    )

    return game


# ==================================================
# BUILD PATTERN PREDICTION
# ==================================================

def build_pattern_prediction(game):

    if not game:
        return None

    player_score = game.get(
        "player_score"
    )

    dealer_score = game.get(
        "dealer_score"
    )

    # ----------------------------------------------
    # ОЧКИ ОБЯЗАТЕЛЬНЫ
    # ----------------------------------------------

    if player_score is None:
        return None

    if dealer_score is None:
        return None

    # ----------------------------------------------
    # У ИГРОКА СТРОГО МЕНЬШЕ 21
    # ----------------------------------------------

    if player_score >= 21:

        print(
            f"🚫 #N{game['game_number']} "
            f"пропуск: игрок "
            f"{player_score} очков (нужно <21)",
            flush=True
        )

        return None

    # ----------------------------------------------
    # У ДИЛЕРА НЕ ДОЛЖНО БЫТЬ 21
    # ----------------------------------------------

    if dealer_score == 21:

        print(
            f"🚫 #N{game['game_number']} "
            f"пропуск: дилер 21",
            flush=True
        )

        return None

    # ----------------------------------------------
    # НИЧЬЯ
    # ----------------------------------------------

    if player_score == dealer_score:

        print(
            f"🚫 #N{game['game_number']} "
            f"пропуск: ничья "
            f"{player_score}:{dealer_score}",
            flush=True
        )

        return None

    # ----------------------------------------------
    # КАРТЫ ИГРОКА
    # ----------------------------------------------

    player_cards = game.get(
        "player_cards",
        []
    )

    if not player_cards:
        return None

    first_card = player_cards[0]

    match = re.match(
        r"(10|[2-9AJQK])([♠♣♦♥])",
        first_card
    )

    if not match:
        return None

    source_rank = normalize_rank(
        match.group(1)
    )

    source_suit = normalize_suit(
        match.group(2)
    )

    if not source_rank:
        return None

    if not source_suit:
        return None

    # ----------------------------------------------
    # ТОЛЬКО J Q K A
    # ----------------------------------------------

    if source_rank not in SOURCE_RANKS:

        print(
            f"⏭️ #N{game['game_number']} "
            f"первая карта {first_card} "
            f"не J/Q/K/A",
            flush=True
        )

        return None

    # ----------------------------------------------
    # ЗЕРКАЛЬНЫЙ РАНГ
    # ----------------------------------------------

    target_rank = RANK_MIRROR.get(
        source_rank
    )

    if not target_rank:
        return None

    # ----------------------------------------------
    # ЗЕРКАЛЬНАЯ МАСТЬ
    # ----------------------------------------------

    mirror_suit = SUIT_MIRROR.get(
        source_suit
    )

    if not mirror_suit:
        return None

    # ----------------------------------------------
    # ДВЕ КАРТЫ
    # ----------------------------------------------

    card_original = normalize_card(
        target_rank,
        source_suit
    )

    card_mirror = normalize_card(
        target_rank,
        mirror_suit
    )

    predicted_cards = []

    if card_original:
        predicted_cards.append(
            card_original
        )

    if (
        card_mirror
        and card_mirror not in predicted_cards
    ):
        predicted_cards.append(
            card_mirror
        )

    if not predicted_cards:
        return None

    # ----------------------------------------------
    # ЦЕЛЬ +11
    # ----------------------------------------------

    target_number = add_game_offset(
        game["game_number"],
        PREDICTION_OFFSET
    )

    return {
        "source_number":
            game["game_number"],

        "source_game_id":
            game["game_id"],

        "source_card":
            first_card,

        "source_rank":
            source_rank,

        "source_suit":
            source_suit,

        "target_rank":
            target_rank,

        "target_number":
            target_number,

        "predicted_cards":
            predicted_cards
    }


# ==================================================
# CHECK DUPLICATE PREDICTION
# ==================================================

def prediction_exists(source_game_id):

    for entry in predictions:

        if str(
            entry.get("source_game_id")
        ) == str(source_game_id):

            return True

    return False


# ==================================================
# MESSAGE
# ==================================================

def make_prediction_message(entry):

    cards_text = " + ".join(
        entry.get(
            "predicted_cards",
            []
        )
    )

    return (
        f"🎯 <b>Игра: "
        f"#N{entry['target_number']}</b>\n\n"

        f"🃏 <b>{cards_text}</b>\n\n"

        f"📊 Паттерн: первая карта игрока "
        f"{entry['source_card']}\n"

        f"🔗 Источник: "
        f"#N{entry['source_number']}\n"

        f"⏩ Смещение: "
        f"+{PREDICTION_OFFSET} игр"
    )


# ==================================================
# CREATE PREDICTION
# ==================================================

def create_pattern_prediction(game):

    global predictions
    global last_prediction_time

    if prediction_exists(
        game.get("game_id")
    ):
        return None

    pattern = build_pattern_prediction(
        game
    )

    if not pattern:
        return None

    now = time.time()

    if now - last_prediction_time < 1:
        return None

    entry = {
        "source_number":
            pattern["source_number"],

        "source_game_id":
            pattern["source_game_id"],

        "source_card":
            pattern["source_card"],

        "source_rank":
            pattern["source_rank"],

        "source_suit":
            pattern["source_suit"],

        "target_rank":
            pattern["target_rank"],

        "target_number":
            pattern["target_number"],

        "predicted_cards":
            pattern["predicted_cards"],

        "status": "pending",

        "created_at":
            datetime.now(
                MOSCOW_TZ
            ).isoformat(),

        "message_id": None,

        "original_text": "",

        "result_game": None,

        "found_card": None,

        "current_dogon": 0
    }

    predictions.append(entry)

    message = make_prediction_message(
        entry
    )

    entry["original_text"] = message

    atomic_save_json(
        PREDICTIONS_FILE,
        predictions
    )

    message_id = telegram_send(
        message
    )

    if message_id:

        entry["message_id"] = message_id

        atomic_save_json(
            PREDICTIONS_FILE,
            predictions
        )

    last_prediction_time = now

    print(
        "\n══════════════════════════════",
        flush=True
    )

    print(
        "🔮 НОВЫЙ ПРОГНОЗ",
        flush=True
    )

    print(
        f"📥 Источник: "
        f"#N{entry['source_number']}",
        flush=True
    )

    print(
        f"🎯 Цель: "
        f"#N{entry['target_number']}",
        flush=True
    )

    print(
        f"🃏 Прогноз: "
        f"{' + '.join(entry['predicted_cards'])}",
        flush=True
    )

    print(
        "══════════════════════════════\n",
        flush=True
    )

    return entry


# ==================================================
# UPDATE MESSAGE
# ==================================================

def update_prediction_status(
    entry,
    success,
    found=None
):

    message_id = entry.get(
        "message_id"
    )

    original_text = entry.get(
        "original_text",
        ""
    )

    if not message_id:
        return

    if not original_text:
        return

    lines = original_text.split("\n")

    target = entry.get(
        "target_number"
    )

    if success:

        lines[0] = (
            f"🎯 <b>Игра: "
            f"#N{target} ✅</b>"
        )

        lines.append("")

        lines.append(
            f"✅ ЗАШЛО: "
            f"#N{found['num']}"
        )

        lines.append(
            f"🃏 Выпало: "
            f"{found['card']}"
        )

        lines.append(
            f"🔁 Догон: "
            f"{found['dogon']}"
        )

    else:

        lines[0] = (
            f"🎯 <b>Игра: "
            f"#N{target} ❌</b>"
        )

        lines.append("")

        lines.append(
            f"❌ Не зашло за "
            f"{DOGON_GAMES + 1} игр"
        )

    new_text = "\n".join(lines)

    telegram_edit(
        message_id,
        new_text
    )


# ==================================================
# FIND GAME BY NUMBER
# ==================================================

def get_game_by_number(number):

    for game in history_data:

        if int(
            game.get("game_number", 0)
        ) == int(number):

            return game

    return None


# ==================================================
# CHECK PREDICTIONS
# ==================================================

def check_predictions():

    global predictions

    changed = False

    pending = [
        x for x in predictions
        if x.get("status") == "pending"
    ]

    for entry in pending:

        target = entry.get(
            "target_number"
        )

        predicted_cards = entry.get(
            "predicted_cards",
            []
        )

        if not target:
            continue

        if not predicted_cards:
            continue

        found = None

        all_available = True

        # ------------------------------------------
        # ОСНОВНАЯ + ДОГОНЫ
        # ------------------------------------------

        for dogon in range(
            DOGON_GAMES + 1
        ):

            check_number = (
                add_game_offset(
                    target,
                    dogon
                )
            )

            game = get_game_by_number(
                check_number
            )

            if not game:

                all_available = False
                break

            actual_cards = []

            for card in game.get(
                "player_cards",
                []
            ):
                if card not in actual_cards:
                    actual_cards.append(card)

            for card in game.get(
                "dealer_cards",
                []
            ):
                if card not in actual_cards:
                    actual_cards.append(card)

            for predicted in predicted_cards:

                if predicted in actual_cards:

                    found = {
                        "num": check_number,
                        "dogon": dogon,
                        "card": predicted
                    }

                    break

            if found:
                break

        # ------------------------------------------
        # WIN
        # ------------------------------------------

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
                f"✅ ПРОГНОЗ ЗАШЁЛ | "
                f"Цель #N{target} | "
                f"Результат #N{found['num']} | "
                f"{found['card']}",
                flush=True
            )

            update_prediction_status(
                entry,
                True,
                found
            )

            continue

        # ------------------------------------------
        # ЕЩЁ ЖДЁМ ИГРЫ
        # ------------------------------------------

        if not all_available:
            continue

        # ------------------------------------------
        # LOSE
        # ------------------------------------------

        entry["status"] = "lose"

        entry["current_dogon"] = (
            DOGON_GAMES
        )

        changed = True

        print(
            f"❌ ПРОГНОЗ НЕ ЗАШЁЛ | "
            f"Цель #N{target}",
            flush=True
        )

        update_prediction_status(
            entry,
            False
        )

    if changed:

        atomic_save_json(
            PREDICTIONS_FILE,
            predictions
        )


# ==================================================
# CLEANUP PREDICTIONS
# ==================================================

def cleanup_predictions():

    global predictions

    if len(predictions) > 1000:

        predictions = predictions[-1000:]

        atomic_save_json(
            PREDICTIONS_FILE,
            predictions
        )


# ==================================================
# PROCESS API GAMES
# ==================================================

def process_api_games():

    global last_seen_game_ids

    games = get_live_games()

    if not games:
        return

    candidates = []

    for game in games:

        if not isinstance(game, dict):
            continue

        league_id = extract_league_id(
            game
        )

        # Если league ID найден — фильтруем
        if (
            league_id is not None
            and league_id != BACCARAT_LEAGUE_ID
        ):
            continue

        game_id = extract_game_id(
            game
        )

        if not game_id:
            continue

        candidates.append(
            game_id
        )

    # ----------------------------------------------
    # ОБРАБАТЫВАЕМ ИГРЫ
    # ----------------------------------------------

    for game_id in candidates:

        # Уже в истории?
        exists = False

        for item in history_data:

            if str(
                item.get("game_id")
            ) == str(game_id):

                exists = True
                break

        if exists:
            continue

        # Получаем детали
        raw_data = get_game_details(
            game_id
        )

        if not raw_data:
            continue

        parsed = parse_api_game(
            game_id,
            raw_data
        )

        if not parsed:
            continue

        # Сохраняем новую игру
        saved_game = save_new_game(
            parsed
        )

        if not saved_game:
            continue

        # Создаём прогноз
        create_pattern_prediction(
            saved_game
        )


# ==================================================
# MAIN
# ==================================================

def main():

    global history_data
    global predictions

    print()
    print("==================================================")
    print("🚀 OLD PATTERN API BOT")
    print("==================================================")
    print("📡 Источник: 1x API")
    print(
        f"💾 История: "
        f"последние {MAX_HISTORY_GAMES} игр"
    )
    print("🎯 Прогноз: +11 игр")
    print("🔁 Догоны: 4")
    print()
    print("🚫 Пропуск если:")
    print("   • Игрок >= 21")
    print("   • Дилер == 21")
    print("   • Ничья")
    print()
    print("🃏 Триггер: первая карта J/Q/K/A")
    print("🔄 Ранги: J↔K | Q↔A")
    print("🔄 Масти: ♣↔♥ | ♠↔♦")
    print("==================================================")
    print()

    # ----------------------------------------------
    # LOAD
    # ----------------------------------------------

    history_data = load_history()

    predictions = load_predictions()

    print(
        f"💾 Загружено игр: "
        f"{len(history_data)}",
        flush=True
    )

    print(
        f"📊 Загружено прогнозов: "
        f"{len(predictions)}",
        flush=True
    )

    if history_data:

        last = history_data[-1]

        print(
            f"📌 Последняя игра: "
            f"#N{last.get('game_number')} "
            f"| ID {last.get('game_id')}",
            flush=True
        )

    print()
    print("🤖 Бот запущен...")
    print()

    # ----------------------------------------------
    # LOOP
    # ----------------------------------------------

    while True:

        start = time.time()

        try:

            # 1. Получаем новые игры API
            process_api_games()

            # 2. Проверяем прогнозы
            check_predictions()

            # 3. Чистим прогнозы
            cleanup_predictions()

            elapsed = time.time() - start

            sleep_time = max(
                0.1,
                POLL_INTERVAL - elapsed
            )

            time.sleep(
                sleep_time
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


# ==================================================
# START
# ==================================================

if __name__ == "__main__":
    main()