import os
import sys
import json
import re
import time
import pickle
import traceback
from datetime import datetime, timedelta
from collections import defaultdict

import numpy as np
import requests
import pytz
from sklearn.linear_model import SGDClassifier
from sklearn.preprocessing import StandardScaler


# =====================================================================
# ENV
# =====================================================================

BOT_TOKEN = os.getenv("BOT_TOKEN") or os.getenv("BOT_TOKEN_PROGNOZ_BACCARA")
CHANNEL_STATS = os.getenv("CHANNEL_STATS_BACCARA")
CHANNEL_PROGNOZ = os.getenv("CHANNEL_PROGNOZ_BACCARA")

if not BOT_TOKEN or not CHANNEL_STATS or not CHANNEL_PROGNOZ:
    print(
        "❌ ОШИБКА: переменные окружения для баккары не заданы!",
        flush=True
    )
    sys.exit(1)

CHANNEL_STATS = str(CHANNEL_STATS).strip()
CHANNEL_PROGNOZ = str(CHANNEL_PROGNOZ).strip()

MOSCOW_TZ = pytz.timezone("Europe/Moscow")

BASE_URL = "https://1xlite-0687.pro"


# =====================================================================
# FILES / SETTINGS
# =====================================================================

CARDS_DATA_FILE = "cards_data.json"
HISTORY_FILE = "cards_history_baccarat.json"
OFFSET_FILE = "cards_offset_baccarat.txt"

MODEL_FILE = "baccarat_sgd_model.pkl"
SCANNER_FILE = "baccarat_pattern_scanner.pkl"

# Новая отдельная статистика аналитики
ANALYTICS_FILE = "baccarat_analytics.json"

DOGON_GAMES = 4

CHECK_INTERVAL = 5
MAX_RECORDS = 3000

MIN_TRAIN_SAMPLES = 50

ML_CONFIDENCE_THRESHOLD = 0.20

# Раз в час
ANALYTICS_INTERVAL = 3600


# =====================================================================
# PATTERN SCANNER
# =====================================================================

PATTERN_MIN_SUPPORT = 12
PATTERN_MIN_PRECISION = 0.35
PATTERN_MIN_LIFT = 1.10
PATTERN_MAX_FEATURES = 160

PATTERN_LAGS = (
    1,
    2,
    3,
    4,
    5,
    6,
    8,
    10,
)

PATTERN_WINDOWS = (
    3,
    5,
    8,
    12,
    20,
)


# =====================================================================
# SUITS
# =====================================================================

TARGET_SUITS = [
    "♠️",
    "♣️",
    "♦️",
    "♥️",
]

SUIT_TO_INDEX = {
    suit: i
    for i, suit in enumerate(TARGET_SUITS)
}

INDEX_TO_SUIT = {
    i: suit
    for i, suit in enumerate(TARGET_SUITS)
}

MIRROR_SUITS = {
    "♣️": "♥️",
    "♥️": "♣️",
    "♠️": "♦️",
    "♦️": "♠️",
}


# =====================================================================
# API SETTINGS
# =====================================================================

SPORT_ID = 236
LIGA_ID = 2050671
GR = 415

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36"
    ),
    "Accept": "application/json, text/plain, */*",
    "Referer": (
        f"{BASE_URL}/ru/live/baccarat/"
        f"{LIGA_ID}-baccara"
    ),
    "Cookie": (
        "platform_type=desktop; "
        "lng=ru; "
        "cookies_agree_type=3; "
        "tzo=3; "
        "is12h=0"
    ),
}


# =====================================================================
# GLOBALS
# =====================================================================

predictions = []

seen_upcoming_games = set()

games_cache = {}

ml_model = None
ml_scaler = None
ml_last_train_count = 0

scanner_patterns = []
scanner_last_train_count = 0


# =====================================================================
# MAIN STATS
# =====================================================================

stats = {
    "total": 0,
    "win": 0,
    "lose": 0,

    "by_dogon": {
        0: 0,
        1: 0,
        2: 0,
        3: 0,
    },

    "suit_hits": defaultdict(int),

    "model": {
        "total": 0,
        "win": 0,
        "lose": 0,
    },
}


# =====================================================================
# SOURCE ANALYTICS
# =====================================================================
#
# Отдельная реальная статистика:
#
# ML       - чистая модель SGD
# PATTERN  - чистый Pattern Scanner
# COMBINED - 85% ML + 15% Pattern
#
# =====================================================================

analytics = {
    "ml": {
        "total": 0,
        "win": 0,
        "lose": 0,
    },

    "pattern": {
        "total": 0,
        "win": 0,
        "lose": 0,
    },

    "combined": {
        "total": 0,
        "win": 0,
        "lose": 0,
    },

    "agreement": 0,
    "disagreement": 0,
}


# =====================================================================
# ANALYTICS LOAD
# =====================================================================

def load_analytics():

    global analytics

    if not os.path.exists(ANALYTICS_FILE):
        print(
            "📊 Файл аналитики пока не создан",
            flush=True
        )
        return

    try:

        with open(
            ANALYTICS_FILE,
            "r",
            encoding="utf-8"
        ) as f:

            data = json.load(f)

        if not isinstance(data, dict):
            return

        for source in (
            "ml",
            "pattern",
            "combined",
        ):

            if isinstance(
                data.get(source),
                dict
            ):

                analytics[source] = {
                    "total": int(
                        data[source].get(
                            "total",
                            0
                        )
                    ),

                    "win": int(
                        data[source].get(
                            "win",
                            0
                        )
                    ),

                    "lose": int(
                        data[source].get(
                            "lose",
                            0
                        )
                    ),
                }

        analytics["agreement"] = int(
            data.get(
                "agreement",
                0
            )
        )

        analytics["disagreement"] = int(
            data.get(
                "disagreement",
                0
            )
        )

        print(
            "📊 Аналитика загружена",
            flush=True
        )

    except Exception as e:

        print(
            f"⚠️ Ошибка загрузки аналитики: {e}",
            flush=True
        )


# =====================================================================
# ANALYTICS SAVE
# =====================================================================

def save_analytics():

    try:

        tmp = ANALYTICS_FILE + ".tmp"

        with open(
            tmp,
            "w",
            encoding="utf-8"
        ) as f:

            json.dump(
                analytics,
                f,
                indent=2,
                ensure_ascii=False
            )

        os.replace(
            tmp,
            ANALYTICS_FILE
        )

        return True

    except Exception as e:

        print(
            f"⚠️ Ошибка сохранения аналитики: {e}",
            flush=True
        )

        return False


# =====================================================================
# SOURCE ACCURACY
# =====================================================================

def get_source_accuracy(source):

    source_data = analytics.get(
        source,
        {}
    )

    total = int(
        source_data.get(
            "total",
            0
        )
    )

    wins = int(
        source_data.get(
            "win",
            0
        )
    )

    if total <= 0:
        return 0.0

    return (
        wins
        / total
        * 100
    )


# =====================================================================
# PROGRESS BAR
# =====================================================================

def make_progress_bar(
    percent,
    length=14
):

    percent = max(
        0.0,
        min(
            100.0,
            float(percent)
        )
    )

    filled = round(
        length
        * percent
        / 100
    )

    return (
        "█" * filled
        +
        "░" * (
            length - filled
        )
    )


# =====================================================================
# BEST SOURCE
# =====================================================================

def get_best_source():

    values = {}

    if analytics["ml"]["total"] > 0:
        values["ML"] = get_source_accuracy(
            "ml"
        )

    if analytics["pattern"]["total"] > 0:
        values["PATTERN"] = get_source_accuracy(
            "pattern"
        )

    if analytics["combined"]["total"] > 0:
        values["COMBINED"] = get_source_accuracy(
            "combined"
        )

    if not values:
        return "НЕТ ДАННЫХ"

    return max(
        values,
        key=values.get
    )


# =====================================================================
# BUILD ANALYTICS MESSAGE
# =====================================================================

def build_analytics_message():

    ml_accuracy = get_source_accuracy(
        "ml"
    )

    pattern_accuracy = get_source_accuracy(
        "pattern"
    )

    combined_accuracy = get_source_accuracy(
        "combined"
    )

    agreement = int(
        analytics.get(
            "agreement",
            0
        )
    )

    disagreement = int(
        analytics.get(
            "disagreement",
            0
        )
    )

    decisions = (
        agreement
        +
        disagreement
    )

    if decisions > 0:

        agreement_percent = (
            agreement
            / decisions
            * 100
        )

        disagreement_percent = (
            disagreement
            / decisions
            * 100
        )

    else:

        agreement_percent = 0.0
        disagreement_percent = 0.0

    best_source = get_best_source()

    now = datetime.now(
        MOSCOW_TZ
    ).strftime(
        "%H:%M:%S"
    )

    return (
        "📊 <b>АНАЛИТИКА ПРОГНОЗОВ</b>\n\n"

        "🤖 <b>ML</b>\n"
        f"{make_progress_bar(ml_accuracy)} "
        f"<b>{ml_accuracy:.1f}%</b>\n"
        f"Прогнозов: {analytics['ml']['total']} | "
        f"Зашло: {analytics['ml']['win']}\n\n"

        "🔎 <b>PATTERN</b>\n"
        f"{make_progress_bar(pattern_accuracy)} "
        f"<b>{pattern_accuracy:.1f}%</b>\n"
        f"Прогнозов: {analytics['pattern']['total']} | "
        f"Зашло: {analytics['pattern']['win']}\n\n"

        "⚖️ <b>COMBINED</b>\n"
        f"{make_progress_bar(combined_accuracy)} "
        f"<b>{combined_accuracy:.1f}%</b>\n"
        f"Прогнозов: {analytics['combined']['total']} | "
        f"Зашло: {analytics['combined']['win']}\n\n"

        "────────────────\n\n"

        "🧠 <b>Согласие ML + Pattern:</b> "
        f"{agreement_percent:.1f}%\n"

        "⚔️ <b>Расхождение ML / Pattern:</b> "
        f"{disagreement_percent:.1f}%\n\n"

        f"🏆 <b>Лучший источник: {best_source}</b>\n\n"

        f"🕒 Обновлено: {now}"
    )


# =====================================================================
# SEND HOURLY ANALYTICS
# =====================================================================

def send_hourly_analytics():

    text = build_analytics_message()

    msg_id = send_message(
        CHANNEL_PROGNOZ,
        text
    )

    if msg_id:

        print(
            "📊 Почасовая аналитика отправлена",
            flush=True
        )

        return True

    return False


# =====================================================================
# UPDATE SOURCE ANALYTICS
# =====================================================================

def update_source_analytics(
    source,
    hit
):

    if source not in (
        "ml",
        "pattern",
        "combined",
    ):
        return

    analytics[source]["total"] += 1

    if hit:

        analytics[source]["win"] += 1

    else:

        analytics[source]["lose"] += 1


# =====================================================================
# TELEGRAM
# =====================================================================

def telegram_request(
    method,
    payload=None,
    timeout=20
):

    url = (
        f"https://api.telegram.org/"
        f"bot{BOT_TOKEN}/{method}"
    )

    try:

        response = requests.post(
            url,
            json=payload or {},
            timeout=timeout
        )

        if response.status_code != 200:
            return None

        data = response.json()

        if not data.get("ok"):
            return None

        return data

    except Exception:

        return None


def send_message(
    chat_id,
    text
):

    result = telegram_request(
        "sendMessage",
        {
            "chat_id": chat_id,
            "text": text,
            "parse_mode": "HTML",
        },
        timeout=15
    )

    if not result:
        return None

    return (
        result
        .get(
            "result",
            {}
        )
        .get(
            "message_id"
        )
    )


def edit_message(
    message_id,
    text
):

    return bool(
        telegram_request(
            "editMessageText",
            {
                "chat_id": CHANNEL_PROGNOZ,
                "message_id": message_id,
                "text": text,
                "parse_mode": "HTML",
            },
            timeout=15
        )
    )


# =====================================================================
# DATA
# =====================================================================

def load_data():

    if not os.path.exists(
        CARDS_DATA_FILE
    ):
        return []

    try:

        with open(
            CARDS_DATA_FILE,
            "r",
            encoding="utf-8"
        ) as f:

            data = json.load(f)

        if isinstance(
            data,
            list
        ):
            return data

        if isinstance(
            data,
            dict
        ):

            for key in (
                "data",
                "games",
                "records",
                "items",
                "history",
                "cards",
            ):

                if isinstance(
                    data.get(key),
                    list
                ):

                    return data[key]

    except Exception as e:

        print(
            f"⚠️ Ошибка загрузки {CARDS_DATA_FILE}: {e}",
            flush=True
        )

    return []


def save_data(data):

    try:

        data = data[
            -MAX_RECORDS:
        ]

        tmp = (
            CARDS_DATA_FILE
            + ".tmp"
        )

        with open(
            tmp,
            "w",
            encoding="utf-8"
        ) as f:

            json.dump(
                data,
                f,
                indent=2,
                ensure_ascii=False
            )

        os.replace(
            tmp,
            CARDS_DATA_FILE
        )

        return True

    except Exception as e:

        print(
            f"⚠️ Ошибка сохранения {CARDS_DATA_FILE}: {e}",
            flush=True
        )

        return False


def load_history():

    if not os.path.exists(
        HISTORY_FILE
    ):
        return []

    try:

        with open(
            HISTORY_FILE,
            "r",
            encoding="utf-8"
        ) as f:

            data = json.load(f)

        return (
            data
            if isinstance(
                data,
                list
            )
            else []
        )

    except Exception:

        return []


def save_history(history):

    try:

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

    except Exception:
        pass


def get_offset():

    try:

        with open(
            OFFSET_FILE,
            "r",
            encoding="utf-8"
        ) as f:

            return int(
                f.read().strip()
            )

    except Exception:

        return 0


def save_offset(offset):

    try:

        with open(
            OFFSET_FILE,
            "w",
            encoding="utf-8"
        ) as f:

            f.write(
                str(offset)
            )

    except Exception:
        pass


# =====================================================================
# NORMALIZATION
# =====================================================================

def normalize_suit(suit):

    if not suit:
        return None

    s = str(suit)

    s = (
        s
        .replace(
            "\ufe0f",
            ""
        )
        .strip()
    )

    mapping = {
        "♠": "♠️",
        "♣": "♣️",
        "♦": "♦️",
        "♥": "♥️",
    }

    return mapping.get(
        s
    )


# =====================================================================
# PARSING CARDS
# =====================================================================

def extract_player_cards(record):

    if not isinstance(
        record,
        dict
    ):
        return []

    cards = record.get(
        "player_cards",
        []
    )

    if not isinstance(
        cards,
        list
    ):
        return []

    result = []

    for card in cards:

        if isinstance(
            card,
            dict
        ):

            suit = normalize_suit(
                card.get(
                    "suit"
                )
            )

            rank = str(
                card.get(
                    "rank",
                    ""
                )
            )

            if suit in TARGET_SUITS:

                result.append(
                    {
                        "rank": rank,
                        "suit": suit,
                    }
                )

        elif isinstance(
            card,
            str
        ):

            match = re.search(
                r"(10|[2-9AJQK])([♠♣♦♥])",
                card.replace(
                    "\ufe0f",
                    ""
                )
            )

            if match:

                result.append(
                    {
                        "rank": match.group(1),
                        "suit": normalize_suit(
                            match.group(2)
                        ),
                    }
                )

    return result


def extract_player_suits(record):

    return [
        card["suit"]
        for card in extract_player_cards(
            record
        )
        if card.get("suit")
        in TARGET_SUITS
    ]


def parse_suits_from_text(text):
    """
    Берём только PLAYER-группу после #N...
    """

    if not text:
        return []

    try:

        clean = (
            str(text)
            .replace(
                "\ufe0f",
                ""
            )
        )

        match = re.search(
            r"#N\d+\.\s*"
            r"(?:[✅❌🔮]\s*)?"
            r"\d+\(([^)]*)\)",
            clean
        )

        if not match:
            return []

        suits = []

        for suit in re.findall(
            r"(?:10|[2-9AJQK])([♠♣♦♥])",
            match.group(1)
        ):

            normalized = normalize_suit(
                suit
            )

            if normalized:

                suits.append(
                    normalized
                )

        return suits

    except Exception:

        return []


def parse_full_cards_from_text(text):

    if not text:
        return []

    try:

        clean = (
            str(text)
            .replace(
                "\ufe0f",
                ""
            )
        )

        match = re.search(
            r"#N\d+\.\s*"
            r"(?:[✅❌🔮]\s*)?"
            r"\d+\(([^)]*)\)",
            clean
        )

        if not match:
            return []

        result = []

        for rank, suit in re.findall(
            r"(10|[2-9AJQK])([♠♣♦♥])",
            match.group(1)
        ):

            result.append(
                {
                    "rank": rank,
                    "suit": normalize_suit(
                        suit
                    ),
                }
            )

        return result

    except Exception:

        return []


# =====================================================================
# TIME / GAME NUMBER
# =====================================================================

def get_game_number_from_timestamp(ts):

    if not ts:
        return None

    try:

        if isinstance(
            ts,
            (int, float)
        ):

            dt = datetime.fromtimestamp(
                ts,
                MOSCOW_TZ
            )

        else:

            dt = datetime.fromisoformat(
                str(ts).replace(
                    "Z",
                    "+00:00"
                )
            )

            if dt.tzinfo is None:

                dt = MOSCOW_TZ.localize(
                    dt
                )

            else:

                dt = dt.astimezone(
                    MOSCOW_TZ
                )

    except Exception:

        return None

    start = dt.replace(
        hour=3,
        minute=0,
        second=0,
        microsecond=0
    )

    if dt < start:

        start -= timedelta(
            days=1
        )

    minutes = int(
        (
            dt - start
        ).total_seconds()
        // 60
    )

    return (
        minutes % 1440
    ) + 1


def add_game_offset(
    num,
    offset
):

    return (
        (
            int(num)
            - 1
            + int(offset)
        )
        % 1440
    ) + 1


# =====================================================================
# DATA-DRIVEN PATTERN SCANNER
# =====================================================================

def record_signature(record):

    suits = extract_player_suits(
        record
    )

    ranks = [
        str(
            card.get(
                "rank",
                "?"
            )
        )
        for card
        in extract_player_cards(
            record
        )
    ]

    return {
        "suits": set(suits),

        "ranks": ranks,

        "count": len(suits),

        "lat": float(
            record.get(
                "latency_ms"
            )
            or 0.0
        ),

        "state": str(
            record.get(
                "state",
                ""
            )
        ),

        "game_num": (
            int(
                record.get(
                    "game_number"
                )
            )
            if str(
                record.get(
                    "game_number",
                    ""
                )
            ).isdigit()
            else get_game_number_from_timestamp(
                record.get(
                    "timestamp_msk"
                )
            )
        ),
    }


def build_scanner_feature_map(
    data,
    idx
):

    """
    Признаки строятся только по истории до текущей игры.

    Миллисекунды полностью исключены из прогнозной логики.

    Модель работает по игровой истории.
    """

    features = {}

    if idx <= 0:
        return features

    current = record_signature(
        data[idx - 1]
    )

    history = [
        record_signature(record)
        for record in data[:idx]
    ]

    # -------------------------------------------------------------
    # LAG FEATURES
    # -------------------------------------------------------------

    for lag in PATTERN_LAGS:

        if idx - lag - 1 < 0:
            continue

        historical = history[
            -1 - lag
        ]

        for suit in TARGET_SUITS:

            features[
                f"lag{lag}_p_{suit}"
            ] = int(
                suit
                in historical["suits"]
            )

        features[
            f"lag{lag}_cards"
        ] = historical["count"]

        state = historical["state"]

        features[
            f"lag{lag}_state_{state}"
        ] = 1

    # -------------------------------------------------------------
    # WINDOW FEATURES
    # -------------------------------------------------------------

    for window in PATTERN_WINDOWS:

        sequence = history[
            -window:
        ]

        if not sequence:
            continue

        for suit in TARGET_SUITS:

            values = [
                int(
                    suit
                    in historical["suits"]
                )
                for historical
                in sequence
            ]

            features[
                f"win{window}_cnt_{suit}"
            ] = sum(values)

            features[
                f"win{window}_rate_{suit}"
            ] = (
                sum(values)
                / len(values)
            )

            features[
                f"win{window}_last_{suit}"
            ] = values[-1]

            features[
                f"win{window}_streak_{suit}"
            ] = _tail_streak(
                values
            )

        features[
            f"win{window}_avg_cards"
        ] = (
            sum(
                historical["count"]
                for historical
                in sequence
            )
            / len(sequence)
        )

        features[
            f"win{window}_avg_latency"
        ] = (
            sum(
                historical["lat"]
                for historical
                in sequence
            )
            / len(sequence)
        )

    # -------------------------------------------------------------
    # PREVIOUS GAME
    # -------------------------------------------------------------

    features[
        "prev_cards"
    ] = current["count"]

    features[
        "prev_latency"
    ] = current["lat"]

    # -------------------------------------------------------------
    # TRANSITIONS
    # -------------------------------------------------------------

    if idx >= 2:

        previous_2 = history[-2]

        for suit_a in TARGET_SUITS:

            for suit_b in TARGET_SUITS:

                features[
                    f"transition_{suit_a}_{suit_b}"
                ] = int(
                    suit_a
                    in previous_2["suits"]
                    and
                    suit_b
                    in current["suits"]
                )

    return features


def _tail_streak(values):

    count = 0

    for value in reversed(values):

        if value:
            count += 1

        else:
            break

    return count


# =====================================================================
# TARGET
# =====================================================================

def target_presence(record):

    suits = set(
        extract_player_suits(
            record
        )
    )

    return np.array(
        [
            1
            if suit in suits
            else 0
            for suit
            in TARGET_SUITS
        ],
        dtype=int
    )


# =====================================================================
# PATTERN SCANNER TRAINING
# =====================================================================

def train_pattern_scanner(data):

    global scanner_patterns
    global scanner_last_train_count

    if len(data) < MIN_TRAIN_SAMPLES:
        return False

    feature_rows = []
    targets = []

    for i in range(
        1,
        len(data)
    ):

        features = build_scanner_feature_map(
            data,
            i
        )

        if not features:
            continue

        feature_rows.append(
            features
        )

        targets.append(
            target_presence(
                data[i]
            )
        )

    if len(feature_rows) < MIN_TRAIN_SAMPLES:
        return False

    names = sorted(
        {
            key
            for row
            in feature_rows
            for key
            in row
        }
    )

    target_array = np.array(
        targets
    )

    baseline = np.mean(
        target_array,
        axis=0
    )

    discovered = []

    for name in names:

        values = np.array(
            [
                row.get(
                    name,
                    0.0
                )
                for row
                in feature_rows
            ],
            dtype=float
        )

        if np.all(
            values == values[0]
        ):
            continue

        mask = values > 0

        support = int(
            mask.sum()
        )

        if (
            support < PATTERN_MIN_SUPPORT
            or support
            < len(values) * 0.02
        ):
            continue

        for class_idx, suit in enumerate(
            TARGET_SUITS
        ):

            precision = float(
                np.mean(
                    target_array[
                        mask,
                        class_idx
                    ]
                )
            )

            if baseline[class_idx] <= 0:
                continue

            lift = (
                precision
                / float(
                    baseline[class_idx]
                )
            )

            if (
                precision
                >= PATTERN_MIN_PRECISION
                and
                lift
                >= PATTERN_MIN_LIFT
            ):

                discovered.append(
                    {
                        "feature": name,
                        "suit": suit,
                        "support": support,
                        "precision": precision,
                        "lift": lift,
                    }
                )

    discovered.sort(
        key=lambda x: (
            x["lift"]
            * x["precision"],
            x["support"]
        ),
        reverse=True
    )

    scanner_patterns = discovered[
        :PATTERN_MAX_FEATURES
    ]

    scanner_last_train_count = len(
        data
    )

    try:

        with open(
            SCANNER_FILE,
            "wb"
        ) as f:

            pickle.dump(
                scanner_patterns,
                f
            )

    except Exception:
        pass

    print(
        "🔎 Pattern Scanner: "
        f"найдено {len(scanner_patterns)} "
        "рабочих паттернов",
        flush=True
    )

    return True


# =====================================================================
# LOAD PATTERN SCANNER
# =====================================================================

def load_pattern_scanner():

    global scanner_patterns

    try:

        with open(
            SCANNER_FILE,
            "rb"
        ) as f:

            patterns = pickle.load(
                f
            )

        if isinstance(
            patterns,
            list
        ):

            scanner_patterns = patterns

    except Exception:

        scanner_patterns = []


# =====================================================================
# PATTERN SCORES
# =====================================================================

def scanner_scores_for_target(
    data,
    target_record
):

    if (
        not scanner_patterns
        or not data
    ):

        return {
            suit: 0.0
            for suit
            in TARGET_SUITS
        }

    temp = list(data)

    target_copy = dict(
        target_record
    )

    target_copy[
        "player_cards"
    ] = []

    target_copy[
        "dealer_cards"
    ] = []

    target_copy[
        "sequence"
    ] = []

    temp.append(
        target_copy
    )

    features = build_scanner_feature_map(
        temp,
        len(temp) - 1
    )

    scores = defaultdict(float)
    weights = defaultdict(float)

    for pattern in scanner_patterns:

        value = float(
            features.get(
                pattern["feature"],
                0.0
            )
        )

        if value <= 0:
            continue

        weight = max(
            0.0,
            (
                pattern["lift"]
                - 1.0
            )
            * pattern["precision"]
        )

        scores[
            pattern["suit"]
        ] += (
            value
            * weight
        )

        weights[
            pattern["suit"]
        ] += value

    return {
        suit: (
            scores[suit]
            / weights[suit]
            if weights[suit]
            else 0.0
        )
        for suit
        in TARGET_SUITS
    }


# =====================================================================
# ML FEATURE VECTOR
# =====================================================================

def scanner_feature_vector(
    data,
    target_record
):

    temp = list(data)

    target_copy = dict(
        target_record
    )

    target_copy[
        "player_cards"
    ] = []

    target_copy[
        "dealer_cards"
    ] = []

    target_copy[
        "sequence"
    ] = []

    temp.append(
        target_copy
    )

    features = build_scanner_feature_map(
        temp,
        len(temp) - 1
    )

    return features


# =====================================================================
# ML TRAINING DATA
# =====================================================================

def build_ml_training(data):

    rows = []
    targets = []

    for i in range(
        1,
        len(data)
    ):

        features = build_scanner_feature_map(
            data,
            i
        )

        if not features:
            continue

        rows.append(
            features
        )

        targets.append(
            target_presence(
                data[i]
            )
        )

    if not rows:
        return None, None, None

    names = sorted(
        {
            key
            for row
            in rows
            for key
            in row
        }
    )

    X = np.array(
        [
            [
                float(
                    row.get(
                        name,
                        0.0
                    )
                )
                for name
                in names
            ]
            for row
            in rows
        ],
        dtype=float
    )

    Y = np.array(
        targets,
        dtype=int
    )

    return (
        X,
        Y,
        names
    )


# =====================================================================
# TRAIN SGD MODEL
# =====================================================================

def train_ml_model():

    global ml_model
    global ml_scaler
    global ml_last_train_count

    data = load_data()

    if len(data) < MIN_TRAIN_SAMPLES:

        print(
            f"⏳ SGD: "
            f"{len(data)}/{MIN_TRAIN_SAMPLES}",
            flush=True
        )

        return False

    X, Y, names = build_ml_training(
        data
    )

    if (
        X is None
        or len(X)
        < MIN_TRAIN_SAMPLES
    ):
        return False

    try:

        scaler = StandardScaler()

        X_scaled = scaler.fit_transform(
            X
        )

        estimators = []

        for j in range(4):

            classifier = SGDClassifier(
                loss="log_loss",
                max_iter=2500,
                tol=1e-3,
                random_state=42 + j,
                class_weight="balanced",
            )

            classifier.fit(
                X_scaled,
                Y[:, j]
            )

            estimators.append(
                classifier
            )

        ml_model = {
            "estimators": estimators,
            "feature_names": names,
        }

        ml_scaler = scaler

        ml_last_train_count = len(
            data
        )

        with open(
            MODEL_FILE,
            "wb"
        ) as f:

            pickle.dump(
                {
                    "model": ml_model,
                    "scaler": ml_scaler,
                },
                f
            )

        print(
            "🤖 SGD обучен: "
            f"{len(X)} примеров | "
            f"{X.shape[1]} признаков | "
            "4 масти",
            flush=True
        )

        return True

    except Exception as e:

        print(
            f"❌ Ошибка обучения SGD: {e}",
            flush=True
        )

        ml_model = None
        ml_scaler = None

        return False


# =====================================================================
# LOAD MODEL
# =====================================================================

def load_ml_model():

    global ml_model
    global ml_scaler

    try:

        with open(
            MODEL_FILE,
            "rb"
        ) as f:

            obj = pickle.load(
                f
            )

        ml_model = obj.get(
            "model"
        )

        ml_scaler = obj.get(
            "scaler"
        )

        return bool(
            ml_model
            and ml_scaler
        )

    except Exception:

        return False


# =====================================================================
# MODEL PREDICTION
# =====================================================================

def get_ml_prediction(
    data,
    target_record
):

    if (
        not ml_model
        or ml_scaler is None
    ):

        return {}, 0.0

    try:

        features = scanner_feature_vector(
            data,
            target_record
        )

        names = ml_model[
            "feature_names"
        ]

        X = np.array(
            [
                [
                    float(
                        features.get(
                            name,
                            0.0
                        )
                    )
                    for name
                    in names
                ]
            ],
            dtype=float
        )

        X_scaled = ml_scaler.transform(
            X
        )

        result = {}

        for i, classifier in enumerate(
            ml_model["estimators"]
        ):

            probabilities = (
                classifier
                .predict_proba(
                    X_scaled
                )[0]
            )

            if 1 in classifier.classes_:

                class_index = list(
                    classifier.classes_
                ).index(1)

                probability = float(
                    probabilities[
                        class_index
                    ]
                )

            else:

                probability = 0.0

            result[
                TARGET_SUITS[i]
            ] = probability

        confidence = (
            max(
                result.values()
            )
            if result
            else 0.0
        )

        return (
            result,
            confidence
        )

    except Exception as e:

        print(
            f"⚠️ Ошибка ML прогноза: {e}",
            flush=True
        )

        return {}, 0.0


# =====================================================================
# MODEL + PATTERN + COMBINED PREDICTION
# =====================================================================
#
# ML       = чистый SGD
# PATTERN  = чистый Pattern Scanner
# COMBINED = 85% ML + 15% Pattern
#
# =====================================================================

def get_model_prediction(
    timestamp_msk,
    target_record=None
):

    global analytics

    data = load_data()

    if target_record is None:

        target_record = {
            "timestamp_msk": timestamp_msk
        }

    else:

        target_record = dict(
            target_record
        )

        target_record[
            "timestamp_msk"
        ] = timestamp_msk

    # -------------------------------------------------------------
    # ML
    # -------------------------------------------------------------

    ml_probs, confidence = get_ml_prediction(
        data,
        target_record
    )

    if not ml_probs:

        return {
            "model_suit": None,

            "ml_suit": None,
            "pattern_suit": None,
            "combined_suit": None,

            "raw_ml_probs": {},
            "model_probs": {},
            "scanner_probs": {},

            "ml_confidence": 0.0,
        }

    # -------------------------------------------------------------
    # PATTERN
    # -------------------------------------------------------------

    scanner_probs = scanner_scores_for_target(
        data,
        target_record
    )

    # -------------------------------------------------------------
    # ML WINNER
    # -------------------------------------------------------------

    ml_suit = max(
        ml_probs,
        key=ml_probs.get
    )

    # -------------------------------------------------------------
    # PATTERN WINNER
    # -------------------------------------------------------------

    pattern_suit = None

    if scanner_probs:

        max_pattern_value = max(
            scanner_probs.values()
        )

        if max_pattern_value > 0:

            leaders = [
                suit
                for suit, value
                in scanner_probs.items()
                if value == max_pattern_value
            ]

            # Если Pattern дал несколько одинаковых лидеров,
            # отдельный прогноз Pattern не учитываем.
            if len(leaders) == 1:

                pattern_suit = leaders[0]

    # -------------------------------------------------------------
    # COMBINED
    # -------------------------------------------------------------
    #
    # 85% ML
    # 15% Pattern
    #
    # -------------------------------------------------------------

    combined_probs = {}

    for suit in TARGET_SUITS:

        ml_value = ml_probs.get(
            suit,
            0.0
        )

        pattern_value = scanner_probs.get(
            suit,
            0.0
        )

        combined_probs[suit] = (
            0.85
            * ml_value
            +
            0.15
            * pattern_value
        )

    combined_suit = max(
        combined_probs,
        key=combined_probs.get
    )

    # -------------------------------------------------------------
    # THRESHOLD
    # -------------------------------------------------------------

    if (
        confidence
        < ML_CONFIDENCE_THRESHOLD
    ):

        return {
            "model_suit": None,

            "ml_suit": ml_suit,
            "pattern_suit": pattern_suit,
            "combined_suit": combined_suit,

            "raw_ml_probs": ml_probs,
            "model_probs": combined_probs,
            "scanner_probs": scanner_probs,

            "ml_confidence": confidence,
        }

    return {
        # Совместимость со старым кодом
        "model_suit": combined_suit,

        # Новые независимые источники
        "ml_suit": ml_suit,
        "pattern_suit": pattern_suit,
        "combined_suit": combined_suit,

        "raw_ml_probs": ml_probs,

        "model_probs": combined_probs,

        "scanner_probs": scanner_probs,

        "ml_confidence": confidence,
    }


# =====================================================================
# UPCOMING API
# =====================================================================

def get_upcoming_games():

    try:

        url = (
            f"{BASE_URL}"
            "/service-api/main-live-feed/v3/"
            "leftMenuSports"
            "?fcountry=1"
            f"&gr={GR}"
            "&lng=ru"
            "&ref=7"
            f"&selectedMs=1.{SPORT_ID}.{LIGA_ID},"
            f"10.{SPORT_ID}.{LIGA_ID}"
        )

        response = requests.get(
            url,
            headers=HEADERS,
            timeout=10
        )

        if response.status_code != 200:
            return []

        data = response.json()

        if not isinstance(
            data,
            list
        ):
            return []

        now = datetime.now(
            MOSCOW_TZ
        )

        games = []

        for section in data:

            if section.get(
                "menuSectionId"
            ) != 10:
                continue

            for sport in section.get(
                "sports",
                []
            ):

                if sport.get(
                    "id"
                ) != SPORT_ID:
                    continue

                for liga in sport.get(
                    "ligas",
                    []
                ):

                    if liga.get(
                        "id"
                    ) != LIGA_ID:
                        continue

                    for game in liga.get(
                        "games",
                        []
                    ):

                        if game.get(
                            "nonStarted"
                        ) is not True:
                            continue

                        start_ts = game.get(
                            "startTs"
                        )

                        if not start_ts:
                            continue

                        start_time = (
                            datetime.fromtimestamp(
                                start_ts,
                                MOSCOW_TZ
                            )
                        )

                        minutes = (
                            start_time
                            - now
                        ).total_seconds() / 60

                        if (
                            0
                            < minutes
                            <= 20
                        ):

                            games.append(
                                {
                                    "game_id": str(
                                        game.get(
                                            "id"
                                        )
                                    ),

                                    "game_num":
                                        get_game_number_from_timestamp(
                                            start_ts
                                        ),

                                    "start_ts":
                                        start_ts,

                                    "start_time":
                                        start_time.isoformat(),

                                    "minutes_until":
                                        minutes,
                                }
                            )

        return games

    except Exception as e:

        print(
            f"❌ Ошибка будущих игр: {e}",
            flush=True
        )

        return []


# =====================================================================
# PREDICTION CREATION
# =====================================================================

def has_prediction_for_target(target):

    return any(
        p.get("target") == target
        and p.get("status") == "pending"
        for p in predictions
    )


def check_upcoming_games():

    global seen_upcoming_games
    global analytics

    upcoming = get_upcoming_games()

    for game in upcoming:

        target_num = game.get(
            "game_num"
        )

        game_id = game.get(
            "game_id"
        )

        if (
            not target_num
            or not game_id
            or game_id
            in seen_upcoming_games
        ):
            continue

        seen_upcoming_games.add(
            game_id
        )

        if has_prediction_for_target(
            target_num
        ):
            continue

        now = datetime.now(
            MOSCOW_TZ
        )

        timestamp = now.strftime(
            "%H:%M:%S"
        )

        target_meta = {
            "game_id": game_id,

            "game_number": target_num,

            "timestamp_msk": timestamp,

            "start_ts": game.get(
                "start_ts"
            ),
        }

        result = get_model_prediction(
            timestamp,
            target_meta
        )

        combined_suit = result.get(
            "combined_suit"
        )

        ml_suit = result.get(
            "ml_suit"
        )

        pattern_suit = result.get(
            "pattern_suit"
        )

        model_suit = result.get(
            "model_suit"
        )

        if not model_suit:

            print(
                f"⏭️ Нет прогноза модели "
                f"для #{target_num}",
                flush=True
            )

            continue

        # ---------------------------------------------------------
        # AGREEMENT / DISAGREEMENT
        # ---------------------------------------------------------
        #
        # Считаем только если Pattern реально дал один прогноз.
        #
        # ---------------------------------------------------------

        if pattern_suit:

            if ml_suit == pattern_suit:

                analytics[
                    "agreement"
                ] += 1

            else:

                analytics[
                    "disagreement"
                ] += 1

            save_analytics()

        model_probs = result.get(
            "model_probs",
            {}
        )

        confidence = result.get(
            "ml_confidence",
            0.0
        )

        msg = (
            "🔮 <b>ПРОГНОЗ МАСТИ "
            "(БАККАРА)</b>\n\n"

            f"🎯 Игра: <b>#N{target_num}</b>\n"

            f"⏰ Время: {timestamp}\n\n"

            f"⚖️ <b>COMBINED:</b> "
            f"<b>{combined_suit}</b>\n\n"

            f"🤖 ML: <b>{ml_suit or '—'}</b>\n"
            f"🔎 Pattern: <b>{pattern_suit or '—'}</b>\n\n"

            f"📊 Уверенность ML: "
            f"<b>{confidence * 100:.1f}%</b>\n\n"

            f"📈 Проверка: "
            f"0–{DOGON_GAMES - 1} догон"
        )

        msg_id = send_message(
            CHANNEL_PROGNOZ,
            msg
        )

        if not msg_id:
            continue

        entry = {
            "target": target_num,

            "source": target_num,

            "game_id": game_id,

            "message_id": msg_id,

            "original_text": msg,

            "status": "pending",

            "timestamp_msk": timestamp,

            # -----------------------------------------------------
            # THREE SOURCES
            # -----------------------------------------------------

            "ml_suit": ml_suit,

            "pattern_suit": pattern_suit,

            "combined_suit": combined_suit,

            # Совместимость
            "model_suit": combined_suit,

            # -----------------------------------------------------

            "raw_ml_probs": result.get(
                "raw_ml_probs",
                {}
            ),

            "model_probs": model_probs,

            "scanner_probs": result.get(
                "scanner_probs",
                {}
            ),

            "ml_confidence": confidence,

            # -----------------------------------------------------
            # ANALYTICS FLAGS
            # -----------------------------------------------------

            "analytics_counted": False,

            "analytics_dogon_texts": {},

            "created": now.isoformat(),
        }

        entry[
            "main_suit"
        ] = combined_suit

        entry[
            "additional_suit"
        ] = None

        predictions.append(
            entry
        )

        save_history(
            predictions
        )

        print(
            f"🔮 #{target_num}: "
            f"ML={ml_suit} | "
            f"Pattern={pattern_suit} | "
            f"Combined={combined_suit} | "
            f"Уверенность={confidence * 100:.1f}%",
            flush=True
        )


# =====================================================================
# RESULT CACHE
# =====================================================================

def cache_result(
    num,
    text
):

    games_cache[
        int(num)
    ] = text

    if len(games_cache) > 1000:

        for key in list(
            games_cache
        )[:-500]:

            games_cache.pop(
                key,
                None
            )


# =====================================================================
# SAVE GAME TO TRAINING DATA
# =====================================================================

def add_game_to_cards_data(
    game_num,
    text
):

    data = load_data()

    cards = parse_full_cards_from_text(
        text
    )

    if not cards:
        return False

    signature = "".join(
        f"{card['rank']}{card['suit']}"
        for card
        in cards
    )

    for old in data:

        if str(
            old.get(
                "game_id"
            )
        ) != str(game_num):
            continue

        old_signature = "".join(
            f"{card.get('rank')}"
            f"{normalize_suit(card.get('suit'))}"
            for card
            in old.get(
                "player_cards",
                []
            )
            if isinstance(
                card,
                dict
            )
        )

        if old_signature == signature:
            return False

    now = datetime.now(
        MOSCOW_TZ
    )

    record = {
        "game_id": str(game_num),

        "timestamp_msk":
            now.strftime(
                "%H:%M:%S"
            ),

        "recorded_at":
            now.isoformat(),

        "state": "telegram",

        "player_cards": cards,

        "dealer_cards": [],

        "sequence": [],

        "game_number": int(
            game_num
        ),
    }

    data.append(
        record
    )

    data = data[
        -MAX_RECORDS:
    ]

    return save_data(
        data
    )


# =====================================================================
# COLLECT DOGON RESULTS
# =====================================================================

def collect_dogon_results(entry):

    target = entry.get(
        "target"
    )

    if not target:
        return None

    results = []

    for dogon in range(
        DOGON_GAMES
    ):

        num = add_game_offset(
            target,
            dogon
        )

        text = games_cache.get(
            num
        )

        if not text:
            return None

        results.append(
            {
                "num": num,
                "dogon": dogon,
                "text": text,
                "suits": set(
                    parse_suits_from_text(
                        text
                    )
                ),
            }
        )

    return results


# =====================================================================
# EVALUATE ALL SOURCES
# =====================================================================
#
# Каждый источник проверяется одинаково:
# по полному диапазону 0-3 догон.
#
# =====================================================================

def evaluate_sources_over_dogon(
    entry,
    dogon_results
):

    if entry.get(
        "analytics_counted"
    ):
        return

    if not dogon_results:
        return

    all_actual_suits = set()

    for result in dogon_results:

        all_actual_suits.update(
            result.get(
                "suits",
                set()
            )
        )

    # -------------------------------------------------------------
    # ML
    # -------------------------------------------------------------

    ml_suit = entry.get(
        "ml_suit"
    )

    if ml_suit:

        ml_hit = (
            ml_suit
            in all_actual_suits
        )

        update_source_analytics(
            "ml",
            ml_hit
        )

        entry[
            "ml_hit"
        ] = ml_hit

    # -------------------------------------------------------------
    # PATTERN
    # -------------------------------------------------------------

    pattern_suit = entry.get(
        "pattern_suit"
    )

    if pattern_suit:

        pattern_hit = (
            pattern_suit
            in all_actual_suits
        )

        update_source_analytics(
            "pattern",
            pattern_hit
        )

        entry[
            "pattern_hit"
        ] = pattern_hit

    # -------------------------------------------------------------
    # COMBINED
    # -------------------------------------------------------------

    combined_suit = entry.get(
        "combined_suit"
    )

    if combined_suit:

        combined_hit = (
            combined_suit
            in all_actual_suits
        )

        update_source_analytics(
            "combined",
            combined_hit
        )

        entry[
            "combined_hit"
        ] = combined_hit

    # -------------------------------------------------------------
    # MARK AS COUNTED
    # -------------------------------------------------------------

    entry[
        "analytics_counted"
    ] = True

    entry[
        "analytics_actual_suits"
    ] = list(
        all_actual_suits
    )

    save_analytics()

    print(
        "📊 АНАЛИТИКА ОБНОВЛЕНА | "
        f"ML={'✅' if entry.get('ml_hit') else '❌'} | "
        f"Pattern={'✅' if entry.get('pattern_hit') else '❌'} | "
        f"Combined={'✅' if entry.get('combined_hit') else '❌'}",
        flush=True
    )


# =====================================================================
# FIND FIRST COMBINED HIT
# =====================================================================

def find_combined_hit(
    combined_suit,
    dogon_results
):

    if not combined_suit:
        return None

    for result in dogon_results:

        if (
            combined_suit
            in result["suits"]
        ):

            return result

    return None


# =====================================================================
# RESULT CHECKING
# =====================================================================

def check_results():

    global predictions

    if not predictions:
        return

    for entry in predictions:

        if entry.get(
            "status"
        ) != "pending":
            continue

        target = entry.get(
            "target"
        )

        combined_suit = entry.get(
            "combined_suit"
        )

        # Совместимость со старой историей
        if not combined_suit:

            combined_suit = entry.get(
                "model_suit"
            )

            entry[
                "combined_suit"
            ] = combined_suit

        msg_id = entry.get(
            "message_id"
        )

        original = entry.get(
            "original_text",
            ""
        )

        if (
            not target
            or not msg_id
            or not combined_suit
        ):
            continue

        # -------------------------------------------------------------
        # ВАЖНО:
        #
        # Ждём ВСЕ 4 игры догона.
        #
        # Только после этого честно проверяем:
        # ML / Pattern / Combined
        #
        # -------------------------------------------------------------

        dogon_results = collect_dogon_results(
            entry
        )

        if dogon_results is None:
            continue

        # -------------------------------------------------------------
        # FIND COMBINED RESULT
        # -------------------------------------------------------------

        found = find_combined_hit(
            combined_suit,
            dogon_results
        )

        # -------------------------------------------------------------
        # ANALYTICS
        # -------------------------------------------------------------

        evaluate_sources_over_dogon(
            entry,
            dogon_results
        )

        # -------------------------------------------------------------
        # WIN
        # -------------------------------------------------------------

        if found:

            stats["total"] += 1

            stats["win"] += 1

            stats["by_dogon"][
                found["dogon"]
            ] += 1

            stats["suit_hits"][
                combined_suit
            ] += 1

            stats["model"]["total"] += 1

            stats["model"]["win"] += 1

            result_text = (
                "\n\n"
                "━━━━━━━━━━━━━━━━━━━━\n"
                "✅ <b>ЗАШЛО</b>\n"
                "━━━━━━━━━━━━━━━━━━━━\n"

                f"🎯 Игра: "
                f"#{found['num']}\n"

                f"📈 Догон: "
                f"<b>{found['dogon']}</b>\n"

                f"🃏 Масть игрока: "
                f"<b>{combined_suit}</b>\n\n"

                "📊 <b>Источники:</b>\n"

                f"🤖 ML: "
                f"{'✅' if entry.get('ml_hit') else '❌'}\n"

                f"🔎 Pattern: "
                f"{'✅' if entry.get('pattern_hit') else '❌'}\n"

                f"⚖️ Combined: "
                f"{'✅' if entry.get('combined_hit') else '❌'}"
            )

            edit_message(
                msg_id,
                original
                + result_text
            )

            entry.update(
                {
                    "status": "win",

                    "result_game":
                        found["num"],

                    "dogon":
                        found["dogon"],

                    "found_suit":
                        combined_suit,

                    "model_hit":
                        True,
                }
            )

            save_history(
                predictions
            )

            add_game_to_cards_data(
                found["num"],
                found["text"]
            )

            print(
                f"✅ #{target} ЗАШЛО | "
                f"догон={found['dogon']} | "
                f"Combined={combined_suit}",
                flush=True
            )

            continue

        # -------------------------------------------------------------
        # LOSE
        # -------------------------------------------------------------

        stats["total"] += 1

        stats["lose"] += 1

        stats["model"]["total"] += 1

        stats["model"]["lose"] += 1

        result_text = (
            "\n\n"
            "━━━━━━━━━━━━━━━━━━━━\n"
            "❌ <b>НЕ ЗАШЛО</b>\n"
            "━━━━━━━━━━━━━━━━━━━━\n"

            f"🎯 Цель: "
            f"#{target}\n"

            f"⚖️ Combined: "
            f"<b>{combined_suit}</b>\n"

            f"📈 Проверено: "
            f"0–{DOGON_GAMES - 1} догон\n\n"

            "📊 <b>Источники:</b>\n"

            f"🤖 ML: "
            f"{'✅' if entry.get('ml_hit') else '❌'}\n"

            f"🔎 Pattern: "
            f"{'✅' if entry.get('pattern_hit') else '❌'}\n"

            f"⚖️ Combined: "
            f"{'✅' if entry.get('combined_hit') else '❌'}"
        )

        edit_message(
            msg_id,
            original
            + result_text
        )

        entry[
            "status"
        ] = "lose"

        entry[
            "model_hit"
        ] = False

        save_history(
            predictions
        )

        print(
            f"❌ #{target} НЕ ЗАШЛО | "
            f"Combined={combined_suit}",
            flush=True
        )


# =====================================================================
# TELEGRAM UPDATES
# =====================================================================

def process_updates(
    updates,
    offset
):

    if not updates:
        return offset

    for update in updates.get(
        "result",
        []
    ):

        update_id = update.get(
            "update_id"
        )

        if update_id is None:
            continue

        offset = (
            update_id
            + 1
        )

        save_offset(
            offset
        )

        post = (
            update.get(
                "channel_post"
            )
            or update.get(
                "edited_channel_post"
            )
        )

        if not post:
            continue

        chat_id = str(
            post.get(
                "chat",
                {}
            ).get(
                "id",
                ""
            )
        )

        if chat_id != CHANNEL_STATS:
            continue

        text = post.get(
            "text",
            ""
        )

        match = re.search(
            r"#N(\d+)",
            text
        )

        if not match:
            continue

        if not any(
            marker in text
            for marker in (
                "✅",
                "❌",
                "🔮",
            )
        ):
            continue

        num = int(
            match.group(1)
        )

        cache_result(
            num,
            text
        )

        # ---------------------------------------------------------
        # СОХРАНЯЕМ ВСЕ ИГРЫ
        # ---------------------------------------------------------

        add_game_to_cards_data(
            num,
            text
        )

    return offset


# =====================================================================
# RETRAINING
# =====================================================================

def maybe_retrain_models():

    global ml_last_train_count
    global scanner_last_train_count

    data = load_data()

    count = len(data)

    if count < MIN_TRAIN_SAMPLES:
        return

    if (
        scanner_last_train_count
        != count
    ):

        train_pattern_scanner(
            data
        )

    if (
        ml_last_train_count
        != count
    ):

        train_ml_model()


# =====================================================================
# PRINT ANALYTICS TO CONSOLE
# =====================================================================

def print_analytics_console():

    ml_accuracy = get_source_accuracy(
        "ml"
    )

    pattern_accuracy = get_source_accuracy(
        "pattern"
    )

    combined_accuracy = get_source_accuracy(
        "combined"
    )

    print(
        "📊 ТЕКУЩАЯ АНАЛИТИКА:",
        flush=True
    )

    print(
        f"🤖 ML: "
        f"{analytics['ml']['win']}/"
        f"{analytics['ml']['total']} "
        f"({ml_accuracy:.1f}%)",
        flush=True
    )

    print(
        f"🔎 Pattern: "
        f"{analytics['pattern']['win']}/"
        f"{analytics['pattern']['total']} "
        f"({pattern_accuracy:.1f}%)",
        flush=True
    )

    print(
        f"⚖️ Combined: "
        f"{analytics['combined']['win']}/"
        f"{analytics['combined']['total']} "
        f"({combined_accuracy:.1f}%)",
        flush=True
    )

    print(
        f"🧠 Согласие: "
        f"{analytics['agreement']} | "
        f"⚔️ Расхождение: "
        f"{analytics['disagreement']}",
        flush=True
    )


# =====================================================================
# MAIN
# =====================================================================

def main():

    global predictions

    print(
        "=" * 65,
        flush=True
    )

    print(
        "🔮 ПРОГНОЗ МАСТИ (БАККАРА)",
        flush=True
    )

    print(
        "🤖 SGD MODEL + PATTERN SCANNER",
        flush=True
    )

    print(
        "⚖️ COMBINED: 85% ML + 15% PATTERN",
        flush=True
    )

    print(
        "📊 ДИНАМИЧЕСКАЯ АНАЛИТИКА: ВКЛЮЧЕНА",
        flush=True
    )

    print(
        "⏰ Аналитика Telegram: каждый час",
        flush=True
    )

    print(
        "=" * 65,
        flush=True
    )

    # -------------------------------------------------------------
    # LOAD DATA
    # -------------------------------------------------------------

    data = load_data()

    print(
        f"📚 Загружено игр: "
        f"{len(data)}/{MAX_RECORDS}",
        flush=True
    )

    # -------------------------------------------------------------
    # LOAD ANALYTICS
    # -------------------------------------------------------------

    load_analytics()

    print_analytics_console()

    # -------------------------------------------------------------
    # LOAD / TRAIN SCANNER
    # -------------------------------------------------------------

    load_pattern_scanner()

    if (
        len(data)
        >= MIN_TRAIN_SAMPLES
    ):

        train_pattern_scanner(
            data
        )

    # -------------------------------------------------------------
    # LOAD / TRAIN MODEL
    # -------------------------------------------------------------

    model_loaded = load_ml_model()

    if model_loaded:

        print(
            "🤖 SGD модель загружена",
            flush=True
        )

    elif (
        len(data)
        >= MIN_TRAIN_SAMPLES
    ):

        train_ml_model()

    else:

        print(
            "⏳ Недостаточно данных "
            "для обучения SGD",
            flush=True
        )

    # -------------------------------------------------------------
    # LOAD PREDICTIONS
    # -------------------------------------------------------------

    predictions = load_history()

    if not isinstance(
        predictions,
        list
    ):

        predictions = []

    # -------------------------------------------------------------
    # TELEGRAM OFFSET
    # -------------------------------------------------------------

    offset = get_offset()

    # -------------------------------------------------------------
    # TIMERS
    # -------------------------------------------------------------

    last_upcoming = 0
    last_result = 0
    last_retrain = 0

    # Чтобы после запуска не ждать целый час
    # первую аналитику отправляем через 60 секунд.
    last_analytics = (
        time.time()
        - ANALYTICS_INTERVAL
        + 60
    )

    print(
        "🚀 БОТ ГОТОВ!",
        flush=True
    )

    print(
        "🤖 ML + 🔎 Pattern → ⚖️ Combined",
        flush=True
    )

    print(
        f"📈 Догон: 0–{DOGON_GAMES - 1}",
        flush=True
    )

    print(
        "📊 Аналитика: каждый час",
        flush=True
    )

    # -------------------------------------------------------------
    # MAIN LOOP
    # -------------------------------------------------------------

    while True:

        try:

            now = time.time()

            # -----------------------------------------------------
            # UPCOMING GAMES
            # -----------------------------------------------------

            if (
                now
                - last_upcoming
                >= 10
            ):

                check_upcoming_games()

                last_upcoming = now

            # -----------------------------------------------------
            # RESULT CHECK
            # -----------------------------------------------------

            if (
                now
                - last_result
                >= 5
            ):

                check_results()

                last_result = now

            # -----------------------------------------------------
            # RETRAIN
            # -----------------------------------------------------

            if (
                now
                - last_retrain
                >= 60
            ):

                maybe_retrain_models()

                last_retrain = now

            # -----------------------------------------------------
            # HOURLY ANALYTICS
            # -----------------------------------------------------

            if (
                now
                - last_analytics
                >= ANALYTICS_INTERVAL
            ):

                send_hourly_analytics()

                print_analytics_console()

                last_analytics = now

            # -----------------------------------------------------
            # TELEGRAM UPDATES
            # -----------------------------------------------------

            updates = telegram_request(
                "getUpdates",
                {
                    "offset": offset,
                    "timeout": 5,
                },
                timeout=10
            )

            if updates:

                offset = process_updates(
                    updates,
                    offset
                )

            time.sleep(
                CHECK_INTERVAL
            )

        except KeyboardInterrupt:

            print(
                "\n🛑 БОТ ОСТАНОВЛЕН",
                flush=True
            )

            break

        except Exception as e:

            print(
                f"❌ ОШИБКА MAIN: {e}",
                flush=True
            )

            traceback.print_exc()

            time.sleep(
                10
            )


# =====================================================================
# START
# =====================================================================

if __name__ == "__main__":
    main()