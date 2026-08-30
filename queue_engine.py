import sqlite3
from datetime import datetime
from database import get_connection


class QueueEngine:

    def _now(self):
        return datetime.now().isoformat(timespec="seconds")

    def create_customer(self, name, phone):
        connection = get_connection()

        cursor = connection.execute(
            """
            INSERT INTO customers (name, phone, created_at)
            VALUES (?, ?, ?)
            """,
            (
                name,
                phone,
                self._now()
            )
        )

        customer_id = cursor.lastrowid

        connection.commit()
        connection.close()

        return customer_id

    def generate_token(self, service_id):

        connection = get_connection()

        row = connection.execute(
            """
            SELECT token
            FROM queue_entries
            WHERE service_id = ?
            AND token LIKE 'Q-%'
            ORDER BY id DESC
            LIMIT 1
            """,
            (service_id,)
        ).fetchone()

        connection.close()

        if row is None:
            token_number = 1

        else:
            try:
                token_number = int(
                    row["token"].replace("Q-", "")
                ) + 1

            except (ValueError, TypeError):
                token_number = 1

        return f"Q-{token_number:03d}"
    
    def join_queue(self, customer_name, phone, service_id):

        customer_id = self.create_customer(
            customer_name,
            phone
        )

        now = self._now()

        connection = get_connection()

        token = self.generate_token(service_id)

        cursor = connection.execute(
            """
            INSERT INTO queue_entries
            (
                token,
                customer_id,
                service_id,
                status,
                joined_at
            )
            VALUES (?, ?, ?, 'waiting', ?)
            """,
            (
                token,
                customer_id,
                service_id,
                now
            )
        )

        queue_id = cursor.lastrowid

        connection.execute(
            """
            INSERT INTO queue_events
            (
                queue_entry_id,
                event_type,
                details,
                created_at
            )
            VALUES (?, 'joined', 'Customer joined the queue', ?)
            """,
            (
                queue_id,
                now
            )
        )

        connection.commit()
        connection.close()

        return {
            "queue_id": queue_id,
            "token": token,
            "status": "waiting"
        }
    def get_queue(self, service_id=None):

        connection = get_connection()

        if service_id is None:

            rows = connection.execute(
                """
                SELECT
                    q.id,
                    q.token,
                    c.name AS customer_name,
                    q.service_id,
                    q.status,
                    q.counter_id,
                    q.joined_at
                FROM queue_entries q
                JOIN customers c
                    ON c.id = q.customer_id
                WHERE q.status IN
                    ('waiting', 'accepted', 'serving')
                ORDER BY q.joined_at ASC
                """
            ).fetchall()

        else:

            rows = connection.execute(
                """
                SELECT
                    q.id,
                    q.token,
                    c.name AS customer_name,
                    q.service_id,
                    q.status,
                    q.counter_id,
                    q.joined_at
                FROM queue_entries q
                JOIN customers c
                    ON c.id = q.customer_id
                WHERE q.service_id = ?
                AND q.status IN
                    ('waiting', 'accepted', 'serving')
                ORDER BY q.joined_at ASC
                """,
                (service_id,)
            ).fetchall()

        connection.close()

        return [
            dict(row)
            for row in rows
        ]

    def get_position(self, queue_id):

        connection = get_connection()

        current = connection.execute(
            """
            SELECT joined_at, service_id
            FROM queue_entries
            WHERE id = ?
            """,
            (queue_id,)
        ).fetchone()

        if current is None:

            connection.close()

            return None

        position = connection.execute(
            """
            SELECT COUNT(*) AS position
            FROM queue_entries
            WHERE service_id = ?
            AND status IN ('waiting', 'accepted')
            AND joined_at < ?
            """,
            (
                current["service_id"],
                current["joined_at"]
            )
        ).fetchone()["position"]

        connection.close()

        return position + 1

    def accept_customer(self, queue_id):

        return self._update_status(
            queue_id,
            "accepted",
            "Customer request accepted"
        )

    def start_service(self, queue_id, counter_id):

        connection = get_connection()

        now = self._now()

        connection.execute(
            """
            UPDATE queue_entries
            SET
                status = 'serving',
                counter_id = ?,
                started_at = ?
            WHERE id = ?
            """,
            (
                counter_id,
                now,
                queue_id
            )
        )

        connection.execute(
            """
            UPDATE counters
            SET status = 'busy'
            WHERE id = ?
            """,
            (counter_id,)
        )

        connection.execute(
            """
            INSERT INTO queue_events
            (
                queue_entry_id,
                event_type,
                details,
                created_at
            )
            VALUES (?, 'service_started', ?, ?)
            """,
            (
                queue_id,
                f"Service started at counter {counter_id}",
                now
            )
        )

        connection.commit()
        connection.close()

    def complete_service(self, queue_id):

        connection = get_connection()

        now = self._now()

        row = connection.execute(
            """
            SELECT counter_id
            FROM queue_entries
            WHERE id = ?
            """,
            (queue_id,)
        ).fetchone()

        connection.execute(
            """
            UPDATE queue_entries
            SET
                status = 'completed',
                completed_at = ?
            WHERE id = ?
            """,
            (
                now,
                queue_id
            )
        )

        if row and row["counter_id"]:

            connection.execute(
                """
                UPDATE counters
                SET status = 'available'
                WHERE id = ?
                """,
                (row["counter_id"],)
            )

        connection.execute(
            """
            INSERT INTO queue_events
            (
                queue_entry_id,
                event_type,
                details,
                created_at
            )
            VALUES (?, 'completed', 'Service completed', ?)
            """,
            (
                queue_id,
                now
            )
        )

        connection.commit()
        connection.close()

    def mark_no_show(self, queue_id):

        return self._update_status(
            queue_id,
            "no_show",
            "Customer marked as no-show"
        )

    def _update_status(
        self,
        queue_id,
        status,
        event_details
    ):

        connection = get_connection()

        now = self._now()

        cursor = connection.execute(
            """
            UPDATE queue_entries
            SET status = ?
            WHERE id = ?
            """,
            (
                status,
                queue_id
            )
        )

        if cursor.rowcount == 0:

            connection.close()

            return False

        connection.execute(
            """
            INSERT INTO queue_events
            (
                queue_entry_id,
                event_type,
                details,
                created_at
            )
            VALUES (?, ?, ?, ?)
            """,
            (
                queue_id,
                status,
                event_details,
                now
            )
        )

        connection.commit()
        connection.close()

        return True