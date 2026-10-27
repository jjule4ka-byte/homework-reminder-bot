"""Бот-напоминалка для MAX v3: подписка с согласием на обработку ПДн.

Двухшаговая подписка:
  1. человек запускает бота -> получает уведомление об обработке ПДн
  2. отвечает «Да/Согласен» -> попадает в подписчики, согласие записывается
Только после согласия человек получает напоминания.
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
    "Напоминаю: пожалуйста, отправьте домашнее задание 5 «А» в электронный журнал или в чат с родителями. Спасибо!"
)

CONSENT_REQUEST = """Здравствуйте! Это бот напоминаний о домашнем задании для родителей 5 «А».

Прежде чем подписать вас, прошу согласие на обработку персональных данных.

Оператор: Чиканова Юлия Сергеевна (самозанятая, ИНН 501208342256).
Собираемые данные: ваш идентификатор и имя в мессенджере MAX.
Цель: рассылка напоминаний о домашнем задании в будние дни.
Хранение: на защищённом сервере GitHub (РФ не требуется, данные не передаются третьим лицам).
Согласие можно отозвать в любой момент, написав «Отпишите меня» этому боту — вы будете удалены в течение 24 часов.

Напишите «Да, согласен», чтобы подписаться, или «Нет», чтобы отказаться."""

WELCOME = "Спасибо! Вы подписаны на напоминания о домашнем задании (пн–пт, ~15:00 МСК)."
DECLINED = "Хорошо, вы не подписаны. Если передумаете — просто напишите «Да, согласен»."
AFTER_YES = "да"
DECLINE_WORDS = ("нет", "не согласен", "отказ", "отпишите", "отписаться")

API = "https://botapi.max.ru"
MSK = timezone(timedelta(hours=3))


def load(path, default):
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except FileNotFoundError:
        return default


def save(path, obj):
    with open(path, "w", encoding="utf-8") as f:
        json.dump(obj, f, ensure_ascii=False, indent=2)


def api_request(method, path, body=None, params=None):
    url = API + path + ("?" + urllib.parse.urlencode(params) if params else "")
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
        api_request("POST", "/messages", body={"text": text}, params={"user_id": user_id})
        return True
    except Exception as e:
        print(f"Ошибка отправки {user_id}: {e}")
        return False


users = load("users.json", {"subscribers": [], "pending": {}, "names": {}, "marker": None})
consents = load("consents.json", [])

# ---------- 1. Забираем обновления ----------
params = {"limit": 100, "timeout": 30}
if users["marker"] is not None:
    params["marker"] = users["marker"]
try:
    upd = api_request("GET", "/updates", params=params)
except urllib.error.HTTPError as e:
    print("Ошибка /updates:", e.code, e.read().decode("utf-8", "ignore")[:300])
    upd = {}

now = datetime.now(MSK).isoformat(timespec="seconds")

for u in upd.get("updates", []):
    uid, name, text = None, None, ""
    if "user" in u:
        uid, name = u["user"].get("user_id"), u["user"].get("name")
        text = "bot_started"
    elif "message" in u and "sender" in u["message"]:
        uid = u["message"]["sender"].get("user_id")
        name = u["message"]["sender"].get("name")
        text = (u["message"].get("body") or {}).get("text", "").strip().lower()
    if uid is None:
        continue
    if name:
    users["names"][str(uid)] = name

pending = users["pending"]
uid_key = str(uid)

if uid in users["subscribers"]:
    if any(w in text for w in DECLINE_WORDS):
        users["subscribers"].remove(uid)
        send(uid, "Вы отписаны. Напоминания больше приходить не будут.")
    continue

if uid_key not in pending:
    pending[uid_key] = "asked"
    send(uid, CONSENT_REQUEST)
elif text.startswith("да") or "соглас" in text:
    users["subscribers"].append(uid)
    del pending[uid_key]
    consents.append({"user_id": uid, "name": name, "date": now})
    send(uid, WELCOME)
elif any(w in text for w in DECLINE_WORDS):
    del pending[uid_key]
    send(uid, DECLINED)
else:
    send(uid, "Напишите, пожалуйста, «Да, согласен» для подписки или «Нет» для отказа.")

if upd.get("marker") is not None:
    users["marker"] = upd["marker"]
save("users.json", users)
save("consents.json", consents)
print(f"Подписчиков: {len(users['subscribers'])}, согласий в журнале: {len(consents)}")

# ---------- 2. Рассылка ----------
if MODE == "send":
    if datetime.now(MSK).weekday() >= 5:
        print("Выходной — рассылка не выполняется.")
        sys.exit(0)
    if not users["subscribers"]:
        print("Подписчиков нет.")
        sys.exit(0)
    ok = sum(send(uid, TEXT) for uid in users["subscribers"])
    print(f"Разослано: {ok} из {len(users['subscribers'])}")
