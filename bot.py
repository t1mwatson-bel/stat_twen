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
# ASSET
# ---------------------------------------------------------------------

ASSET_ID = 43

# Название актива для Telegram
ASSET_NAME = "EUR/USD"

# ---------------------------------------------------------------------
# TELEGRAM
# ---------------------------------------------------------------------
# BOT_TOKEN и CHANNEL_ID берутся из переменных окружения хостинга
#
# BOT_TOKEN=...
# CHANNEL_ID=...
# ---------------------------------------------------------------------

BOT_TOKEN = os.getenv("BOT_TOKEN")
CHANNEL_ID = os.getenv("CHANNEL_ID")

TELEGRAM_TIMEOUT = 20


# =====================================================================
# CANDLES
# =====================================================================

DETAILIZATION = "5s"

CANDLE_SECONDS = 5

DB_FILE = "binarium_history.db"


# =====================================================================
# HISTORY
# =====================================================================

HISTORY_HOURS = 12

CHUNK_MINUTES = 60

UPDATE_INTERVAL = 2

LIVE_WINDOW_MINUTES = 10

REQUEST_TIMEOUT = 30

MAX_RETRIES = 3


# =====================================================================
# PATTERN ANALYSIS
# =====================================================================

# Последние закрытые свечи в паттерне
PATTERN_LENGTH = 6

# Минимум исторических совпадений
MIN_MATCHES = 4

# Минимум свечей для работы
MIN_CANDLES_FOR_ANALYSIS = 500

# Минимальная вероятность сигнала
MIN_CONFIDENCE = 60.0


# =====================================================================
# EXPIRATION
# =====================================================================

# Бинарная сделка
EXPIRATION_SECONDS = 60

# 60 секунд / 5 секунд = 12 свечей
EXPIRATION_CANDLES = (
    EXPIRATION_SECONDS // CANDLE_SECONDS
)


# =====================================================================
# SIGNAL TIMING
# =====================================================================

# За сколько секунд до точки входа отправлять сигнал
SIGNAL_ADVANCE_SECONDS = 25

# Минимальное количество секунд до входа.
# Если времени меньше — эту минуту пропускаем.
MIN_SECONDS_BEFORE_ENTRY = 8


# =====================================================================
# LOGGING
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

        value = value[:-1] + "+00:00"

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


def format_timestamp(timestamp):

    if timestamp is None:
        return "-"

    dt = datetime.fromtimestamp(
        timestamp,
        tz=timezone.utc,
    )

    return dt.strftime(
        "%H:%M:%S"
    )


def format_full_timestamp(timestamp):

    if timestamp is None:
        return "-"

    dt = datetime.fromtimestamp(
        timestamp,
        tz=timezone.utc,
    )

    return dt.strftime(
        "%Y-%m-%d %H:%M:%S UTC"
    )


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

            entry_timestamp REAL NOT NULL,
            expiration_timestamp REAL NOT NULL,

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

            checked_time TEXT
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
        CREATE INDEX IF NOT EXISTS idx_signals_entry
        ON signals(entry_timestamp)
        """
    )

    conn.commit()
    conn.close()

    logger.info(
        f"✅ База готова: {DB_FILE}"
    )


# =====================================================================
# TELEGRAM
# =====================================================================

def telegram_enabled():

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

    if not telegram_enabled():

        return False

    url = (
        f"https://api.telegram.org/bot"
        f"{BOT_TOKEN}/sendMessage"
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
            timeout=TELEGRAM_TIMEOUT,
        )

        if response.status_code != 200:

            logger.error(
                "❌ Telegram HTTP %s: %s",
                response.status_code,
                response.text[:500],
            )

            return False

        result = response.json()

        if not result.get("ok"):

            logger.error(
                f"❌ Telegram API ошибка: "
                f"{result}"
            )

            return False

        logger.info(
            "📨 Telegram сообщение отправлено"
        )

        return True

    except Exception:

        logger.exception(
            "❌ Ошибка отправки Telegram"
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
        "from": format_api_time(start_dt),
        "to": format_api_time(end_dt),
        "detalization": DETAILIZATION,
    }

    for attempt in range(
        1,
        MAX_RETRIES + 1,
    ):

        try:

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

                if attempt < MAX_RETRIES:

                    time.sleep(
                        attempt * 2
                    )

                    continue

                return []

            result = response.json()

            if "errors" in result:

                logger.error(
                    f"❌ API ошибка: "
                    f"{result['errors']}"
                )

                return []

            data = result.get("data")

            if not isinstance(data, list):

                logger.warning(
                    "⚠️ API не вернул data"
                )

                return []

            return data

        except requests.RequestException as e:

            logger.warning(
                f"⚠️ HTTP ошибка: {e}"
            )

            if attempt < MAX_RETRIES:

                time.sleep(
                    attempt * 2
                )

                continue

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

        candle_time = item.get("time")

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

    count, _, _ = get_database_stats()

    if count > 0:

        logger.info(
            f"📚 В базе уже "
            f"{count} свечей"
        )

        return

    logger.info(
        "📥 Загрузка истории..."
    )

    end_dt = utc_now()

    start_dt = (
        end_dt
        - timedelta(
            hours=HISTORY_HOURS
        )
    )

    current = start_dt

    total_saved = 0

    while current < end_dt:

        chunk_end = (
            current
            + timedelta(
                minutes=CHUNK_MINUTES
            )
        )

        if chunk_end > end_dt:

            chunk_end = end_dt

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
            f"💾 Новых свечей: {saved}"
        )

        current = chunk_end

        time.sleep(0.3)

    logger.info(
        f"✅ История загружена. "
        f"Всего: {total_saved}"
    )


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

        return 0

    candles = normalize_candles(raw)

    return save_candles(candles)


# =====================================================================
# CLOSED CANDLES
# =====================================================================

def get_closed_candles(candles):

    now_timestamp = time.time()

    closed = []

    for candle in candles:

        timestamp = candle.get("timestamp")

        if timestamp is None:
            continue

        # Свеча считается закрытой
        if (
            timestamp + CANDLE_SECONDS
            <= now_timestamp
        ):

            closed.append(candle)

    return closed


# =====================================================================
# CANDLE DIRECTION
# =====================================================================

def candle_direction(candle):

    open_price = candle.get("open")
    close_price = candle.get("close")

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

    return [
        candle_direction(candle)
        for candle in candles
    ]


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
#
# ВАЖНО:
# После исторического паттерна смотрим цену
# через EXPIRATION_CANDLES.
#
# То есть прогнозируем именно результат
# через 60 секунд.
# =====================================================================

def find_pattern_matches(
    candles,
    directions,
    pattern,
):

    matches = []

    pattern_length = len(pattern)

    total = len(directions)

    # Текущий паттерн начинается здесь
    current_pattern_start = (
        total - pattern_length
    )

    # Историческому совпадению нужно оставить
    # ещё EXPIRATION_CANDLES после него
    last_possible_start = (
        current_pattern_start
        - EXPIRATION_CANDLES
        - 1
    )

    if last_possible_start < 0:
        return matches

    for start_index in range(
        0,
        last_possible_start + 1,
    ):

        end_pattern_index = (
            start_index
            + pattern_length
        )

        historical_pattern = directions[
            start_index:end_pattern_index
        ]

        if historical_pattern != pattern:
            continue

        # Не используем FLAT
        if (
            "FLAT" in historical_pattern
            or None in historical_pattern
        ):
            continue

        # Цена после окончания паттерна
        entry_candle = candles[
            end_pattern_index - 1
        ]

        entry_price = entry_candle["close"]

        # Цена ровно через 60 секунд
        exit_index = (
            end_pattern_index
            - 1
            + EXPIRATION_CANDLES
        )

        if exit_index >= len(candles):
            continue

        exit_candle = candles[
            exit_index
        ]

        exit_price = exit_candle["close"]

        if exit_price > entry_price:

            direction = "UP"

        elif exit_price < entry_price:

            direction = "DOWN"

        else:

            continue

        matches.append(
            {
                "start_index": start_index,
                "entry_index": (
                    end_pattern_index - 1
                ),
                "exit_index": exit_index,
                "next": direction,
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
        < (
            PATTERN_LENGTH
            + EXPIRATION_CANDLES
            + 10
        )
    ):
        return None

    current_pattern = directions[
        -PATTERN_LENGTH:
    ]

    signal_candle = (
        closed_candles[-1]
    )

    if (
        None in current_pattern
        or "FLAT" in current_pattern
    ):

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
                "есть FLAT/невалидная свеча"
            ),
            "signal_candle": signal_candle,
        }

    matches = find_pattern_matches(
        closed_candles,
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
            "Вероятности равны"
        )

    if (
        prediction
        and confidence < MIN_CONFIDENCE
    ):

        reason = (
            f"Уверенность "
            f"{confidence:.1f}% "
            f"ниже "
            f"{MIN_CONFIDENCE}%"
        )

        prediction = None

    if prediction and not reason:

        reason = (
            "Сигнал соответствует "
            "условиям"
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
# CALCULATE NEXT ENTRY TIME
# =====================================================================

def get_next_entry_timestamp():

    now = time.time()

    # Следующая граница минуты
    next_minute = (
        int(now // 60) * 60
        + 60
    )

    seconds_until_entry = (
        next_minute - now
    )

    # Если до минуты слишком мало времени,
    # переносим ещё на одну минуту
    if (
        seconds_until_entry
        < MIN_SECONDS_BEFORE_ENTRY
    ):

        next_minute += 60

    return float(next_minute)


# =====================================================================
# SIGNAL EXISTS FOR ENTRY
# =====================================================================

def signal_exists_for_entry(
    entry_timestamp,
):

    conn = sqlite3.connect(DB_FILE)

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
# HAS ACTIVE SIGNAL
# =====================================================================

def has_active_signal():

    conn = sqlite3.connect(DB_FILE)

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
# SAVE SIGNAL
# =====================================================================

def save_signal(
    result,
    entry_timestamp,
):

    prediction = result.get("prediction")

    if prediction not in (
        "UP",
        "DOWN",
    ):
        return None

    if signal_exists_for_entry(
        entry_timestamp
    ):

        logger.info(
            "⏭️ Сигнал на это время "
            "уже существует"
        )

        return None

    signal_timestamp = time.time()

    expiration_timestamp = (
        entry_timestamp
        + EXPIRATION_SECONDS
    )

    signal_candle = result.get(
        "signal_candle"
    )

    entry_price = None

    if signal_candle:

        entry_price = signal_candle.get(
            "close"
        )

    conn = sqlite3.connect(DB_FILE)

    cursor = conn.cursor()

    try:

        cursor.execute(
            """
            INSERT INTO signals (

                signal_time,
                signal_timestamp,

                entry_timestamp,
                expiration_timestamp,

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
                ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 0
            )
            """,
            (
                datetime.now(
                    timezone.utc
                ).isoformat(),

                signal_timestamp,

                entry_timestamp,

                expiration_timestamp,

                entry_price,

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

                ",".join(
                    result.get(
                        "pattern",
                        [],
                    )
                ),

                EXPIRATION_SECONDS,
            ),
        )

        signal_id = cursor.lastrowid

        conn.commit()

        return signal_id

    except Exception:

        logger.exception(
            "❌ Ошибка сохранения сигнала"
        )

        return None

    finally:

        conn.close()


# =====================================================================
# TELEGRAM SIGNAL
# =====================================================================

def send_signal_to_telegram(
    result,
    entry_timestamp,
):

    prediction = result.get(
        "prediction"
    )

    if prediction == "UP":

        direction_text = (
            "📈 ВЫШЕ 🟢"
        )

    else:

        direction_text = (
            "📉 НИЖЕ 🔴"
        )

    expiration_timestamp = (
        entry_timestamp
        + EXPIRATION_SECONDS
    )

    text = (
        "🚨 <b>НОВЫЙ СИГНАЛ</b>\n\n"

        f"💱 <b>АКТИВ: {ASSET_NAME}</b>\n\n"

        f"🎯 <b>НАПРАВЛЕНИЕ: "
        f"{direction_text}</b>\n\n"

        f"⏰ <b>ТОЧКА ВХОДА: "
        f"{format_timestamp(entry_timestamp)}</b>\n"

        f"🏁 <b>ОКОНЧАНИЕ: "
        f"{format_timestamp(expiration_timestamp)}</b>\n"

        f"⏳ <b>ЭКСПИРАЦИЯ: "
        f"1 МИНУТА</b>\n\n"

        f"🧩 Паттерн: "
        f"{pattern_to_text(result['pattern'])}\n\n"

        f"🔎 Совпадений: "
        f"<b>{result['matches']}</b>\n"

        f"🟢 Вверх: "
        f"{result['up']} "
        f"({result['up_probability']:.1f}%)\n"

        f"🔴 Вниз: "
        f"{result['down']} "
        f"({result['down_probability']:.1f}%)\n\n"

        f"📊 Уверенность: "
        f"<b>{result['confidence']:.1f}%</b>\n\n"

        "⚡️ <b>ОТКРЫТЬ СДЕЛКУ РОВНО "
        "В УКАЗАННОЕ ВРЕМЯ!</b>"
    )

    return send_telegram_message(
        text
    )


# =====================================================================
# CHECK PENDING SIGNALS
# =====================================================================

def check_pending_signals(candles):

    if not candles:
        return

    now_timestamp = time.time()

    conn = sqlite3.connect(DB_FILE)

    cursor = conn.cursor()

    cursor.execute(
        """
        SELECT
            id,
            signal_time,
            entry_timestamp,
            expiration_timestamp,
            entry_price,
            prediction,
            confidence,
            expiration_seconds
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

        entry_timestamp = signal[2]

        expiration_timestamp = signal[3]

        prediction = signal[5]

        confidence = signal[6]

        expiration_seconds = signal[7]

        # Ждём полного окончания экспирации
        if now_timestamp < expiration_timestamp:

            continue

        # ---------------------------------------------------------
        # ИЩЕМ СВЕЧУ ВХОДА
        # ---------------------------------------------------------

        cursor.execute(
            """
            SELECT
                time,
                timestamp,
                open,
                close
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

        entry_row = cursor.fetchone()

        if not entry_row:

            continue

        real_entry_time = entry_row[0]

        # Для точки входа используем OPEN свечи,
        # начавшейся в момент входа
        real_entry_price = entry_row[2]

        # ---------------------------------------------------------
        # ИЩЕМ ЦЕНУ ПОСЛЕ ЭКСПИРАЦИИ
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
                expiration_timestamp
                - CANDLE_SECONDS,

                CANDLE_SECONDS,

                now_timestamp,
            ),
        )

        exit_row = cursor.fetchone()

        if not exit_row:

            continue

        exit_time = exit_row[0]

        exit_price = exit_row[2]

        # ---------------------------------------------------------
        # RESULT
        # ---------------------------------------------------------

        result = "LOSE"

        if prediction == "UP":

            if exit_price > real_entry_price:

                result = "WIN"

        elif prediction == "DOWN":

            if exit_price < real_entry_price:

                result = "WIN"

        # ---------------------------------------------------------
        # SAVE RESULT
        # ---------------------------------------------------------

        cursor.execute(
            """
            UPDATE signals
            SET

                checked = 1,

                result = ?,

                entry_price = ?,

                exit_price = ?,

                checked_time = ?

            WHERE id = ?
            """,
            (
                result,

                real_entry_price,

                exit_price,

                exit_time,

                signal_id,
            ),
        )

        conn.commit()

        # ---------------------------------------------------------
        # TELEGRAM RESULT
        # ---------------------------------------------------------

        if result == "WIN":

            result_text = (
                "✅ <b>ЗАШЛО!</b>"
            )

        else:

            result_text = (
                "❌ <b>НЕ ЗАШЛО!</b>"
            )

        direction_text = (
            "ВЫШЕ 🟢"
            if prediction == "UP"
            else "НИЖЕ 🔴"
        )

        telegram_text = (
            "🔍 <b>РЕЗУЛЬТАТ СИГНАЛА</b>\n\n"

            f"💱 Актив: "
            f"<b>{ASSET_NAME}</b>\n"

            f"🎯 Прогноз: "
            f"<b>{direction_text}</b>\n\n"

            f"⏰ Вход: "
            f"<b>{format_timestamp(entry_timestamp)}</b>\n"

            f"🏁 Проверка: "
            f"<b>{exit_time}</b>\n\n"

            f"💰 Цена входа: "
            f"<b>{real_entry_price:.6f}</b>\n"

            f"💰 Цена выхода: "
            f"<b>{exit_price:.6f}</b>\n\n"

            f"{result_text}\n\n"

            f"📊 Уверенность прогноза: "
            f"<b>{confidence:.1f}%</b>"
        )

        send_telegram_message(
            telegram_text
        )

        logger.info(
            f"📊 Сигнал #{signal_id}: "
            f"{result}"
        )

    conn.close()


# =====================================================================
# STATISTICS
# =====================================================================

def print_statistics():

    conn = sqlite3.connect(DB_FILE)

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
            wins / total * 100
        )

    logger.info(
        "📊 СТАТИСТИКА | "
        f"Всего: {total} | "
        f"WIN: {wins} | "
        f"LOSE: {losses} | "
        f"Точность: {accuracy:.2f}%"
    )


# =====================================================================
# PRINT ANALYSIS
# =====================================================================

def print_current_analysis(result):

    if not result:
        return

    logger.info(
        "-" * 65
    )

    logger.info(
        f"🧩 Паттерн: "
        f"{pattern_to_text(result['pattern'])}"
    )

    logger.info(
        f"🔎 Совпадений: "
        f"{result['matches']}"
    )

    if result["matches"] > 0:

        logger.info(
            f"🟢 UP: "
            f"{result['up']} "
            f"({result['up_probability']:.1f}%)"
        )

        logger.info(
            f"🔴 DOWN: "
            f"{result['down']} "
            f"({result['down_probability']:.1f}%)"
        )

    if result.get("prediction"):

        logger.info(
            f"🚨 СИГНАЛ ПОДХОДИТ: "
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

        logger.info(
            f"ℹ️ Причина: "
            f"{result.get('reason')}"
        )

    logger.info(
        "-" * 65
    )


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
        f"🕯 Свечи: {DETAILIZATION}"
    )

    logger.info(
        f"🧩 Паттерн: "
        f"{PATTERN_LENGTH} свечей"
    )

    logger.info(
        f"⏳ Экспирация: "
        f"{EXPIRATION_SECONDS} секунд"
    )

    logger.info(
        f"🎯 Мин. совпадений: "
        f"{MIN_MATCHES}"
    )

    logger.info(
        f"📊 Мин. уверенность: "
        f"{MIN_CONFIDENCE}%"
    )

    logger.info(
        f"📨 Telegram заранее: "
        f"{SIGNAL_ADVANCE_SECONDS} сек"
    )

    init_database()

    download_history()

    count, first_time, last_time = (
        get_database_stats()
    )

    logger.info(
        f"📚 Свечей: {count}"
    )

    logger.info(
        f"🕐 История: "
        f"{first_time} -> {last_time}"
    )

    last_analyzed_timestamp = None

    last_planned_entry = None

    cycle = 0

    while True:

        cycle += 1

        try:

            # -----------------------------------------------------
            # UPDATE DATA
            # -----------------------------------------------------

            update_recent_candles()

            candles = (
                load_candles_from_database()
            )

            if not candles:

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

                logger.info(
                    "⏳ Недостаточно данных"
                )

                time.sleep(
                    UPDATE_INTERVAL
                )

                continue

            latest_closed = (
                closed_candles[-1]
            )

            latest_timestamp = (
                latest_closed["timestamp"]
            )

            # -----------------------------------------------------
            # ANALYZE ONLY NEW CLOSED CANDLE
            # -----------------------------------------------------

            if (
                latest_timestamp
                != last_analyzed_timestamp
            ):

                result = analyze_pattern(
                    candles
                )

                last_analyzed_timestamp = (
                    latest_timestamp
                )

                print_current_analysis(
                    result
                )

            else:

                result = None

            # -----------------------------------------------------
            # PLAN NEXT ENTRY
            # -----------------------------------------------------

            now = time.time()

            next_entry = (
                get_next_entry_timestamp()
            )

            seconds_until_entry = (
                next_entry - now
            )

            # Анализируем заранее
            if (
                result
                and result.get("prediction")
                and seconds_until_entry
                <= SIGNAL_ADVANCE_SECONDS
                and seconds_until_entry
                >= MIN_SECONDS_BEFORE_ENTRY
            ):

                # Не создаём повтор
                if (
                    last_planned_entry
                    != next_entry
                ):

                    signal_id = save_signal(
                        result,
                        next_entry,
                    )

                    if signal_id:

                        sent = (
                            send_signal_to_telegram(
                                result,
                                next_entry,
                            )
                        )

                        if sent:

                            last_planned_entry = (
                                next_entry
                            )

                            logger.info(
                                f"🚀 Сигнал #{signal_id} "
                                f"запланирован "
                                f"на "
                                f"{format_timestamp(next_entry)}"
                            )

            # -----------------------------------------------------
            # STATS
            # -----------------------------------------------------

            if cycle % 30 == 0:

                print_statistics()

            time.sleep(
                UPDATE_INTERVAL
            )

        except KeyboardInterrupt:

            logger.info(
                "🛑 Остановка"
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

        print(
            "\n🛑 Бот остановлен."
        )

    except Exception:

        print(
            "\n❌ КРИТИЧЕСКАЯ ОШИБКА:"
        )

        traceback.print_exc()

        sys.exit(1)