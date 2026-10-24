# -*- coding: utf-8 -*-
"""
ربات مدرسه فانوس برای پیام‌رسان بله (Bale) — نسخه کامل
======================================================
قابلیت‌ها:
- منوی شیشه‌ای چندسطحی (بخش‌های تودرتو با عمق نامحدود)
- پنل مدیریت چند ادمینه (افزودن/حذف ادمین توسط مالک)
- CRUD کامل بخش‌ها (عنوان، متن، لینک، ترتیب، فعال/مخفی، حذف آبشاری)
- برنامه هفتگی (کلاس/آزمون/مشاوره/اطلاعیه) + یادآوری همگانی
- جزوه‌ها و فایل‌ها (دکمه لینک)، سوالات متداول با صفحه‌بندی
- نظرسنجی (آزمونک) با نتیجه درصدی، آزمون تعیین سطح
- پشتیبانی/تیکت با ارسال پیام به همه ادمین‌ها و پاسخ ادمین
- پروفایل کاربر، آمار ادمین، ارسال همگانی با تأیید و گزارش
- خوش‌آمدگویی فقط یک‌بار (بعد از آن ناوبری بدون سلام)
- فقط کتابخانه requests + کتابخانه استاندارد پایتون

روش اجرا:
  pip install requests
  python bot.py
دستورها: /start ، /id ، /admin ، /help
"""

import os
import re
import json
import time
import sqlite3
import traceback
import datetime
from urllib.parse import urlparse, parse_qs

import requests

# ================== تنظیمات اصلی ==================
TOKEN = "1518094453:YfPVh7dOISdTIr-LhsdHhsSb7R-IbiN9abY" 

OWNER_ID = 1891614962              # شناسه مالک (همیشه ادمین است و حذف نمی‌شود)
DB_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)) or ".", "bot.db")
API = "https://tapi.bale.ai/bot{}/{}"

DEFAULT_SETTINGS = {
    "buttons_per_row": "1",                       # تعداد دکمه در هر ردیف منو
    "support_username": "fanous_support",         # آیدی پشتیبانی (بدون @)
    "support_phone": "021-0000000",               # تلفن پشتیبانی
    "support_id": "0",                            # شناسه عددی پشتیبانی
    "quiz_active": "0",                           # شناسه آزمون فعال
}
EVENT_KINDS = ["کلاس", "آزمون", "مشاوره", "اطلاعیه"]
PAGE_SIZE = 5                                     # تعداد آیتم در هر صفحه لیست‌ها

# وضعیت‌های موقت کاربران: STATES[chat_id] = [نام_وضعیت, داده]
STATES = {}
# محدودسازی نرخ کلیک دکمه: CB_TIMES[chat_id] = آخرین زمان کلیک
CB_TIMES = {}

FEATURES = {
    "sched": "📅 برنامه کلاسی", "res": "📚 جزوه‌ها و فایل‌ها",
    "faq": "❓ سوالات متداول", "polls": "🧪 آزمونک (نظرسنجی)",
    "quiz": "🏆 آزمون تعیین سطح", "support": "🙋 پشتیبانی / ارتباط با ما",
    "profile": "👤 پروفایل من",
}

# ================== لایه ارتباط با API بله ==================
def api(method, retries=2, **payload):
    """فراخوانی امن متدهای Bot API بله؛ در خطای شبکه چند بار تلاش می‌کند."""
    for attempt in range(retries + 1):
        try:
            r = requests.post(API.format(TOKEN, method), json=payload, timeout=35)
            try:
                return r.json()
            except ValueError:
                print(f"[خطا] پاسخ غیر JSON از {method}: {r.status_code} {r.text[:200]}")
                return {"ok": False, "description": "bad json"}
        except requests.RequestException as e:
            print(f"[خطای شبکه] {method} تلاش {attempt + 1}: {e}")
            time.sleep(1 + attempt)
    return {"ok": False, "description": "network error"}

def send_message(chat_id, text, reply_markup=None):
    """ارسال پیام متنی ساده (بدون parse_mode برای جلوگیری از خطای 400)."""
    return api("sendMessage", chat_id=chat_id, text=text, reply_markup=reply_markup)

def edit_message(chat_id, message_id, text, reply_markup=None):
    """ویرایش پیام موجود؛ اگر ممکن نبود پیام جدید می‌فرستد."""
    r = api("editMessageText", chat_id=chat_id, message_id=message_id,
            text=text, reply_markup=reply_markup)
    if not (r and r.get("ok")):
        desc = (r or {}).get("description", "")
        if "not modified" not in desc:  # اگر واقعا ویرایش نشد
            return send_message(chat_id, text, reply_markup)
    return r

def answer_callback(callback_id, text=None):
    """پاسخ به کلیک دکمه شیشه‌ای (حذف حالت لودینگ + پیام کوتاه)."""
    p = {"callback_query_id": callback_id}
    if text:
        p["text"] = text
    api("answerCallbackQuery", **p)

def make_keyboard(buttons, row_width=None):
    """ساخت کیبورد شیشه‌ای؛ buttons = [(متن, callback_data) یا (متن, callback_data, True) برای لینک]."""
    if row_width is None:
        row_width = get_setting_int("buttons_per_row", 1)
        row_width = max(1, min(4, row_width))
    kb = []
    for i in range(0, len(buttons), row_width):
        row = []
        for b in buttons[i:i + row_width]:
            if len(b) == 3 and b[2]:  # دکمه URL
                row.append({"text": b[0], "url": b[1]})
            else:
                row.append({"text": b[0], "callback_data": b[1]})
        kb.append(row)
    return {"inline_keyboard": kb} if kb else None

# ================== دیتابیس ==================
def db():
    """اتصال جدید به دیتابیس."""
    conn = sqlite3.connect(DB_PATH)
    conn.execute("PRAGMA journal_mode=WAL")
    return conn

def q(sql, params=(), fetch="none"):
    """اجرای کوئری ساده با اتصال خودکار."""
    conn = db()
    try:
        cur = conn.execute(sql, params)
        if fetch == "one":
            return cur.fetchone()
        if fetch == "all":
            return cur.fetchall()
        conn.commit()
        return None
    finally:
        conn.close()

def init_db():
    """ساخت جدول‌ها، تنظیمات پیش‌فرض، بخش‌های اولیه و ثبت مالک."""
    conn = db()
    c = conn.cursor()
    c.executescript("""
    CREATE TABLE IF NOT EXISTS users(
        chat_id INTEGER PRIMARY KEY,
        first_name TEXT,
        joined_at TEXT,
        greeted INTEGER DEFAULT 0);
    CREATE TABLE IF NOT EXISTS admins(
        chat_id INTEGER PRIMARY KEY,
        name TEXT,
        added_at TEXT);
    CREATE TABLE IF NOT EXISTS settings(
        key TEXT PRIMARY KEY,
        value TEXT);
    CREATE TABLE IF NOT EXISTS sections(
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        parent_id INTEGER,
        title TEXT,
        content TEXT DEFAULT '',
        url TEXT DEFAULT '',
        sort_order INTEGER DEFAULT 0,
        is_active INTEGER DEFAULT 1,
        created_at TEXT);
    CREATE TABLE IF NOT EXISTS events(
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        title TEXT,
        description TEXT DEFAULT '',
        event_date TEXT,
        event_time TEXT DEFAULT '',
        kind TEXT DEFAULT 'کلاس');
    CREATE TABLE IF NOT EXISTS resources(
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        title TEXT,
        url TEXT,
        description TEXT DEFAULT '');
    CREATE TABLE IF NOT EXISTS faqs(
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        question TEXT,
        answer TEXT);
    CREATE TABLE IF NOT EXISTS polls(
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        question TEXT,
        created_at TEXT);
    CREATE TABLE IF NOT EXISTS poll_options(
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        poll_id INTEGER,
        text TEXT,
        votes INTEGER DEFAULT 0);
    CREATE TABLE IF NOT EXISTS poll_votes(
        poll_id INTEGER,
        chat_id INTEGER,
        option_id INTEGER,
        PRIMARY KEY(poll_id, chat_id));
    CREATE TABLE IF NOT EXISTS quiz_questions(
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        text TEXT,
        sort_order INTEGER DEFAULT 0);
    CREATE TABLE IF NOT EXISTS quiz_options(
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        question_id INTEGER,
        text TEXT,
        is_correct INTEGER DEFAULT 0);
    CREATE TABLE IF NOT EXISTS quiz_results(
        chat_id INTEGER,
        score INTEGER,
        total INTEGER,
        created_at TEXT);
    CREATE TABLE IF NOT EXISTS tickets(
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        chat_id INTEGER,
        user_name TEXT,
        text TEXT,
        created_at TEXT,
        status TEXT DEFAULT 'open');
    """)
    columns = {column[1] for column in c.execute("PRAGMA table_info(sections)")}
    for column, kind in (("forward_chat_id", "TEXT"), ("forward_message_id", "INTEGER")):
        if column not in columns:
            c.execute(f"ALTER TABLE sections ADD COLUMN {column} {kind}")
    # تنظیمات پیش‌فرض
    for k, v in DEFAULT_SETTINGS.items():
        c.execute("INSERT OR IGNORE INTO settings(key, value) VALUES(?,?)", (k, v))
    # مالک همیشه ادمین است
    c.execute("INSERT OR IGNORE INTO admins(chat_id, name, added_at) VALUES(?,?,?)",
              (OWNER_ID, "مالک", time.strftime("%Y-%m-%d %H:%M:%S")))
    # بخش‌های پیش‌فرض ریشه‌ای
    if c.execute("SELECT COUNT(*) FROM sections").fetchone()[0] == 0:
        for i, (t, txt) in enumerate([("نحوه ورود به سایت", "راهنمای ورود به سایت به‌زودی تکمیل می‌شود."),
                                      ("نحوه شرکت در آزمون", "راهنمای شرکت در آزمون به‌زودی تکمیل می‌شود.")]):
            c.execute("INSERT INTO sections(parent_id, title, content, sort_order, created_at) VALUES(?,?,?,?,?)",
                      (None, t, txt, i, time.strftime("%Y-%m-%d %H:%M:%S")))
    conn.commit()
    conn.close()

# ================== تنظیمات ==================
def get_setting(key, default=""):
    row = q("SELECT value FROM settings WHERE key=?", (key,), "one")
    return row[0] if row and row[0] is not None else default

def set_setting(key, value):
    q("INSERT INTO settings(key, value) VALUES(?,?) "
      "ON CONFLICT(key) DO UPDATE SET value=excluded.value", (key, str(value)))

def get_setting_int(key, default=1):
    try:
        return int(get_setting(key, str(default)))
    except (ValueError, TypeError):
        return default

# ================== کاربران و ادمین‌ها ==================
def now_str():
    return time.strftime("%Y-%m-%d %H:%M:%S")

def register_user(chat_id, first_name):
    """ثبت کاربر؛ اگر جدید بود True برمی‌گرداند."""
    row = q("SELECT 1 FROM users WHERE chat_id=?", (chat_id,), "one")
    if row:
        return False
    q("INSERT INTO users(chat_id, first_name, joined_at, greeted) VALUES(?,?,?,0)",
      (chat_id, first_name or "دوست من", now_str()))
    return True

def is_admin(chat_id):
    """مالک همیشه ادمین است + جدول ادمین‌ها."""
    return chat_id == OWNER_ID or bool(q("SELECT 1 FROM admins WHERE chat_id=?", (chat_id,), "one"))

def is_owner(chat_id):
    return chat_id == OWNER_ID

def get_admins():
    return q("SELECT chat_id, name FROM admins ORDER BY chat_id", fetch="all")

def user_name(chat_id):
    row = q("SELECT first_name FROM users WHERE chat_id=?", (chat_id,), "one")
    return row[0] if row and row[0] else "دوست من"

# ================== ابزارهای عمومی ==================
def safe_int(s, default=None):
    try:
        return int(s)
    except (ValueError, TypeError):
        return default

def escape_cb(s):
    """اطمینان از کوتاه بودن callback_data (حد 64 بایت)."""
    s = str(s)
    return s[:60]

def paginate(items, page, per=PAGE_SIZE):
    """صفحه‌بندی لیست: (آیتم‌های صفحه، کل صفحات)."""
    total = max(1, (len(items) + per - 1) // per)
    page = max(1, min(page, total))
    return items[(page - 1) * per: page * per], total, page

def pager_buttons(kind, page, total):
    """دکمه‌های صفحه بعد/قبل."""
    btns = []
    if page > 1:
        btns.append(("⬅️ قبلی", f"g:{kind}:{page - 1}"))
    if page < total:
        btns.append(("بعدی ➡️", f"g:{kind}:{page + 1}"))
    return btns

def rate_ok(chat_id):
    """محدودسازی نرخ: حداقل 0.5 ثانیه بین دو کلیک."""
    t = time.time()
    last = CB_TIMES.get(chat_id, 0)
    if t - last < 0.5:
        return False
    CB_TIMES[chat_id] = t
    return True

# ================== منوی چندسطحی بخش‌ها ==================
def child_sections(parent_id, only_active=True):
    """فهرست زیربخش‌های یک بخش."""
    if only_active:
        return q("SELECT id, title, url FROM sections WHERE parent_id IS ? AND is_active=1 "
                 "ORDER BY sort_order, id", (parent_id,), "all")
    return q("SELECT id, title, url FROM sections WHERE parent_id IS ? ORDER BY sort_order, id",
             (parent_id,), "all")

def get_section(sid):
    return q("SELECT id, parent_id, title, content, url FROM sections WHERE id=?", (sid,), "one")

def section_available(sid):
    visited = set()
    while sid is not None:
        if sid in visited:
            return False
        visited.add(sid)
        row = q("SELECT parent_id, is_active FROM sections WHERE id=?", (sid,), "one")
        if not row or not row[1]:
            return False
        sid = row[0]
    return True

def parse_message_link(text):
    parsed = urlparse(text.strip())
    if parsed.scheme not in ("http", "https") or parsed.hostname not in ("ble.ir", "www.ble.ir", "bale.ai"):
        return None
    parts = parsed.path.strip("/").split("/")
    query = parse_qs(parsed.query)
    if len(parts) == 2:
        source, message_id = parts
    elif len(parts) == 1:
        source = parts[0]
        message_id = query.get("message_id", query.get("post", [""]))[0]
    else:
        return None
    if not re.fullmatch(r"[A-Za-z][A-Za-z0-9_]*", source) or not message_id.isdigit() or int(message_id) <= 0:
        return None
    return "@" + source, int(message_id)

def save_section_forward(chat_id, sid, source, message_id):
    result = api("forwardMessage", chat_id=chat_id, from_chat_id=source, message_id=message_id)
    if not result or not result.get("ok"):
        send_message(chat_id, "❌ پیام قابل دریافت نیست. دسترسی ربات به مبدأ را بررسی کن یا خود ویدیو را اینجا فوروارد کن. تنظیم قبلی تغییر نکرد.")
        return
    q("UPDATE sections SET forward_chat_id=?, forward_message_id=?, content='', url='' WHERE id=?",
      (str(source), message_id, sid))
    STATES.pop(chat_id, None)
    send_message(chat_id, "✅ پیام برای فوروارد ذخیره شد.")
    show_section_admin(chat_id, sid)

def feature_for_callback(data):
    if data in FEATURES:
        return data
    if data == "a:supmsg":
        return "support"
    if data.startswith("g:"):
        return {"ev": "sched", "res": "res", "faq": "faq"}.get(data.split(":")[1])
    if data.startswith("f") and data[1:].isdigit():
        return "faq"
    if (data.startswith("pl") and data[2:].isdigit()) or (data.startswith("v") and data[1:].isdigit()):
        return "polls"
    if data == "q:next" or (data.startswith("q") and data[1:].isdigit()):
        return "quiz"
    return None

def section_text(sid):
    """متن نمایشی یک بخش (لینک یا محتوا)."""
    row = get_section(sid)
    if not row:
        return None, None
    sid, pid, title, content, url = row
    txt = f"📖 {title}\n"
    forward = q("SELECT forward_chat_id, forward_message_id FROM sections WHERE id=?", (sid,), "one")
    if forward and forward[0] and forward[1]:
        return txt + "\n🎬 پیام فورواردی تنظیم شده است.", None
    if url:
        txt += f"\n🔗 لینک: {url}"
    elif content:
        txt += f"\n{content}"
    else:
        txt += "\nمحتوایی برای این بخش ثبت نشده است."
    return txt, url

def menu_buttons(parent_id, for_admin=False):
    """دکمه‌های منو: زیربخش‌ها + بازگشت به والد."""
    btns = [(f"📄 {t}", escape_cb(f"s{i}")) for (i, t, u) in child_sections(parent_id, not for_admin)]
    if parent_id:
        parent = get_section(parent_id)
        btns.append(("◀️ بازگشت", escape_cb(f"p{parent[1] or 0}")))
    btns.append(("🏠 منوی اصلی", "menu"))
    return btns

def open_section(chat_id, sid, message_id=None):
    """نمایش یک بخش (بدون سلام؛ فقط ناوبری)."""
    if not is_admin(chat_id) and not section_available(sid):
        send_message(chat_id, "این بخش غیرفعال است یا یافت نشد.")
        return
    txt, _ = section_text(sid)
    row = get_section(sid)
    pid = row[1] if row else 0
    kb = make_keyboard(menu_buttons(sid))
    forward = q("SELECT forward_chat_id, forward_message_id FROM sections WHERE id=?", (sid,), "one")
    if forward and forward[0] and forward[1]:
        result = api("forwardMessage", chat_id=chat_id, from_chat_id=forward[0], message_id=forward[1])
        if not result or not result.get("ok"):
            send_message(chat_id, "❌ ارسال ویدیو/پیام ممکن نشد؛ لطفاً به پشتیبانی اطلاع بده.", kb)
            return
    if message_id:
        edit_message(chat_id, message_id, txt or "این بخش یافت نشد.", kb)
    else:
        send_message(chat_id, txt or "این بخش یافت نشد.", kb)

def show_menu(chat_id, message_id=None, greet=False, name=None):
    """منوی اصلی؛ فقط بار اول (greet=True) خوش‌آمد می‌گوید."""
    text = "🎓 مدرسه فانوس" if not greet else (
        f"سلام {name} عزیز! 🌸\nبه مدرسه فانوس خوش آمدی! 🎓\n\nاز منوی زیر انتخاب کن:")
    btns = [(f"📄 {t}", escape_cb(f"s{i}")) for (i, t, u) in child_sections(None)]
    # امکانات آموزشی ثابت منوی اصلی
    btns += [
        ("📅 برنامه کلاسی", "sched"),
        ("📚 جزوه‌ها و فایل‌ها", "res"),
        ("❓ سوالات متداول", "faq"),
        ("🧪 آزمونک (نظرسنجی)", "polls"),
        ("🏆 آزمون تعیین سطح", "quiz"),
        ("🙋 پشتیبانی / ارتباط با ما", "support"),
        ("👤 پروفایل من", "profile"),
    ]
    btns = [button for button in btns if button[1] not in FEATURES or get_setting("feature_" + button[1], "1") == "1"]
    if is_admin(chat_id):
        btns.append(("🛠 پنل مدیریت", "a:panel"))
    kb = make_keyboard(btns)
    if message_id:
        edit_message(chat_id, message_id, text, kb)
    else:
        send_message(chat_id, text, kb)

def tree_text(parent_id=None, depth=0):
    """پیش‌نمایش درختی بخش‌ها به‌صورت متن."""
    rows = q("SELECT id, title, is_active FROM sections WHERE parent_id IS ? ORDER BY sort_order, id",
             (parent_id,), "all")
    lines = []
    for i, (sid, title, act) in enumerate(rows):
        mark = "🟢" if act else "⚪️"
        lines.append("  " * depth + f"└ {mark} {title} (#{sid})")
        lines += tree_text(sid, depth + 1)
    return lines

# ================== پنل مدیریت ==================
def admin_panel(chat_id):
    """منوی اصلی پنل مدیریت."""
    if not is_admin(chat_id):
        return
    kb = make_keyboard([
        ("📢 ارسال همگانی", "a:broadcast"), ("📢 ارسال به ادمین‌ها", "a:broadcastA"),
        ("🗂 مدیریت بخش‌ها", "a:secs"), ("📅 برنامه کلاسی", "a:events"),
        ("📚 جزوه‌ها", "a:res"), ("❓ FAQ", "a:faq"),
        ("🧪 نظرسنجی‌ها", "a:polls"), ("🏆 آزمون تعیین سطح", "a:quiz"),
        ("🎫 تیکت‌ها", "a:tickets"), ("📊 آمار", "a:stats"),
        ("👥 ادمین‌ها", "a:admins"), ("⚙️ تنظیمات", "a:settings"),
        ("🟢 فعال / غیرفعال کردن امکانات", "a:features"),
        ("🏠 منوی اصلی", "menu"),
    ])
    send_message(chat_id, "🛠 پنل مدیریت مدرسه فانوس\nیک گزینه انتخاب کن:", kb)

def section_admin_buttons():
    """دکمه‌های مدیریت بخش‌ها (شامل مخفی‌ها)."""
    btns = []
    for sid, title in q("SELECT id, title FROM sections WHERE parent_id IS NULL ORDER BY sort_order, id", fetch="all"):
        btns.append((f"📄 {title}", escape_cb(f"a:sec:{sid}")))
    btns += [("➕ بخش اصلی جدید", "a:addsec"), ("🏠 منوی اصلی", "menu")]
    return btns

def one_section_admin_buttons(sid):
    """دکمه‌های مدیریت یک بخش مشخص."""
    row = get_section(sid)
    if not row:
        return [("🏠 منوی اصلی", "menu")]
    sid, pid, title, content, url = row
    act = q("SELECT is_active FROM sections WHERE id=?", (sid,), "one")[0]
    btns = [
        ("➕ افزودن زیربخش", f"a:addsub:{sid}"),
        ("✏️ ویرایش عنوان", f"a:editt:{sid}"),
        ("📝 ویرایش متن", f"a:editc:{sid}"),
        ("🔗 ویرایش لینک", f"a:editu:{sid}"),
        ("🎬 تنظیم پیام / ویدیوی فورواردی", f"a:editf:{sid}"),
        ("⬆️ بالا", f"a:up:{sid}"), ("⬇️ پایین", f"a:down:{sid}"),
        (("🔵 فعال ✅" if act else "⚪️ مخفی ❌"), f"a:toggle:{sid}"),
        ("👁 نمایش", escape_cb(f"s{sid}")),
        ("🗑 حذف", f"a:del:{sid}"),
    ]
    if pid:
        btns.append(("◀️ بازگشت به والد", f"a:sec:{pid}"))
    else:
        btns.append(("◀️ بازگشت", "a:secs"))
    btns.append(("🏠 منوی اصلی", "menu"))
    return btns

def show_section_admin(chat_id, sid, message_id=None):
    txt, _ = section_text(sid)
    row = get_section(sid)
    hidden = " (مخفی)" if row and not q("SELECT is_active FROM sections WHERE id=?", (sid,), "one")[0] else ""
    kids = len(child_sections(sid, False))
    text = (txt or "یافت نشد") + f"\n\n🔧 مدیریت بخش{hidden} — زیربخش‌ها: {kids}"
    kb = make_keyboard(one_section_admin_buttons(sid))
    if message_id:
        edit_message(chat_id, message_id, text, kb)
    else:
        send_message(chat_id, text, kb)

def move_section(sid, delta):
    """جابه‌جایی ترتیب یک بخش در سطح خودش."""
    row = get_section(sid)
    if not row:
        return
    pid = row[1]
    sibs = q("SELECT id FROM sections WHERE parent_id IS ? ORDER BY sort_order, id", (pid,), "all")
    ids = [r[0] for r in sibs]
    i = ids.index(sid)
    j = max(0, min(len(ids) - 1, i + delta))
    if i == j:
        return
    ids[i], ids[j] = ids[j], ids[i]
    for pos, sid2 in enumerate(ids):
        q("UPDATE sections SET sort_order=? WHERE id=?", (pos, sid2))

def delete_section_cascade(sid):
    """حذف آبشاری یک بخش و همه زیربخش‌هایش."""
    count = 0
    def rec(pid):
        nonlocal count
        for (cid,) in q("SELECT id FROM sections WHERE parent_id=?", (pid,), "all"):
            rec(cid)
            count += 1
    rec(sid)
    q("DELETE FROM sections WHERE id=?", (sid,))
    count += 1
    return count

def admins_panel(chat_id, message_id=None):
    """مدیریت ادمین‌ها — فقط مالک."""
    rows = get_admins()
    text = "👥 ادمین‌های ربات:\n" + "\n".join(
        f"• {name} ({cid})" + (" 👑 مالک" if cid == OWNER_ID else "") for cid, name in rows)
    btns = []
    if is_owner(chat_id):
        for cid, name in rows:
            if cid != OWNER_ID:
                btns.append((f"❌ {name}", f"a:rma:{cid}"))
        btns.append(("➕ افزودن ادمین", "a:addadm"))
    btns.append(("◀️ بازگشت", "a:panel"))
    kb = make_keyboard(btns)
    if message_id:
        edit_message(chat_id, message_id, text, kb)
    else:
        send_message(chat_id, text, kb)

# ================== برنامه کلاسی (رویدادها) ==================
def upcoming_events(days=7):
    """رویدادهای امروز تا {days} روز بعد."""
    today = datetime.date.today()
    limit = today + datetime.timedelta(days=days)
    rows = q("SELECT id, title, event_date, event_time, kind FROM events "
             "WHERE event_date>=? AND event_date<=? ORDER BY event_date, event_time",
             (today.isoformat(), limit.isoformat()), "all")
    return rows

def events_text(rows):
    if not rows:
        return "رویدادی برای این بازه ثبت نشده است. 🌱"
    lines = []
    for eid, title, d, t, kind in rows:
        try:
            wd = ["دوشنبه", "سه‌شنبه", "چهارشنبه", "پنجشنبه", "جمعه", "شنبه", "یکشنبه"][
                datetime.date.fromisoformat(d).weekday()]
        except ValueError:
            wd = ""
        lines.append(f"{kind} 📌 {title}\n📅 {d} {wd}{' ⏰ ' + t if t else ''}")
    return "\n\n".join(lines)

def events_panel(chat_id, message_id=None):
    rows = q("SELECT id, title, event_date, kind FROM events ORDER BY event_date", fetch="all")
    text = "📅 مدیریت برنامه کلاسی\n" + ("\n".join(f"• [{k}] {t} — {d}" for _, t, d, k in rows) or "رویدادی نیست.")
    kb = make_keyboard([("➕ افزودن رویداد", "a:addev"), ("🔔 ارسال یادآوری", "a:remind")] +
                       [(f"🗑 {t}", f"a:delev:{i}") for i, t, _, _ in rows] +
                       [("◀️ بازگشت", "a:panel"), ("🏠 منوی اصلی", "menu")])
    if message_id:
        edit_message(chat_id, message_id, text, kb)
    else:
        send_message(chat_id, text, kb)

# ================== جزوه‌ها و فایل‌ها ==================
def resources_panel(chat_id, message_id=None):
    rows = q("SELECT id, title FROM resources ORDER BY id DESC", fetch="all")
    text = "📚 مدیریت جزوه‌ها و فایل‌ها\n" + ("\n".join(f"• {t}" for _, t in rows) or "موردی نیست.")
    kb = make_keyboard([("➕ افزودن جزوه", "a:addres")] +
                       [(f"🗑 {t}", f"a:delres:{i}") for i, t in rows] +
                       [("◀️ بازگشت", "a:panel"), ("🏠 منوی اصلی", "menu")])
    if message_id:
        edit_message(chat_id, message_id, text, kb)
    else:
        send_message(chat_id, text, kb)

def show_resources(chat_id, message_id=None, page=1):
    rows = q("SELECT id, title, url, description FROM resources ORDER BY id DESC", fetch="all")
    items, total, page = paginate(rows, page)
    btns = [(f"📚 {t}", u, True) for _, t, u, _ in items]
    btns += pager_buttons("res", page, total)
    btns.append(("🏠 منوی اصلی", "menu"))
    text = "📚 جزوه‌ها و فایل‌های آموزشی (صفحه {} از {})\n\n{}".format(
        page, total, "\n".join(f"• {t}" + (f" — {d}" if d else "") for _, t, _, d in items) or "فعلاً جزوه‌ای ثبت نشده است.")
    kb = make_keyboard(btns)
    if message_id:
        edit_message(chat_id, message_id, text, kb)
    else:
        send_message(chat_id, text, kb)

# ================== سوالات متداول (FAQ) ==================
def show_faq(chat_id, message_id=None, page=1):
    rows = q("SELECT id, question, answer FROM faqs ORDER BY id", fetch="all")
    items, total, page = paginate(rows, page)
    btns = [(f"❓ {qq[:35]}", escape_cb(f"f{i}")) for i, qq, _ in items]
    btns += pager_buttons("faq", page, total)
    btns.append(("🏠 منوی اصلی", "menu"))
    text = "❓ سوالات متداول (صفحه {} از {})\n\nروی هر سوال بزن تا جوابش را ببینی.".format(page, total)
    kb = make_keyboard(btns)
    if message_id:
        edit_message(chat_id, message_id, text, kb)
    else:
        send_message(chat_id, text, kb)

def faq_admin_panel(chat_id, message_id=None, page=1):
    rows = q("SELECT id, question FROM faqs ORDER BY id", fetch="all")
    items, total, page = paginate(rows, page)
    kb = make_keyboard([("➕ افزودن سوال", "a:addfaq")] +
                       [(f"🗑 {qq[:30]}", f"a:delfaq:{i}") for i, qq in items] +
                       pager_buttons("afaq", page, total) +
                       [("◀️ بازگشت", "a:panel"), ("🏠 منوی اصلی", "menu")])
    if message_id:
        edit_message(chat_id, message_id, "❓ مدیریت FAQ", kb)
    else:
        send_message(chat_id, "❓ مدیریت FAQ", kb)

# ================== نظرسنجی (آزمونک) ==================
def show_polls(chat_id, message_id=None):
    rows = q("SELECT id, question FROM polls ORDER BY id DESC", fetch="all")
    if not rows:
        kb = make_keyboard([("🏠 منوی اصلی", "menu")])
        text = "🧪 فعلاً نظرسنجی فعالی وجود ندارد."
    else:
        kb = make_keyboard([(f"🧪 {qq[:40]}", escape_cb(f"pl{i}")) for i, qq in rows] +
                           [("🏠 منوی اصلی", "menu")])
        text = "🧪 آزمونک‌ها — روی هر نظرسنجی بزن:"
    if message_id:
        edit_message(chat_id, message_id, text, kb)
    else:
        send_message(chat_id, text, kb)

def show_poll(chat_id, poll_id, message_id=None):
    poll = q("SELECT question FROM polls WHERE id=?", (poll_id,), "one")
    if not poll:
        return show_polls(chat_id, message_id)
    opts = q("SELECT id, text, votes FROM poll_options WHERE poll_id=? ORDER BY id", (poll_id,), "all")
    voted = q("SELECT option_id FROM poll_votes WHERE poll_id=? AND chat_id=?",
              (poll_id, chat_id), "one")
    tvotes = sum(v for _, _, v in opts) or 1
    if voted:  # نمایش نتایج با نوار درصدی
        lines = []
        for oid, txt, v in opts:
            pct = round(v * 100 / tvotes)
            bar = "▇" * (pct // 5)
            mark = " ✅" if oid == voted[0] else ""
            lines.append(f"{txt}{mark}\n{bar} {pct}%")
        text = f"🧪 {poll[0]}\n\n" + "\n".join(lines) + f"\n\nمجموع آرا: {tvotes} — رأی تو ثبت شد. 🙏"
        kb = make_keyboard([("🏠 منوی اصلی", "menu")])
    else:
        text = f"🧪 {poll[0]}\n\nیک گزینه انتخاب کن:"
        kb = make_keyboard([(txt, escape_cb(f"v{oid}")) for oid, txt, _ in opts] +
                           [("🏠 منوی اصلی", "menu")])
    if message_id:
        edit_message(chat_id, message_id, text, kb)
    else:
        send_message(chat_id, text, kb)

def cast_vote(chat_id, option_id):
    """ثبت رأی کاربر (هر کاربر یک رأی در هر نظرسنجی)."""
    opt = q("SELECT poll_id, text FROM poll_options WHERE id=?", (option_id,), "one")
    if not opt:
        return
    poll_id, otext = opt
    try:
        q("INSERT INTO poll_votes(poll_id, chat_id, option_id) VALUES(?,?,?)",
          (poll_id, chat_id, option_id))
        q("UPDATE poll_options SET votes=votes+1 WHERE id=?", (option_id,))
        answer_callback_answer = "رأی تو ثبت شد! ✅"
    except sqlite3.IntegrityError:
        answer_callback_answer = "شما قبلاً در این نظرسنجی رأی داده‌اید. ⚠️"
    show_poll(chat_id, poll_id)
    return answer_callback_answer

def polls_admin_panel(chat_id, message_id=None):
    rows = q("SELECT id, question FROM polls ORDER BY id DESC", fetch="all")
    kb = make_keyboard([("➕ نظرسنجی جدید", "a:addpoll")] +
                       [(f"📊 {qq[:32]}", f"a:pollr:{i}") for i, qq in rows] +
                       [(f"🗑 {qq[:28]}", f"a:delpoll:{i}") for i, qq in rows] +
                       [("◀️ بازگشت", "a:panel"), ("🏠 منوی اصلی", "menu")])
    if message_id:
        edit_message(chat_id, message_id, "🧪 مدیریت نظرسنجی‌ها", kb)
    else:
        send_message(chat_id, "🧪 مدیریت نظرسنجی‌ها", kb)

def poll_results_text(poll_id):
    poll = q("SELECT question FROM polls WHERE id=?", (poll_id,), "one")
    opts = q("SELECT text, votes FROM poll_options WHERE poll_id=? ORDER BY id", (poll_id,), "all")
    tv = sum(v for _, v in opts) or 1
    lines = [f"📊 نتایج نظرسنجی: {poll[0] if poll else '?'}", ""]
    for txt, v in opts:
        pct = round(v * 100 / tv)
        lines.append(f"{txt}: {'▇' * (pct // 5)} {pct}% ({v} رأی)")
    return "\n".join(lines)

# ================== آزمون تعیین سطح ==================
def start_quiz(chat_id, message_id=None):
    """شروع آزمون فعال؛ اگر سوال نبود پیام مناسب می‌دهد."""
    qq = q("SELECT id, text FROM quiz_questions ORDER BY sort_order, id", fetch="all")
    if not qq:
        kb = make_keyboard([("🏠 منوی اصلی", "menu")])
        text = "🏆 فعلاً آزمون فعالی وجود ندارد. به‌زودی اضافه می‌شود! 🌱"
        if message_id:
            edit_message(chat_id, message_id, text, kb)
        else:
            send_message(chat_id, text, kb)
        return
    STATES[chat_id] = ["quiz", {"idx": 0, "score": 0, "qs": [i for i, _ in qq]}]
    ask_quiz_question(chat_id, 0, message_id)

def ask_quiz_question(chat_id, idx, message_id=None):
    st = STATES.get(chat_id)
    if not st or st[0] != "quiz":
        return
    qid = st[1]["qs"][idx]
    row = q("SELECT text FROM quiz_questions WHERE id=?", (qid,), "one")
    if not row:
        return
    opts = q("SELECT id, text FROM quiz_options WHERE question_id=? ORDER BY id", (qid,), "all")
    text = f"🏆 آزمون تعیین سطح\nسوال {idx + 1} از {len(st[1]['qs'])}\n\n{row[0]}"
    kb = make_keyboard([(t, escape_cb(f"q{oid}")) for oid, t in opts] +
                       [("انصراف", "menu")])
    if message_id:
        edit_message(chat_id, message_id, text, kb)
    else:
        send_message(chat_id, text, kb)

def quiz_answer(chat_id, option_id):
    """بررسی جواب و نمایش نتیجه سوال."""
    st = STATES.get(chat_id)
    if not st or st[0] != "quiz":
        return
    data = st[1]
    qid = data["qs"][data["idx"]]
    opt = q("SELECT text, is_correct, question_id FROM quiz_options WHERE id=?", (option_id,), "one")
    correct_txt, correct_id = None, None
    for oid, t, ic in q("SELECT id, text, is_correct FROM quiz_options WHERE question_id=?", (qid,), "all"):
        if ic:
            correct_txt, correct_id = t, oid
    good = bool(opt and opt[1])
    if good:
        data["score"] += 1
    STATES[chat_id] = ["quiz", data]
    last = data["idx"] >= len(data["qs"]) - 1
    if last:
        finish_quiz(chat_id)
    else:
        text = ("✅ درست بود! آفرین. 🌟" if good else f"❌ اشتباه بود. جواب درست: {correct_txt}") + \
               "\n\nبرای سوال بعدی بزن:"
        send_message(chat_id, text, make_keyboard([("سوال بعدی ➡️", "q:next"), ("اتمام", "menu")]))

def finish_quiz(chat_id):
    st = STATES.pop(chat_id, None)
    if not st:
        return
    score, total = st[1]["score"], len(st[1]["qs"])
    q("INSERT INTO quiz_results(chat_id, score, total, created_at) VALUES(?,?,?,?)",
      (chat_id, score, total, now_str()))
    pct = round(score * 100 / total) if total else 0
    if pct >= 80:
        msg = "عالی بود! سطح تو پیشرفته است. 🌟"
    elif pct >= 50:
        msg = "خوب بود! با کمی تمرین بهتر می‌شوی. 💪"
    else:
        msg = "شروع خوبی بود! در کلاس‌های ما پیشرفت می‌کنی. 🌱"
    send_message(chat_id, f"🏁 آزمون تمام شد!\nنمره تو: {score} از {total} ({pct}%)\n\n{msg}",
                 make_keyboard([("🏠 منوی اصلی", "menu")]))

def quiz_admin_panel(chat_id, message_id=None):
    nq = q("SELECT COUNT(*) FROM quiz_questions", fetch="one")[0]
    kb = make_keyboard([("➕ افزودن سوال", "a:addqq"), ("🗑 پاک کردن همه سوالات", "a:clrquiz"),
                        ("👤 نتایج کاربران", "a:quizres"), ("◀️ بازگشت", "a:panel"), ("🏠 منوی اصلی", "menu")])
    text = f"🏆 مدیریت آزمون تعیین سطح\nتعداد سوالات فعلی: {nq}"
    if message_id:
        edit_message(chat_id, message_id, text, kb)
    else:
        send_message(chat_id, text, kb)

# ================== پشتیبانی و تیکت‌ها ==================
def support_panel(chat_id, message_id=None):
    uname = get_setting("support_username")
    phone = get_setting("support_phone")
    text = ("🙋 پشتیبانی مدرسه فانوس\n\n"
            f"آیدی پشتیبانی: @{uname}\nتلفن: {phone}\n\n"
            "اگر سوال یا مشکلی داری، روی «✍️ پیام به پشتیبانی» بزن و پیامت را بنویس؛ "
            "برای مربی‌ها ارسال می‌شود.")
    kb = make_keyboard([("✍️ پیام به پشتیبانی", "a:supmsg"),
                        (f"💬 گفتگو با پشتیبانی", f"https://ble.ir/{uname}", True),
                        ("🏠 منوی اصلی", "menu")])
    if message_id:
        edit_message(chat_id, message_id, text, kb)
    else:
        send_message(chat_id, text, kb)

def forward_to_admins(user_id, user_n, text):
    """ارسال پیام کاربر به همه ادمین‌ها + ثبت تیکت."""
    tid = q("INSERT INTO tickets(chat_id, user_name, text, created_at) VALUES(?,?,?,?)",
            (user_id, user_n, text, now_str()), "one")  # q با fetch one آخرین id؟
    return tid

def notify_admins_new_ticket(user_id, user_n, text):
    q("INSERT INTO tickets(chat_id, user_name, text, created_at, status) VALUES(?,?,?,?, 'open')",
      (user_id, user_n, text, now_str()))
    header = f"🎫 پیام جدید از پشتیبانی\nاز: {user_n} (id={user_id})\n\n{text}\n\nبرای پاسخ دکمه زیر را بزن."
    for aid, _ in get_admins():
        send_message(aid, header, make_keyboard([("↩️ پاسخ به کاربر", f"rpl{user_id}")]))

def tickets_panel(chat_id, message_id=None):
    rows = q("SELECT id, chat_id, user_name, substr(text,1,30), status FROM tickets ORDER BY id DESC LIMIT 15", fetch="all")
    text = "🎫 آخرین تیکت‌ها:"
    btns = []
    for tid, uid, un, tx, status in rows:
        icon = "🟢" if status == "open" else "🔵"
        text += f"\n{icon} #{tid} {un}: {tx}"
        btns.append((f"↩️ #{tid}", f"a:tkt:{tid}"))
    btns += [("🧹 بستن همه بازها", "a:tkclose"), ("◀️ بازگشت", "a:panel"), ("🏠 منوی اصلی", "menu")]
    kb = make_keyboard(btns)
    if message_id:
        edit_message(chat_id, message_id, text, kb)
    else:
        send_message(chat_id, text, kb)

# ================== پروفایل و آمار ==================
def profile_text(chat_id):
    row = q("SELECT first_name, joined_at FROM users WHERE chat_id=?", (chat_id,), "one")
    name = row[0] if row else user_name(chat_id)
    joined = row[1] if row else "—"
    votes = q("SELECT COUNT(*) FROM poll_votes WHERE chat_id=?", (chat_id,), "one")[0]
    quizzes = q("SELECT COUNT(*) FROM quiz_results WHERE chat_id=?", (chat_id,), "one")[0]
    best = q("SELECT MAX(score) FROM quiz_results WHERE chat_id=?", (chat_id,), "one")[0]
    return (f"👤 پروفایل من\n\nنام: {name}\nشناسه: {chat_id}\n"
            f"تاریخ عضویت: {joined}\nنظرسنجی‌های شرکت‌کرده: {votes}\n"
            f"آزمون‌های داده‌شده: {quizzes}" + (f"\nبهترین نمره: {best}" if best is not None else ""))

def stats_text():
    users = q("SELECT COUNT(*) FROM users", fetch="one")[0]
    admins = len(get_admins())
    secs = q("SELECT COUNT(*) FROM sections", fetch="one")[0]
    open_tk = q("SELECT COUNT(*) FROM tickets WHERE status='open'", fetch="one")[0]
    up = len(upcoming_events(30))
    today = q("SELECT COUNT(*) FROM users WHERE joined_at LIKE ?",
              (time.strftime("%Y-%m-%d") + "%",), "one")[0]
    return (f"📊 آمار ربات مدرسه فانوس\n\n👥 کاربران: {users}\n🆕 عضو امروز: {today}\n"
            f"🛡 ادمین‌ها: {admins}\n🗂 بخش‌ها: {secs}\n🎫 تیکت باز: {open_tk}\n"
            f"📅 رویدادهای ۳۰ روز آینده: {up}")

# (اصلاح) ارسال پیام کاربر به همه ادمین‌ها + ثبت تیکت
def forward_to_admins(user_id, user_n, text):
    notify_admins_new_ticket(user_id, user_n, text)

# ================== ارسال همگانی ==================
def confirm_broadcast(chat_id, text, to_admins=False):
    STATES[chat_id] = ["bcast", (text, to_admins)]
    kb = make_keyboard([("✅ ارسال کن", "a:bok"), ("❌ لغو", "a:panel")])
    send_message(chat_id, f"📢 متن پیام برای ارسال:\n\n{text}\n\nتأیید می‌کنی؟", kb)

def do_broadcast(chat_id):
    st = STATES.pop(chat_id, None)
    if not st:
        return admin_panel(chat_id)
    text, to_admins = st[1]
    if to_admins:
        targets = [c for c, _ in get_admins()]
    else:
        targets = [r[0] for r in q("SELECT chat_id FROM users", fetch="all")]
    ok = fail = 0
    for uid in targets:
        r = send_message(uid, text)
        if r and r.get("ok"):
            ok += 1
        else:
            fail += 1
        time.sleep(0.05)  # جلوگیری از فشار به سرور
    send_message(chat_id, f"✅ ارسال همگانی تمام شد.\nموفق: {ok} | ناموفق (مسدود/خطا): {fail}")
    admin_panel(chat_id)

def send_reminder():
    """یادآوری رویدادهای ۷ روز آینده به همه کاربران."""
    rows = upcoming_events(7)
    text = "🔔 یادآوری برنامه هفته (۷ روز آینده)\n\n" + events_text(rows)
    targets = [r[0] for r in q("SELECT chat_id FROM users", fetch="all")]
    ok = fail = 0
    for uid in targets:
        if send_message(uid, text) and True:
            ok += 1
        else:
            fail += 1
        time.sleep(0.05)
    return ok, fail

# ================== مسیریابی کلیک‌های شیشه‌ای ==================
def handle_callback(chat_id, data, callback_id, message_id, first_name):
    """پردازش کلیک روی دکمه‌های شیشه‌ای با طرح کدهای کوتاه (<=64 بایت)."""
    if ((data.startswith("a:") and data != "a:supmsg") or data.startswith(("g:afaq:", "rpl"))) and not is_admin(chat_id):
        answer_callback(callback_id, "⛔️ دسترسی ندارید.")
        return
    feature = feature_for_callback(data)
    if feature and get_setting("feature_" + feature, "1") != "1":
        answer_callback(callback_id, "این بخش غیرفعال است.")
        return
    if not rate_ok(chat_id):
        answer_callback(callback_id, "کمی آهسته‌تر! ⏳")
        return
    answer_callback(callback_id)

    # --- ناوبری منو ---
    if data == "menu":
        STATES.pop(chat_id, None)
        show_menu(chat_id, message_id, greet=False)
    elif data.startswith("s") and data[1:].isdigit():
        open_section(chat_id, int(data[1:]), message_id)
    elif data.startswith("p") and data[1:].isdigit():
        pid = int(data[1:])
        if pid:
            open_section(chat_id, pid, message_id)
        else:
            show_menu(chat_id, message_id)

    # --- امکانات کاربری ---
    elif data == "sched":
        text = "📅 برنامه هفته (۷ روز آینده)\n\n" + events_text(upcoming_events(7))
        kb = make_keyboard([("🗓 همه رویدادها", "g:ev:1"), ("🏠 منوی اصلی", "menu")])
        edit_message(chat_id, message_id, text, kb)
    elif data == "res":
        show_resources(chat_id, message_id)
    elif data == "faq":
        show_faq(chat_id, message_id)
    elif data == "polls":
        show_polls(chat_id, message_id)
    elif data == "quiz":
        start_quiz(chat_id, message_id)
    elif data == "support":
        support_panel(chat_id, message_id)
    elif data == "profile":
        kb = make_keyboard([("🏠 منوی اصلی", "menu")])
        edit_message(chat_id, message_id, profile_text(chat_id), kb)
    elif data == "a:supmsg":
        STATES[chat_id] = ["ticket", None]
        send_message(chat_id, "✍️ پیامت را بنویس تا برای پشتیبانی ارسال شود:")
    elif data.startswith("f") and data[1:].isdigit():  # نمایش جواب FAQ
        row = q("SELECT question, answer FROM faqs WHERE id=?", (int(data[1:]),), "one")
        if row:
            edit_message(chat_id, message_id, f"❓ {row[0]}\n\n✅ {row[1]}",
                         make_keyboard([("◀️ بازگشت به سوالات", "faq"), ("🏠 منوی اصلی", "menu")]))
    elif data.startswith("pl") and data[2:].isdigit():  # باز کردن یک نظرسنجی
        show_poll(chat_id, int(data[2:]), message_id)
    elif data.startswith("v") and data[1:].isdigit():  # رأی
        cast_vote(chat_id, int(data[1:]))
    elif data == "q:next":  # سوال بعدی آزمون
        st = STATES.get(chat_id)
        if st and st[0] == "quiz":
            ask_quiz_question(chat_id, st[1]["idx"] + 1)
    elif data.startswith("q") and data[1:].isdigit():  # جواب آزمون
        st = STATES.get(chat_id)
        if st and st[0] == "quiz":
            quiz_answer(chat_id, int(data[1:]))
    elif data.startswith("g:"):  # صفحه‌بندی g:{kind}:{page}
        _, kind, p = data.split(":", 2)
        page = safe_int(p, 1)
        if kind == "faq":
            show_faq(chat_id, message_id, page)
        elif kind == "res":
            show_resources(chat_id, message_id, page)
        elif kind == "ev":
            rows = q("SELECT id, title, event_date, event_time, kind FROM events "
                     "WHERE event_date>=? ORDER BY event_date, event_time",
                     (datetime.date.today().isoformat(),), "all")
            items, total, page = paginate(rows, page)
            btns = pager_buttons("ev", page, total) + [("◀️ برنامه هفته", "sched"), ("🏠 منوی اصلی", "menu")]
            edit_message(chat_id, message_id,
                         f"🗓 همه رویدادها (صفحه {page} از {total})\n\n" + events_text(items),
                         make_keyboard(btns))
        elif kind == "afaq":
            faq_admin_panel(chat_id, message_id, page)

    # --- پنل مدیریت ---
    elif data == "a:panel":
        STATES.pop(chat_id, None)
        admin_panel(chat_id)
    elif data == "a:features" or data.startswith("a:feature:"):
        if data.startswith("a:feature:"):
            feature = data.split(":", 2)[2]
            if feature not in FEATURES:
                return
            set_setting("feature_" + feature, "0" if get_setting("feature_" + feature, "1") == "1" else "1")
        buttons = [(f"{'🟢' if get_setting('feature_' + key, '1') == '1' else '⚪️'} {title}", f"a:feature:{key}")
                   for key, title in FEATURES.items()]
        buttons.append(("◀️ پنل مدیریت", "a:panel"))
        edit_message(chat_id, message_id, "برای تغییر وضعیت هر قابلیت، روی آن بزن:", make_keyboard(buttons))
    elif data == "a:broadcast":
        STATES[chat_id] = ["btext", False]
        send_message(chat_id, "📢 متن پیام همگانی را بفرست:")
    elif data == "a:broadcastA":
        STATES[chat_id] = ["btext", True]
        send_message(chat_id, "📢 متن پیام برای ادمین‌ها را بفرست:")
    elif data == "a:bok":
        do_broadcast(chat_id)
    elif data == "a:secs":
        kb = make_keyboard(section_admin_buttons())
        edit_message(chat_id, message_id, "🗂 مدیریت بخش‌ها — یک بخش را انتخاب کن:", kb)
    elif data == "a:addsec":
        STATES[chat_id] = ["sec_title", [None]]
        send_message(chat_id, "➕ عنوان بخش اصلی جدید را بفرست:")
    elif data.startswith("a:addsub:"):
        sid = safe_int(data.split(":")[2])
        STATES[chat_id] = ["sec_title", [sid]]
        send_message(chat_id, "➕ عنوان زیربخش جدید را بفرست:")
    elif data.startswith("a:sec:"):
        show_section_admin(chat_id, safe_int(data.split(":")[2]), message_id)
    elif data.startswith("a:editt:"):
        STATES[chat_id] = ["sec_editt", safe_int(data.split(":")[2])]
        send_message(chat_id, "✏️ عنوان جدید را بفرست:")
    elif data.startswith("a:editc:"):
        STATES[chat_id] = ["sec_editc", safe_int(data.split(":")[2])]
        send_message(chat_id, "📝 متن جدید را بفرست (برای حذف متن «-» بفرست):")
    elif data.startswith("a:editu:"):
        STATES[chat_id] = ["sec_editu", safe_int(data.split(":")[2])]
        send_message(chat_id, "🔗 لینک جدید را بفرست (برای حذف «-» بفرست):")
    elif data.startswith("a:editf:"):
        STATES[chat_id] = ["sec_editf", safe_int(data.split(":")[2])]
        send_message(chat_id, "🎬 لینک پیام بله (با شناسه پیام) را بفرست، یا ویدیو/پیام موردنظر را همین‌جا فوروارد کن.\nبرای حذف «-» و برای انصراف /cancel بفرست.\nربات باید به پیام مبدأ دسترسی داشته باشد.")
    elif data.startswith("a:up:"):
        move_section(safe_int(data.split(":")[2]), -1)
        show_section_admin(chat_id, safe_int(data.split(":")[2]), message_id)
    elif data.startswith("a:down:"):
        move_section(safe_int(data.split(":")[2]), +1)
        show_section_admin(chat_id, safe_int(data.split(":")[2]), message_id)
    elif data.startswith("a:toggle:"):
        sid = safe_int(data.split(":")[2])
        q("UPDATE sections SET is_active=1-is_active WHERE id=?", (sid,))
        show_section_admin(chat_id, sid, message_id)
    elif data.startswith("a:del:"):  # هشدار + تأیید حذف آبشاری
        sid = safe_int(data.split(":")[2])
        kids = count_descendants(sid)
        kb = make_keyboard([("✅ بله، حذف کن", f"a:delok:{sid}"), ("❌ انصراف", f"a:sec:{sid}")])
        edit_message(chat_id, message_id,
                     f"🗑 حذف این بخش و {kids} زیربخش آن؟\nاین عمل بازگشت‌پذیر نیست!",
                     kb)
    elif data.startswith("a:delok:"):
        sid = safe_int(data.split(":")[2])
        n = delete_section_cascade(sid)
        send_message(chat_id, f"🗑 {n} بخش حذف شد.")
        edit_message(chat_id, message_id, "🗂 مدیریت بخش‌ها:", make_keyboard(section_admin_buttons()))
    elif data == "a:events":
        events_panel(chat_id, message_id)
    elif data == "a:addev":
        STATES[chat_id] = ["ev_title", None]
        send_message(chat_id, "➕ عنوان رویداد را بفرست:")
    elif data.startswith("a:delev:"):
        q("DELETE FROM events WHERE id=?", (safe_int(data.split(":")[2]),))
        events_panel(chat_id)
    elif data == "a:remind":
        ok, fail = send_reminder()
        send_message(chat_id, f"🔔 یادآوری ارسال شد.\nموفق: {ok} | ناموفق: {fail}")
        events_panel(chat_id)
    elif data == "a:res":
        resources_panel(chat_id, message_id)
    elif data == "a:addres":
        STATES[chat_id] = ["res_title", None]
        send_message(chat_id, "➕ عنوان جزوه را بفرست:")
    elif data.startswith("a:delres:"):
        q("DELETE FROM resources WHERE id=?", (safe_int(data.split(":")[2]),))
        resources_panel(chat_id)
    elif data == "a:faq":
        faq_admin_panel(chat_id, message_id)
    elif data == "a:addfaq":
        STATES[chat_id] = ["faq_q", None]
        send_message(chat_id, "➕ متن سوال را بفرست:")
    elif data.startswith("a:delfaq:"):
        q("DELETE FROM faqs WHERE id=?", (safe_int(data.split(":")[2]),))
        faq_admin_panel(chat_id)
    elif data == "a:polls":
        polls_admin_panel(chat_id, message_id)
    elif data == "a:addpoll":
        STATES[chat_id] = ["poll_q", []]
        send_message(chat_id, "➕ سوال نظرسنجی را بفرست:\n(بعدش گزینه‌ها را یکی‌یکی بفرست، در پایان «تمام» را بفرست)")
    elif data.startswith("a:pollr:"):
        pid = safe_int(data.split(":")[2])
        edit_message(chat_id, message_id, poll_results_text(pid),
                     make_keyboard([("◀️ بازگشت", "a:polls"), ("🏠 منوی اصلی", "menu")]))
    elif data.startswith("a:delpoll:"):
        pid = safe_int(data.split(":")[2])
        q("DELETE FROM poll_votes WHERE poll_id=?", (pid,))
        q("DELETE FROM poll_options WHERE poll_id=?", (pid,))
        q("DELETE FROM polls WHERE id=?", (pid,))
        polls_admin_panel(chat_id)
    elif data == "a:quiz":
        quiz_admin_panel(chat_id, message_id)
    elif data == "a:addqq":
        STATES[chat_id] = ["qq_text", []]
        send_message(chat_id, "➕ متن سوال آزمون را بفرست:")
    elif data == "a:clrquiz":
        q("DELETE FROM quiz_options")
        q("DELETE FROM quiz_questions")
        quiz_admin_panel(chat_id)
    elif data == "a:quizres":
        rows = q("SELECT user_name, chat_id, score, total FROM quiz_results r JOIN users u ON u.chat_id=r.chat_id "
                 "ORDER BY r.created_at DESC LIMIT 15", fetch="all")
        text = "👤 آخرین نتایج آزمون‌ها:\n" + ("\n".join(f"• {n} ({c}): {s}/{t}" for n, c, s, t in rows) or "هنوز نتیجه‌ای نیست.")
        edit_message(chat_id, message_id, text, make_keyboard([("◀️ بازگشت", "a:quiz")]))
    elif data == "a:tickets":
        tickets_panel(chat_id, message_id)
    elif data.startswith("a:tkt:"):
        tid = safe_int(data.split(":")[2])
        row = q("SELECT chat_id, user_name, text, status FROM tickets WHERE id=?", (tid,), "one")
        if row:
            q("UPDATE tickets SET status='answered' WHERE id=?", (tid,))
            STATES[chat_id] = ["reply", row[0]]
            send_message(chat_id, f"✍️ پاسخ به {row[1]} (id={row[0]}) برای تیکت #{tid}:\n\n«{row[2]}»\n\nپاسخت را بنویس:")
    elif data == "a:tkclose":
        q("UPDATE tickets SET status='closed' WHERE status='open'")
        tickets_panel(chat_id)
    elif data.startswith("rpl") and data[3:].isdigit():  # ادمین می‌خواهد پاسخ دهد
        STATES[chat_id] = ["reply", int(data[3:])]
        send_message(chat_id, "✍️ پاسخت را بنویس:")
    elif data == "a:stats":
        edit_message(chat_id, message_id, stats_text(), make_keyboard([("◀️ بازگشت", "a:panel")]))
    elif data == "a:admins":
        admins_panel(chat_id, message_id)
    elif data == "a:addadm":
        if not is_owner(chat_id):
            send_message(chat_id, "⛔️ فقط مالک می‌تواند ادمین اضافه کند.")
        else:
            STATES[chat_id] = ["addadm", None]
            send_message(chat_id, "➕ شناسه عددی (chat_id) ادمین جدید را بفرست:")
    elif data.startswith("a:rma:"):
        if not is_owner(chat_id):
            send_message(chat_id, "⛔️ فقط مالک می‌تواند ادمین حذف کند.")
        else:
            aid = safe_int(data.split(":")[2])
            if aid == OWNER_ID:
                send_message(chat_id, "👑 مالک قابل حذف نیست.")
            else:
                q("DELETE FROM admins WHERE chat_id=?", (aid,))
                send_message(chat_id, "🗑 ادمین حذف شد.")
        admins_panel(chat_id)
    elif data == "a:settings":
        text = ("⚙️ تنظیمات فعلی\n\n"
                f"تعداد دکمه در هر ردیف منو: {get_setting_int('buttons_per_row', 1)}\n"
                f"آیدی پشتیبانی: @{get_setting('support_username')}\n"
                f"تلفن پشتیبانی: {get_setting('support_phone')}")
        kb = make_keyboard([("🔢 تغییر عرض منو", "a:setwidth"), ("💬 تغییر آیدی پشتیبانی", "a:setsup"),
                            ("📞 تغییر تلفن پشتیبانی", "a:setphone"),
                            ("🗂 پیش‌نمایش درخت منو", "a:tree"), ("◀️ بازگشت", "a:panel")])
        edit_message(chat_id, message_id, text, kb)
    elif data == "a:setwidth":
        STATES[chat_id] = ["setwidth", None]
        send_message(chat_id, "🔢 تعداد دکمه در هر ردیف (1 تا 4) را بفرست:")
    elif data == "a:setsup":
        STATES[chat_id] = ["setsup", None]
        send_message(chat_id, "💬 آیدی پشتیبانی را بدون @ بفرست:")
    elif data == "a:setphone":
        STATES[chat_id] = ["setphone", None]
        send_message(chat_id, "📞 تلفن پشتیبانی را بفرست:")
    elif data == "a:tree":
        tree = "\n".join(tree_text(None)) or "بخشی نیست."
        edit_message(chat_id, message_id, "🗂 پیش‌نمایش درخت منو:\n\n" + tree,
                     make_keyboard([("◀️ بازگشت", "a:settings")]))
    else:
        show_menu(chat_id, message_id)

def count_descendants(sid):
    """تعداد زیربخش‌های یک بخش (برای هشدار حذف)."""
    n = 0
    for (cid,) in q("SELECT id FROM sections WHERE parent_id=?", (sid,), "all"):
        n += 1 + count_descendants(cid)
    return n

# ================== پردازش پیام‌های متنی ==================
def handle_state_message(chat_id, text, first_name):
    """مدیریت حالت‌های موقت (ورود مرحله‌ای اطلاعات)."""
    st = STATES.get(chat_id)
    if not st:
        return False
    state, temp = st[0], st[1]
    if state not in ("ticket", "quiz") and not is_admin(chat_id):
        STATES.pop(chat_id, None)
        return False
    if state == "addadm" and not is_owner(chat_id):
        STATES.pop(chat_id, None)
        return False
    if state in ("ticket", "quiz") and get_setting("feature_" + ("support" if state == "ticket" else "quiz"), "1") != "1":
        STATES.pop(chat_id, None)
        send_message(chat_id, "این بخش غیرفعال است.")
        return True

    if state == "btext":  # متن همگانی → تأیید
        confirm_broadcast(chat_id, text, bool(temp))
    elif state == "bcast":
        pass  # فقط با دکمه تأیید ارسال می‌شود

    elif state == "sec_title":  # [parent_id]
        STATES[chat_id] = ["sec_content", [temp[0], text]]
        send_message(chat_id, "📝 متن بخش را بفرست (یا «-» برای بدون متن):")
    elif state == "sec_content":  # [parent_id, title]
        pid, title = temp
        content = "" if text.strip() == "-" else text
        pos = q("SELECT COALESCE(MAX(sort_order),0)+1 FROM sections WHERE parent_id IS ?", (pid,), "one")[0]
        q("INSERT INTO sections(parent_id, title, content, sort_order, created_at) VALUES(?,?,?,?,?)",
          (pid, title, content, pos, now_str()))
        STATES.pop(chat_id, None)
        send_message(chat_id, f"✅ بخش «{title}» اضافه شد.")
        admin_panel(chat_id)
    elif state == "sec_editt":
        q("UPDATE sections SET title=? WHERE id=?", (text, temp))
        STATES.pop(chat_id, None)
        send_message(chat_id, "✏️ عنوان ویرایش شد.")
        show_section_admin(chat_id, temp)
    elif state == "sec_editc":
        q("UPDATE sections SET content=?, url='', forward_chat_id=NULL, forward_message_id=NULL WHERE id=?", ("" if text.strip() == "-" else text, temp))
        STATES.pop(chat_id, None)
        send_message(chat_id, "📝 متن ویرایش شد.")
        show_section_admin(chat_id, temp)
    elif state == "sec_editu":
        q("UPDATE sections SET url=?, forward_chat_id=NULL, forward_message_id=NULL WHERE id=?", ("" if text.strip() == "-" else text.strip(), temp))
        STATES.pop(chat_id, None)
        send_message(chat_id, "🔗 لینک ویرایش شد.")
        show_section_admin(chat_id, temp)

    elif state == "sec_editf":
        if text.strip() == "-":
            q("UPDATE sections SET forward_chat_id=NULL, forward_message_id=NULL WHERE id=?", (temp,))
            STATES.pop(chat_id, None)
            show_section_admin(chat_id, temp)
        else:
            source = parse_message_link(text)
            if source:
                save_section_forward(chat_id, temp, *source)
            else:
                send_message(chat_id, "لینک باید شناسه پیام داشته باشد؛ مثلاً https://ble.ir/channel/123 . اگر لینک شما این قالب را ندارد، خود ویدیو را فوروارد کن.")

    elif state == "ev_title":
        STATES[chat_id] = ["ev_date", [text]]
        send_message(chat_id, "📅 تاریخ را به شکل YYYY-MM-DD بفرست (مثلا 1403-09-15 یا 2024-12-05):")
    elif state == "ev_date":
        STATES[chat_id] = ["ev_time", temp + [text.strip()]]
        send_message(chat_id, "⏰ ساعت را بفرست (مثلا 16:30 یا «-» برای بدون ساعت):")
    elif state == "ev_time":
        STATES[chat_id] = ["ev_kind", temp + [text.strip()]]
        send_message(chat_id, "نوع رویداد یکی از این‌ها را بفرست:\n" + " | ".join(EVENT_KINDS))
    elif state == "ev_kind":
        kind = text.strip()
        if kind not in EVENT_KINDS:
            send_message(chat_id, "⚠️ نوع نامعتبر است؛ یکی از:\n" + " | ".join(EVENT_KINDS))
        else:
            title, d, t = temp
            q("INSERT INTO events(title, description, event_date, event_time, kind) VALUES(?,?,?,?,?)",
              (title, "", d, "" if t == "-" else t, kind))
            STATES.pop(chat_id, None)
            send_message(chat_id, f"✅ رویداد «{title}» ثبت شد.")
            events_panel(chat_id)

    elif state == "res_title":
        STATES[chat_id] = ["res_url", text]
        send_message(chat_id, "🔗 لینک جزوه را بفرست:")
    elif state == "res_url":
        title = temp
        STATES[chat_id] = ["res_desc", (title, text.strip())]
        send_message(chat_id, "📝 توضیح کوتاه را بفرست (یا «-»):")
    elif state == "res_desc":
        title, url = temp
        q("INSERT INTO resources(title, url, description) VALUES(?,?,?)",
          (title, url, "" if text.strip() == "-" else text))
        STATES.pop(chat_id, None)
        send_message(chat_id, f"✅ جزوه «{title}» اضافه شد.")
        resources_panel(chat_id)

    elif state == "faq_q":
        STATES[chat_id] = ["faq_a", text]
        send_message(chat_id, "✅ جواب این سوال را بفرست:")
    elif state == "faq_a":
        q("INSERT INTO faqs(question, answer) VALUES(?,?)", (temp, text))
        STATES.pop(chat_id, None)
        send_message(chat_id, "✅ سوال جدید اضافه شد.")
        faq_admin_panel(chat_id)

    elif state == "poll_q":  # temp = لیست گزینه‌ها؛ سوال در حالت poll_q جدید ست می‌شود
        if temp and temp[0] and text.strip() == "تمام":
            question = temp[0]
            opts = temp[1:]
            if len(opts) < 2:
                send_message(chat_id, "⚠️ حداقل دو گزینه لازم است؛ گزینه بعدی را بفرست.")
            else:
                q("INSERT INTO polls(question, created_at) VALUES(?,?)", (question, now_str()))
                pid = q("SELECT MAX(id) FROM polls", fetch="one")[0]
                for o in opts:
                    q("INSERT INTO poll_options(poll_id, text) VALUES(?,?)", (pid, o))
                STATES.pop(chat_id, None)
                send_message(chat_id, f"✅ نظرسنجی با {len(opts)} گزینه ساخته شد.")
                polls_admin_panel(chat_id)
        elif not temp:
            STATES[chat_id] = ["poll_q", [text]]
            send_message(chat_id, "➕ گزینه اول را بفرست (در پایان «تمام» را بفرست):")
        else:
            STATES[chat_id] = ["poll_q", temp + [text]]
            send_message(chat_id, "➕ گزینه بعدی را بفرست (یا «تمام» برای پایان):")

    elif state == "qq_text":  # سوال آزمون
        STATES[chat_id] = ["qq_opt", [text, None, 0]]  # [سوال، گزینه‌ها، شماره گزینه درست]
        send_message(chat_id, "➕ گزینه اول را بفرست (در پایان از گزینه‌ها «تمام» را بفرست):")
    elif state == "qq_opt":
        qtext, opts, cid = temp[0], temp[1] or [], temp[2]
        if opts and text.strip() == "تمام":
            if len(opts) < 2 or cid == 0:
                send_message(chat_id, "⚠️ حداقل ۲ گزینه و یک گزینه درست (با *) لازم است.")
            else:
                q("INSERT INTO quiz_questions(text) VALUES(?)", (qtext,))
                qid = q("SELECT MAX(id) FROM quiz_questions", fetch="one")[0]
                for i, o in enumerate(opts):
                    q("INSERT INTO quiz_options(question_id, text, is_correct) VALUES(?,?,?)",
                      (qid, o, 1 if i == cid - 1 else 0))
                STATES.pop(chat_id, None)
                send_message(chat_id, "✅ سوال آزمون اضافه شد.")
                quiz_admin_panel(chat_id)
        else:
            opts.append(text)
            STATES[chat_id] = ["qq_opt", [qtext, opts, len(opts) if text.startswith("*") else cid]]
            extra = " (این گزینه با * علامت‌گذاری شد و درست است ✅)" if text.startswith("*") else ""
            send_message(chat_id, f"➕ گزینه بعدی را بفرست یا «تمام» را بفرست:{extra}")

    elif state == "setwidth":
        n = safe_int(text, 1)
        if 1 <= n <= 4:
            set_setting("buttons_per_row", n)
            STATES.pop(chat_id, None)
            send_message(chat_id, f"✅ عرض منو روی {n} ست شد.")
            admin_panel(chat_id)
        else:
            send_message(chat_id, "⚠️ عددی بین 1 تا 4 بفرست.")
    elif state == "setsup":
        set_setting("support_username", text.strip().lstrip("@"))
        STATES.pop(chat_id, None)
        send_message(chat_id, "✅ آیدی پشتیبانی ثبت شد.")
        admin_panel(chat_id)
    elif state == "setphone":
        set_setting("support_phone", text.strip())
        STATES.pop(chat_id, None)
        send_message(chat_id, "✅ تلفن پشتیبانی ثبت شد.")
        admin_panel(chat_id)
    elif state == "addadm":
        aid = safe_int(text)
        if not aid:
            send_message(chat_id, "⚠️ شناسه عددی معتبر بفرست.")
        elif is_admin(aid):
            send_message(chat_id, "این کاربر از قبل ادمین است. ⚠️")
            STATES.pop(chat_id, None)
            admins_panel(chat_id)
        else:
            q("INSERT INTO admins(chat_id, name, added_at) VALUES(?,?,?)",
              (aid, "ادمین", now_str()))
            STATES.pop(chat_id, None)
            send_message(chat_id, f"✅ کاربر {aid} ادمین شد.")
            admins_panel(chat_id)
            send_message(aid, "🎓 شما به‌عنوان ادمین ربات مدرسه فانوس منصوب شدید!\nبا /admin پنل را باز کنید.")
    elif state == "ticket":
        STATES.pop(chat_id, None)
        send_message(chat_id, "✅ پیامت برای پشتیبانی ارسال شد. به‌زودی پاسخ می‌دهیم. 🌸")
        notify_admins_new_ticket(chat_id, first_name, text)
    elif state == "reply":
        uid = temp
        STATES.pop(chat_id, None)
        r = send_message(uid, f"📩 پاسخ پشتیبانی مدرسه فانوس:\n\n{text}")
        if r and r.get("ok"):
            send_message(chat_id, "✅ پاسخ ارسال شد.")
        else:
            send_message(chat_id, "⚠️ ارسال ناموفق (شاید کاربر ربات را بلاک کرده).")
    elif state == "quiz":
        send_message(chat_id, "⚠️ در وسط آزمون هستی؛ از دکمه‌های پیام استفاده کن.")
    else:
        STATES.pop(chat_id, None)
        return False
    return True

def handle_message(chat_id, text, first_name, message_id=None):
    """پردازش پیام‌ها: دستورها، حالت‌های ادمین، و پیش‌فرض (منو بدون سلام)."""
    register_user(chat_id, first_name)

    if text == "/cancel":
        STATES.pop(chat_id, None)
        show_menu(chat_id)
        return

    if handle_state_message(chat_id, text, first_name):
        return

    if text == "/start":
        row = q("SELECT greeted FROM users WHERE chat_id=?", (chat_id,), "one")
        greeted = bool(row and row[0])
        if not greeted:  # فقط بار اول خوش‌آمد
            q("UPDATE users SET greeted=1 WHERE chat_id=?", (chat_id,))
            show_menu(chat_id, None, greet=True, name=first_name)
        else:
            show_menu(chat_id, None, greet=False)
    elif text == "/id":
        send_message(chat_id, f"شناسه عددی شما: {chat_id}")
    elif text == "/admin":
        if is_admin(chat_id):
            STATES.pop(chat_id, None)
            admin_panel(chat_id)
        else:
            send_message(chat_id, "⛔️ دسترسی ندارید.")
    elif text == "/help":
        help_text = "📖 راهنما:\n/start — نمایش منو\n/id — شناسه شما\n/cancel — انصراف\n"
        if is_admin(chat_id):
            help_text += "/admin — پنل مدیریت\n"
        send_message(chat_id, help_text + "برای ارتباط با پشتیبانی از منوی اصلی استفاده کن.")
    elif is_admin(chat_id) and text == "منو":
        admin_panel(chat_id)
    else:
        # هر پیام دیگری: فقط منو، بدون سلام تکراری
        show_menu(chat_id, None, greet=False)

# ================== پردازش آپدیت‌ها ==================
def process_update(upd):
    """پردازش یک آپدیت getUpdates."""
    if "callback_query" in upd:
        cb = upd["callback_query"]
        msg = cb.get("message") or {}
        chat_id = (msg.get("chat") or {}).get("id")
        if not chat_id:
            return
        if (msg.get("chat") or {}).get("type") != "private" or (cb.get("from") or {}).get("id") != chat_id:
            answer_callback(cb.get("id"), "لطفاً در گفتگوی خصوصی ربات استفاده کن.")
            return
        handle_callback(chat_id, cb.get("data", ""), cb.get("id"),
                        msg.get("message_id"), (msg.get("chat") or {}).get("first_name", "دوست من"))
    elif "message" in upd:
        msg = upd["message"]
        chat_id = msg["chat"]["id"]
        if msg["chat"].get("type") != "private" or msg.get("from", {}).get("id") != chat_id:
            return
        state = STATES.get(chat_id)
        if state and state[0] == "sec_editf" and is_admin(chat_id) and (msg.get("video") or msg.get("document") or msg.get("forward_from_chat") or msg.get("forward_origin")):
            save_section_forward(chat_id, state[1], chat_id, msg["message_id"])
            return
        text = msg.get("text", "")
        first_name = msg.get("from", {}).get("first_name") or msg["chat"].get("first_name") or "دوست من"
        if text:
            handle_message(chat_id, text, first_name, msg.get("message_id"))

# ================== راه‌اندازی و حلقه اصلی ==================
def startup_check():
    """بررسی اعتبار توکن با getMe."""
    r = api("getMe")
    if r and r.get("ok"):
        me = r.get("result", {})
        print(f"✅ اتصال برقرار شد. ربات: @{me.get('username', '?')} (id={me.get('id')})")
        return True
    print("❌ getMe ناموفق بود؛ توکن یا اتصال اینترنت را بررسی کنید.")
    print(f"پاسخ سرور: {r}")
    return False

def main():
    """نقطه شروع: ساخت دیتابیس + حلقه long-polling."""
    init_db()
    if not startup_check():
        return
    offset = 0
    print("🤖 ربات مدرسه فانوس در حال اجراست... (Ctrl+C برای توقف)")
    while True:
        try:
            r = api("getUpdates", offset=offset, timeout=60)
            if r and r.get("ok"):
                for upd in r.get("result", []):
                    offset = upd["update_id"] + 1
                    try:
                        process_update(upd)
                    except Exception:
                        traceback.print_exc()  # خطای یک آپدیت، ربات را نمی‌بندد
            else:
                time.sleep(3)
        except KeyboardInterrupt:
            print("ربات متوقف شد. 👋")
            break
        except Exception:
            traceback.print_exc()
            time.sleep(3)

if __name__ == "__main__":
    main()
