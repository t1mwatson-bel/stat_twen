import os
import sys
import json
import time
import requests
import pytz
import re

from datetime import datetime

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

if not BOT_TOKEN or not CHANNEL_PROGNOZ:
    print("❌ Ошибка: BOT_TOKEN или CHANNEL_PROGNOZ не заданы!", flush=True)
    sys.exit(1)


# =====================================================================
# CONFIG
# =====================================================================

MOSCOW_TZ = pytz.timezone("Europe/Moscow")

PREDICTIONS_FILE = "twentyone_predictions.json"
OFFSET_FILE = "pattern_offset.txt"

POLL_INTERVAL = 2.0

# Количество игр для проверки после основной цели
DOGON_GAMES = 4

# Через сколько игр даётся прогноз
FORECAST_OFFSET = 11

# Запрещённые теги
FORBIDDEN_TAGS = {"G", "O", "X", "R"}

# Карты, которые могут быть первой картой игрока
SOURCE_RANKS = {"J", "Q", "K", "A"}

# Зеркальные ранги
RANK_MIRROR = {
    "J": "K",
    "K": "J",
    "Q": "A",
    "A": "Q",
}

# Зеркальные масти
SUIT_MIRROR = {
    "♣": "♥",
    "♥": "♣",
    "♠": "♦",
    "♦": "♠",
}

TELEGRAM_API = f"https://api.telegram.org/bot{BOT_TOKEN}"

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 "
        "(Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36"
    ),
    "Accept": "application/json, text/plain, */*",
}

SESSION = requests.Session()
SESSION.headers.update(HEADERS)


# =====================================================================
# GLOBALS
# =====================================================================

predictions = []
games_cache = {}

last_prediction_time = 0

# Защита от повторной обработки сообщений
processed_source_games = set()

# Минимальная пауза между прогнозами
PREDICTION_COOLDOWN_SECONDS = 1


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
# LOAD PREDICTIONS
# =====================================================================

def load_predictions():
    global processed_source_games

    data = load_json_file(PREDICTIONS_FILE, [])

    if not isinstance(data, list):
        data = []

    # Восстанавливаем защиту от повторной обработки
    for entry in data:
        if not isinstance(entry, dict):
            continue

        source_number = entry.get("source_number")
        source_id = entry.get("source_game_id")

        if source_number is not None:
            key = make_source_key(
                source_number,
                source_id
            )
            processed_source_games.add(key)

    return data


# =====================================================================
# GAME NUMBER
# =====================================================================

def add_game_offset(number, offset):
    """
    Старый механизм перехода через сутки.
    Если игра 1438 + 11 -> корректно перейдёт в начало.
    """

    return ((int(number) - 1 + int(offset)) % 1440) + 1


# =====================================================================
# CARD HELPERS
# =====================================================================

def normalize_card(rank, suit):
    """
    Возвращает карту в едином формате:
    A♣️
    """

    if not rank or not suit:
        return None

    rank = str(rank).upper().strip()
    suit = str(suit).replace("\ufe0f", "").strip()

    if rank not in {
        "2", "3", "4", "5",
        "6", "7", "8", "9",
        "10", "J", "Q", "K", "A"
    }:
        return None

    if suit not in {"♠", "♣", "♦", "♥"}:
        return None

    return f"{rank}{suit}\ufe0f"


def split_card(card):
    """
    A♣️ -> ("A", "♣")
    10♥️ -> ("10", "♥")
    """

    if not card:
        return None, None

    card = str(card).replace("\ufe0f", "")

    match = re.fullmatch(
        r"(10|[2-9AJQK])([♠♣♦♥])",
        card
    )

    if not match:
        return None, None

    return match.group(1), match.group(2)


# =====================================================================
# FORBIDDEN TAGS
# =====================================================================

def get_game_tags(text):
    """
    Достаёт именно хэштеги.

    Пример:
    #N977 ... #T32 #R #G #O

    Получим:
    {"R", "G", "O"}
    """

    if not text:
        return set()

    tags = set()

    found = re.findall(
        r"#([A-Za-zА-Яа-яЁё])\b",
        text.upper()
    )

    for tag in found:
        tag = tag.upper()

        # N и T — служебные части сообщения,
        # нас интересуют остальные одиночные теги
        if tag not in {"N", "T"}:
            tags.add(tag)

    return tags


def has_forbidden_tags(text):
    tags = get_game_tags(text)

    found_forbidden = tags & FORBIDDEN_TAGS

    return bool(found_forbidden), found_forbidden


# =====================================================================
# PARSE COMPLETED GAME
# =====================================================================

def parse_completed_game(text):
    """
    Полный парсер завершённой игры.

    Пример:

    #N1001. ✅20(Q♣J♥Q♥J♠10♥) - 27(7♣7♥K♦9♥) #T47

    Нам важно:
    - номер игры
    - карты игрока (левая часть)
    - карты дилера (правая часть)
    - теги
    - ID
    """

    if not text:
        return None

    # Игра должна быть завершённой
    if not re.search(r"[✅🔰]", text):
        return None

    number_match = re.search(
        r"#N(\d+)",
        text,
        re.IGNORECASE
    )

    if not number_match:
        return None

    game_number = int(number_match.group(1))

    # ID необязателен, но сохраняем
    id_match = re.search(
        r"\(ID:\s*(\d+)\)",
        text,
        re.IGNORECASE
    )

    game_id = id_match.group(1) if id_match else None

    # =================================================================
    # Ищем две группы карт:
    #
    # 20(Q♣J♥Q♥J♠10♥) - 27(7♣7♥K♦9♥)
    # =================================================================

    groups = re.findall(
        r"(?:[✅🔰]?\d+)\(([^)]*)\)",
        text
    )

    if len(groups) < 2:
        return None

    player_raw = groups[0]
    dealer_raw = groups[1]

    card_pattern = r"(10|[2-9AJQK])([♠♣♦♥])\ufe0f?"

    player_found = re.findall(
        card_pattern,
        player_raw
    )

    dealer_found = re.findall(
        card_pattern,
        dealer_raw
    )

    player_cards = [
        normalize_card(rank, suit)
        for rank, suit in player_found
    ]

    dealer_cards = [
        normalize_card(rank, suit)
        for rank, suit in dealer_found
    ]

    player_cards = [
        c for c in player_cards
        if c
    ]

    dealer_cards = [
        c for c in dealer_cards
        if c
    ]

    if not player_cards:
        return None

    tags = get_game_tags(text)

    return {
        "game_number": game_number,
        "game_id": game_id,
        "player_cards": player_cards,
        "dealer_cards": dealer_cards,
        "first_player_card": player_cards[0],
        "tags": list(tags),
        "raw_text": text,
    }


# =====================================================================
# OLD PARSER FOR RESULT CHECK
# НЕ МЕНЯЕМ ЛОГИКУ ПРОВЕРКИ РЕЗУЛЬТАТА
# =====================================================================

def parse_cards_from_message(text):
    """
    Используется для проверки результата прогноза.

    Оставляем принцип:
    - берём завершённую игру
    - собираем все карты
    - проверяем попадание прогнозируемой карты
    """

    if not text:
        return None

    if not re.search(r"[✅🔰]", text):
        return None

    match = re.search(
        r"#N(\d+)",
        text
    )

    if not match:
        return None

    game_number = int(match.group(1))

    found = re.findall(
        r"(10|[2-9AJQK])([♠♣♦♥])\ufe0f?",
        text
    )

    cards = []

    for rank, suit in found:
        card = normalize_card(rank, suit)

        if card:
            cards.append(card)

    # Убираем дубли, сохраняя порядок
    cards = list(dict.fromkeys(cards))

    return {
        "game_number": game_number,
        "cards": cards,
    }


# =====================================================================
# NEW PATTERN ENGINE
# =====================================================================

def build_pattern_prediction(source_game):
    """
    ОСНОВНАЯ НОВАЯ ЛОГИКА.

    Условия:

    1. Нет тегов G/O/X/R
    2. Первая карта игрока только J/Q/K/A
    3. Зеркалим ранг:
       J -> K
       K -> J
       Q -> A
       A -> Q
    4. Берём две масти:
       исходную
       + зеркальную
    5. Цель = игра + 11
    """

    if not source_game:
        return None

    source_number = source_game.get("game_number")
    source_id = source_game.get("game_id")

    if source_number is None:
        return None

    raw_text = source_game.get("raw_text", "")

    # ================================================================
    # 1. ПРОВЕРКА ЗАПРЕЩЁННЫХ ТЕГОВ
    # ================================================================

    forbidden, forbidden_tags = has_forbidden_tags(raw_text)

    if forbidden:
        print(
            f"⏭️ #{source_number} ПРОПУСК | "
            f"запрещённые теги: "
            f"{', '.join(sorted(forbidden_tags))}",
            flush=True
        )
        return None

    # ================================================================
    # 2. ПЕРВАЯ КАРТА ИГРОКА
    # ================================================================

    first_card = source_game.get("first_player_card")

    if not first_card:
        print(
            f"⏭️ #{source_number} ПРОПУСК | "
            f"нет первой карты игрока",
            flush=True
        )
        return None

    rank, suit = split_card(first_card)

    if not rank or not suit:
        return None

    # ================================================================
    # 3. ТОЛЬКО J/Q/K/A
    # ================================================================

    if rank not in SOURCE_RANKS:
        print(
            f"⏭️ #{source_number} ПРОПУСК | "
            f"первая карта {first_card}, "
            f"не J/Q/K/A",
            flush=True
        )
        return None

    # ================================================================
    # 4. ЗЕРКАЛЬНЫЙ РАНГ
    # ================================================================

    target_rank = RANK_MIRROR.get(rank)

    if not target_rank:
        return None

    # ================================================================
    # 5. ЗЕРКАЛЬНАЯ МАСТЬ
    # ================================================================

    mirror_suit = SUIT_MIRROR.get(suit)

    if not mirror_suit:
        return None

    # ================================================================
    # 6. ДВЕ ПРОГНОЗИРУЕМЫЕ КАРТЫ
    # ================================================================

    card_original_suit = normalize_card(
        target_rank,
        suit
    )

    card_mirror_suit = normalize_card(
        target_rank,
        mirror_suit
    )

    predicted_cards = [
        card_original_suit,
        card_mirror_suit
    ]

    predicted_cards = [
        card for card in predicted_cards
        if card
    ]

    if not predicted_cards:
        return None

    # ================================================================
    # 7. ЦЕЛЕВАЯ ИГРА +11
    # ================================================================

    target_number = add_game_offset(
        source_number,
        FORECAST_OFFSET
    )

    return {
        "source_number": source_number,
        "source_game_id": source_id,
        "source_card": first_card,
        "source_rank": rank,
        "source_suit": suit,

        "target_rank": target_rank,
        "mirror_suit": mirror_suit,

        "target_number": target_number,
        "predicted_cards": predicted_cards,

        "pattern": (
            f"{rank}{suit} -> "
            f"{target_rank}{suit} / "
            f"{target_rank}{mirror_suit}"
        )
    }


# =====================================================================
# SOURCE KEY
# =====================================================================

def make_source_key(source_number, source_game_id=None):
    """
    Уникальный ключ источника.

    Защищает от ситуации:
    Telegram прислал одно и то же сообщение повторно.
    """

    if source_game_id:
        return f"ID:{source_game_id}"

    return f"N:{source_number}"


# =====================================================================
# CHECK DUPLICATES
# =====================================================================

def prediction_exists_for_source(
    source_number,
    source_game_id=None
):
    key = make_source_key(
        source_number,
        source_game_id
    )

    if key in processed_source_games:
        return True

    for entry in predictions:

        if (
            entry.get("source_number") == source_number
            and
            str(entry.get("source_game_id") or "")
            == str(source_game_id or "")
        ):
            return True

    return False


def prediction_exists_for_target(target_number):
    """
    Дополнительная защита:
    не создаём два pending-прогноза
    на одну и ту же игру.
    """

    for entry in predictions:

        if (
            entry.get("target_number") == target_number
            and entry.get("status") == "pending"
        ):
            return True

    return False


# =====================================================================
# TELEGRAM
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

    except Exception as e:
        print(
            f"⚠️ Ошибка редактирования: {e}",
            flush=True
        )

        return False


# =====================================================================
# PREDICTION MESSAGE
# =====================================================================

def make_prediction_message(entry):

    source_number = entry["source_number"]
    target_number = entry["target_number"]

    source_card = entry["source_card"]

    predicted_cards = entry["predicted_cards"]

    card1 = (
        predicted_cards[0]
        if len(predicted_cards) > 0
        else "—"
    )

    card2 = (
        predicted_cards[1]
        if len(predicted_cards) > 1
        else "—"
    )

    text = (
        f"🎯 Игра: #N{target_number}\n"
        f"🃏 {card1}\n"
        f"🃏 {card2}"
    )

    return text


# =====================================================================
# CREATE PREDICTION
# =====================================================================

def create_pattern_prediction(source_game):

    global last_prediction_time
    global predictions
    global processed_source_games

    if not source_game:
        return None

    source_number = source_game.get("game_number")
    source_id = source_game.get("game_id")

    if source_number is None:
        return None

    # ================================================================
    # ЗАЩИТА ОТ ПОВТОРА ИСТОЧНИКА
    # ================================================================

    if prediction_exists_for_source(
        source_number,
        source_id
    ):
        print(
            f"⏭️ #{source_number} уже обработана ранее",
            flush=True
        )
        return None

    # ================================================================
    # СОЗДАЁМ ПАТТЕРН
    # ================================================================

    result = build_pattern_prediction(
        source_game
    )

    if not result:
        return None

    target_number = result["target_number"]

    # ================================================================
    # ЗАЩИТА ОТ ДВУХ ПРОГНОЗОВ НА ОДНУ ЦЕЛЬ
    # ================================================================

    if prediction_exists_for_target(
        target_number
    ):
        print(
            f"⏭️ На #N{target_number} "
            f"уже есть pending-прогноз",
            flush=True
        )

        # Источник всё равно помечаем обработанным,
        # чтобы не пытаться снова
        key = make_source_key(
            source_number,
            source_id
        )

        processed_source_games.add(key)

        return None

    # ================================================================
    # COOLDOWN
    # ================================================================

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

    # ================================================================
    # ЛОГ
    # ================================================================

    print(
        "\n"
        "══════════════════════════════════════",
        flush=True
    )

    print(
        "🧠 НОВЫЙ ПАТТЕРН НАЙДЕН",
        flush=True
    )

    print(
        f"📌 Источник: #N{source_number}",
        flush=True
    )

    print(
        f"🃏 Первая карта игрока: "
        f"{result['source_card']}",
        flush=True
    )

    print(
        f"🔄 Зеркальный ранг: "
        f"{result['target_rank']}",
        flush=True
    )

    print(
        f"🎯 Цель +{FORECAST_OFFSET}: "
        f"#N{target_number}",
        flush=True
    )

    print(
        f"🔮 Прогноз: "
        f"{' / '.join(result['predicted_cards'])}",
        flush=True
    )

    print(
        "══════════════════════════════════════",
        flush=True
    )

    # ================================================================
    # СОЗДАЁМ ЗАПИСЬ
    # ================================================================

    entry = {
        # Источник
        "source_number": source_number,
        "source_game_id": source_id,
        "source_card": result["source_card"],

        # Цель
        "target_number": target_number,

        # Прогноз
        "predicted_cards": result["predicted_cards"],

        # Информация о паттерне
        "pattern": result["pattern"],

        # Статус
        "status": "pending",

        # Догон
        "current_dogon": 0,

        # Время
        "created_at": datetime.now(
            MOSCOW_TZ
        ).isoformat(),

        # Telegram
        "message_id": None,
        "original_text": "",

        # Результат
        "result_game": None,
        "found_card": None
    }

    # Добавляем сразу
    predictions.append(entry)

    # Помечаем источник обработанным
    key = make_source_key(
        source_number,
        source_id
    )

    processed_source_games.add(key)

    # Сохраняем ДО отправки
    atomic_save_json(
        PREDICTIONS_FILE,
        predictions
    )

    last_prediction_time = now_ts

    return entry


# =====================================================================
# OFFSET
# =====================================================================

def get_offset():

    try:
        if os.path.exists(OFFSET_FILE):

            with open(
                OFFSET_FILE,
                "r",
                encoding="utf-8"
            ) as f:

                return int(
                    f.read().strip()
                )

    except Exception:
        pass

    return 0


def save_offset(offset):

    try:
        with open(
            OFFSET_FILE,
            "w",
            encoding="utf-8"
        ) as f:

            f.write(str(offset))

    except Exception:
        pass


# =====================================================================
# PROCESS TELEGRAM UPDATES
# =====================================================================

def process_telegram_updates(offset):

    global predictions
    global games_cache

    if not CHANNEL_STATS:
        return offset

    try:

        response = SESSION.get(
            f"{TELEGRAM_API}/getUpdates",
            params={
                "offset": offset,
                "timeout": 3,
                "limit": 50,
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

            # Берём новые и редактированные сообщения
            post = (
                update.get("channel_post")
                or update.get("edited_channel_post")
            )

            if not post:
                continue

            chat_id = str(
                post.get("chat", {}).get("id", "")
            )

            if chat_id != str(CHANNEL_STATS):
                continue

            text = post.get("text", "")

            if not text:
                continue

            # =========================================================
            # 1. ПАРСИМ ЗАВЕРШЁННУЮ ИГРУ
            # =========================================================

            completed_game = parse_completed_game(
                text
            )

            if not completed_game:
                continue

            game_number = completed_game[
                "game_number"
            ]

            # =========================================================
            # 2. СОХРАНЯЕМ В КЭШ ДЛЯ ПРОВЕРКИ РЕЗУЛЬТАТА
            # =========================================================

            parsed_result = parse_cards_from_message(
                text
            )

            if parsed_result:

                games_cache[
                    parsed_result["game_number"]
                ] = text

                print(
                    f"💾 КЭШ: "
                    f"#{parsed_result['game_number']} "
                    f"-> {parsed_result['cards']}",
                    flush=True
                )

            # =========================================================
            # 3. СОЗДАЁМ НОВЫЙ ПРОГНОЗ ПО ПАТТЕРНУ
            # =========================================================

            prediction = create_pattern_prediction(
                completed_game
            )

            if prediction:

                message = make_prediction_message(
                    prediction
                )

                prediction[
                    "original_text"
                ] = message

                message_id = telegram_send(
                    message
                )

                if message_id:

                    prediction[
                        "message_id"
                    ] = message_id

                    atomic_save_json(
                        PREDICTIONS_FILE,
                        predictions
                    )

                    print(
                        f"📤 ПРОГНОЗ ОТПРАВЛЕН | "
                        f"Источник #{prediction['source_number']} "
                        f"-> Цель #{prediction['target_number']} | "
                        f"{prediction['predicted_cards']}",
                        flush=True
                    )

                else:

                    print(
                        "⚠️ Telegram не вернул message_id",
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
# СТАРАЯ ЛОГИКА ПРОВЕРКИ СОХРАНЕНА
# =====================================================================

def check_predictions():

    global predictions

    if not predictions:
        return

    if not CHANNEL_STATS:
        return

    changed = False

    pending_count = sum(
        1
        for entry in predictions
        if entry.get("status") == "pending"
    )

    if pending_count:

        print(
            f"🔍 Проверяем прогнозы: "
            f"{pending_count} pending | "
            f"кэш игр: {len(games_cache)}",
            flush=True
        )

    for entry in predictions:

        if entry.get("status") != "pending":
            continue

        target = entry.get("target_number")

        predicted_cards = [
            c for c in entry.get(
                "predicted_cards",
                []
            )
            if c
        ]

        msg_id = entry.get("message_id")

        original_text = entry.get(
            "original_text",
            ""
        )

        if not target:
            continue

        if not predicted_cards:
            continue

        # =============================================================
        # ИЩЕМ КАРТУ:
        #
        # target
        # target + 1
        # target + 2
        # target + 3
        # target + 4
        # =============================================================

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

        # =============================================================
        # WIN
        # =============================================================

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
                f"✅ ЗАШЛО | "
                f"Источник #{entry.get('source_number')} | "
                f"Цель #{target} | "
                f"Результат #{found['num']} | "
                f"Догон {found['dogon']} | "
                f"{found['card']}",
                flush=True
            )

            # Редактируем сообщение
            if msg_id and original_text:

                lines = original_text.split(
                    "\n"
                )

                if lines:

                    lines[0] = (
                        f"🎯 Игра: #N{target} ✅"
                    )

                new_text = "\n".join(
                    lines
                )

                telegram_edit(
                    msg_id,
                    new_text
                )

            atomic_save_json(
                PREDICTIONS_FILE,
                predictions
            )

            continue

        # =============================================================
        # ЖДЁМ ИГРЫ ДЛЯ ДОГОНОВ
        # =============================================================

        if not all_available:

            print(
                f"⏳ Ожидание результата "
                f"для #{target}",
                flush=True
            )

            continue

        # =============================================================
        # LOSE
        # =============================================================

        entry["status"] = "lose"

        changed = True

        print(
            f"❌ НЕ ЗАШЛО | "
            f"Источник #{entry.get('source_number')} | "
            f"Цель #{target} | "
            f"догоны 0-{DOGON_GAMES}",
            flush=True
        )

        if msg_id and original_text:

            lines = original_text.split(
                "\n"
            )

            if lines:

                lines[0] = (
                    f"🎯 Игра: #N{target} ❌"
                )

            new_text = "\n".join(
                lines
            )

            telegram_edit(
                msg_id,
                new_text
            )

        atomic_save_json(
            PREDICTIONS_FILE,
            predictions
        )

    if changed:

        print(
            "💾 Результаты прогнозов обновлены",
            flush=True
        )


# =====================================================================
# CLEANUP PREDICTIONS
# =====================================================================

def cleanup_predictions():

    global predictions

    # Храним историю прогнозов
    if len(predictions) > 5000:

        predictions = predictions[-5000:]

        atomic_save_json(
            PREDICTIONS_FILE,
            predictions
        )


# =====================================================================
# MAIN
# =====================================================================

def main():

    global predictions

    print(
        "\n"
        "=================================================="
    )

    print(
        "🚀 OLD PATTERN BOT — НОВАЯ ЛОГИКА"
    )

    print(
        "=================================================="
    )

    print(
        "📡 Источник: CHANNEL_STATS"
    )

    print(
        "🧠 Паттерн: первая карта игрока J/Q/K/A"
    )

    print(
        "🔄 Ранги: J↔K | Q↔A"
    )

    print(
        "🔄 Масти: ♣↔♥ | ♠↔♦"
    )

    print(
        f"🎯 Смещение прогноза: +{FORECAST_OFFSET} игр"
    )

    print(
        f"🚫 Исключения: "
        f"{', '.join('#' + x for x in sorted(FORBIDDEN_TAGS))}"
    )

    print(
        f"🔁 Проверка: "
        f"основная + {DOGON_GAMES} догонов"
    )

    print(
        "==================================================\n"
    )

    # ================================================================
    # ЗАГРУЖАЕМ ПРОГНОЗЫ
    # ================================================================

    predictions = load_predictions()

    print(
        f"📊 Загружено прогнозов: "
        f"{len(predictions)}",
        flush=True
    )

    print(
        f"🛡️ Обработанных источников: "
        f"{len(processed_source_games)}",
        flush=True
    )

    # ================================================================
    # TELEGRAM OFFSET
    # ================================================================

    offset = get_offset()

    print(
        f"📌 Telegram offset: {offset}",
        flush=True
    )

    print(
        "\n🤖 Бот запущен...\n",
        flush=True
    )

    # ================================================================
    # MAIN LOOP
    # ================================================================

    while True:

        start = time.time()

        try:

            # =========================================================
            # 1. ЧИТАЕМ КАНАЛ
            # =========================================================

            offset = process_telegram_updates(
                offset
            )

            # =========================================================
            # 2. ПРОВЕРЯЕМ РЕЗУЛЬТАТЫ
            # =========================================================

            check_predictions()

            # =========================================================
            # 3. ЧИСТИМ СТАРЫЕ ПРОГНОЗЫ
            # =========================================================

            cleanup_predictions()

            # =========================================================
            # PAUSE
            # =========================================================

            elapsed = time.time() - start

            sleep_time = max(
                0.1,
                POLL_INTERVAL - elapsed
            )

            time.sleep(sleep_time)

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