import requests
import time
from datetime import datetime

# ===== НАСТРОЙКИ =====
API_KEY = "49af09509d358f7c23208c4d0b30e7b69b2cdb06c8e328795ad03ff45d6c9f1f"  # твой ключ с odds-api.io
TELEGRAM_TOKEN = "8357635747:AAGAH_Rwk-vR8jGa6Q9F-AJLsMaEIj-JDBU"
CHANNEL_ID = -1003179573402  # твой канал для прогнозов

# Топ-5 футбольных лиг (европейские)
TOP_LEAGUES = [
    {"name": "EPL", "id": "soccer_epl"},
    {"name": "LaLiga", "id": "soccer_spain_la_liga"},
    {"name": "Bundesliga", "id": "soccer_germany_bundesliga"},
    {"name": "Serie A", "id": "soccer_italy_serie_a"},
    {"name": "Ligue 1", "id": "soccer_france_ligue_one"}
]

def get_matches():
    """Получает матчи на сегодня"""
    all_matches = []
    
    for league in TOP_LEAGUES:
        url = f"https://api.odds-api.io/v3/sports/{league['id']}/events"
        headers = {"X-API-Key": API_KEY}
        params = {"date": "today"}
        
        try:
            response = requests.get(url, headers=headers, params=params)
            if response.status_code == 200:
                data = response.json()
                matches = data.get('data', [])[:3]  # берем по 3 матча с лиги
                
                for match in matches:
                    all_matches.append({
                        'league': league['name'],
                        'home': match['home_team'],
                        'away': match['away_team'],
                        'start_time': match['commence_time'],
                        'id': match['id']
                    })
                print(f"✅ {league['name']}: {len(matches)} матчей")
            else:
                print(f"❌ {league['name']}: ошибка {response.status_code}")
        except Exception as e:
            print(f"❌ {league['name']}: {e}")
        
        time.sleep(0.5)  # пауза между запросами
    
    return all_matches[:10]  # топ-10 матчей дня

def get_odds(match_id):
    """Получает коэффициенты на матч"""
    url = f"https://api.odds-api.io/v3/events/{match_id}/odds"
    headers = {"X-API-Key": API_KEY}
    params = {
        "markets": "h2h,totals",  # исходы и тоталы
        "regions": "eu,uk"
    }
    
    try:
        response = requests.get(url, headers=headers, params=params)
        if response.status_code == 200:
            return response.json().get('data', [])
    except:
        pass
    return []

def calculate_prediction(odds_data):
    """Считает прогноз на основе коэффициентов"""
    best_odds = {}
    
    # Ищем лучшие коэффициенты
    for bookmaker in odds_data:
        for market in bookmaker.get('markets', []):
            if market['key'] == 'h2h':
                for outcome in market['outcomes']:
                    name = outcome['name']
                    if name not in best_odds or outcome['price'] > best_odds[name]:
                        best_odds[name] = outcome['price']
    
    # Если нет коэффициентов, возвращаем None
    if not best_odds:
        return None
    
    # Сортируем по вероятности (чем меньше кэф, тем выше вероятность)
    sorted_odds = sorted(best_odds.items(), key=lambda x: x[1])
    
    # Переводим кэфы в проценты
    probabilities = {}
    for name, odd in best_odds.items():
        prob = round(100 / odd, 1)
        probabilities[name] = prob
    
    # Нормализуем сумму до 100%
    total = sum(probabilities.values())
    if total > 0:
        for name in probabilities:
            probabilities[name] = round(probabilities[name] / total * 100)
    
    return {
        'best': sorted_odds[0][0],  # самый вероятный исход
        'odds': best_odds,
        'probs': probabilities
    }

def format_prediction(match, prediction):
    """Форматирует прогноз как в баккаре"""
    if not prediction:
        return None
    
    text = f"⚽ ПРОГНОЗ НА МАТЧ\n"
    text += "━━━━━━━━━━━━━━━━━━━━━━\n\n"
    text += f"🏆 {match['league']}\n"
    text += f"🎯 {match['home']} - {match['away']}\n\n"
    
    # Время матча
    match_time = datetime.fromisoformat(match['start_time'].replace('Z', '+00:00'))
    text += f"⏱ {match_time.strftime('%d.%m %H:%M')}\n\n"
    
    # Прогноз на исход
    text += f"🔮 ПРОГНОЗ: {prediction['best']}\n\n"
    
    # Вероятности
    text += f"📊 ВЕРОЯТНОСТИ:\n"
    for outcome, prob in prediction['probs'].items():
        text += f"  {outcome}: {prob}%\n"
    
    # Коэффициенты
    text += f"\n💰 ЛУЧШИЕ КЭФЫ:\n"
    for outcome, odd in prediction['odds'].items():
        text += f"  {outcome}: {odd}\n"
    
    text += f"\n⏱ {datetime.now().strftime('%H:%M')} МСК"
    
    return text

def send_to_telegram(text):
    """Отправляет сообщение в Telegram"""
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    data = {
        "chat_id": CHANNEL_ID,
        "text": text,
        "parse_mode": "HTML"
    }
    try:
        requests.post(url, json=data)
        print("✅ Отправлено в Telegram")
    except Exception as e:
        print(f"❌ Ошибка отправки: {e}")

def main():
    print("🔍 Собираю матчи...")
    matches = get_matches()
    
    print(f"\n📊 Найдено матчей: {len(matches)}")
    
    for i, match in enumerate(matches, 1):
        print(f"\n⚽ {i}. {match['home']} - {match['away']}")
        
        # Получаем коэффициенты
        odds_data = get_odds(match['id'])
        
        # Делаем прогноз
        prediction = calculate_prediction(odds_data)
        
        # Форматируем и отправляем
        text = format_prediction(match, prediction)
        if text:
            print(f"   ✅ Прогноз готов")
            send_to_telegram(text)
            time.sleep(2)  # пауза между отправками
        else:
            print(f"   ❌ Нет данных для прогноза")

if __name__ == "__main__":
    main()