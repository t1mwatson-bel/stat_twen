import os
import sys
import requests
import json
import time
from datetime import datetime
import pytz

# =====================================================================
# ПРИНУДИТЕЛЬНЫЙ ВЫВОД ЛОГОВ
# =====================================================================
sys.stdout.flush()
print("=" * 60, flush=True)
print("🧪 ТЕСТОВЫЙ БОТ: ПРОГНОЗ ПО ЗАДЕРЖКЕ (СКРЫТЫЙ)", flush=True)
print("=" * 60, flush=True)

# =====================================================================
# ПЕРЕМЕННЫЕ ОКРУЖЕНИЯ (БЕРУТСЯ С ХОСТИНГА)
# =====================================================================
BOT_TOKEN = os.getenv('BOT_TOKEN')
if not BOT_TOKEN:
    BOT_TOKEN = os.getenv('BOT_TOKEN_PROGNOZ')

CHAT_ID = os.getenv('CHAT_ID')

print("🔍 ДИАГНОСТИКА ПЕРЕМЕННЫХ:", flush=True)
print(f"BOT_TOKEN: {BOT_TOKEN[:5] if BOT_TOKEN else 'НЕ ЗАДАН'}", flush=True)
print(f"CHAT_ID: {CHAT_ID if CHAT_ID else 'НЕ ЗАДАН'}", flush=True)
print("=" * 60, flush=True)

if not BOT_TOKEN or not CHAT_ID:
    print("❌ ОШИБКА: переменные окружения не заданы!", flush=True)
    exit(1)

print("✅ Все переменные заданы!", flush=True)

# =====================================================================
# НАСТРОЙКИ
# =====================================================================
MOSCOW_TZ = pytz.timezone('Europe/Moscow')

# Адрес API (рабочее зеркало)
BASE_URL = "https://1xlite-36553.pro"

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
    "Accept": "application/json, text/plain, */*",
    "Referer": f"{BASE_URL}/ru/live/twentyone/2092323-21-classics",
    "Cookie": "platform_type=desktop; SESSION=34219176f69eace1b636911e2de9a15e; lng=ru; cookies_agree_type=3; tzo=3; is12h=0; auid=uaJbk2qIgo2M+6ofAxNqAg==; _ym_isad=2; mdd=1; _ga_7JGWL9SV66=GS2.1.s1787337341$o4$g1$t1787337359$j42$l0$h1608459194; window_width=150; referral_values=%7B%22type%22%3A%22reflinkid%22%2C%22val%22%3A%22s_50970m_355c_%22%2C%22additional%22%3A%7B%22name_tag%22%3A%22tag%22%7D%7D; fatman_uuid=45f69ff0-ecb1-67d4-3ff2-3a45baafc739; che_g=777dc1b9-efbf-4728-947a-4a2992ef6da5; sh.session.id=684214c4-f09e-42da-9c1a-ea61b9aca91b; _ym_uid=1786989905737338437; _ym_d=1786989905; _ga=GA1.1.547872848.1786989906"
}

SUITS_NAMES = {0: "♠️", 1: "♣️", 2: "♦️", 3: "♥️"}
RANKS = {1: "A", 2: "2", 3: "3", 4: "4", 5: "5", 6: "6", 7: "7", 8: "8", 9: "9", 10: "10", 11: "J", 12: "Q", 13: "K"}

# =====================================================================
# КЭШ ДЛЯ ТЕСТА
# =====================================================================
test_results = {
    "total": 0,
    "correct": 0
}

# =====================================================================
# ФУНКЦИИ ПРОГНОЗА ПО ЗАДЕРЖКЕ (СКРЫТАЯ)
# =====================================================================
def predict_suit_by_latency(latency):
    """
    Скрытая функция прогноза масти по задержке.
    Задержка НЕ ВЫВОДИТСЯ в сообщения.
    """
    # ПРИМЕРНАЯ ЗАВИСИМОСТЬ (на основе твоих данных)
    if 93 <= latency < 96:
        return "♥️"
    elif 96 <= latency < 99:
        return "♠️"
    elif 99 <= latency < 102:
        return "♦️"
    elif 102 <= latency < 105:
        return "♣️"
    else:
        return None  # Неопределённость

# =====================================================================
# ФУНКЦИИ РАБОТЫ С API
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
            return response.json(), latency, start_time, end_time
        else:
            return None, None, None, None
    except Exception as e:
        print(f"❌ Ошибка игры {game_id}: {e}", flush=True)
        return None, None, None, None

def parse_cards_and_state(data):
    sc = data.get("Value", {}).get("SC", {})
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
    
    return player_cards, dealer_cards, state

def get_suits_from_cards(cards):
    """Извлекает масти из карт"""
    suits = []
    for card in cards:
        cs = card.get("CS", 0)
        suit = SUITS_NAMES.get(cs, "?")
        suits.append(suit)
    return suits

# =====================================================================
# ОСНОВНОЙ ЦИКЛ ТЕСТА
# =====================================================================
def main():
    print("🔄 ТЕСТОВЫЙ БОТ ЗАПУЩЕН (ПРОГНОЗ ПО ЗАДЕРЖКЕ)", flush=True)
    print("📌 Задержка НЕ выводится в сообщения, только в логах", flush=True)
    print("=" * 60, flush=True)
    
    processed_games = set()
    
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
                
                data, latency, start_time, end_time = get_game_data(game_id)
                if not data:
                    continue
                
                player_cards, dealer_cards, state = parse_cards_and_state(data)
                
                if not player_cards:
                    continue
                
                # =============================================
                # 1. ПРОГНОЗ ПО ЗАДЕРЖКЕ (СКРЫТЫЙ)
                # =============================================
                predicted_suit = predict_suit_by_latency(latency)
                
                if predicted_suit is None:
                    print(f"⏭️ Игра {game_id}: задержка {latency:.2f} мс — нет прогноза", flush=True)
                    continue
                
                print(f"🧪 ТЕСТ: Игра {game_id}", flush=True)
                print(f"   📊 Задержка: {latency:.2f} мс (в сообщении НЕ будет)", flush=True)
                print(f"   🃏 Прогноз масти: {predicted_suit}", flush=True)
                
                # =============================================
                # 2. ЖДЁМ ЗАВЕРШЕНИЯ ИГРЫ
                # =============================================
                if state not in ["4", "5"]:
                    print(f"   ⏳ Игра ещё не завершена (state={state}), ждём...", flush=True)
                    continue
                
                # =============================================
                # 3. ПРОВЕРЯЕМ РЕЗУЛЬТАТ (масть у дилера)
                # =============================================
                dealer_suits = get_suits_from_cards(dealer_cards)
                
                if predicted_suit in dealer_suits:
                    result = "✅ СОВПАЛО!"
                    test_results["correct"] += 1
                else:
                    result = "❌ НЕ СОВПАЛО!"
                
                test_results["total"] += 1
                
                print(f"   🎯 Реальная масть дилера: {', '.join(dealer_suits) if dealer_suits else 'нет карт'}", flush=True)
                print(f"   📊 Результат: {result}", flush=True)
                print(f"   📈 Статистика: {test_results['correct']} из {test_results['total']} ({test_results['correct']/test_results['total']*100:.1f}%)", flush=True)
                print("=" * 60, flush=True)
                
                # Сохраняем игру в обработанные
                processed_games.add(game_id)
                
                time.sleep(0.3)
            
            # Очистка кэша
            if len(processed_games) > 200:
                processed_games.clear()
                print("🗑️ Кэш очищен", flush=True)
            
            time.sleep(5)
            
        except KeyboardInterrupt:
            print("\n🛑 Тест остановлен", flush=True)
            print(f"📊 Итог: {test_results['correct']} из {test_results['total']} ({test_results['correct']/test_results['total']*100:.1f}%)", flush=True)
            break
        except Exception as e:
            print(f"❌ Ошибка: {e}", flush=True)
            time.sleep(10)

if __name__ == "__main__":
    main()