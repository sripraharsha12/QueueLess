from database import get_connection, initialize_database
from queue_engine import QueueEngine


initialize_database()

connection = get_connection()

# Create a test service
connection.execute(
    """
    INSERT INTO services (name, average_service_minutes)
    VALUES (?, ?)
    """,
    ("General Service", 10)
)

service_id = connection.execute(
    "SELECT last_insert_rowid()"
).fetchone()[0]

# Create test counters
connection.execute(
    "INSERT INTO counters (name, status) VALUES (?, ?)",
    ("Counter 1", "available")
)

connection.execute(
    "INSERT INTO counters (name, status) VALUES (?, ?)",
    ("Counter 2", "available")
)

connection.commit()
connection.close()


# Test queue
engine = QueueEngine()

result = engine.join_queue(
    "Test Customer",
    service_id
)

print("\n=== QUEUELESS TEST ===")
print("Customer: Test Customer")
print("Token:", result["token"])
print("Status:", result["status"])

position = engine.get_position(result["queue_id"])

print("Position:", position)

print("\nCurrent Queue:")

for customer in engine.get_queue(service_id):
    print(
        customer["token"],
        "-",
        customer["customer_name"],
        "-",
        customer["status"]
    )

print("\nQueue Engine is working! ✅")