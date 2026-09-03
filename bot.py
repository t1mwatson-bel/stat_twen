 in obj:
            find_cards(item, context, player, dealer)

    return player, dealer


def unique_cards(cards):
    result = []
    seen = set()

    for card in cards:
        text = card_text(card)
        if not text or text in seen:
            continue
        seen.add(text)
        result.append({
            "rank": normalize_rank(card.get("rank")),
            "suit": f"{normalize_suit(card.get('suit'))}\ufe0f",
        })

    return result


def parse_game_data(game_id, raw):
    if not raw:
        return None

    player, dealer = find_cards(raw)
    player = unique_cards(player)
    dealer = unique_cards(dealer)

    if not player and not dealer:
        return None

    sequence = []
    pos = 1

    for i in range(max(len(player), len(dealer))):
        if i < len(player):
            sequence.append({
                "position": pos,
                "who": "P",
                "rank": player[i]["rank"],
                "suit": player[i]["suit"],
            })
            pos += 1

        if i < len(dealer):
            sequence.append({
                "position": pos,
                "who": "D",
                "rank": dealer[i]["rank"],
                "suit": dealer[i]["suit"],
            })
            pos += 1

    now = datetime.now(MOSCOW_TZ)

    return {
        "game_id": str(game_id),
        "timestamp_msk": now.strftime("%H:%M:%S.%f")[:-3],
        "player_cards": player,
        "dealer_cards": dealer,
        "sequence": sequence,
        "total_cards": len(player) + len(dealer),
        "first_player_card": player[0] if player else None,
        "id_last_digit": str(game_id)[-1],
        "id_last_two": str(game_id)[-2:],
    }


def add_or_update_game(game):
    global history

    game_id = str(game.get("game_id", ""))
    if not game_id:
        return False

    index = find_game_index(game_id)

    if index >= 0:
        old = history[index]
        old_count = len(old.get("player_cards", [])) + len(old.get("dealer_cards", []))
        new_count = len(game.get("player_cards", [])) + len(game.get("dealer_cards", []))

        if new_count >= old_count:
            history[index] = game
            save_json(DATA_FILE, history)
        return False

    history.append(game)
    history = history[-MAX_HISTORY_GAMES:]
    save_json(DATA_FILE, history)

    print(
        f"💾 Новая игра | ID={game_id} | "
        f"P1={card_text(game.get('first_player_card'))} | История={len(history)}",
        flush=True,
    )

    return True


# ============================================================
# PROCESS GAME
# ============================================================

def process_game(active_game):
    game_id = str(active_game.get("id", ""))
    if not game_id:
        return

    is_new = not game_exists(game_id)

    # Прогноз создается сразу при появлении новой игры в live feed.
    if is_new:
        print("\n══════════════════════════════════", flush=True)
        print(f"🆕 НОВАЯ ИГРА / ЛОББИ | ID={game_id}", flush=True)

        prediction = create_prediction(game_id, get_game_number())

        if prediction:
            message = make_prediction_message(prediction)
            prediction["original_text"] = message

            message_id = telegram_send(message)
            if message_id:
                prediction["message_id"] = message_id
                save_json(PREDICTIONS_FILE, predictions)

                print(
                    f"📤 SCANNER ПРОГНОЗ: {prediction['predicted_card']} "
                    f"на #N{prediction['target_number']}",
                    flush=True,
                )

    raw = get_game_data(game_id)
    if raw:
        parsed = parse_game_data(game_id, raw)
        if parsed:
            add_or_update_game(parsed)


# ============================================================
# MAIN
# ============================================================

def main():
    global history
    global predictions

    history = load_history()
    predictions = load_predictions()
    offset = load_offset()

    print("\n==================================================", flush=True)
    print("🚀 OLD BOT — HYBRID + PATTERN SCANNER", flush=True)
    print("==================================================", flush=True)
    print(f"📚 История: {len(history)} игр", flush=True)
    print("🤖 Методы: MS + ID1 + ID2 + FREQ + PATTERN SCANNER", flush=True)
    print(f"🎯 Мин. вероятность: {MIN_FORECAST_PROBABILITY:.0%}", flush=True)
    print(f"📏 Мин. отрыв: {MIN_LEADER_GAP:.0%}", flush=True)
    print(f"🧩 Паттерны: длина {PATTERN_LENGTHS}", flush=True)
    print(f"📈 Догон: {DOGON_GAMES} игр", flush=True)
    print("==================================================\n", flush=True)

    while True:
        started = time.time()

        try:
            games = get_active_games()

            if games:
                print(f"📡 API игр: {len(games)}", flush=True)

            for game in games:
                try:
                    process_game(game)
                except Exception as e:
                    print(f"❌ Ошибка игры: {e}", flush=True)

            offset = process_updates(offset)
            check_predictions()

            if len(predictions) > 1000:
                predictions[:] = predictions[-1000:]
                save_json(PREDICTIONS_FILE, predictions)

            elapsed = time.time() - started
            time.sleep(max(0.1, POLL_INTERVAL - elapsed))

        except KeyboardInterrupt:
            print("🛑 Бот остановлен", flush=True)
            break

        except Exception as e:
            print(f"❌ Критическая ошибка: {e}", flush=True)
            time.sleep(3)


if __name__ == "__main__":
    main()
