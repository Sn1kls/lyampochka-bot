BRAND = "Лямпочка"
SITE_URL = "https://poweron.toe.com.ua"

MENU_SCHEDULE = "📅 Графік"
MENU_NEXT = "⏭ Що далі"
MENU_LIST = "📋 Мої адреси"
MENU_ADD = "➕ Додати адресу"
MENU_SETTINGS = "⚙️ Налаштування"
MENU_REMOVE = "🗑 Видалити адресу"
MENU_HELP = "❓ Допомога"

GREETING = (
    f"Привіт! Я «{BRAND}» 💡\n"
    "Підкажу, коли у тебе вимикатимуть світло, і напишу, щойно обленерго змінить графік."
)
ADD_FIRST = "Почнімо з твоєї адреси 👇"
COMMANDS = (
    ("schedule", "графік на сьогодні чи завтра"),
    ("next", "коли вимкнуть чи увімкнуть світло"),
    ("add", "додати адресу"),
    ("list", "мої адреси"),
    ("settings", "налаштування сповіщень"),
    ("remove", "видалити адресу"),
    ("forget", "стерти всі мої дані"),
    ("help", "що я вмію"),
)

ASK_CITY = "З якого ти міста чи села? Напиши кілька літер назви."
CHOOSE_CITY = "Обери зі списку або напиши назву ще раз:"
ASK_STREET = "Місто: <b>{city}</b>.\nТепер напиши кілька літер назви вулиці."
CHOOSE_STREET = "Обери вулицю зі списку або напиши назву ще раз:"
CHOOSE_BUILDING = "Вулиця: <b>{street}</b>.\nОбери будинок зі списку або просто напиши його номер:"
NOTHING_FOUND = "Нічого не знайшлося. Спробуй написати інакше."
NO_BUILDINGS = "Для цієї вулиці будинків не знайшлося. Спробуй іншу вулицю."
BUILDING_NOT_FOUND = "Такого будинку не бачу. Обери зі списку або спробуй написати інакше."
NO_SCHEDULE_FOR_ADDRESS = (
    "На жаль, для адреси <b>{address}</b> графіки погодинних відключень не діють, "
    "тож підписувати не буду."
)
CHOOSE_QUEUES = "Твій будинок у кількох чергах: {queues}. Яку відстежувати?"
BUTTON_QUEUE = "Черга {queue}"
BUTTON_ALL_QUEUES = "Усі"
QUEUES_ONE = "підчерга {queues}"
QUEUES_MANY = "черги {queues}"
QUEUES_AND = " і "
QUEUE_TRACKED = "{queue} (стежу)"
CONFIRM_ADDRESS = (
    "<b>{address}</b>\n{queues}\n\nЗберегти як «{label}»? Хочеш іншу назву — просто напиши її."
)
ADDED = (
    "Готово! Адресу «{label}» додано. Графік з'явиться за кілька хвилин після першої "
    f"перевірки — тоді натисни «{MENU_SCHEDULE}» внизу."
)
CANCELLED = "Гаразд, скасовано."
DEFAULT_LABEL = "Дім"
LABEL_MAX_LENGTH = 40

NO_SUBSCRIPTIONS = "Адрес ще немає. Додай першу 👇"
LIST_HEADER = "Твої адреси:"
LIST_ITEM = "• <b>{label}</b> — {address} ({queues})"
CHOOSE_SUBSCRIPTION = "Яка адреса?"
CHOOSE_DAY = "На коли?"
TODAY = "Сьогодні"
TOMORROW = "Завтра"
REMOVE_PROMPT = "Яку адресу видалити?"
REMOVE_CONFIRM = "Видалити адресу «{label}»? Це не можна скасувати."
REMOVED = "Адресу видалено."
ADDRESS_GONE = "Такої адреси вже немає."
FORGET_CONFIRM = "Видалити всі твої адреси та дані? Це не можна скасувати."
FORGOTTEN = "Усе стерто. Якщо передумаєш — /start."

SOURCE_DOWN = "Сервіс обленерго зараз не відповідає. Спробуй трохи пізніше."
STALE_BUTTON = "Ця кнопка вже застаріла. Почни спочатку."
START_FIRST = "Спершу натисни /start, щоб ми познайомились."

HELP = (
    f"{MENU_SCHEDULE} — графік на сьогодні чи завтра\n"
    f"{MENU_NEXT} — коли вимкнуть чи увімкнуть світло\n"
    f"{MENU_LIST} — твої адреси; там же додати чи видалити\n"
    f"{MENU_SETTINGS} — сповіщення та нагадування\n\n"
    "Стерти всі свої дані: /forget"
)

BUTTON_SAVE = "Зберегти"
BUTTON_FORGET = "Так, видалити все"
BUTTON_REMOVE = "Так, видалити"
BUTTON_CANCEL = "Скасувати"
BUTTON_PREVIOUS = "◀️"
BUTTON_NEXT = "▶️"

DAY_TITLE = "💡 <b>{label}</b>, {day}"
DAY_TODAY = "сьогодні ({date})"
DAY_TOMORROW = "завтра ({date})"
SUBQUEUE_UPDATED = "Підчерга {subqueue} · оновлено {updated}"
SUBQUEUE = "Підчерга {subqueue}"
QUEUE_NOT_LOADED = "Графіка на цей день поки немає."
PICK_QUEUE_BUTTON = "Обери чергу кнопкою вище 👆"
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

NEXT_OFF = "світло вимкнуть о {latest} (через {delta})"
NEXT_OFF_WINDOW = "світло можуть вимкнути з {earliest}, точно — о {latest} (через {delta})"
NEXT_OFF_POSSIBLE = "можливе вимкнення з {earliest} (перемикання)"
NEXT_ON = "світло увімкнуть о {latest} (через {delta})"
NEXT_ON_WINDOW = "світло можуть увімкнути з {earliest}, точно — о {latest} (через {delta})"
NEXT_ON_ANYTIME = "світло можуть дати будь-якої хвилини, точно — о {latest}"
NEXT_ONE = "<b>{label}</b>: {event}"
NEXT_TITLE = "<b>{label}</b>:"
NEXT_QUEUE = "• підчерга {queue}: {event}"
NEXT_NONE = "<b>{label}</b>: найближчим часом змін не заплановано."

UPDATE_TITLE = "💡 Графік для <b>{label}</b>{queue} оновлено"
UPDATE_QUEUE = " (черга {queue})"
UPDATE_NEW_DAY = "З'явився графік на {date}:"
UPDATE_NEW_DAY_EMPTY = "З'явився графік на {date}: без відключень 🎉"
UPDATE_CHANGED_DAY = "Зміни на {date}:"
UPDATE_ADDED = "Додано:"
UPDATE_REMOVED = "Прибрано:"
UPDATE_LINK = f'<a href="{SITE_URL}">poweron.toe.com.ua</a>'

REMINDER_OFF_WINDOW = "⏰ <b>{label}</b>{queue}: за {minutes} хв можуть вимкнути світло (з {earliest}, точно — о {latest})"
REMINDER_OFF_EXACT = "⏰ <b>{label}</b>{queue}: за {minutes} хв вимкнуть світло (о {latest})"
REMINDER_OFF_POSSIBLE = "⏰ <b>{label}</b>{queue}: за {minutes} хв можливе вимкнення з {earliest}"
REMINDER_ON_WINDOW = (
    "💡 <b>{label}</b>{queue}: за {minutes} хв мають дати світло (з {earliest}, точно — о {latest})"
)
REMINDER_ON_EXACT = "💡 <b>{label}</b>{queue}: за {minutes} хв дадуть світло (о {latest})"
REMINDER_ON_POSSIBLE = (
    "💡 <b>{label}</b>{queue}: за {minutes} хв можливе повернення світла з {earliest}"
)

SUBQUEUES_CHANGED = (
    "🔄 Для <b>{label}</b> змінилися черги.\n"
    "Було: {previous}\nСтало: {current}\nСтежу за: {tracked}\n\n"
    f"Перевір, чи все гаразд, у «{MENU_SETTINGS}»."
)
SUBQUEUES_GONE = (
    "⚠️ За даними обленерго, графіки відключень для <b>{label}</b>, схоже, більше не діють "
    "на цю адресу.\nМожливо, це збій у даних, тож нічого не змінюю — перевір на "
    f"{UPDATE_LINK}"
)

MENU_UPDATED = "🔄 Оновив меню: тепер усе під кнопками внизу 👇"
PLANNED_WORK = "🛠 <b>{label}</b>: планові роботи {date} з {start} до {end}"
PLANNED_WORK_REASON = " — {reason}"

SETTINGS_TITLE = "⚙️ Налаштування для <b>{label}</b>"
SETTINGS_UPDATES = "Пуші про оновлення графіка і планові роботи: {state}"
SETTINGS_REMINDER_OFF = "⏰ Нагадати перед вимкненням: {when}"
SETTINGS_REMINDER_ON = "💡 Нагадати перед поверненням світла: {when}"
SETTINGS_ENABLED = "увімкнено"
SETTINGS_DISABLED = "вимкнено"
BUTTON_UPDATES_ON = "✅ Пуші про оновлення"
BUTTON_UPDATES_OFF = "🚫 Пуші про оновлення"
BUTTON_REMINDER_OFF = "⏰ Нагадати до вимкнення: {value}"
BUTTON_REMINDER_ON = "💡 Нагадати до повернення: {value}"
REMINDER_NONE = "без"

DURATION_HOURS = "{hours} год"
DURATION_MINUTES = "{minutes} хв"

ALERT_API_SCHEMA = (
    "🚨 Відповідь обленерго змінила формат, тож я не можу її розібрати. "
    "Показую графіки з пам'яті.\n<code>{details}</code>"
)
ALERT_API_DOWN = (
    "🚨 Сайт обленерго давно не відповідає. Показую графіки з пам'яті.\n<code>{details}</code>"
)
ALERT_NEW_USER = "👤 Новий користувач: {details}"
ALERT_BACKUP_FAILED = (
    "🗄 Не вдалося зробити щоденний бекап бази, спробую ще раз.\n<code>{details}</code>"
)
BACKUP_CAPTION = "🗄 Бекап бази {name}, зашифрований паролем BACKUP_PASSWORD"

STATUS_TITLE = "📊 <b>Лямпочка {version}</b>"
STATUS_COUNTS = "Користувачів: {users}, адрес: {subscriptions}, у черзі розсилки: {pending}"
STATUS_SUBQUEUE = "{label}: {polled}"
STATUS_SUBQUEUE_STALE = "⚠️ {label}: {polled}"
STATUS_NEVER_POLLED = "ще не опитувалась"
