import os
import sqlite3
import argparse
import time
import random
import sys

CATEGORIES = [
    "Mains & Entrees", "Pasta & Italian", "Breakfast & Brunch",
    "Soups & Stews", "Salads & Bowls", "Desserts & Sweets", "Quick & Easy"
]

DISHES = [
    "Creamy Tuscan Chicken", "Classic Margherita Pizza", "Garlic Butter Steak Bites",
    "Crispy Air-Fryer Salmon", "Authentic Beef Tacos", "Vegetable Pad Thai",
    "Loaded Baked Potato Soup", "Fluffy Blueberry Pancakes", "Avocado Caesar Salad",
    "Chocolate Molten Lava Cake", "Honey Dijon Glazed Pork Chops", "Shrimp Scampi"
]

def get_db_path():
    return os.environ.get('DATABASE_PATH', os.path.join(os.path.dirname(__file__), 'recipe_api', 'recipes.db'))

def ensure_tables(conn):
    cursor = conn.cursor()
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            username TEXT UNIQUE NOT NULL COLLATE NOCASE,
            email TEXT UNIQUE NOT NULL COLLATE NOCASE,
            password_hash TEXT NOT NULL,
            display_name TEXT DEFAULT '',
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            is_active INTEGER DEFAULT 1
        )
    ''')
    cursor.execute('CREATE INDEX IF NOT EXISTS idx_users_username ON users(username)')
    cursor.execute('CREATE INDEX IF NOT EXISTS idx_users_email ON users(email)')

    cursor.execute('''
        CREATE TABLE IF NOT EXISTS sessions (
            token TEXT PRIMARY KEY,
            user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            expires_at TIMESTAMP NOT NULL,
            user_agent TEXT DEFAULT '',
            ip_address TEXT DEFAULT ''
        )
    ''')
    cursor.execute('CREATE INDEX IF NOT EXISTS idx_sessions_user ON sessions(user_id)')

    cursor.execute('''
        CREATE TABLE IF NOT EXISTS recipes (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER DEFAULT 1,
            title TEXT NOT NULL,
            ingredients TEXT NOT NULL,
            instructions TEXT NOT NULL,
            category TEXT DEFAULT 'General',
            is_favorite INTEGER DEFAULT 0,
            prep_time TEXT DEFAULT '',
            cook_time TEXT DEFAULT '',
            difficulty TEXT DEFAULT 'Easy',
            servings TEXT DEFAULT ''
        )
    ''')

    planner_cols = [c[1] for c in cursor.execute("PRAGMA table_info(planner)").fetchall()]
    if not planner_cols:
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS planner (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL DEFAULT 1,
                date_key TEXT NOT NULL,
                breakfast TEXT DEFAULT 'Not planned',
                lunch TEXT DEFAULT 'Not planned',
                dinner TEXT DEFAULT 'Not planned',
                tasks TEXT DEFAULT '',
                notes TEXT DEFAULT '',
                UNIQUE(user_id, date_key)
            )
        ''')
    elif 'user_id' not in planner_cols:
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS planner_v2 (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL DEFAULT 1,
                date_key TEXT NOT NULL,
                breakfast TEXT DEFAULT 'Not planned',
                lunch TEXT DEFAULT 'Not planned',
                dinner TEXT DEFAULT 'Not planned',
                tasks TEXT DEFAULT '',
                notes TEXT DEFAULT '',
                UNIQUE(user_id, date_key)
            )
        ''')
        cursor.execute('''
            INSERT OR IGNORE INTO planner_v2 (user_id, date_key, breakfast, lunch, dinner, tasks, notes)
            SELECT 1, date_key, breakfast, lunch, dinner, tasks, notes FROM planner
        ''')
        cursor.execute('DROP TABLE planner')
        cursor.execute('ALTER TABLE planner_v2 RENAME TO planner')

    cursor.execute('''
        CREATE TABLE IF NOT EXISTS groceries (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER DEFAULT 1,
            item TEXT NOT NULL,
            checked INTEGER DEFAULT 0
        )
    ''')

    # Column migrations
    recipe_cols = [c[1] for c in cursor.execute("PRAGMA table_info(recipes)").fetchall()]
    if 'user_id' not in recipe_cols:
        cursor.execute("ALTER TABLE recipes ADD COLUMN user_id INTEGER DEFAULT 1")
    if 'category' not in recipe_cols:
        cursor.execute("ALTER TABLE recipes ADD COLUMN category TEXT DEFAULT 'General'")
    if 'is_favorite' not in recipe_cols:
        cursor.execute("ALTER TABLE recipes ADD COLUMN is_favorite INTEGER DEFAULT 0")

    grocery_cols = [c[1] for c in cursor.execute("PRAGMA table_info(groceries)").fetchall()]
    if 'user_id' not in grocery_cols:
        cursor.execute("ALTER TABLE groceries ADD COLUMN user_id INTEGER DEFAULT 1")

    cursor.execute('CREATE INDEX IF NOT EXISTS idx_recipes_user ON recipes(user_id)')
    cursor.execute('CREATE INDEX IF NOT EXISTS idx_planner_user_date ON planner(user_id, date_key)')
    cursor.execute('CREATE INDEX IF NOT EXISTS idx_groceries_user ON groceries(user_id)')
    conn.commit()

def seed_database(users_count=500, recipes_per_user=10, db_path=None):
    if not db_path:
        db_path = get_db_path()

    print(f"\n🌱 Database Seeding Tool")
    print(f"📁 Target Database: {db_path}")
    print(f"👥 Users to seed:    {users_count:,}")
    print(f"🍲 Recipes per user: {recipes_per_user:,}")
    print(f"📈 Total Recipes:    {users_count * recipes_per_user:,}")
    print("-" * 50)

    conn = sqlite3.connect(db_path, timeout=30.0)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA synchronous=NORMAL")
    ensure_tables(conn)

    t0 = time.time()
    cursor = conn.cursor()

    # Bulk User Generation
    print("⏳ Inserting users...")
    user_rows = []
    for u in range(1, users_count + 1):
        username = f"seed_user_{u}"
        email = f"user_{u}@benchmark.local"
        pw_hash = "scrypt:32768:8:1$dummy$dummypasswordhashforbenchmarkingpurposes"
        display_name = f"User {u}"
        user_rows.append((username, email, pw_hash, display_name))

    cursor.executemany(
        "INSERT OR IGNORE INTO users (username, email, password_hash, display_name) VALUES (?, ?, ?, ?)",
        user_rows
    )
    conn.commit()

    # Get all user IDs
    users = cursor.execute("SELECT id FROM users WHERE username LIKE 'seed_user_%'").fetchall()
    user_ids = [row[0] for row in users]

    # Bulk Recipe Generation
    print(f"⏳ Generating and inserting {len(user_ids) * recipes_per_user:,} recipes...")
    recipe_rows = []
    planner_rows = []
    grocery_rows = []

    for uid in user_ids:
        for r in range(1, recipes_per_user + 1):
            dish = random.choice(DISHES)
            cat = random.choice(CATEGORIES)
            title = f"{dish} #{r}"
            ingredients = f"- 1 lb {dish.split()[-1]}\n- 2 tbsp butter\n- 1 tsp garlic powder\n- Salt and pepper"
            instructions = f"1) Prepare {dish}.\n2) Cook over medium heat for 20 minutes.\n3) Garnish and enjoy."
            is_fav = 1 if r == 1 else 0
            recipe_rows.append((uid, title, ingredients, instructions, cat, is_fav, "15 mins", "25 mins", "Easy", "4"))

        # Add sample meal planner entries
        for day in [1, 5, 10, 15, 20]:
            date_key = f"2026-09-{day:02d}"
            planner_rows.append((uid, date_key, "Oatmeal with fruit", "Chicken Salad wrap", random.choice(DISHES), "Grocery run", "Family dinner"))

        # Add sample groceries
        grocery_rows.append((uid, "Whole Milk", 0))
        grocery_rows.append((uid, "Fresh Eggs (1 Dozen)", 0))
        grocery_rows.append((uid, "Sourdough Bread", 1))

    cursor.executemany(
        """INSERT INTO recipes (user_id, title, ingredients, instructions, category, is_favorite, prep_time, cook_time, difficulty, servings)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        recipe_rows
    )
    
    cursor.executemany(
        """INSERT OR REPLACE INTO planner (user_id, date_key, breakfast, lunch, dinner, tasks, notes)
           VALUES (?, ?, ?, ?, ?, ?, ?)""",
        planner_rows
    )

    cursor.executemany(
        "INSERT INTO groceries (user_id, item, checked) VALUES (?, ?, ?)",
        grocery_rows
    )

    conn.commit()
    elapsed = time.time() - t0

    # Query Performance Verification
    total_users_in_db = cursor.execute("SELECT COUNT(*) FROM users").fetchone()[0]
    total_recipes_in_db = cursor.execute("SELECT COUNT(*) FROM recipes").fetchone()[0]
    total_plans_in_db = cursor.execute("SELECT COUNT(*) FROM planner").fetchone()[0]
    db_size_mb = os.path.getsize(db_path) / (1024 * 1024)

    # Benchmark individual user query speed on large DB
    test_uid = user_ids[len(user_ids) // 2]
    q_start = time.time()
    user_recipes = cursor.execute("SELECT * FROM recipes WHERE user_id = ? ORDER BY is_favorite DESC, id DESC", (test_uid,)).fetchall()
    q_elapsed_ms = (time.time() - q_start) * 1000

    conn.close()

    print("=" * 50)
    print("✅ DATABASE SEEDING COMPLETE!")
    print("=" * 50)
    print(f"⏱️  Seeding Time:         {elapsed:.2f} seconds")
    print(f"💾 Total Database Size:   {db_size_mb:.2f} MB")
    print(f"👥 Total Users in DB:     {total_users_in_db:,}")
    print(f"🍲 Total Recipes in DB:   {total_recipes_in_db:,}")
    print(f"📅 Total Plans in DB:     {total_plans_in_db:,}")
    print("-" * 50)
    print(f"⚡ User Query Lookup:    {q_elapsed_ms:.3f} ms (Retrieved {len(user_recipes)} recipes)")
    print("=" * 50 + "\n")

def clean_database(db_path=None):
    if not db_path:
        db_path = get_db_path()
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    print("🧹 Cleaning seed test data from database...")
    seed_users = cursor.execute("SELECT id FROM users WHERE username LIKE 'seed_user_%'").fetchall()
    seed_ids = [r[0] for r in seed_users]
    if seed_ids:
        placeholders = ','.join('?' * len(seed_ids))
        cursor.execute(f"DELETE FROM recipes WHERE user_id IN ({placeholders})", seed_ids)
        cursor.execute(f"DELETE FROM planner WHERE user_id IN ({placeholders})", seed_ids)
        cursor.execute(f"DELETE FROM groceries WHERE user_id IN ({placeholders})", seed_ids)
        cursor.execute(f"DELETE FROM users WHERE id IN ({placeholders})", seed_ids)
        conn.commit()
    conn.close()
    print(f"✨ Cleaned {len(seed_ids):,} seed users and their associated data!\n")

if __name__ == '__main__':
    parser = argparse.ArgumentParser(description="Seed database for scale testing")
    parser.add_argument("--users", type=int, default=500, help="Number of users to seed (default: 500)")
    parser.add_argument("--recipes", type=int, default=10, help="Recipes per user (default: 10)")
    parser.add_argument("--clean", action="store_true", help="Remove all seed data from database")
    parser.add_argument("--db", type=str, default=None, help="Path to sqlite recipes.db file")
    args = parser.parse_args()

    if args.clean:
        clean_database(args.db)
    else:
        seed_database(users_count=args.users, recipes_per_user=args.recipes, db_path=args.db)
