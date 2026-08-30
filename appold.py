from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse
from datetime import datetime
import os
import json
import html
import threading
import time

from database import initialize_database, get_connection
from queue_engine import QueueEngine
from eta import calculate_eta


HOST = "0.0.0.0"
PORT = int(os.environ.get("PORT", 8000))


class QueueLessHandler(BaseHTTPRequestHandler):

    # ---------------------------------------------------------
    # RESPONSE HELPERS
    # ---------------------------------------------------------

    def send_html(self, content, status=200):
        data = content.encode("utf-8")

        self.send_response(status)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()

        self.wfile.write(data)

    def send_json(self, data, status=200):
        body = json.dumps(data).encode("utf-8")

        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()

        self.wfile.write(body)

    def redirect(self, location):
        self.send_response(303)
        self.send_header("Location", location)
        self.end_headers()

    # ---------------------------------------------------------
    # GET REQUESTS
    # ---------------------------------------------------------

    def do_GET(self):

        path = urlparse(self.path).path
        query = parse_qs(urlparse(self.path).query)

        # Customer home page
        if path == "/":
            self.customer_page()
            return

        # Customer queue status
        if path == "/status":
            self.status_page(query)
            return

        # Management dashboard
        if path == "/management":
            self.management_page()
            return

        # Health check
        if path == "/health":
            self.send_json({
                "status": "ok",
                "application": "QueueLess"
            })
            return

        self.send_json({
            "error": "Not Found"
        }, 404)

    # ---------------------------------------------------------
    # POST REQUESTS
    # ---------------------------------------------------------

    def do_POST(self):

        path = urlparse(self.path).path

        length = int(self.headers.get("Content-Length", 0))

        body = self.rfile.read(length).decode("utf-8")

        data = parse_qs(body)

        # Customer joins queue
        if path == "/join":
            self.join_queue(data)
            return

        # Management calls next customer
        if path == "/call-next":
            self.call_next(data)
            return

        if path == "/remind":
            self.remind_customer(data)
            return
        
        # Management completes current service
        if path == "/complete-service":
            self.complete_service(data)
            return

        # Management marks a customer as no-show
        if path == "/no-show":
            self.no_show(data)
            return

        self.send_json({
            "error": "Not Found"
        }, 404)

    # ---------------------------------------------------------
    # CUSTOMER PAGE
    # ---------------------------------------------------------

    def customer_page(self):

        connection = get_connection()

        services = connection.execute(
            """
            SELECT id, name
            FROM services
            WHERE active = 1
            ORDER BY name
            """
        ).fetchall()

        connection.close()

        options = ""

        for service in services:
            options += f"""
            <option value="{service["id"]}">
                {html.escape(service["name"])}
            </option>
            """

        if not options:
            options = """
            <option value="">
                No services available
            </option>
            """

        page = f"""
<!DOCTYPE html>
<html>
<head>

<meta charset="UTF-8">

<meta name="viewport"
      content="width=device-width, initial-scale=1.0">

<title>QueueLess</title>

<style>

* {{
    box-sizing: border-box;
}}

body {{
    margin: 0;
    font-family: Arial, sans-serif;
    background: #f7f7f5;
    color: #242424;
}}

.container {{
    width: 100%;
    max-width: 760px;
    margin: auto;
    padding: 55px 20px;
}}

.header {{
    text-align: center;
    margin-bottom: 45px;
}}

.logo {{
    font-size: 36px;
    font-weight: 700;
    letter-spacing: -1px;
}}

.tagline {{
    margin-top: 8px;
    color: #88857d;
    font-size: 17px;
}}

.card {{
    max-width: 620px;
    margin: auto;
    background: #ffffff;
    border: 1px solid #e4e1da;
    border-radius: 24px;
    padding: 42px;
    box-shadow: 0 8px 30px rgba(0,0,0,0.04);
}}

.card h2 {{
    margin: 0;
    font-size: 28px;
}}

.description {{
    margin: 8px 0 32px;
    color: #77746d;
    font-size: 16px;
}}

label {{
    display: block;
    margin-bottom: 8px;
    color: #66635c;
    font-size: 15px;
}}

input,
select {{
    width: 100%;
    height: 54px;
    padding: 0 16px;
    margin-bottom: 22px;
    border: 1px solid #dedbd4;
    border-radius: 12px;
    background: #fff;
    color: #292929;
    font-size: 16px;
}}

input:focus,
select:focus {{
    outline: none;
    border-color: #4f8275;
}}

button {{
    width: 100%;
    height: 56px;
    border: none;
    border-radius: 12px;
    background: #4f8275;
    color: white;
    font-size: 17px;
    font-weight: 600;
    cursor: pointer;
}}

button:hover {{
    background: #426f64;
}}

.note {{
    text-align: center;
    margin-top: 22px;
    color: #9a978f;
    font-size: 14px;
}}

</style>

</head>

<body>

<div class="container">

    <div class="header">

        <div class="logo">
            QueueLess
        </div>

        <div class="tagline">
            Skip the wait, keep your place
        </div>

    </div>


    <div class="card">

        <h2>
            Join the queue
        </h2>

        <div class="description">
            A few details and you're in line.
        </div>


        <form method="POST" action="/join">

            <label>
                Name
            </label>

            <input
                type="text"
                name="name"
                placeholder="Your name"
                required
            >


            <label>
                Phone number
            </label>

            <input
                type="tel"
                name="phone"
                placeholder="Your phone number"
                maxlength="10"
                pattern="[0-9]{{10}}"
                required
            >


            <label>
                Service
            </label>

            <select
                name="service_id"
                required
            >

                {options}

            </select>


            <button type="submit">
                Join queue
            </button>

        </form>


        <div class="note">
            You'll see your position and wait time next.
        </div>

    </div>

</div>

</body>
</html>
"""

        self.send_html(page)
    # ---------------------------------------------------------
    # JOIN QUEUE
    # ---------------------------------------------------------

    def join_queue(self, data):

        name = data.get("name", [""])[0].strip()

        phone = data.get("phone", [""])[0].strip()

        service_id = data.get("service_id", [""])[0]

        if not name or not service_id:

            self.send_json({
                "error": "Name and service are required"
            }, 400)

            return

        try:

            service_id = int(service_id)

        except ValueError:

            self.send_json({
                "error": "Invalid service"
            }, 400)

            return

        try:

            engine = QueueEngine()

            result = engine.join_queue(
                name,
                phone,
                service_id
            )

            queue_id = result["queue_id"]

            # IMPORTANT:
            # Redirect after POST.
            #
            # This prevents browser refresh from
            # submitting the JOIN QUEUE form again.

            self.redirect(
                f"/status?id={queue_id}"
            )

        except Exception as error:

            self.send_json({
                "error": str(error)
            }, 500)

    # ---------------------------------------------------------
    # CUSTOMER STATUS PAGE
    # ---------------------------------------------------------

    def status_page(self, query):

            queue_id_list = query.get("id")

            if not queue_id_list:

              self.send_html(
                  "<h1>Queue entry not found.</h1>",
                  404
              )

              return

            try:

              queue_id = int(queue_id_list[0])

            except (ValueError, TypeError):

              self.send_html(
                  "<h1>Invalid queue ID.</h1>",
                  400
              )

              return

            connection = get_connection()

            queue = connection.execute(
              """
              SELECT
                  q.id,
                  q.token,
                  q.status,
                  c.name AS customer_name,
                  s.name AS service_name
              FROM queue_entries q
              JOIN customers c
                  ON q.customer_id = c.id
              JOIN services s
                  ON q.service_id = s.id
              WHERE q.id = ?
              """,
              (queue_id,)
            ).fetchone()

            if queue is None:

              connection.close()

              self.send_html(
                  "<h1>Queue entry not found.</h1>",
                  404
              )

              return

          # ---------------------------------------------------------
          # GET CURRENT ETA
          # ---------------------------------------------------------

            eta = calculate_eta(queue_id)

            if eta is None:

              connection.close()

              self.send_html(
                  "<h1>Unable to calculate queue status.</h1>",
                  500
              )

              return

            people_ahead = eta["people_ahead"]

            estimated_wait = eta[
              "estimated_wait_minutes"
          ]

            active_counters = eta[
              "active_counters"
          ]

          # ---------------------------------------------------------
          # CHECK WHETHER CUSTOMER ALREADY HAS A REMINDER
          # ---------------------------------------------------------

            reminder = connection.execute(
              """
              SELECT
                  reminder_minutes,
                  sent
              FROM notifications
              WHERE queue_entry_id = ?
              AND reminder_minutes IS NOT NULL
              ORDER BY id DESC
              LIMIT 1
              """,
              (queue_id,)
          ).fetchone()

            connection.close()

          # ---------------------------------------------------------
          # CUSTOMER INFORMATION
          # ---------------------------------------------------------

            customer_name = html.escape(
              queue["customer_name"]
          )

            token = html.escape(
              queue["token"]
          )

            service_name = html.escape(
              queue["service_name"]
          )

            status = queue["status"].upper()

          # ---------------------------------------------------------
          # NOTIFICATION
          # ---------------------------------------------------------

            notification_message = ""

            connection = get_connection()

            notification = connection.execute(
              """
              SELECT message
              FROM notifications
              WHERE queue_entry_id = ?
              AND sent = 1
              ORDER BY id DESC
              LIMIT 1
              """,
              (queue_id,)
          ).fetchone()

            connection.close()

            if notification:

              notification_message = f"""
              <div class="notification">
                  🔔 <strong>Notification</strong>
                  <p>{html.escape(notification["message"])}</p>
              </div>
              """

          # ---------------------------------------------------------
          # STATUS MESSAGE
          # ---------------------------------------------------------

            if queue["status"] == "serving":

              message = """
              <div class="serving">
                  🎉 IT'S YOUR TURN!
              </div>
              """

            elif queue["status"] == "completed":

              message = """
              <div class="completed">
                  ✅ Service completed.
              </div>
              """

            elif queue["status"] == "no_show":

              message = """
              <div class="completed">
                  ❌ You were marked as no-show.
              </div>
              """

            else:

              message = """
              <div class="waiting">
                  🟢 You are in the queue
              </div>
              """

          # ---------------------------------------------------------
          # REMINDER SECTION
          # ---------------------------------------------------------

            reminder_section = ""

            if queue["status"] == "waiting":

              if reminder is not None:

                  selected_minutes = reminder[
                      "reminder_minutes"
                  ]

                  if reminder["sent"] == 1:

                      reminder_section = f"""
                      <div class="reminder-set">

                          <strong>🔔 Reminder sent</strong>

                          <p>
                              Your {selected_minutes}-minute
                              reminder has been triggered.
                          </p>

                      </div>
                      """

                  else:

                      reminder_section = f"""
                      <div class="reminder-set">

                          <strong>✅ Reminder set</strong>

                          <p>
                              You selected a reminder
                              {selected_minutes} minutes
                              before your turn.
                          </p>

                      </div>
                      """

              else:

                  # Build reminder options based on ETA

                  reminder_options = ""

                  if estimated_wait >= 10:

                      reminder_options += """
                      <option value="10">
                          10 minutes before
                      </option>
                      """

                  if estimated_wait >= 20:

                      reminder_options += """
                      <option value="20">
                          20 minutes before
                      </option>
                      """

                  if estimated_wait >= 30:

                      reminder_options += """
                      <option value="30">
                          30 minutes before
                      </option>
                      """

                  if reminder_options:

                      reminder_section = f"""
                      <div class="reminder">

                          <h3>
                              🔔 Set a Reminder
                          </h3>

                          <p>
                              Choose when you want to be
                              reminded before your turn.
                          </p>

                          <form method="POST"
                                action="/remind">

                              <input
                                  type="hidden"
                                  name="queue_id"
                                  value="{queue_id}"
                              >

                              <select
                                  name="reminder_minutes"
                                  required
                              >

                                  {reminder_options}

                              </select>

                              <br><br>

                              <button type="submit">
                                  🔔 Set Reminder
                              </button>

                          </form>

                      </div>
                      """

                  else:

                      reminder_section = """
                      <div class="reminder-set">

                          <strong>
                              ⏱️ Your turn is approaching.
                          </strong>

                          <p>
                              Your estimated waiting time
                              is less than 10 minutes.
                          </p>

                      </div>
                      """

          # ---------------------------------------------------------
          # HTML PAGE
          # ---------------------------------------------------------

            page = f"""
      <!DOCTYPE html>

      <html>

      <head>

      <meta charset="UTF-8">

      <meta name="viewport"
            content="width=device-width, initial-scale=1.0">

      <meta http-equiv="refresh" content="10">

      <title>{token} - QueueLess</title>

      <style>

      body {{

          font-family: Arial, sans-serif;

          background: #f4f6f8;

          margin: 0;

          padding: 30px 20px;

          text-align: center;

      }}

      .container {{

          max-width: 550px;

          margin: auto;

      }}

      .card {{

          background: white;

          padding: 35px;

          border-radius: 18px;

          box-shadow:
              0 4px 20px rgba(0,0,0,0.08);

      }}

      .token {{

          font-size: 65px;

          font-weight: bold;

          margin: 25px 0;

      }}

      .service {{

          color: #666;

      }}

      .stat {{

          margin: 20px 0;

      }}

      .number {{

          font-size: 32px;

          font-weight: bold;

      }}

      .waiting {{

          padding: 15px;

          border-radius: 8px;

          margin: 20px 0;

          background: #eef8ee;

      }}

      .serving {{

          padding: 20px;

          border-radius: 8px;

          margin: 20px 0;

          background: #e8f0ff;

          font-size: 22px;

          font-weight: bold;

      }}

      .completed {{

          padding: 20px;

          border-radius: 8px;

          margin: 20px 0;

          background: #eee;

      }}

      .reminder {{

          margin-top: 25px;

          padding: 20px;

          border-radius: 12px;

          background: #f8f8f8;

      }}

      .reminder-set {{

          margin-top: 25px;

          padding: 20px;

          border-radius: 12px;

          background: #eef8ee;

      }}

      select {{

          padding: 12px;

          border-radius: 8px;

          border: 1px solid #ccc;

          font-size: 16px;

      }}

      button {{

          padding: 14px 25px;

          border: none;

          border-radius: 8px;

          background: #111;

          color: white;

          cursor: pointer;

          font-size: 15px;

      }}

      button:hover {{

          opacity: 0.85;

      }}

      .notification {{

          background: #fff3cd;

          border: 1px solid #ffc107;

          border-radius: 10px;

          padding: 15px;

          margin: 20px 0;

          text-align: left;

      }}

      </style>

      </head>

      <body>

      <div class="container">

          <div class="card">

              <h1>QueueLess</h1>

              <p>
                  Welcome, {customer_name}
              </p>

              <p class="service">
                  {service_name}
              </p>

              <div class="token">
                  {token}
              </div>

              {notification_message}

              {message}

              <div class="stat">

                  <p>People ahead</p>

                  <div class="number">
                      {people_ahead}
                  </div>

              </div>

              <div class="stat">

                  <p>Estimated waiting time</p>

                  <div class="number">
                      {estimated_wait} min
                  </div>

              </div>

              <div class="stat">

                  <p>Active counters</p>

                  <div class="number">
                      {active_counters}
                  </div>

              </div>

              {reminder_section}

              <p style="color:#777; margin-top:25px;">

                  This page automatically refreshes.

              </p>

          </div>

      </div>

      </body>

      </html>
      """
            self.send_html(page)
          # ---------------------------------------------------------
          # MANAGEMENT DASHBOARD
          # ---------------------------------------------------------

    def management_page(self):

        connection = get_connection()

        queue = connection.execute(
            """
            SELECT
                q.id,
                q.token,
                c.name AS customer_name,
                s.name AS service_name,
                q.status,
                q.counter_id,
                q.joined_at
            FROM queue_entries q
            JOIN customers c
                ON q.customer_id = c.id
            JOIN services s
                ON q.service_id = s.id
            WHERE q.status IN
                ('waiting', 'accepted', 'serving')
            ORDER BY q.joined_at ASC
            """
        ).fetchall()

        counters = connection.execute(
            """
            SELECT id, name, status
            FROM counters
            ORDER BY id
            """
        ).fetchall()

        analytics = connection.execute(
            """
            SELECT
                COUNT(
                    CASE
                        WHEN status = 'completed'
                        THEN 1
                    END
                ) AS total_served,

                COUNT(
                    CASE
                        WHEN status = 'no_show'
                        THEN 1
                    END
                ) AS total_no_show,

                AVG(
                    CASE
                        WHEN status = 'completed'
                        AND started_at IS NOT NULL
                        AND completed_at IS NOT NULL
                        THEN
                            (
                                julianday(completed_at)
                                - julianday(started_at)
                            ) * 24 * 60
                    END
                ) AS avg_service,

                AVG(
                    CASE
                        WHEN status = 'completed'
                        AND joined_at IS NOT NULL
                        AND started_at IS NOT NULL
                        THEN
                            (
                                julianday(started_at)
                                - julianday(joined_at)
                            ) * 24 * 60
                    END
                ) AS avg_wait

            FROM queue_entries
            """
        ).fetchone()

        connection.close()

        total_served = analytics["total_served"] or 0
        total_no_show = analytics["total_no_show"] or 0

        avg_service = (
            round(analytics["avg_service"], 1)
            if analytics["avg_service"] is not None
            else 0
        )

        avg_wait = (
            round(analytics["avg_wait"], 1)
            if analytics["avg_wait"] is not None
            else 0
        )

        waiting = sum(
            1
            for item in queue
            if item["status"] == "waiting"
        )

        serving = sum(
            1
            for item in queue
            if item["status"] == "serving"
        )

        rows = ""

        for item in queue:

            action = ""

            if item["status"] == "waiting":

                action = f"""
                <div class="actions">

                    <form method="POST"
                          action="/call-next">

                        <input
                            type="hidden"
                            name="queue_id"
                            value="{item["id"]}"
                        >

                        <button
                            type="submit"
                            class="btn primary">
                            CALL
                        </button>

                    </form>

                    <form method="POST"
                          action="/no-show">

                        <input
                            type="hidden"
                            name="queue_id"
                            value="{item["id"]}"
                        >

                        <button
                            type="submit"
                            class="btn danger">
                            NO-SHOW
                        </button>

                    </form>

                </div>
                """

            elif item["status"] == "serving":

                action = f"""
                <form method="POST"
                      action="/complete-service">

                    <input
                        type="hidden"
                        name="queue_id"
                        value="{item["id"]}"
                    >

                    <button
                        type="submit"
                        class="btn complete">
                        COMPLETE
                    </button>

                </form>
                """

            rows += f"""
            <tr>

                <td>
                    <strong>
                        {html.escape(item["token"])}
                    </strong>
                </td>

                <td>
                    {html.escape(item["customer_name"])}
                </td>

                <td>
                    {html.escape(item["service_name"])}
                </td>

                <td>
                    <span class="status {item["status"]}">
                        {item["status"].upper()}
                    </span>
                </td>

                <td>
                    {item["counter_id"] or "-"}
                </td>

                <td>
                    {action}
                </td>

            </tr>
            """

        if not rows:

            rows = """
            <tr>

                <td
                    colspan="6"
                    class="empty">

                    No customers currently in the queue.

                </td>

            </tr>
            """

        counter_rows = ""

        for counter in counters:

            status = counter["status"].lower()

            counter_rows += f"""
            <div class="counter-card">

                <div class="counter-top">

                    <div class="counter-name">
                        {html.escape(counter["name"])}
                    </div>

                    <div class="counter-dot {status}">
                    </div>

                </div>

                <div class="counter-status">
                    {counter["status"].upper()}
                </div>

            </div>
            """

        if not counter_rows:

            counter_rows = """
            <div class="empty">
                No counters configured.
            </div>
            """

        page = f"""
    <!DOCTYPE html>

    <html>

    <head>

    <meta charset="UTF-8">

    <meta name="viewport"
          content="width=device-width, initial-scale=1.0">

    <meta http-equiv="refresh"
          content="5">

    <title>QueueLess Management</title>

    <style>

    * {{
        box-sizing: border-box;
    }}

    body {{
        margin: 0;
        background: #f7f7f5;
        color: #242424;
        font-family: Arial, sans-serif;
    }}

    .container {{
        max-width: 1150px;
        margin: auto;
        padding: 35px 22px 50px;
    }}

    /* HEADER */

    .header {{
        display: flex;
        justify-content: space-between;
        align-items: center;
        margin-bottom: 38px;
    }}

    .logo {{
        font-size: 30px;
        font-weight: 700;
        letter-spacing: -0.8px;
    }}

    .header-right {{
        color: #85827b;
        font-size: 14px;
    }}

    /* SECTION */

    .section-title {{
        font-size: 18px;
        font-weight: 600;
        margin-bottom: 15px;
    }}

    /* OVERVIEW */

    .stats {{
        display: grid;
        grid-template-columns:
            repeat(3, 1fr);

        gap: 15px;

        margin-bottom: 28px;
    }}

    .stat-card {{
        background: white;
        border: 1px solid #e4e1da;
        border-radius: 16px;
        padding: 23px;
    }}

    .stat-label {{
        color: #85827b;
        font-size: 14px;
        margin-bottom: 12px;
    }}

    .stat-number {{
        font-size: 32px;
        font-weight: 700;
    }}

    /* MAIN CARD */

    .card {{
        background: white;
        border: 1px solid #e4e1da;
        border-radius: 18px;
        padding: 25px;
        margin-bottom: 25px;
    }}

    .card-title {{
        font-size: 20px;
        font-weight: 600;
        margin-bottom: 20px;
    }}

    /* ANALYTICS */

    .analytics {{
        display: grid;

        grid-template-columns:
            repeat(4, 1fr);

        gap: 12px;
    }}

    .analytics-item {{
        background: #fafaf8;
        border: 1px solid #ebe8e2;
        border-radius: 12px;
        padding: 17px;
    }}

    .analytics-label {{
        color: #85827b;
        font-size: 13px;
        margin-bottom: 9px;
    }}

    .analytics-value {{
        font-size: 22px;
        font-weight: 700;
    }}

    /* TABLE */

    .table-wrapper {{
        overflow-x: auto;
    }}

    table {{
        width: 100%;
        border-collapse: collapse;
    }}

    th {{
        text-align: left;
        padding: 12px;
        color: #85827b;
        font-size: 12px;
        font-weight: 600;
        border-bottom: 1px solid #e9e6df;
    }}

    td {{
        padding: 16px 12px;
        border-bottom: 1px solid #efede8;
        font-size: 14px;
    }}

    tr:last-child td {{
        border-bottom: none;
    }}

    /* STATUS */

    .status {{
        display: inline-block;
        padding: 6px 10px;
        border-radius: 20px;
        font-size: 11px;
        font-weight: 700;
    }}

    .status.waiting {{
        background: #f1eee7;
        color: #6e685d;
    }}

    .status.serving {{
        background: #e3eee9;
        color: #477568;
    }}

    .status.accepted {{
        background: #eeeaf2;
        color: #6c5c76;
    }}

    /* BUTTONS */

    .actions {{
        display: flex;
        gap: 7px;
        flex-wrap: wrap;
    }}

    .btn {{
        border: none;
        border-radius: 8px;
        padding: 9px 13px;
        font-size: 11px;
        font-weight: 700;
        cursor: pointer;
    }}

    .primary {{
        background: #4f8275;
        color: white;
    }}

    .primary:hover {{
        background: #426f64;
    }}

    .danger {{
        background: #f3eeee;
        color: #9a5d5d;
    }}

    .complete {{
        background: #eeeeea;
        color: #44443f;
    }}

    /* COUNTERS */

    .counters {{
        display: grid;

        grid-template-columns:
            repeat(auto-fit, minmax(220px, 1fr));

        gap: 14px;
    }}

    .counter-card {{
        border: 1px solid #e4e1da;
        border-radius: 14px;
        padding: 18px;
    }}

    .counter-top {{
        display: flex;
        justify-content: space-between;
        align-items: center;
    }}

    .counter-name {{
        font-size: 16px;
        font-weight: 600;
    }}

    .counter-dot {{
        width: 9px;
        height: 9px;
        border-radius: 50%;
        background: #aaa;
    }}

    .counter-dot.available {{
        background: #5d917f;
    }}

    .counter-dot.serving {{
        background: #c28b55;
    }}

    .counter-status {{
        margin-top: 9px;
        color: #85827b;
        font-size: 12px;
    }}

    /* EMPTY */

    .empty {{
        text-align: center;
        color: #99958c;
        padding: 25px;
    }}

    .refresh {{
        text-align: right;
        color: #aaa69e;
        font-size: 12px;
    }}

    /* MOBILE */

    @media (max-width: 750px) {{

        .container {{
            padding: 25px 15px 40px;
        }}

        .stats {{
            grid-template-columns: 1fr;
        }}

        .analytics {{
            grid-template-columns:
                repeat(2, 1fr);
        }}

        .card {{
            padding: 18px;
        }}

        .header {{
            margin-bottom: 28px;
        }}

        .logo {{
            font-size: 26px;
        }}

    }}

    </style>

    </head>

    <body>

    <div class="container">

        <div class="header">

            <div class="logo">
                QueueLess
            </div>

            <div class="header-right">
                Management
            </div>

        </div>


        <div class="section-title">
            Today's overview
        </div>


        <div class="stats">

            <div class="stat-card">

                <div class="stat-label">
                    Waiting
                </div>

                <div class="stat-number">
                    {waiting}
                </div>

            </div>


            <div class="stat-card">

                <div class="stat-label">
                    Serving
                </div>

                <div class="stat-number">
                    {serving}
                </div>

            </div>


            <div class="stat-card">

                <div class="stat-label">
                    Total active
                </div>

                <div class="stat-number">
                    {len(queue)}
                </div>

            </div>

        </div>


        <div class="card">

            <div class="card-title">
                Queue analysis
            </div>

            <div class="analytics">

                <div class="analytics-item">

                    <div class="analytics-label">
                        Total served
                    </div>

                    <div class="analytics-value">
                        {total_served}
                    </div>

                </div>


                <div class="analytics-item">

                    <div class="analytics-label">
                        No-shows
                    </div>

                    <div class="analytics-value">
                        {total_no_show}
                    </div>

                </div>


                <div class="analytics-item">

                    <div class="analytics-label">
                        Average wait
                    </div>

                    <div class="analytics-value">
                        {avg_wait} min
                    </div>

                </div>


                <div class="analytics-item">

                    <div class="analytics-label">
                        Average service
                    </div>

                    <div class="analytics-value">
                        {avg_service} min
                    </div>

                </div>

            </div>

        </div>


        <div class="card">

            <div class="card-title">
                Current queue
            </div>

            <div class="table-wrapper">

                <table>

                    <thead>

                        <tr>

                            <th>
                                Token
                            </th>

                            <th>
                                Customer
                            </th>

                            <th>
                                Service
                            </th>

                            <th>
                                Status
                            </th>

                            <th>
                                Counter
                            </th>

                            <th>
                                Action
                            </th>

                        </tr>

                    </thead>

                    <tbody>

                        {rows}

                    </tbody>

                </table>

            </div>

        </div>


        <div class="card">

            <div class="card-title">
                Counters
            </div>

            <div class="counters">

                {counter_rows}

            </div>

        </div>


        <div class="refresh">
            Dashboard refreshes automatically
        </div>

    </div>

    </body>

    </html>
    """

        self.send_html(page)


    def complete_service(self, data):

        queue_id_list = data.get("queue_id", [""])

        try:
            queue_id = int(queue_id_list[0])

        except (ValueError, TypeError):

            self.send_json({
                "error": "Invalid queue ID"
            }, 400)

            return

        engine = QueueEngine()

        engine.complete_service(queue_id)

        self.redirect("/management")


    def no_show(self, data):

        queue_id_list = data.get("queue_id", [""])

        try:
            queue_id = int(queue_id_list[0])

        except (ValueError, TypeError):

            self.send_json({
                "error": "Invalid queue ID"
            }, 400)

            return

        connection = get_connection()

        queue = connection.execute(
            """
            SELECT id, status, counter_id
            FROM queue_entries
            WHERE id = ?
            """,
            (queue_id,)
        ).fetchone()

        if queue is None:

            connection.close()

            self.send_json({
                "error": "Queue entry not found"
            }, 404)

            return

        if queue["status"] not in (
            "waiting",
            "accepted",
            "serving"
        ):

            connection.close()

            self.send_json({
                "error": "Customer cannot be marked as no-show"
            }, 400)

            return

        connection.execute(
            """
            UPDATE queue_entries
            SET status = 'no_show'
            WHERE id = ?
            """,
            (queue_id,)
        )

        if queue["counter_id"] is not None:

            connection.execute(
                """
                UPDATE counters
                SET status = 'available'
                WHERE id = ?
                """,
                (queue["counter_id"],)
            )

        connection.commit()
        connection.close()

        self.redirect("/management")

    def remind_customer(self, data):

        queue_id_list = data.get(
            "queue_id",
            [""]
        )

        queue_id = queue_id_list[0]

        try:
            queue_id = int(queue_id)

        except (ValueError, TypeError):

            self.send_json({
                "error": "Invalid queue ID"
            }, 400)

            return

        connection = get_connection()

        # Check that the queue entry exists
        queue = connection.execute(
            """
            SELECT id, status
            FROM queue_entries
            WHERE id = ?
            """,
            (queue_id,)
        ).fetchone()

        if queue is None:

            connection.close()

            self.send_json({
                "error": "Queue entry not found"
            }, 404)

            return

        # Do not allow reminders for completed/no-show customers
        if queue["status"] in ("completed", "no_show"):

            connection.close()

            self.send_json({
                "error": "Reminder cannot be set for this customer"
            }, 400)

            return

        reminder_value = data.get("reminder_minutes", [""])[0]

        try:
            reminder_minutes = int(reminder_value)
        except (ValueError, TypeError):
            connection.close()
            self.send_json({
                "error": "Invalid reminder time"
            }, 400)
            return

        if reminder_minutes not in (10, 20, 30):
            connection.close()
            self.send_json({
                "error": "Reminder must be 10, 20, or 30 minutes"
            }, 400)
            return

        # Check whether the selected reminder is already enabled
        existing = connection.execute(
            """
            SELECT id
            FROM notifications
            WHERE queue_entry_id = ?
            AND reminder_minutes = ?
            AND sent = 0
            LIMIT 1
            """,
            (queue_id, reminder_minutes)
        ).fetchone()

        if existing:

            connection.close()

            self.redirect(
                f"/status?id={queue_id}"
            )

            return

        # Create the customer's selected reminder
        connection.execute(
            """
            INSERT INTO notifications
            (
                queue_entry_id,
                message,
                reminder_minutes,
                sent,
                created_at
            )
            VALUES (?, ?, ?, ?, ?)
            """,
            (
                queue_id,
                f"🔔 Reminder enabled. You will be notified approximately {reminder_minutes} minutes before your turn.",
                reminder_minutes,
                0,
                datetime.now().isoformat(
                    timespec="seconds"
                )
            )
        )

        connection.commit()
        connection.close()

        # Return to customer status page
        self.redirect(
            f"/status?id={queue_id}"
        )


# -------------------------------------------------------------
# AUTOMATIC REMINDER CHECKER
# -------------------------------------------------------------

def reminder_checker():

    while True:

        try:

            connection = get_connection()

            reminders = connection.execute(
                """
                SELECT
                    id,
                    queue_entry_id,
                    reminder_minutes
                FROM notifications
                WHERE reminder_minutes IS NOT NULL
                AND sent = 0
                """
            ).fetchall()

            connection.close()

            for reminder in reminders:

                eta = calculate_eta(
                    reminder["queue_entry_id"]
                )

                if eta is None:
                    continue

                estimated_wait = eta[
                    "estimated_wait_minutes"
                ]

                reminder_minutes = reminder[
                    "reminder_minutes"
                ]

                # Trigger when ETA reaches the
                # reminder time selected by customer
                if estimated_wait <= reminder_minutes:

                    if estimated_wait <= 0:

                        message = (
                            "🎉 Your turn is now! "
                            "Please proceed to the counter."
                        )

                    else:

                        message = (
                            f"🔔 Your turn is approximately "
                            f"{round(estimated_wait)} minutes away. "
                            "Please start making your way back."
                        )

                    connection = get_connection()

                    cursor = connection.execute(
                        """
                        UPDATE notifications
                        SET
                            message = ?,
                            sent = 1
                        WHERE id = ?
                        AND sent = 0
                        """,
                        (
                            message,
                            reminder["id"]
                        )
                    )

                    connection.commit()
                    connection.close()

                    if cursor.rowcount > 0:

                        print(
                            f"Reminder triggered: "
                            f"queue={reminder['queue_entry_id']}, "
                            f"selected={reminder_minutes} min, "
                            f"eta={estimated_wait} min"
                        )

        except Exception as e:

            print(
                "Reminder checker error:",
                e
            )

        time.sleep(30)
           
            
        
# -------------------------------------------------------------
# START SERVER
# -------------------------------------------------------------

def main():

    initialize_database()

    reminder_thread = threading.Thread(
        target=reminder_checker,
        daemon=True
    )

    reminder_thread.start()

    server = ThreadingHTTPServer(
        (HOST, PORT),
        QueueLessHandler
    )

    print(
        f"QueueLess running on port {PORT}"
    )

    print(
        f"Customer:   http://localhost:{PORT}/"
    )

    print(
        f"Management: http://localhost:{PORT}/management"
    )

    try:

        server.serve_forever()

    except KeyboardInterrupt:

        print("\nQueueLess stopped.")

    finally:

        server.server_close()


if __name__ == "__main__":
    main()