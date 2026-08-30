from database import initialize_database, get_connection
from queue_engine import QueueEngine
from eta import calculate_eta


initialize_database()

connection = get_connection()

# Create a service
connection.execute(
    """
    INSERT INTO services (name, average_service_minutes)
    VALUES (?, ?)
    """,
    ("Test Service", 10)
)

service_id = connection.execute(
    "SELECT last_insert_rowid()"
).fetchone()[0]

# Create two counters
connection.execute(
    """
    INSERT INTO counters (name, status)
    VALUES (?, ?)
    """,
    ("Counter 1", "available")
)

connection.execute(
    """
    INSERT INTO counters (name, status)
    VALUES (?, ?)
    """,
    ("Counter 2", "available")
)

connection.commit()
connection.close()


# Add customers
engine = QueueEngine()

first = engine.join_queue("Customer 1", service_id)
second = engine.join_queue("Customer 2", service_id)
third = engine.join_queue("Customer 3", service_id)


# Calculate ETA for third customer
eta = calculate_eta(third["queue_id"])

print("\n=== QUEUELESS ETA TEST ===")

print("Token:", third["token"])
print("People ahead:", eta["people_ahead"])
print("Active counters:", eta["active_counters"])
print("Average service time:", eta["average_service_minutes"], "minutes")
print("Estimated wait:", eta["estimated_wait_minutes"], "minutes")

print("\nETA Engine is working! ✅")