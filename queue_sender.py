import sqlite3, json, time, requests
from config import QUEUE_DB, PUSH_ENDPOINT, DEBUG

def init_db():
    conn = sqlite3.connect(QUEUE_DB)
    conn.execute("""CREATE TABLE IF NOT EXISTS outbox (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        payload TEXT,
        created_at REAL,
        sent INTEGER DEFAULT 0)""")
    conn.commit(); conn.close()

def queue_payload(payload):
    conn = sqlite3.connect(QUEUE_DB)
    conn.execute("INSERT INTO outbox (payload, created_at, sent) VALUES (?, ?, 0)",
                 (json.dumps(payload), time.time()))
    conn.commit(); conn.close()
    if DEBUG: print("[queue] queued", payload)

def send_now(payload, timeout=3.0):
    if DEBUG: print("[send_now]", payload)
    r = requests.post(PUSH_ENDPOINT, json=payload, timeout=timeout)
    r.raise_for_status()

def flush_outbox():
    conn = sqlite3.connect(QUEUE_DB)
    cur = conn.cursor()
    for id_, payload_text in cur.execute("SELECT id, payload FROM outbox WHERE sent=0"):
        p = json.loads(payload_text)
        try:
            send_now(p)
            conn.execute("UPDATE outbox SET sent=1 WHERE id=?", (id_,))
            conn.commit()
            if DEBUG: print("[outbox] sent id", id_)
        except Exception as e:
            if DEBUG: print("[outbox] failed id", id_, str(e))
            break
    conn.close()
