import sqlite3

# Connect to database
conn = sqlite3.connect("data/taiex.sqlite")
cur = conn.cursor()

# Read line_id.txt and parse the data
line_ids = {}
with open("line_id.txt", "r", encoding="utf-8") as f:
    for line in f:
        line = line.strip()
        if line and ":" in line:
            name, user_id = line.split(":", 1)
            name = name.strip()
            user_id = user_id.strip()
            line_ids[user_id] = name

print(f"Found {len(line_ids)} LINE IDs to update:")
for user_id, name in line_ids.items():
    print(f"  {name}: {user_id}")

# Update display_name for each user_id
updated_count = 0
for user_id, name in line_ids.items():
    cur.execute(
        "UPDATE subscribers SET display_name = ? WHERE user_id = ?",
        (name, user_id)
    )
    if cur.rowcount > 0:
        updated_count += cur.rowcount
        print(f"Updated {name} for user_id: {user_id}")
    else:
        print(f"User ID not found in database: {user_id} ({name})")
        # Optionally add new subscriber if not exists
        response = input(f"Add {name} ({user_id}) as new subscriber? (y/n): ")
        if response.lower() == 'y':
            cur.execute(
                "INSERT INTO subscribers (user_id, display_name, followed_at, active) VALUES (?, ?, datetime('now'), 1)",
                (user_id, name)
            )
            print(f"Added new subscriber: {name}")
            updated_count += 1

# Commit changes
conn.commit()
print(f"\nTotal updates made: {updated_count}")

# Verify the updates
print("\nCurrent subscribers in database:")
cur.execute("SELECT user_id, display_name, followed_at, active FROM subscribers")
for row in cur.fetchall():
    print(f"  {row[1] or 'Unknown'}: {row[0]} (joined: {row[2]}, active: {row[3]})")

conn.close()
print("\nDatabase update completed!")