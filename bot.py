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

DOGON_GAMES = 4

CHECK_INTERVAL = 5
MAX_RECORDS = 3000

MIN_TRAIN_SAMPLES = 50

ML_CONFIDENCE_THRESHOLD = 0.20

# Вес источников
ML_WEIGHT = 0.85
PATTERN_WEIGHT = 0.15

# Минимальная сила Pattern для отдельного прогноза.
# Pattern score после нормализации должен быть выше этого значения.
PATTERN_SIGNAL_THRESHOLD = 0.05

# Как часто публиковать аналитику
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

last_analytics_time = 0


# =====================================================================
# STATS
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

    "agreement": {
        "total": 0,
        "same": 0,
        "different": 0,
    },
}


# =====================================================================
# TELEGRAM
# =====================================================================

def telegram_request(method, payload=None, timeout=20):

    url = f"https://api.telegram.org/bot{BOT_TOKEN}/{method}"

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


def send_message(chat_id, text):

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

    return result.get(
        "result",
        {}
    ).get(
        "message_id"
    )


def edit_message(message_id, text):

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

    if not os.path.exists(CARDS_DATA_FILE):
        return []

    try:

        with open(
            CARDS_DATA_FILE,
            "r",
            encoding="utf-8"
        ) as f:

            data = json.load(f)

        if isinstance(data, list):
            return data

        if isinstance(data, dict):

            for key in (
                "data",
                "games",
                "records",
                "items",
                "history",
                "cards",
            ):

                if isinstance(data.get(key), list):
                    return data[key]

    except Exception as e:

        print(
            f"⚠️ Ошибка загрузки {CARDS_DATA_FILE}: {e}",
            flush=True
        )

    return []


def save_data(data):

    try:

        data = data[-MAX_RECORDS:]

        tmp = CARDS_DATA_FILE + ".tmp"

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

    if not os.path.exists(HISTORY_FILE):
        return []

    try:

        with open(
            HISTORY_FILE,
            "r",
            encoding="utf-8"
        ) as f:

            data = json.load(f)

        return data if isinstance(data, list) else []

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

    except Exception as e:

        print(
            f"⚠️ Ошибка сохранения истории: {e}",
            flush=True
        )


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

    s = str(suit).replace(
        "\ufe0f",
        ""
    ).strip()

    return {
        "♠": "♠️",
        "♣": "♣️",
        "♦": "♦️",
        "♥": "♥️",
    }.get(s)


# =====================================================================
# PARSING CARDS
# =====================================================================

def extract_player_cards(record):

    if not isinstance(record, dict):
        return []

    cards = record.get(
        "player_cards",
        []
    )

    if not isinstance(cards, list):
        return []

    result = []

    for card in cards:

        if isinstance(card, dict):

            suit = normalize_suit(
                card.get("suit")
            )

            rank = str(
                card.get("rank", "")
            )

            if suit in TARGET_SUITS:

                result.append(
                    {
                        "rank": rank,
                        "suit": suit,
                    }
                )

        elif isinstance(card, str):

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
        for card in extract_player_cards(record)
        if card.get("suit") in TARGET_SUITS
    ]


def parse_suits_from_text(text):
    """
    Берём только PLAYER-группу после #N...
    """

    if not text:
        return []

    try:

        clean = str(text).replace(
            "\ufe0f",
            ""
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
                suits.append(normalized)

        return suits

    except Exception:
        return []


def parse_full_cards_from_text(text):

    if not text:
        return []

    try:

        clean = str(text).replace(
            "\ufe0f",
            ""
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

            normalized = normalize_suit(suit)

            if normalized:

                result.append(
                    {
                        "rank": rank,
                        "suit": normalized,
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
        start -= timedelta(days=1)

    minutes = int(
        (dt - start).total_seconds()
        // 60
    )

    return (
        minutes % 1440
    ) + 1


def add_game_offset(num, offset):

    return (
        (
            int(num) - 1 + int(offset)
        )
        % 1440
    ) + 1


# =====================================================================
# DATA SIGNATURE
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
        for card in extract_player_cards(record)
    ]

    game_number = None

    try:

        value = record.get(
            "game_number"
        )

        if value is not None:
            game_number = int(value)

    except Exception:

        game_number = get_game_number_from_timestamp(
            record.get(
                "timestamp_msk"
            )
        )

    return {
        "suits": set(suits),
        "ranks": ranks,
        "count": len(suits),

        "lat": float(
            record.get(
                "latency_ms"
            ) or 0.0
        ),

        "state": str(
            record.get(
                "state",
                ""
            )
        ),

        "game_num": game_number,
    }


# =====================================================================
# HELPER
# =====================================================================

def _tail_streak(values):

    count = 0

    for value in reversed(values):

        if value:
            count += 1
        else:
            break

    return count


# =====================================================================
# PATTERN FEATURES
# =====================================================================

def build_scanner_feature_map(data, idx):

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
                suit in historical["suits"]
            )

        features[
            f"lag{lag}_cards"
        ] = historical["count"]

        state = historical["state"]

        if state:

            features[
                f"lag{lag}_state_{state}"
            ] = 1

    # -------------------------------------------------------------
    # WINDOW FEATURES
    # -------------------------------------------------------------

    for window in PATTERN_WINDOWS:

        sequence = history[-window:]

        if not sequence:
            continue

        for suit in TARGET_SUITS:

            values = [
                int(
                    suit in historical["suits"]
                )
                for historical in sequence
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
            ] = _tail_streak(values)

        features[
            f"win{window}_avg_cards"
        ] = (
            sum(
                historical["count"]
                for historical in sequence
            )
            / len(sequence)
        )

        features[
            f"win{window}_avg_latency"
        ] = (
            sum(
                historical["lat"]
                for historical in sequence
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
                    suit_a in previous_2["suits"]
                    and
                    suit_b in current["suits"]
                )

    return features


# =====================================================================
# TARGET
# =====================================================================

def target_presence(record):

    suits = set(
        extract_player_suits(record)
    )

    return np.array(
        [
            1 if suit in suits else 0
            for suit in TARGET_SUITS
        ],
        dtype=int
    )


# =====================================================================
# PATTERN TRAINING
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
            for row in feature_rows
            for key in row
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
                for row in feature_rows
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
            or support < len(values) * 0.02
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

    scanner_last_train_count = len(data)

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
        f"🔎 Pattern Scanner: найдено "
        f"{len(scanner_patterns)} рабочих паттернов",
        flush=True
    )

    return True


def load_pattern_scanner():

    global scanner_patterns

    try:

        with open(
            SCANNER_FILE,
            "rb"
        ) as f:

            patterns = pickle.load(f)

        if isinstance(
            patterns,
            list
        ):

            scanner_patterns = patterns

    except Exception:

        scanner_patterns = []


# =====================================================================
# PATTERN PREDICTION
# =====================================================================

def scanner_scores_for_target(
    data,
    target_record
):
    """
    Возвращает:
    - вероятности Pattern по мастям
    - количество реально активированных паттернов
    """

    if (
        not scanner_patterns
        or not data
    ):

        return (
            {
                suit: 0.0
                for suit in TARGET_SUITS
            },
            0
        )

    temp = list(data)

    target_copy = dict(
        target_record
    )

    target_copy["player_cards"] = []
    target_copy["dealer_cards"] = []
    target_copy["sequence"] = []

    temp.append(
        target_copy
    )

    features = build_scanner_feature_map(
        temp,
        len(temp) - 1
    )

    scores = defaultdict(float)
    weights = defaultdict(float)

    active_patterns = 0

    for pattern in scanner_patterns:

        value = float(
            features.get(
                pattern["feature"],
                0.0
            )
        )

        if value <= 0:
            continue

        active_patterns += 1

        # Реальный вес паттерна
        weight = (
            max(
                0.0,
                pattern["lift"] - 1.0
            )
            * pattern["precision"]
            * np.log1p(
                pattern["support"]
            )
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

    # Нет ни одного активного паттерна
    if active_patterns == 0:

        return (
            {
                suit: 0.0
                for suit in TARGET_SUITS
            },
            0
        )

    raw_probs = {}

    for suit in TARGET_SUITS:

        if weights[suit] > 0:

            raw_probs[suit] = (
                scores[suit]
                / weights[suit]
            )

        else:

            raw_probs[suit] = 0.0

    # Нормализуем Pattern значения
    max_value = max(
        raw_probs.values()
    )

    if max_value <= 0:

        return (
            {
                suit: 0.0
                for suit in TARGET_SUITS
            },
            active_patterns
        )

    normalized = {
        suit: (
            value / max_value
        )
        for suit, value in raw_probs.items()
    }

    return (
        normalized,
        active_patterns
    )


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

    target_copy["player_cards"] = []
    target_copy["dealer_cards"] = []
    target_copy["sequence"] = []

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
            for row in rows
            for key in row
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
                for name in names
            ]
            for row in rows
        ],
        dtype=float
    )

    Y = np.array(
        targets,
        dtype=int
    )

    return X, Y, names


# =====================================================================
# TRAIN ML
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
        or len(X) < MIN_TRAIN_SAMPLES
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

        ml_last_train_count = len(data)

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
            f"🤖 SGD обучен: "
            f"{len(X)} примеров | "
            f"{X.shape[1]} признаков | "
            f"4 масти",
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

            obj = pickle.load(f)

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
# ML PREDICTION
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
                    for name in names
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
            max(result.values())
            if result
            else 0.0
        )

        return result, confidence

    except Exception as e:

        print(
            f"⚠️ Ошибка ML прогноза: {e}",
            flush=True
        )

        return {}, 0.0


# =====================================================================
# FULL PREDICTION
# =====================================================================

def get_model_prediction(
    timestamp_msk,
    target_record=None
):
    """
    Полный анализ:

    ML
    Pattern (только если реально есть сигнал)
    Combined

    Если Pattern нет:
    Combined = ML
    """

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

    ml_probs, ml_confidence = get_ml_prediction(
        data,
        target_record
    )

    if not ml_probs:

        return {
            "ml_suit": None,
            "ml_probability": 0.0,
            "ml_probs": {},

            "pattern_suit": None,
            "pattern_probability": 0.0,
            "pattern_probs": {},
            "active_patterns": 0,

            "combined_suit": None,
            "combined_probability": 0.0,
            "combined_probs": {},

            "agreement": None,
            "ml_confidence": 0.0,
        }

    ml_suit = max(
        ml_probs,
        key=ml_probs.get
    )

    ml_probability = ml_probs.get(
        ml_suit,
        0.0
    )

    # -------------------------------------------------------------
    # PATTERN
    # -------------------------------------------------------------

    pattern_probs, active_patterns = (
        scanner_scores_for_target(
            data,
            target_record
        )
    )

    pattern_suit = None
    pattern_probability = 0.0

    has_pattern_signal = False

    if (
        active_patterns > 0
        and pattern_probs
        and max(pattern_probs.values()) > 0
    ):

        candidate_pattern_suit = max(
            pattern_probs,
            key=pattern_probs.get
        )

        candidate_probability = (
            pattern_probs.get(
                candidate_pattern_suit,
                0.0
            )
        )

        # Pattern существует только при реальном сигнале
        if (
            candidate_probability
            >= PATTERN_SIGNAL_THRESHOLD
        ):

            pattern_suit = candidate_pattern_suit
            pattern_probability = (
                candidate_probability
            )
            has_pattern_signal = True

    # -------------------------------------------------------------
    # COMBINED
    # -------------------------------------------------------------

    combined_probs = {}

    if has_pattern_signal:

        for suit in TARGET_SUITS:

            combined_probs[suit] = (
                ML_WEIGHT
                * ml_probs.get(
                    suit,
                    0.0
                )
                +
                PATTERN_WEIGHT
                * pattern_probs.get(
                    suit,
                    0.0
                )
            )

        combined_suit = max(
            combined_probs,
            key=combined_probs.get
        )

        combined_probability = (
            combined_probs[
                combined_suit
            ]
        )

        agreement = (
            ml_suit
            == pattern_suit
        )

    else:

        # Если Pattern сигнала нет —
        # Combined полностью повторяет ML
        combined_probs = dict(
            ml_probs
        )

        combined_suit = ml_suit

        combined_probability = (
            ml_probability
        )

        agreement = None

    # -------------------------------------------------------------
    # ML THRESHOLD
    # -------------------------------------------------------------

    if (
        ml_confidence
        < ML_CONFIDENCE_THRESHOLD
    ):

        combined_suit = None

    return {
        "ml_suit": ml_suit,
        "ml_probability": ml_probability,
        "ml_probs": ml_probs,

        "pattern_suit": pattern_suit,
        "pattern_probability": pattern_probability,
        "pattern_probs": pattern_probs,
        "active_patterns": active_patterns,

        "combined_suit": combined_suit,
        "combined_probability": combined_probability,
        "combined_probs": combined_probs,

        "agreement": agreement,
        "ml_confidence": ml_confidence,
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
                            start_time - now
                        ).total_seconds() / 60

                        if (
                            0 < minutes <= 20
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
# PREDICTION CHECK
# =====================================================================

def has_prediction_for_target(target):

    return any(
        p.get("target") == target
        and p.get("status") == "pending"
        for p in predictions
    )


# =====================================================================
# ANALYSIS TEXT
# =====================================================================

def build_analysis_text(
    target_num,
    result
):

    ml_suit = result.get(
        "ml_suit"
    )

    ml_probability = result.get(
        "ml_probability",
        0.0
    )

    pattern_suit = result.get(
        "pattern_suit"
    )

    pattern_probability = result.get(
        "pattern_probability",
        0.0
    )

    combined_suit = result.get(
        "combined_suit"
    )

    combined_probability = result.get(
        "combined_probability",
        0.0
    )

    active_patterns = result.get(
        "active_patterns",
        0
    )

    agreement = result.get(
        "agreement"
    )

    text = (
        f"🔮 <b>#{target_num} АНАЛИЗ</b>\n\n"

        f"🤖 ML: <b>{ml_suit}</b> — "
        f"<b>{ml_probability * 100:.1f}%</b>\n"
    )

    # -------------------------------------------------------------
    # Pattern выводится ТОЛЬКО если реально есть прогноз
    # -------------------------------------------------------------

    if pattern_suit:

        text += (
            f"🔎 Pattern: <b>{pattern_suit}</b> — "
            f"<b>{pattern_probability * 100:.1f}%</b>\n"
        )

    text += (
        f"⚖️ Combined: <b>{combined_suit}</b> — "
        f"<b>{combined_probability * 100:.1f}%</b>"
    )

    # -------------------------------------------------------------
    # Эти строки тоже только при Pattern
    # -------------------------------------------------------------

    if pattern_suit:

        text += (
            f"\n\n🧩 Активных паттернов: "
            f"<b>{active_patterns}</b>\n"

            f"🤝 Согласие: "
            f"<b>{'ДА' if agreement else 'НЕТ'}</b>"
        )

    return text


# =====================================================================
# PREDICTION CREATION
# =====================================================================

def check_upcoming_games():

    global seen_upcoming_games

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
            or game_id in seen_upcoming_games
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

        if not combined_suit:

            print(
                f"⏭️ Нет прогноза "
                f"для #{target_num}",
                flush=True
            )

            continue

        # ---------------------------------------------------------
        # CONSOLE ANALYSIS
        # ---------------------------------------------------------

        console_text = build_analysis_text(
            target_num,
            result
        )

        print(
            "\n"
            + "=" * 50
            + "\n"
            + re.sub(
                r"<[^>]+>",
                "",
                console_text
            )
            + "\n"
            + "=" * 50,
            flush=True
        )

        # ---------------------------------------------------------
        # TELEGRAM FORECAST
        # ---------------------------------------------------------

        msg = (
            "🔮 <b>ПРОГНОЗ МАСТИ "
            "(БАККАРА)</b>\n\n"

            f"🎯 Игра: <b>#N{target_num}</b>\n"

            f"⏰ Время: {timestamp}\n\n"

            f"⚖️ <b>Прогноз:</b> "
            f"<b>{combined_suit}</b>\n"

            f"📊 Вероятность: "
            f"<b>{result.get('combined_probability', 0.0) * 100:.1f}%</b>\n\n"

            f"📈 Проверка: "
            f"0–{DOGON_GAMES - 1} догон"
        )

        # Если Pattern есть — добавляем анализ
        if result.get("pattern_suit"):

            msg += (
                "\n\n────────────────\n\n"
                + build_analysis_text(
                    target_num,
                    result
                )
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
            # ML
            # -----------------------------------------------------

            "ml_suit":
                result.get("ml_suit"),

            "ml_probability":
                result.get(
                    "ml_probability",
                    0.0
                ),

            "ml_probs":
                result.get(
                    "ml_probs",
                    {}
                ),

            # -----------------------------------------------------
            # PATTERN
            # -----------------------------------------------------

            "pattern_suit":
                result.get(
                    "pattern_suit"
                ),

            "pattern_probability":
                result.get(
                    "pattern_probability",
                    0.0
                ),

            "pattern_probs":
                result.get(
                    "pattern_probs",
                    {}
                ),

            "active_patterns":
                result.get(
                    "active_patterns",
                    0
                ),

            # -----------------------------------------------------
            # COMBINED
            # -----------------------------------------------------

            "combined_suit":
                result.get(
                    "combined_suit"
                ),

            "combined_probability":
                result.get(
                    "combined_probability",
                    0.0
                ),

            "combined_probs":
                result.get(
                    "combined_probs",
                    {}
                ),

            "agreement":
                result.get(
                    "agreement"
                ),

            "ml_confidence":
                result.get(
                    "ml_confidence",
                    0.0
                ),

            "created":
                now.isoformat(),
        }

        # Совместимость со старой историей
        entry["model_suit"] = (
            entry["combined_suit"]
        )

        entry["main_suit"] = (
            entry["combined_suit"]
        )

        entry["additional_suit"] = None

        predictions.append(
            entry
        )

        save_history(
            predictions
        )

        print(
            f"💾 Прогноз #{target_num} сохранён | "
            f"ML={entry['ml_suit']} | "
            f"Pattern={entry['pattern_suit']} | "
            f"Combined={entry['combined_suit']}",
            flush=True
        )


# =====================================================================
# RESULT CACHE
# =====================================================================

def cache_result(num, text):

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
# SAVE GAME
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
        for card in cards
    )

    for old in data:

        if str(
            old.get("game_id")
        ) != str(game_num):
            continue

        old_signature = "".join(
            f"{card.get('rank')}"
            f"{normalize_suit(card.get('suit'))}"
            for card in old.get(
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

        "game_number":
            int(game_num),
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
# CHECK ONE SOURCE
# =====================================================================

def source_hit_in_games(
    suit,
    target
):

    if not suit:
        return None

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
            continue

        actual = set(
            parse_suits_from_text(
                text
            )
        )

        if suit in actual:

            return {
                "hit": True,
                "game": num,
                "dogon": dogon,
                "actual": actual,
            }

    return {
        "hit": False,
        "game": None,
        "dogon": None,
        "actual": set(),
    }


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

        msg_id = entry.get(
            "message_id"
        )

        original = entry.get(
            "original_text",
            ""
        )

        combined_suit = entry.get(
            "combined_suit"
        )

        if (
            not target
            or not msg_id
            or not combined_suit
        ):
            continue

        # ---------------------------------------------------------
        # Проверяем наличие всех игр
        # ---------------------------------------------------------

        all_available = True

        for dogon in range(
            DOGON_GAMES
        ):

            num = add_game_offset(
                target,
                dogon
            )

            if num not in games_cache:

                all_available = False
                break

        if not all_available:
            continue

        # ---------------------------------------------------------
        # ML
        # ---------------------------------------------------------

        ml_result = source_hit_in_games(
            entry.get(
                "ml_suit"
            ),
            target
        )

        # ---------------------------------------------------------
        # PATTERN
        # ---------------------------------------------------------

        pattern_suit = entry.get(
            "pattern_suit"
        )

        pattern_result = None

        if pattern_suit:

            pattern_result = source_hit_in_games(
                pattern_suit,
                target
            )

        # ---------------------------------------------------------
        # COMBINED
        # ---------------------------------------------------------

        combined_result = source_hit_in_games(
            combined_suit,
            target
        )

        # ---------------------------------------------------------
        # UPDATE ML STATS
        # ---------------------------------------------------------

        if ml_result:

            stats["ml"]["total"] += 1

            if ml_result["hit"]:
                stats["ml"]["win"] += 1
            else:
                stats["ml"]["lose"] += 1

        # ---------------------------------------------------------
        # UPDATE PATTERN STATS
        # ---------------------------------------------------------

        if pattern_result:

            stats["pattern"]["total"] += 1

            if pattern_result["hit"]:
                stats["pattern"]["win"] += 1
            else:
                stats["pattern"]["lose"] += 1

        # ---------------------------------------------------------
        # UPDATE COMBINED STATS
        # ---------------------------------------------------------

        if combined_result:

            stats["combined"]["total"] += 1

            if combined_result["hit"]:
                stats["combined"]["win"] += 1
            else:
                stats["combined"]["lose"] += 1

        # ---------------------------------------------------------
        # AGREEMENT STATS
        # ---------------------------------------------------------

        if pattern_suit:

            stats["agreement"]["total"] += 1

            if (
                entry.get("ml_suit")
                == pattern_suit
            ):
                stats["agreement"]["same"] += 1
            else:
                stats["agreement"]["different"] += 1

        # ---------------------------------------------------------
        # MAIN WIN
        # ---------------------------------------------------------

        if (
            combined_result
            and combined_result["hit"]
        ):

            stats["total"] += 1
            stats["win"] += 1

            dogon = combined_result[
                "dogon"
            ]

            stats["by_dogon"][
                dogon
            ] += 1

            stats["suit_hits"][
                combined_suit
            ] += 1

            result_text = (
                "\n\n"
                "━━━━━━━━━━━━━━━━━━━━\n"
                "✅ <b>ЗАШЛО</b>\n"
                "━━━━━━━━━━━━━━━━━━━━\n"

                f"🎯 Игра: "
                f"#{combined_result['game']}\n"

                f"📈 Догон: "
                f"<b>{dogon}</b>\n"

                f"🃏 Масть игрока: "
                f"<b>{combined_suit}</b>\n\n"

                f"🤖 ML: "
                f"{'✅' if ml_result and ml_result['hit'] else '❌'}"
            )

            if pattern_suit:

                result_text += (
                    f"\n🔎 Pattern: "
                    f"{'✅' if pattern_result and pattern_result['hit'] else '❌'}"
                )

            result_text += (
                "\n⚖️ Combined: "
                "<b>✅ ЗАШЛО</b>"
            )

            edit_message(
                msg_id,
                original + result_text
            )

            entry.update(
                {
                    "status": "win",

                    "result_game":
                        combined_result[
                            "game"
                        ],

                    "dogon":
                        dogon,

                    "found_suit":
                        combined_suit,

                    "ml_hit":
                        bool(
                            ml_result
                            and ml_result["hit"]
                        ),

                    "pattern_hit":
                        bool(
                            pattern_result
                            and pattern_result["hit"]
                        )
                        if pattern_result
                        else None,

                    "combined_hit": True,
                }
            )

            save_history(
                predictions
            )

            result_game_text = games_cache.get(
                combined_result[
                    "game"
                ]
            )

            if result_game_text:

                add_game_to_cards_data(
                    combined_result[
                        "game"
                    ],
                    result_game_text
                )

            continue

        # ---------------------------------------------------------
        # LOSE
        # ---------------------------------------------------------

        stats["total"] += 1
        stats["lose"] += 1

        result_text = (
            "\n\n"
            "━━━━━━━━━━━━━━━━━━━━\n"
            "❌ <b>НЕ ЗАШЛО</b>\n"
            "━━━━━━━━━━━━━━━━━━━━\n"

            f"🎯 Цель: "
            f"#{target}\n\n"

            f"🤖 ML: "
            f"{'✅' if ml_result and ml_result['hit'] else '❌'}"
        )

        if pattern_suit:

            result_text += (
                f"\n🔎 Pattern: "
                f"{'✅' if pattern_result and pattern_result['hit'] else '❌'}"
            )

        result_text += (
            "\n⚖️ Combined: "
            "<b>❌ НЕ ЗАШЛО</b>\n\n"

            f"📈 Проверено: "
            f"0–{DOGON_GAMES - 1} догон"
        )

        edit_message(
            msg_id,
            original + result_text
        )

        entry.update(
            {
                "status": "lose",

                "ml_hit":
                    bool(
                        ml_result
                        and ml_result["hit"]
                    ),

                "pattern_hit":
                    bool(
                        pattern_result
                        and pattern_result["hit"]
                    )
                    if pattern_result
                    else None,

                "combined_hit": False,
            }
        )

        save_history(
            predictions
        )


# =====================================================================
# PERCENT
# =====================================================================

def get_accuracy(source):

    total = stats[
        source
    ]["total"]

    win = stats[
        source
    ]["win"]

    if total <= 0:
        return 0.0

    return (
        win / total
    ) * 100


# =====================================================================
# BAR
# =====================================================================

def make_bar(percent, length=14):

    percent = max(
        0.0,
        min(
            100.0,
            percent
        )
    )

    filled = round(
        length
        * percent
        / 100
    )

    return (
        "█" * filled
        + "░" * (
            length - filled
        )
    )


# =====================================================================
# ANALYTICS
# =====================================================================

def build_hourly_analytics():

    ml_accuracy = get_accuracy(
        "ml"
    )

    pattern_accuracy = get_accuracy(
        "pattern"
    )

    combined_accuracy = get_accuracy(
        "combined"
    )

    sources = {
        "ML": ml_accuracy,
        "PATTERN": pattern_accuracy,
        "COMBINED": combined_accuracy,
    }

    # Pattern без прогнозов не участвует
    if stats["pattern"]["total"] == 0:
        sources.pop(
            "PATTERN",
            None
        )

    best_source = max(
        sources,
        key=sources.get
    )

    agreement_total = stats[
        "agreement"
    ]["total"]

    if agreement_total > 0:

        agreement_percent = (
            stats["agreement"]["same"]
            / agreement_total
            * 100
        )

        disagreement_percent = (
            stats["agreement"]["different"]
            / agreement_total
            * 100
        )

    else:

        agreement_percent = 0.0
        disagreement_percent = 0.0

    text = (
        "📊 <b>АНАЛИТИКА ПРОГНОЗОВ</b>\n\n"

        "🤖 <b>ML</b>\n"
        f"{make_bar(ml_accuracy)} "
        f"{ml_accuracy:.1f}%\n"
    )

    if stats["pattern"]["total"] > 0:

        text += (
            "\n"
            "🔎 <b>PATTERN</b>\n"
            f"{make_bar(pattern_accuracy)} "
            f"{pattern_accuracy:.1f}%\n"
        )

    text += (
        "\n"
        "⚖️ <b>COMBINED</b>\n"
        f"{make_bar(combined_accuracy)} "
        f"{combined_accuracy:.1f}%\n"

        "\n"
        "────────────────\n"
    )

    if agreement_total > 0:

        text += (
            "\n"
            f"🧠 Согласие ML + Pattern: "
            f"<b>{agreement_percent:.1f}%</b>\n"

            f"⚔️ Расхождение ML / Pattern: "
            f"<b>{disagreement_percent:.1f}%</b>\n"
        )

    text += (
        "\n"
        f"🏆 Лучший источник: "
        f"<b>{best_source}</b>\n\n"

        "────────────────\n"

        f"📈 Всего Combined: "
        f"<b>{stats['combined']['total']}</b>\n"

        f"✅ Зашло: "
        f"<b>{stats['combined']['win']}</b>\n"

        f"❌ Не зашло: "
        f"<b>{stats['combined']['lose']}</b>"
    )

    return text


# =====================================================================
# HOURLY ANALYTICS SEND
# =====================================================================

def maybe_send_analytics():

    global last_analytics_time

    now = time.time()

    if (
        last_analytics_time
        and now - last_analytics_time
        < ANALYTICS_INTERVAL
    ):
        return

    # Не отправляем пустую аналитику
    if stats["combined"]["total"] <= 0:
        return

    text = build_hourly_analytics()

    msg_id = send_message(
        CHANNEL_PROGNOZ,
        text
    )

    if msg_id:

        last_analytics_time = now

        print(
            "📊 Почасовая аналитика отправлена",
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

        offset = update_id + 1

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
                "🔮"
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

        # Сохраняем все игры
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

    if scanner_last_train_count != count:

        train_pattern_scanner(
            data
        )

    if ml_last_train_count != count:

        train_ml_model()


# =====================================================================
# RESTORE STATS FROM HISTORY
# =====================================================================

def rebuild_stats_from_history():

    global stats

    # Не пересчитываем pending
    # Восстанавливаем только завершённые прогнозы

    for entry in predictions:

        status = entry.get(
            "status"
        )

        if status not in (
            "win",
            "lose"
        ):
            continue

        # Combined
        combined_hit = entry.get(
            "combined_hit"
        )

        if combined_hit is not None:

            stats["combined"]["total"] += 1

            if combined_hit:
                stats["combined"]["win"] += 1
            else:
                stats["combined"]["lose"] += 1

        # ML
        ml_hit = entry.get(
            "ml_hit"
        )

        if ml_hit is not None:

            stats["ml"]["total"] += 1

            if ml_hit:
                stats["ml"]["win"] += 1
            else:
                stats["ml"]["lose"] += 1

        # Pattern
        if entry.get(
            "pattern_suit"
        ):

            pattern_hit = entry.get(
                "pattern_hit"
            )

            if pattern_hit is not None:

                stats["pattern"]["total"] += 1

                if pattern_hit:
                    stats["pattern"]["win"] += 1
                else:
                    stats["pattern"]["lose"] += 1

            stats["agreement"]["total"] += 1

            if (
                entry.get("ml_suit")
                == entry.get("pattern_suit")
            ):

                stats["agreement"]["same"] += 1

            else:

                stats["agreement"]["different"] += 1

    print(
        f"📊 Статистика восстановлена | "
        f"ML={stats['ml']['total']} | "
        f"Pattern={stats['pattern']['total']} | "
        f"Combined={stats['combined']['total']}",
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
        "🤖 ML + 🔎 PATTERN + ⚖️ COMBINED",
        flush=True
    )

    print(
        f"⚖️ Вес Combined: "
        f"ML {ML_WEIGHT * 100:.0f}% / "
        f"Pattern {PATTERN_WEIGHT * 100:.0f}%",
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
    # LOAD / TRAIN SCANNER
    # -------------------------------------------------------------

    load_pattern_scanner()

    if len(scanner_patterns):

        print(
            f"🔎 Загружено Pattern: "
            f"{len(scanner_patterns)}",
            flush=True
        )

    if len(data) >= MIN_TRAIN_SAMPLES:

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

    elif len(data) >= MIN_TRAIN_SAMPLES:

        train_ml_model()

    else:

        print(
            "⏳ Недостаточно данных "
            "для обучения SGD",
            flush=True
        )

    # -------------------------------------------------------------
    # LOAD HISTORY
    # -------------------------------------------------------------

    predictions = load_history()

    if not isinstance(
        predictions,
        list
    ):

        predictions = []

    print(
        f"📂 Загружено прогнозов: "
        f"{len(predictions)}",
        flush=True
    )

    rebuild_stats_from_history()

    # -------------------------------------------------------------
    # TELEGRAM OFFSET
    # -------------------------------------------------------------

    offset = get_offset()

    last_upcoming = 0
    last_result = 0
    last_retrain = 0

    print(
        "🚀 БОТ ГОТОВ!",
        flush=True
    )

    print(
        "📊 Аналитика: "
        "ML / Pattern / Combined",
        flush=True
    )

    print(
        "🕐 Почасовая статистика включена",
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
                now - last_upcoming
                >= 10
            ):

                check_upcoming_games()

                last_upcoming = now

            # -----------------------------------------------------
            # RESULT CHECK
            # -----------------------------------------------------

            if (
                now - last_result
                >= 5
            ):

                check_results()

                last_result = now

            # -----------------------------------------------------
            # HOURLY ANALYTICS
            # -----------------------------------------------------

            maybe_send_analytics()

            # -----------------------------------------------------
            # RETRAIN
            # -----------------------------------------------------

            if (
                now - last_retrain
                >= 60
            ):

                maybe_retrain_models()

                last_retrain = now

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

            time.sleep(10)


# =====================================================================
# START
# =====================================================================

if __name__ == "__main__":
    main()