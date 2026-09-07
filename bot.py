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

# -------------------------------------------------
# АКТИВ
# -------------------------------------------------

ASSET_ID = 43
ASSET_NAME = "EUR/USD"

# -------------------------------------------------
# СВЕЧИ
# -------------------------------------------------

DETAILIZATION = "5s"
CANDLE_SECONDS = 5

# -------------------------------------------------
# БАЗА
# -------------------------------------------------

DB_FILE = "binarium_history.db"


# =====================================================================
# TELEGRAM
# =====================================================================

BOT_TOKEN = os.getenv("BOT_TOKEN")
CHANNEL_ID = os.getenv("CHANNEL_ID")

TELEGRAM_TIMEOUT = 20


# =====================================================================
# HISTORY
# =====================================================================

HISTORY_HOURS = 12

CHUNK_MINUTES = 60

UPDATE_INTERVAL = 3

LIVE_WINDOW_MINUTES = 10

REQUEST_TIMEOUT = 30
MAX_RETRIES = 3


# =====================================================================
# PATTERN ANALYSIS
# =====================================================================

# Последние закрытые свечи для паттерна
PATTERN_LENGTH = 6

# Минимум исторических совпадений
MIN_MATCHES = 8

# Минимум свечей в базе
MIN_CANDLES_FOR_ANALYSIS = 500

# Минимальная общая вероятность
MIN_CONFIDENCE = 70.0

# Минимальная разница между UP и DOWN
MIN_DIRECTION_ADVANTAGE = 20.0

# -------------------------------------------------
# ПРОВЕРКА СВЕЖИХ СОВПАДЕНИЙ
# -------------------------------------------------

RECENT_MATCHES_TO_CHECK = 10

MIN_RECENT_MATCHES = 4

MIN_RECENT_CONFIDENCE = 60.0


# =====================================================================
# TRADE SETTINGS
# =====================================================================

# Экспирация на Binarium
EXPIRATION_SECONDS = 60

# За сколько секунд до начала минуты
# отправлять сигнал
SIGNAL_ADVANCE_SECONDS = 5


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

    dt = parse_api_time(
        value
    )

    if dt is None:
        return 0.0

    return dt.timestamp()


def timestamp_to_utc_string(timestamp):

    try:

        dt = datetime.fromtimestamp(
            timestamp,
            tz=timezone.utc,
        )

        return dt.strftime(
            "%Y-%m-%d %H:%M:%S UTC"
        )

    except Exception:

        return "Неизвестно"


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

            expiration_timestamp REAL,

            entry_price REAL NOT NULL,

            prediction TEXT NOT NULL,

            confidence REAL NOT NULL,

            matches INTEGER NOT NULL,

            up_count INTEGER NOT NULL,

            down_count INTEGER NOT NULL,

            recent_matches INTEGER DEFAULT 0,

            recent_up INTEGER DEFAULT 0,

            recent_down INTEGER DEFAULT 0,

            recent_confidence REAL DEFAULT 0,

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

    # -------------------------------------------------------------
    # MIGRATION
    # -------------------------------------------------------------

    columns = [
        row[1]
        for row in cursor.execute(
            "PRAGMA table_info(signals)"
        ).fetchall()
    ]

    migrations = {
        "entry_timestamp": (
            "ALTER TABLE signals "
            "ADD COLUMN entry_timestamp REAL"
        ),
        "expiration_timestamp": (
            "ALTER TABLE signals "
            "ADD COLUMN expiration_timestamp REAL"
        ),
        "recent_matches": (
            "ALTER TABLE signals "
            "ADD COLUMN recent_matches INTEGER DEFAULT 0"
        ),
        "recent_up": (
            "ALTER TABLE signals "
            "ADD COLUMN recent_up INTEGER DEFAULT 0"
        ),
        "recent_down": (
            "ALTER TABLE signals "
            "ADD COLUMN recent_down INTEGER DEFAULT 0"
        ),
        "recent_confidence": (
            "ALTER TABLE signals "
            "ADD COLUMN recent_confidence REAL DEFAULT 0"
        ),
        "telegram_sent": (
            "ALTER TABLE signals "
            "ADD COLUMN telegram_sent INTEGER DEFAULT 0"
        ),
        "result_telegram_sent": (
            "ALTER TABLE signals "
            "ADD COLUMN result_telegram_sent INTEGER DEFAULT 0"
        ),
    }

    for column, sql in migrations.items():

        if column not in columns:

            try:

                cursor.execute(sql)

            except Exception:

                logger.exception(
                    f"Ошибка миграции {column}"
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
        "parse_mode": "Markdown",
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
                f"❌ Telegram HTTP "
                f"{response.status_code}: "
                f"{response.text}"
            )

            return False

        result = response.json()

        if not result.get("ok"):

            logger.error(
                f"❌ Telegram API: "
                f"{result}"
            )

            return False

        logger.info(
            "📨 Telegram сообщение отправлено"
        )

        return True

    except Exception as e:

        logger.error(
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

            data = result.get("data")

            if not isinstance(
                data,
                list,
            ):

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

            return []

        except Exception:

            logger.exception(
                "❌ Ошибка запроса свечей"
            )

            return []

    return []


# =====================================================================
# NORMALIZE
# =====================================================================

def normalize_candles(raw_candles):

    result = []

    for item in raw_candles:

        if not isinstance(item, dict):
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
        (ASSET_ID,),
    )

    row = cursor.fetchone()

    conn.close()

    if not row:

        return 0, None, None

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
        (ASSET_ID,),
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
            f"📚 База уже содержит "
            f"{count} свечей"
        )

        return

    logger.info(
        "📥 ПЕРВАЯ ЗАГРУЗКА ИСТОРИИ"
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
            f"💾 Новых свечей: "
            f"{saved}"
        )

        current = chunk_end

        time.sleep(0.3)

    logger.info(
        f"✅ История загружена: "
        f"{total_saved}"
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

    now_timestamp = time.time()

    closed = []

    for candle in candles:

        timestamp = candle.get(
            "timestamp"
        )

        if timestamp is None:
            continue

        if (
            timestamp
            + CANDLE_SECONDS
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
# =====================================================================

def find_pattern_matches(
    directions,
    pattern,
):

    matches = []

    pattern_length = len(pattern)

    current_pattern_start = (
        len(directions)
        - pattern_length
    )

    # Исторический паттерн не должен пересекаться
    # с текущим паттерном
    max_index = (
        current_pattern_start - 1
    )

    for i in range(
        pattern_length,
        max_index + 1,
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
# CALCULATE MATCH STATISTICS
# =====================================================================

def calculate_match_statistics(matches):

    up = sum(
        1
        for match in matches
        if match["next"] == "UP"
    )

    down = sum(
        1
        for match in matches
        if match["next"] == "DOWN"
    )

    total = up + down

    if total <= 0:

        return {
            "total": 0,
            "up": 0,
            "down": 0,
            "up_probability": 0.0,
            "down_probability": 0.0,
            "prediction": None,
            "confidence": 0.0,
            "advantage": 0.0,
        }

    up_probability = (
        up / total * 100
    )

    down_probability = (
        down / total * 100
    )

    prediction = None
    confidence = 0.0

    if up_probability > down_probability:

        prediction = "UP"
        confidence = up_probability

    elif down_probability > up_probability:

        prediction = "DOWN"
        confidence = down_probability

    advantage = abs(
        up_probability
        - down_probability
    )

    return {
        "total": total,
        "up": up,
        "down": down,
        "up_probability": up_probability,
        "down_probability": down_probability,
        "prediction": prediction,
        "confidence": confidence,
        "advantage": advantage,
    }


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

    current_pattern = directions[
        -PATTERN_LENGTH:
    ]

    signal_candle = closed_candles[-1]

    if None in current_pattern:

        return None

    if "FLAT" in current_pattern:

        return {
            "pattern": current_pattern,
            "prediction": None,
            "confidence": 0.0,
            "matches": 0,
            "up": 0,
            "down": 0,
            "up_probability": 0.0,
            "down_probability": 0.0,
            "recent_matches": 0,
            "recent_up": 0,
            "recent_down": 0,
            "recent_confidence": 0.0,
            "reason": "В паттерне есть FLAT",
            "signal_candle": signal_candle,
        }

    matches = find_pattern_matches(
        directions,
        current_pattern,
    )

    overall = calculate_match_statistics(
        matches
    )

    # Последние совпадения ближе к текущему моменту
    recent_matches = matches[
        -RECENT_MATCHES_TO_CHECK:
    ]

    recent = calculate_match_statistics(
        recent_matches
    )

    prediction = None
    confidence = overall["confidence"]
    reason = ""

    # -------------------------------------------------------------
    # FILTER 1 — МАЛО ДАННЫХ
    # -------------------------------------------------------------

    if overall["total"] < MIN_MATCHES:

        reason = (
            f"Недостаточно совпадений: "
            f"{overall['total']}/{MIN_MATCHES}"
        )

    # -------------------------------------------------------------
    # FILTER 2 — НЕТ НАПРАВЛЕНИЯ
    # -------------------------------------------------------------

    elif not overall["prediction"]:

        reason = (
            "Нет явного направления"
        )

    # -------------------------------------------------------------
    # FILTER 3 — ОБЩАЯ УВЕРЕННОСТЬ
    # -------------------------------------------------------------

    elif (
        overall["confidence"]
        < MIN_CONFIDENCE
    ):

        reason = (
            f"Общая уверенность "
            f"{overall['confidence']:.1f}% "
            f"ниже {MIN_CONFIDENCE}%"
        )

    # -------------------------------------------------------------
    # FILTER 4 — ПЕРЕВЕС
    # -------------------------------------------------------------

    elif (
        overall["advantage"]
        < MIN_DIRECTION_ADVANTAGE
    ):

        reason = (
            f"Маленький перевес: "
            f"{overall['advantage']:.1f}%"
        )

    # -------------------------------------------------------------
    # FILTER 5 — СВЕЖАЯ СТАТИСТИКА
    # -------------------------------------------------------------

    elif (
        recent["total"]
        < MIN_RECENT_MATCHES
    ):

        reason = (
            f"Недостаточно свежих совпадений: "
            f"{recent['total']}/"
            f"{MIN_RECENT_MATCHES}"
        )

    # -------------------------------------------------------------
    # FILTER 6 — СВЕЖАЯ СТАТИСТИКА ПРОТИВ
    # -------------------------------------------------------------

    elif (
        recent["prediction"]
        != overall["prediction"]
    ):

        reason = (
            "Свежая статистика "
            "противоречит общей"
        )

    # -------------------------------------------------------------
    # FILTER 7 — СВЕЖАЯ УВЕРЕННОСТЬ
    # -------------------------------------------------------------

    elif (
        recent["confidence"]
        < MIN_RECENT_CONFIDENCE
    ):

        reason = (
            f"Свежая уверенность "
            f"{recent['confidence']:.1f}% "
            f"ниже "
            f"{MIN_RECENT_CONFIDENCE}%"
        )

    # -------------------------------------------------------------
    # SIGNAL APPROVED
    # -------------------------------------------------------------

    else:

        prediction = overall["prediction"]

        reason = (
            "Сигнал прошёл все "
            "статистические фильтры"
        )

    return {
        "pattern": current_pattern,

        "matches": overall["total"],

        "up": overall["up"],
        "down": overall["down"],

        "up_probability":
            overall["up_probability"],

        "down_probability":
            overall["down_probability"],

        "prediction": prediction,

        "confidence": confidence,

        "advantage":
            overall["advantage"],

        "recent_matches":
            recent["total"],

        "recent_up":
            recent["up"],

        "recent_down":
            recent["down"],

        "recent_confidence":
            recent["confidence"],

        "reason": reason,

        "signal_candle":
            signal_candle,
    }


# =====================================================================
# CALCULATE NEXT MINUTE ENTRY
# =====================================================================

def calculate_entry_time():

    now = time.time()

    next_minute = (
        int(now // 60) + 1
    ) * 60

    return float(next_minute)


# =====================================================================
# CHECK ACTIVE SIGNAL
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
# SIGNAL EXISTS
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
        (entry_timestamp,),
    )

    row = cursor.fetchone()

    conn.close()

    return row is not None


# =====================================================================
# GET ENTRY PRICE
# =====================================================================

def get_entry_price(
    candles,
    entry_timestamp,
):

    candidates = []

    for candle in candles:

        timestamp = candle.get(
            "timestamp"
        )

        if timestamp is None:
            continue

        if timestamp >= (
            entry_timestamp
            - CANDLE_SECONDS
        ):

            candidates.append(candle)

    if candidates:

        return candidates[-1].get(
            "close"
        )

    if candles:

        return candles[-1].get(
            "close"
        )

    return None


# =====================================================================
# SAVE SIGNAL
# =====================================================================

def save_signal(
    result,
    candle,
    entry_timestamp,
):

    prediction = result.get(
        "prediction"
    )

    if prediction not in (
        "UP",
        "DOWN",
    ):

        return None

    if has_active_signal():

        logger.info(
            "⏳ Уже есть активный сигнал"
        )

        return None

    if signal_exists_for_entry(
        entry_timestamp
    ):

        logger.info(
            "⏭️ Сигнал на эту минуту "
            "уже существует"
        )

        return None

    entry_price = candle.get("close")

    if entry_price is None:

        return None

    expiration_timestamp = (
        entry_timestamp
        + EXPIRATION_SECONDS
    )

    pattern_text = ",".join(
        result.get("pattern", [])
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

                recent_matches,
                recent_up,
                recent_down,
                recent_confidence,

                pattern,

                expiration_seconds,

                checked

            )
            VALUES (
                ?, ?, ?, ?, ?, ?, ?, ?, ?, ?,
                ?, ?, ?, ?, ?, ?, 0
            )
            """,
            (
                candle.get("time"),
                candle.get("timestamp"),

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

                result.get(
                    "recent_matches",
                    0,
                ),

                result.get(
                    "recent_up",
                    0,
                ),

                result.get(
                    "recent_down",
                    0,
                ),

                result.get(
                    "recent_confidence",
                    0.0,
                ),

                pattern_text,

                EXPIRATION_SECONDS,
            ),
        )

        signal_id = cursor.lastrowid

        conn.commit()

        return {
            "id": signal_id,
            "entry_price": entry_price,
            "entry_timestamp": entry_timestamp,
            "expiration_timestamp":
                expiration_timestamp,
        }

    except Exception:

        logger.exception(
            "❌ Ошибка сохранения сигнала"
        )

        return None

    finally:

        conn.close()


# =====================================================================
# SEND SIGNAL TELEGRAM
# =====================================================================

def send_signal_telegram(
    result,
    signal_data,
):

    prediction = result["prediction"]

    if prediction == "UP":

        direction_text = (
            "🚀 ВЫШЕ 🟢"
        )

    else:

        direction_text = (
            "📉 НИЖЕ 🔴"
        )

    entry_time = timestamp_to_utc_string(
        signal_data["entry_timestamp"]
    )

    expiration_time = timestamp_to_utc_string(
        signal_data[
            "expiration_timestamp"
        ]
    )

    text = (
        "🚨 *НОВЫЙ СИГНАЛ*\n\n"

        f"💱 *Актив:* `{ASSET_NAME}`\n\n"

        f"🎯 *НАПРАВЛЕНИЕ:* "
        f"{direction_text}\n\n"

        f"⏰ *ТОЧКА ВХОДА:*\n"
        f"`{entry_time}`\n\n"

        f"⏱ *ЭКСПИРАЦИЯ:*\n"
        f"`1 МИНУТА`\n\n"

        f"🏁 *ВРЕМЯ ПРОВЕРКИ:*\n"
        f"`{expiration_time}`\n\n"

        f"💰 Ориентир цены: "
        f"`{signal_data['entry_price']}`\n\n"

        f"🧩 Паттерн: "
        f"{pattern_to_text(result['pattern'])}\n\n"

        f"📊 Общая статистика:\n"
        f"🔎 Совпадений: "
        f"*{result['matches']}*\n"
        f"🟢 UP: "
        f"{result['up']} "
        f"({result['up_probability']:.1f}%)\n"
        f"🔴 DOWN: "
        f"{result['down']} "
        f"({result['down_probability']:.1f}%)\n\n"

        f"🔥 Свежая статистика:\n"
        f"🔎 Совпадений: "
        f"{result['recent_matches']}\n"
        f"🟢 UP: "
        f"{result['recent_up']}\n"
        f"🔴 DOWN: "
        f"{result['recent_down']}\n"
        f"🎯 Уверенность: "
        f"{result['recent_confidence']:.1f}%\n\n"

        f"⚡️ *ПРОГНОЗ:* "
        f"*{direction_text}*"
    )

    success = send_telegram_message(
        text
    )

    if success:

        conn = sqlite3.connect(DB_FILE)

        cursor = conn.cursor()

        cursor.execute(
            """
            UPDATE signals
            SET telegram_sent = 1
            WHERE id = ?
            """,
            (signal_data["id"],),
        )

        conn.commit()
        conn.close()

    return success


# =====================================================================
# SEND RESULT TELEGRAM
# =====================================================================

def send_result_telegram(
    signal_id,
    prediction,
    result,
    entry_price,
    exit_price,
    entry_timestamp,
    expiration_timestamp,
):

    if result == "WIN":

        result_text = (
            "✅ *ЗАШЛО!*"
        )

    else:

        result_text = (
            "❌ *НЕ ЗАШЛО*"
        )

    if prediction == "UP":

        prediction_text = "ВЫШЕ 🟢"

    else:

        prediction_text = "НИЖЕ 🔴"

    entry_time = timestamp_to_utc_string(
        entry_timestamp
    )

    exit_time = timestamp_to_utc_string(
        expiration_timestamp
    )

    text = (
        "📊 *РЕЗУЛЬТАТ СИГНАЛА*\n\n"

        f"💱 *Актив:* `{ASSET_NAME}`\n\n"

        f"🎯 Прогноз: "
        f"*{prediction_text}*\n\n"

        f"⏰ Вход: "
        f"`{entry_time}`\n"

        f"🏁 Проверка: "
        f"`{exit_time}`\n\n"

        f"💰 Цена входа: "
        f"`{entry_price}`\n"

        f"💰 Цена выхода: "
        f"`{exit_price}`\n\n"

        f"{result_text}"
    )

    success = send_telegram_message(
        text
    )

    if success:

        conn = sqlite3.connect(DB_FILE)

        cursor = conn.cursor()

        cursor.execute(
            """
            UPDATE signals
            SET result_telegram_sent = 1
            WHERE id = ?
            """,
            (signal_id,),
        )

        conn.commit()
        conn.close()

    return success


# =====================================================================
# CHECK PENDING SIGNALS
# =====================================================================

def check_pending_signals(candles):

    if not candles:
        return

    now = time.time()

    conn = sqlite3.connect(DB_FILE)

    cursor = conn.cursor()

    cursor.execute(
        """
        SELECT
            id,
            signal_time,
            signal_timestamp,

            entry_timestamp,
            expiration_timestamp,

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

        expiration_timestamp = signal[4]

        entry_price = signal[5]

        prediction = signal[6]

        confidence = signal[7]

        expiration_seconds = signal[8]

        result_telegram_sent = signal[9]

        if not expiration_timestamp:

            expiration_timestamp = (
                signal_timestamp
                + expiration_seconds
            )

        # Ждём окончания экспирации
        if now < expiration_timestamp:

            continue

        # Ищем первую полностью закрытую свечу
        # после окончания экспирации

        exit_candle = None

        for candle in candles:

            timestamp = candle.get(
                "timestamp"
            )

            if timestamp is None:
                continue

            candle_close = (
                timestamp
                + CANDLE_SECONDS
            )

            if (
                timestamp
                >= expiration_timestamp
                and candle_close
                <= now
            ):

                exit_candle = candle
                break

        if not exit_candle:

            continue

        exit_price = exit_candle.get(
            "close"
        )

        exit_time = exit_candle.get(
            "time"
        )

        if exit_price is None:

            continue

        result = "LOSE"

        if prediction == "UP":

            if exit_price > entry_price:

                result = "WIN"

        elif prediction == "DOWN":

            if exit_price < entry_price:

                result = "WIN"

        cursor.execute(
            """
            UPDATE signals
            SET
                checked = 1,
                result = ?,
                exit_price = ?,
                checked_time = ?,
                expiration_timestamp = ?
            WHERE id = ?
            """,
            (
                result,
                exit_price,
                exit_time,
                expiration_timestamp,
                signal_id,
            ),
        )

        conn.commit()

        logger.info("")
        logger.info("=" * 65)
        logger.info("🔍 ПРОВЕРКА СИГНАЛА")
        logger.info("=" * 65)

        logger.info(
            f"💱 Актив: {ASSET_NAME}"
        )

        logger.info(
            f"🎯 Прогноз: {prediction}"
        )

        logger.info(
            f"💰 Вход: {entry_price}"
        )

        logger.info(
            f"💰 Выход: {exit_price}"
        )

        logger.info(
            f"📊 Уверенность: "
            f"{confidence:.1f}%"
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

        if not result_telegram_sent:

            send_result_telegram(
                signal_id,
                prediction,
                result,
                entry_price,
                exit_price,
                entry_timestamp,
                expiration_timestamp,
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

    logger.info("")
    logger.info("=" * 65)
    logger.info(
        "📊 СТАТИСТИКА"
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
# PRINT ANALYSIS
# =====================================================================

def print_current_analysis(result):

    if not result:
        return

    logger.info("")
    logger.info("-" * 65)

    logger.info(
        f"💱 Актив: {ASSET_NAME}"
    )

    logger.info(
        f"🧩 Паттерн: "
        f"{pattern_to_text(result['pattern'])}"
    )

    logger.info(
        f"🔎 Всего совпадений: "
        f"{result['matches']}"
    )

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

    logger.info(
        f"📊 Общая уверенность: "
        f"{result['confidence']:.1f}%"
    )

    logger.info(
        f"⚖️ Перевес: "
        f"{result['advantage']:.1f}%"
    )

    logger.info(
        f"🔥 Свежих совпадений: "
        f"{result['recent_matches']}"
    )

    logger.info(
        f"🔥 Свежая уверенность: "
        f"{result['recent_confidence']:.1f}%"
    )

    if result.get("prediction"):

        logger.info(
            f"🚨 СИГНАЛ ОДОБРЕН: "
            f"{result['prediction']}"
        )

    else:

        logger.info(
            "⏭️ Сигнал отклонён"
        )

    logger.info(
        f"ℹ️ {result.get('reason')}"
    )

    logger.info("-" * 65)


# =====================================================================
# WAIT UNTIL SIGNAL WINDOW
# =====================================================================

def is_signal_window():

    now = time.time()

    seconds = now % 60

    # Анализируем ближе к новой минуте
    return (
        seconds
        >= (
            60
            - SIGNAL_ADVANCE_SECONDS
        )
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
        f"🔎 Минимум совпадений: "
        f"{MIN_MATCHES}"
    )

    logger.info(
        f"📊 Мин. уверенность: "
        f"{MIN_CONFIDENCE}%"
    )

    logger.info(
        f"⚖️ Мин. перевес: "
        f"{MIN_DIRECTION_ADVANTAGE}%"
    )

    logger.info(
        f"🔥 Проверка последних: "
        f"{RECENT_MATCHES_TO_CHECK}"
    )

    logger.info(
        f"⏱ Экспирация: "
        f"{EXPIRATION_SECONDS} секунд"
    )

    logger.info(
        f"📨 Telegram: "
        f"{'ВКЛ' if telegram_enabled() else 'ВЫКЛ'}"
    )

    # -------------------------------------------------------------
    # DATABASE
    # -------------------------------------------------------------

    init_database()

    # -------------------------------------------------------------
    # HISTORY
    # -------------------------------------------------------------

    download_history()

    count, first_time, last_time = (
        get_database_stats()
    )

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

    last_analyzed_minute = None

    # -------------------------------------------------------------
    # LOOP
    # -------------------------------------------------------------

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
            # CHECK RESULTS ALWAYS
            # -----------------------------------------------------

            check_pending_signals(
                candles
            )

            # -----------------------------------------------------
            # MINIMUM DATA
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
                    "⏳ Недостаточно свечей"
                )

                time.sleep(
                    UPDATE_INTERVAL
                )

                continue

            # -----------------------------------------------------
            # SIGNAL WINDOW
            # -----------------------------------------------------

            if not is_signal_window():

                time.sleep(
                    UPDATE_INTERVAL
                )

                continue

            # -----------------------------------------------------
            # CURRENT TARGET MINUTE
            # -----------------------------------------------------

            entry_timestamp = (
                calculate_entry_time()
            )

            entry_minute = (
                int(entry_timestamp)
            )

            # Уже анализировали эту минуту
            if (
                entry_minute
                == last_analyzed_minute
            ):

                time.sleep(1)

                continue

            last_analyzed_minute = (
                entry_minute
            )

            logger.info("")
            logger.info("=" * 70)
            logger.info(
                "🔮 АНАЛИЗ ПЕРЕД ВХОДОМ"
            )
            logger.info("=" * 70)

            logger.info(
                f"⏰ Следующий вход: "
                f"{timestamp_to_utc_string(entry_timestamp)}"
            )

            # -----------------------------------------------------
            # ANALYZE
            # -----------------------------------------------------

            result = analyze_pattern(
                candles
            )

            print_current_analysis(
                result
            )

            if not result:

                continue

            if not result.get(
                "prediction"
            ):

                continue

            # -----------------------------------------------------
            # SAVE SIGNAL
            # -----------------------------------------------------

            signal_candle = (
                result.get(
                    "signal_candle"
                )
            )

            if not signal_candle:

                continue

            signal_data = save_signal(
                result,
                signal_candle,
                entry_timestamp,
            )

            if not signal_data:

                continue

            # -----------------------------------------------------
            # TELEGRAM
            # -----------------------------------------------------

            send_signal_telegram(
                result,
                signal_data,
            )

            # -----------------------------------------------------
            # STATISTICS
            # -----------------------------------------------------

            if cycle % 20 == 0:

                print_statistics()

            time.sleep(1)

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