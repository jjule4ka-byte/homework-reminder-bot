"""Бот-напоминалка для MAX.

Логика:
1. Пользователь запускает бота или пишет ему.
2. Пользователь автоматически добавляется в подписчики.
3. При первом запуске бот отправляет приветственное сообщение.
4. Подписчики получают напоминания.
"""

import os
import sys
import json
import urllib.parse
import urllib.request
import urllib.error
from datetime import datetime, timezone, timedelta


MAX_TOKEN = os.environ["MAX_BOT_TOKEN"]
MODE = os.environ.get("MODE", "send")

TEXT = os.environ.get(
    "REMINDER_TEXT",
    "Напоминаю: пожалуйста, отправьте домашнее задание 5 «А» в электронный журнал или в чат с родителями. Спасибо!",
)

WELCOME = (
    "Здравствуйте! 👋\n\n"
    "Вы подписаны на напоминания о домашнем задании для 5 «А»."
)

API = "https://platform-api2.max.ru"
MSK = timezone(timedelta(hours=3))


def load(path, default):
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return default


def save(path, obj):
    with open(path, "w", encoding="utf-8") as f:
        json.dump(obj, f, ensure_ascii=False, indent=2)


def api_request(method, path, body=None, params=None):
    url = API + path

    if params:
        url += "?" + urllib.parse.urlencode(params)

    data = json.dumps(body).encode("utf-8") if body is not None else None

    req = urllib.request.Request(
        url,
        data=data,
        method=method,
    )

    req.add_header("Authorization", MAX_TOKEN)

    if body is not None:
        req.add_header("Content-Type", "application/json")

    with urllib.request.urlopen(req, timeout=40) as resp:
        raw = resp.read().decode("utf-8")
        return json.loads(raw) if raw else {}


def send(user_id, text):
    try:
        api_request(
            "POST",
            "/messages",
            body={"text": text},
            params={"user_id": int(user_id)},
        )
        return True

    except urllib.error.HTTPError as e:
        details = e.read().decode("utf-8", "ignore")[:500]
        print(f"Ошибка отправки {user_id}: HTTP {e.code}: {details}")
        return False

    except Exception as e:
        print(f"Ошибка отправки {user_id}: {e}")
        return False


users = load(
    "users.json",
    {
        "subscribers": [],
        "names": {},
        "marker": None,
    },
)

# На случай, если users.json остался от старой версии бота.
users["subscribers"] = [
    str(uid) for uid in users.get("subscribers", [])
]

users["names"] = {
    str(uid): value
    for uid, value in users.get("names", {}).items()
}

users.setdefault("marker", None)


# ---------- 1. Забираем новые сообщения ----------

params = {
    "limit": 100,
    "timeout": 30,
}

if users["marker"] is not None:
    params["marker"] = users["marker"]

try:
    upd = api_request(
        "GET",
        "/updates",
        params=params,
    )

except urllib.error.HTTPError as e:
    details = e.read().decode("utf-8", "ignore")[:500]
    print(f"Ошибка /updates: HTTP {e.code}: {details}")
    upd = {}

except Exception as e:
    print(f"Ошибка /updates: {e}")
    upd = {}


for update in upd.get("updates", []):

    update_type = update.get("update_type", "")

    uid = None
    name = None

    # Пользователь нажал «Начать».
    if update_type == "bot_started":

        user = update.get("user") or {}

        uid = user.get("user_id")
        name = user.get("name") or user.get("first_name")

    # Пользователь написал сообщение.
    elif update_type == "message_created":

        message = update.get("message") or {}
        sender = message.get("sender") or {}

        uid = sender.get("user_id")
        name = sender.get("name") or sender.get("first_name")

    else:
        continue

    if uid is None:
        continue

    uid = str(uid)

    if name:
        users["names"][uid] = name

    # Новый пользователь.
    if uid not in users["subscribers"]:

        users["subscribers"].append(uid)

        send(uid, WELCOME)


if upd.get("marker") is not None:
    users["marker"] = upd["marker"]


save("users.json", users)

print(
    f"Подписчиков: {len(users['subscribers'])}"
)


# ---------- 2. Рассылка ----------

if MODE == "send":

    if datetime.now(MSK).weekday() >= 5:
        print("Выходной — рассылка не выполняется.")
        sys.exit(0)

    if not users["subscribers"]:
        print("Подписчиков нет.")
        sys.exit(0)

    sent_count = sum(
        send(uid, TEXT)
        for uid in users["subscribers"]
    )

    print(
        f"Разослано: {sent_count} "
        f"из {len(users['subscribers'])}"
    )
