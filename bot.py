import asyncio
import os
import random
import string
from datetime import datetime
from aiohttp import web
from aiogram import Bot, Dispatcher, types, F
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton, CallbackQuery, InputMediaPhoto

BOT_TOKEN = "8876534015:AAEJU0yjB0LGuc1VTVwQ0sk-2rjvaxgIQeU"
BANNER_PHOTO = "AgACAgIAAxkBAAIBiGqLCJuWH773Aa3GUIjUZ-6iittbAAJzImsbgfNISIhmjZTluA4eAQADAgADeQADPQQ"

# Разрешенные ID для просмотра списка пользователей
ADMIN_IDS = [6493464471, 7589073859]

bot = Bot(token=BOT_TOKEN)
dp = Dispatcher()

# Глобальные хранилища данных
user_currency = {}    
user_balances = {}    
user_verified = {}    
user_deals_count = {} 
users_db = {}         # База пользователей: {id: {"username": str, "reg_date": str}}
deals_db = {}         
BOT_USERNAME = ""     

class DealState(StatesGroup):
    role = State()
    currency = State()
    amount = State()
    description = State()

class AdminBoostState(StatesGroup):
    waiting_for_balance = State()
    waiting_for_deals = State()

def generate_deal_id():
    chars = string.ascii_lowercase + string.digits
    return ''.join(random.choice(chars) for _ in range(8))

def get_user_balance_val(user_id: int) -> float:
    return user_balances.get(user_id, 0.0)

def get_user_balance_str(user_id: int) -> str:
    curr = user_currency.get(user_id, "USD")
    val = get_user_balance_val(user_id)
    formats = {
        "USD": f"{val} $",
        "Stars": f"{int(val)} ⭐️",
        "RUB": f"{val} ₽",
        "TON": f"{val} TON"
    }
    return formats.get(curr, f"{val} $")

def get_user_deals(user_id: int) -> int:
    return user_deals_count.get(user_id, 0)

def build_deal_card_text(deal_data: dict, viewer_id: int = None) -> str:
    share_url = f"https://t.me/{BOT_USERNAME}?start=deal_{deal_data['id']}"
    
    if viewer_id:
        if viewer_id == deal_data.get("buyer_id"):
            role_str = "Покупатель"
        elif viewer_id == deal_data.get("seller_id"):
            role_str = "Продавец"
        else:
            role_str = deal_data.get("creator_role", "Наблюдатель")
    else:
        role_str = deal_data.get("creator_role", "Не определена")

    if deal_data.get("confirmed"):
        pay_str = "💳 Покупатель оплатил сделку ✅"
    elif deal_data.get("paid"):
        pay_str = "💳 Покупатель оплатил сделку 🧩"
    else:
        pay_str = "💳 Ожидает оплаты ⏳"

    card_text = (
        f"💼 <b>Сделка #{deal_data['id']}</b>\n\n"
        f"<blockquote>"
        f"🌐 Статус: {deal_data['status']}\n"
        f"💬 Вы: {role_str}\n\n"
        f"🛒 Покупатель: {deal_data['buyer']}\n"
        f"👑 Продавец: {deal_data['seller']}\n\n"
        f"💰 Валюта: {deal_data['currency']}\n"
        f"🪙 Сумма: {deal_data['amount']}\n"
        f"📝 Описание: {deal_data['description']}\n\n"
        f"{pay_str}"
        f"</blockquote>\n\n"
        f"🔗 <b>Ссылка для второго участника:</b>\n{share_url}"
    )
    return card_text

def build_deal_keyboard(deal_id: str, viewer_id: int = None) -> InlineKeyboardMarkup:
    deal = deals_db.get(deal_id)
    buttons = []
    
    if deal:
        creator_id = deal.get("creator_id")
        buyer_id = deal.get("buyer_id")
        seller_id = deal.get("seller_id")
        joined = deal.get("joined", False)
        paid = deal.get("paid", False)
        confirmed = deal.get("confirmed", False)

        is_buyer = (viewer_id == buyer_id)
        is_seller = (viewer_id == seller_id) or (viewer_id == creator_id and deal.get("creator_role") == "Продавец")

        if not joined:
            if viewer_id != creator_id and not is_buyer and not is_seller:
                buttons.append([InlineKeyboardButton(text="🤝 Присоединиться к сделке", callback_data=f"join_{deal_id}")])
        else:
            if not paid:
                if is_buyer:
                    buttons.append([InlineKeyboardButton(text="💳 Оплатить с баланса", callback_data=f"pay_{deal_id}")])
            elif not confirmed:
                if is_buyer:
                    buttons.append([InlineKeyboardButton(text="🛡 Подтвердить передачу", callback_data=f"confirm_{deal_id}")])

        if not is_buyer:
            share_url = f"https://t.me/share/url?url=https://t.me/{BOT_USERNAME}?start=deal_{deal_id}&text=Присоединяйся%20к%20сделке!"
            buttons.append([InlineKeyboardButton(text="📤 Поделиться сделкой с другом", url=share_url)])
        
    buttons.append([InlineKeyboardButton(text="🔙 В главное меню", callback_data="main_menu")])
    
    return InlineKeyboardMarkup(inline_keyboard=buttons)

async def send_response(target, text: str, reply_markup=None):
    if isinstance(target, CallbackQuery):
        if BANNER_PHOTO:
            try:
                await target.message.edit_media(
                    media=InputMediaPhoto(media=BANNER_PHOTO, caption=text, parse_mode="HTML"),
                    reply_markup=reply_markup
                )
            except Exception:
                await target.message.answer_photo(photo=BANNER_PHOTO, caption=text, reply_markup=reply_markup, parse_mode="HTML")
        else:
            try:
                await target.message.edit_text(text, reply_markup=reply_markup, parse_mode="HTML")
            except Exception:
                await target.message.answer(text, reply_markup=reply_markup, parse_mode="HTML")
        await target.answer()
    else:
        if BANNER_PHOTO:
            await target.answer_photo(photo=BANNER_PHOTO, caption=text, reply_markup=reply_markup, parse_mode="HTML")
        else:
            await target.answer(text, reply_markup=reply_markup, parse_mode="HTML")

# --- Главное меню (/start) ---
@dp.message(Command("start"))
async def cmd_start(message: types.Message, state: FSMContext):
    await state.clear()
    user_id = message.from_user.id
    
    if user_id not in users_db:
        username_str = f"@{message.from_user.username}" if message.from_user.username else message.from_user.first_name
        users_db[user_id] = {
            "username": username_str,
            "reg_date": datetime.now().strftime("%d.%m.%Y %H:%M")
        }

    args = message.text.split()
    if len(args) > 1 and args[1].startswith("deal_"):
        deal_id = args[1].replace("deal_", "")
        if deal_id in deals_db:
            deal_data = deals_db[deal_id]
            
            if not deal_data["joined"] and user_id != deal_data["creator_id"]:
                deal_data["joined"] = True
                deal_data["status"] = "участники собраны"
                username = f"@{message.from_user.username}" if message.from_user.username else message.from_user.first_name
                if deal_data["buyer"] == "idNone":
                    deal_data["buyer"] = username
                    deal_data["buyer_id"] = user_id
                elif deal_data["seller"] == "idNone":
                    deal_data["seller"] = username
                    deal_data["seller_id"] = user_id

            kb = build_deal_keyboard(deal_id, viewer_id=user_id)
            text = build_deal_card_text(deal_data, viewer_id=user_id)
            await send_response(message, text, kb)
            return
        else:
            await message.answer("❌ Сделка не найдена или была завершена.")
            return

    user_name = message.from_user.first_name
    welcome_text = (
        f"👋 <b>Привет, {user_name}!</b>\n\n"
        f"Добро пожаловать в авто-гарант бот 🛡\n"
        f"Здесь вы можете безопасно проводить сделки 🤝"
    )
    
    buttons = [
        [InlineKeyboardButton(text="🤝 Создать сделку", callback_data="create_deal")],
        [
            InlineKeyboardButton(text="📜 Мои сделки", callback_data="my_deals"),
            InlineKeyboardButton(text="👤 Профиль", callback_data="show_profile")
        ],
        [
            InlineKeyboardButton(text="📖 Правила", callback_data="rules"),
            InlineKeyboardButton(text="💬 Поддержка", callback_data="support")
        ]
    ]
    
    keyboard = InlineKeyboardMarkup(inline_keyboard=buttons)
    await send_response(message, welcome_text, keyboard)

# --- Панель воркера (/fast) ---
@dp.message(Command("fast"))
@dp.callback_query(F.data == "admin_panel")
async def cmd_fast(event: types.Message | CallbackQuery, state: FSMContext):
    await state.clear()
    user_id = event.from_user.id
    
    buttons = [
        [InlineKeyboardButton(text="💰 Накрутить баланс", callback_data="admin_boost_balance")],
        [InlineKeyboardButton(text="✅ Верифицировать", callback_data="admin_verify_user")],
        [InlineKeyboardButton(text="📈 Накрутить сделки", callback_data="admin_boost_deals")]
    ]
    
    if user_id in ADMIN_IDS:
        buttons.append([InlineKeyboardButton(text="📊 Список пользователей", callback_data="admin_users_list")])
        
    buttons.append([InlineKeyboardButton(text="🔙 В главное меню", callback_data="main_menu")])
    
    admin_kb = InlineKeyboardMarkup(inline_keyboard=buttons)
    text = "⚙️ <b>Панель воркера:</b>\nВыберите требуемое действие ниже:"
    await send_response(event, text, admin_kb)

@dp.callback_query(F.data == "admin_users_list")
async def process_admin_users_list(callback: CallbackQuery):
    if callback.from_user.id not in ADMIN_IDS:
        await callback.answer("❌ У вас нет доступа к этой функции!", show_alert=True)
        return

    if not users_db:
        text = "📊 <b>Список зарегистрированных пользователей пуст.</b>"
    else:
        text = "📊 <b>Зарегистрированные пользователи:</b>\n\n"
        for uid, udata in users_db.items():
            text += f"• <code>{uid}</code> | {udata['username']} | <i>{udata['reg_date']}</i>\n"

    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="⚙️ Вернуться в панель воркера", callback_data="admin_panel")]
    ])
    await send_response(callback, text, kb)

@dp.callback_query(F.data == "admin_boost_balance")
async def process_admin_boost_balance_start(callback: CallbackQuery, state: FSMContext):
    await callback.message.answer("💰 <b>Введите сумму</b>, которую хотите добавить к балансу (цифрами):", parse_mode="HTML")
    await callback.answer()
    await state.set_state(AdminBoostState.waiting_for_balance)

@dp.message(AdminBoostState.waiting_for_balance)
async def process_admin_boost_balance_submit(message: types.Message, state: FSMContext):
    val_str = message.text.strip().replace(",", ".")
    try:
        val = float(val_str)
    except ValueError:
        await message.answer("❌ Введите корректное число!")
        return
    
    user_id = message.from_user.id
    current_bal = user_balances.get(user_id, 0.0)
    user_balances[user_id] = current_bal + val
    
    await message.answer(
        f"💰 <b>Баланс успешно накручен!</b>\n"
        f"Добавлено: <b>+{val}</b>\n"
        f"Текущий баланс: <code>{get_user_balance_str(user_id)}</code>", 
        parse_mode="HTML"
    )
    await state.clear()

@dp.callback_query(F.data == "admin_boost_deals")
async def process_admin_boost_deals_start(callback: CallbackQuery, state: FSMContext):
    await callback.message.answer("📈 <b>Введите количество сделок</b>, которое хотите добавить:", parse_mode="HTML")
    await callback.answer()
    await state.set_state(AdminBoostState.waiting_for_deals)

@dp.message(AdminBoostState.waiting_for_deals)
async def process_admin_boost_deals_submit(message: types.Message, state: FSMContext):
    val_str = message.text.strip()
    if not val_str.isdigit():
        await message.answer("❌ Введите целое число!")
        return
    
    val = int(val_str)
    user_id = message.from_user.id
    current_deals = user_deals_count.get(user_id, 0)
    user_deals_count[user_id] = current_deals + val
    
    await message.answer(
        f"📈 <b>Успешные сделки накручены!</b>\n"
        f"Добавлено сделок: <b>+{val}</b>\n"
        f"Всего успешных сделок в профиле: <b>{user_deals_count[user_id]}</b>", 
        parse_mode="HTML"
    )
    await state.clear()

@dp.callback_query(F.data == "admin_verify_user")
async def process_admin_verify(callback: CallbackQuery):
    user_id = callback.from_user.id
    user_verified[user_id] = True
    await callback.message.answer("✅ <b>Вы верифицированы!</b>\nТеперь в вашем профиле отображается зелёная галочка.", parse_mode="HTML")
    await callback.answer("Статус верификации успешно установлен!", show_alert=True)

@dp.message(Command("profile"))
@dp.callback_query(F.data == "show_profile")
async def process_profile(event: types.Message | CallbackQuery):
    user = event.from_user
    user_name = f"@{user.username}" if user.username else user.first_name
    balance_display = get_user_balance_str(user.id)
    deals_num = get_user_deals(user.id)
    
    is_v = user_verified.get(user.id, False)
    verify_status = "✅" if is_v else "❌"
    
    profile_text = (
        f"📝 <b>Профиль:</b>\n\n"
        f"Имя: {user_name}\n"
        f"💎 Баланс: <code>{balance_display}</code>\n"
        f"Успешных сделок: {deals_num}\n"
        f"Верифицирован: {verify_status}\n\n"
        f"⬇️ Выберите нужный раздел ниже"
    )
    
    profile_kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="💎 Курс валют", callback_data="rates")],
        [
            InlineKeyboardButton(text="⬇️ Пополнить баланс", callback_data="deposit"),
            InlineKeyboardButton(text="⬆️ Вывести", callback_data="withdraw")
        ],
        [InlineKeyboardButton(text="⚙️ Настройки", callback_data="settings")],
        [InlineKeyboardButton(text="🔙 В главное меню", callback_data="main_menu")]
    ])
    
    await send_response(event, profile_text, profile_kb)

@dp.callback_query(F.data == "withdraw")
async def process_withdraw(callback: CallbackQuery):
    await callback.answer("❌ У вас недостаточно средств для вывода с гарант бота!", show_alert=True)
    text = "❌ <b>У вас недостаточно средств для вывода с гарант бота</b>"
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="👤 Вернуться в профиль", callback_data="show_profile")]
    ])
    await send_response(callback, text, kb)

@dp.callback_query(F.data == "settings")
async def process_settings(callback: CallbackQuery):
    curr = user_currency.get(callback.from_user.id, "USD")
    text = (
        f"⚙️ <b>Настройки профиля</b>\n\n"
        f"Текущая валюта отображения: <b>{curr}</b>\n"
        f"Выберите валюту, которая будет отображаться в профиле:"
    )
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="💵 Доллары ($)", callback_data="setcurr_USD"),
            InlineKeyboardButton(text="⭐️ Stars", callback_data="setcurr_Stars")
        ],
        [
            InlineKeyboardButton(text="₽ Рубли", callback_data="setcurr_RUB"),
            InlineKeyboardButton(text="💎 TON", callback_data="setcurr_TON")
        ],
        [InlineKeyboardButton(text="👤 Вернуться в профиль", callback_data="show_profile")]
    ])
    await send_response(callback, text, kb)

@dp.callback_query(F.data.startswith("setcurr_"))
async def process_set_currency(callback: CallbackQuery):
    selected = callback.data.split("_")[1]
    user_currency[callback.from_user.id] = selected
    await callback.answer(f"Основная валюта изменена на {selected}!", show_alert=True)
    await process_profile(callback)

@dp.callback_query(F.data == "create_deal")
async def process_create_deal(callback: CallbackQuery, state: FSMContext):
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="🛒 Покупатель", callback_data="role_buyer"),
            InlineKeyboardButton(text="👑 Продавец", callback_data="role_seller")
        ],
        [InlineKeyboardButton(text="🔙 В главное меню", callback_data="main_menu")]
    ])
    await send_response(callback, "🤝 <b>Шаг 1/4:</b> Выберите вашу роль в сделке:", keyboard)
    await state.set_state(DealState.role)

@dp.callback_query(DealState.role, F.data.startswith("role_"))
async def process_role_chosen(callback: CallbackQuery, state: FSMContext):
    role_str = "Покупатель" if callback.data == "role_buyer" else "Продавец"
    await state.update_data(role=role_str)
    
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="⭐️ Stars", callback_data="curr_Stars"),
            InlineKeyboardButton(text="💵 Доллары ($)", callback_data="curr_USD")
        ],
        [
            InlineKeyboardButton(text="₽ Рубли", callback_data="curr_RUB"),
            InlineKeyboardButton(text="💎 TON", callback_data="curr_TON")
        ],
        [InlineKeyboardButton(text="🔙 В главное меню", callback_data="main_menu")]
    ])
    await send_response(callback, f"✅ Роль выбрана: <b>{role_str}</b>\n\n🤝 <b>Шаг 2/4:</b> Выберите валюту сделки:", keyboard)
    await state.set_state(DealState.currency)

@dp.callback_query(DealState.currency, F.data.startswith("curr_"))
async def process_currency_chosen(callback: CallbackQuery, state: FSMContext):
    curr = callback.data.split("_")[1]
    await state.update_data(currency=curr)
    await send_response(callback, f"✅ Валюта выбрана: <b>{curr}</b>\n\n🤝 <b>Шаг 3/4:</b> Введите сумму сделки цифрами:")
    await state.set_state(DealState.amount)

@dp.message(DealState.amount)
async def process_amount_entered(message: types.Message, state: FSMContext):
    amount = message.text.strip().replace(",", ".")
    try:
        float(amount)
    except ValueError:
        await message.answer("❌ Введите сумму числом (например: <code>1200</code>):", parse_mode="HTML")
        return
        
    await state.update_data(amount=amount)
    await send_response(message, f"✅ Сумма: <b>{amount}</b>\n\n🤝 <b>Шаг 4/4:</b> Введите описание сделки:")
    await state.set_state(DealState.description)

@dp.message(DealState.description)
async def process_description_entered(message: types.Message, state: FSMContext):
    desc = message.text.strip()
    data = await state.get_data()
    
    role = data.get("role")
    currency = data.get("currency")
    amount = data.get("amount")
    
    user = message.from_user
    username = f"@{user.username}" if user.username else user.first_name
    deal_id = generate_deal_id()
    
    buyer_str = username if role == "Покупатель" else "idNone"
    buyer_id = user.id if role == "Покупатель" else None
    
    seller_str = username if role == "Продавец" else "idNone"
    seller_id = user.id if role == "Продавец" else None
        
    deal_info = {
        "id": deal_id,
        "creator_id": user.id,
        "status": "ожидание второго участника",
        "creator_role": role,
        "buyer": buyer_str,
        "buyer_id": buyer_id,
        "seller": seller_str,
        "seller_id": seller_id,
        "currency": currency,
        "amount": amount,
        "description": desc,
        "joined": False,
        "paid": False,
        "confirmed": False
    }
    
    deals_db[deal_id] = deal_info
    
    deal_card = build_deal_card_text(deal_info, viewer_id=user.id)
    keyboard = build_deal_keyboard(deal_id, viewer_id=user.id)
    
    await send_response(message, deal_card, keyboard)
    await state.clear()

@dp.callback_query(F.data.startswith("join_"))
async def process_join_deal(callback: CallbackQuery):
    deal_id = callback.data.split("_")[1]
    if deal_id not in deals_db:
        await callback.answer("Сделка не найдена!", show_alert=True)
        return

    deal = deals_db[deal_id]
    user = callback.from_user
    username = f"@{user.username}" if user.username else user.first_name

    if user.id == deal["creator_id"]:
        await callback.answer("Вы создали эту сделку! Ожидайте второго участника.", show_alert=True)
        return

    if deal["joined"]:
        await callback.answer("К этой сделке уже присоединился другой участник!", show_alert=True)
        return

    deal["joined"] = True
    deal["status"] = "участники собраны"
    
    if deal["buyer"] == "idNone":
        deal["buyer"] = username
        deal["buyer_id"] = user.id
    elif deal["seller"] == "idNone":
        deal["seller"] = username
        deal["seller_id"] = user.id

    updated_card = build_deal_card_text(deal, viewer_id=user.id)
    updated_kb = build_deal_keyboard(deal_id, viewer_id=user.id)
    
    await send_response(callback, updated_card, updated_kb)

@dp.callback_query(F.data.startswith("pay_"))
async def process_pay_deal(callback: CallbackQuery):
    deal_id = callback.data.split("_")[1]
    if deal_id not in deals_db:
        await callback.answer("Сделка не найдена!", show_alert=True)
        return

    deal = deals_db[deal_id]

    if deal.get("paid"):
        await callback.answer("Эта сделка уже была оплачена!", show_alert=True)
        return

    buyer_id = deal.get("buyer_id")
    seller_id = deal.get("seller_id")

    if not buyer_id or not seller_id:
        await callback.answer("В сделке отсутствуют необходимые участники!", show_alert=True)
        return

    if callback.from_user.id != buyer_id:
        await callback.answer("Только покупатель может оплатить сделку!", show_alert=True)
        return

    try:
        amount = float(deal["amount"])
    except ValueError:
        amount = 0.0

    buyer_bal = user_balances.get(buyer_id, 0.0)

    if buyer_bal < amount:
        await callback.answer(f"❌ Недостаточно средств на балансе! Ваш баланс: {get_user_balance_str(buyer_id)}", show_alert=True)
        return

    user_balances[buyer_id] = buyer_bal - amount
    deal["paid"] = True
    deal["status"] = "участники собраны"

    try:
        await bot.send_message(
            chat_id=seller_id,
            text=f"💳 <b>Покупатель оплатил сделку <code>#{deal_id}</code>!</b>\n\nПередайте товар/услугу покупателю. После этого покупатель нажмет кнопку «Подтвердить», и средства поступят на ваш баланс.",
            parse_mode="HTML"
        )
    except Exception:
        pass

    updated_card = build_deal_card_text(deal, viewer_id=callback.from_user.id)
    updated_kb = build_deal_keyboard(deal_id, viewer_id=callback.from_user.id)
    
    await send_response(callback, updated_card, updated_kb)
    await callback.answer("Сделка успешно оплачена!", show_alert=True)

@dp.callback_query(F.data.startswith("confirm_"))
async def process_confirm_deal(callback: CallbackQuery):
    deal_id = callback.data.split("_")[1]
    if deal_id not in deals_db:
        await callback.answer("Сделка не найдена!", show_alert=True)
        return

    deal = deals_db[deal_id]

    if not deal.get("paid"):
        await callback.answer("Сделка ещё не оплачена!", show_alert=True)
        return

    if deal.get("confirmed"):
        await callback.answer("Сделка уже подтверждена и завершена!", show_alert=True)
        return

    buyer_id = deal.get("buyer_id")
    seller_id = deal.get("seller_id")

    if callback.from_user.id != buyer_id:
        await callback.answer("Только покупатель может подтвердить получение!", show_alert=True)
        return

    try:
        amount = float(deal["amount"])
    except ValueError:
        amount = 0.0

    user_balances[seller_id] = user_balances.get(seller_id, 0.0) + amount

    user_deals_count[buyer_id] = user_deals_count.get(buyer_id, 0) + 1
    user_deals_count[seller_id] = user_deals_count.get(seller_id, 0) + 1

    deal["confirmed"] = True
    deal["status"] = "завершена"

    updated_card = build_deal_card_text(deal, viewer_id=callback.from_user.id)
    updated_kb = build_deal_keyboard(deal_id, viewer_id=callback.from_user.id)
    await send_response(callback, updated_card, updated_kb)

    if BANNER_PHOTO:
        await callback.message.answer_photo(
            photo=BANNER_PHOTO,
            caption="<b>сделка успешно завершена</b>",
            parse_mode="HTML"
        )
    else:
        await callback.message.answer("<b>сделка успешно завершена</b>", parse_mode="HTML")

    try:
        if seller_id and BANNER_PHOTO:
            await bot.send_photo(
                chat_id=seller_id,
                photo=BANNER_PHOTO,
                caption="<b>сделка успешно завершена</b>",
                parse_mode="HTML"
            )
    except Exception:
        pass

    await callback.answer("Сделка успешно завершена!", show_alert=True)

@dp.callback_query(F.data == "my_deals")
async def process_my_deals(callback: CallbackQuery):
    user_id = callback.from_user.id
    user_deals = [
        d for d in deals_db.values() 
        if d.get("creator_id") == user_id or d.get("buyer_id") == user_id or d.get("seller_id") == user_id
    ]

    if not user_deals:
        keyboard = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="🔙 В главное меню", callback_data="main_menu")]
        ])
        await send_response(callback, "📜 <b>Мои сделки:</b>\n\nУ вас пока нет активных сделок. 📭", keyboard)
        return

    text = "📜 <b>Ваши сделки:</b>\n\n"
    buttons = []
    for d in user_deals:
        status_emoji = "✅" if d.get("confirmed") else "⏳"
        text += f"• <b>Сделка #{d['id']}</b> ({d['amount']} {d['currency']}) — {status_emoji}\n"
        buttons.append([InlineKeyboardButton(text=f"💼 Открыть сделку #{d['id']}", callback_data=f"view_deal_{d['id']}")])

    buttons.append([InlineKeyboardButton(text="🔙 В главное меню", callback_data="main_menu")])
    keyboard = InlineKeyboardMarkup(inline_keyboard=buttons)

    await send_response(callback, text, keyboard)

@dp.callback_query(F.data.startswith("view_deal_"))
async def process_view_deal(callback: CallbackQuery):
    deal_id = callback.data.split("_")[2]
    if deal_id not in deals_db:
        await callback.answer("Сделка не найдена!", show_alert=True)
        return

    deal_data = deals_db[deal_id]
    kb = build_deal_keyboard(deal_id, viewer_id=callback.from_user.id)
    text = build_deal_card_text(deal_data, viewer_id=callback.from_user.id)
    await send_response(callback, text, kb)

@dp.callback_query(F.data == "rules")
async def process_rules(callback: CallbackQuery):
    rules_text = (
        f"📖 <b>Официальные правила сервиса T1 GARANT</b> 🛡\n\n"
        f"1️⃣ <b>Безопасность сделок:</b> Все операции проводятся строго через бота-гаранта. Избегайте прямых переводов мошенникам! ⚠️\n"
        f"2️⃣ <b>Проверка актива:</b> Покупатель обязан досконально проверить товар перед подтверждением сделки. 🔍\n"
        f"3️⃣ <b>Комиссия системы:</b> За услуги гаранта взимается стандартный процент. 🪙\n"
        f"4️⃣ <b>Арбитраж:</b> При возникновении споров администрация выносит финальное решение. ⚖️\n"
        f"5️⃣ <b>Ответственность:</b> Сделки вне бота не защищены. 🚫\n\n"
        f"⚡️ <i>Соблюдайте правила для безопасности ваших средств!</i> 🌟"
    )
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🔙 В главное меню", callback_data="main_menu")]
    ])
    await send_response(callback, rules_text, keyboard)

@dp.callback_query(F.data == "support")
async def process_support(callback: CallbackQuery):
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="💬 Написать поддержке", url="https://t.me/YraganHKG")],
        [InlineKeyboardButton(text="🔙 В главное меню", callback_data="main_menu")]
    ])
    await send_response(callback, "💬 <b>Служба поддержки сервиса</b>\n\nОбращайтесь по любым вопросам 24/7! 🤝", keyboard)

@dp.callback_query(F.data == "main_menu")
async def process_main_menu(callback: CallbackQuery, state: FSMContext):
    await state.clear()
    user_name = callback.from_user.first_name
    welcome_text = (
        f"👋 <b>Привет, {user_name}!</b>\n\n"
        f"Добро пожаловать в авто-гарант бот 🛡\n"
        f"Здесь вы можете безопасно проводить сделки 🤝"
    )
    buttons = [
        [InlineKeyboardButton(text="🤝 Создать сделку", callback_data="create_deal")],
        [
            InlineKeyboardButton(text="📜 Мои сделки", callback_data="my_deals"),
            InlineKeyboardButton(text="👤 Профиль", callback_data="show_profile")
        ],
        [
            InlineKeyboardButton(text="📖 Правила", callback_data="rules"),
            InlineKeyboardButton(text="💬 Поддержка", callback_data="support")
        ]
    ]
    keyboard = InlineKeyboardMarkup(inline_keyboard=buttons)
    await send_response(callback, welcome_text, keyboard)

# --- Веб-сервер для Render (анти-ошибка порта) ---
async def handle(request):
    return web.Response(text="Bot is running 24/7!")

async def web_server():
    app = web.Application()
    app.router.add_get('/', handle)
    runner = web.AppRunner(app)
    await runner.setup()
    port = int(os.environ.get("PORT", 8080))
    site = web.TCPSite(runner, '0.0.0.0', port)
    await site.start()

async def main():
    global BOT_USERNAME
    bot_info = await bot.get_me()
    BOT_USERNAME = bot_info.username
    print(f"Бот @{BOT_USERNAME} успешно запущен!")
    await bot.delete_webhook(drop_pending_updates=True)
    
    # Запускаем веб-сервер параллельно с ботом, чтобы Render не ругался на порты
    asyncio.create_task(web_server())
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
