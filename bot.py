import os
import sys
import subprocess
import importlib

# =====================================================================
# АВТОУСТАНОВКА ЗАВИСИМОСТЕЙ
# =====================================================================
REQUIRED_PACKAGES = ['numpy', 'catboost', 'scikit-learn', 'requests', 'pytz']

def install_package(package):
    print(f"📦 Устанавливаю: {package}...", flush=True)
    try:
        subprocess.check_call([sys.executable, "-m", "pip", "install", package, "--quiet", "--no-cache-dir"])
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
# ТЕПЕРЬ ИМПОРТИРУЕМ ВСЁ ОСТАЛЬНОЕ
# =====================================================================
import requests
import json
import re
import time
import pickle
import numpy as np
from datetime import datetime, timedelta
import pytz
from collections import deque, defaultdict
import warnings
import gc
warnings.filterwarnings('ignore')

try:
    from catboost import CatBoostClassifier
    ML_AVAILABLE = True
    print("✅ CatBoost загружен!", flush=True)
except ImportError:
    ML_AVAILABLE = False
    print("⚠️ CatBoost не установлен.", flush=True)

# =====================================================================
# ПЕРЕМЕННЫЕ ОКРУЖЕНИЯ
# =====================================================================
BOT_TOKEN = os.getenv('BOT_TOKEN')
if not BOT_TOKEN:
    BOT_TOKEN = os.getenv('BOT_TOKEN_PROGNOZ')

CHANNEL_STATS = os.getenv('CHANNEL_STATS')
CHANNEL_PROGNOZ = os.getenv('CHANNEL_PROGNOZ')

if not BOT_TOKEN or not CHANNEL_STATS or not CHANNEL_PROGNOZ:
    print("❌ ОШИБКА: переменные окружения не заданы!", flush=True)
    sys.exit(1)

# =====================================================================
# НАСТРОЙКИ (ОПТИМИЗИРОВАНЫ ДЛЯ ПАМЯТИ)
# =====================================================================
MOSCOW_TZ = pytz.timezone('Europe/Moscow')
BASE_URL = "https://1xlite-36553.pro"

DATA_FILE = "cards_data.json"
HISTORY_FILE = "cards_history.json"
ML_MODEL_FILE = "cards_model.pkl"
OFFSET_FILE = "cards_offset.txt"
GAME_HISTORY_FILE = "cards_game_history.json"

MAX_RECORDS = 3000
CHECK_INTERVAL = 5
OFFSET = 1
MIN_TRAIN_SAMPLES = 300
MAX_HISTORY = 500
MAX_GAME_HISTORY = 5
DOGON_GAMES = 4
ML_CONFIDENCE_THRESHOLD = 0.60
MAX_TRAIN_SAMPLES = 2000

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
stats = {"total": 0, "win": 0, "lose": 0, "by_dogon": {0: 0, 1: 0, 2: 0, 3: 0}, "ml_wins": 0, "ml_losses": 0, "games_collected": 0, "last_report": time.time(), "card_hits": defaultdict(int)}
processed_games = set()
finished_games = set()
all_messages = []
predictions = []

# =====================================================================
# ТЕЛЕГРАМ
# =====================================================================
def get_updates(offset):
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/getUpdates"
    try:
        r = requests.get(url, params={"offset": offset, "timeout": 30}, timeout=35)
        return r.json()
    except Exception as e:
        print(f"❌ getUpdates: {e}")
        return {}

def send_message(chat_id, text):
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
    try:
        r = requests.post(url, json={"chat_id": chat_id, "text": text, "parse_mode": "HTML"}, timeout=10)
        if r.status_code == 200:
            return r.json()["result"]["message_id"]
    except:
        pass
    return None

def edit_message(message_id, text):
    if not message_id:
        return False
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/editMessageText"
    try:
        r = requests.post(url, json={"chat_id": CHANNEL_PROGNOZ, "message_id": message_id, "text": text, "parse_mode": "HTML"}, timeout=10)
        return r.status_code == 200
    except:
        return False

def send_startup_message():
    data_count = len(load_data())
    msg = f"""
🃏 ТОЧНАЯ КАРТА (ML ТОП-2)
📊 Собрано игр: {data_count}/{MAX_RECORDS}
🧠 ML: {'✅ АКТИВНА' if ml_initialized else '⏳ ОЖИДАЕТ'}
🎯 Смещение: +{OFFSET} игр
📈 Догон: {DOGON_GAMES - 1} игр
⚡ Порог уверенности ML: {int(ML_CONFIDENCE_THRESHOLD * 100)}%
⏰ {datetime.now(MOSCOW_TZ).strftime('%d.%m.%Y %H:%M:%S')}
"""
    send_message(CHANNEL_PROGNOZ, msg)
    print("🚀 БОТ ЗАПУЩЕН!")

# =====================================================================
# ДАННЫЕ
# =====================================================================
def load_data():
    if not os.path.exists(DATA_FILE):
        return []
    try:
        with open(DATA_FILE, 'r') as f:
            data = json.load(f)
            return data[-MAX_RECORDS:] if len(data) > MAX_RECORDS else data
    except:
        return []

def save_data(record):
    global collection_active, stats
    data = load_data()
    if len(data) >= MAX_RECORDS:
        collection_active = False
        return data
    for i, r in enumerate(data):
        if r.get("game_id") == record["game_id"]:
            data[i] = record
            break
    else:
        data.append(record)
        stats["games_collected"] += 1
    if len(data) > MAX_RECORDS:
        data = data[-MAX_RECORDS:]
    with open(DATA_FILE, 'w') as f:
        json.dump(data, f, indent=2)
    return data

def load_history():
    if not os.path.exists(HISTORY_FILE):
        return []
    try:
        with open(HISTORY_FILE, 'r') as f:
            data = json.load(f)
            return data[-MAX_HISTORY:] if len(data) > MAX_HISTORY else data
    except:
        return []

def save_history(history):
    if len(history) > MAX_HISTORY:
        history = history[-MAX_HISTORY:]
    with open(HISTORY_FILE, 'w') as f:
        json.dump(history, f, indent=2)

def get_offset():
    try:
        with open(OFFSET_FILE, 'r') as f:
            return int(f.read().strip())
    except:
        return 0

def save_offset(offset):
    with open(OFFSET_FILE, 'w') as f:
        f.write(str(offset))

# =====================================================================
# API
# =====================================================================
def get_active_games():
    url = f"{BASE_URL}/service-api/main-live-feed/v3/games1x2?cfView=3&count=40&fcountry=190&gr=415&grMode=4&lng=ru&ref=7&selectedMs=10.146.1643503"
    try:
        r = requests.get(url, headers=HEADERS, timeout=10)
        if r.status_code != 200:
            return []
        data = r.json()
        games = data.get("Value", []) if isinstance(data, dict) else data
        return [g for g in games if g.get("liga", {}).get("id") == 1643503 and g.get("id")]
    except:
        return []

def get_game_data(game_id):
    url = f"{BASE_URL}/service-api/LiveFeed/GetGameZip?id={game_id}&isSubGames=true&GroupEvents=true&countevents=250&grMode=4&partner=7&topGroups=&country=190&marketType=1&isNewBuilder=true"
    try:
        t0 = time.time()
        r = requests.get(url, headers=HEADERS, timeout=5)
        latency = (time.time() - t0) * 1000
        if r.status_code == 200:
            return r.json(), latency
    except:
        pass
    return None, None

def get_game_number_by_time():
    now = datetime.now(MOSCOW_TZ)
    start = now.replace(hour=3, minute=0, second=0)
    if now < start:
        start = start - timedelta(days=1)
    return int((now - start).total_seconds() / 60) % 1440 + 1

def parse_game_from_text(text):
    try:
        m = re.search(r'#N(\d+)', text)
        if not m:
            return None
        num = int(m.group(1))
        parts = None
        for sep in ['◀️', '▶️', '—', ' - ', '-']:
            if sep in text:
                parts = text.split(sep, 1)
                break
        if not parts or len(parts) < 2:
            return None
        def parse_cards(part):
            m2 = re.search(r'\(([^)]*)\)', part)
            if not m2:
                return []
            s = m2.group(1)
            cards = []
            i = 0
            while i < len(s):
                if s[i].isspace():
                    i += 1
                    continue
                if s.startswith('10', i):
                    rank = '10'
                    i += 2
                elif s[i] in 'AKQJ' or s[i].isdigit():
                    rank = s[i]
                    i += 1
                else:
                    i += 1
                    continue
                suit = None
                for sym in SUITS:
                    if s.startswith(sym, i):
                        suit = sym
                        i += len(sym)
                        break
                if suit and rank:
                    cards.append({"rank": rank, "suit": suit})
            return cards
        return {"number": num, "player_cards": parse_cards(parts[0]), "dealer_cards": parse_cards(parts[1]), "text": text}
    except:
        return None

# =====================================================================
# ML
# =====================================================================
def extract_features(game_data, latency, game_num):
    if not game_data:
        return None
    pc = game_data.get("player_cards", [])
    dc = game_data.get("dealer_cards", [])
    f = {
        "latency": latency,
        "game_num": game_num % 100,
        "p1_rank_val": 0, "p2_rank_val": 0, "p3_rank_val": 0,
        "d1_rank_val": 0, "d2_rank_val": 0,
        "player_total": 0, "dealer_total": 0,
        "player_count": len(pc), "dealer_count": len(dc),
        "hour": datetime.now(MOSCOW_TZ).hour,
        "minute": datetime.now(MOSCOW_TZ).minute,
        "day_of_week": datetime.now(MOSCOW_TZ).weekday(),
        "is_weekend": 1 if datetime.now(MOSCOW_TZ).weekday() >= 5 else 0,
    }
    for i, c in enumerate(pc[:3]):
        if c.get("rank") in RANK_VALUES:
            f[f"p{i+1}_rank_val"] = RANK_VALUES[c.get("rank")]
    for i, c in enumerate(dc[:2]):
        if c.get("rank") in RANK_VALUES:
            f[f"d{i+1}_rank_val"] = RANK_VALUES[c.get("rank")]
    for c in pc:
        if c.get("rank") in RANK_VALUES:
            v = RANK_VALUES[c.get("rank")]
            f["player_total"] += 10 if v >= 11 else v
    for c in dc:
        if c.get("rank") in RANK_VALUES:
            v = RANK_VALUES[c.get("rank")]
            f["dealer_total"] += 10 if v >= 11 else v
    return f

def train_ml_model():
    global ml_model, ml_initialized
    if not ML_AVAILABLE:
        return False
    data = load_data()
    if len(data) < MIN_TRAIN_SAMPLES:
        print(f"⚠️ Мало данных: {len(data)}/{MIN_TRAIN_SAMPLES}")
        return False
    X, y, fn = [], [], None
    print(f"🧠 Обучение на {len(data)} играх...")
    for game in data:
        cards = game.get("player_cards", []) + game.get("dealer_cards", [])
        if not cards:
            continue
        f = extract_features(game, game.get("latency_ms", 0), 0)
        if not f:
            continue
        v = []
        for k in sorted(f.keys()):
            v.append(f[k])
        if not fn:
            fn = sorted(f.keys())
        for c in cards:
            cs = c.get("rank", "") + c.get("suit", "")
            if cs in TARGET_CARDS:
                X.append(v)
                y.append(TARGET_CARDS.index(cs))
                break
    if len(X) < MIN_TRAIN_SAMPLES:
        print(f"⚠️ Мало примеров: {len(X)}/{MIN_TRAIN_SAMPLES}")
        return False
    if len(X) > MAX_TRAIN_SAMPLES:
        import random
        idx = random.sample(range(len(X)), MAX_TRAIN_SAMPLES)
        X = [X[i] for i in idx]
        y = [y[i] for i in idx]
        print(f"📉 Сэмплировано до {MAX_TRAIN_SAMPLES}")
    X = np.array(X)
    y = np.array(y)
    model = CatBoostClassifier(iterations=150, depth=6, learning_rate=0.08, random_seed=42, verbose=False, loss_function='MultiClass', early_stopping_rounds=20, l2_leaf_reg=5, thread_count=1)
    model.fit(X, y)
    ml_model = model
    ml_initialized = True
    del X, y
    gc.collect()
    with open(ML_MODEL_FILE, 'wb') as f:
        pickle.dump({'model': model, 'feature_count': len(fn), 'train_samples': len(data), 'feature_names': fn}, f)
    print(f"✅ Модель сохранена!")
    return True

def load_ml_model():
    global ml_model, ml_initialized
    if not ML_AVAILABLE or not os.path.exists(ML_MODEL_FILE):
        return False
    try:
        with open(ML_MODEL_FILE, 'rb') as f:
            data = pickle.load(f)
            ml_model = data['model']
            ml_initialized = True
            print(f"✅ Модель загружена")
            return True
    except:
        return False

def predict_ml(features):
    if not ml_initialized or not ml_model or not features:
        return None, None
    try:
        v = [features[k] for k in sorted(features.keys())]
        probs = ml_model.predict_proba(np.array([v]))[0]
        idx = np.argsort(probs)[-2:][::-1]
        return [(TARGET_CARDS[i], probs[i]) for i in idx], probs[idx[0]]
    except:
        return None, None

def get_prediction(latency, game_data):
    if not ml_initialized or not game_data:
        return None, None, None
    f = extract_features(game_data, latency, 0)
    if not f:
        return None, None, None
    cards, conf = predict_ml(f)
    if cards and conf and conf >= ML_CONFIDENCE_THRESHOLD:
        return cards, "ml", conf
    return None, None, None

# =====================================================================
# ПРОВЕРКА РЕЗУЛЬТАТОВ
# =====================================================================
def check_results():
    global predictions, stats, all_messages
    for entry in predictions:
        if entry.get("status") != "pending":
            continue
        target = entry.get("target")
        predicted = entry.get("cards", [])
        msg_id = entry.get("message_id")
        orig = entry.get("original_text", "")
        if not predicted or not msg_id:
            continue
        for i in range(DOGON_GAMES):
            game_num = target + i
            game_msg = None
            for m in all_messages:
                if f"#N{game_num}" in m and ('✅' in m or '🔰' in m):
                    game_msg = m
                    break
            if not game_msg:
                continue
            gd = parse_game_from_text(game_msg)
            if not gd:
                continue
            found = False
            found_card = None
            cards = gd.get("player_cards", []) + gd.get("dealer_cards", [])
            actual = []
            for c in cards:
                cs = c.get("rank", "") + c.get("suit", "")
                if cs:
                    actual.append(cs)
                    if cs in predicted:
                        found = True
                        found_card = cs
                        break
            if found:
                print(f"🎯 {found_card} в игре #{game_num} (догон {i})")
                stats["total"] += 1
                stats["win"] += 1
                stats["by_dogon"][i] = stats["by_dogon"].get(i, 0) + 1
                stats["ml_wins"] += 1
                stats["card_hits"][found_card] += 1
                text = orig + f"\n\n✅ ЗАШЛО на догоне {i}: #{game_num}\n   Выпала: {found_card}"
                edit_message(msg_id, text)
                entry["status"] = "win"
                entry["result_game"] = game_num
                save_history(predictions)
                return
            if i == DOGON_GAMES - 1:
                actual_target = None
                for c in actual:
                    if c in TARGET_CARDS:
                        actual_target = c
                        break
                if actual_target:
                    print(f"❌ Ошибка: ждали {predicted}, выпала {actual_target}")
                    stats["total"] += 1
                    stats["lose"] += 1
                    stats["ml_losses"] += 1
                    # обучение на ошибке
                    try:
                        f = extract_features(gd, gd.get("latency_ms", 0), target)
                        if f and ml_initialized:
                            v = [f[k] for k in sorted(f.keys())]
                            X_new = np.array([v])
                            y_new = TARGET_CARDS.index(actual_target)
                            if hasattr(ml_model, 'partial_fit'):
                                ml_model.partial_fit(X_new, [y_new])
                                print(f"✅ Запомнил {actual_target}")
                    except:
                        pass
                    text = orig + f"\n\n❌ НЕ ЗАШЛО\n   Выпала: {actual_target}"
                    edit_message(msg_id, text)
                    entry["status"] = "lose"
                    save_history(predictions)
                    return
                else:
                    stats["total"] += 1
                    stats["lose"] += 1
                    stats["ml_losses"] += 1
                    text = orig + "\n\n❌ НЕ ЗАШЛО (целевых карт не было)"
                    edit_message(msg_id, text)
                    entry["status"] = "lose"
                    save_history(predictions)
                    return

# =====================================================================
# ПЛАНИРОВЩИК
# =====================================================================
def schedule_for_game(game_number):
    target = game_number + OFFSET
    for e in predictions:
        if e.get("target") == target and e.get("status") in ("scheduled", "pending"):
            return
    predictions.append({"source": target-1, "target": target, "offset": OFFSET, "status": "scheduled", "created": datetime.now(MOSCOW_TZ).isoformat()})
    if len(predictions) > 200:
        predictions = predictions[-200:]
    save_history(predictions)
    print(f"📅 Запланирован прогноз: #{target-1} → #{target}")

def check_and_predict():
    for entry in predictions:
        if entry.get("status") != "scheduled":
            continue
        target = entry.get("target")
        current = get_game_number_by_time()
        left = target - current
        if left not in (1, 2):
            continue
        print(f"🔥 До цели #{target} осталось {left} игр")
        latency = None
        for g in get_active_games():
            data, lat = get_game_data(str(g.get("id")))
            if data:
                latency = lat
                break
        if latency is None:
            continue
        game_data = None
        for m in all_messages:
            if f"#N{current}" in m:
                game_data = parse_game_from_text(m)
                break
        if not game_data:
            continue
        cards, method, conf = get_prediction(latency, game_data)
        if not cards or len(cards) < 2:
            print(f"⏭️ Нет прогноза для #{target}")
            continue
        # проверка P1, D1, P2
        pc = game_data.get("player_cards", [])
        dc = game_data.get("dealer_cards", [])
        check = []
        if pc:
            check.append(pc[0])
        if dc:
            check.append(dc[0])
        if len(pc) > 1:
            check.append(pc[1])
        pred_card = cards[0][0]
        blocked = False
        for c in check:
            if c.get("rank", "") + c.get("suit", "") == pred_card:
                blocked = True
                break
        if blocked:
            print(f"⏭️ {pred_card} уже есть среди P1,D1,P2 → пропускаю")
            continue
        total = sum(p[1] for p in cards)
        msg = f"🔮 ТОЧНАЯ КАРТА (ML ТОП-2)\n\n🎯 Целевая игра: #N{target} (+{OFFSET})\n🤖 ML (увер. {conf*100:.1f}%)\n⏰ {datetime.now(MOSCOW_TZ).strftime('%H:%M:%S')}\n\n📊 Топ-2 карты:\n"
        list_cards = []
        for i, (c, p) in enumerate(cards, 1):
            list_cards.append(c)
            msg += f"  {i}️⃣ {c} — {p*100:.1f}%\n"
        msg += f"\n📊 Суммарная вероятность: {total*100:.1f}%\n📈 Догон: {DOGON_GAMES-1} игр"
        if game_data:
            p1 = game_data.get("player_cards", [])[0] if game_data.get("player_cards") else None
            p2 = game_data.get("dealer_cards", [])[0] if game_data.get("dealer_cards") else None
            p3 = game_data.get("player_cards", [])[1] if len(game_data.get("player_cards", [])) > 1 else None
            seq = ""
            if p1:
                seq += f"P1:{p1['rank']}{p1['suit']} "
            if p2:
                seq += f"D2:{p2['rank']}{p2['suit']} "
            if p3:
                seq += f"P3:{p3['rank']}{p3['suit']}"
            if seq:
                msg += f"\n📌 {seq}"
        mid = send_message(CHANNEL_PROGNOZ, msg)
        if mid:
            entry["cards"] = list_cards
            entry["message_id"] = mid
            entry["original_text"] = msg
            entry["status"] = "pending"
            entry["confidence"] = conf
            save_history(predictions)
            print(f"✅ ПРОГНОЗ ОТПРАВЛЕН: #{target} → {', '.join(list_cards)}")

# =====================================================================
# СБОР ДАННЫХ
# =====================================================================
def collect_game_data():
    global collection_active, finished_games
    if not collection_active:
        return
    for g in get_active_games():
        gid = str(g.get("id"))
        if gid in finished_games:
            continue
        data, latency = get_game_data(gid)
        if not data:
            continue
        pc, dc, state = [], [], None
        sc = data.get("Value", {}).get("SC", {})
        for item in sc.get("S", []):
            if item.get("Key") == "P1":
                try:
                    pc = [{"rank": RANKS.get(c.get("CV", 0), "?"), "suit": SUITS_NAMES.get(c.get("CS", 0), "?")} for c in json.loads(item.get("Value", "[]"))]
                except:
                    pass
            if item.get("Key") == "P2":
                try:
                    dc = [{"rank": RANKS.get(c.get("CV", 0), "?"), "suit": SUITS_NAMES.get(c.get("CS", 0), "?")} for c in json.loads(item.get("Value", "[]"))]
                except:
                    pass
            if item.get("Key") == "STATE":
                state = item.get("Value")
        if pc or dc:
            record = {"game_id": gid, "latency_ms": latency or 0, "state": state, "player_cards": pc, "dealer_cards": dc}
            save_data(record)
            if state in ["4", "5"]:
                finished_games.add(gid)
                print(f"🏁 Игра {gid} завершена")
            if len(load_data()) >= MAX_RECORDS:
                collection_active = False
                return

# =====================================================================
# СТАТИСТИКА
# =====================================================================
def send_stats_report():
    now = datetime.now(MOSCOW_TZ)
    total = stats["total"]
    win = stats["win"]
    acc = win / total * 100 if total else 0
    msg = f"""
📊 СТАТИСТИКА
⏰ {now.strftime('%d.%m.%Y %H:%M:%S')}
══════════════════════════════════════════
📊 Собрано игр: {len(load_data())}/{MAX_RECORDS}
📈 Всего прогнозов: {total}
✅ Зашло: {win} ({acc:.1f}%)
❌ Не зашло: {stats['lose']}
🤖 ML: {stats['ml_wins']}✅ / {stats['ml_losses']}❌
"""
    send_message(CHANNEL_STATS, msg)

# =====================================================================
# MAIN
# =====================================================================
def main():
    global predictions, all_messages, stats, game_history, collection_active
    print("🔄 БОТ ЗАПУЩЕН")
    load_ml_model()
    if not ml_initialized and len(load_data()) >= MIN_TRAIN_SAMPLES:
        train_ml_model()
    predictions = load_history()
    send_startup_message()
    # Загружаем сообщения
    try:
        r = requests.get(f"https://api.telegram.org/bot{BOT_TOKEN}/getUpdates", params={"chat_id": CHANNEL_STATS, "limit": 100}, timeout=10)
        if r.status_code == 200:
            for u in r.json().get("result", []):
                p = u.get("channel_post")
                if p and p.get("text"):
                    all_messages.append(p.get("text"))
    except:
        pass
    print(f"📥 Загружено сообщений: {len(all_messages)}")
    last_train = time.time()
    last_stats = time.time()
    last_check = time.time()
    offset = get_offset()
    while True:
        try:
            now = time.time()
            collect_game_data()
            # Обновления
            updates = get_updates(offset)
            for u in updates.get("result", []):
                offset = u["update_id"] + 1
                save_offset(offset)
                p = u.get("channel_post") or u.get("edited_channel_post")
                if not p:
                    continue
                if str(p.get("chat", {}).get("id")) != str(CHANNEL_STATS):
                    continue
                text = p.get("text", "")
                if "#N" in text:
                    all_messages.append(text)
                    if len(all_messages) > 500:
                        all_messages = all_messages[-500:]
                    m = re.search(r'#N(\d+)', text)
                    if m:
                        num = int(m.group(1))
                        print(f"📥 Игра #{num}")
                        schedule_for_game(num)
                        check_results()
            if now - last_check >= CHECK_INTERVAL:
                check_and_predict()
                last_check = now
            check_results()
            if now - last_train > 600:
                if len(load_data()) >= MIN_TRAIN_SAMPLES:
                    train_ml_model()
                    gc.collect()
                last_train = now
            if now - last_stats > 3600:
                send_stats_report()
                last_stats = now
            if len(predictions) > 200:
                predictions = predictions[-200:]
                save_history(predictions)
            gc.collect()
            time.sleep(CHECK_INTERVAL)
        except KeyboardInterrupt:
            print("🛑 Остановка")
            break
        except Exception as e:
            print(f"❌ Ошибка: {e}")
            time.sleep(10)

if __name__ == "__main__":
    main()