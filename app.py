import os
import html
import json
import sqlite3
import threading
import time
from pathlib import Path
from datetime import datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse, quote

HOST = "0.0.0.0"
PORT = int(os.environ.get("PORT", "8000"))
DB_PATH = Path(os.environ.get("QUEUELESS_DB", str(Path(__file__).parent / "queueless.db")))


def now():
    return datetime.now().isoformat(timespec="seconds")


def get_connection():
    con = sqlite3.connect(DB_PATH, timeout=15, check_same_thread=False)
    con.row_factory = sqlite3.Row
    con.execute("PRAGMA foreign_keys = ON")
    con.execute("PRAGMA busy_timeout = 15000")
    con.execute("PRAGMA journal_mode = WAL")
    return con


def initialize_database():
    con = get_connection()
    try:
        con.executescript("""
        CREATE TABLE IF NOT EXISTS services (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            average_service_minutes INTEGER NOT NULL DEFAULT 10,
            active INTEGER NOT NULL DEFAULT 1
        );

        CREATE TABLE IF NOT EXISTS counters (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            status TEXT NOT NULL DEFAULT 'available'
        );

        CREATE TABLE IF NOT EXISTS customers (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            phone TEXT,
            created_at TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS queue_entries (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            token TEXT NOT NULL UNIQUE,
            customer_id INTEGER NOT NULL,
            service_id INTEGER NOT NULL,
            status TEXT NOT NULL DEFAULT 'waiting',
            counter_id INTEGER,
            joined_at TEXT NOT NULL,
            accepted_at TEXT,
            started_at TEXT,
            completed_at TEXT,
            FOREIGN KEY(customer_id) REFERENCES customers(id),
            FOREIGN KEY(service_id) REFERENCES services(id),
            FOREIGN KEY(counter_id) REFERENCES counters(id)
        );

        CREATE TABLE IF NOT EXISTS notifications (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            queue_entry_id INTEGER NOT NULL,
            message TEXT NOT NULL,
            reminder_minutes INTEGER,
            sent INTEGER NOT NULL DEFAULT 0,
            created_at TEXT NOT NULL,
            FOREIGN KEY(queue_entry_id) REFERENCES queue_entries(id)
                ON DELETE CASCADE
        );

        CREATE TABLE IF NOT EXISTS queue_events (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            queue_entry_id INTEGER,
            event_type TEXT NOT NULL,
            details TEXT,
            created_at TEXT NOT NULL,
            FOREIGN KEY(queue_entry_id) REFERENCES queue_entries(id)
                ON DELETE CASCADE
        );
        """)

        if con.execute("SELECT COUNT(*) AS c FROM services").fetchone()["c"] == 0:
            con.executemany(
                "INSERT INTO services(name, average_service_minutes, active) VALUES (?, ?, 1)",
                [("General Enquiry", 10), ("Billing", 10), ("Support", 10)]
            )

        if con.execute("SELECT COUNT(*) AS c FROM counters").fetchone()["c"] == 0:
            con.executemany(
                "INSERT INTO counters(name, status) VALUES (?, 'available')",
                [("Counter 1",), ("Counter 2",)]
            )
        else:
            con.execute("UPDATE counters SET status='available' WHERE status='offline'")

        con.commit()
    finally:
        con.close()


def add_event(con, queue_id, event_type, details):
    con.execute(
        "INSERT INTO queue_events(queue_entry_id,event_type,details,created_at) VALUES(?,?,?,?)",
        (queue_id, event_type, details, now())
    )


def next_token(con):
    row = con.execute(
        "SELECT token FROM queue_entries ORDER BY id DESC LIMIT 1"
    ).fetchone()
    if not row:
        number = 1
    else:
        try:
            number = int(row["token"].replace("Q-", "")) + 1
        except (ValueError, TypeError):
            number = 1
    return f"Q-{number:03d}"


def join_queue(name, phone, service_id):
    con = get_connection()
    try:
        created = now()
        customer = con.execute(
            "INSERT INTO customers(name,phone,created_at) VALUES(?,?,?)",
            (name, phone, created)
        )
        customer_id = customer.lastrowid
        token = next_token(con)
        cur = con.execute(
            """INSERT INTO queue_entries
               (token,customer_id,service_id,status,joined_at)
               VALUES(?,?,?,'waiting',?)""",
            (token, customer_id, service_id, created)
        )
        queue_id = cur.lastrowid
        add_event(con, queue_id, "joined", "Customer joined the queue")
        con.commit()
        return queue_id
    except Exception:
        con.rollback()
        raise
    finally:
        con.close()


def calculate_eta(queue_id):
    con = get_connection()
    try:
        current = con.execute(
            "SELECT id, service_id, status, joined_at FROM queue_entries WHERE id=?",
            (queue_id,)
        ).fetchone()
        if current is None:
            return None

        ahead = con.execute(
            """SELECT COUNT(*) AS c FROM queue_entries
               WHERE service_id=?
               AND status IN ('waiting','accepted')
               AND joined_at < ?""",
            (current["service_id"], current["joined_at"])
        ).fetchone()["c"]

        service = con.execute(
            "SELECT average_service_minutes FROM services WHERE id=?",
            (current["service_id"],)
        ).fetchone()
        average = int(service["average_service_minutes"] if service else 10)

        active = con.execute(
            "SELECT COUNT(*) AS c FROM counters WHERE status IN ('available','busy')"
        ).fetchone()["c"]
        active = max(active, 1)

        if current["status"] in ("serving", "completed", "no_show"):
            wait = 0
        else:
            wait = max(0, round((ahead * average) / active))

        return {
            "people_ahead": ahead,
            "estimated_wait_minutes": wait,
            "active_counters": active
        }
    finally:
        con.close()


def page_shell(title, body, refresh=None):
    refresh_tag = f'<meta http-equiv="refresh" content="{refresh}">' if refresh else ""
    return f"""<!DOCTYPE html>
<html>
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
{refresh_tag}
<title>{html.escape(title)}</title>
<style>
*{{box-sizing:border-box}}
body{{margin:0;background:#f7f7f4;color:#222;font-family:Arial,sans-serif}}
.container{{max-width:1050px;margin:auto;padding:32px 18px 50px}}
.narrow{{max-width:560px}}
.brand{{font-size:32px;font-weight:800;letter-spacing:-1px}}
.muted{{color:#777;margin-top:7px}}
.card{{background:#fff;border:1px solid #e4e1da;border-radius:18px;padding:25px;margin-top:20px;box-shadow:0 5px 20px rgba(0,0,0,.04)}}
label{{display:block;font-weight:700;margin:16px 0 7px}}
input,select{{width:100%;padding:14px;border:1px solid #d8d5ce;border-radius:10px;font-size:16px;background:#fff}}
button{{border:0;border-radius:10px;padding:13px 18px;background:#3f7669;color:#fff;font-weight:700;cursor:pointer}}
button:hover{{opacity:.9}}
.primary{{width:100%;margin-top:22px;font-size:16px}}
.grid{{display:grid;grid-template-columns:repeat(3,1fr);gap:14px}}
.stat{{background:#fafaf7;border:1px solid #e8e5de;border-radius:14px;padding:18px}}
.stat .label{{color:#777;font-size:13px;margin-bottom:8px}}
.stat .value{{font-size:30px;font-weight:800}}
.token{{font-size:58px;font-weight:800;letter-spacing:2px;text-align:center;margin:20px 0}}
.center{{text-align:center}}
.ok{{padding:13px;border-radius:10px;background:#edf7f1;color:#3d6e5e;font-weight:700}}
.warn{{padding:13px;border-radius:10px;background:#fff5df;color:#806329}}
.danger{{padding:13px;border-radius:10px;background:#faeded;color:#955858}}
.actions{{display:flex;gap:8px;flex-wrap:wrap}}
.actions form{{margin:0}}
.small{{padding:9px 12px;font-size:12px}}
table{{width:100%;border-collapse:collapse}}
th,td{{padding:13px 10px;border-bottom:1px solid #eee;text-align:left;font-size:14px}}
th{{color:#777;font-size:12px}}
.badge{{display:inline-block;border-radius:20px;padding:6px 9px;font-size:10px;font-weight:800}}
.waiting{{background:#eeeae1;color:#696258}}
.serving{{background:#e5f2ed;color:#3f7567}}
.completed{{background:#e8eee9;color:#4c665b}}
.no_show{{background:#f5eaea;color:#935b5b}}
.counter{{display:flex;justify-content:space-between;border:1px solid #e4e1da;border-radius:12px;padding:15px;margin-top:10px}}
a{{color:#4b7167;text-decoration:none}}
.footer{{text-align:center;color:#999;font-size:12px;margin-top:25px}}
.status-wrap{{max-width:380px;margin:0 auto;text-align:center;padding:26px 0 20px}}
.status-brand{{font-size:28px;font-weight:800;margin-bottom:14px}}
.welcome{{font-size:14px;margin:0 0 8px}}
.service-name{{font-size:14px;color:#666;margin:0}}
.status-wrap .token{{font-size:52px;margin:24px 0 18px}}
.status-stat{{margin:18px 0}}
.status-label{{font-size:13px;color:#555;margin-bottom:7px}}
.status-value{{font-size:25px;font-weight:800}}
.status-value small{{font-size:16px}}
.status-wrap .ok,.status-wrap .warn,.status-wrap .danger{{margin:12px 0}}
.reminder-card{{background:#f7f7f7;border-radius:12px;padding:20px 18px;margin-top:24px;text-align:center}}
.reminder-card h3{{margin:0 0 14px;font-size:16px}}
.reminder-card p{{font-size:13px;color:#444;margin:0 0 14px;line-height:1.45}}
.reminder-card select{{width:145px;padding:9px 10px;font-size:13px;margin-bottom:14px}}
.reminder-card button{{display:block;margin:0 auto;background:#171717;padding:10px 18px;font-size:12px}}
.reminder-enabled{{background:#edf7f1;color:#356b5b;border-radius:10px;padding:12px;margin-top:14px;font-size:13px}}
.reminder-enabled span{{display:block;font-weight:400;margin-top:5px;color:#4f6f66}}
.auto-refresh{{color:#777;font-size:12px;margin-top:20px}}
@media(max-width:700px){{.grid{{grid-template-columns:1fr}}table{{min-width:760px}}.token{{font-size:48px}}}}
</style>
</head>
<body>
<div class="container">{body}</div>
</body>
</html>"""


class QueueLessHandler(BaseHTTPRequestHandler):
    def log_message(self, fmt, *args):
        print(fmt % args)

    def send_html(self, content, status=200):
        data = content.encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def send_json(self, data, status=200):
        payload = json.dumps(data).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    def redirect(self, location):
        self.send_response(303)
        self.send_header("Location", location)
        self.end_headers()

    def do_GET(self):
        parsed = urlparse(self.path)
        path = parsed.path
        query = parse_qs(parsed.query)

        if path == "/":
            self.customer_page()
        elif path == "/status":
            self.status_page(query)
        elif path == "/management":
            self.management_page()
        elif path == "/health":
            self.send_json({"status": "ok", "application": "QueueLess"})
        else:
            self.send_json({"error": "Not Found"}, 404)

    def do_POST(self):
        path = urlparse(self.path).path
        length = int(self.headers.get("Content-Length", 0))
        data = parse_qs(self.rfile.read(length).decode("utf-8"))

        try:
            if path == "/join":
                self.join(data)
            elif path == "/call-next":
                self.call_next(data)
            elif path == "/complete-service":
                self.complete(data)
            elif path == "/no-show":
                self.no_show(data)
            elif path == "/remind":
                self.remind(data)
            else:
                self.send_json({"error": "Not Found"}, 404)
        except sqlite3.OperationalError as e:
            self.send_json({"error": f"Database error: {e}"}, 500)
        except Exception as e:
            self.send_json({"error": str(e)}, 500)

    def customer_page(self):
        con = get_connection()
        try:
            services = con.execute(
                "SELECT id,name FROM services WHERE active=1 ORDER BY name"
            ).fetchall()
        finally:
            con.close()

        options = "".join(
            f'<option value="{s["id"]}">{html.escape(s["name"])}</option>'
            for s in services
        )

        body = f"""
<div class="narrow" style="margin:auto">
    <div class="brand">QueueLess</div>
    <div class="muted">Join the queue without standing in it.</div>

    <div class="card">
        <h2>Join the queue</h2>
        <form method="POST" action="/join">
            <label>Your name</label>
            <input name="name" required placeholder="Enter your name">

            <label>Phone number</label>
            <input name="phone" type="tel" maxlength="15" placeholder="Optional">

            <label>Service</label>
            <select name="service_id" required>{options}</select>

            <button class="primary" type="submit">Join Queue</button>
        </form>
    </div>


    <div class="footer">QueueLess • Simple digital queue management</div>
</div>"""
        self.send_html(page_shell("QueueLess", body))

    def join(self, data):
        name = data.get("name", [""])[0].strip()
        phone = data.get("phone", [""])[0].strip()
        try:
            service_id = int(data.get("service_id", [""])[0])
        except ValueError:
            self.send_json({"error": "Please select a valid service."}, 400)
            return

        if not name:
            self.send_json({"error": "Name is required."}, 400)
            return

        queue_id = join_queue(name, phone, service_id)
        self.redirect(f"/status?id={queue_id}")

    def status_page(self, query):
        try:
            queue_id = int(query.get("id", [""])[0])
        except (ValueError, TypeError):
            self.send_html(page_shell("QueueLess", '<div class="card center"><h2>Invalid queue ID</h2></div>'), 400)
            return

        con = get_connection()
        try:
            queue = con.execute(
                """SELECT q.*, c.name AS customer_name, s.name AS service_name
                   FROM queue_entries q
                   JOIN customers c ON c.id=q.customer_id
                   JOIN services s ON s.id=q.service_id
                   WHERE q.id=?""",
                (queue_id,)
            ).fetchone()
            notification = con.execute(
                """SELECT message,sent FROM notifications
                   WHERE queue_entry_id=? AND reminder_minutes IS NULL AND sent=1
                   ORDER BY id DESC LIMIT 1""",
                (queue_id,)
            ).fetchone()
            reminder = con.execute(
                """SELECT reminder_minutes,sent FROM notifications
                   WHERE queue_entry_id=? AND reminder_minutes IS NOT NULL
                   ORDER BY id DESC LIMIT 1""",
                (queue_id,)
            ).fetchone()
        finally:
            con.close()

        if queue is None:
            self.send_html(page_shell("QueueLess", '<div class="card center"><h2>Queue entry not found.</h2></div>'), 404)
            return

        eta = calculate_eta(queue_id) or {"people_ahead": 0, "estimated_wait_minutes": 0, "active_counters": 0}
        status = queue["status"]

        if status == "serving":
            message = '<div class="ok center">🎉 IT\'S YOUR TURN! Please proceed to the counter.</div>'
        elif status == "completed":
            message = '<div class="ok center">✅ Service completed. Thank you!</div>'
        elif status == "no_show":
            message = '<div class="danger center">❌ This queue entry was marked as no-show.</div>'
        else:
            message = '<div class="ok center">🟢 You are in the queue.</div>'

        notice = ""
        if notification:
            notice = f'<div class="warn" style="margin-top:15px">🔔 {html.escape(notification["message"])}</div>'

        reminder_box = ""
        if status == "waiting":
            if reminder:
                reminder_box = '<div class="ok center" style="margin-top:15px">🔔 Reminder is enabled.</div>'
            elif eta["estimated_wait_minutes"] >= 10:
                reminder_box = f"""
                <div class="reminder-card">
                    <h3>🔔 &nbsp;Set a Reminder</h3>
                    <p>Choose when you want to be reminded before your turn.</p>
                    <form method="POST" action="/remind">
                        <input type="hidden" name="queue_id" value="{queue_id}">
                        <select name="reminder_minutes">
                            {''.join(f'<option value="{m}">{m} minutes before</option>' for m in (10,20,30) if eta['estimated_wait_minutes'] >= m)}
                        </select>
                        <button type="submit">🔔 Set Reminder</button>
                    </form>
                </div>"""

        # Customer-facing status design: simple, mobile-friendly, and
        # based on the earlier QueueLess reminder screen.
        if reminder:
            reminder_status = (
                '<div class="reminder-enabled">🔔 <strong>Reminder enabled</strong>'
                f'<span>You will be reminded at approximately {reminder["reminder_minutes"]} minutes before your turn.</span></div>'
                if not reminder["sent"] else
                '<div class="reminder-enabled">🔔 <strong>Reminder sent</strong><span>Your QueueLess reminder has been delivered.</span></div>'
            )
        else:
            reminder_status = ""

        body = f"""
<div class="status-wrap">
    <div class="status-brand">QueueLess</div>
    <p class="welcome">Welcome, <strong>{html.escape(queue['customer_name'])}</strong></p>
    <p class="service-name">{html.escape(queue['service_name'])}</p>

    <div class="token">{html.escape(queue['token'])}</div>

    {message}
    {notice}

    <div class="status-stat">
        <div class="status-label">People ahead</div>
        <div class="status-value">{eta['people_ahead']}</div>
    </div>

    <div class="status-stat">
        <div class="status-label">Estimated waiting time</div>
        <div class="status-value">{eta['estimated_wait_minutes']} <small>min</small></div>
    </div>

    <div class="status-stat">
        <div class="status-label">Active counters</div>
        <div class="status-value">{eta['active_counters']}</div>
    </div>

    {reminder_box}
    {reminder_status}

    <p class="auto-refresh">This page automatically refreshes.</p>
</div>"""
        self.send_html(page_shell(f"{queue['token']} - QueueLess", body, refresh=10))

    def management_page(self):
        con = get_connection()
        try:
            queue = con.execute(
                """SELECT q.id,q.token,c.name AS customer_name,s.name AS service_name,
                          q.status,q.counter_id,q.joined_at
                   FROM queue_entries q
                   JOIN customers c ON c.id=q.customer_id
                   JOIN services s ON s.id=q.service_id
                   WHERE q.status IN ('waiting','accepted','serving')
                   ORDER BY q.joined_at ASC"""
            ).fetchall()
            counters = con.execute("SELECT id,name,status FROM counters ORDER BY id").fetchall()
            analytics = con.execute(
                """SELECT
                    COUNT(CASE WHEN status='completed' THEN 1 END) AS served,
                    COUNT(CASE WHEN status='no_show' THEN 1 END) AS no_show,
                    AVG(CASE WHEN status='completed' AND started_at IS NOT NULL AND completed_at IS NOT NULL
                        THEN (julianday(completed_at)-julianday(started_at))*24*60 END) AS avg_service,
                    AVG(CASE WHEN status='completed' AND joined_at IS NOT NULL AND started_at IS NOT NULL
                        THEN (julianday(started_at)-julianday(joined_at))*24*60 END) AS avg_wait
                  FROM queue_entries"""
            ).fetchone()
        finally:
            con.close()

        waiting = sum(1 for q in queue if q["status"] == "waiting")
        serving = sum(1 for q in queue if q["status"] == "serving")

        rows = ""
        for q in queue:
            if q["status"] == "waiting":
                action = f"""
                <div class="actions">
                    <form method="POST" action="/call-next"><input type="hidden" name="queue_id" value="{q['id']}"><button class="small">CALL</button></form>
                    <form method="POST" action="/no-show"><input type="hidden" name="queue_id" value="{q['id']}"><button class="small" style="background:#955858">NO-SHOW</button></form>
                </div>"""
            else:
                action = ""
                if q["status"] == "serving":
                    action = f"<form method=\"POST\" action=\"/complete-service\"><input type=\"hidden\" name=\"queue_id\" value=\"{q['id']}\"><button class=\"small\">COMPLETE</button></form>"
            rows += f"""<tr>
                <td><strong>{html.escape(q['token'])}</strong></td>
                <td>{html.escape(q['customer_name'])}</td>
                <td>{html.escape(q['service_name'])}</td>
                <td><span class="badge {q['status']}">{q['status'].upper()}</span></td>
                <td>{q['counter_id'] or '-'}</td>
                <td>{action}</td>
            </tr>"""

        if not rows:
            rows = '<tr><td colspan="6" class="center">No active customers.</td></tr>'

        counter_html = "".join(
            f'<div class="counter"><strong>{html.escape(c["name"])}</strong><span>{c["status"].upper()}</span></div>'
            for c in counters
        )

        avg_wait = round(analytics["avg_wait"], 1) if analytics["avg_wait"] is not None else 0
        avg_service = round(analytics["avg_service"], 1) if analytics["avg_service"] is not None else 0

        body = f"""
<div class="brand">QueueLess <span class="muted" style="font-size:14px;font-weight:400">Management</span></div>
<div class="muted">Live queue control and analytics</div>

<div class="grid" style="margin-top:25px">
    <div class="stat"><div class="label">Waiting</div><div class="value">{waiting}</div></div>
    <div class="stat"><div class="label">Serving</div><div class="value">{serving}</div></div>
    <div class="stat"><div class="label">Active</div><div class="value">{len(queue)}</div></div>
</div>

<div class="card">
    <h2>Current Queue</h2>
    <div style="overflow-x:auto">
    <table>
        <tr><th>Token</th><th>Customer</th><th>Service</th><th>Status</th><th>Counter</th><th>Action</th></tr>
        {rows}
    </table>
    </div>
</div>

<div class="card">
    <h2>Queue Analytics</h2>
    <div class="grid">
        <div class="stat"><div class="label">Total Served</div><div class="value">{analytics['served'] or 0}</div></div>
        <div class="stat"><div class="label">No-Shows</div><div class="value">{analytics['no_show'] or 0}</div></div>
        <div class="stat"><div class="label">Average Wait</div><div class="value">{avg_wait}<small> min</small></div></div>
    </div>
    <div class="stat" style="margin-top:14px"><div class="label">Average Service Time</div><div class="value">{avg_service}<small> min</small></div></div>
</div>

<div class="card">
    <h2>Counters</h2>
    {counter_html}
</div>

<div class="footer">Management dashboard refreshes every 5 seconds.</div>"""
        self.send_html(page_shell("QueueLess Management", body, refresh=5))

    def call_next(self, data):
        try:
            queue_id = int(data.get("queue_id", [""])[0])
        except ValueError:
            self.send_json({"error": "Invalid queue ID"}, 400)
            return

        con = get_connection()
        try:
            queue = con.execute("SELECT status FROM queue_entries WHERE id=?", (queue_id,)).fetchone()
            counter = con.execute("SELECT id,name FROM counters WHERE status='available' ORDER BY id LIMIT 1").fetchone()
            if queue is None:
                self.send_json({"error": "Queue entry not found"}, 404)
                return
            if queue["status"] != "waiting":
                self.send_json({"error": "Customer is not waiting"}, 400)
                return
            if counter is None:
                self.send_json({"error": "No available counter"}, 400)
                return

            stamp = now()
            con.execute("UPDATE queue_entries SET status='serving',counter_id=?,started_at=? WHERE id=?", (counter["id"], stamp, queue_id))
            con.execute("UPDATE counters SET status='busy' WHERE id=?", (counter["id"],))
            add_event(con, queue_id, "service_started", f"Service started at {counter['name']}")
            con.execute(
                "INSERT INTO notifications(queue_entry_id,message,reminder_minutes,sent,created_at) VALUES(?,?,?,?,?)",
                (queue_id, f"Your turn! Please proceed to {counter['name']}.", None, 1, stamp)
            )
            con.commit()
        except Exception:
            con.rollback()
            raise
        finally:
            con.close()
        self.redirect("/management")

    def complete(self, data):
        queue_id = int(data.get("queue_id", [""])[0])
        con = get_connection()
        try:
            row = con.execute("SELECT counter_id FROM queue_entries WHERE id=?", (queue_id,)).fetchone()
            stamp = now()
            con.execute("UPDATE queue_entries SET status='completed',completed_at=? WHERE id=?", (stamp, queue_id))
            if row and row["counter_id"]:
                con.execute("UPDATE counters SET status='available' WHERE id=?", (row["counter_id"],))
            add_event(con, queue_id, "completed", "Service completed")
            con.commit()
        except Exception:
            con.rollback(); raise
        finally:
            con.close()
        self.redirect("/management")

    def no_show(self, data):
        queue_id = int(data.get("queue_id", [""])[0])
        con = get_connection()
        try:
            row = con.execute("SELECT counter_id,status FROM queue_entries WHERE id=?", (queue_id,)).fetchone()
            if row is None:
                self.send_json({"error": "Queue entry not found"}, 404); return
            stamp = now()
            con.execute("UPDATE queue_entries SET status='no_show' WHERE id=?", (queue_id,))
            if row["counter_id"]:
                con.execute("UPDATE counters SET status='available' WHERE id=?", (row["counter_id"],))
            add_event(con, queue_id, "no_show", "Customer marked as no-show")
            con.commit()
        except Exception:
            con.rollback(); raise
        finally:
            con.close()
        self.redirect("/management")

    def remind(self, data):
        queue_id = int(data.get("queue_id", [""])[0])
        minutes = int(data.get("reminder_minutes", ["10"])[0])
        if minutes not in (10, 20, 30):
            minutes = 10

        con = get_connection()
        try:
            row = con.execute("SELECT status FROM queue_entries WHERE id=?", (queue_id,)).fetchone()
            if row is None:
                self.send_json({"error": "Queue entry not found"}, 404); return
            existing = con.execute(
                "SELECT id FROM notifications WHERE queue_entry_id=? AND reminder_minutes IS NOT NULL AND sent=0 LIMIT 1",
                (queue_id,)
            ).fetchone()
            if not existing:
                con.execute(
                    "INSERT INTO notifications(queue_entry_id,message,reminder_minutes,sent,created_at) VALUES(?,?,?,?,?)",
                    (queue_id, f"Reminder enabled for approximately {minutes} minutes before your turn.", minutes, 0, now())
                )
                con.commit()
        except Exception:
            con.rollback(); raise
        finally:
            con.close()
        self.redirect(f"/status?id={queue_id}")


def reminder_checker():
    while True:
        try:
            con = get_connection()
            reminders = con.execute(
                "SELECT id,queue_entry_id,reminder_minutes FROM notifications WHERE reminder_minutes IS NOT NULL AND sent=0"
            ).fetchall()
            con.close()

            for r in reminders:
                eta = calculate_eta(r["queue_entry_id"])
                if eta is None:
                    continue
                if eta["estimated_wait_minutes"] <= r["reminder_minutes"]:
                    con = get_connection()
                    try:
                        message = (
                            "🎉 Your turn is now! Please proceed to the counter."
                            if eta["estimated_wait_minutes"] <= 0
                            else f"🔔 Your turn is approximately {round(eta['estimated_wait_minutes'])} minutes away."
                        )
                        con.execute(
                            "UPDATE notifications SET message=?,sent=1 WHERE id=? AND sent=0",
                            (message, r["id"])
                        )
                        con.commit()
                    finally:
                        con.close()
        except Exception as e:
            print("Reminder checker:", e)
        time.sleep(30)


def main():
    initialize_database()
    threading.Thread(target=reminder_checker, daemon=True).start()
    server = ThreadingHTTPServer((HOST, PORT), QueueLessHandler)
    print(f"QueueLess running on port {PORT}")
    print(f"Customer:   http://localhost:{PORT}/")
    print(f"Management: http://localhost:{PORT}/management")
    print(f"Health:     http://localhost:{PORT}/health")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nQueueLess stopped.")
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
