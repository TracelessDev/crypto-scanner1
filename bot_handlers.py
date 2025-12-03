import json
from aiogram import Router, F, types
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.types import ReplyKeyboardMarkup, KeyboardButton, InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.utils.keyboard import InlineKeyboardBuilder
from aiogram.exceptions import TelegramBadRequest
from database import get_user_settings, update_user_setting
from states import SettingsState

router = Router()

async def refresh_menu(cb: types.CallbackQuery, text: str, reply_markup):
    try:
        await cb.message.edit_text(text, reply_markup=reply_markup, parse_mode="HTML")
    except TelegramBadRequest:
        await cb.answer()
    except Exception as e:
        print(f"UI Error: {e}")

def get_main_menu():
    return ReplyKeyboardMarkup(keyboard=[
        [KeyboardButton(text="⚙️ Настройки"), KeyboardButton(text="📊 Источники")]
    ], resize_keyboard=True)

@router.message(Command("start"))
async def cmd_start(message: types.Message):
    await get_user_settings(message.from_user.id) 
    await message.answer(
        "<b>Impulse Screener</b>\n\n"
        "Система мониторинга волатильности.\n"
        "Настройте параметры для начала работы.",
        reply_markup=get_main_menu(),
        parse_mode="HTML"
    )

# --- SETTINGS MAIN ---
@router.message(F.text == "⚙️ Настройки")
async def settings_main_msg(message: types.Message):
    await show_settings_menu(message)

async def show_settings_menu(message_or_cb):
    if isinstance(message_or_cb, types.CallbackQuery):
        user_id = message_or_cb.from_user.id
        message = message_or_cb.message
    else:
        user_id = message_or_cb.from_user.id
        message = message_or_cb

    user = await get_user_settings(user_id)
    
    sig_map = {'BOTH': 'Long/Short', 'PUMP': 'Long Only', 'DUMP': 'Short Only'}
    current_sig = sig_map.get(user['signal_type'], 'BOTH')

    text = "<b>⚙️ Конфигурация</b>"
    
    kb = InlineKeyboardBuilder()
    kb.button(text=f"⏱ Таймфрейм: {user['interval']}м", callback_data="menu_interval")
    kb.button(text=f"⚡️ Порог: {user['threshold']}%", callback_data="menu_threshold")
    
    # Кнопка ведет в подменю RSI
    rsi_status = "Вкл" if user['rsi_enabled'] else "Выкл"
    kb.button(text=f"📈 Настройки RSI ({rsi_status})", callback_data="menu_rsi_main")
    
    kb.button(text=f"👀 Данные", callback_data="menu_display")
    kb.button(text=f"🚦 Режим: {current_sig}", callback_data="toggle_sig_type")
    
    trend_status = "Вкл" if user['filter_24h_enabled'] else "Выкл"
    kb.button(text=f"📉 Тренд 24ч: {trend_status}", callback_data="menu_24h")
    
    kb.adjust(1)
    
    if isinstance(message_or_cb, types.CallbackQuery):
        await refresh_menu(message_or_cb, text, kb.as_markup())
    else:
        await message.answer(text, reply_markup=kb.as_markup(), parse_mode="HTML")

@router.callback_query(F.data == "settings_main")
async def back_to_main(cb: types.CallbackQuery):
    await show_settings_menu(cb)

# --- RSI SUB-MENU ---
@router.callback_query(F.data == "menu_rsi_main")
async def menu_rsi_main(cb: types.CallbackQuery):
    user = await get_user_settings(cb.from_user.id)
    
    text = (
        "<b>📈 Конфигурация RSI</b>\n\n"
        "Настройте индикатор перекупленности/перепроданности.\n"
        "Сигналы будут игнорироваться, если RSI выходит за эти рамки."
    )
    
    kb = InlineKeyboardBuilder()
    
    # Toggle
    status = "✅ АКТИВЕН" if user['rsi_enabled'] else "❌ ВЫКЛЮЧЕН"
    kb.button(text=status, callback_data="toggle_rsi_bool")
    
    if user['rsi_enabled']:
        # TF Cycle
        kb.button(text=f"Таймфрейм: {user.get('rsi_timeframe', '5m')}", callback_data="cycle_rsi_tf")
        
        # Limits
        kb.button(text=f"Макс. для Лонга: < {user['rsi_pump_limit']}", callback_data="input_rsi_pump")
        kb.button(text=f"Мин. для Шорта: > {user['rsi_dump_limit']}", callback_data="input_rsi_dump")
        
    kb.button(text="🔙 Назад", callback_data="settings_main")
    kb.adjust(1)
    
    await refresh_menu(cb, text, kb.as_markup())

@router.callback_query(F.data == "toggle_rsi_bool")
async def toggle_rsi_bool(cb: types.CallbackQuery):
    user = await get_user_settings(cb.from_user.id)
    await update_user_setting(cb.from_user.id, "rsi_enabled", not user['rsi_enabled'])
    await menu_rsi_main(cb)

@router.callback_query(F.data == "cycle_rsi_tf")
async def cycle_rsi_tf(cb: types.CallbackQuery):
    user = await get_user_settings(cb.from_user.id)
    modes = ['1m', '5m', '15m', '1h', '4h']
    curr = user.get('rsi_timeframe', '5m')
    try: idx = modes.index(curr)
    except: idx = 1
    new_val = modes[(idx + 1) % len(modes)]
    
    await update_user_setting(cb.from_user.id, "rsi_timeframe", new_val)
    await menu_rsi_main(cb)

# Inputs for RSI
@router.callback_query(F.data == "input_rsi_pump")
async def input_rsi_pump(cb: types.CallbackQuery, state: FSMContext):
    await cb.message.answer("Введите Макс. RSI для Лонга (например 70):")
    await state.set_state(SettingsState.waiting_for_rsi_pump)
    await cb.answer()

@router.message(SettingsState.waiting_for_rsi_pump)
async def finish_rsi_pump(message: types.Message, state: FSMContext):
    try:
        val = int(message.text)
        if 1 <= val <= 99:
            await update_user_setting(message.from_user.id, "rsi_pump_limit", val)
            await message.answer(f"✅ Фильтр обновлен: RSI < {val}")
        else: await message.answer("❌ От 1 до 99")
    except: await message.answer("❌ Число")
    await state.clear()
    await show_settings_menu(message)

@router.callback_query(F.data == "input_rsi_dump")
async def input_rsi_dump(cb: types.CallbackQuery, state: FSMContext):
    await cb.message.answer("Введите Мин. RSI для Шорта (например 30):")
    await state.set_state(SettingsState.waiting_for_rsi_dump)
    await cb.answer()

@router.message(SettingsState.waiting_for_rsi_dump)
async def finish_rsi_dump(message: types.Message, state: FSMContext):
    try:
        val = int(message.text)
        if 1 <= val <= 99:
            await update_user_setting(message.from_user.id, "rsi_dump_limit", val)
            await message.answer(f"✅ Фильтр обновлен: RSI > {val}")
        else: await message.answer("❌ От 1 до 99")
    except: await message.answer("❌ Число")
    await state.clear()
    await show_settings_menu(message)

# --- EXCHANGES ---
@router.message(F.text == "📊 Источники")
async def menu_exchanges(message: types.Message):
    await show_exchange_menu(message)

async def show_exchange_menu(message_or_cb):
    if isinstance(message_or_cb, types.CallbackQuery):
        user_id = message_or_cb.from_user.id
        message = message_or_cb.message
    else:
        user_id = message_or_cb.from_user.id
        message = message_or_cb

    user = await get_user_settings(user_id)
    try: active_list = json.loads(user['exchanges'])
    except: active_list = []
    
    kb = InlineKeyboardBuilder()
    for ex in ["binance", "bybit", "mexc"]:
        is_active = ex in active_list
        status = "☑️" if is_active else "⬜️"
        kb.button(text=f"{status} {ex.capitalize()}", callback_data=f"toggle_ex_{ex}")
    
    kb.adjust(1)
    
    text = "<b>🏦 Источники данных</b>"
    
    if isinstance(message_or_cb, types.CallbackQuery):
        await refresh_menu(message_or_cb, text, kb.as_markup())
    else:
        await message.answer(text, reply_markup=kb.as_markup(), parse_mode="HTML")

@router.callback_query(F.data.startswith("toggle_ex_"))
async def toggle_exchange(cb: types.CallbackQuery):
    ex = cb.data.split("_")[2]
    user = await get_user_settings(cb.from_user.id)
    
    try: current_list = json.loads(user['exchanges'])
    except: current_list = []
        
    if ex in current_list:
        if len(current_list) > 1: current_list.remove(ex)
        else:
            await cb.answer("Оставьте хотя бы одну биржу")
            return
    else:
        current_list.append(ex)
    
    await update_user_setting(cb.from_user.id, "exchanges", json.dumps(current_list))
    await show_exchange_menu(cb)

# --- OTHER MENUS (Interval, Threshold, etc - Same logic) ---
# ... (Остальные хендлеры для интервала, порога и дисплея остаются как в прошлом коде, 
# только проверь, чтобы они были подключены. Я сократил для читаемости, 
# если нужно - продублирую, но они не менялись по логике, только текст заголовка)
# Важно добавить хендлеры для menu_interval, menu_threshold, menu_display
# Ниже полные версии для копипаста:

@router.callback_query(F.data == "menu_interval")
async def menu_interval(cb: types.CallbackQuery):
    user = await get_user_settings(cb.from_user.id)
    kb = InlineKeyboardBuilder()
    for p in [1, 3, 5, 10, 15, 30, 60]:
        mark = "✅" if user['interval'] == p else ""
        kb.button(text=f"{p}м {mark}", callback_data=f"set_int_{p}")
    kb.button(text="✍️ Вручную", callback_data="input_interval")
    kb.button(text="🔙 Назад", callback_data="settings_main")
    kb.adjust(3, 4, 1, 1)
    await refresh_menu(cb, f"<b>⏱ Интервал: {user['interval']} мин</b>", kb.as_markup())

@router.callback_query(F.data.startswith("set_int_"))
async def set_interval_preset(cb: types.CallbackQuery):
    val = int(cb.data.split("_")[2])
    await update_user_setting(cb.from_user.id, "interval", val)
    await menu_interval(cb)

@router.callback_query(F.data == "input_interval")
async def input_int(cb: types.CallbackQuery, state: FSMContext):
    await cb.message.answer("Минуты (1-120):")
    await state.set_state(SettingsState.waiting_for_interval)
    await cb.answer()

@router.message(SettingsState.waiting_for_interval)
async def finish_int(message: types.Message, state: FSMContext):
    try:
        val = int(message.text)
        if 1 <= val <= 120:
            await update_user_setting(message.from_user.id, "interval", val)
            await message.answer(f"✅ Интервал: {val}м")
        else: await message.answer("❌ 1-120")
    except: pass
    await state.clear()
    await show_settings_menu(message)

@router.callback_query(F.data == "menu_threshold")
async def menu_threshold(cb: types.CallbackQuery):
    user = await get_user_settings(cb.from_user.id)
    kb = InlineKeyboardBuilder()
    for p in [1.0, 2.0, 3.0, 5.0, 7.0, 10.0]:
        mark = "✅" if user['threshold'] == p else ""
        kb.button(text=f"{p}% {mark}", callback_data=f"set_thr_{p}")
    kb.button(text="✍️ Вручную", callback_data="input_threshold")
    kb.button(text="🔙 Назад", callback_data="settings_main")
    kb.adjust(2, 2, 2, 1, 1)
    await refresh_menu(cb, f"<b>⚡️ Порог: {user['threshold']}%</b>", kb.as_markup())

@router.callback_query(F.data.startswith("set_thr_"))
async def set_threshold_preset(cb: types.CallbackQuery):
    val = float(cb.data.split("_")[2])
    await update_user_setting(cb.from_user.id, "threshold", val)
    await menu_threshold(cb)

@router.callback_query(F.data == "input_threshold")
async def input_thr(cb: types.CallbackQuery, state: FSMContext):
    await cb.message.answer("Процент (напр. 2.5):")
    await state.set_state(SettingsState.waiting_for_threshold)
    await cb.answer()

@router.message(SettingsState.waiting_for_threshold)
async def finish_thr(message: types.Message, state: FSMContext):
    try:
        val = float(message.text.replace(',', '.'))
        if 0.1 <= val <= 100:
            await update_user_setting(message.from_user.id, "threshold", val)
            await message.answer(f"✅ Порог: {val}%")
        else: await message.answer("❌ Некорректно")
    except: pass
    await state.clear()
    await show_settings_menu(message)

@router.callback_query(F.data == "menu_display")
async def menu_display(cb: types.CallbackQuery):
    user = await get_user_settings(cb.from_user.id)
    kb = InlineKeyboardBuilder()
    toggles = [
        ("show_imbalance", "Imbalance"),
        ("show_funding", "Funding"),
        ("show_vol24", "Volume 24h"),
        ("show_listing", "Listing Date"),
        ("show_hashtag", "Hashtag #")
    ]
    for col, label in toggles:
        status = "☑️" if user[col] else "⬜️"
        kb.button(text=f"{status} {label}", callback_data=f"toggle_disp_{col}")
    kb.button(text="🔙 Назад", callback_data="settings_main")
    kb.adjust(1)
    await refresh_menu(cb, "<b>👀 Данные</b>", kb.as_markup())

@router.callback_query(F.data.startswith("toggle_disp_"))
async def toggle_display(cb: types.CallbackQuery):
    col = cb.data.split("toggle_disp_")[1]
    user = await get_user_settings(cb.from_user.id)
    await update_user_setting(cb.from_user.id, col, not user[col])
    await menu_display(cb)

@router.callback_query(F.data == "toggle_sig_type")
async def toggle_sig_type(cb: types.CallbackQuery):
    user = await get_user_settings(cb.from_user.id)
    modes = ['BOTH', 'PUMP', 'DUMP']
    idx = modes.index(user['signal_type'])
    await update_user_setting(cb.from_user.id, 'signal_type', modes[(idx + 1) % len(modes)])
    await show_settings_menu(cb)

@router.callback_query(F.data == "menu_24h")
async def toggle_24h(cb: types.CallbackQuery):
    user = await get_user_settings(cb.from_user.id)
    await update_user_setting(cb.from_user.id, "filter_24h_enabled", not user['filter_24h_enabled'])
    await show_settings_menu(cb)