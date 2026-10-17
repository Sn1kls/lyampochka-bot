BRAND = "Лямпочка"
SITE_URL = "https://poweron.toe.com.ua"

GREETING = (
    f"Привіт! Я «{BRAND}» 💡\n"
    "Підкажу, коли у тебе вимикатимуть світло, і напишу, щойно обленерго змінить графік.\n\n"
    "Почнімо з адреси: /add\n"
    "Усі команди: /help"
)
HELP = (
    "/add — додати адресу\n"
    "/list — мої адреси\n"
    "/schedule — графік на сьогодні чи завтра\n"
    "/next — найближче вимкнення чи увімкнення\n"
    "/remove — видалити адресу\n"
    "/forget — стерти всі мої дані"
)

ASK_CITY = "З якого ти міста чи села? Напиши кілька літер назви."
CHOOSE_CITY = "Обери зі списку або напиши назву ще раз:"
ASK_STREET = "Місто: <b>{city}</b>.\nТепер напиши кілька літер назви вулиці."
CHOOSE_STREET = "Обери вулицю зі списку або напиши назву ще раз:"
CHOOSE_BUILDING = "Обери будинок зі списку або просто напиши його номер:"
NOTHING_FOUND = "Нічого не знайшлося. Спробуй написати інакше."
NO_BUILDINGS = "Для цієї вулиці будинків не знайшлося. Спробуй іншу вулицю."
BUILDING_NOT_FOUND = "Такого будинку не бачу. Обери зі списку або спробуй написати інакше."
NO_SCHEDULE_FOR_ADDRESS = (
    "На жаль, для адреси <b>{address}</b> графіки погодинних відключень не діють, "
    "тож підписувати не буду."
)
CONFIRM_ADDRESS = (
    "<b>{address}</b>\nПідчерга {subqueue}\n\n"
    "Зберегти як «{label}»? Хочеш іншу назву — просто напиши її."
)
ADDED = "Готово! Адресу «{label}» додано. Глянь графік: /schedule"
CANCELLED = "Гаразд, скасовано."
DEFAULT_LABEL = "Дім"
LABEL_MAX_LENGTH = 40

NO_SUBSCRIPTIONS = "Адрес ще немає. Додай першу: /add"
LIST_HEADER = "Твої адреси:"
LIST_ITEM = "• <b>{label}</b> — {address} (підчерга {subqueue})"
CHOOSE_SUBSCRIPTION = "Яка адреса?"
CHOOSE_DAY = "На коли?"
TODAY = "Сьогодні"
TOMORROW = "Завтра"
REMOVE_PROMPT = "Яку адресу видалити?"
REMOVED = "Адресу видалено."
ADDRESS_GONE = "Такої адреси вже немає."
FORGET_CONFIRM = "Видалити всі твої адреси та дані? Це не можна скасувати."
FORGOTTEN = "Усе стерто. Якщо передумаєш — /start."

SOURCE_DOWN = "Сервіс обленерго зараз не відповідає. Спробуй трохи пізніше."
STALE_BUTTON = "Ця кнопка вже застаріла. Почни спочатку."

BUTTON_SAVE = "Зберегти"
BUTTON_FORGET = "Так, видалити все"
BUTTON_CANCEL = "Скасувати"

DAY_TITLE = "💡 <b>{label}</b>, {day}"
DAY_TODAY = "сьогодні ({date})"
DAY_TOMORROW = "завтра ({date})"
SUBQUEUE_UPDATED = "Підчерга {subqueue} · оновлено {updated}"
LINE_ON = "🟢 {start}–{end} є світло"
LINE_OFF = "🔴 {start}–{end} немає світла"
LINE_SWITCHING = "🟡 {start}–{end} можливе відключення (перемикання)"
LINE_UNKNOWN = "⚪ {start}–{end} невідомо, уточни на сайті"
TOTAL_OFF = "Разом без світла: {duration}"
NO_OUTAGES = "Відключень не заплановано 🎉"
NO_SCHEDULE_TODAY = "Графіка на сьогодні ще немає."
NO_SCHEDULE_TOMORROW = "Графіка на завтра ще немає — щойно з'явиться, напишу."
NOTE = "Графік може змінюватися впродовж дня, тож поглядай і на poweron.toe.com.ua"

NEXT_OFF = "<b>{label}</b>: світло вимкнуть о {time} (через {delta})"
NEXT_ON = "<b>{label}</b>: світло увімкнуть о {time} (через {delta})"
NEXT_NONE = "<b>{label}</b>: найближчим часом змін не заплановано."

UPDATE_TITLE = "💡 Графік для <b>{label}</b> оновлено"
UPDATE_NEW_DAY = "З'явився графік на {date}:"
UPDATE_NEW_DAY_EMPTY = "З'явився графік на {date}: без відключень 🎉"
UPDATE_CHANGED_DAY = "Зміни на {date}:"
UPDATE_ADDED = "Додано:"
UPDATE_REMOVED = "Прибрано:"
UPDATE_LINK = f'<a href="{SITE_URL}">poweron.toe.com.ua</a>'

DURATION_HOURS = "{hours} год"
DURATION_MINUTES = "{minutes} хв"
