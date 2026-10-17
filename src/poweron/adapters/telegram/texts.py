BRAND = "Лямпочка"
SITE_URL = "https://poweron.toe.com.ua"

GREETING = (
    f"Привіт! Я «{BRAND}» 💡\n"
    "Підкажу, коли у тебе вимикатимуть світло, і напишу, щойно обленерго змінить графік.\n\n"
    "Почнімо з адреси: /add\n"
    "Усі команди: /help"
)
COMMANDS = (
    ("schedule", "графік на сьогодні чи завтра"),
    ("next", "коли вимкнуть чи увімкнуть світло"),
    ("add", "додати адресу"),
    ("list", "мої адреси"),
    ("remove", "видалити адресу"),
    ("forget", "стерти всі мої дані"),
    ("help", "що я вмію"),
)
HELP = "\n".join(f"/{command} — {description}" for command, description in COMMANDS)

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
ADDED = (
    "Готово! Адресу «{label}» додано. Графік з'явиться за кілька хвилин після першої "
    "перевірки — тоді глянь його: /schedule"
)
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
START_FIRST = "Спершу натисни /start, щоб ми познайомились."

BUTTON_SAVE = "Зберегти"
BUTTON_FORGET = "Так, видалити все"
BUTTON_CANCEL = "Скасувати"
BUTTON_PREVIOUS = "◀️"
BUTTON_NEXT = "▶️"

DAY_TITLE = "💡 <b>{label}</b>, {day}"
DAY_TODAY = "сьогодні ({date})"
DAY_TOMORROW = "завтра ({date})"
SUBQUEUE_UPDATED = "Підчерга {subqueue} · оновлено {updated}"
LINE_ON = "🟢 {start}–{end} є світло"
LINE_OFF = "🔴 {start}–{end} немає світла"
LINE_SWITCHING = "🟡 {start}–{end} можливе відключення (перемикання)"
LINE_UNKNOWN = "⚪ {start}–{end} невідомо, уточни на сайті"
TOTAL_OFF = "Разом без світла: {duration}"
TOTAL_WITH_SWITCHING = " (до {duration} з перемиканнями)"
NO_OUTAGES = "Відключень не заплановано 🎉"
ONLY_SWITCHING = "Відключень не заплановано, лише можливі перемикання (до {duration})"
NO_SCHEDULE_TODAY = (
    "Графіка на сьогодні поки немає: його або ще не опубліковано, або він ще не завантажився. "
    "Спробуй за кілька хвилин."
)
NO_SCHEDULE_TOMORROW = "Графіка на завтра ще немає — щойно з'явиться, напишу."
STALE_DATA = "⚠️ Дані могли застаріти: востаннє з сайту оновлено {checked}."
NOTE = "Графік може змінюватися впродовж дня, тож поглядай і на poweron.toe.com.ua"

NEXT_OFF = "<b>{label}</b>: світло вимкнуть о {latest} (через {delta})"
NEXT_OFF_WINDOW = (
    "<b>{label}</b>: світло можуть вимкнути з {earliest}, точно — о {latest} (через {delta})"
)
NEXT_OFF_POSSIBLE = "<b>{label}</b>: можливе вимкнення з {earliest} (перемикання)"
NEXT_ON = "<b>{label}</b>: світло увімкнуть о {latest} (через {delta})"
NEXT_ON_WINDOW = (
    "<b>{label}</b>: світло можуть увімкнути з {earliest}, точно — о {latest} (через {delta})"
)
NEXT_ON_ANYTIME = "<b>{label}</b>: світло можуть дати будь-якої хвилини, точно — о {latest}"
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
