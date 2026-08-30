#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import os
import sys
import subprocess
import importlib

# =====================================================================
# АВТОУСТАНОВКА ЗАВИСИМОСТЕЙ (ВЫПОЛНЯЕТСЯ ДО ВСЕХ ОСТАЛЬНЫХ ИМПОРТОВ)
# =====================================================================
REQUIRED_PACKAGES = [
    'numpy',
    'scikit-learn',
    'requests',
    'pytz',
    'scipy'
]

def install_package(package):
    print(f"📦 Устанавливаю: {package}...", flush=True)
    try:
        subprocess.check_call([sys.executable, "-m", "pip", "install", package, "--quiet"])
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
        print(f"\n📦 Нужно установить: {', '.join(missing)}", flush=True)
        for package in missing:
            if not install_package(package):
                print(f"❌ Не удалось установить {package}", flush=True)
                return False
        print("\n✅ ВСЕ ЗАВИСИМОСТИ УСТАНОВЛЕНЫ!", flush=True)
    else:
        print("\n✅ ВСЕ ЗАВИСИМОСТИ УСТАНОВЛЕНЫ!", flush=True)
    
    print("=" * 60, flush=True)
    return True

if not check_and_install_dependencies():
    print("❌ ОШИБКА: Невозможно продолжить работу", flush=True)
    sys.exit(1)

# =====================================================================
# ТЕПЕРЬ МОЖНО ИМПОРТИРОВАТЬ ВСЕ ОСТАЛЬНЫЕ БИБЛИОТЕКИ
# =====================================================================
import requests
import json
import re
import time
import pickle
import numpy as np
from datetime import datetime, timedelta
import pytz
from collections import deque, defaultdict, Counter
import warnings
import gc
warnings.filterwarnings('ignore')

# =====================================================================
# МЛ-БИБЛИОТЕКИ
# =====================================================================
from sklearn.ensemble import RandomForestClassifier, VotingClassifier
from sklearn.neural_network import MLPClassifier
from sklearn.linear_model import LogisticRegression
from sklearn.cluster import KMeans
from sklearn.preprocessing import StandardScaler
from sklearn.decomposition import PCA
import scipy.stats as stats

ML_AVAILABLE = True
print("✅ Все ML-библиотеки загружены!", flush=True)

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
print(f"BOT_TOKEN: {BOT_TOKEN[:5] if BOT_TOKEN else 'НЕ ЗАДАН'}...", flush=True)
print(f"CHANNEL_STATS: {CHANNEL_STATS if CHANNEL_STATS else 'НЕ ЗАДАН'}", flush=True)
print(f"CHANNEL_PROGNOZ: {CHANNEL_PROGNOZ if CHANNEL_PROGNOZ else 'НЕ ЗАДАН'}", flush=True)
print("=" * 60, flush=True)

if not BOT_TOKEN or not CHANNEL_STATS or not CHANNEL_PROGNOZ:
    print("❌ ОШИБКА: переменные окружения не заданы!", flush=True)
    sys.exit(1)

# =====================================================================
# НАСТРОЙКИ
# =====================================================================
MOSCOW_TZ = pytz.timezone('Europe/Moscow')
BASE_URL = "https://1xlite-36553.pro"

DATA_FILE = "cards_data.json"
HISTORY_FILE = "cards_history.json"
ML_MODEL_FILE = "cards_model.pkl"
OFFSET_FILE = "cards_offset.txt"
GAME_HISTORY_FILE = "cards_game_history.json"
ERROR_FILE = "learning_errors.json"
PATTERN_FILE = "error_patterns.json"

MAX_RECORDS = 3000
CHECK_INTERVAL = 5
OFFSET = 1
MIN_TRAIN_SAMPLES = 300
MAX_HISTORY = 2000
MAX_GAME_HISTORY = 10
DOGON_GAMES = 4
ML_CONFIDENCE_THRESHOLD = 0.60
RETRAIN_THRESHOLD = 500

TARGET_CARDS = [
    "J♠️", "J♣️", "J♦️", "J♥️",
    "Q♠️", "Q♣️", "Q♦️", "Q♥️",
    "K♠️", "K♣️", "K♦️", "K♥️",
    "A♠️", "A♣️", "A♦️", "A♥️"
]

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
    "Accept": "application/json, text/plain, */*",
    "Referer": f"{BASE_URL}/ru/live/twentyone/1643503-twentyone-game",
    "Cookie": "platform_type=desktop; lng=ru; cookies_agree_type=3; tzo=3; is12h=0; referral_values=%7B%22type%22%3A%22reflinkid%22%2C%22val%22%3A%22s_50970m_355c_%22%2C%22additional%22%3A%7B%22name_tag%22%3A%22tag%22%7D%7D; reflinkid=s_50970m_355c_; auid=uaJb+WqQFLEHP+WbAwdUAg==; fatman_uuid=6dac517c-7199-1491-828a-723ace371af0; che_g=3741ad9b-2648-4e11-b16e-55cbdda04b42; SESSION=ae9f1b4deac37d41be6873b1acf03cf4; sh.session.id=1e645679-820b-4250-86f5-bf39161d311d; _ga=GA1.1.103981619.1787827389; _ym_uid=1787827389562709649; _ym_d=1787827389; _ym_isad=2; _ym_visorc=b; mdd=1; _ga_7JGWL9SV66=GS2.1.s1787827388$o1$g1$t1787827414$j34$l0$h1219464045; window_width=150"
}

SUITS = ["♠️", "♣️", "♦️", "♥️"]
SUITS_NAMES = {0: "♠️", 1: "♣️", 2: "♦️", 3: "♥️"}
RANK_VALUES = {'6': 6, '7': 7, '8': 8, '9': 9, '10': 10, 'J': 11, 'Q': 12, 'K': 13, 'A': 14}
RANKS = {1: "A", 2: "2", 3: "3", 4: "4", 5: "5", 6: "6", 7: "7", 8: "8", 9: "9", 10: "10", 11: "J", 12: "Q", 13: "K"}

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
    "card_hits": defaultdict(int),
    "high_confidence": 0,
    "top1_hits": 0
}

processed_games = set()
finished_games = set()
all_messages = []
predictions = []

# ML-переменные
error_patterns = []
scaler = StandardScaler()
feature_importance = None
_new_records_since_train = 0

# =====================================================================
# ФУНКЦИИ ТЕЛЕГРАМ
# =====================================================================
def get_updates(offset):
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/getUpdates"
    params = {"offset": offset, "timeout": 30}
    try:
        response = requests.get(url, params=params, timeout=35)
        return response.json()
    except Exception as e:
        print(f"❌ Ошибка getUpdates: {e}", flush=True)
        return {}

def send_message(chat_id, text):
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
    payload = {"chat_id": chat_id, "text": text, "parse_mode": "HTML"}
    try:
        response = requests.post(url, json=payload, timeout=10)
        if response.status_code == 200:
            return response.json()["result"]["message_id"]
        else:
            print(f"❌ Ошибка отправки: {response.status_code}", flush=True)
            return None
    except Exception as e:
        print(f"❌ Ошибка отправки: {e}", flush=True)
        return None

def edit_message(message_id, text):
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/editMessageText"
    payload = {"chat_id": CHANNEL_PROGNOZ, "message_id": message_id, "text": text, "parse_mode": "HTML"}
    try:
        response = requests.post(url, json=payload, timeout=10)
        return response.status_code == 200
    except Exception as e:
        print(f"❌ Ошибка редактирования: {e}", flush=True)
        return False

def send_startup_message():
    data_count = len(load_data())
    now = datetime.now(MOSCOW_TZ)
    
    msg = f"""
🃏 ТОЧНАЯ КАРТА (ML АНСАМБЛЬ)
📊 Собрано игр: {data_count}/{MAX_RECORDS}
🧠 ML: {'✅ АКТИВНА' if ml_initialized else '⏳ ОЖИДАЕТ'}
🎯 Смещение: +{OFFSET} игр
📈 Догон: {DOGON_GAMES - 1} игр
⚡ Порог уверенности ML: {int(ML_CONFIDENCE_THRESHOLD * 100)}%
🧠 Обучение на ошибках: ВКЛ
⏰ {now.strftime('%d.%m.%Y %H:%M:%S')}
"""
    send_message(CHANNEL_PROGNOZ, msg)
    print("🚀 БОТ ЗАПУЩЕН!", flush=True)

# =====================================================================
# ФУНКЦИИ ДЛЯ РАБОТЫ С ДАННЫМИ
# =====================================================================
def load_data():
    if os.path.exists(DATA_FILE):
        try:
            with open(DATA_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except:
            return []
    return []

def save_data(record):
    global collection_active, stats, _new_records_since_train

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
        _new_records_since_train += 1

    if len(data) > MAX_RECORDS:
        data = data[-MAX_RECORDS:]

    with open(DATA_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)

    if len(data) >= MAX_RECORDS:
        collection_active = False
        print(f"⏸️ СБОР ДАННЫХ ОСТАНОВЛЕН! Достигнут лимит {MAX_RECORDS}", flush=True)

    return data

def load_history():
    if os.path.exists(HISTORY_FILE):
        try:
            with open(HISTORY_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except:
            return []
    return []

def save_history(history):
    if len(history) > MAX_HISTORY:
        history = history[-MAX_HISTORY:]
    with open(HISTORY_FILE, "w", encoding="utf-8") as f:
        json.dump(history, f, indent=2, ensure_ascii=False)

def load_game_history():
    if os.path.exists(GAME_HISTORY_FILE):
        try:
            with open(GAME_HISTORY_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
                return deque(data, maxlen=MAX_GAME_HISTORY)
        except:
            return deque(maxlen=MAX_GAME_HISTORY)
    return deque(maxlen=MAX_GAME_HISTORY)

def save_game_history():
    try:
        with open(GAME_HISTORY_FILE, "w", encoding="utf-8") as f:
            json.dump(list(game_history), f, indent=2, ensure_ascii=False)
    except:
        pass

def get_offset():
    if os.path.exists(OFFSET_FILE):
        try:
            with open(OFFSET_FILE, "r") as f:
                return int(f.read().strip())
        except:
            return 0
    return 0

def save_offset(offset):
    with open(OFFSET_FILE, "w") as f:
        f.write(str(offset))

# =====================================================================
# ЗАГРУЗКА НАЧАЛЬНЫХ ДАННЫХ С GITHUB
# =====================================================================
GITHUB_DATA_URL = "https://raw.githubusercontent.com/t1mwatson-bel/stat_twen/main/cards_data.json"

def download_initial_data():
    local_data = []
    if os.path.exists(DATA_FILE):
        try:
            with open(DATA_FILE, "r", encoding="utf-8") as f:
                local_data = json.load(f)
            print(f"📂 Загружено локальных записей: {len(local_data)}", flush=True)
        except:
            local_data = []

    if len(local_data) >= MIN_TRAIN_SAMPLES:
        print(f"✅ Локальных данных достаточно ({len(local_data)}), пропускаю скачивание с GitHub", flush=True)
        return local_data

    print(f"⚠️ Локальных данных мало ({len(local_data)}), скачиваю с GitHub...", flush=True)
    github_data = []
    try:
        response = requests.get(GITHUB_DATA_URL, timeout=30)
        if response.status_code == 200:
            github_data = response.json()
            print(f"✅ Скачано записей с GitHub: {len(github_data)}", flush=True)
        else:
            print(f"⚠️ Не удалось скачать данные (код {response.status_code})", flush=True)
    except Exception as e:
        print(f"⚠️ Ошибка скачивания: {e}", flush=True)

    merged = {}
    for record in github_data:
        game_id = record.get("game_id")
        if game_id:
            merged[game_id] = record
    for record in local_data:
        game_id = record.get("game_id")
        if game_id:
            merged[game_id] = record

    result = list(merged.values())
    if len(result) > MAX_RECORDS:
        result = result[-MAX_RECORDS:]

    with open(DATA_FILE, "w", encoding="utf-8") as f:
        json.dump(result, f, indent=2, ensure_ascii=False)

    del merged, github_data, local_data
    gc.collect()

    print(f"📊 Итого записей после объединения: {len(result)}", flush=True)
    return result

# =====================================================================
# ФУНКЦИИ API
# =====================================================================
def get_active_games():
    try:
        url = f"{BASE_URL}/service-api/main-live-feed/v3/games1x2?cfView=3&count=40&fcountry=190&gr=415&grMode=4&lng=ru&ref=7&selectedMs=10.146.1643503"
        response = requests.get(url, headers=HEADERS, timeout=10)
        
        if response.status_code == 200:
            data = response.json()
            if isinstance(data, dict) and "Value" in data:
                games = data.get("Value", [])
            elif isinstance(data, list):
                games = data
            else:
                return []
            
            active_games = []
            for game in games:
                if game.get("liga", {}).get("id") == 1643503:
                    game_id = game.get("id")
                    if game_id:
                        active_games.append(game)
            return active_games
        else:
            return []
    except Exception as e:
        print(f"❌ Ошибка API: {e}", flush=True)
        return []

def get_game_data(game_id):
    url = f"{BASE_URL}/service-api/LiveFeed/GetGameZip?id={game_id}&isSubGames=true&GroupEvents=true&countevents=250&grMode=4&partner=7&topGroups=&country=190&marketType=1&isNewBuilder=true"
    try:
        start_time = time.time()
        response = requests.get(url, headers=HEADERS, timeout=5)
        end_time = time.time()
        latency = (end_time - start_time) * 1000
        
        if response.status_code == 200:
            return response.json(), latency, start_time, end_time
        else:
            return None, None, None, None
    except Exception as e:
        print(f"❌ Ошибка игры {game_id}: {e}", flush=True)
        return None, None, None, None

def parse_cards_and_state(data):
    if not data or not isinstance(data, dict):
        return [], [], None
    
    sc = data.get("Value", {})
    if not isinstance(sc, dict):
        return [], [], None
    
    sc = sc.get("SC", {})
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
                player_cards = json.loads(item.get("Value", "[]"))
            except:
                player_cards = []
        if item.get("Key") == "P2":
            try:
                dealer_cards = json.loads(item.get("Value", "[]"))
            except:
                dealer_cards = []
        if item.get("Key") == "STATE":
            state = item.get("Value")
    
    return player_cards, dealer_cards, state

def get_game_number_by_time():
    now = datetime.now(MOSCOW_TZ)
    start = now.replace(hour=3, minute=0, second=0, microsecond=0)
    if now < start:
        start = start - timedelta(days=1)
    diff_minutes = (now - start).total_seconds() / 60
    game_number = int(diff_minutes) % 1440 + 1
    return game_number

def parse_game_from_text(text):
    try:
        game_match = re.search(r'#N(\d+)', text)
        if not game_match:
            return None
        game_number = int(game_match.group(1))
        
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
            cards_match = re.search(r'\(([^)]+)\)', part)
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
                if i + 1 < len(cards_str) and cards_str[i:i+2] == '10':
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
                        suit = cards_str[i].replace('♠', '♠️').replace('♣', '♣️').replace('♦', '♦️').replace('♥', '♥️')
                        i += 1
                    else:
                        i += 1
                        continue
                if rank and suit:
                    cards.append({"rank": rank, "suit": suit})
            return cards
        
        player_cards = parse_cards_from_part(player_part)
        dealer_cards = parse_cards_from_part(dealer_part)
        
        return {
            "number": game_number,
            "player_cards": player_cards,
            "dealer_cards": dealer_cards,
            "text": text
        }
    except Exception as e:
        print(f"❌ Ошибка парсинга: {e}", flush=True)
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
        if rank and suit and rank != "?" and suit != "?":
            all_cards.append(rank + suit)
    
    game_history.append({
        "latency": latency,
        "cards": all_cards,
        "game_num": game_num,
        "timestamp": datetime.now(MOSCOW_TZ).isoformat()
    })
    save_game_history()

def get_history_features():
    features = {}
    
    if len(game_history) >= 2:
        latencies = [g["latency"] for g in game_history]
        features["prev_latency"] = latencies[-2]
        features["latency_delta"] = latencies[-1] - latencies[-2]
        
        if len(latencies) >= 5:
            recent = latencies[-5:]
            features["latency_trend"] = (recent[-1] - recent[0]) / 5
    
    if len(game_history) >= 2:
        all_cards = []
        for g in game_history:
            all_cards.extend(g.get("cards", []))
        
        if all_cards:
            last_card = all_cards[-1] if all_cards else ""
            if last_card in TARGET_CARDS:
                features["prev_card"] = TARGET_CARDS.index(last_card)
    
    now = datetime.now(MOSCOW_TZ)
    features["hour"] = now.hour
    features["minute"] = now.minute
    features["day_of_week"] = now.weekday()
    features["is_weekend"] = 1 if now.weekday() >= 5 else 0
    
    return features

# =====================================================================
# РАСШИРЕННЫЕ ML-ФУНКЦИИ
# =====================================================================
def extract_features_from_game(game_data, latency, game_num):
    if not game_data:
        return None
    
    player_cards = game_data.get("player_cards", [])
    dealer_cards = game_data.get("dealer_cards", [])
    
    features = {
        "latency": latency,
        "game_num": game_num % 100,
        "p1_rank_val": 0, "p1_suit": -1,
        "p2_rank_val": 0, "p2_suit": -1,
        "p3_rank_val": 0, "p3_suit": -1,
        "d1_rank_val": 0, "d1_suit": -1,
        "d2_rank_val": 0, "d2_suit": -1,
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
        "player_dealer_ratio": 0,
        "card_density": 0
    }
    
    for i, card in enumerate(player_cards[:3]):
        rank = card.get("rank", "")
        suit = card.get("suit", "")
        if rank in RANK_VALUES:
            features[f"p{i+1}_rank_val"] = RANK_VALUES[rank]
        if suit in SUITS:
            features[f"p{i+1}_suit"] = SUITS.index(suit)
    
    for i, card in enumerate(dealer_cards[:2]):
        rank = card.get("rank", "")
        suit = card.get("suit", "")
        if rank in RANK_VALUES:
            features[f"d{i+1}_rank_val"] = RANK_VALUES[rank]
        if suit in SUITS:
            features[f"d{i+1}_suit"] = SUITS.index(suit)
    
    player_total = 0
    for card in player_cards:
        rank = card.get("rank", "")
        if rank in RANK_VALUES:
            val = RANK_VALUES[rank]
            if val >= 11:
                player_total += 10
            else:
                player_total += val
    features["player_total"] = player_total
    
    dealer_total = 0
    for card in dealer_cards:
        rank = card.get("rank", "")
        if rank in RANK_VALUES:
            val = RANK_VALUES[rank]
            if val >= 11:
                dealer_total += 10
            else:
                dealer_total += val
    features["dealer_total"] = dealer_total
    
    # Производные признаки
    features["player_dealer_ratio"] = player_total / max(dealer_total, 1)
    features["card_density"] = (len(player_cards) + len(dealer_cards)) / 4
    
    # Признаки из истории
    if len(game_history) >= 2:
        prev_games = list(game_history)[-2:]
        features["trend"] = prev_games[1].get("latency", 0) - prev_games[0].get("latency", 0)
    
    history_features = get_history_features()
    for key, value in history_features.items():
        if key in features:
            features[key] = value
    
    return features

# =====================================================================
# ПОИСК ПАТТЕРНОВ
# =====================================================================
def find_patterns(data):
    patterns = {
        "sequences": [],
        "time_patterns": {},
        "clusters": []
    }
    
    if len(data) < 50:
        return patterns
    
    # 1. Повторяющиеся последовательности
    sequences = []
    for game in data[-1000:]:
        cards = game.get("player_cards", []) + game.get("dealer_cards", [])
        if len(cards) >= 2:
            seq = "→".join([f"{c.get('rank','')}{c.get('suit','')}" for c in cards[:4]])
            sequences.append(seq)
    
    seq_counter = Counter(sequences)
    patterns["sequences"] = [s for s, c in seq_counter.most_common(10) if c >= 3]
    
    # 2. Временные паттерны
    hour_card_map = defaultdict(Counter)
    for game in data[-2000:]:
        try:
            timestamp = game.get("timestamp_msk", "")
            if timestamp:
                hour = int(timestamp.split(":")[0])
                all_cards = game.get("player_cards", []) + game.get("dealer_cards", [])
                for card in all_cards:
                    card_str = f"{card.get('rank','')}{card.get('suit','')}"
                    if card_str in TARGET_CARDS:
                        hour_card_map[hour][card_str] += 1
        except:
            continue
    
    patterns["time_patterns"] = {
        hour: [c for c, _ in counter.most_common(3)]
        for hour, counter in hour_card_map.items()
    }
    
    return patterns

# =====================================================================
# АНАЛИЗ ОШИБОК
# =====================================================================
def analyze_errors_and_improve():
    global error_patterns
    
    if not os.path.exists(ERROR_FILE):
        return
    
    try:
        with open(ERROR_FILE, "r") as f:
            errors = json.load(f)
    except:
        return
    
    if len(errors) < 10:
        return
    
    print(f"📊 Анализирую {len(errors)} ошибок для улучшения...", flush=True)
    
    error_by_card = defaultdict(list)
    for error in errors[-100:]:
        card = error.get("correct_card")
        if card:
            error_by_card[card].append(error)
    
    new_patterns = []
    for card, card_errors in error_by_card.items():
        if len(card_errors) >= 5:
            feature_counter = Counter()
            for err in card_errors:
                features = err.get("features", {})
                for key, value in features.items():
                    if isinstance(value, (int, float)):
                        feature_counter[f"{key}_{value}"] += 1
            
            top_patterns = feature_counter.most_common(5)
            new_patterns.append({
                "card": card,
                "patterns": top_patterns,
                "count": len(card_errors)
            })
    
    if new_patterns:
        print(f"✅ Найдено {len(new_patterns)} новых паттернов ошибок", flush=True)
        error_patterns.extend(new_patterns)
        
        with open(PATTERN_FILE, "w") as f:
            json.dump(error_patterns, f, indent=2)

# =====================================================================
# ОБУЧЕНИЕ МОДЕЛИ
# =====================================================================
def train_advanced_model():
    global ml_model, ml_initialized, feature_importance, scaler
    
    data = load_data()
    if len(data) < MIN_TRAIN_SAMPLES:
        print(f"⚠️ ML: недостаточно данных ({len(data)}/{MIN_TRAIN_SAMPLES})", flush=True)
        return False
    
    X = []
    y = []
    feature_names = None
    
    print(f"🧠 ML: расширенное обучение на {len(data)} играх...", flush=True)
    
    for game in data:
        all_cards = game.get("player_cards", []) + game.get("dealer_cards", [])
        if not all_cards:
            continue
        
        features = extract_features_from_game(game, game.get("latency_ms", 0), 0)
        if not features:
            continue
        
        feature_vector = []
        sorted_keys = sorted(features.keys())
        if not feature_names:
            feature_names = sorted_keys
        for key in sorted_keys:
            feature_vector.append(features[key])
        
        for card in all_cards:
            rank = card.get("rank", "")
            suit = card.get("suit", "")
            card_str = rank + suit
            if card_str in TARGET_CARDS:
                X.append(feature_vector)
                y.append(TARGET_CARDS.index(card_str))
                break
    
    if len(X) < MIN_TRAIN_SAMPLES:
        print(f"⚠️ ML: недостаточно примеров ({len(X)}/{MIN_TRAIN_SAMPLES})", flush=True)
        return False
    
    X = np.array(X)
    y = np.array(y)
    
    # Нормализуем
    X_scaled = scaler.fit_transform(X)
    
    print(f"🧠 ML: обучение ансамбля на {len(X)} примерах...", flush=True)
    
    # Ансамбль из 3 моделей
    rf = RandomForestClassifier(
        n_estimators=80,
        max_depth=6,
        min_samples_split=4,
        min_samples_leaf=2,
        random_state=42,
        n_jobs=1,
        class_weight='balanced'
    )
    
    mlp = MLPClassifier(
        hidden_layer_sizes=(30, 15),
        activation='relu',
        learning_rate='adaptive',
        max_iter=200,
        random_state=42,
        early_stopping=True,
        n_iter_no_change=10
    )
    
    lr = LogisticRegression(
        multi_class='multinomial',
        solver='lbfgs',
        max_iter=150,
        C=1.5,
        random_state=42
    )
    
    ensemble = VotingClassifier(
        estimators=[
            ('rf', rf),
            ('mlp', mlp),
            ('lr', lr)
        ],
        voting='soft',
        weights=[2, 1, 1]
    )
    
    ensemble.fit(X_scaled, y)
    
    ml_model = ensemble
    feature_importance = rf.feature_importances_
    ml_initialized = True
    
    try:
        with open(ML_MODEL_FILE, 'wb') as f:
            pickle.dump({
                'model': ensemble,
                'scaler': scaler,
                'feature_count': len(X[0]),
                'train_samples': len(X),
                'total_games': len(data),
                'feature_names': feature_names,
                'feature_importance': feature_importance.tolist()
            }, f)
        print(f"✅ Ансамбль сохранён! Обучено на {len(X)} примерах", flush=True)
    except Exception as e:
        print(f"⚠️ Ошибка сохранения: {e}", flush=True)
        return False
    finally:
        del X, y, X_scaled, data
        gc.collect()
    
    return True

def load_advanced_model():
    global ml_model, ml_initialized, scaler, feature_importance
    
    if not os.path.exists(ML_MODEL_FILE):
        return False
    
    try:
        with open(ML_MODEL_FILE, 'rb') as f:
            data = pickle.load(f)
            ml_model = data['model']
            if 'scaler' in data:
                scaler = data['scaler']
            ml_initialized = True
            feature_importance = data.get('feature_importance', [])
            print(f"✅ Модель загружена ({data.get('train_samples', 0)} примеров)", flush=True)
            return True
    except Exception as e:
        print(f"⚠️ Не удалось загрузить модель: {e}", flush=True)
        return False

def load_error_patterns():
    global error_patterns
    if os.path.exists(PATTERN_FILE):
        try:
            with open(PATTERN_FILE, "r") as f:
                error_patterns = json.load(f)
            print(f"📊 Загружено паттернов ошибок: {len(error_patterns)}", flush=True)
        except:
            pass

# =====================================================================
# РАСШИРЕННЫЙ ПРОГНОЗ
# =====================================================================
def predict_advanced(features):
    global ml_model, ml_initialized, scaler, error_patterns, stats
    
    if not ml_initialized or not ml_model:
        return None, None, None
    
    try:
        feature_vector = []
        for key in sorted(features.keys()):
            feature_vector.append(features[key])
        
        X_pred = np.array([feature_vector])
        X_scaled = scaler.transform(X_pred)
        
        probs = ml_model.predict_proba(X_scaled)[0]
        
        sorted_indices = np.argsort(probs)[::-1]
        top_cards = [(TARGET_CARDS[i], probs[i]) for i in sorted_indices[:3]]
        confidence = probs[sorted_indices[0]]
        
        # Анализ паттернов ошибок
        current_cards = []
        for key in ['p1_rank_val', 'p2_rank_val', 'p3_rank_val', 'd1_rank_val', 'd2_rank_val']:
            if key in features and features[key] > 0:
                current_cards.append(features[key])
        
        if error_patterns and len(current_cards) >= 2:
            card_patterns = []
            for pattern in error_patterns:
                card = pattern.get("card")
                if card:
                    card_probs = pattern.get("patterns", [])
                    for prob_pattern, count in card_probs:
                        if count >= 3 and any(str(c) in prob_pattern for c in current_cards[:3]):
                            card_patterns.append(card)
            
            if card_patterns:
                corrected_cards = []
                for card, prob in top_cards:
                    if card in card_patterns:
                        prob = min(prob * 1.2, 0.95)
                    corrected_cards.append((card, prob))
                top_cards = corrected_cards
                confidence = max(prob for _, prob in top_cards)
        
        # ТОП-1 при высокой уверенности
        is_high_confidence = confidence >= 0.75
        
        print(f"📊 Топ-3 карты:", flush=True)
        for i, (card, prob) in enumerate(top_cards[:3], 1):
            print(f"   {i}. {card} — {prob*100:.1f}%", flush=True)
        print(f"📊 Макс. уверенность: {confidence*100:.1f}%", flush=True)
        
        if is_high_confidence:
            print(f"✅ ВЫСОКАЯ УВЕРЕННОСТЬ → ТОП-1: {top_cards[0][0]}", flush=True)
            stats["high_confidence"] += 1
            top_cards = top_cards[:1]
        
        return top_cards, "ensemble", confidence
        
    except Exception as e:
        print(f"⚠️ Ошибка ML-прогноза: {e}", flush=True)
        return None, None, None

def get_advanced_prediction(latency, current_game_data):
    if not ml_initialized:
        print(f"⏳ ML модель не инициализирована", flush=True)
        return None, None, None
    
    if not current_game_data:
        print(f"⏳ Нет данных о текущей игре", flush=True)
        return None, None, None
    
    features = extract_features_from_game(current_game_data, latency, 0)
    if not features:
        print(f"⏳ Не удалось извлечь признаки", flush=True)
        return None, None, None
    
    ml_cards, method, confidence = predict_advanced(features)
    
    if ml_cards and confidence:
        if confidence >= ML_CONFIDENCE_THRESHOLD:
            print(f"✅ Уверенность {confidence*100:.1f}% >= {ML_CONFIDENCE_THRESHOLD*100:.0f}% → ДАЮ ПРОГНОЗ!", flush=True)
            return ml_cards, method, confidence
        else:
            print(f"⏭️ Уверенность {confidence*100:.1f}% < {ML_CONFIDENCE_THRESHOLD*100:.0f}% → ПРОПУСКАЮ", flush=True)
            return None, None, None
    
    return None, None, None

# =====================================================================
# ПРОВЕРКА РЕЗУЛЬТАТОВ С ОБУЧЕНИЕМ НА ОШИБКАХ
# =====================================================================
def check_results():
    global predictions, stats, all_messages, ml_model, error_patterns, ml_initialized
    
    for entry in predictions:
        if entry.get("status") != "pending":
            continue

        target = entry.get("target")
        predicted_cards = entry.get("cards", [])
        message_id = entry.get("message_id")
        method = entry.get("method", "ensemble")
        original_text = entry.get("original_text", "")
        confidence = entry.get("confidence", 0)

        if not predicted_cards or not message_id:
            continue

        max_games_to_check = DOGON_GAMES

        for i in range(max_games_to_check):
            game_to_check = target + i

            game_msg = None
            for msg in all_messages:
                if isinstance(msg, tuple):
                    text = msg[0]
                else:
                    text = msg
                if f"#N{game_to_check}" in text and ('✅' in text or '🔰' in text):
                    game_msg = text
                    break

            if not game_msg:
                continue

            game_data = parse_game_from_text(game_msg)
            if not game_data:
                continue

            found = False
            found_card = None
            all_cards = game_data.get("player_cards", []) + game_data.get("dealer_cards", [])
            actual_cards = []
            
            for card in all_cards:
                rank = card.get("rank", "")
                suit = card.get("suit", "")
                if rank == "?" or suit == "?":
                    continue
                card_str = rank + suit
                actual_cards.append(card_str)
                if card_str in predicted_cards:
                    found = True
                    found_card = card_str
                    break

            # ПОПАДАНИЕ
            if found:
                print(f"🎯 КАРТА НАЙДЕНА! {found_card} в игре #{game_to_check} (догон {i})", flush=True)

                stats["total"] += 1
                stats["win"] += 1
                stats["by_dogon"][i] = stats["by_dogon"].get(i, 0) + 1
                stats["ml_wins"] += 1
                stats["card_hits"][found_card] += 1
                
                if confidence >= 0.75 and len(predicted_cards) == 1:
                    stats["top1_hits"] += 1

                if i == 0:
                    result_text = f"\n\n✅ ЗАШЛО в целевой игре: #{game_to_check}\n   Выпала: {found_card}"
                else:
                    result_text = f"\n\n✅ ЗАШЛО на догоне {i}: #{game_to_check}\n   Выпала: {found_card}"

                if message_id:
                    edit_message(message_id, original_text + result_text)
                entry["status"] = "win"
                entry["result_game"] = game_to_check
                entry["dogon"] = i
                entry["found_card"] = found_card
                save_history(predictions)
                return

            # ОШИБКА - УЧИМСЯ
            if i == max_games_to_check - 1 and not found:
                print(f"❌ Карты {', '.join(predicted_cards)} НЕ НАЙДЕНЫ", flush=True)

                actual_target = None
                for card_str in actual_cards:
                    if card_str in TARGET_CARDS:
                        actual_target = card_str
                        break

                if actual_target:
                    print(f"📘 ОШИБКА: ждали {predicted_cards}, выпала {actual_target}")
                    stats["total"] += 1
                    stats["lose"] += 1
                    stats["ml_losses"] += 1

                    # Сохраняем ошибку для обучения
                    try:
                        features = extract_features_from_game(game_data, game_data.get("latency_ms", 0), target)
                        if features:
                            errors = []
                            if os.path.exists(ERROR_FILE):
                                with open(ERROR_FILE, 'r') as f:
                                    errors = json.load(f)
                            
                            errors.append({
                                "timestamp": datetime.now(MOSCOW_TZ).isoformat(),
                                "features": features,
                                "correct_card": actual_target,
                                "predicted_cards": predicted_cards,
                                "game_num": target,
                                "confidence": confidence
                            })
                            
                            if len(errors) > 500:
                                errors = errors[-500:]
                            
                            with open(ERROR_FILE, 'w') as f:
                                json.dump(errors, f, indent=2)
                            print(f"📝 Ошибка сохранена (всего: {len(errors)})", flush=True)
                            
                            if len(errors) % 20 == 0:
                                analyze_errors_and_improve()
                                if len(load_data()) >= MIN_TRAIN_SAMPLES:
                                    print("🔄 Запускаю переобучение...", flush=True)
                                    train_advanced_model()
                                    
                    except Exception as e:
                        print(f"⚠️ Ошибка при дообучении: {e}", flush=True)

                    result_text = f"\n\n❌ НЕ ЗАШЛО (проверено {max_games_to_check} игр)\n   Выпала: {actual_target}\n   🧠 Ошибка проанализирована"
                    if message_id:
                        edit_message(message_id, original_text + result_text)
                    entry["status"] = "lose"
                    entry["actual_card"] = actual_target
                    save_history(predictions)
                    return

# =====================================================================
# ПЛАНИРОВЩИК
# =====================================================================
def schedule_for_game(game_number):
    global predictions
    
    target = game_number + OFFSET
    
    for entry in predictions:
        if entry.get("target") == target and entry.get("status") in ("scheduled", "pending"):
            return
    
    predictions.append({
        "source": game_number,
        "target": target,
        "offset": OFFSET,
        "status": "scheduled",
        "created": datetime.now(MOSCOW_TZ).isoformat(),
    })
    
    if len(predictions) > 200:
        predictions = predictions[-200:]
    
    save_history(predictions)
    print(f"📅 Запланирован прогноз: #{game_number} → #{target} (+{OFFSET})", flush=True)

def is_predicted_card_in_current_game(predicted_cards, current_game_data):
    if not predicted_cards or not current_game_data:
        return False
    
    player_cards = current_game_data.get("player_cards", [])[:2]
    dealer_cards = current_game_data.get("dealer_cards", [])[:2]
    check_cards = player_cards + dealer_cards
    
    current_card_strings = []
    for card in check_cards:
        rank = card.get("rank", "")
        suit = card.get("suit", "")
        if rank and suit and rank != "?" and suit != "?":
            current_card_strings.append(rank + suit)
    
    for predicted_card in predicted_cards:
        if predicted_card in current_card_strings:
            return True
    return False

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
        
        print(f"🔥 До цели #{target} осталось {games_left} игр! Делаю прогноз...", flush=True)
        
        latency = None
        active_games = get_active_games()
        for game in active_games:
            game_id = str(game.get("id"))
            data, measured_latency, _, _ = get_game_data(game_id)
            if data:
                latency = measured_latency
                break
        
        if latency is None:
            print("⏳ Не удалось получить задержку", flush=True)
            continue
        
        current_game_data = None
        for msg in all_messages:
            if isinstance(msg, tuple):
                text = msg[0]
            else:
                text = msg
            if f"#N{current_num}" in text:
                current_game_data = parse_game_from_text(text)
                break
        
        if not current_game_data:
            print(f"⏳ Нет данных о текущей игре #{current_num}", flush=True)
            continue
        
        predicted_cards, method, confidence = get_advanced_prediction(latency, current_game_data)
        
        if not predicted_cards:
            print(f"⏭️ Нет прогноза для #{target}", flush=True)
            continue
        
        if is_predicted_card_in_current_game(predicted_cards, current_game_data):
            predicted_card_str = ", ".join(predicted_cards)
            print(f"⏭️ Прогнозируемая карта ({predicted_card_str}) уже есть в текущей игре → пропускаю", flush=True)
            continue
        
        if current_game_data:
            all_cards = current_game_data.get("player_cards", []) + current_game_data.get("dealer_cards", [])
            update_game_history(latency, all_cards, current_num)
        
        total_prob = 0
        is_top1 = len(predicted_cards) == 1
        
        if is_top1:
            msg = f"🔮 ТОЧНАЯ КАРТА (ML ТОП-1)\n\n"
        else:
            msg = f"🔮 ТОЧНАЯ КАРТА (ML ТОП-2)\n\n"
        
        msg += f"🎯 Целевая игра: #N{target} (+{OFFSET})\n"
        msg += f"🤖 Метод: Ансамбль (увер. {confidence*100:.1f}%)\n"
        msg += f"⏰ Прогноз: {datetime.now(MOSCOW_TZ).strftime('%H:%M:%S')}\n\n"
        msg += f"📊 {'Топ-1' if is_top1 else 'Топ-2'} карта:\n"
        
        cards_list = []
        i = 1
        for card, prob in predicted_cards:
            cards_list.append(card)
            msg += f"  {i}️⃣ {card} — {prob*100:.1f}%\n"
            total_prob += prob
            i += 1
        
        msg += f"\n📊 Суммарная вероятность: {total_prob*100:.1f}%\n"
        msg += f"📈 Догон: {DOGON_GAMES - 1} игр\n"
        msg += f"📍 Ищем: любую позицию (игрок/дилер)"
        
        if current_game_data:
            p1 = current_game_data.get("player_cards", [])[0] if current_game_data.get("player_cards") else None
            p2 = current_game_data.get("dealer_cards", [])[0] if current_game_data.get("dealer_cards") else None
            p3 = current_game_data.get("player_cards", [])[1] if len(current_game_data.get("player_cards", [])) > 1 else None
            
            seq_str = ""
            if p1:
                seq_str += f"P1:{p1['rank']}{p1['suit']} "
            if p2:
                seq_str += f"D2:{p2['rank']}{p2['suit']} "
            if p3:
                seq_str += f"P3:{p3['rank']}{p3['suit']}"
            if seq_str:
                msg += f"\n📌 {seq_str}"
        
        message_id = send_message(CHANNEL_PROGNOZ, msg)
        
        if message_id:
            entry["cards"] = cards_list
            entry["method"] = method
            entry["message_id"] = message_id
            entry["original_text"] = msg
            entry["status"] = "pending"
            entry["latency"] = latency
            entry["confidence"] = confidence
            save_history(predictions)
            print(f"✅ ПРОГНОЗ ОТПРАВЛЕН: #{target} → {', '.join(cards_list)} (увер. {confidence*100:.1f}%)", flush=True)

# =====================================================================
# СБОР ДАННЫХ
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
        game_id = str(game.get("id"))
        
        if game_id in finished_games:
            continue
        
        game_data, latency, start_time, end_time = get_game_data(game_id)
        
        if not game_data or not isinstance(game_data, dict):
            continue
        
        player_cards, dealer_cards, state = parse_cards_and_state(game_data)
        
        if player_cards or dealer_cards:
            timestamp = datetime.fromtimestamp(start_time, MOSCOW_TZ) if start_time else datetime.now(MOSCOW_TZ)
            timestamp_msk_str = timestamp.strftime('%H:%M:%S.%f')[:-3]
            
            def format_card(c):
                return {"rank": RANKS.get(c.get("CV", 0), "?"), "suit": SUITS_NAMES.get(c.get("CS", 0), "?")}
            
            record = {
                "game_id": game_id,
                "timestamp_msk": timestamp_msk_str,
                "latency_ms": round(latency, 2) if latency else 0,
                "state": state,
                "player_cards": [format_card(c) for c in player_cards],
                "dealer_cards": [format_card(c) for c in dealer_cards],
            }
            
            data = save_data(record)
            
            if state in ["4", "5"]:
                finished_games.add(game_id)
                print(f"🏁 Игра {game_id} завершена (state={state}), сохранена", flush=True)
            
            if len(data) >= MAX_RECORDS:
                collection_active = False
                return
        
        time.sleep(0.5)

# =====================================================================
# СТАТИСТИКА
# =====================================================================
def send_stats_report():
    now = datetime.now(MOSCOW_TZ)
    
    win_percent = 0
    if stats['total'] > 0:
        win_percent = stats['win'] / stats['total'] * 100
    
    data_count = len(load_data())
    
    msg = f"""
📊 СТАТИСТИКА (ML АНСАМБЛЬ + ОБУЧЕНИЕ НА ОШИБКАХ)
⏰ {now.strftime('%d.%m.%Y %H:%M:%S')}
══════════════════════════════════════════
📊 Собрано игр: {data_count}/{MAX_RECORDS}
📈 Всего прогнозов: {stats['total']}
✅ Зашло: {stats['win']} ({win_percent:.1f}%)
❌ Не зашло: {stats['lose']}

🤖 ML: {stats['ml_wins']}✅ / {stats['ml_losses']}❌

🎯 Топ-1 (увер.≥75%): {stats['top1_hits']}/{stats['high_confidence']} ({stats['top1_hits']/max(stats['high_confidence'],1)*100:.1f}%)

По догонам ({DOGON_GAMES - 1} игр):
  Догон 0: {stats['by_dogon'].get(0, 0)}
  Догон 1: {stats['by_dogon'].get(1, 0)}
  Догон 2: {stats['by_dogon'].get(2, 0)}
  Догон 3: {stats['by_dogon'].get(3, 0)}"""

    msg += "\n\nТоп-5 карт:\n"
    if stats["card_hits"]:
        sorted_cards = sorted(dict(stats["card_hits"]).items(), key=lambda x: x[1], reverse=True)[:5]
        for card, count in sorted_cards:
            msg += f"  {card}: {count}\n"
    else:
        msg += "  (пока нет данных)\n"
    
    if ml_initialized:
        msg += "\n🤖 ML: АКТИВНА (ансамбль 3 моделей)"
        msg += f"\n🧠 Обучение на ошибках: {'ВКЛ' if error_patterns else 'ОЖИДАЕТ'}"
    else:
        msg += f"\n🤖 ML: ОЖИДАЕТ ({data_count}/{MIN_TRAIN_SAMPLES})"
    
    send_message(CHANNEL_STATS, msg)

# =====================================================================
# ОСНОВНОЙ ЦИКЛ
# =====================================================================
def main():
    global predictions, all_messages, stats, game_history, collection_active
    global _new_records_since_train, ml_initialized
    
    print("🔄 ТОЧНАЯ КАРТА (ML АНСАМБЛЬ + ОБУЧЕНИЕ НА ОШИБКАХ)", flush=True)
    print("=" * 60, flush=True)
    print(f"📁 Данные: {DATA_FILE}", flush=True)
    print(f"📊 Максимум записей: {MAX_RECORDS}", flush=True)
    print(f"🎯 Смещение: +{OFFSET} игр", flush=True)
    print(f"📈 Догон: {DOGON_GAMES - 1} игр", flush=True)
    print(f"⚡ Порог уверенности: {int(ML_CONFIDENCE_THRESHOLD * 100)}%", flush=True)
    print(f"🔄 Переобучение: каждые {RETRAIN_THRESHOLD} новых записей", flush=True)
    print("=" * 60, flush=True)
    
    # Загружаем данные
    existing_data = download_initial_data()
    print(f"📊 Всего записей: {len(existing_data)}", flush=True)
    
    if len(existing_data) >= MAX_RECORDS:
        collection_active = False
        print(f"⏸️ СБОР ДАННЫХ ОТКЛЮЧЁН (лимит {MAX_RECORDS})", flush=True)
    
    game_history = load_game_history()
    print(f"📈 Загружено истории: {len(game_history)} игр", flush=True)
    
    predictions = load_history()
    load_advanced_model()
    load_error_patterns()
    stats["games_collected"] = len(existing_data)
    
    # Обучаем модель если нужно
    if len(existing_data) >= MIN_TRAIN_SAMPLES and not ml_initialized:
        print(f"🧠 Данных достаточно ({len(existing_data)}), обучаю модель...", flush=True)
        train_advanced_model()
    
    send_startup_message()
    
    # Загружаем сообщения из канала
    try:
        url = f"https://api.telegram.org/bot{BOT_TOKEN}/getUpdates"
        params = {"chat_id": CHANNEL_STATS, "limit": 100}
        response = requests.get(url, params=params, timeout=10)
        if response.status_code == 200:
            data = response.json()
            for update in data.get("result", []):
                post = update.get("channel_post")
                if post and post.get("text"):
                    all_messages.append((post.get("text"), time.time()))
    except:
        pass
    
    print(f"📥 Загружено сообщений: {len(all_messages)}", flush=True)
    
    last_stats_time = time.time()
    last_check_time = time.time()
    last_gc_time = time.time()
    offset = get_offset()
    
    print("🚀 БОТ ГОТОВ К РАБОТЕ!", flush=True)
    print("=" * 60, flush=True)
    
    while True:
        try:
            current_time = time.time()
            
            # Сбор данных
            collect_game_data()
            
            # Обработка обновлений
            updates = get_updates(offset)
            for update in updates.get("result", []):
                offset = update["update_id"] + 1
                save_offset(offset)
                
                channel_post = update.get("channel_post")
                edited_post = update.get("edited_channel_post")
                post = channel_post if channel_post else edited_post
                if not post:
                    continue
                
                chat_id = post.get("chat", {}).get("id")
                if str(chat_id) != str(CHANNEL_STATS):
                    continue
                
                text = post.get("text", "")
                if not text or "#N" not in text:
                    continue
                
                all_messages.append((text, time.time()))
                if len(all_messages) > 100:
                    all_messages = all_messages[-100:]
                
                game_id_match = re.search(r'#N(\d+)', text)
                if game_id_match:
                    game_number = int(game_id_match.group(1))
                    print(f"📥 Получена игра #{game_number}", flush=True)
                    schedule_for_game(game_number)
                    check_results()
            
            # Проверка прогнозов
            if current_time - last_check_time >= CHECK_INTERVAL:
                check_and_predict()
                last_check_time = current_time
            
            check_results()
            
            # Переобучение
            if _new_records_since_train >= RETRAIN_THRESHOLD:
                data_count = len(load_data())
                if data_count >= MIN_TRAIN_SAMPLES:
                    print(f"🔄 НАКОПИЛОСЬ {_new_records_since_train} НОВЫХ ИГР → ЗАПУСК ПЕРЕОБУЧЕНИЯ...", flush=True)
                    train_advanced_model()
                    _new_records_since_train = 0
                    gc.collect()
            
            # Статистика
            if current_time - last_stats_time > 3600:
                send_stats_report()
                last_stats_time = current_time
            
            # Сборка мусора
            if current_time - last_gc_time > 30:
                gc.collect()
                last_gc_time = current_time
            
            # Ограничение списков
            if len(processed_games) > 500:
                processed_games.clear()
            if len(predictions) > 200:
                predictions = predictions[-200:]
                save_history(predictions)
            
            time.sleep(CHECK_INTERVAL)
            
        except KeyboardInterrupt:
            print("🛑 Бот остановлен", flush=True)
            data_count = len(load_data())
            print(f"📊 Всего собрано записей: {data_count}", flush=True)
            break
        except Exception as e:
            print(f"❌ Ошибка: {e}", flush=True)
            import traceback
            traceback.print_exc()
            time.sleep(30)

if __name__ == "__main__":
    main()