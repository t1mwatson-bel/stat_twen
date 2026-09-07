import os
import sys
import time
import sqlite3
import logging
import traceback

from datetime import (
    datetime,
    timedelta,
    timezone,
)

import requests


# =====================================================================
# SETTINGS
# =====================================================================

BASE_URL = "https://api.binarium.com"

# ---------------------------------------------------------------------
# АКТИВ
# ---------------------------------------------------------------------

ASSET_ID = 43

# Название для Telegram
ASSET_NAME = "EUR/USD"


# ---------------------------------------------------------------------
# СВЕЧИ
# ---------------------------------------------------------------------

# Интервал свечей для анализа
DETAILIZATION = "5s"

# Продолжительность одной свечи
CANDLE_SECONDS = 5


# ---------------------------------------------------------------------
# DATABASE
# ---------------------------------------------------------------------

DB_FILE = "binarium_history.db"


# ---------------------------------------------------------------------
# TELEGRAM
# ---------------------------------------------------------------------

# Берутся из переменных окружения хостинга
BOT_TOKEN = os.getenv("BOT_TOKEN")
CHANNEL_ID = os.getenv("CHANNEL_ID")

TELEGRAM_API_URL = "https://api.telegram.org"


# =====================================================================
# СБОР ИСТОРИИ
# =====================================================================

# При первом запуске
HISTORY_HOURS = 12

# Размер одного запроса
CHUNK_MINUTES = 60

# Интервал обновления
UPDATE_INTERVAL = 5

# Последние минуты для обновления
LIVE_WINDOW_MINUTES = 10

REQUEST_TIMEOUT = 30
MAX_RETRIES = 3


# =====================================================================
# АНАЛИЗ ПАТТЕРНОВ
# =====================================================================

# Последние закрытые свечи для паттерна
PATTERN_LENGTH = 6

# Минимум исторических совпадений
MIN_MATCHES = 4

# Минимум свечей в базе
MIN_CANDLES_FOR_ANALYSIS = 500

# Минимальная уверенность
MIN_CONFIDENCE = 58.0


# =====================================================================
# ЭКСПИРАЦИЯ
# =====================================================================

# Экспирация в минутах
EXPIRATION_MINUTES = 1

# Экспирация в секундах
EXPIRATION_SECONDS = (
    EXPIRATION_MINUTES * 60
)


# =====================================================================
# ЛОГИРОВАНИЕ
# =====================================================================

logging.basicConfig(
    level=logging.INFO,
    format=(
        "%(asctime)s | "
        "%(levelname)s | "
        "%(message)s"
    ),
)

logger = logging.getLogger(
    "BINARIUM"
)


# =====================================================================
# HTTP SESSION
# =====================================================================

session = requests.Session()

session.headers.update(
    {
        "User-Agent": (
            "Mozilla/5.0 "
            "(Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 "
            "(KHTML, like Gecko) "
            "Chrome/150.0.0.0 Safari/537.36"
        ),
        "Accept": (
            "application/json, "
            "text/plain, "
            "*/*"
        ),
        "Referer": "https://binarium.com/",
        "Origin": "https://binarium.com",
        "Connection": "keep-alive",
    }
)


# =====================================================================
# TIME
# =====================================================================

def utc_now():

    return datetime.now(
        timezone.utc
    )


def format_api_time(dt):

    dt = dt.astimezone(
        timezone.utc
    )

    return dt.strftime(
        "%Y-%m-%dT%H:%M:%S.000Z"
    )


def parse_api_time(value):

    if not value:
        return None

    value = str(value).strip()

    if value.endswith("Z"):

        value = (
            value[:-1]
            + "+00:00"
        )

    try:

        dt = datetime.fromisoformat(
            value
        )

        if dt.tzinfo is None:

            dt = dt.replace(
                tzinfo=timezone.utc
            )

        return dt.astimezone(
            timezone.utc
        )

    except Exception:

        return None


def timestamp_from_api_time(value):

    dt = parse_api_time(value)

    if dt is None:
        return 0.0

    return dt.timestamp()


def timestamp_to_datetime(timestamp):

    return datetime.fromtimestamp(
        timestamp,
        tz=timezone.utc,
    )


def format_timestamp(timestamp):

    dt = timestamp_to_datetime(
        timestamp
    )

    return dt.strftime(
        "%H:%M:%S UTC"
    )


# =====================================================================
# NEXT MINUTE ENTRY
# =====================================================================

def get_next_minute_timestamp(timestamp):

    dt = timestamp_to_datetime(
        timestamp
    )

    next_minute = (
        dt.replace(
            second=0,
            microsecond=0,
        )
        + timedelta(minutes=1)
    )

    return next_minute.timestamp()


# =====================================================================
# DATABASE
# =====================================================================

def init_database():

    conn = sqlite3.connect(
        DB_FILE
    )

    cursor = conn.cursor()

    # -------------------------------------------------------------
    # CANDLES
    # -------------------------------------------------------------

    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS candles (
            asset_id INTEGER NOT NULL,
            time TEXT NOT NULL,
            timestamp REAL NOT NULL,
            open REAL NOT NULL,
            high REAL NOT NULL,
            low REAL NOT NULL,
            close REAL NOT NULL,
            PRIMARY KEY (asset_id, time)
        )
        """
    )

    cursor.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_candles_timestamp
        ON candles(asset_id, timestamp)
        """
    )

    # -------------------------------------------------------------
    # SIGNALS
    # -------------------------------------------------------------

    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS signals (
            id INTEGER PRIMARY KEY AUTOINCREMENT,

            signal_time TEXT NOT NULL,
            signal_timestamp REAL NOT NULL,

            entry_timestamp REAL,

            entry_price REAL,

            prediction TEXT NOT NULL,

            confidence REAL NOT NULL,

            matches INTEGER NOT NULL,

            up_count INTEGER NOT NULL,
            down_count INTEGER NOT NULL,

            pattern TEXT NOT NULL,

            expiration_seconds INTEGER NOT NULL,

            checked INTEGER DEFAULT 0,

            result TEXT,

            exit_price REAL,

            checked_time TEXT,

            telegram_sent INTEGER DEFAULT 0,

            result_telegram_sent INTEGER DEFAULT 0
        )
        """
    )

    cursor.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_signals_checked
        ON signals(checked)
        """
    )

    cursor.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_signals_timestamp
        ON signals(signal_timestamp)
        """
    )

    conn.commit()
    conn.close()

    logger.info(
        f"✅ База данных готова: {DB_FILE}"
    )


# =====================================================================
# TELEGRAM
# =====================================================================

def telegram_ready():

    if not BOT_TOKEN:

        logger.warning(
            "⚠️ BOT_TOKEN не найден "
            "в переменных окружения"
        )

        return False

    if not CHANNEL_ID:

        logger.warning(
            "⚠️ CHANNEL_ID не найден "
            "в переменных окружения"
        )

        return False

    return True


def send_telegram_message(text):

    if not telegram_ready():

        return False

    url = (
        f"{TELEGRAM_API_URL}"
        f"/bot{BOT_TOKEN}"
        f"/sendMessage"
    )

    payload = {
        "chat_id": CHANNEL_ID,
        "text": text,
        "parse_mode": "HTML",
        "disable_web_page_preview": True,
    }

    try:

        response = requests.post(
            url,
            json=payload,
            timeout=20,
        )

        if response.status_code != 200:

            logger.error(
                f"❌ Telegram HTTP "
                f"{response.status_code}: "
                f"{response.text}"
            )

            return False

        result = response.json()

        if not result.get("ok"):

            logger.error(
                f"❌ Telegram ошибка: "
                f"{result}"
            )

            return False

        logger.info(
            "📨 Сообщение отправлено "
            "в Telegram"
        )

        return True

    except Exception as e:

        logger.exception(
            f"❌ Ошибка Telegram: {e}"
        )

        return False


# =====================================================================
# REQUEST CANDLES
# =====================================================================

def request_candles(
    start_dt,
    end_dt,
):

    url = (
        f"{BASE_URL}"
        f"/api/v1/assets/"
        f"{ASSET_ID}/candles"
    )

    params = {
        "from": format_api_time(
            start_dt
        ),
        "to": format_api_time(
            end_dt
        ),
        "detalization": DETAILIZATION,
    }

    for attempt in range(
        1,
        MAX_RETRIES + 1,
    ):

        try:

            logger.info(
                "Запрос свечей: %s -> %s",
                format_api_time(start_dt),
                format_api_time(end_dt),
            )

            response = session.get(
                url,
                params=params,
                timeout=REQUEST_TIMEOUT,
            )

            logger.info(
                "HTTP %s | %.2f KB",
                response.status_code,
                len(response.content) / 1024,
            )

            if response.status_code != 200:

                logger.warning(
                    f"⚠️ HTTP "
                    f"{response.status_code}"
                )

                if attempt < MAX_RETRIES:

                    time.sleep(
                        2 * attempt
                    )

                    continue

                return []

            try:

                result = response.json()

            except Exception:

                logger.error(
                    "❌ Не удалось разобрать JSON"
                )

                return []

            if "errors" in result:

                logger.error(
                    f"❌ API ошибка: "
                    f"{result['errors']}"
                )

                return []

            data = result.get(
                "data"
            )

            if not isinstance(
                data,
                list,
            ):

                logger.warning(
                    "⚠️ API не вернул data"
                )

                return []

            logger.info(
                f"Получено свечей: "
                f"{len(data)}"
            )

            return data

        except requests.RequestException as e:

            logger.warning(
                f"⚠️ HTTP ошибка: {e}"
            )

            if attempt < MAX_RETRIES:

                time.sleep(
                    2 * attempt
                )

                continue

            return []

        except Exception:

            logger.exception(
                "❌ Ошибка запроса"
            )

            return []

    return []


# =====================================================================
# NORMALIZE CANDLES
# =====================================================================

def normalize_candles(raw_candles):

    result = []

    for item in raw_candles:

        if not isinstance(
            item,
            dict,
        ):
            continue

        candle_time = item.get(
            "time"
        )

        if not candle_time:
            continue

        try:

            open_price = float(
                item["open"]
            )

            high_price = float(
                item["high"]
            )

            low_price = float(
                item["low"]
            )

            close_price = float(
                item["close"]
            )

        except (
            KeyError,
            TypeError,
            ValueError,
        ):

            continue

        timestamp = timestamp_from_api_time(
            candle_time
        )

        if timestamp <= 0:
            continue

        result.append(
            {
                "asset_id": ASSET_ID,
                "time": candle_time,
                "timestamp": timestamp,
                "open": open_price,
                "high": high_price,
                "low": low_price,
                "close": close_price,
            }
        )

    result.sort(
        key=lambda x: x["timestamp"]
    )

    return result


# =====================================================================
# SAVE CANDLES
# =====================================================================

def save_candles(candles):

    if not candles:
        return 0

    conn = sqlite3.connect(
        DB_FILE
    )

    cursor = conn.cursor()

    new_saved = 0

    try:

        for candle in candles:

            cursor.execute(
                """
                SELECT 1
                FROM candles
                WHERE asset_id = ?
                AND time = ?
                LIMIT 1
                """,
                (
                    candle["asset_id"],
                    candle["time"],
                ),
            )

            exists = cursor.fetchone()

            cursor.execute(
                """
                INSERT OR REPLACE INTO candles (
                    asset_id,
                    time,
                    timestamp,
                    open,
                    high,
                    low,
                    close
                )
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    candle["asset_id"],
                    candle["time"],
                    candle["timestamp"],
                    candle["open"],
                    candle["high"],
                    candle["low"],
                    candle["close"],
                ),
            )

            if not exists:

                new_saved += 1

        conn.commit()

    finally:

        conn.close()

    return new_saved


# =====================================================================
# DATABASE STATS
# =====================================================================

def get_database_stats():

    conn = sqlite3.connect(
        DB_FILE
    )

    cursor = conn.cursor()

    cursor.execute(
        """
        SELECT
            COUNT(*),
            MIN(time),
            MAX(time)
        FROM candles
        WHERE asset_id = ?
        """,
        (
            ASSET_ID,
        ),
    )

    row = cursor.fetchone()

    conn.close()

    if not row:

        return (
            0,
            None,
            None,
        )

    return (
        row[0] or 0,
        row[1],
        row[2],
    )


# =====================================================================
# LOAD CANDLES
# =====================================================================

def load_candles_from_database():

    conn = sqlite3.connect(
        DB_FILE
    )

    cursor = conn.cursor()

    cursor.execute(
        """
        SELECT
            time,
            timestamp,
            open,
            high,
            low,
            close
        FROM candles
        WHERE asset_id = ?
        ORDER BY timestamp ASC
        """,
        (
            ASSET_ID,
        ),
    )

    rows = cursor.fetchall()

    conn.close()

    candles = []

    for row in rows:

        candles.append(
            {
                "time": row[0],
                "timestamp": row[1],
                "open": row[2],
                "high": row[3],
                "low": row[4],
                "close": row[5],
            }
        )

    return candles


# =====================================================================
# DOWNLOAD HISTORY
# =====================================================================

def download_history():

    count, _, _ = (
        get_database_stats()
    )

    if count > 0:

        logger.info(
            f"📚 База уже содержит "
            f"{count} свечей"
        )

        return

    logger.info("")
    logger.info("=" * 70)
    logger.info(
        "📥 ПЕРВАЯ ЗАГРУЗКА ИСТОРИИ"
    )
    logger.info("=" * 70)

    end_dt = utc_now()

    start_dt = (
        end_dt
        - timedelta(
            hours=HISTORY_HOURS
        )
    )

    current = start_dt

    total_saved = 0
    chunk_number = 0

    while current < end_dt:

        chunk_number += 1

        chunk_end = (
            current
            + timedelta(
                minutes=CHUNK_MINUTES
            )
        )

        if chunk_end > end_dt:

            chunk_end = end_dt

        logger.info("")
        logger.info(
            f"📦 ЧАНК #{chunk_number}"
        )

        raw = request_candles(
            current,
            chunk_end,
        )

        candles = normalize_candles(
            raw
        )

        saved = save_candles(
            candles
        )

        total_saved += saved

        logger.info(
            f"💾 Новых свечей: "
            f"{saved}"
        )

        current = chunk_end

        time.sleep(0.3)

    logger.info("")
    logger.info("=" * 70)
    logger.info(
        "✅ ИСТОРИЯ ЗАГРУЖЕНА"
    )
    logger.info(
        f"💾 Всего новых: "
        f"{total_saved}"
    )
    logger.info("=" * 70)


# =====================================================================
# UPDATE RECENT CANDLES
# =====================================================================

def update_recent_candles():

    end_dt = utc_now()

    start_dt = (
        end_dt
        - timedelta(
            minutes=LIVE_WINDOW_MINUTES
        )
    )

    raw = request_candles(
        start_dt,
        end_dt,
    )

    if not raw:

        logger.warning(
            "⚠️ Новые свечи не получены"
        )

        return 0

    candles = normalize_candles(
        raw
    )

    return save_candles(
        candles
    )


# =====================================================================
# CLOSED CANDLES
# =====================================================================

def get_closed_candles(candles):

    if not candles:
        return []

    now_timestamp = time.time()

    closed = []

    for candle in candles:

        timestamp = candle.get(
            "timestamp"
        )

        if timestamp is None:
            continue

        candle_close_time = (
            timestamp
            + CANDLE_SECONDS
        )

        if candle_close_time <= now_timestamp:

            closed.append(
                candle
            )

    return closed


# =====================================================================
# CANDLE DIRECTION
# =====================================================================

def candle_direction(candle):

    open_price = candle.get(
        "open"
    )

    close_price = candle.get(
        "close"
    )

    if (
        open_price is None
        or close_price is None
    ):

        return None

    if close_price > open_price:

        return "UP"

    if close_price < open_price:

        return "DOWN"

    return "FLAT"


# =====================================================================
# BUILD DIRECTIONS
# =====================================================================

def build_directions(candles):

    directions = []

    for candle in candles:

        directions.append(
            candle_direction(candle)
        )

    return directions


# =====================================================================
# PATTERN TO TEXT
# =====================================================================

def pattern_to_text(pattern):

    symbols = {
        "UP": "🟢",
        "DOWN": "🔴",
        "FLAT": "⚪",
    }

    return "".join(
        symbols.get(item, "?")
        for item in pattern
    )


# =====================================================================
# FIND PATTERN MATCHES
# =====================================================================

def find_pattern_matches(
    directions,
    pattern,
):

    matches = []

    pattern_length = len(
        pattern
    )

    total_directions = len(
        directions
    )

    current_pattern_start = (
        total_directions
        - pattern_length
    )

    max_search_index = (
        current_pattern_start
        - 1
    )

    if max_search_index <= pattern_length:

        return matches

    for i in range(
        pattern_length,
        max_search_index + 1,
    ):

        historical_pattern = directions[
            i - pattern_length:i
        ]

        if historical_pattern != pattern:
            continue

        next_direction = directions[i]

        if next_direction not in (
            "UP",
            "DOWN",
        ):
            continue

        matches.append(
            {
                "index": i,
                "next": next_direction,
            }
        )

    return matches


# =====================================================================
# ANALYZE PATTERN
# =====================================================================

def analyze_pattern(candles):

    closed_candles = get_closed_candles(
        candles
    )

    if (
        len(closed_candles)
        < MIN_CANDLES_FOR_ANALYSIS
    ):

        return None

    directions = build_directions(
        closed_candles
    )

    if (
        len(directions)
        < PATTERN_LENGTH + 2
    ):

        return None

    current_pattern = directions[
        -PATTERN_LENGTH:
    ]

    if None in current_pattern:

        return None

    signal_candle = (
        closed_candles[-1]
    )

    if "FLAT" in current_pattern:

        return {
            "pattern": current_pattern,
            "matches": 0,
            "up": 0,
            "down": 0,
            "up_probability": 0.0,
            "down_probability": 0.0,
            "prediction": None,
            "confidence": 0.0,
            "reason": (
                "В текущем паттерне "
                "есть FLAT-свеча"
            ),
            "signal_candle": signal_candle,
        }

    matches = find_pattern_matches(
        directions,
        current_pattern,
    )

    up_count = sum(
        1
        for match in matches
        if match["next"] == "UP"
    )

    down_count = sum(
        1
        for match in matches
        if match["next"] == "DOWN"
    )

    total = (
        up_count
        + down_count
    )

    if total < MIN_MATCHES:

        return {
            "pattern": current_pattern,
            "matches": total,
            "up": up_count,
            "down": down_count,
            "up_probability": 0.0,
            "down_probability": 0.0,
            "prediction": None,
            "confidence": 0.0,
            "reason": (
                f"Недостаточно совпадений: "
                f"{total}/{MIN_MATCHES}"
            ),
            "signal_candle": signal_candle,
        }

    up_probability = (
        up_count / total * 100
    )

    down_probability = (
        down_count / total * 100
    )

    prediction = None
    confidence = 0.0
    reason = ""

    if up_probability > down_probability:

        prediction = "UP"
        confidence = up_probability

    elif down_probability > up_probability:

        prediction = "DOWN"
        confidence = down_probability

    else:

        reason = (
            "Вероятности UP и DOWN равны"
        )

    if (
        prediction
        and confidence < MIN_CONFIDENCE
    ):

        reason = (
            f"Уверенность {confidence:.1f}% "
            f"ниже минимума "
            f"{MIN_CONFIDENCE}%"
        )

        prediction = None

    if prediction and not reason:

        reason = (
            "Сигнал соответствует "
            "всем условиям"
        )

    return {
        "pattern": current_pattern,
        "matches": total,
        "up": up_count,
        "down": down_count,
        "up_probability": up_probability,
        "down_probability": down_probability,
        "prediction": prediction,
        "confidence": confidence,
        "reason": reason,
        "signal_candle": signal_candle,
    }


# =====================================================================
# CHECK ACTIVE SIGNAL
# =====================================================================

def has_active_signal():

    conn = sqlite3.connect(
        DB_FILE
    )

    cursor = conn.cursor()

    cursor.execute(
        """
        SELECT COUNT(*)
        FROM signals
        WHERE checked = 0
        """
    )

    count = cursor.fetchone()[0]

    conn.close()

    return count > 0


# =====================================================================
# SIGNAL EXISTS FOR ENTRY TIME
# =====================================================================

def signal_exists_for_entry(
    entry_timestamp,
):

    conn = sqlite3.connect(
        DB_FILE
    )

    cursor = conn.cursor()

    cursor.execute(
        """
        SELECT id
        FROM signals
        WHERE entry_timestamp = ?
        LIMIT 1
        """,
        (
            entry_timestamp,
        ),
    )

    row = cursor.fetchone()

    conn.close()

    return row is not None


# =====================================================================
# SAVE SIGNAL
# =====================================================================

def save_signal(
    result,
    candle,
):

    prediction = result.get(
        "prediction"
    )

    if prediction not in (
        "UP",
        "DOWN",
    ):

        return None

    signal_timestamp = candle.get(
        "timestamp"
    )

    if signal_timestamp is None:

        return None

    # -------------------------------------------------------------
    # ТОЧКА ВХОДА = НАЧАЛО СЛЕДУЮЩЕЙ МИНУТЫ
    # -------------------------------------------------------------

    entry_timestamp = (
        get_next_minute_timestamp(
            signal_timestamp
        )
    )

    # Если сигнал уже слишком поздний
    if entry_timestamp <= time.time():

        entry_timestamp = (
            entry_timestamp + 60
        )

    if signal_exists_for_entry(
        entry_timestamp
    ):

        logger.info(
            "⏭️ Для этой точки входа "
            "сигнал уже существует"
        )

        return None

    if has_active_signal():

        logger.info(
            "⏳ Уже есть активный сигнал. "
            "Ждём результата."
        )

        return None

    pattern_text = ",".join(
        result.get(
            "pattern",
            [],
        )
    )

    conn = sqlite3.connect(
        DB_FILE
    )

    cursor = conn.cursor()

    try:

        cursor.execute(
            """
            INSERT INTO signals (
                signal_time,
                signal_timestamp,
                entry_timestamp,
                entry_price,
                prediction,
                confidence,
                matches,
                up_count,
                down_count,
                pattern,
                expiration_seconds,
                checked
            )
            VALUES (
                ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 0
            )
            """,
            (
                candle.get("time"),
                signal_timestamp,
                entry_timestamp,

                # Реальная цена входа будет
                # зафиксирована после начала минуты
                None,

                prediction,
                result.get(
                    "confidence",
                    0.0,
                ),
                result.get(
                    "matches",
                    0,
                ),
                result.get(
                    "up",
                    0,
                ),
                result.get(
                    "down",
                    0,
                ),
                pattern_text,
                EXPIRATION_SECONDS,
            ),
        )

        signal_id = cursor.lastrowid

        conn.commit()

        return {
            "id": signal_id,
            "entry_timestamp": entry_timestamp,
        }

    except Exception:

        logger.exception(
            "❌ Ошибка сохранения сигнала"
        )

        return None

    finally:

        conn.close()


# =====================================================================
# TELEGRAM SIGNAL MESSAGE
# =====================================================================

def send_signal_to_telegram(
    result,
    signal_data,
):

    prediction = result.get(
        "prediction"
    )

    entry_timestamp = signal_data.get(
        "entry_timestamp"
    )

    entry_time = format_timestamp(
        entry_timestamp
    )

    if prediction == "UP":

        direction = (
            "🚀 ВЫШЕ 🟢"
        )

        short_direction = (
            "ВЫШЕ"
        )

    else:

        direction = (
            "📉 НИЖЕ 🔴"
        )

        short_direction = (
            "НИЖЕ"
        )

    message = (
        "🚨 <b>НОВЫЙ СИГНАЛ</b>\n\n"

        f"💱 <b>АКТИВ: {ASSET_NAME}</b>\n\n"

        "━━━━━━━━━━━━━━━━\n\n"

        f"⏰ <b>ТОЧКА ВХОДА: "
        f"{entry_time}</b>\n\n"

        f"🎯 <b>НАПРАВЛЕНИЕ: "
        f"{direction}</b>\n\n"

        f"⏱ <b>ЭКСПИРАЦИЯ: "
        f"{EXPIRATION_MINUTES} МИН.</b>\n\n"

        "━━━━━━━━━━━━━━━━\n\n"

        f"🧩 Паттерн: "
        f"{pattern_to_text(result['pattern'])}\n\n"

        f"🔎 Совпадений: "
        f"<b>{result['matches']}</b>\n\n"

        f"🟢 Вверх: "
        f"{result['up']} "
        f"({result['up_probability']:.1f}%)\n\n"

        f"🔴 Вниз: "
        f"{result['down']} "
        f"({result['down_probability']:.1f}%)\n\n"

        f"📊 Уверенность: "
        f"<b>{result['confidence']:.1f}%</b>\n\n"

        "━━━━━━━━━━━━━━━━\n\n"

        f"⚡️ <b>ПРОГНОЗ: "
        f"{short_direction}</b>\n"

        f"🕐 <b>ВХОД РОВНО В "
        f"{entry_time}</b>"
    )

    return send_telegram_message(
        message
    )


# =====================================================================
# PRINT SIGNAL
# =====================================================================

def print_signal(
    result,
    signal_data,
):

    entry_timestamp = signal_data.get(
        "entry_timestamp"
    )

    logger.info("")
    logger.info("=" * 65)
    logger.info("🚨 НОВЫЙ СИГНАЛ")
    logger.info("=" * 65)

    logger.info(
        f"💱 Актив: {ASSET_NAME}"
    )

    logger.info(
        f"⏰ ТОЧКА ВХОДА: "
        f"{format_timestamp(entry_timestamp)}"
    )

    logger.info(
        f"🎯 Направление: "
        f"{result['prediction']}"
    )

    logger.info(
        f"⏱ Экспирация: "
        f"{EXPIRATION_MINUTES} мин."
    )

    logger.info(
        f"🧩 Паттерн: "
        f"{pattern_to_text(result['pattern'])}"
    )

    logger.info(
        f"🔎 Совпадений: "
        f"{result['matches']}"
    )

    logger.info(
        f"📊 Уверенность: "
        f"{result['confidence']:.1f}%"
    )

    logger.info("=" * 65)


# =====================================================================
# GET ENTRY PRICE
# =====================================================================

def get_entry_price(
    cursor,
    entry_timestamp,
):

    cursor.execute(
        """
        SELECT
            time,
            timestamp,
            open
        FROM candles
        WHERE asset_id = ?
        AND timestamp >= ?
        ORDER BY timestamp ASC
        LIMIT 1
        """,
        (
            ASSET_ID,
            entry_timestamp,
        ),
    )

    return cursor.fetchone()


# =====================================================================
# CHECK PENDING SIGNALS
# =====================================================================

def check_pending_signals(candles):

    if not candles:
        return

    now_timestamp = time.time()

    conn = sqlite3.connect(
        DB_FILE
    )

    cursor = conn.cursor()

    cursor.execute(
        """
        SELECT
            id,
            signal_time,
            signal_timestamp,
            entry_timestamp,
            entry_price,
            prediction,
            confidence,
            expiration_seconds,
            result_telegram_sent
        FROM signals
        WHERE checked = 0
        ORDER BY id ASC
        """
    )

    signals = cursor.fetchall()

    if not signals:

        conn.close()
        return

    for signal in signals:

        signal_id = signal[0]
        signal_time = signal[1]
        signal_timestamp = signal[2]
        entry_timestamp = signal[3]
        entry_price = signal[4]
        prediction = signal[5]
        confidence = signal[6]
        expiration_seconds = signal[7]
        result_telegram_sent = signal[8]

        # ---------------------------------------------------------
        # ЖДЁМ ТОЧКУ ВХОДА
        # ---------------------------------------------------------

        if now_timestamp < entry_timestamp:

            continue

        # ---------------------------------------------------------
        # ФИКСИРУЕМ РЕАЛЬНУЮ ЦЕНУ ВХОДА
        # ---------------------------------------------------------

        if entry_price is None:

            entry_row = get_entry_price(
                cursor,
                entry_timestamp,
            )

            if not entry_row:

                continue

            entry_candle_time = entry_row[0]
            entry_candle_timestamp = entry_row[1]
            real_entry_price = entry_row[2]

            # Убеждаемся что свеча уже существует
            if entry_candle_timestamp > now_timestamp:

                continue

            cursor.execute(
                """
                UPDATE signals
                SET entry_price = ?
                WHERE id = ?
                """,
                (
                    real_entry_price,
                    signal_id,
                ),
            )

            conn.commit()

            entry_price = real_entry_price

            logger.info(
                f"📍 Зафиксирована цена входа "
                f"для сигнала #{signal_id}: "
                f"{entry_price}"
            )

        # ---------------------------------------------------------
        # ВРЕМЯ ЭКСПИРАЦИИ
        # ---------------------------------------------------------

        expiration_timestamp = (
            entry_timestamp
            + expiration_seconds
        )

        if now_timestamp < expiration_timestamp:

            continue

        # ---------------------------------------------------------
        # ИЩЕМ СВЕЧУ ПОСЛЕ ЭКСПИРАЦИИ
        # ---------------------------------------------------------

        cursor.execute(
            """
            SELECT
                time,
                timestamp,
                close
            FROM candles
            WHERE asset_id = ?
            AND timestamp >= ?
            AND timestamp + ? <= ?
            ORDER BY timestamp ASC
            LIMIT 1
            """,
            (
                ASSET_ID,
                expiration_timestamp,
                CANDLE_SECONDS,
                now_timestamp,
            ),
        )

        exit_row = cursor.fetchone()

        if not exit_row:

            continue

        exit_time = exit_row[0]
        exit_timestamp = exit_row[1]
        exit_price = exit_row[2]

        result = "LOSE"

        if prediction == "UP":

            if exit_price > entry_price:

                result = "WIN"

        elif prediction == "DOWN":

            if exit_price < entry_price:

                result = "WIN"

        # ---------------------------------------------------------
        # СОХРАНЯЕМ РЕЗУЛЬТАТ
        # ---------------------------------------------------------

        cursor.execute(
            """
            UPDATE signals
            SET
                checked = 1,
                result = ?,
                exit_price = ?,
                checked_time = ?
            WHERE id = ?
            """,
            (
                result,
                exit_price,
                exit_time,
                signal_id,
            ),
        )

        conn.commit()

        # ---------------------------------------------------------
        # ЛОГ
        # ---------------------------------------------------------

        logger.info("")
        logger.info("=" * 65)
        logger.info("🔍 ПРОВЕРКА СИГНАЛА")
        logger.info("=" * 65)

        logger.info(
            f"💱 Актив: {ASSET_NAME}"
        )

        logger.info(
            f"🆔 Сигнал: #{signal_id}"
        )

        logger.info(
            f"🕐 Вход: "
            f"{format_timestamp(entry_timestamp)}"
        )

        logger.info(
            f"💰 Цена входа: "
            f"{entry_price}"
        )

        logger.info(
            f"⏱ Экспирация: "
            f"{EXPIRATION_MINUTES} мин."
        )

        logger.info(
            f"💰 Цена выхода: "
            f"{exit_price}"
        )

        logger.info(
            f"🎯 Прогноз: "
            f"{prediction}"
        )

        if result == "WIN":

            logger.info(
                "✅ ЗАШЛО!"
            )

        else:

            logger.info(
                "❌ НЕ ЗАШЛО!"
            )

        logger.info("=" * 65)

        # ---------------------------------------------------------
        # TELEGRAM RESULT
        # ---------------------------------------------------------

        if result == "WIN":

            result_text = (
                "✅ ЗАШЛО"
            )

            result_emoji = "🎉"

        else:

            result_text = (
                "❌ НЕ ЗАШЛО"
            )

            result_emoji = "📊"

        direction_text = (
            "ВЫШЕ 🟢"
            if prediction == "UP"
            else "НИЖЕ 🔴"
        )

        telegram_message = (
            f"{result_emoji} "
            f"<b>РЕЗУЛЬТАТ СИГНАЛА</b>\n\n"

            f"💱 <b>АКТИВ: "
            f"{ASSET_NAME}</b>\n\n"

            f"🎯 Прогноз: "
            f"<b>{direction_text}</b>\n\n"

            f"💰 Вход: "
            f"<b>{entry_price}</b>\n\n"

            f"💰 Выход: "
            f"<b>{exit_price}</b>\n\n"

            f"⏱ Экспирация: "
            f"<b>{EXPIRATION_MINUTES} мин.</b>\n\n"

            "━━━━━━━━━━━━━━━━\n\n"

            f"<b>{result_text}</b>"
        )

        sent = send_telegram_message(
            telegram_message
        )

        if sent:

            cursor.execute(
                """
                UPDATE signals
                SET result_telegram_sent = 1
                WHERE id = ?
                """,
                (
                    signal_id,
                ),
            )

            conn.commit()

    conn.close()


# =====================================================================
# SIGNAL STATISTICS
# =====================================================================

def print_statistics():

    conn = sqlite3.connect(
        DB_FILE
    )

    cursor = conn.cursor()

    cursor.execute(
        """
        SELECT
            COUNT(*),

            SUM(
                CASE
                    WHEN result = 'WIN'
                    THEN 1
                    ELSE 0
                END
            ),

            SUM(
                CASE
                    WHEN result = 'LOSE'
                    THEN 1
                    ELSE 0
                END
            )

        FROM signals

        WHERE checked = 1
        """
    )

    row = cursor.fetchone()

    conn.close()

    total = row[0] or 0
    wins = row[1] or 0
    losses = row[2] or 0

    accuracy = 0.0

    if total > 0:

        accuracy = (
            wins
            / total
            * 100
        )

    logger.info("")
    logger.info("=" * 65)
    logger.info(
        "📊 СТАТИСТИКА СИГНАЛОВ"
    )
    logger.info("=" * 65)

    logger.info(
        f"🎯 Всего: {total}"
    )

    logger.info(
        f"✅ Зашло: {wins}"
    )

    logger.info(
        f"❌ Не зашло: {losses}"
    )

    logger.info(
        f"📈 Точность: "
        f"{accuracy:.2f}%"
    )

    logger.info("=" * 65)


# =====================================================================
# CURRENT ANALYSIS
# =====================================================================

def print_current_analysis(
    result,
):

    if not result:
        return

    logger.info("")
    logger.info("-" * 65)

    logger.info(
        f"🧩 Текущий паттерн: "
        f"{pattern_to_text(result['pattern'])}"
    )

    signal_candle = result.get(
        "signal_candle"
    )

    if signal_candle:

        logger.info(
            f"🕯 Последняя закрытая: "
            f"{signal_candle.get('time')}"
        )

    logger.info(
        f"🔎 Найдено совпадений: "
        f"{result['matches']}"
    )

    if result["matches"] > 0:

        logger.info(
            f"🟢 Вверх: "
            f"{result['up']} "
            f"({result['up_probability']:.1f}%)"
        )

        logger.info(
            f"🔴 Вниз: "
            f"{result['down']} "
            f"({result['down_probability']:.1f}%)"
        )

    if result.get("prediction"):

        logger.info(
            f"🎯 ВОЗМОЖНЫЙ СИГНАЛ: "
            f"{result['prediction']}"
        )

        logger.info(
            f"📊 Уверенность: "
            f"{result['confidence']:.1f}%"
        )

    else:

        logger.info(
            "⏭️ Сигнал не подходит"
        )

    reason = result.get(
        "reason"
    )

    if reason:

        logger.info(
            f"ℹ️ Причина: {reason}"
        )

    logger.info("-" * 65)


# =====================================================================
# MAIN
# =====================================================================

def main():

    logger.info("")
    logger.info("=" * 70)
    logger.info(
        "🤖 BINARIUM AUTO ANALYZER"
    )
    logger.info("=" * 70)

    logger.info(
        f"💱 Актив: {ASSET_NAME}"
    )

    logger.info(
        f"🆔 Asset ID: {ASSET_ID}"
    )

    logger.info(
        f"🕯 Интервал анализа: "
        f"{DETAILIZATION}"
    )

    logger.info(
        f"🧩 Размер паттерна: "
        f"{PATTERN_LENGTH} свечей"
    )

    logger.info(
        f"🎯 Минимум совпадений: "
        f"{MIN_MATCHES}"
    )

    logger.info(
        f"📊 Минимальная уверенность: "
        f"{MIN_CONFIDENCE}%"
    )

    logger.info(
        f"⏱ Экспирация: "
        f"{EXPIRATION_MINUTES} мин."
    )

    # -------------------------------------------------------------
    # DATABASE
    # -------------------------------------------------------------

    init_database()

    # -------------------------------------------------------------
    # TELEGRAM
    # -------------------------------------------------------------

    if telegram_ready():

        logger.info(
            "✅ Telegram настроен"
        )

    # -------------------------------------------------------------
    # HISTORY
    # -------------------------------------------------------------

    download_history()

    # -------------------------------------------------------------
    # STATS
    # -------------------------------------------------------------

    count, first_time, last_time = (
        get_database_stats()
    )

    logger.info("")

    logger.info(
        f"📚 Свечей в базе: {count}"
    )

    logger.info(
        f"🕐 Первая: {first_time}"
    )

    logger.info(
        f"🕐 Последняя: {last_time}"
    )

    cycle = 0

    last_analyzed_timestamp = None

    # -------------------------------------------------------------
    # MAIN LOOP
    # -------------------------------------------------------------

    while True:

        cycle += 1

        try:

            now = utc_now()

            logger.info("")
            logger.info("=" * 70)

            logger.info(
                f"🔄 ЦИКЛ #{cycle} | "
                f"{format_api_time(now)}"
            )

            # -----------------------------------------------------
            # UPDATE CANDLES
            # -----------------------------------------------------

            saved = update_recent_candles()

            count, _, last_time = (
                get_database_stats()
            )

            logger.info(
                f"💾 Новых свечей: {saved}"
            )

            logger.info(
                f"📚 Всего свечей: {count}"
            )

            logger.info(
                f"🕯 Последняя свеча: "
                f"{last_time}"
            )

            # -----------------------------------------------------
            # LOAD
            # -----------------------------------------------------

            candles = (
                load_candles_from_database()
            )

            if not candles:

                logger.warning(
                    "⚠️ В базе нет свечей"
                )

                time.sleep(
                    UPDATE_INTERVAL
                )

                continue

            # -----------------------------------------------------
            # CHECK OLD SIGNALS
            # -----------------------------------------------------

            check_pending_signals(
                candles
            )

            # -----------------------------------------------------
            # CLOSED CANDLES
            # -----------------------------------------------------

            closed_candles = (
                get_closed_candles(
                    candles
                )
            )

            if (
                len(closed_candles)
                < MIN_CANDLES_FOR_ANALYSIS
            ):

                remaining = (
                    MIN_CANDLES_FOR_ANALYSIS
                    - len(closed_candles)
                )

                logger.info(
                    f"⏳ Нужно ещё "
                    f"{remaining} свечей"
                )

                time.sleep(
                    UPDATE_INTERVAL
                )

                continue

            # -----------------------------------------------------
            # NEW CLOSED CANDLE
            # -----------------------------------------------------

            latest_closed = (
                closed_candles[-1]
            )

            latest_closed_timestamp = (
                latest_closed.get(
                    "timestamp"
                )
            )

            if (
                latest_closed_timestamp
                == last_analyzed_timestamp
            ):

                logger.info(
                    "⏳ Новая закрытая свеча "
                    "ещё не появилась"
                )

                time.sleep(
                    UPDATE_INTERVAL
                )

                continue

            # -----------------------------------------------------
            # ANALYZE
            # -----------------------------------------------------

            result = analyze_pattern(
                candles
            )

            last_analyzed_timestamp = (
                latest_closed_timestamp
            )

            print_current_analysis(
                result
            )

            # -----------------------------------------------------
            # NEW SIGNAL
            # -----------------------------------------------------

            if (
                result
                and result.get(
                    "prediction"
                )
            ):

                signal_candle = (
                    result.get(
                        "signal_candle"
                    )
                )

                if signal_candle:

                    signal_data = (
                        save_signal(
                            result,
                            signal_candle,
                        )
                    )

                    if signal_data:

                        print_signal(
                            result,
                            signal_data,
                        )

                        send_signal_to_telegram(
                            result,
                            signal_data,
                        )

            # -----------------------------------------------------
            # STATISTICS
            # -----------------------------------------------------

            if cycle % 12 == 0:

                print_statistics()

            # -----------------------------------------------------
            # WAIT
            # -----------------------------------------------------

            time.sleep(
                UPDATE_INTERVAL
            )

        except KeyboardInterrupt:

            logger.info(
                "🛑 Остановка по Ctrl+C"
            )

            break

        except Exception:

            logger.exception(
                "❌ Ошибка главного цикла"
            )

            time.sleep(5)


# =====================================================================
# START
# =====================================================================

if __name__ == "__main__":

    try:

        main()

    except KeyboardInterrupt:

        print()
        print(
            "🛑 Бот остановлен."
        )

    except Exception:

        print()
        print(
            "❌ КРИТИЧЕСКАЯ ОШИБКА:"
        )

        traceback.print_exc()

        sys.exit(1)