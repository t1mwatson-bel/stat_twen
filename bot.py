import os
import sys
import requests
import json
import re
import time
from datetime import datetime, timedelta
import pytz

# =====================================================================
# НАСТРОЙКИ
# =====================================================================
BOT_TOKEN = os.getenv('BOT_TOKEN')
if not BOT_TOKEN:
    BOT_TOKEN = os.getenv('BOT_TOKEN_PROGNOZ')

CHAT_ID = os.getenv('CHAT_ID_21')
if not CHAT_ID:
    CHAT_ID = os.getenv('CHAT_ID')

if not BOT_TOKEN or not CHAT_ID:
    print("❌ Ошибка: BOT_TOKEN или CHAT_ID не заданы!", flush=True)
    sys.exit(1)

print(f"✅ BOT_TOKEN: {BOT_TOKEN[:5]}...", flush=True)
print(f"✅ CHAT_ID: {CHAT_ID}", flush=True)

MOSCOW_TZ = pytz.timezone('Europe/Moscow')
BASE_URL = "https://1xlite-6021.pro"

API = f"https://api.telegram.org/bot{BOT_TOKEN}"
messages = {}
processed_games = set()
game_numbers = {}
player_cards_history = {}
dealer_cards_history = {}
game_state_history = {}

SUITS_NAMES = {0: "♠️", 1: "♣️", 2: "♦️", 3: "♥️"}
RANKS = {2: "2", 3: "3", 4: "4", 5: "5", 6: "6", 7: "7", 8: "8", 9: "9", 10: "10", 11: "J", 12: "Q", 13: "K", 14: "A"}

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
    "Accept": "application/json, text/plain, */*",
    "Referer": f"{BASE_URL}/ru/live/twentyone/2092323-21-classics",
    "Cookie": "platform_type=desktop; SESSION=34219176f69eace1b636911e2de9a15e; lng=ru; cookies_agree_type=3; tzo=3; is12h=0; auid=uaJbk2qIgo2M+6ofAxNqAg==; _ym_isad=2; mdd=1; _ga_7JGWL9SV66=GS2.1.s1787337341$o4$g1$t1787337359$j42$l0$h1608459194; window_width=150; referral_values=%7B%22type%22%3A%22reflinkid%22%2C%22val%22%3A%22s_50970m_355c_%22%2C%22additional%22%3A%7B%22name_tag%22%3A%22tag%22%7D%7D; fatman_uuid=45f69ff0-ecb1-67d4-3ff2-3a45baafc739; che_g=777dc1b9-efbf-4728-947a-4a2992ef6da5; sh.session.id=684214c4-f09e-42da-9c1a-ea61b9aca91b; _ym_uid=1786989905737338437; _ym_d=1786989905; _ga=GA1.1.547872848.1786989906"
}

print("✅ Настройки для 21 Classic загружены", flush=True)

# =====================================================================
# ФУНКЦИИ
# =====================================================================
def get_game_number():
    """Номер игры от 1 до 720 (каждые 2 минуты, старт в 03:00)"""
    now = datetime.now(MOSCOW_TZ)
    start = now.replace(hour=3, minute=0, second=0, microsecond=0)
    if now < start:
        start = start - timedelta(days=1)
    diff_minutes = (now - start).total_seconds() / 60
    game_number = int(diff_minutes) / 2 % 720 + 1
    return int(game_number)

def get_active_games():
    """Получает список активных игр 21 Classic"""
    try:
        url = f"{BASE_URL}/service-api/main-live-feed/v3/games1x2?cfView=3&count=40&fcountry=1&gr=415&grMode=4&lng=ru&ref=7&selectedMs=1.146.2092323,2.146.2092323,10.146.2092323"
        response = requests.get(url, headers=HEADERS, timeout=10)
        
        if response.status_code == 200:
            data = response.json()
            
            if isinstance(data, list):
                games = data
            elif isinstance(data, dict) and "Value" in data:
                games = data.get("Value", [])
            else:
                return []
            
            active_games = []
            for game in games:
                if game.get("liga", {}).get("id") == 2092323:
                    game_id = game.get("id")
                    if game_id and str(game_id) not in processed_games:
                        active_games.append(game)
            
            return active_games
        else:
            print(f"⚠️ Статус API: {response.status_code}", flush=True)
    except Exception as e:
        print(f"❌ Ошибка: {e}", flush=True)
    
    return []

def get_game_data(game_id):
    """Получает данные конкретной игры"""
    url = f"{BASE_URL}/service-api/LiveFeed/GetGameZip?id={game_id}&isSubGames=true&GroupEvents=true&countevents=250&grMode=4&partner=7&topGroups=&country=190&marketType=1&isNewBuilder=true"
    try:
        response = requests.get(url, headers=HEADERS, timeout=5)
        if response.status_code == 200:
            return response.json()
    except Exception as e:
        print(f"❌ Ошибка игры {game_id}: {e}", flush=True)
    return None

def format_cards(cards):
    """Форматирует карты с цветными эмодзи"""
    if not cards:
        return ""
    result = []
    for c in cards:
        cs = c.get("CS", 0)
        cv = c.get("CV", 0)
        suit = SUITS_NAMES.get(cs, "?")
        rank = RANKS.get(cv, str(cv))
        result.append(f"{rank}{suit}")
    return "".join(result)

def calculate_score(cards):
    """Подсчет очков (туз всегда 11)"""
    if not cards:
        return 0
    
    score = 0
    for c in cards:
        cv = c.get("CV", 0)
        if cv == 14:      # Туз = 11
            score += 11
        elif cv == 13:    # Король = 4
            score += 4
        elif cv == 12:    # Дама = 3
            score += 3
        elif cv == 11:    # Валет = 2
            score += 2
        elif 6 <= cv <= 10:  # 6,7,8,9,10
            score += cv
    return score

def is_game_finished(state, player_cards, dealer_cards, p_score, d_score):
    """Проверяет, завершена ли игра"""
    if state in ["4", "5"]:
        return True
    
    if p_score == 21 or d_score == 21:
        return True
    
    if p_score > 21 or d_score > 21:
        return True
    
    # Дилер остановился (2+ карты и >= 17) — игра завершена
    if dealer_cards and len(dealer_cards) >= 2 and d_score >= 17:
        return True
    
    return False

def get_arrow(state, player_cards, dealer_cards, p_score, d_score):
    """Определяет стрелку"""
    if state == "1":
        return "◀️"
    elif state in ("2", "3"):
        return "▶️"
    elif not dealer_cards:
        return "◀️"
    elif len(dealer_cards) == 1:
        return "◀️"
    else:
        if d_score < 17:
            return "▶️"
        else:
            return "⏹️"
    return ""

def build_message(game_num, game_id, player_cards, dealer_cards, p_score, d_score, state):
    p_hand = format_cards(player_cards)
    d_hand = format_cards(dealer_cards)
    total = p_score + d_score if dealer_cards else p_score
    
    if is_game_finished(state, player_cards, dealer_cards, p_score, d_score):
        tags = []
        if len(player_cards) == 2 and len(dealer_cards) == 2:
            tags.append("#R")
        
        player_aces = sum(1 for c in player_cards if c.get("CV") == 14)
        dealer_aces = sum(1 for c in dealer_cards if c.get("CV") == 14)
        if (len(player_cards) == 2 and player_aces == 2) or (len(dealer_cards) == 2 and dealer_aces == 2):
            tags.append("#G")
        
        if p_score == 21 or d_score == 21:
            tags.append("#O")
        if p_score == d_score:
            tags.append("#X")
        
        tag_str = " " + " ".join(tags) if tags else ""
        
        if p_score > 21:
            return f"#N{game_num}. {p_score}({p_hand}) - ✅{d_score}({d_hand}) #T{total}{tag_str} (ID: {game_id})"
        if d_score > 21:
            return f"#N{game_num}. ✅{p_score}({p_hand}) - {d_score}({d_hand}) #T{total}{tag_str} (ID: {game_id})"
        if p_score == 21:
            return f"#N{game_num}. ✅{p_score}({p_hand}) - {d_score}({d_hand}) #T{total}{tag_str} (ID: {game_id})"
        if d_score == 21:
            return f"#N{game_num}. {p_score}({p_hand}) - ✅{d_score}({d_hand}) #T{total}{tag_str} (ID: {game_id})"
        if p_score > d_score:
            return f"#N{game_num}. ✅{p_score}({p_hand}) - {d_score}({d_hand}) #T{total}{tag_str} (ID: {game_id})"
        if d_score > p_score:
            return f"#N{game_num}. {p_score}({p_hand}) - ✅{d_score}({d_hand}) #T{total}{tag_str} (ID: {game_id})"
        return f"#N{game_num}. {p_score}({p_hand}) - 🔰{d_score}({d_hand}) #T{total}{tag_str} (ID: {game_id})"
    
    arrow = get_arrow(state, player_cards, dealer_cards, p_score, d_score)
    return f"#N{game_num}. {p_score}({p_hand}) {arrow} {d_score}({d_hand}) #T{total} (ID: {game_id})"

def send_message(text):
    try:
        r = requests.post(API + "/sendMessage", json={"chat_id": CHAT_ID, "text": text})
        if r.status_code == 200:
            return r.json()["result"]["message_id"]
    except Exception as e:
        print(f"❌ Ошибка отправки: {e}", flush=True)
    return None

def edit_message(message_id, text):
    try:
        url = f"{API}/editMessageText"
        payload = {"chat_id": CHAT_ID, "message_id": message_id, "text": text}
        r = requests.post(url, json=payload)
        return r.status_code == 200
    except Exception as e:
        print(f"❌ Ошибка редактирования: {e}", flush=True)
        return False

# =====================================================================
# ОСНОВНОЙ ЦИКЛ
# =====================================================================
def main():
    global processed_games, game_numbers, player_cards_history, dealer_cards_history, messages, game_state_history
    
    print("🔄 ПАРСЕР 21 CLASSIC ЗАПУЩЕН (ЛАЙВ-РЕЖИМ)", flush=True)
    print(f"🕐 Игры каждые 2 минуты, старт в 03:00", flush=True)
    print("=" * 60, flush=True)
    
    while True:
        try:
            active_games = get_active_games()
            
            if not active_games:
                time.sleep(5)
                continue
            
            for game in active_games:
                game_id = str(game.get("id"))
                
                if game_id in processed_games:
                    continue
                
                data = get_game_data(game_id)
                if not data:
                    continue
                
                value = data.get("Value", {})
                if not isinstance(value, dict):
                    continue
                
                sc = value.get("SC", {})
                if not isinstance(sc, dict):
                    continue
                
                player_cards = []
                dealer_cards = []
                state = None
                
                for item in sc.get("S", []):
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
                
                if not player_cards:
                    continue
                
                if game_id not in game_numbers:
                    game_numbers[game_id] = get_game_number()
                game_number = game_numbers[game_id]
                
                p1_str = json.dumps(player_cards)
                p2_str = json.dumps(dealer_cards)
                
                cards_changed = (game_id not in player_cards_history or player_cards_history[game_id] != p1_str or
                                 game_id not in dealer_cards_history or dealer_cards_history[game_id] != p2_str)
                state_changed = (game_id not in game_state_history or game_state_history[game_id] != state)
                
                force_update = False
                if len(player_cards) == 2 and calculate_score(player_cards) == 21:
                    force_update = True
                if dealer_cards and len(dealer_cards) == 2 and calculate_score(dealer_cards) == 21:
                    force_update = True
                
                if not cards_changed and not state_changed and not force_update:
                    continue
                
                if force_update and not cards_changed:
                    player_cards_history[game_id] = p1_str + "_FORCED"
                
                player_cards_history[game_id] = p1_str
                dealer_cards_history[game_id] = p2_str
                game_state_history[game_id] = state
                
                p_score = calculate_score(player_cards)
                d_score = calculate_score(dealer_cards) if dealer_cards else 0
                
                msg = build_message(game_number, game_id, player_cards, dealer_cards, p_score, d_score, state)
                
                if game_id in messages:
                    edit_message(messages[game_id], msg)
                    print(f"🔄 Обновлена игра {game_id}: {msg}", flush=True)
                else:
                    msg_id = send_message(msg)
                    if msg_id:
                        messages[game_id] = msg_id
                        print(f"📤 Новая игра {game_id}: {msg}", flush=True)
                
                if is_game_finished(state, player_cards, dealer_cards, p_score, d_score):
                    processed_games.add(game_id)
                    print(f"🏁 Игра {game_id} завершена (state={state}, p_score={p_score}, d_score={d_score})", flush=True)
                
                time.sleep(0.3)
            
            if len(processed_games) > 500:
                processed_games.clear()
                game_numbers.clear()
                player_cards_history.clear()
                dealer_cards_history.clear()
                game_state_history.clear()
                messages.clear()
                print("🗑️ Кэш очищен", flush=True)
            
            time.sleep(2)
            
        except Exception as e:
            print(f"❌ Критическая ошибка: {e}", flush=True)
            import traceback
            traceback.print_exc()
            time.sleep(5)

if __name__ == "__main__":
    main()