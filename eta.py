from database import get_connection
from statistics import mean


def get_active_counter_count():
    connection = get_connection()

    row = connection.execute(
        """
        SELECT COUNT(*) AS count
        FROM counters
        WHERE status IN ('available', 'busy')
        """
    ).fetchone()

    connection.close()

    return max(row["count"], 1)


def get_average_service_time(service_id):

    connection = get_connection()

    # Get the configured average service time
    service = connection.execute(
        """
        SELECT average_service_minutes
        FROM services
        WHERE id = ?
        """,
        (service_id,)
    ).fetchone()

    # Get recent completed services
    rows = connection.execute(
        """
        SELECT
            (julianday(completed_at) - julianday(started_at)) * 24 * 60
            AS duration
        FROM queue_entries
        WHERE service_id = ?
        AND status = 'completed'
        AND started_at IS NOT NULL
        AND completed_at IS NOT NULL
        ORDER BY completed_at DESC
        LIMIT 5
        """,
        (service_id,)
    ).fetchall()

    connection.close()

    # Only accept realistic service durations
    durations = [
        row["duration"]
        for row in rows
        if row["duration"] is not None
        and 1 <= row["duration"] <= 30
    ]

    # Use recent real service times if available
    if durations:
        return mean(durations)

    # Otherwise use the service's configured average
    if service and service["average_service_minutes"]:
        return service["average_service_minutes"]

    # Final fallback
    return 10


def calculate_eta(queue_id):

    connection = get_connection()

    # Get customer information
    customer = connection.execute(
        """
        SELECT
            service_id,
            joined_at,
            status
        FROM queue_entries
        WHERE id = ?
        """,
        (queue_id,)
    ).fetchone()

    if customer is None:

        connection.close()

        return None

    # Count customers waiting before this customer
    ahead = connection.execute(
        """
        SELECT COUNT(*) AS count
        FROM queue_entries
        WHERE service_id = ?
        AND status IN ('waiting', 'accepted')
        AND joined_at < ?
        """,
        (
            customer["service_id"],
            customer["joined_at"]
        )
    ).fetchone()["count"]

    # Count customers currently being served
    serving = connection.execute(
        """
        SELECT COUNT(*) AS count
        FROM queue_entries
        WHERE service_id = ?
        AND status = 'serving'
        """,
        (customer["service_id"],)
    ).fetchone()["count"]

    connection.close()

    # Number of active counters
    counters = get_active_counter_count()

    # Average service time
    service_time = get_average_service_time(
        customer["service_id"]
    )

    # Customer is already being served
    if customer["status"] == "serving":

        estimated_minutes = 0

    # Customer has already completed service
    elif customer["status"] == "completed":

        estimated_minutes = 0

    # Customer is waiting
    else:

        # Customers who need to be handled before this customer
        customers_before = ahead + serving

        # Nobody before this customer
        if customers_before == 0:

            estimated_minutes = 0

        else:

            # Customers are handled in parallel
            # according to the number of active counters
            batches = (
                customers_before + counters - 1
            ) // counters

            estimated_minutes = (
                batches * service_time
            )

    return {
        "people_ahead": ahead,
        "active_counters": counters,
        "average_service_minutes": round(
            service_time,
            1
        ),
        "estimated_wait_minutes": round(
            estimated_minutes,
            1
        )
    }