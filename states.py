from aiogram.fsm.state import State, StatesGroup

class SettingsState(StatesGroup):
    waiting_for_interval = State()
    waiting_for_threshold = State()
    waiting_for_rsi_period = State()
    waiting_for_rsi_pump = State()
    waiting_for_rsi_dump = State()
