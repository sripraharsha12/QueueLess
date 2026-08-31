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
DB_PATH = Path(__file__).parent / "queueless.db"


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
                if reminder["sent"]:
                    reminder_box = f"""
                    <div class="reminder-set">
                        <div class="reminder-title">🔔 Reminder sent</div>
                        <div>Your {reminder["reminder_minutes"]}-minute reminder has been triggered.</div>
                    </div>"""
                else:
                    reminder_box = f"""
                    <div class="reminder-set">
                        <div class="reminder-title">✅ Reminder set</div>
                        <div>You selected a reminder {reminder["reminder_minutes"]} minutes before your turn.</div>
                    </div>"""
            else:
                reminder_options = "".join(
                    f'<option value="{m}">{m} minutes before</option>'
                    for m in (10, 20, 30)
                    if eta["estimated_wait_minutes"] >= m
                )
                if reminder_options:
                    reminder_box = f"""
                    <div class="reminder-card">
                        <div class="reminder-title">🔔 Set a Reminder</div>
                        <p>Choose when you want to be reminded before your turn.</p>
                        <form method="POST" action="/remind">
                            <input type="hidden" name="queue_id" value="{queue_id}">
                            <select name="reminder_minutes" required>{reminder_options}</select>
                            <button type="submit">🔔 Set Reminder</button>
                        </form>
                    </div>"""
                else:
                    reminder_box = """
                    <div class="reminder-card">
                        <div class="reminder-title">🔔 Set a Reminder</div>
                        <p>Your turn is less than 10 minutes away. Keep this page open for the live turn notification.</p>
                        <button type="button" disabled style="opacity:.55;cursor:not-allowed;width:100%;margin-top:8px">Reminder unavailable</button>
                    </div>"""

        body = f"""
<div class="status-wrap">
    <div class="status-brand">QueueLess</div>
    <div class="status-subtitle">Your queue status</div>

    <div class="status-card">
        <p class="welcome">Welcome, <strong>{html.escape(queue["customer_name"])}</strong></p>
        <p class="service-name">{html.escape(queue["service_name"])}</p>
        <div class="big-token">{html.escape(queue["token"])}</div>
        {message}
        {notice}

        <div class="status-stats">
            <div><div class="stat-label">People ahead</div><div class="stat-value">{eta["people_ahead"]}</div></div>
            <div><div class="stat-label">Estimated waiting time</div><div class="stat-value">{eta["estimated_wait_minutes"]} min</div></div>
            <div><div class="stat-label">Active counters</div><div class="stat-value">{eta["active_counters"]}</div></div>
        </div>
    </div>

    {reminder_box}
    <div class="auto-refresh">This page automatically refreshes.</div>
</div>

<style>
.status-wrap{{max-width:560px;margin:0 auto;text-align:center}}
.status-brand{{font-size:34px;font-weight:800;margin-top:10px}}
.status-subtitle{{color:#77746d;font-size:15px;margin:3px 0 18px}}
.status-card{{background:#fff;border:1px solid #e3dfd7;border-radius:16px;padding:26px 22px;box-shadow:0 4px 18px rgba(0,0,0,.04)}}
.welcome{{margin:0;font-size:16px}}
.service-name{{margin:8px 0 0;color:#666;font-size:15px}}
.big-token{{font-size:58px;font-weight:800;letter-spacing:1px;margin:18px 0 20px}}
.status-message{{border-radius:10px;padding:14px;margin:12px 0;font-size:15px}}
.waiting-box{{background:#eef8ef;color:#3d6f5e}}
.serving-box{{background:#e7f1ff;color:#315d88}}
.completed-box{{background:#f0f0f0;color:#555}}
.danger-box{{background:#faecec;color:#975656}}
.notification-box{{background:#fff4db;border:1px solid #f0d695;border-radius:10px;padding:13px;margin-top:12px;text-align:left;color:#765d20}}
.notification-text{{margin-top:5px}}
.status-stats{{display:grid;grid-template-columns:repeat(3,1fr);gap:12px;margin-top:18px}}
.status-stats>div{{background:#faf9f6;border:1px solid #e6e2da;border-radius:12px;padding:14px 8px}}
.stat-label{{font-size:11px;color:#77746d;line-height:1.25}}
.stat-value{{font-size:24px;font-weight:800;margin-top:7px}}
.reminder-card,.reminder-set{{margin-top:14px;background:#f8f8f8;border-radius:12px;padding:20px;border:1px solid #ece9e3}}
.reminder-card{{text-align:center}}
.reminder-set{{background:#edf8f2;color:#477464}}
.reminder-title{{font-weight:800;font-size:16px;margin-bottom:8px}}
.reminder-card p{{color:#666;font-size:14px;margin:6px 0 14px}}
.reminder-card select{{width:100%;padding:12px;border:1px solid #d6d1c8;border-radius:9px;background:#fff;font-size:15px}}
.reminder-card button{{margin-top:12px;width:100%;padding:13px;border:0;border-radius:9px;background:#111;color:#fff;font-weight:700;cursor:pointer}}
.auto-refresh{{color:#999;font-size:12px;margin:18px 0 5px}}
@media(max-width:600px){{.status-stats{{grid-template-columns:repeat(3,1fr)}}.big-token{{font-size:50px}}}}
</style>
"""
        self.send_html(page_shell(f"{queue['token']} - QueueLess", body, refresh=10))

    def management_page(self):
        con = get_connection()
        try:
            queue = con.execute(
                """SELECT q.id,q.token,c.name AS customer_name,s.name AS service_name,
                          q.status,q.counter_id,q.joined_at,q.started_at
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
                    COUNT(*) AS total,
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
        active = waiting + serving
        served = analytics["served"] or 0
        no_show = analytics["no_show"] or 0
        total_processed = served + no_show
        avg_wait = round(analytics["avg_wait"], 1) if analytics["avg_wait"] is not None else 0
        avg_service = round(analytics["avg_service"], 1) if analytics["avg_service"] is not None else 0
        service_rate = round((served / total_processed) * 100) if total_processed else 0
        busy_counters = sum(1 for c in counters if c["status"] in ("busy", "serving"))
        counter_util = round((busy_counters / len(counters)) * 100) if counters else 0

        rows = ""
        for q in queue:
            if q["status"] == "waiting":
                action = f"""
                <div class="actions">
                    <form method="POST" action="/call-next">
                        <input type="hidden" name="queue_id" value="{q['id']}">
                        <button class="action-btn call" type="submit">CALL</button>
                    </form>
                    <form method="POST" action="/no-show">
                        <input type="hidden" name="queue_id" value="{q['id']}">
                        <button class="action-btn no-show" type="submit">NO-SHOW</button>
                    </form>
                </div>"""
            elif q["status"] == "serving":
                action = f"""
                <form method="POST" action="/complete-service">
                    <input type="hidden" name="queue_id" value="{q['id']}">
                    <button class="action-btn complete" type="submit">COMPLETE</button>
                </form>"""
            else:
                action = ""
            rows += f"""
            <tr>
                <td><span class="token-chip">{html.escape(q['token'])}</span></td>
                <td><strong>{html.escape(q['customer_name'])}</strong></td>
                <td>{html.escape(q['service_name'])}</td>
                <td><span class="badge {q['status']}">{q['status'].upper()}</span></td>
                <td>{q['counter_id'] or '—'}</td>
                <td>{action}</td>
            </tr>"""
        if not rows:
            rows = '<tr><td colspan="6" class="empty">No active customers right now.</td></tr>'

        counter_html = "".join(
            f"""
            <div class="counter-card">
                <div class="counter-top">
                    <div>
                        <div class="counter-name">{html.escape(c['name'])}</div>
                        <div class="counter-sub">Counter {c['id']}</div>
                    </div>
                    <span class="counter-pill {'busy' if c['status'] in ('busy','serving') else 'free'}">
                        {'BUSY' if c['status'] in ('busy','serving') else 'AVAILABLE'}
                    </span>
                </div>
                <div class="counter-line"><span></span></div>
            </div>
            """
            for c in counters
        ) or '<div class="empty">No counters configured.</div>'

        wait_width = min(100, max(0, int(avg_wait * 5)))
        service_width = min(100, max(0, int(avg_service * 5)))

        body = f"""
<style>
.mgmt-shell{{max-width:1180px;margin:0 auto}}
.mgmt-header{{display:flex;justify-content:space-between;align-items:flex-end;gap:20px;margin-bottom:28px}}
.mgmt-title{{font-size:34px;font-weight:800;letter-spacing:-1px;margin:0}}
.mgmt-subtitle{{color:#7d7a73;margin-top:6px}}
.live-dot{{display:inline-flex;align-items:center;gap:8px;padding:8px 12px;border-radius:999px;background:#edf8f4;color:#4f8275;font-size:13px;font-weight:700;white-space:nowrap}}
.live-dot::before{{content:"";width:8px;height:8px;border-radius:50%;background:#4f8275}}
.kpis{{display:grid;grid-template-columns:repeat(4,1fr);gap:16px;margin-bottom:18px}}
.kpi{{background:linear-gradient(145deg,#fff,#f7faf8);border:1px solid #e2e7e4;border-radius:18px;padding:20px;position:relative;overflow:hidden}}
.kpi::after{{content:"";position:absolute;right:-28px;top:-28px;width:90px;height:90px;border-radius:50%;background:#eaf2ef}}
.kpi-label{{color:#7d7a73;font-size:12px;font-weight:700;letter-spacing:.06em;margin-bottom:10px}}
.kpi-value{{font-size:34px;font-weight:800;position:relative;z-index:1}}
.kpi-note{{font-size:12px;color:#8c8982;margin-top:7px;position:relative;z-index:1}}
.dashboard-grid{{display:grid;grid-template-columns:1.65fr 1fr;gap:18px;align-items:start}}
.card.mgmt-card{{margin-bottom:0;border-radius:18px;padding:22px}}
.section-head{{display:flex;justify-content:space-between;align-items:center;gap:12px;margin-bottom:18px}}
.section-head h2{{margin:0;font-size:20px}}
.section-caption{{color:#8c8982;font-size:13px;margin-top:4px}}
.table-wrap{{overflow-x:auto}}
table{{width:100%;border-collapse:collapse;min-width:760px}}
th{{color:#8a877f;font-size:11px;text-transform:uppercase;letter-spacing:.06em;padding:11px 10px;border-bottom:1px solid #ece9e2;text-align:left}}
td{{padding:14px 10px;border-bottom:1px solid #f0eee9;font-size:14px}}
.token-chip{{display:inline-block;font-weight:800;background:#edf4f1;color:#4f8275;border:1px solid #dce9e4;padding:7px 10px;border-radius:10px}}
.badge{{display:inline-block;padding:6px 10px;border-radius:999px;font-size:10px;font-weight:800;letter-spacing:.04em}}
.badge.waiting{{background:#fff6db;color:#9a7b19}}
.badge.serving{{background:#e8f5ef;color:#3d7664}}
.badge.accepted{{background:#eef0ff;color:#5963a9}}
.actions{{display:flex;gap:7px;align-items:center}}
.action-btn{{width:auto;height:auto;border:0;border-radius:9px;padding:9px 12px;color:#fff;font-size:11px;font-weight:800;cursor:pointer}}
.call{{background:#4f8275}}
.complete{{background:#5666a8}}
.no-show{{background:#a46262}}
.analytics-grid{{display:grid;grid-template-columns:repeat(2,1fr);gap:12px}}
.mini{{background:#fafbf9;border:1px solid #ecefe9;border-radius:14px;padding:15px}}
.mini .label{{font-size:12px;color:#8b887f}}
.mini .big{{font-size:24px;font-weight:800;margin-top:5px}}
.meter{{margin-top:8px;height:8px;border-radius:999px;background:#e9ece9;overflow:hidden}}
.meter>span{{display:block;height:100%;border-radius:999px;background:#6d9b8e}}
.counter-list{{display:grid;gap:11px}}
.counter-card{{border:1px solid #e8ebe7;background:#fbfcfb;border-radius:14px;padding:15px}}
.counter-top{{display:flex;justify-content:space-between;align-items:center;gap:12px}}
.counter-name{{font-weight:800}}
.counter-sub{{color:#959188;font-size:12px;margin-top:3px}}
.counter-pill{{padding:6px 10px;border-radius:999px;font-size:10px;font-weight:800}}
.counter-pill.free{{background:#edf8f2;color:#4d806c}}
.counter-pill.busy{{background:#fff1e6;color:#a56c3b}}
.counter-line{{margin-top:12px;height:4px;border-radius:999px;background:#e8ece8}}
.counter-line span{{display:block;width:55%;height:100%;border-radius:999px;background:#6d9b8e}}
.empty{{color:#959188;padding:28px 10px;text-align:center}}
@media(max-width:900px){{.kpis{{grid-template-columns:repeat(2,1fr)}}.dashboard-grid{{grid-template-columns:1fr}}}}
@media(max-width:560px){{.kpis{{grid-template-columns:1fr}}.mgmt-header{{align-items:flex-start;flex-direction:column}}.analytics-grid{{grid-template-columns:1fr}}.mgmt-title{{font-size:29px}}}}
</style>

<div class="mgmt-shell">
    <div class="mgmt-header">
        <div>
            <div class="brand" style="font-size:15px;margin-bottom:7px;">QueueLess</div>
            <h1 class="mgmt-title">Management Dashboard</h1>
            <div class="mgmt-subtitle">Monitor the queue, counters, service flow and performance.</div>
        </div>
        <div class="live-dot">LIVE • refreshes every 5 seconds</div>
    </div>

    <div class="kpis">
        <div class="kpi"><div class="kpi-label">WAITING</div><div class="kpi-value">{waiting}</div><div class="kpi-note">Customers currently waiting</div></div>
        <div class="kpi"><div class="kpi-label">SERVING</div><div class="kpi-value">{serving}</div><div class="kpi-note">Customers at counters</div></div>
        <div class="kpi"><div class="kpi-label">SERVED</div><div class="kpi-value">{served}</div><div class="kpi-note">Completed services</div></div>
        <div class="kpi"><div class="kpi-label">SERVICE RATE</div><div class="kpi-value">{service_rate}%</div><div class="kpi-note">Completed vs processed</div></div>
    </div>

    <div class="dashboard-grid">
        <div class="card mgmt-card">
            <div class="section-head">
                <div><h2>Current Queue</h2><div class="section-caption">Manage customers in real time.</div></div>
                <span class="badge serving">{active} ACTIVE</span>
            </div>
            <div class="table-wrap">
                <table>
                    <thead><tr><th>Token</th><th>Customer</th><th>Service</th><th>Status</th><th>Counter</th><th>Action</th></tr></thead>
                    <tbody>{rows}</tbody>
                </table>
            </div>
        </div>

        <div style="display:grid;gap:18px;">
            <div class="card mgmt-card">
                <div class="section-head"><div><h2>Queue Analytics</h2><div class="section-caption">Performance overview</div></div></div>
                <div class="analytics-grid">
                    <div class="mini"><div class="label">Average wait</div><div class="big">{avg_wait} min</div><div class="meter"><span style="width:{wait_width}%"></span></div></div>
                    <div class="mini"><div class="label">Average service</div><div class="big">{avg_service} min</div><div class="meter"><span style="width:{service_width}%"></span></div></div>
                    <div class="mini"><div class="label">No-shows</div><div class="big">{no_show}</div><div class="kpi-note">Customers missed</div></div>
                    <div class="mini"><div class="label">Counter usage</div><div class="big">{counter_util}%</div><div class="meter"><span style="width:{counter_util}%"></span></div></div>
                </div>
            </div>

            <div class="card mgmt-card">
                <div class="section-head"><div><h2>Counters</h2><div class="section-caption">Live counter availability</div></div></div>
                <div class="counter-list">{counter_html}</div>
            </div>
        </div>
    </div>

    <div class="footer" style="margin-top:20px;">QueueLess • Smart digital queue management</div>
</div>"""
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
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nQueueLess stopped.")
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
