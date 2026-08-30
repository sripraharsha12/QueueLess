from database import get_connection

connection = get_connection()

tables = connection.execute(
    """
    SELECT name
    FROM sqlite_master
    WHERE type = 'table'
    AND name NOT LIKE 'sqlite_%'
    """
).fetchall()

for table in tables:
    print(table["name"])

connection.close()