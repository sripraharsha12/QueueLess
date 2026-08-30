import sqlite3
from pathlib import Path

DB_PATH = Path(__file__).parent / "queueless.db"


def get_connection():
    connection = sqlite3.connect(DB_PATH)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys = ON")
    return connection


def initialize_database():
    connection = get_connection()

    connection.executescript("""
        CREATE TABLE IF NOT EXISTS services (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            average_service_minutes INTEGER NOT NULL DEFAULT 10,
            active INTEGER NOT NULL DEFAULT 1
        );

        CREATE TABLE IF NOT EXISTS counters (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            status TEXT NOT NULL DEFAULT 'offline'
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
            FOREIGN KEY (customer_id) REFERENCES customers(id),
            FOREIGN KEY (service_id) REFERENCES services(id),
            FOREIGN KEY (counter_id) REFERENCES counters(id)
        );

        CREATE TABLE IF NOT EXISTS notifications (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            queue_entry_id INTEGER NOT NULL,
            message TEXT NOT NULL,
            reminder_minutes INTEGER,
            sent INTEGER NOT NULL DEFAULT 0,
            created_at TEXT NOT NULL,
            FOREIGN KEY (queue_entry_id) REFERENCES queue_entries(id)
        );

        CREATE TABLE IF NOT EXISTS queue_events (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            queue_entry_id INTEGER,
            event_type TEXT NOT NULL,
            details TEXT,
            created_at TEXT NOT NULL,
            FOREIGN KEY (queue_entry_id) REFERENCES queue_entries(id)
        );
    """)

    connection.commit()
    connection.close()

def reset_demo_data():
    connection = get_connection()

    # Delete test-related data first because of foreign keys
    connection.execute("DELETE FROM notifications")
    connection.execute("DELETE FROM queue_events")
    connection.execute("DELETE FROM queue_entries")
    connection.execute("DELETE FROM customers")

    # Reset both counters to available
    connection.execute("""
        UPDATE counters
        SET status = 'available'
    """)

    # Reset auto-increment counters
    connection.execute("""
        DELETE FROM sqlite_sequence
        WHERE name IN (
            'notifications',
            'queue_events',
            'queue_entries',
            'customers'
        )
    """)

    connection.commit()
    connection.close()

    print("Demo queue data cleared successfully.")

if __name__ == "__main__":
    initialize_database()
    print("QueueLess database initialized successfully.")