import os
import sys
import requests
import json
import re
import time
from datetime import datetime, timedelta
import pytz

# =====================================================================
# ПРИНУДИТЕЛЬНЫЙ ВЫВОД ЛОГОВ
# =====================================================================
sys.stdout.flush()
print("=" * 60, flush=True)
print("🃏 ТЕСТ: ПОСЛЕДОВАТЕЛЬНОСТЬ (СМЕЩЕНИЕ +10, БЕЗ ТАЙМАУТА) + ВЕРОЯТНОСТИ", flush=True)
print("=" * 60, flush=True)

# =====================================================================
# ПЕРЕМЕННЫЕ ОКРУЖЕНИЯ
# =====================================================================
BOT_TOKEN = os.getenv('BOT_TOKEN')
if not BOT_TOKEN:
    BOT_TOKEN = os.getenv('BOT_TOKEN_PROGNOZ')

CHANNEL_STATS = os.getenv('CHANNEL_STATS')
CHANNEL_PROGNOZ = os.getenv('CHANNEL_PROGNOZ')

print("🔍 ДИАГНОСТИКА ПЕРЕМЕННЫХ:", flush=True)
print(f"BOT_TOKEN: {BOT_TOKEN[:5] if BOT_TOKEN else 'НЕ ЗАДАН'}", flush=True)
print(f"CHANNEL_STATS: {CHANNEL_STATS if CHANNEL_STATS else 'НЕ ЗАДАН'}", flush=True)
print(f"CHANNEL_PROGNOZ: {CHANNEL_PROGNOZ if CHANNEL_PROGNOZ else 'НЕ ЗАДАН'}", flush=True)
print("=" * 60, flush=True)

if not BOT_TOKEN or not CHANNEL_STATS or not CHANNEL_PROGNOZ:
    print("❌ ОШИБКА: переменные окружения не заданы!", flush=True)
    exit(1)

print("✅ Все переменные заданы!", flush=True)

# =====================================================================
# НАСТРОЙКИ
# =====================================================================
MOSCOW_TZ = pytz.timezone('Europe/Moscow')
BASE_URL = "https://1xlite-36553.pro"
OFFSET_FILE = "offset_seq_no_timeout.txt"
HISTORY_FILE = "history_seq_no_timeout.json"
PROBS_LOG_FILE = "prob_diff_log.json"  # для логирования разниц
MAX_HISTORY = 500
PROCESSED_GAMES = set()
LAST_PREDICT_TIME = 0
PREDICT_INTERVAL = 2
TIMEOUT_SECONDS = 1800  # 30 минут
OFFSET = 10
MIN_PROB_DIFF = 0  # пока 0, чтобы не отсеивать

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
    "Accept": "application/json, text/plain, */*",
    "Referer": f"{BASE_URL}/ru/live/twentyone/2092323-21-classics",
    "Cookie": "platform_type=desktop; SESSION=34219176f69eace1b636911e2de9a15e; lng=ru; cookies_agree_type=3; tzo=3; is12h=0; auid=uaJbk2qIgo2M+6ofAxNqAg==; _ym_isad=2; mdd=1; _ga_7JGWL9SV66=GS2.1.s1787337341$o4$g1$t1787337359$j42$l0$h1608459194; window_width=150; referral_values=%7B%22type%22%3A%22reflinkid%22%2C%22val%22%3A%22s_50970m_355c_%22%2C%22additional%22%3A%7B%22name_tag%22%3A%22tag%22%7D%7D; fatman_uuid=45f69ff0-ecb1-67d4-3ff2-3a45baafc739; che_g=777dc1b9-efbf-4728-947a-4a2992ef6da5; sh.session.id=684214c4-f09e-42da-9c1a-ea61b9aca91b; _ym_uid=1786989905737338437; _ym_d=1786989905; _ga=GA1.1.547872848.1786989906"
}

SUITS_NAMES = {0: "♠️", 1: "♣️", 2: "♦️", 3: "♥️"}

# =====================================================================
# ТАБЛИЦА ВЕРОЯТНОСТЕЙ (ПРОЦЕНТЫ)
# =====================================================================
LATENCY_PROBS = {
    (93, 95): {"♣️": 28.3, "♥️": 24.5, "♠️": 23.5, "♦️": 23.7},
    (95, 97): {"♠️": 29.1, "♥️": 28.7, "♣️": 21.5, "♦️": 20.7},
    (97, 99): {"♦️": 26.7, "♠️": 25.9, "♣️": 24.5, "♥️": 22.9},
    (99, 101): {"♥️": 27.4, "♦️": 25.3, "♠️": 24.2, "♣️": 23.1},
    (101, 103): {"♣️": 26.5, "♠️": 25.1, "♥️": 24.8, "♦️": 23.6},
    (103, 105): {"♥️": 27.8, "♦️": 24.6, "♣️": 24.2, "♠️": 23.4},
    (105, 200): {"♠️": 27.6, "♣️": 25.9, "♥️": 24.3, "♦️": 22.2},
}

def get_suit_probs(latency):
    for (low, high), probs in LATENCY_PROBS.items():
        if low <= latency < high:
            return probs
    return None

def predict_suit_with_probs(latency):
    """Возвращает (основная_масть, процент, вторая_масть, процент_второй, разница)"""
    probs = get_suit_probs(latency)
    if not probs:
        return None, None, None, None, None
    
    sorted_probs = sorted(probs.items(), key=lambda x: x[1], reverse=True)
    top_suit, top_prob = sorted_probs[0]
    second_suit, second_prob = sorted_probs[1] if len(sorted_probs) > 1 else (None, 0)
    diff = top_prob - second_prob if second_suit else 0
    
    return top_suit, top_prob, second_suit, second_prob, diff

# =====================================================================
# СТАТИСТИКА
# =====================================================================
stats = {
    "total": 0,
    "win": 0,
    "lose": 0,
    "by_dogon": {0: 0, 1: 0, 2: 0, 3: 0},
    "last_report": time.time()
}

# Лог разниц (для анализа)
prob_log = []

def load_prob_log():
    if os.path.exists(PROBS_LOG_FILE):
        try:
            with open(PROBS_LOG_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except:
            return []
    return []

def save_prob_log():
    try:
        with open(PROBS_LOG_FILE, "w", encoding="utf-8") as f:
            json.dump(prob_log[-1000:], f, indent=2, ensure_ascii=False)
    except:
        pass

def update_stats(dogon_number, result):
    stats["total"] += 1
    if result == "win":
        stats["win"] += 1
        if dogon_number in stats["by_dogon"]:
            stats["by_dogon"][dogon_number] += 1
        else:
            stats["by_dogon"][dogon_number] = 1
    else:
        stats["lose"] += 1

def send_stats_report():
    now = datetime.now(MOSCOW_TZ)
    msg = f"📊 <b>СТАТИСТИКА (ПОСЛЕДОВАТЕЛЬНОСТЬ +10) + ВЕРОЯТНОСТИ</b>\n"
    msg += f"⏰ {now.strftime('%d.%m.%Y %H:%M:%S')}\n"
    msg += f"{'=' * 30}\n"
    msg += f"📈 Всего: {stats['total']}\n"
    if stats['total'] > 0:
        msg += f"✅ Зашло: {stats['win']} ({stats['win']/stats['total']*100:.1f}%)\n"
    else:
        msg += f"✅ Зашло: 0\n"
    msg += f"❌ Не зашло: {stats['lose']}\n"
    msg += f"{'=' * 30}\n"
    msg += f"<b>По догонам:</b>\n"
    for i in range(4):
        msg += f"  Догон {i}: {stats['by_dogon'].get(i, 0)}\n"
    # Добавим статистику по разницам (если есть)
    if prob_log:
        diffs = [p["diff"] for p in prob_log if "diff" in p]
        if diffs:
            avg_diff = sum(diffs) / len(diffs)
            msg += f"{'=' * 30}\n"
            msg += f"📊 Средняя разница: {avg_diff:.2f}%\n"
            msg += f"📊 Минимальная: {min(diffs):.2f}%\n"
            msg += f"📊 Максимальная: {max(diffs):.2f}%\n"
    send_message(msg)

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

def send_message(text):
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
    payload = {"chat_id": CHANNEL_PROGNOZ, "text": text, "parse_mode": "HTML"}
    try:
        response = requests.post(url, json=payload, timeout=10)
        if response.status_code == 200:
            return response.json()["result"]["message_id"]
        else:
            print(f"❌ Ошибка отправки: {response.status_code} - {response.text}", flush=True)
            return None
    except Exception as e:
        print(f"❌ Ошибка отправки: {e}", flush=True)
        return None

def edit_message(message_id, text):
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/editMessageText"
    payload = {"chat_id": CHANNEL_PROGNOZ, "message_id": message_id, "text": text, "parse_mode": "HTML"}
    try:
        response = requests.post(url, json=payload, timeout=10)
        if response.status_code == 200:
            return True
        else:
            print(f"❌ Ошибка редактирования: {response.status_code} - {response.text}", flush=True)
            return False
    except Exception as e:
        print(f"❌ Ошибка редактирования: {e}", flush=True)
        return False

def send_startup_message():
    now = datetime.now(MOSCOW_TZ)
    msg = f"🚀 <b>ТЕСТ: ПОСЛЕДОВАТЕЛЬНОСТЬ (+10, ВЕРОЯТНОСТИ)</b>\n"
    msg += f"⏰ Время: {now.strftime('%d.%m.%Y %H:%M:%S')} (МСК)\n"
    msg += f"📌 Выводятся вероятности для каждой масти\n"
    msg += f"🔄 Версия: 11.0 (с вероятностями)"
    send_message(msg)
    print(f"📤 Приветствие отправлено в канал", flush=True)

# =====================================================================
# ПАРСИНГ
# =====================================================================
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

# =====================================================================
# ФУНКЦИИ API
# =====================================================================
def get_active_games():
    try:
        url = f"{BASE_URL}/service-api/main-live-feed/v3/games1x2?cfView=3&count=40&fcountry=1&gr=415&grMode=4&lng=ru&ref=7&selectedMs=1.146.2092323,2.146.2092323,10.146.2092323"
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
                if game.get("liga", {}).get("id") == 2092323:
                    game_id = game.get("id")
                    if game_id:
                        active_games.append(game)
            return active_games
        else:
            return []
    except Exception as e:
        print(f"❌ Ошибка: {e}", flush=True)
        return []

def get_game_data(game_id):
    url = f"{BASE_URL}/service-api/LiveFeed/GetGameZip?id={game_id}&isSubGames=true&GroupEvents=true&countevents=250&grMode=4&partner=7&topGroups=&country=190&marketType=1&isNewBuilder=true"
    try:
        start_time = time.time()
        response = requests.get(url, headers=HEADERS, timeout=5)
        end_time = time.time()
        latency = (end_time - start_time) * 1000
        if response.status_code == 200:
            return response.json(), latency
        else:
            return None, None
    except Exception as e:
        print(f"❌ Ошибка игры {game_id}: {e}", flush=True)
        return None, None

def get_game_number():
    now = datetime.now(MOSCOW_TZ)
    start = now.replace(hour=3, minute=0, second=0, microsecond=0)
    if now < start:
        start = start - timedelta(days=1)
    diff_minutes = (now - start).total_seconds() / 60
    game_number = int(diff_minutes) // 2 % 720 + 1
    return game_number

# =====================================================================
# ПРОГНОЗ
# =====================================================================
# НОВАЯ ФУНКЦИЯ: используем predict_suit_with_probs
def refine_by_sequence(p1, p2, p3, base_suit, latency):
    # Оставляем без изменений (твоя логика)
    if 93 <= latency < 95:
        if p1 and p1.get("rank") == "7" and p1.get("suit") == "♣️":
            return "♥️"
        elif p1 and p1.get("rank") == "8" and p1.get("suit") == "♠️":
            return "♣️"
        elif p1 and p1.get("rank") == "9" and p1.get("suit") == "♥️":
            return "♦️"
        elif p1 and p1.get("rank") in ["J", "Q", "K"] and p1.get("suit") == "♣️":
            return "♥️"
        elif p1 and p1.get("rank") in ["J", "Q", "K"] and p1.get("suit") == "♠️":
            return "♣️"
    
    if 95 <= latency < 97:
        if p1 and p1.get("rank") == "7" and p1.get("suit") == "♠️":
            return "♣️"
        elif p1 and p1.get("rank") == "8" and p1.get("suit") == "♣️":
            return "♥️"
        elif p1 and p1.get("rank") == "9" and p1.get("suit") == "♦️":
            return "♠️"
    
    if 97 <= latency < 99:
        if p1 and p1.get("rank") == "9" and p1.get("suit") == "♦️":
            return "♠️"
        elif p1 and p1.get("rank") == "8" and p1.get("suit") == "♠️":
            return "♦️"
        elif p1 and p1.get("rank") == "7" and p1.get("suit") == "♥️":
            return "♣️"
    
    if p1 and p2 and p1.get("suit") == p2.get("suit"):
        if p1.get("suit") == "♣️":
            return "♥️"
        elif p1.get("suit") == "♠️":
            return "♦️"
        elif p1.get("suit") == "♦️":
            return "♣️"
        elif p1.get("suit") == "♥️":
            return "♠️"
    
    return base_suit

# =====================================================================
# ОСНОВНЫЕ ФУНКЦИИ
# =====================================================================
def save_history(history):
    with open(HISTORY_FILE, "w", encoding="utf-8") as f:
        json.dump(history, f, indent=2, ensure_ascii=False)

def load_history():
    if os.path.exists(HISTORY_FILE):
        try:
            with open(HISTORY_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except:
            return []
    return []

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

def load_recent_messages():
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/getUpdates"
    params = {"chat_id": CHANNEL_STATS, "limit": 100}
    try:
        response = requests.get(url, params=params, timeout=10)
        if response.status_code == 200:
            data = response.json()
            messages = []
            for update in data.get("result", []):
                post = update.get("channel_post")
                if post and post.get("text"):
                    messages.append(post.get("text"))
            return messages
    except Exception as e:
        print(f"❌ Ошибка загрузки истории: {e}", flush=True)
    return []

def clean_memory(history):
    if len(history) > MAX_HISTORY:
        history = history[-MAX_HISTORY:]
        print(f"🧹 Очистка кэша: оставлено {len(history)} записей", flush=True)
    return history

# =====================================================================
# ПРОВЕРКА РЕЗУЛЬТАТА
# =====================================================================
def check_results(history, all_messages):
    global stats
    current_time = time.time()
    
    for entry in history:
        if entry.get("status") != "pending":
            continue
        
        target = entry.get("target")
        predicted_suit = entry.get("suit")
        from_game = entry.get("from_game")
        message_id = entry.get("message_id")
        created_time = entry.get("time", "")
        
        if not predicted_suit or not message_id:
            continue
        
        max_games_to_check = 4
        
        for i in range(max_games_to_check):
            game_to_check = target + i
            
            game_msg = None
            for msg in all_messages:
                if f"#N{game_to_check}" in msg and ('✅' in msg or '🔰' in msg):
                    game_msg = msg
                    break
            
            if not game_msg:
                print(f"⏳ Ждем игру #N{game_to_check} для проверки масти {predicted_suit}", flush=True)
                continue
            
            game_data = parse_game_from_text(game_msg)
            if not game_data:
                continue
            
            suit_found = False
            player_cards = game_data.get("player_cards", [])
            
            for card in player_cards:
                if card.get("suit") == predicted_suit:
                    suit_found = True
                    break
            
            if suit_found:
                print(f"🎯 МАСТЬ {predicted_suit} НАЙДЕНА в игре #N{game_to_check}!", flush=True)
                dogon_number = i
                update_stats(dogon_number, "win")
                
                original_text = entry.get("original_text", "")
                if dogon_number == 0:
                    result_text = f"\n\n✅ <b>ЗАШЛО</b> в целевой игре: #N{game_to_check}"
                else:
                    result_text = f"\n\n✅ <b>ЗАШЛО</b> на догоне {dogon_number}: #N{game_to_check}"
                
                edit_message(message_id, original_text + result_text)
                entry["status"] = "win"
                entry["result_game"] = game_to_check
                entry["dogon"] = dogon_number
                save_history(history)
                return
            
            if i == max_games_to_check - 1:
                print(f"❌ Масть {predicted_suit} НЕ НАЙДЕНА за {max_games_to_check} игр", flush=True)
                update_stats(0, "lose")
                
                original_text = entry.get("original_text", "")
                result_text = f"\n\n❌ <b>НЕ ЗАШЛО</b> (проверено {max_games_to_check} игр)"
                
                edit_message(message_id, original_text + result_text)
                entry["status"] = "lose"
                save_history(history)
                return

# =====================================================================
# ОСНОВНОЙ ЦИКЛ
# =====================================================================
def main():
    global LAST_PREDICT_TIME, stats, prob_log
    
    print("🔄 ЗАПУСК ТЕСТА (ПОСЛЕДОВАТЕЛЬНОСТЬ +10, ВЕРОЯТНОСТИ)...", flush=True)
    print("=" * 60, flush=True)
    
    # Загружаем лог разниц
    prob_log = load_prob_log()
    
    send_startup_message()
    
    offset = get_offset()
    history = load_history()
    
    print("📥 Загрузка последних сообщений из канала...", flush=True)
    all_messages = load_recent_messages()
    print(f"📥 Загружено сообщений: {len(all_messages)}", flush=True)
    
    check_results(history, all_messages)
    
    last_cleanup_time = time.time()
    last_forced_check = time.time()
    last_stats_time = time.time()
    
    print("🚀 БОТ ГОТОВ К РАБОТЕ!", flush=True)
    print("=" * 60, flush=True)
    print("", flush=True)
    
    while True:
        try:
            current_time = time.time()
            
            if current_time - last_stats_time > 3600:
                send_stats_report()
                last_stats_time = current_time
            
            if current_time - last_cleanup_time > 3600:
                history = clean_memory(history)
                save_history(history)
                last_cleanup_time = current_time
            
            if current_time - last_forced_check > 30:
                print("🔄 Принудительная проверка...", flush=True)
                check_results(history, all_messages)
                last_forced_check = current_time
            
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
                
                game_id_match = re.search(r'#N(\d+)', text)
                if not game_id_match:
                    continue
                game_number = int(game_id_match.group(1))
                
                all_messages.append(text)
                if len(all_messages) > 500:
                    all_messages = all_messages[-500:]
                
                print(f"📥 Получена игра #N{game_number}", flush=True)
                print(f"📝 Текст: {text}", flush=True)
                
                if '✅' in text or '🔰' in text:
                    print(f"✅ #N{game_number} завершена - проверяем", flush=True)
                    check_results(history, all_messages)
                    continue
                
                print(f"⏭️ #N{game_number} не завершена", flush=True)
                
                if game_number in PROCESSED_GAMES:
                    print(f"⏭️ #N{game_number} уже обработана", flush=True)
                    continue
                
                games = get_active_games()
                if not games:
                    continue

                current_game_num = get_game_number()
                target_game = current_game_num + OFFSET

                already_queued = any(
                    h.get("target") == target_game
                    and h.get("status") in ("scheduled", "pending")
                    for h in history
                )

                if already_queued:
                    print(
                        f"⏳ #N{target_game} уже стоит в очереди",
                        flush=True
                    )
                    PROCESSED_GAMES.add(game_number)
                    continue

                history.append({
                    "from_game": current_game_num,
                    "target": target_game,
                    "offset": OFFSET,
                    "created_time": datetime.now(MOSCOW_TZ).isoformat(),
                    "status": "scheduled"
                })
                save_history(history)

                PROCESSED_GAMES.add(game_number)

                print(
                    f"📅 Запланирован прогноз: #{current_game_num} "
                    f"→ #{target_game} (+{OFFSET}), "
                    f"отправка примерно за 2 минуты",
                    flush=True
                )

                pending_count = len([
                    h for h in history
                    if h.get("status") in ("scheduled", "pending")
                ])
                print(f"📊 В очереди: {pending_count}", flush=True)
            
            # =========================================================
            # ПЛАНИРОВЩИК
            # =========================================================
            current_num = get_game_number()

            for entry in history:
                if entry.get("status") != "scheduled":
                    continue

                target = entry.get("target")
                if not isinstance(target, int):
                    continue

                games_left = target - current_num

                if games_left != 1:
                    continue

                print(
                    f"🔥 Время прогноза: текущая #{current_num}, "
                    f"цель #{target} (+{OFFSET})",
                    flush=True
                )

                games = get_active_games()
                if not games:
                    continue

                latency = None
                for game in games:
                    game_id = str(game.get("id"))
                    data, measured_latency = get_game_data(game_id)
                    if data:
                        latency = measured_latency
                        break

                if latency is None:
                    print(
                        "⏳ Не удалось получить свежую задержку — "
                        "прогноз остаётся в очереди",
                        flush=True
                    )
                    continue

                current_game_data = None
                for msg_text in all_messages:
                    if f"#N{current_num}" in msg_text:
                        current_game_data = parse_game_from_text(msg_text)
                        break

                # НОВЫЙ ПРОГНОЗ С ВЕРОЯТНОСТЯМИ
                top_suit, top_prob, second_suit, second_prob, diff = predict_suit_with_probs(latency)
                if top_suit is None:
                    print(
                        f"⏭️ Задержка {latency:.2f} мс — "
                        "нет данных для прогноза",
                        flush=True
                    )
                    continue

                # Логируем разницу
                prob_log.append({
                    "timestamp": datetime.now(MOSCOW_TZ).isoformat(),
                    "latency": latency,
                    "top_suit": top_suit,
                    "top_prob": top_prob,
                    "second_suit": second_suit,
                    "second_prob": second_prob,
                    "diff": diff
                })
                save_prob_log()

                base_suit = top_suit
                predicted_suit = base_suit

                if current_game_data:
                    p1 = (
                        current_game_data.get("player_cards", [])[0]
                        if current_game_data.get("player_cards")
                        else None
                    )
                    p2 = (
                        current_game_data.get("dealer_cards", [])[0]
                        if current_game_data.get("dealer_cards")
                        else None
                    )
                    p3 = (
                        current_game_data.get("player_cards", [])[1]
                        if len(current_game_data.get("player_cards", [])) > 1
                        else None
                    )

                    refined = refine_by_sequence(
                        p1, p2, p3, base_suit, latency
                    )

                    if refined != base_suit:
                        print(
                            f"🔍 Уточнение: {base_suit} → {refined}",
                            flush=True
                        )
                        predicted_suit = refined

                msg = "🔮 <b>ТЕСТ: ПОСЛЕДОВАТЕЛЬНОСТЬ (+10)</b>\n"
                msg += f"🃏 Масть: {predicted_suit} ({top_prob:.1f}%)\n"
                if second_suit:
                    msg += f"🎲 Альтернатива: {second_suit} ({second_prob:.1f}%)\n"
                    msg += f"📊 Разница: {diff:.1f}%\n"

                if current_game_data:
                    p1 = (
                        current_game_data.get("player_cards", [])[0]
                        if current_game_data.get("player_cards")
                        else None
                    )
                    p2 = (
                        current_game_data.get("dealer_cards", [])[0]
                        if current_game_data.get("dealer_cards")
                        else None
                    )
                    p3 = (
                        current_game_data.get("player_cards", [])[1]
                        if len(current_game_data.get("player_cards", [])) > 1
                        else None
                    )

                    seq_str = ""
                    if p1:
                        seq_str += f"P1:{p1['rank']}{p1['suit']} "
                    if p2:
                        seq_str += f"D2:{p2['rank']}{p2['suit']} "
                    if p3:
                        seq_str += f"P3:{p3['rank']}{p3['suit']}"

                    if seq_str:
                        msg += f"📌 {seq_str}\n"

                msg += f"🎯 Целевая игра: #N{target}\n"
                msg += "📈 3 игры догон\n"
                msg += "⏰ " + datetime.now(MOSCOW_TZ).strftime("%H:%M:%S")

                message_id = send_message(msg)

                if message_id:
                    entry["status"] = "pending"
                    entry["suit"] = predicted_suit
                    entry["time"] = datetime.now(MOSCOW_TZ).isoformat()
                    entry["message_id"] = message_id
                    entry["original_text"] = msg
                    save_history(history)

                    print(
                        f"✅ ПРОГНОЗ ОТПРАВЛЕН: #N{target} → "
                        f"масть {predicted_suit} ({top_prob:.1f}%), "
                        f"разница {diff:.1f}%",
                        flush=True
                    )

            check_results(history, all_messages)
            history = clean_memory(history)
            save_history(history)
            
            if len(PROCESSED_GAMES) > 500:
                PROCESSED_GAMES.clear()
            
            time.sleep(1)
            
        except Exception as e:
            print(f"❌ Ошибка: {e}", flush=True)
            import traceback
            traceback.print_exc()
            time.sleep(30)

if __name__ == "__main__":
    main()