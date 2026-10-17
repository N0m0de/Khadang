"""Durable owner decisions; resolving a reminder never messages a contact."""
import re
import time
from telegram import InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import CallbackQueryHandler
from . import db
from .config import settings
from .outgoing import attributed

SCHEMA = '''CREATE TABLE IF NOT EXISTS owner_followups (
 id INTEGER PRIMARY KEY AUTOINCREMENT, owner_id INTEGER NOT NULL,
 source_key TEXT NOT NULL, chat_id INTEGER NOT NULL, contact TEXT NOT NULL,
 description TEXT NOT NULL, kind TEXT NOT NULL, status TEXT NOT NULL DEFAULT 'pending',
 created_at INTEGER NOT NULL, updated_at INTEGER NOT NULL,
 UNIQUE(owner_id,source_key)
)'''
LABELS = {'pending': 'Still pending', 'done': 'Done', 'confirmed': 'Confirmed / attending', 'declined': 'Declined'}
_REQUEST = re.compile(r'\b(can you|could you|please|check|review|send me|look into|follow up|remind me)\b|'
                      r'بررسی|چک کن|چکش|بفرست|پیگیری|لطفا|لطفاً|یادت نره|میشه|می شه|میتونی|می تونی', re.I)


async def initialize():
    await db._db().execute(SCHEMA)
    await db._db().commit()


async def add(row, description, kind='task', *, refine=False):
    if row['role'] != 'user' or kind not in ('task', 'meeting'):
        return
    message = row['tg_message_id'] or f'row-{row["id"]}'
    key = f'{row["conn_id"]}:{row["chat_id"]}:{message}'
    await db._db().execute('''INSERT OR IGNORE INTO owner_followups
        (owner_id,source_key,chat_id,contact,description,kind,created_at,updated_at)
        VALUES(?,?,?,?,?,?,?,?)''', (settings.owner_user_id, key, row['chat_id'],
        row['contact'], str(description).strip()[:700], kind, row['created_at'], int(time.time())))
    if refine:
        await db._db().execute('''UPDATE owner_followups SET description=?,kind=?
            WHERE owner_id=? AND source_key=? AND status='pending' ''',
            (str(description).strip()[:700], kind, settings.owner_user_id, key))
    await db._db().commit()


async def capture_requests(rows, classifier):
    # Keep this useful when OpenAI is unavailable; conservative source-backed suggestions.
    for row in rows:
        text = row['content'].replace('\u200c', ' ')
        scheduling = classifier(text) == 'Scheduling / deadline request'
        if row['role'] == 'user' and (scheduling or _REQUEST.search(text)):
            await add(row, row['content'], 'meeting' if scheduling else 'task')


async def pending():
    cur = await db._db().execute('SELECT * FROM owner_followups WHERE owner_id=? AND status=? ORDER BY created_at,id',
                                (settings.owner_user_id, 'pending'))
    return [dict(row) for row in await cur.fetchall()]


async def get(item_id):
    cur = await db._db().execute('SELECT * FROM owner_followups WHERE id=? AND owner_id=?',
                                (item_id, settings.owner_user_id))
    row = await cur.fetchone()
    return dict(row) if row else None


def card(item):
    from datetime import datetime
    from zoneinfo import ZoneInfo
    date = datetime.fromtimestamp(item['created_at'], ZoneInfo('Asia/Tehran')).strftime('%Y-%m-%d %H:%M')
    return attributed(f'📌 Follow-up #{item["id"]} — {item["contact"]} (chat {item["chat_id"]})\n'
                      f'Requested: {date} Tehran time\n\n{item["description"]}\n\n'
                      f'Status: {LABELS[item["status"]]}\n'
                      'Have you handled this request or decided about the invitation?\n'
                      'Buttons record your status only; no message is sent to the contact.')


def keyboard(item):
    choices = [('✅ Done', 'done')]
    if item['kind'] == 'meeting':
        choices.append(('👍 Confirmed / attending', 'confirmed'))
    return InlineKeyboardMarkup([
        [InlineKeyboardButton(label, callback_data=f'fu:{item["id"]}:{action}') for label, action in choices],
        [InlineKeyboardButton('❌ Declined', callback_data=f'fu:{item["id"]}:declined'),
         InlineKeyboardButton('⏳ Still pending', callback_data=f'fu:{item["id"]}:pending')]])


async def on_callback(update, _ctx):
    query = update.callback_query
    if query is None:
        return
    if (query.from_user.id != settings.owner_user_id or query.message is None
            or query.message.chat.id != settings.owner_user_id):
        await query.answer('Owner only.', show_alert=True)
        return
    match = re.fullmatch(r'fu:(\d+):(done|confirmed|declined|pending)', query.data or '')
    if match is None:
        await query.answer('Invalid action.')
        return
    item_id, action = int(match[1]), match[2]
    item = await get(item_id)
    if item is None:
        await query.answer('Item no longer available.')
        return
    if action == 'confirmed' and item['kind'] != 'meeting':
        await query.answer('Use Done for this task.')
        return
    if item['status'] != 'pending':
        await query.answer('Already recorded: ' + LABELS[item['status']])
        return
    await db._db().execute('UPDATE owner_followups SET status=?,updated_at=? WHERE id=? AND owner_id=? AND status=?',
                          (action, int(time.time()), item_id, settings.owner_user_id, 'pending'))
    await db._db().commit()
    item = await get(item_id)
    await query.answer('Saved. No message sent to the contact.')
    if action != 'pending':
        await query.edit_message_text(card(item), reply_markup=None)


def register(app):
    app.add_handler(CallbackQueryHandler(on_callback, pattern=r'^fu:'))
