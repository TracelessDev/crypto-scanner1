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
        [KeyboardButton(text="⚙️ Настройки сканера"), KeyboardButton(text="🏦 Источник данных")]
    ], resize_keyboard=True)

# --- START ---
@router.message(Command("start"))
async def cmd_start(message: types.Message):
    await get_user_settings(message.from_user.id) 
    await message.answer(
        "<b>🟢 ТЕРМИНАЛ АКТИВЕН</b>\n\n"
        "Я отслеживаю аномальную волатильность на фьючерсных рынках (Binance, Bybit, MEXC) в реальном времени.\n\n"
        "Для начала работы выберите биржу и настройте чувствительность сигналов.",
        reply_markup=get_main_menu(),
        parse_mode="HTML"
    )

# --- SETTINGS MAIN ---
@router.message(F.text == "⚙️ Настройки сканера")
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
    
    # Красивые названия режимов
    sig_map = {
        'BOTH': 'Все движения (Long/Short)', 
        'PUMP': 'Только Рост (Long) 🟢', 
        'DUMP': 'Только Падение (Short) 🔴'
    }
    current_sig = sig_map.get(user['signal_type'], 'BOTH')

    text = (
        "<b>⚙️ КОНФИГУРАЦИЯ СКАНЕРА</b>\n\n"
        "Текущие параметры отслеживания:"
    )
    
    kb = InlineKeyboardBuilder()
    kb.button(text=f"⏱ Таймфрейм: {user['interval']} мин", callback_data="menu_interval")
    kb.button(text=f"⚡️ Изменение цены: {user['threshold']}%", callback_data="menu_threshold")
    kb.button(text=f"📊 Фильтр RSI: {'ВКЛ' if user['rsi_enabled'] else 'ВЫКЛ'}", callback_data="menu_rsi")
    kb.button(text=f"👀 Данные в сигнале", callback_data="menu_display")
    kb.button(text=f"🚦 Режим: {current_sig}", callback_data="toggle_sig_type")
    
    trend_status = "ВКЛ (Только по тренду)" if user['filter_24h_enabled'] else "ВЫКЛ (Любые скачки)"
    kb.button(text=f"📈 Фильтр тренда (24ч): {trend_status}", callback_data="menu_24h")
    
    kb.adjust(1)
    
    if isinstance(message_or_cb, types.CallbackQuery):
        await refresh_menu(message_or_cb, text, kb.as_markup())
    else:
        await message.answer(text, reply_markup=kb.as_markup(), parse_mode="HTML")

@router.callback_query(F.data == "settings_main")
async def back_to_main(cb: types.CallbackQuery):
    await show_settings_menu(cb)

# --- 1. INTERVAL ---
@router.callback_query(F.data == "menu_interval")
async def menu_interval(cb: types.CallbackQuery):
    user = await get_user_settings(cb.from_user.id)
    text = (
        f"<b>⏱ ТАЙМФРЕЙМ АНАЛИЗА</b>\n\n"
        f"Текущее значение: <b>{user['interval']} мин</b>\n"
        "За какой период времени отслеживать изменение цены?"
    )
    kb = InlineKeyboardBuilder()
    for p in [1, 3, 5, 10, 15, 30, 60]:
        mark = "✅" if user['interval'] == p else ""
        kb.button(text=f"{p}м {mark}", callback_data=f"set_int_{p}")
    
    kb.button(text="✍️ Своё значение", callback_data="input_interval")
    kb.button(text="🔙 Назад", callback_data="settings_main")
    kb.adjust(3, 4, 1, 1)
    
    await refresh_menu(cb, text, kb.as_markup())

@router.callback_query(F.data.startswith("set_int_"))
async def set_interval_preset(cb: types.CallbackQuery):
    val = int(cb.data.split("_")[2])
    await update_user_setting(cb.from_user.id, "interval", val)
    await menu_interval(cb)

@router.callback_query(F.data == "input_interval")
async def input_interval_start(cb: types.CallbackQuery, state: FSMContext):
    await cb.message.answer("Введите период анализа в минутах (от 1 до 120):")
    await state.set_state(SettingsState.waiting_for_interval)
    await cb.answer()

@router.message(SettingsState.waiting_for_interval)
async def input_interval_finish(message: types.Message, state: FSMContext):
    try:
        val = int(message.text)
        if 1 <= val <= 120:
            await update_user_setting(message.from_user.id, "interval", val)
            await message.answer(f"✅ Таймфрейм установлен: {val} мин")
        else:
            await message.answer("❌ Введите значение от 1 до 120.")
    except:
        await message.answer("❌ Требуется целое число.")
    await state.clear()
    await show_settings_menu(message)

# --- 2. THRESHOLD ---
@router.callback_query(F.data == "menu_threshold")
async def menu_threshold(cb: types.CallbackQuery):
    user = await get_user_settings(cb.from_user.id)
    text = (
        f"<b>⚡️ ЧУВСТВИТЕЛЬНОСТЬ СКАНЕРА</b>\n\n"
        f"Текущий триггер: <b>{user['threshold']}%</b>\n"
        "Минимальный процент изменения цены, необходимый для сигнала."
    )
    kb = InlineKeyboardBuilder()
    for p in [1.0, 2.0, 3.0, 5.0, 7.0, 10.0]:
        mark = "✅" if user['threshold'] == p else ""
        kb.button(text=f"{p}% {mark}", callback_data=f"set_thr_{p}")
    
    kb.button(text="✍️ Свой %", callback_data="input_threshold")
    kb.button(text="🔙 Назад", callback_data="settings_main")
    kb.adjust(2, 2, 2, 1, 1)
    
    await refresh_menu(cb, text, kb.as_markup())

@router.callback_query(F.data.startswith("set_thr_"))
async def set_threshold_preset(cb: types.CallbackQuery):
    val = float(cb.data.split("_")[2])
    await update_user_setting(cb.from_user.id, "threshold", val)
    await menu_threshold(cb)

@router.callback_query(F.data == "input_threshold")
async def input_thr_start(cb: types.CallbackQuery, state: FSMContext):
    await cb.message.answer("Введите минимальный % изменения (например 2.5):")
    await state.set_state(SettingsState.waiting_for_threshold)
    await cb.answer()

@router.message(SettingsState.waiting_for_threshold)
async def input_thr_finish(message: types.Message, state: FSMContext):
    try:
        val = float(message.text.replace(',', '.'))
        if 0.1 <= val <= 100:
            await update_user_setting(message.from_user.id, "threshold", val)
            await message.answer(f"✅ Триггер установлен: {val}%")
        else:
            await message.answer("❌ Некорректное значение.")
    except:
        await message.answer("❌ Введите число.")
    await state.clear()
    await show_settings_menu(message)

# --- 3. DISPLAY OPTIONS ---
@router.callback_query(F.data == "menu_display")
async def menu_display(cb: types.CallbackQuery):
    user = await get_user_settings(cb.from_user.id)
    kb = InlineKeyboardBuilder()
    
    toggles = [
        ("show_imbalance", "Дисбаланс стакана (Bid/Ask)"),
        ("show_funding", "Ставка финансирования"),
        ("show_vol24", "Объем торгов (24ч)"),
        ("show_listing", "Дата листинга"),
        ("show_hashtag", "Хэштег монеты (#BTC)")
    ]
    
    for col, label in toggles:
        status = "✅" if user[col] else "❌"
        kb.button(text=f"{label} {status}", callback_data=f"toggle_disp_{col}")
        
    kb.button(text="🔙 Назад", callback_data="settings_main")
    kb.adjust(1)
    
    await refresh_menu(cb, "<b>👀 ОТОБРАЖЕНИЕ ДАННЫХ</b>\nВыберите, какие метрики показывать в карточке сигнала:", kb.as_markup())

@router.callback_query(F.data.startswith("toggle_disp_"))
async def toggle_display(cb: types.CallbackQuery):
    col = cb.data.split("toggle_disp_")[1]
    user = await get_user_settings(cb.from_user.id)
    await update_user_setting(cb.from_user.id, col, not user[col])
    await menu_display(cb)

# --- 4. EXCHANGE ---
@router.message(F.text == "🏦 Источник данных")
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
    active = user.get('active_exchange', 'binance')
    
    kb = InlineKeyboardBuilder()
    for ex in ["binance", "bybit", "mexc"]:
        status = "✅" if ex == active else ""
        kb.button(text=f"{ex.upper()} Futures {status}", callback_data=f"set_ex_{ex}")
    kb.adjust(1)
    
    text = "<b>🏦 ИСТОЧНИК ДАННЫХ</b>\nВыберите биржу для отслеживания:"
    
    if isinstance(message_or_cb, types.CallbackQuery):
        await refresh_menu(message_or_cb, text, kb.as_markup())
    else:
        await message.answer(text, reply_markup=kb.as_markup(), parse_mode="HTML")

@router.callback_query(F.data.startswith("set_ex_"))
async def set_exchange(cb: types.CallbackQuery):
    ex = cb.data.split("_")[2]
    user = await get_user_settings(cb.from_user.id)
    
    if user.get('active_exchange') == ex:
        await cb.answer(f"{ex.upper()} уже активна")
        return

    await update_user_setting(cb.from_user.id, "active_exchange", ex)
    await show_exchange_menu(cb)

# --- 5. LOGIC TOGGLES ---
@router.callback_query(F.data == "toggle_sig_type")
async def toggle_sig_type(cb: types.CallbackQuery):
    user = await get_user_settings(cb.from_user.id)
    modes = ['BOTH', 'PUMP', 'DUMP']
    curr_idx = modes.index(user['signal_type'])
    next_mode = modes[(curr_idx + 1) % len(modes)]
    
    await update_user_setting(cb.from_user.id, 'signal_type', next_mode)
    await show_settings_menu(cb)

@router.callback_query(F.data == "menu_rsi")
async def toggle_rsi(cb: types.CallbackQuery):
    user = await get_user_settings(cb.from_user.id)
    await update_user_setting(cb.from_user.id, "rsi_enabled", not user['rsi_enabled'])
    await show_settings_menu(cb)

@router.callback_query(F.data == "menu_24h")
async def toggle_24h(cb: types.CallbackQuery):
    user = await get_user_settings(cb.from_user.id)
    await update_user_setting(cb.from_user.id, "filter_24h_enabled", not user['filter_24h_enabled'])
    await show_settings_menu(cb)