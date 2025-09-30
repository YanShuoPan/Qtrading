import sqlite3

conn = sqlite3.connect("data/taiex.sqlite")
cur = conn.cursor()

# 1) 列出所有資料表
cur.execute("SELECT name FROM sqlite_master WHERE type='table'")
print("Tables:", cur.fetchall())

# 2) 列出某表 schema
cur.execute("PRAGMA table_info(subscribers)")
print("subscribers columns:", cur.fetchall())

# 3) 看看前 5 筆
for row in cur.execute("SELECT * FROM subscribers LIMIT 5"):
    print(row)

conn.close()