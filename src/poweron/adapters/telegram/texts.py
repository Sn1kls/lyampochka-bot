BRAND = "Лямпочка"
# Each oblenergo's own schedule page: (link, what the user sees).
SITE_TERNOPIL = ("https://poweron.toe.com.ua", "poweron.toe.com.ua")
SITE_VOLYN = (
    "https://energy.volyn.ua/spozhyvacham/perervy-u-elektropostachanni/hrafik-vidkliuchen/",
    "energy.volyn.ua",
)
SITE_LVIV = ("https://poweron.loe.lviv.ua", "poweron.loe.lviv.ua")
# Behind a bot check that a person's browser passes; also DTEK's current outages page.
SITE_DNEM = ("https://www.dtek-dnem.com.ua/ua/shutdowns", "dtek-dnem.com.ua")
SITE_CEK = ("https://cek.dp.ua/index.php/cpojivaham/vidkliuchennia.html", "cek.dp.ua")
# Each oblenergo's page of the outages happening now (Lviv: its homepage). Checked 2026-11-24.
OUTAGES_TERNOPIL = "https://poweron.toe.com.ua/avarijni_vidkluchenna_realtime"
OUTAGES_VOLYN = (
    "https://energy.volyn.ua/spozhyvacham/perervy-u-elektropostachanni/"
    "chomu-nemaie-elektropostachannia/"
)
OUTAGES_CEK = "https://cek.dp.ua/index.php/cpojivaham/vidkliuchennia/2-uncategorised/961-gav.html"
BUTTON_OUTAGES = "⚡ Немає світла? Аварійні"

MENU_SCHEDULE = "📅 Графік"
MENU_NEXT = "⏭ Що далі"
MENU_LIST = "📋 Мої адреси"
MENU_ADD = "➕ Додати адресу"
MENU_SETTINGS = "⚙️ Налаштування"
MENU_REMOVE = "🗑 Видалити адресу"
MENU_HELP = "❓ Допомога"
MENU_FEEDBACK = "✉️ Написати розробнику"
MENU_FEEDBACK_OLD = "✉️ Відгук"
# Where someone gets stuck adding an address.
STUCK = f"\nНе виходить? Натисни «{MENU_FEEDBACK}» внизу і напиши, що шукаєш."

GREETING = (
    f"Привіт! Я «{BRAND}» 💡\n"
    "Підкажу, коли у тебе вимикатимуть світло, і напишу, щойно обленерго змінить графік."
)
ADD_FIRST = "Почнімо з твоєї адреси 👇"
# Profile "about" (≤120 chars) and the empty-chat description before Start (≤512 chars).
ABOUT = (
    "Графіки відключень світла на Волині, Дніпропетровщині, Львівщині й Тернопільщині: "
    "сповіщення про зміни й нагадування 💡"
)
DESCRIPTION = (
    f"Привіт! Я «{BRAND}» 💡\n\n"
    "Стежу за графіками відключень світла Волиньобленерго, ДТЕК і ЦЕК на Дніпропетровщині, "
    "Львівобленерго та Тернопільобленерго.\n\n"
    "• Покажу графік для твоєї адреси на сьогодні й завтра\n"
    "• Напишу, щойно графік зміниться\n"
    "• Нагадаю перед вимкненням\n\n"
    "Натисни кнопку внизу й додай свою адресу 👇"
)
COMMANDS = (
    ("schedule", "графік на сьогодні чи завтра"),
    ("next", "коли вимкнуть чи увімкнуть світло"),
    ("add", "додати адресу"),
    ("list", "мої адреси"),
    ("settings", "налаштування сповіщень"),
    ("remove", "видалити адресу"),
    ("forget", "стерти всі мої дані"),
    ("feedback", "написати розробнику"),
    ("help", "що я вмію"),
)

ASK_REGION = "У якій області адреса?"
REGION_TERNOPIL = "Тернопільська"
REGION_VOLYN = "Волинська"
REGION_LVIV = "Львівська"
REGION_DNIPRO = "Дніпропетровська"
# Next to a Dnipropetrovsk queue: the two operators' groups share names («1.1»).
OPERATOR_DNEM = "ДТЕК"
OPERATOR_CEK = "ЦЕК"
ASK_CITY = "З якого ти міста чи села? Напиши кілька літер назви."
CHOOSE_CITY = "Обери зі списку або напиши назву ще раз:"
ASK_STREET = "Місто: <b>{city}</b>.\nТепер напиши кілька літер назви вулиці."
CHOOSE_STREET = "Обери вулицю зі списку або напиши назву ще раз:"
CHOOSE_BUILDING = "Вулиця: <b>{street}</b>.\nОбери будинок зі списку або просто напиши його номер:"
ASK_BUILDING_NUMBER = "Вулиця: <b>{street}</b>.\nНапиши номер будинку, наприклад 12 чи 12А."
NOTHING_FOUND = "Нічого не знайшлося. Спробуй написати інакше." + STUCK
NO_BUILDINGS = "Для цієї вулиці будинків не знайшлося. Спробуй іншу вулицю." + STUCK
BUILDING_NOT_FOUND = "Такого будинку не бачу. Обери зі списку або спробуй написати інакше." + STUCK
NO_SCHEDULE_FOR_ADDRESS = (
    "На жаль, для адреси <b>{address}</b> графіки погодинних відключень не діють, "
    "тож підписувати не буду.\n"
    f"Думаєш, це помилка? Натисни «{MENU_FEEDBACK}» внизу і напиши."
)
CHOOSE_QUEUES = "Твій будинок у кількох чергах: {queues}. Яку відстежувати?"
BUTTON_QUEUE = "Черга {queue}"
BUTTON_ALL_QUEUES = "Усі"
QUEUES_ONE = "підчерга {queues}"
QUEUES_MANY = "черги {queues}"
QUEUES_AND = " і "
QUEUE_TRACKED = "{queue} (стежу)"
CONFIRM_ADDRESS = (
    "<b>{address}</b>\n{queues}\n\nЗберегти як «{label}»? Хочеш іншу назву – просто напиши її."
)
ADDED = (
    "Готово! Адресу «{label}» додано. Графік з'явиться за кілька хвилин після першої "
    f"перевірки – тоді натисни «{MENU_SCHEDULE}» внизу."
)
CANCELLED = "Гаразд, скасовано."
DEFAULT_LABEL = "Дім"
LABEL_MAX_LENGTH = 40

NO_SUBSCRIPTIONS = "Адрес ще немає. Додай першу 👇"
LIST_HEADER = "Твої адреси:"
LIST_ITEM = "• <b>{label}</b> – {address} ({queues})"
CHOOSE_SUBSCRIPTION = "Яка адреса?"
CHOOSE_DAY = "На коли?"
TODAY = "Сьогодні"
TOMORROW = "Завтра"
REMOVE_PROMPT = "Яку адресу видалити?"
REMOVE_CONFIRM = "Видалити адресу «{label}»? Це не можна скасувати."
REMOVED = "Адресу видалено."
ADDRESS_GONE = "Такої адреси вже немає."
FORGET_CONFIRM = "Видалити всі твої адреси та дані? Це не можна скасувати."
FORGOTTEN = "Усе стерто. Якщо передумаєш – /start."

SOURCE_DOWN = "Сервіс обленерго зараз не відповідає. Спробуй трохи пізніше."
STALE_BUTTON = "Ця кнопка вже застаріла. Почни спочатку."
START_FIRST = "Спершу натисни /start, щоб ми познайомились."

HELP = (
    f"{MENU_SCHEDULE} – графік на сьогодні чи завтра\n"
    f"{MENU_NEXT} – коли вимкнуть чи увімкнуть світло\n"
    f"{MENU_LIST} – твої адреси; там же додати чи видалити\n"
    f"{MENU_SETTINGS} – сповіщення, нагадування, назва адреси\n"
    f"{MENU_FEEDBACK} – питання, скарга чи ідея, розробник відповість тут\n\n"
    "Стерти всі свої дані: /forget"
)

BUTTON_SAVE = "Зберегти"
BUTTON_FORGET = "Так, видалити все"
BUTTON_REMOVE = "Так, видалити"
BUTTON_CANCEL = "Скасувати"
BUTTON_PREVIOUS = "◀️"
BUTTON_NEXT = "▶️"

DAY_TITLE = "📅 <b>{label}</b>, {day}"
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
NO_SCHEDULE_TOMORROW = "Графіка на завтра ще немає – щойно з'явиться, напишу."
STALE_DATA = "⚠️ Дані могли застаріти: востаннє з сайту оновлено {checked}."
NOTE = "Графік може змінюватися впродовж дня, тож поглядай і на {site}"

# Hours are read as ordinals, so only 11 («одинадцятій») starts with a vowel and takes «об».
AT = "о {time}"
AT_ELEVEN = "об {time}"
NEXT_OFF = "світло вимкнуть {at_latest} (через {delta})"
NEXT_OFF_WINDOW = "світло можуть вимкнути з {earliest}, точно – {at_latest} (через {delta})"
NEXT_OFF_POSSIBLE = "можливе вимкнення з {earliest} (перемикання)"
NEXT_ON = "світло увімкнуть {at_latest} (через {delta})"
NEXT_ON_WINDOW = "світло можуть увімкнути з {earliest}, точно – {at_latest} (через {delta})"
NEXT_ON_ANYTIME = "світло можуть дати будь-якої хвилини, точно – {at_latest}"
NEXT_ONE = "<b>{label}</b>: {event}"
NEXT_TITLE = "<b>{label}</b>:"
NEXT_QUEUE = "• підчерга {queue}: {event}"
NEXT_NONE = "<b>{label}</b>: найближчим часом змін не заплановано."

# The address only when the user has several, the queue only when the address tracks several.
FOR_ADDRESS = " · <b>{label}</b>"
FOR_ADDRESS_QUEUE = " · <b>{label}</b> (черга {queue})"
FOR_QUEUE = " · черга {queue}"
UPDATE_TITLE = "💡 Оновлення на {day}{target}:"
UPDATE_NEW_LINE = " 🆕"
UPDATE_STALE_REMINDER = "⚠️ Нагадування про вимкнення {at_times} уже неактуальне."
UPDATE_LINK = '<a href="{url}">{site}</a>'

# 🪫 means "power goes off", 🔋 means "power comes back".
REMINDER_OFF_WINDOW = (
    "🪫 За {minutes} хв можуть ВИМКНУТИ світло (з {earliest}, точно – {at_latest})"
)
REMINDER_OFF_EXACT = "🪫 За {minutes} хв ВИМКНУТЬ світло ({at_latest})"
REMINDER_OFF_POSSIBLE = "🪫 За {minutes} хв можливе ВИМКНЕННЯ з {earliest}"
REMINDER_ON_WINDOW = "🔋 За {minutes} хв мають ДАТИ світло (з {earliest}, точно – {at_latest})"
REMINDER_ON_EXACT = "🔋 За {minutes} хв ДАДУТЬ світло ({at_latest})"
REMINDER_ON_POSSIBLE = "🔋 За {minutes} хв можливе ПОВЕРНЕННЯ світла з {earliest}"

SUBQUEUES_CHANGED = (
    "🔄 Для <b>{label}</b> змінилися черги.\n"
    "Було: {previous}\nСтало: {current}\nСтежу за: {tracked}\n\n"
    f"Перевір, чи все гаразд, у «{MENU_SETTINGS}»."
)
SUBQUEUES_GONE = (
    "⚠️ За даними обленерго, графіки відключень для <b>{label}</b>, схоже, більше не діють "
    "на цю адресу.\nМожливо, це збій у даних, тож нічого не змінюю – перевір на {link}"
)

NO_ADDRESS_NUDGE = (
    "👋 Адреси ще немає, тому я не можу показувати графік і надсилати сповіщення.\n"
    f"Натисни «{MENU_ADD}» внизу: це кілька секунд 👇" + STUCK
)

MENU_UPDATED = (
    "🔄 Оновив меню внизу 👇\n"
    f"{MENU_HELP} – що вміє кожна кнопка\n"
    f"{MENU_FEEDBACK} – питання, скарга чи ідея, можна зі скріном"
)
PLANNED_WORK = "🛠 <b>{label}</b>: планові роботи {date} з {start} до {end}"
PLANNED_WORK_REASON = " – {reason}"
EMERGENCY = "⚠️ <b>Зараз аварійне відключення</b>, світло обіцяють дати {at}"
PLANNED_NOW = "🛠 <b>Зараз планове відключення</b>, світло обіцяють дати {at}"
SUSPENDED = "⚠️ <b>Зараз екстрені відключення</b>, графік не діє"
OUTAGE_REASON = "\nПричина: {reason}"

SETTINGS_TITLE = "⚙️ Налаштування для <b>{label}</b>"
SETTINGS_UPDATES = "Сповіщення про оновлення графіка і планові роботи: {state}"
SETTINGS_REMINDER_OFF = "🪫 Нагадати перед вимкненням: {when}"
SETTINGS_REMINDER_ON = "🔋 Нагадати перед поверненням світла: {when}"
SETTINGS_REMIND_POSSIBLE = "⏱ Нагадувати до: можливого відключення 🟡"
SETTINGS_REMIND_EXACT = "⏱ Нагадувати до: точного відключення 🔴"
SETTINGS_ENABLED = "увімкнено"
SETTINGS_DISABLED = "вимкнено"
BUTTON_UPDATES_ON = "✅ Сповіщення про оновлення"
BUTTON_UPDATES_OFF = "🚫 Сповіщення про оновлення"
BUTTON_QUEUE_TRACKED = "✅ Черга {queue}"
BUTTON_QUEUE_UNTRACKED = "🚫 Черга {queue}"
LAST_TRACKED_QUEUE = (
    "Хоча б за однією чергою треба стежити. Щоб прибрати адресу повністю – «🗑 Видалити адресу»."
)
BUTTON_REMINDER_OFF = "🪫 Нагадати до вимкнення: {value}"
BUTTON_REMINDER_ON = "🔋 Нагадати до повернення: {value}"
BUTTON_REMIND_POSSIBLE = "⏱ Нагадувати до: можливого 🟡"
BUTTON_REMIND_EXACT = "⏱ Нагадувати до: точного 🔴"
BUTTON_RENAME = "✏️ Змінити назву"
ASK_NEW_LABEL = "Напиши нову назву для «{label}»."
RENAMED = "Готово! Тепер ця адреса зветься «{label}»."
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
ALERT_SCHEDULE_STALE = (
    "🚨 Графік черги давно не оновлюється: обленерго не віддає дані. "
    "Показую графіки з пам'яті.\n<code>{details}</code>"
)
ALERT_SIDE_API_DOWN = (
    "⚠️ Частина сайту обленерго не відповідає: планові роботи або перевірка черг. "
    "Спробую пізніше.\n<code>{details}</code>"
)
ALERT_NEW_USER = "👤 Новий користувач: {details}\n↩️ Зроби Reply, щоб написати цій людині."
ALERT_BACKUP_FAILED = (
    "🗄 Не вдалося зробити щоденний бекап бази, спробую ще раз.\n<code>{details}</code>"
)
ALERT_VOE_CATALOG_STALE = (
    "📒 Довідник черг Волині давно не оновлювався ({details}). "
    "Перевір щотижневе вивантаження на Mac: <code>scripts/sync_volyn_queues.sh</code>"
)
ALERT_VOE_CATALOG_IMPORTED = "📒 Довідник черг Волині оновлено: {details}"
ALERT_SCHEDULE_SUSPENDED = (
    "⚠️ YASNO показує екстрені відключення ({details}): графік не діє. "
    "Час подивитися, як виглядає відповідь, і вирішити про пуш."
)
BACKUP_CAPTION = "🗄 Бекап бази {name}, зашифрований паролем BACKUP_PASSWORD"

STATUS_TITLE = "📊 <b>Лямпочка {version}</b>"
STATUS_COUNTS = "Користувачів: {users}, адрес: {subscriptions}, у черзі розсилки: {pending}"
STATUS_REGION = "\n<b>{region}</b>"
STATUS_SUBQUEUE = "{label}: опитано {polled}, {schedule}"
STATUS_SUBQUEUE_STALE = "⚠️ {label}: опитано {polled}, {schedule}"
STATUS_NEVER_POLLED = "⚠️ {label}: ще не опитувалась"
STATUS_LAST_SCHEDULE = "останній графік на {day}"
STATUS_NO_SCHEDULE = "графіків ще немає"

FEEDBACK_ASK = (
    "Напиши питання, скаргу чи ідею. Можна скрін, файл чи голосове.\n"
    "Прочитає розробник і відповість тут, у цьому чаті."
)
FEEDBACK_SENT = "Дякую! Передав розробнику ✉️"
FEEDBACK_CANCELLED = "Добре, скасовано."
FEEDBACK_LIMIT = "Повідомлень забагато. Спробуй знову через {minutes} хв."
FEEDBACK_UNAVAILABLE = "Зараз написати розробнику не вийде, спробуй пізніше."
FEEDBACK_HEADER = (
    "✉️ <b>Відгук</b> · користувач #{user_id}\n"
    "{name}\n\n"
    "{addresses}\n\n"
    "↩️ Щоб відповісти, зроби Reply на цей заголовок або на сам відгук вище."
)
FEEDBACK_NO_ADDRESSES = "Адрес немає."
FEEDBACK_REPLY = "💬 <b>Від розробника</b>\n\n{text}"
FEEDBACK_REPLY_SENT = "✅ Надіслано"
FEEDBACK_USER_GONE = "Цього користувача вже немає: він стер свої дані або заблокував бота."
FEEDBACK_REPLY_TEXT_ONLY = "Відповідь можна надіслати лише текстом."
FEEDBACK_REPLY_TOO_LONG = "Задовга відповідь: максимум {limit} символів."
FEEDBACK_NOT_COPYABLE = (
    "Таке повідомлення передати не можу. Надішли текст, скрін, файл чи голосове."
)
