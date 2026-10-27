"""Бот-напоминалка для MAX: подписка с согласием на обработку ПДн.

Логика:
1. Пользователь запускает бота или пишет ему.
2. Бот просит согласие на обработку персональных данных.
3. После ответа «Да, согласен» пользователь попадает в подписчики.
4. Только подписчики получают напоминания.
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

CONSENT_REQUEST = """Здравствуйте! Это бот напоминаний о домашнем задании для родителей 5 «А».

Прежде чем подписать вас, прошу согласие на обработку персональных данных.

Оператор: Чиканова Юлия Сергеевна (самозанятая, ИНН 501208342256).
Собираемые данные: ваш идентификатор и имя в мессенджере MAX.
Цель: рассылка напоминаний о домашнем задании в будние дни.
Согласие можно отозвать в любой момент, написав «Отпишите меня» этому боту.

Напишите «Да», чтобы подписаться, или «Нет», чтобы отказаться."""

WELCOME = "Спасибо! Вы подписаны на напоминания о домашнем задании."
DECLINED = "Хорошо, вы не подписаны. Если передумаете — просто напишите «Да, согласен»."

DECLINE_WORDS = (
    "нет",
    "не согласен",
    "отказ",
    "отпишите",
    "отписаться",
    "отписаться от рассылки",
)

# Актуальный API MAX.
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
    req = urllib.request.Request(url, data=data, method=method)
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
        "pending": {},
        "names": {},
        "marker": None,
    },
)
consents = load("consents.json", [])

# Нормализуем старые данные: ID всегда храним строками,
# чтобы JSON не превращал ключи словаря в другой тип.
users["subscribers"] = [str(uid) for uid in users.get("subscribers", [])]
users["pending"] = {str(uid): value for uid, value in users.get("pending", {}).items()}
users["names"] = {str(uid): value for uid, value in users.get("names", {}).items()}
users.setdefault("marker", None)


# ---------- 1. Забираем обновления ----------
params = {
    "limit": 100,
    "timeout": 30,
}

if users["marker"] is not None:
    params["marker"] = users["marker"]

try:
    upd = api_request("GET", "/updates", params=params)
except urllib.error.HTTPError as e:
    details = e.read().decode("utf-8", "ignore")[:500]
    print(f"Ошибка /updates: HTTP {e.code}: {details}")
    upd = {}
except Exception as e:
    print(f"Ошибка /updates: {e}")
    upd = {}

now = datetime.now(MSK).isoformat(timespec="seconds")

for update in upd.get("updates", []):
    update_type = update.get("update_type", "")
    uid = None
    name = None
    text = ""

    # Пользователь начал/возобновил общение с ботом.
    if update_type == "bot_started":
        user = update.get("user") or {}
        uid = user.get("user_id")
        name = user.get("name") or user.get("first_name")
        text = "bot_started"

    # Пользователь отправил сообщение.
    elif update_type == "message_created":
        message = update.get("message") or {}
        sender = message.get("sender") or {}
        body = message.get("body") or {}

        uid = sender.get("user_id")
        name = sender.get("name") or sender.get("first_name")
        text = (body.get("text") or "").strip().lower()

    else:
        continue

    if uid is None:
        continue

    uid = str(uid)

    if name:
        users["names"][uid] = name

    # Уже подписанный пользователь может отписаться.
    if uid in users["subscribers"]:
        if any(word in text for word in DECLINE_WORDS):
            users["subscribers"].remove(uid)
            users["pending"].pop(uid, None)
            send(uid, "Вы отписаны. Напоминания больше приходить не будут.")
        continue

    # Если пользователь ещё не подтверждал согласие — просим его.
    if uid not in users["pending"]:
        users["pending"][uid] = "asked"
        send(uid, CONSENT_REQUEST)
        continue

    # Пользователь уже получил запрос согласия и теперь отвечает.
    if text.startswith("да") or "соглас" in text:
        if uid not in users["subscribers"]:
            users["subscribers"].append(uid)

        users["pending"].pop(uid, None)

        consents.append(
            {
                "user_id": uid,
                "name": name or users["names"].get(uid),
                "date": now,
            }
        )

        send(uid, WELCOME)

    elif any(word in text for word in DECLINE_WORDS):
        users["pending"].pop(uid, None)
        send(uid, DECLINED)

    elif text != "bot_started":
        send(
            uid,
            "Напишите, пожалуйста, «Да, согласен» для подписки или «Нет» для отказа.",
        )


if upd.get("marker") is not None:
    users["marker"] = upd["marker"]

save("users.json", users)
save("consents.json", consents)

print(
    f"Подписчиков: {len(users['subscribers'])}, "
    f"согласий в журнале: {len(consents)}"
)


# ---------- 2. Рассылка ----------
if MODE == "send":
    if datetime.now(MSK).weekday() >= 5:
        print("Выходной — рассылка не выполняется.")
        sys.exit(0)

    if not users["subscribers"]:
        print("Подписчиков нет.")
        sys.exit(0)

    sent_count = sum(send(uid, TEXT) for uid in users["subscribers"])
    print(f"Разослано: {sent_count} из {len(users['subscribers'])}")

