import os
import sys
import requests
import json
import time
from datetime import datetime, timedelta
import pytz

# =====================================================================
# ПРИНУДИТЕЛЬНЫЙ ВЫВОД ЛОГОВ
# =====================================================================
sys.stdout.flush()
print("=" * 60, flush=True)
print("🃏 ПРОГНОЗИСТ ПО ЗАДЕРЖКЕ (ЛОГИКА КАК В ПРОГНОЗИСТЕ ПО МАСТИ)", flush=True)
print("=" * 60, flush=True)

# =====================================================================
# ПЕРЕМЕННЫЕ ОКРУЖЕНИЯ
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
BASE_URL = "https://1xlite-36553.pro"

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
    "Accept": "application/json, text/plain, */*",
    "Referer": f"{BASE_URL}/ru/live/twentyone/2092323-21-classics",
    "Cookie": "platform_type=desktop; SESSION=34219176f69eace1b636911e2de9a15e; lng=ru; cookies_agree_type=3; tzo=3; is12h=0; auid=uaJbk2qIgo2M+6ofAxNqAg==; _ym_isad=2; mdd=1; _ga_7JGWL9SV66=GS2.1.s1787337341$o4$g1$t1787337359$j42$l0$h1608459194; window_width=150; referral_values=%7B%22type%22%3A%22reflinkid%22%2C%22val%22%3A%22s_50970m_355c_%22%2C%22additional%22%3A%7B%22name_tag%22%3A%22tag%22%7D%7D; fatman_uuid=45f69ff0-ecb1-67d4-3ff2-3a45baafc739; che_g=777dc1b9-efbf-4728-947a-4a2992ef6da5; sh.session.id=684214c4-f09e-42da-9c1a-ea61b9aca91b; _ym_uid=1786989905737338437; _ym_d=1786989905; _ga=GA1.1.547872848.1786989906"
}

SUITS_NAMES = {0: "♠️", 1: "♣️", 2: "♦️", 3: "♥️"}

# =====================================================================
# НОМЕР ИГРЫ
# =====================================================================
def get_game_number():
    now = datetime.now(MOSCOW_TZ)
    start = now.replace(hour=3, minute=0, second=0, microsecond=0)
    if now < start:
        start = start - timedelta(days=1)
    diff_minutes = (now - start).total_seconds() / 60
    game_number = int(diff_minutes) // 2 % 720 + 1
    return game_number

# =====================================================================
# ПРИВЕТСТВИЕ
# =====================================================================
def send_startup_message():
    now = datetime.now(MOSCOW_TZ)
    msg = f"🚀 <b>БОТ ПРОГНОЗИСТ ЗАПУЩЕН</b>\n"
    msg += f"⏰ Время: {now.strftime('%d.%m.%Y %H:%M:%S')} (МСК)\n"
    msg += f"🤖 Статус: Активен\n"
    msg += f"📌 Режим: Прогноз по задержке → игрок\n"
    msg += f"🔄 Версия: 4.0 (как в прогнозисте по масти)"
    send_message(msg)
    print(f"📤 Приветствие отправлено в канал", flush=True)

# =====================================================================
# ОТПРАВКА И РЕДАКТИРОВАНИЕ
# =====================================================================
def send_message(text):
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
    payload = {"chat_id": CHAT_ID, "text": text, "parse_mode": "HTML"}
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
    payload = {"chat_id": CHAT_ID, "message_id": message_id, "text": text, "parse_mode": "HTML"}
    try:
        response = requests.post(url, json=payload, timeout=10)
        if response.status_code == 200:
            return True
        else:
            print(f"❌ Ошибка редактирования: {response.status_code}", flush=True)
            return False
    except Exception as e:
        print(f"❌ Ошибка редактирования: {e}", flush=True)
        return False

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

def get_suits_from_player_cards(player_cards):
    suits = []
    for card in player_cards:
        cs = card.get("CS", 0)
        suit = SUITS_NAMES.get(cs, "?")
        suits.append(suit)
    return suits

def predict_suit_by_latency(latency):
    if 93 <= latency < 96:
        return "♥️"
    elif 96 <= latency < 99:
        return "♠️"
    elif 99 <= latency < 102:
        return "♦️"
    elif 102 <= latency < 105:
        return "♣️"
    else:
        return None

# =====================================================================
# ОСНОВНОЙ ЦИКЛ (ЛОГИКА КАК В ПРОГНОЗИСТЕ ПО МАСТИ)
# =====================================================================
def main():
    print("🔄 БОТ ЗАПУЩЕН", flush=True)
    print("=" * 60, flush=True)

    send_startup_message()

    # Храним прогнозы: {target_game: {"suit": suit, "from_game": game_num, "message_id": msg_id, "checked": False}}
    predictions = {}
    processed_games = set()

    while True:
        try:
            games = get_active_games()
            if not games:
                time.sleep(5)
                continue

            for game in games:
                game_id = str(game.get("id"))
                if game_id in processed_games:
                    continue

                data, latency, start_time, end_time = get_game_data(game_id)
                if not data:
                    continue

                player_cards, dealer_cards, state = parse_cards_and_state(data)
                if not player_cards:
                    continue

                current_game_num = get_game_number()

                # =====================================================
                # ЕСЛИ ИГРА ЗАВЕРШЕНА (state=4/5) — ПРОВЕРЯЕМ ПРОГНОЗ
                # =====================================================
                if state in ["4", "5"]:
                    # Проверяем, есть ли прогноз на эту игру
                    if current_game_num in predictions:
                        pred = predictions[current_game_num]
                        player_suits = get_suits_from_player_cards(player_cards)

                        # Проверяем, есть ли масть у игрока
                        if pred["suit"] in player_suits:
                            # ✅ ЗАШЛО!
                            result_text = f"✅ ЗАШЛО"
                            pred["checked"] = True
                            pred["result"] = "win"
                            print(f"🎯 Прогноз #N{current_game_num} ЗАШЕЛ!", flush=True)
                            
                            final_text = f"🔮 <b>ПРОГНОЗ ПО ЗАДЕРЖКЕ</b>\n"
                            final_text += f"📊 От игры: #N{pred['from_game']}\n"
                            final_text += f"🃏 Масть игрока: {pred['suit']}\n"
                            final_text += f"🎯 Игра: #N{current_game_num}\n"
                            final_text += f"📊 Результат: {result_text}"
                            edit_message(pred["message_id"], final_text)
                            print(f"📤 Результат для #N{current_game_num}: {result_text}", flush=True)
                            
                            processed_games.add(game_id)
                        else:
                            # ❌ НЕ ЗАШЛО — проверяем следующий догон
                            # Считаем, какой это догон
                            dogon_number = current_game_num - pred["target"]
                            
                            if dogon_number >= 3:
                                # Догон 3 и не зашло → проигрыш
                                result_text = "❌ НЕ ЗАШЛО (3 догона)"
                                pred["checked"] = True
                                pred["result"] = "lose"
                                print(f"❌ Прогноз #N{current_game_num} НЕ ЗАШЕЛ (3 догона)", flush=True)
                                
                                final_text = f"🔮 <b>ПРОГНОЗ ПО ЗАДЕРЖКЕ</b>\n"
                                final_text += f"📊 От игры: #N{pred['from_game']}\n"
                                final_text += f"🃏 Масть игрока: {pred['suit']}\n"
                                final_text += f"🎯 Игра: #N{current_game_num}\n"
                                final_text += f"📈 Догон: {dogon_number}\n"
                                final_text += f"📊 Результат: {result_text}"
                                edit_message(pred["message_id"], final_text)
                                print(f"📤 Результат для #N{current_game_num}: {result_text}", flush=True)
                                
                                processed_games.add(game_id)
                            else:
                                # Обновляем сообщение с текущим догоном
                                dogon_text = f"🎯 Игра: #N{current_game_num}\n📈 Догон: {dogon_number} (ждём следующую игру)"
                                update_text = f"🔮 <b>ПРОГНОЗ ПО ЗАДЕРЖКЕ</b>\n"
                                update_text += f"📊 От игры: #N{pred['from_game']}\n"
                                update_text += f"🃏 Масть игрока: {pred['suit']}\n"
                                update_text += dogon_text
                                edit_message(pred["message_id"], update_text)
                                print(f"⏳ Прогноз #N{current_game_num} не зашёл (догон {dogon_number})", flush=True)
                    else:
                        processed_games.add(game_id)
                    
                    continue

                # =====================================================
                # ДЕЛАЕМ ПРОГНОЗ НА СЛЕДУЮЩУЮ ИГРУ
                # =====================================================
                target_game = current_game_num + 1

                # Проверяем, нет ли уже прогноза на эту целевую игру
                if target_game in predictions:
                    continue

                predicted_suit = predict_suit_by_latency(latency)
                if predicted_suit is None:
                    print(f"⏭️ {game_id}: задержка {latency:.2f} мс — нет прогноза", flush=True)
                    continue

                # Отправляем прогноз
                msg = f"🔮 <b>ПРОГНОЗ ПО ЗАДЕРЖКЕ</b>\n"
                msg += f"📊 От игры: #N{current_game_num}\n"
                msg += f"🃏 Масть игрока: {predicted_suit}\n"
                msg += f"🎯 Целевая игра: #N{target_game}\n"
                msg += f"📈 3 игры догон"

                msg_id = send_message(msg)
                print(f"📤 Прогноз для #N{target_game}: {predicted_suit}", flush=True)

                # Сохраняем прогноз
                predictions[target_game] = {
                    "suit": predicted_suit,
                    "from_game": current_game_num,
                    "target": target_game,
                    "message_id": msg_id,
                    "checked": False,
                    "result": None
                }

                time.sleep(0.3)

            # Очистка кэша
            if len(processed_games) > 200:
                processed_games.clear()
                print("🗑️ Кэш очищен", flush=True)

            time.sleep(3)

        except KeyboardInterrupt:
            print("\n🛑 Остановка", flush=True)
            break
        except Exception as e:
            print(f"❌ Ошибка: {e}", flush=True)
            time.sleep(10)

if __name__ == "__main__":
    main()