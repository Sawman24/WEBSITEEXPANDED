import os
import re
import json
import sqlite3
import secrets
import hashlib
import hmac
from datetime import datetime, timedelta, timezone
from functools import wraps
from fractions import Fraction
import requests
from bs4 import BeautifulSoup
from flask import Flask, request, jsonify, make_response, send_from_directory
from flask_cors import CORS

try:
    from werkzeug.security import generate_password_hash, check_password_hash
except ImportError:
    def generate_password_hash(password, method='scrypt'):
        salt = secrets.token_hex(16)
        h = hashlib.pbkdf2_hmac('sha256', password.encode('utf-8'), salt.encode('utf-8'), 100000).hex()
        return f"pbkdf2:sha256:{salt}:{h}"

    def check_password_hash(p_hash, password):
        try:
            parts = p_hash.split(':')
            if len(parts) == 4 and parts[0] == 'pbkdf2':
                salt = parts[2]
                expected_h = parts[3]
                actual_h = hashlib.pbkdf2_hmac('sha256', password.encode('utf-8'), salt.encode('utf-8'), 100000).hex()
                return hmac.compare_digest(expected_h, actual_h)
            return False
        except Exception:
            return False

def verify_password(password, p_hash):
    try:
        return check_password_hash(p_hash, password)
    except Exception:
        return False


app = Flask(__name__)
# Enable CORS with credentials support for session cookies
CORS(app, supports_credentials=True)

DATABASE = os.environ.get('DATABASE_PATH', os.path.join(os.path.abspath(os.path.dirname(__file__)), 'recipes.db'))
UPLOAD_FOLDER = os.environ.get('UPLOAD_FOLDER', os.path.join(os.path.abspath(os.path.dirname(DATABASE)), 'uploads'))
os.makedirs(UPLOAD_FOLDER, exist_ok=True)

SESSION_COOKIE_NAME = 'recipe_session_token'
SESSION_DURATION_DAYS = 30

def get_db_connection():
    conn = sqlite3.connect(DATABASE, timeout=30.0)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA synchronous=NORMAL")
    conn.execute("PRAGMA foreign_keys=ON")
    conn.row_factory = sqlite3.Row  # Access columns by name
    return conn

def init_db():
    db_dir = os.path.dirname(DATABASE)
    if db_dir and not os.path.exists(db_dir):
        os.makedirs(db_dir, exist_ok=True)

    bundled_db = os.path.join(os.path.abspath(os.path.dirname(__file__)), 'recipes.db')
    if not os.path.exists(DATABASE) and os.path.exists(bundled_db) and os.path.abspath(DATABASE) != bundled_db:
        import shutil
        shutil.copy2(bundled_db, DATABASE)

    conn = get_db_connection()
    cursor = conn.cursor()

    # Users Table
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

    # Sessions Table
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

    # Rate Limiting / Brute Force Prevention Table
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS login_attempts (
            ip_address TEXT PRIMARY KEY,
            attempts INTEGER DEFAULT 0,
            last_attempt TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            locked_until TIMESTAMP
        )
    ''')

    # Recipes Table
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

    # Groceries Table
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS groceries (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER DEFAULT 1,
            item TEXT NOT NULL,
            checked INTEGER DEFAULT 0
        )
    ''')

    # Stickies Table
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS stickies (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER DEFAULT 1,
            content TEXT NOT NULL,
            author TEXT DEFAULT 'Note',
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    ''')

    # Pantry Table
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS pantry (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER DEFAULT 1,
            item TEXT NOT NULL,
            category TEXT DEFAULT 'General',
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    ''')

    # Planner Table (Check schema and auto-migrate to multi-tenant user_id + date_key)
    planner_cols = [col[1] for col in cursor.execute('PRAGMA table_info(planner)').fetchall()]
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
        # Migrate old single-user planner table
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

    # Password Resets Table
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS password_resets (
            token TEXT PRIMARY KEY,
            user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            expires_at TIMESTAMP NOT NULL,
            used INTEGER DEFAULT 0
        )
    ''')
    cursor.execute('CREATE INDEX IF NOT EXISTS idx_password_resets_user ON password_resets(user_id)')

    # Community Food Feed Posts Table
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS community_posts (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            content TEXT NOT NULL,
            image_url TEXT DEFAULT '',
            recipe_id INTEGER REFERENCES recipes(id) ON DELETE SET NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    ''')
    cursor.execute('CREATE INDEX IF NOT EXISTS idx_community_posts_user ON community_posts(user_id)')
    cursor.execute('CREATE INDEX IF NOT EXISTS idx_community_posts_created ON community_posts(created_at DESC)')

    # Post Likes Table
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS post_likes (
            post_id INTEGER NOT NULL REFERENCES community_posts(id) ON DELETE CASCADE,
            user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            PRIMARY KEY (post_id, user_id)
        )
    ''')
    cursor.execute('CREATE INDEX IF NOT EXISTS idx_post_likes_post ON post_likes(post_id)')

    # Post Comments Table
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS post_comments (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            post_id INTEGER NOT NULL REFERENCES community_posts(id) ON DELETE CASCADE,
            user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            comment TEXT NOT NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    ''')
    cursor.execute('CREATE INDEX IF NOT EXISTS idx_post_comments_post ON post_comments(post_id)')

    # Friendships & Social Connections Table
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS friendships (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            friend_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            status TEXT DEFAULT 'accepted',
            is_close_friend INTEGER DEFAULT 0,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(user_id, friend_id)
        )
    ''')
    cursor.execute('CREATE INDEX IF NOT EXISTS idx_friendships_user ON friendships(user_id)')
    cursor.execute('CREATE INDEX IF NOT EXISTS idx_friendships_friend ON friendships(friend_id)')

    # Moderation & Content Reports Table
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS post_reports (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            post_id INTEGER REFERENCES community_posts(id) ON DELETE CASCADE,
            comment_id INTEGER REFERENCES post_comments(id) ON DELETE CASCADE,
            reported_by INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            reason TEXT DEFAULT 'inappropriate',
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(post_id, reported_by),
            UNIQUE(comment_id, reported_by)
        )
    ''')
    cursor.execute('CREATE INDEX IF NOT EXISTS idx_post_reports_post ON post_reports(post_id)')
    cursor.execute('CREATE INDEX IF NOT EXISTS idx_post_reports_comment ON post_reports(comment_id)')

    # Auto-migrate columns if tables already exist
    recipe_columns = [col[1] for col in cursor.execute('PRAGMA table_info(recipes)').fetchall()]
    if 'user_id' not in recipe_columns:
        cursor.execute("ALTER TABLE recipes ADD COLUMN user_id INTEGER DEFAULT 1")
    if 'category' not in recipe_columns:
        cursor.execute("ALTER TABLE recipes ADD COLUMN category TEXT DEFAULT 'General'")
    if 'is_favorite' not in recipe_columns:
        cursor.execute("ALTER TABLE recipes ADD COLUMN is_favorite INTEGER DEFAULT 0")
    if 'prep_time' not in recipe_columns:
        cursor.execute("ALTER TABLE recipes ADD COLUMN prep_time TEXT DEFAULT ''")
    if 'cook_time' not in recipe_columns:
        cursor.execute("ALTER TABLE recipes ADD COLUMN cook_time TEXT DEFAULT ''")
    if 'difficulty' not in recipe_columns:
        cursor.execute("ALTER TABLE recipes ADD COLUMN difficulty TEXT DEFAULT 'Easy'")
    if 'servings' not in recipe_columns:
        cursor.execute("ALTER TABLE recipes ADD COLUMN servings TEXT DEFAULT ''")
    if 'share_token' not in recipe_columns:
        cursor.execute("ALTER TABLE recipes ADD COLUMN share_token TEXT")
    if 'visibility' not in recipe_columns:
        cursor.execute("ALTER TABLE recipes ADD COLUMN visibility TEXT DEFAULT 'public'")

    post_columns = [col[1] for col in cursor.execute('PRAGMA table_info(community_posts)').fetchall()]
    if 'is_hidden' not in post_columns:
        cursor.execute("ALTER TABLE community_posts ADD COLUMN is_hidden INTEGER DEFAULT 0")
    if 'report_count' not in post_columns:
        cursor.execute("ALTER TABLE community_posts ADD COLUMN report_count INTEGER DEFAULT 0")

    comment_columns = [col[1] for col in cursor.execute('PRAGMA table_info(post_comments)').fetchall()]
    if 'parent_id' not in comment_columns:
        cursor.execute("ALTER TABLE post_comments ADD COLUMN parent_id INTEGER REFERENCES post_comments(id) ON DELETE CASCADE")
    if 'reply_to_username' not in comment_columns:
        cursor.execute("ALTER TABLE post_comments ADD COLUMN reply_to_username TEXT DEFAULT ''")
    if 'is_hidden' not in comment_columns:
        cursor.execute("ALTER TABLE post_comments ADD COLUMN is_hidden INTEGER DEFAULT 0")

    grocery_columns = [col[1] for col in cursor.execute('PRAGMA table_info(groceries)').fetchall()]
    if 'user_id' not in grocery_columns:
        cursor.execute("ALTER TABLE groceries ADD COLUMN user_id INTEGER DEFAULT 1")

    sticky_columns = [col[1] for col in cursor.execute('PRAGMA table_info(stickies)').fetchall()]
    if 'user_id' not in sticky_columns:
        cursor.execute("ALTER TABLE stickies ADD COLUMN user_id INTEGER DEFAULT 1")

    pantry_columns = [col[1] for col in cursor.execute('PRAGMA table_info(pantry)').fetchall()]
    if 'user_id' not in pantry_columns:
        cursor.execute("ALTER TABLE pantry ADD COLUMN user_id INTEGER DEFAULT 1")

    # Create Indexes for Multi-Tenant performance
    cursor.execute('CREATE INDEX IF NOT EXISTS idx_recipes_user ON recipes(user_id)')
    cursor.execute('CREATE INDEX IF NOT EXISTS idx_recipes_share_token ON recipes(share_token)')
    cursor.execute('CREATE INDEX IF NOT EXISTS idx_planner_user ON planner(user_id)')
    cursor.execute('CREATE INDEX IF NOT EXISTS idx_planner_user_date ON planner(user_id, date_key)')
    cursor.execute('CREATE INDEX IF NOT EXISTS idx_groceries_user ON groceries(user_id)')
    cursor.execute('CREATE INDEX IF NOT EXISTS idx_stickies_user ON stickies(user_id)')
    cursor.execute('CREATE INDEX IF NOT EXISTS idx_pantry_user ON pantry(user_id)')

    conn.commit()
    conn.close()

# Initialize the database when the app starts
with app.app_context():
    init_db()

# --- Authentication Helpers & Middleware ---

def create_user_session(user_id, ip_address='', user_agent=''):
    token = secrets.token_urlsafe(32)
    expires_at = (datetime.now(timezone.utc) + timedelta(days=SESSION_DURATION_DAYS)).strftime('%Y-%m-%d %H:%M:%S')
    conn = get_db_connection()
    conn.execute(
        'INSERT INTO sessions (token, user_id, expires_at, user_agent, ip_address) VALUES (?, ?, ?, ?, ?)',
        (token, user_id, expires_at, user_agent[:255] if user_agent else '', ip_address[:45] if ip_address else '')
    )
    conn.commit()
    conn.close()
    return token, expires_at

def get_authenticated_user():
    token = request.cookies.get(SESSION_COOKIE_NAME)
    if not token:
        auth_header = request.headers.get('Authorization', '')
        if auth_header.startswith('Bearer '):
            token = auth_header[7:].strip()
    if not token:
        return None

    conn = get_db_connection()
    now_str = datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S')
    row = conn.execute('''
        SELECT u.id, u.username, u.email, u.display_name, u.created_at, u.is_active
        FROM sessions s
        JOIN users u ON s.user_id = u.id
        WHERE s.token = ? AND s.expires_at > ? AND u.is_active = 1
    ''', (token, now_str)).fetchone()
    conn.close()

    if row:
        return {
            'id': row['id'],
            'username': row['username'],
            'email': row['email'],
            'display_name': row['display_name'] or row['username'],
            'created_at': row['created_at']
        }
    return None

def login_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        user = get_authenticated_user()
        if not user:
            return jsonify({'error': 'Authentication required. Please log in.', 'code': 'UNAUTHORIZED'}), 401
        request.current_user = user
        return f(*args, **kwargs)
    return decorated_function

def check_login_rate_limit(ip_address):
    conn = get_db_connection()
    now = datetime.now(timezone.utc)
    now_str = now.strftime('%Y-%m-%d %H:%M:%S')
    row = conn.execute('SELECT * FROM login_attempts WHERE ip_address = ?', (ip_address,)).fetchone()
    if row and row['locked_until'] and row['locked_until'] > now_str:
        conn.close()
        return False, "Too many failed login attempts. Please wait a few minutes."
    conn.close()
    return True, ""

def record_login_attempt(ip_address, success):
    conn = get_db_connection()
    now = datetime.now(timezone.utc)
    now_str = now.strftime('%Y-%m-%d %H:%M:%S')
    if success:
        conn.execute('DELETE FROM login_attempts WHERE ip_address = ?', (ip_address,))
    else:
        row = conn.execute('SELECT * FROM login_attempts WHERE ip_address = ?', (ip_address,)).fetchone()
        if row:
            new_attempts = row['attempts'] + 1
            locked_until = (now + timedelta(minutes=5)).strftime('%Y-%m-%d %H:%M:%S') if new_attempts >= 5 else None
            conn.execute('UPDATE login_attempts SET attempts = ?, last_attempt = ?, locked_until = ? WHERE ip_address = ?',
                         (new_attempts, now_str, locked_until, ip_address))
        else:
            conn.execute('INSERT INTO login_attempts (ip_address, attempts, last_attempt) VALUES (?, 1, ?)',
                         (ip_address, now_str))
    conn.commit()
    conn.close()

def set_session_cookie(response, token, max_age_days=SESSION_DURATION_DAYS):
    max_age = max_age_days * 86400
    is_secure = request.is_secure or request.headers.get('X-Forwarded-Proto', '') == 'https'
    response.set_cookie(
        SESSION_COOKIE_NAME,
        token,
        max_age=max_age,
        httponly=True,
        samesite='Lax',
        secure=is_secure,
        path='/'
    )
    return response

def clear_session_cookie(response):
    response.set_cookie(
        SESSION_COOKIE_NAME,
        '',
        max_age=0,
        httponly=True,
        samesite='Lax',
        path='/'
    )
    return response


# --- Helper: Smart Ingredient Parser & Consolidator ---

FRACTIONS_MAP = {
    '½': 0.5, '⅓': 1/3, '⅔': 2/3, '¼': 0.25, '¾': 0.75,
    '⅕': 0.2, '⅖': 0.4, '⅗': 0.6, '⅘': 0.8,
    '⅙': 1/6, '⅚': 5/6, '⅛': 0.125, '⅜': 0.375, '⅝': 0.625, '⅞': 0.875
}

UNIT_SYNONYMS = {
    'cups': 'cup', 'cup': 'cup', 'c.': 'cup', 'c': 'cup',
    'tablespoons': 'tbsp', 'tablespoon': 'tbsp', 'tbsp': 'tbsp', 'tbs': 'tbsp', 'tb': 'tbsp', 'tbsps': 'tbsp',
    'teaspoons': 'tsp', 'teaspoon': 'tsp', 'tsp': 'tsp', 'tsps': 'tsp',
    'ounces': 'oz', 'ounce': 'oz', 'oz': 'oz', 'ozs': 'oz',
    'pounds': 'lb', 'pound': 'lb', 'lbs': 'lb', 'lb': 'lb',
    'grams': 'g', 'gram': 'g', 'g': 'g', 'gs': 'g',
    'kilograms': 'kg', 'kilogram': 'kg', 'kg': 'kg', 'kgs': 'kg',
    'milliliters': 'ml', 'milliliter': 'ml', 'ml': 'ml',
    'liters': 'liter', 'liter': 'liter', 'l': 'liter',
    'cloves': 'clove', 'clove': 'clove',
    'cans': 'can', 'can': 'can',
    'slices': 'slice', 'slice': 'slice',
    'stalks': 'stalk', 'stalk': 'stalk',
    'pinches': 'pinch', 'pinch': 'pinch',
    'dashes': 'dash', 'dash': 'dash',
    'packages': 'package', 'package': 'package', 'pkg': 'package', 'pkgs': 'package',
    'bunches': 'bunch', 'bunch': 'bunch',
    'heads': 'head', 'head': 'head'
}

def format_quantity_fraction(amount):
    if amount <= 0:
        return ""
    whole = int(amount)
    remainder = amount - whole
    fraction_str = ""
    # Map common decimals to fractions
    for frac_val, frac_symbol in [
        (0.5, '1/2'), (0.25, '1/4'), (0.75, '3/4'),
        (0.333, '1/3'), (0.666, '2/3'), (0.125, '1/8'),
        (0.375, '3/8'), (0.625, '5/8'), (0.875, '7/8')
    ]:
        if abs(remainder - frac_val) < 0.045:
            fraction_str = frac_symbol
            break
    if fraction_str:
        return f"{whole} {fraction_str}".strip()
    if remainder == 0:
        return str(whole)
    return f"{amount:.2f}".rstrip('0').rstrip('.')

def parse_ingredient_line(line):
    clean = line.strip().lstrip('-*• ').strip()
    if not clean:
        return None

    # Replace unicode fractions
    for unicode_char, val in FRACTIONS_MAP.items():
        if unicode_char in clean:
            clean = clean.replace(unicode_char, f" {val} ")

    clean = re.sub(r'\s+', ' ', clean).strip()

    # Regex for mixed fraction, simple fraction, or decimal/int
    qty_regex = r'^(\d+\s+\d+/\d+|\d+/\d+|\d+(?:\.\d+)?)\s*(.*)$'
    match = re.match(qty_regex, clean)

    if not match:
        return {'qty': None, 'unit': '', 'item': clean, 'raw': clean}

    qty_str = match.group(1).strip()
    rest = match.group(2).strip()

    # Calculate float qty
    try:
        if ' ' in qty_str:
            whole, frac = qty_str.split()
            qty = float(whole) + float(Fraction(frac))
        elif '/' in qty_str:
            qty = float(Fraction(qty_str))
        else:
            qty = float(qty_str)
    except Exception:
        qty = None

    if qty is None:
        return {'qty': None, 'unit': '', 'item': clean, 'raw': clean}

    # Extract unit if present
    words = rest.split()
    unit = ''
    item_words = words
    if words:
        first_word_clean = words[0].lower().rstrip('.,')
        if first_word_clean in UNIT_SYNONYMS:
            unit = UNIT_SYNONYMS[first_word_clean]
            item_words = words[1:]

    item_name = " ".join(item_words).strip()
    # Remove trailing descriptors like ", minced", ", chopped", etc. for grouping
    canonical_item = re.sub(r',?\s*(minced|chopped|diced|sliced|divided|crushed|to taste|optional|melted|softened|room temperature|fresh|grated|peeled|drained)\b', '', item_name, flags=re.I).strip()
    if not canonical_item:
        canonical_item = item_name

    return {
        'qty': qty,
        'unit': unit,
        'item': canonical_item if canonical_item else clean,
        'display_name': item_name if item_name else clean,
        'raw': clean
    }

def consolidate_ingredients(items_list):
    """
    Intelligently merges duplicate ingredients by summing quantities for identical units.
    """
    parsed_items = []
    for raw in items_list:
        parsed = parse_ingredient_line(raw)
        if parsed:
            parsed_items.append(parsed)

    grouped = {}
    unparsed_items = []

    for p in parsed_items:
        if p['qty'] is None:
            # Check if exact unparsed item already added
            if p['raw'] not in unparsed_items:
                unparsed_items.append(p['raw'])
            continue

        key = (p['item'].lower(), p['unit'].lower())
        if key not in grouped:
            grouped[key] = {
                'qty': p['qty'],
                'unit': p['unit'],
                'name': p['display_name']
            }
        else:
            grouped[key]['qty'] += p['qty']

    results = []
    for (item_key, unit_key), data in grouped.items():
        qty_formatted = format_quantity_fraction(data['qty'])
        unit = data['unit']
        if unit:
            # Pluralize common units if needed
            if data['qty'] > 1 and unit in ['cup', 'clove', 'can', 'slice', 'stalk', 'package', 'bunch', 'head']:
                unit = unit + 's'
            results.append(f"{qty_formatted} {unit} {data['name']}".strip())
        else:
            results.append(f"{qty_formatted} {data['name']}".strip())

    for u in unparsed_items:
        if u not in results:
            results.append(u)

    return results

# --- Recipe Web Scraper Helpers & Endpoints ---

VALID_RECIPE_CATEGORIES = [
    'General', 'Breakfast', 'Mains & Entrees', 'Soup', 'Sandwich',
    'Salad', 'Pasta', 'Side Dish', 'Sauce', 'Dressing',
    'Appetizers & Dips', 'Dessert', 'Baking & Bread',
    'Snacks & Smoothies', 'Drinks & Cocktails'
]

def parse_iso_duration(val):
    """Converts ISO 8601 duration (e.g. PT25M, PT1H30M, P0Y0M0DT0H10M0.000S) or numeric minutes into human-readable strings."""
    if not val:
        return ""
    if isinstance(val, (int, float)):
        return f"{int(val)} mins"
    val_str = str(val).strip()
    if not val_str:
        return ""

    # Comprehensive ISO 8601 duration regex matching
    iso_match = re.match(r'^P(?:(\d+)Y)?(?:(\d+)M)?(?:(\d+)W)?(?:(\d+)D)?(?:T(?:(\d+)H)?(?:(\d+(?:\.\d+)?)M)?(?:(\d+(?:\.\d+)?)S)?)?$', val_str, re.IGNORECASE)
    if iso_match:
        years, months, weeks, days, hours, minutes, seconds = iso_match.groups()
        parts = []
        if days and int(days) > 0:
            parts.append(f"{int(days)} day{'s' if int(days) > 1 else ''}")
        if hours and int(hours) > 0:
            parts.append(f"{int(hours)} hr{'s' if int(hours) > 1 else ''}")
        if minutes and float(minutes) > 0:
            m_val = int(float(minutes))
            parts.append(f"{m_val} min{'s' if m_val > 1 else ''}")
        if seconds and float(seconds) > 0 and not hours and not minutes:
            s_val = int(float(seconds))
            parts.append(f"{s_val} secs")
        return " ".join(parts) if parts else ""

    return val_str

def classify_recipe_category(title, raw_category="", text=""):
    """Intelligently maps raw category or recipe keywords to one of the 15 supported categories."""
    t_lower = title.lower()
    raw_lower = raw_category.lower()
    combined = f"{title} {raw_category} {text}".lower()

    # Exact match on raw category if present
    for cat in VALID_RECIPE_CATEGORIES:
        if cat.lower() in raw_lower:
            return cat

    # High priority matching on recipe title
    if any(k in t_lower for k in ['soup', 'stew', 'chowder', 'chili', 'bisque', 'broth', 'ramen', 'gumbo']):
        return 'Soup'
    if any(k in t_lower for k in ['sandwich', 'burger', 'panini', 'wrap', 'sub', 'toast', 'grilled cheese', 'slider', 'tacos', 'taco', 'fajita', 'burrito', 'quesadilla']):
        return 'Mains & Entrees'
    if any(k in t_lower for k in ['salad', 'slaw', 'vinaigrette salad']):
        return 'Salad'
    if any(k in t_lower for k in ['pasta', 'spaghetti', 'fettuccine', 'penne', 'lasagna', 'ravioli', 'macaroni', 'carbonara', 'bolognese', 'gnocchi', 'noodles', 'alfredo']):
        return 'Pasta'
    if any(k in t_lower for k in ['pancake', 'waffle', 'omelet', 'egg', 'oatmeal', 'french toast', 'crepe', 'frittata', 'breakfast', 'granola']):
        return 'Breakfast'
    if any(k in t_lower for k in ['cookie', 'cake', 'brownie', 'cupcake', 'pie', 'tart', 'pudding', 'ice cream', 'dessert', 'cheesecake', 'tiramisu', 'fudge', 'chocolate', 'frosting']):
        return 'Dessert'
    if any(k in t_lower for k in ['bread', 'biscuit', 'scone', 'muffin', 'focaccia', 'sourdough', 'dough', 'loaf', 'crust', 'bagel', 'roll', 'bun']):
        return 'Baking & Bread'
    if any(k in t_lower for k in ['dressing', 'vinaigrette']):
        return 'Dressing'
    if any(k in t_lower for k in ['sauce', 'salsa', 'gravy', 'marinade', 'pesto', 'mayo', 'aioli', 'glaze']):
        return 'Sauce'
    if any(k in t_lower for k in ['chicken', 'beef', 'steak', 'pork', 'salmon', 'fish', 'roast', 'casserole', 'curry', 'stir fry', 'ribs', 'meatball', 'main', 'dinner', 'entree', 'pork chop', 'shrimp']):
        return 'Mains & Entrees'

    # Fallback matching on full text
    if any(k in combined for k in ['soup', 'stew', 'chowder', 'chili', 'bisque', 'broth', 'ramen', 'gumbo']):
        return 'Soup'
    if any(k in combined for k in ['sandwich', 'burger', 'panini', 'wrap', 'sub', 'toast', 'grilled cheese', 'slider']):
        return 'Sandwich'
    if any(k in combined for k in ['salad', 'slaw', 'vinaigrette salad']):
        return 'Salad'
    if any(k in combined for k in ['pasta', 'spaghetti', 'fettuccine', 'penne', 'lasagna', 'ravioli', 'macaroni', 'carbonara', 'bolognese', 'gnocchi', 'noodles', 'alfredo']):
        return 'Pasta'
    if any(k in combined for k in ['pancake', 'waffle', 'omelet', 'egg', 'oatmeal', 'french toast', 'crepe', 'frittata', 'breakfast', 'granola']):
        return 'Breakfast'
    if any(k in combined for k in ['cocktail', 'margarita', 'martini', 'drink', 'punch', 'mocktail']):
        return 'Drinks & Cocktails'
    if any(k in combined for k in ['smoothie', 'shake', 'latte', 'lemonade', 'juice']):
        return 'Snacks & Smoothies'
    if any(k in combined for k in ['cookie', 'cake', 'brownie', 'cupcake', 'pie', 'tart', 'pudding', 'ice cream', 'dessert', 'cheesecake', 'tiramisu', 'fudge', 'chocolate', 'frosting']):
        return 'Dessert'
    if any(k in combined for k in ['bread', 'biscuit', 'scone', 'muffin', 'focaccia', 'sourdough', 'dough', 'loaf', 'crust', 'bagel', 'roll', 'bun']):
        return 'Baking & Bread'
    if any(k in combined for k in ['dressing', 'vinaigrette']):
        return 'Dressing'
    if any(k in combined for k in ['sauce', 'salsa', 'gravy', 'marinade', 'pesto', 'mayo', 'aioli', 'glaze']):
        return 'Sauce'
    if any(k in combined for k in ['dip', 'appetizer', 'bruschetta', 'nachos', 'wings', 'snack', 'crostini', 'bites', 'tapas']):
        return 'Appetizers & Dips'
    if any(k in combined for k in ['chicken', 'beef', 'steak', 'pork', 'salmon', 'fish', 'tacos', 'roast', 'casserole', 'curry', 'stir fry', 'ribs', 'meatball', 'main', 'dinner', 'entree', 'pork chop', 'shrimp']):
        return 'Mains & Entrees'
    if any(k in combined for k in ['side', 'potato', 'fries', 'vegetables', 'rice dish', 'green beans', 'asparagus']):
        return 'Side Dish'

    return 'General'

def fetch_recipe_html(url):
    """Fetches raw HTML from a recipe URL with multiple browser fingerprints and automatic proxy fallback for bot-protected websites."""
    header_variants = [
        # Variant 1: Mobile Safari with cross-site Referer (bypasses Dotdash Meredith / Allrecipes / Serious Eats / Cloudflare blogs)
        {
            'User-Agent': 'Mozilla/5.0 (iPhone; CPU iPhone OS 17_4_1 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.4.1 Mobile/15E148 Safari/604.1',
            'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
            'Accept-Language': 'en-US,en;q=0.9',
            'Referer': 'https://www.google.com/',
            'Sec-Fetch-Dest': 'document',
            'Sec-Fetch-Mode': 'navigate',
            'Sec-Fetch-Site': 'cross-site'
        },
        # Variant 2: Modern Desktop Chrome
        {
            'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36',
            'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8',
            'Accept-Language': 'en-US,en;q=0.9',
            'Referer': 'https://www.google.com/'
        }
    ]

    # Step 1: Try direct fetches with different header fingerprints
    for headers in header_variants:
        try:
            session = requests.Session()
            resp = session.get(url, headers=headers, timeout=10, allow_redirects=True)
            if resp.status_code == 200 and len(resp.text) > 400:
                lowered = resp.text[:2500].lower()
                is_challenge = any(x in lowered for x in [
                    '<title>just a moment...</title>',
                    '<title>access denied</title>',
                    '<title>attention required! | cloudflare</title>',
                    '<title>403 forbidden</title>',
                    '<title>robot or human?</title>',
                    '<title>security check</title>',
                    'action="/_bm/_data"',
                    'cf-browser-verification',
                    'id="challenge-running"'
                ])
                if not is_challenge:
                    return resp.text
        except Exception:
            pass

    # Step 2: Google Residential Proxy Mirror (Bypasses Datacenter IP 403 on Linux Ubuntu Servers for Allrecipes, Dotdash Meredith, NYT, Cloudflare blogs)
    gt_url = f"https://translate.google.com/translate?sl=auto&tl=en&u={url}"
    try:
        resp = requests.get(gt_url, headers=header_variants[1], timeout=10)
        if resp.status_code == 200 and len(resp.text) > 1000:
            return resp.text
    except Exception:
        pass

    # Step 3: Fallback to Jina Reader proxy with HTML output (bypasses Akamai/Cloudflare EdgeSuite like Food Network)
    jina_url = f"https://r.jina.ai/{url}"
    try:
        resp = requests.get(jina_url, headers={'User-Agent': 'Mozilla/5.0', 'X-Return-Format': 'html'}, timeout=15)
        if resp.status_code == 200 and len(resp.text) > 400:
            return resp.text
    except Exception:
        pass

    # Step 4: Final attempt with standard Jina markdown text
    try:
        resp = requests.get(jina_url, headers={'User-Agent': 'Mozilla/5.0'}, timeout=15)
        if resp.status_code == 200 and len(resp.text) > 200:
            return resp.text
    except Exception:
        pass

    # Step 5: Public Web Proxy Mirror
    try:
        resp = requests.get(f"https://api.allorigins.win/raw?url={requests.utils.quote(url)}", headers={'User-Agent': 'Mozilla/5.0'}, timeout=8)
        if resp.status_code == 200 and len(resp.text) > 500:
            return resp.text
    except Exception:
        pass

    # Step 6: Re-run direct request to raise descriptive HTTP error if website was completely unreachable
    resp = requests.get(url, headers=header_variants[0], timeout=12, allow_redirects=True)
    resp.raise_for_status()
    return resp.text

def extract_recipe_from_url(url, raw_content=None):
    """
    Extracts recipe metadata from URL or raw content using a multi-strategy engine:
    1. recipe-scrapers library (scrape_me / scrape_html with wild_mode=True)
    2. Deep BeautifulSoup Schema.org JSON-LD parser (supports nested @graph, HowToStep, HowToSection)
    3. Microdata & Recipe Plugin DOM selectors (WP Recipe Maker, Tasty Recipes, Create by Mediavine, etc.)
    4. Markdown & plaintext regex fallback
    """
    html_content = raw_content if raw_content else fetch_recipe_html(url)

    title = ""
    ingredients = []
    instructions = []
    prep_time = ""
    cook_time = ""
    servings = ""
    category = "General"

    # Strategy 1: recipe-scrapers library (Primary extractor for 150+ sites + schema.org)
    try:
        from recipe_scrapers import scrape_html, scrape_me
        scraper = None
        if "<" in html_content and ">" in html_content:
            try:
                scraper = scrape_html(html_content, org_url=url, wild_mode=True)
            except Exception:
                scraper = None

        if scraper is None and not raw_content:
            try:
                scraper = scrape_me(url, wild_mode=True)
            except Exception:
                scraper = None

        if scraper:
            try:
                t = scraper.title()
                if t:
                    title = str(t).strip()
            except Exception:
                pass

            try:
                ings = scraper.ingredients()
                if ings:
                    ingredients = [str(x).strip() for x in ings if str(x).strip()]
            except Exception:
                pass

            try:
                if hasattr(scraper, 'instructions_list'):
                    inst_list = scraper.instructions_list()
                    if inst_list:
                        instructions = [str(x).strip() for x in inst_list if str(x).strip()]
                if not instructions:
                    raw_inst = scraper.instructions()
                    if isinstance(raw_inst, str) and raw_inst.strip():
                        instructions = [line.strip() for line in raw_inst.split('\n') if line.strip()]
                    elif isinstance(raw_inst, list):
                        instructions = [str(x).strip() for x in raw_inst if str(x).strip()]
            except Exception:
                pass

            try:
                p = scraper.prep_time()
                if p:
                    prep_time = f"{int(p)} mins" if isinstance(p, (int, float)) else parse_iso_duration(p)
            except Exception:
                pass

            try:
                c = scraper.cook_time()
                if c:
                    cook_time = f"{int(c)} mins" if isinstance(c, (int, float)) else parse_iso_duration(c)
                if not cook_time:
                    tot = scraper.total_time()
                    if tot:
                        cook_time = f"{int(tot)} mins" if isinstance(tot, (int, float)) else parse_iso_duration(tot)
            except Exception:
                pass

            try:
                y = scraper.yields()
                if y:
                    servings = str(y).strip()
            except Exception:
                pass

            try:
                raw_cat = scraper.category() or ""
                category = classify_recipe_category(title, raw_cat, " ".join(ingredients))
            except Exception:
                pass
    except Exception:
        pass

    # Strategy 2: Deep Schema.org JSON-LD parser (BeautifulSoup or Regex)
    if not title or not ingredients or not instructions:
        json_ld_matches = re.findall(r'<script[^>]+type=[\"\']application/ld\+json[\"\'][^>]*>(.*?)</script>', html_content, re.DOTALL | re.I)
        recipe_nodes = []

        def search_nodes(node):
            if isinstance(node, dict):
                t = node.get('@type')
                if t == 'Recipe' or (isinstance(t, list) and 'Recipe' in t) or (isinstance(t, str) and 'recipe' in t.lower()):
                    recipe_nodes.append(node)
                if '@graph' in node and isinstance(node['@graph'], list):
                    for sub in node['@graph']:
                        search_nodes(sub)
                if 'mainEntity' in node:
                    search_nodes(node['mainEntity'])
            elif isinstance(node, list):
                for item in node:
                    search_nodes(item)

        for raw_json in json_ld_matches:
            content = raw_json.strip()
            if not content:
                continue
            try:
                parsed_json = json.loads(content)
                search_nodes(parsed_json)
            except Exception:
                continue

        for r in recipe_nodes:
            if not title:
                title = r.get('name') or r.get('headline') or ''

            if not ingredients and 'recipeIngredient' in r:
                raw_ing = r['recipeIngredient']
                if isinstance(raw_ing, list):
                    ingredients = [str(x).strip() for x in raw_ing if str(x).strip()]
                elif isinstance(raw_ing, str):
                    ingredients = [line.strip() for line in raw_ing.split('\n') if line.strip()]

            if not instructions and 'recipeInstructions' in r:
                raw_inst = r['recipeInstructions']
                if isinstance(raw_inst, list):
                    for step in raw_inst:
                        if isinstance(step, dict):
                            if 'itemListElement' in step and isinstance(step['itemListElement'], list):
                                for sub_step in step['itemListElement']:
                                    if isinstance(sub_step, dict) and 'text' in sub_step:
                                        instructions.append(str(sub_step['text']).strip())
                                    elif isinstance(sub_step, str):
                                        instructions.append(sub_step.strip())
                            elif 'text' in step:
                                instructions.append(str(step['text']).strip())
                        elif isinstance(step, str):
                            instructions.append(step.strip())
                elif isinstance(raw_inst, str):
                    instructions = [line.strip() for line in raw_inst.split('\n') if line.strip()]

            if not prep_time and 'prepTime' in r:
                prep_time = parse_iso_duration(r['prepTime'])

            if not cook_time:
                if 'cookTime' in r:
                    cook_time = parse_iso_duration(r['cookTime'])
                elif 'totalTime' in r:
                    cook_time = parse_iso_duration(r['totalTime'])

            if not servings and ('recipeYield' in r or 'yield' in r):
                y = r.get('recipeYield') or r.get('yield')
                if isinstance(y, list) and len(y) > 1 and not str(y[0]).isalpha():
                    servings = str(y[-1])
                elif isinstance(y, list) and y:
                    servings = str(y[0])
                else:
                    servings = str(y or '')

            if category == 'General' and 'recipeCategory' in r:
                cat_val = r['recipeCategory']
                cat_str = ", ".join(cat_val) if isinstance(cat_val, list) else str(cat_val)
                category = classify_recipe_category(title, cat_str, " ".join(ingredients))

            if title and ingredients and instructions:
                break

    # Strategy 3: Microdata & Recipe Plugin HTML DOM Parser (WordPress Recipe Maker, Tasty, Mediavine Create, etc.)
    if not title or not ingredients or not instructions:
        try:
            from bs4 import BeautifulSoup
            soup = BeautifulSoup(html_content, 'html.parser')

            if not title:
                t_el = soup.select_one('[itemprop="name"], .recipe-title, .wprm-recipe-name, .tasty-recipes-title, .mv-create-title, h1.entry-title, h1')
                if t_el:
                    title = t_el.get_text().strip()

            if not ingredients:
                ing_els = soup.select('[itemprop="recipeIngredient"], [itemprop="ingredients"], .wprm-recipe-ingredient, .tasty-recipes-ingredients li, .mv-create-ingredients li, .recipe-ingredients li, ul.recipe-ingredients li, .ingredients-item')
                if ing_els:
                    ingredients = [el.get_text().strip() for el in ing_els if el.get_text().strip()]

            if not instructions:
                inst_els = soup.select('[itemprop="recipeInstructions"], .wprm-recipe-instruction-text, .tasty-recipes-instructions li, .mv-create-instructions li, .recipe-instructions li, ol.recipe-instructions li, .instructions-section li, .direction-step')
                if inst_els:
                    instructions = [el.get_text().strip() for el in inst_els if el.get_text().strip()]

            if not prep_time:
                p_el = soup.select_one('.wprm-recipe-prep-time-container, .tasty-recipes-prep-time, [itemprop="prepTime"]')
                if p_el:
                    prep_time = parse_iso_duration(p_el.get_text().strip())

            if not cook_time:
                c_el = soup.select_one('.wprm-recipe-cook-time-container, .tasty-recipes-cook-time, [itemprop="cookTime"]')
                if c_el:
                    cook_time = parse_iso_duration(c_el.get_text().strip())

            if not servings:
                s_el = soup.select_one('.wprm-recipe-servings, .tasty-recipes-yield, [itemprop="recipeYield"]')
                if s_el:
                    servings = s_el.get_text().strip()
        except Exception:
            pass

    # Strategy 4: Markdown / Plaintext Fallback Parser
    if not title or not ingredients or not instructions:
        title_match = re.search(r'^(?:#\s*|Title:\s*)(.+)$', html_content, re.MULTILINE)
        if title_match and not title:
            title = title_match.group(1).strip()

        if not ingredients:
            ing_matches = re.findall(r'^\s*(?:-\s*\[[ xX]\]|[-*•])\s*(.+)$', html_content, re.MULTILINE)
            clean_ings = [m.strip() for m in ing_matches if not any(x in m.lower() for x in ['deselect', 'cookie', 'privacy', 'personal information', 'shopping list', 'cook mode', 'advertisement', 'share', 'print', 'pin recipe'])]
            if clean_ings:
                ingredients = clean_ings

        if not instructions:
            dir_sec = re.search(r'###?\s*(?:Directions|Instructions|Steps|Preparation|Method)\s*\n(.*?)(?:###?|$)', html_content, re.DOTALL | re.I)
            if dir_sec:
                for l in dir_sec.group(1).split('\n'):
                    l = l.strip()
                    if not l or l.startswith('![') or l.startswith('[Watch') or 'watch how' in l.lower():
                        continue
                    cleaned = re.sub(r'^(?:\d+[\.\)]|step\s+\d+[:\.]?|[-*•])\s*', '', l, flags=re.I).strip()
                    if cleaned:
                        instructions.append(cleaned)

    # Strategy 5: HTML Document <title> fallback
    if not title:
        title_match = re.search(r'<title>(.*?)</title>', html_content, re.I)
        if title_match:
            title = title_match.group(1).split('|')[0].split(' - ')[0].split(' – ')[0].strip()

    if not title or not (ingredients or instructions):
        raise ValueError("Could not automatically detect recipe information from this URL. Please verify the URL or enter the recipe manually.")

    # Clean and format ingredient list
    clean_ing_list = []
    for ing in ingredients:
        cleaned = re.sub(r'[\xa0\u200b]+', ' ', ing).strip().lstrip('-*• ')
        cleaned = re.sub(r'\s+', ' ', cleaned).strip()
        if cleaned and not any(x in cleaned.lower() for x in [
            'deselect all', 'add to shopping list', 'view shopping list',
            'cook mode (keep screen awake)', 'advertisement', 'nutrition facts',
            'yield:', 'prep time:', 'cook time:', 'total time:'
        ]):
            clean_ing_list.append(cleaned)

    formatted_ingredients = "\n".join([f"- {ing}" for ing in clean_ing_list]) if clean_ing_list else ""

    # Format numbered instructions
    formatted_instructions = []
    for i, step in enumerate(instructions, 1):
        step_clean = re.sub(r'[\xa0\u200b]+', ' ', step).strip()
        step_clean = re.sub(r'^(?:\d+[\.\)]|step\s+\d+[:\.]?|[-*•])\s*', '', step_clean, flags=re.I).strip()
        step_clean = re.sub(r'\s+', ' ', step_clean).strip()
        if step_clean and not step_clean.startswith('![') and not step_clean.startswith('[Watch') and 'watch how' not in step_clean.lower():
            formatted_instructions.append(f"{i}) {step_clean}")
    formatted_instructions_text = "\n\n".join(formatted_instructions) if formatted_instructions else "\n".join(instructions)

    # Recalculate category with all available data
    final_category = classify_recipe_category(title, category, " ".join(clean_ing_list) + " " + formatted_instructions_text)

    # Estimate difficulty
    difficulty = "Easy"
    if len(formatted_instructions) > 8 or len(clean_ing_list) > 12:
        difficulty = "Hard"
    elif len(formatted_instructions) > 4 or len(clean_ing_list) > 7:
        difficulty = "Medium"

    return {
        'title': title.strip(),
        'ingredients': formatted_ingredients.strip(),
        'instructions': formatted_instructions_text.strip(),
        'prep_time': prep_time.strip(),
        'cook_time': cook_time.strip(),
        'servings': servings.strip(),
        'difficulty': difficulty,
        'category': final_category,
        'source_url': url
    }

# --- Authentication Endpoints ---

@app.route('/api/auth/register', methods=['POST'])
def register():
    data = request.get_json() or {}
    username = data.get('username', '').strip()
    email = data.get('email', '').strip().lower()
    password = data.get('password', '')
    display_name = data.get('display_name', '').strip() or username

    if not username or len(username) < 3:
        return jsonify({'error': 'Username must be at least 3 characters long.'}), 400
    if not re.match(r'^[a-zA-Z0-9_.-]+$', username):
        return jsonify({'error': 'Username can only contain letters, numbers, dots, hyphens, and underscores.'}), 400
    if not email or '@' not in email or '.' not in email:
        return jsonify({'error': 'Please provide a valid email address.'}), 400
    if not password or len(password) < 8:
        return jsonify({'error': 'Password must be at least 8 characters long.'}), 400

    conn = get_db_connection()
    cursor = conn.cursor()

    existing_user = cursor.execute('SELECT id FROM users WHERE LOWER(username) = ? OR LOWER(email) = ?', (username.lower(), email)).fetchone()
    if existing_user:
        conn.close()
        return jsonify({'error': 'A user with that username or email already exists.'}), 409

    pwd_hash = generate_password_hash(password)
    cursor.execute(
        'INSERT INTO users (username, email, password_hash, display_name) VALUES (?, ?, ?, ?)',
        (username, email, pwd_hash, display_name)
    )
    user_id = cursor.lastrowid

    # Check if this is the first registered user and claim existing legacy data
    total_users = cursor.execute('SELECT COUNT(*) FROM users').fetchone()[0]
    if total_users == 1:
        cursor.execute('UPDATE recipes SET user_id = ? WHERE user_id = 1 OR user_id IS NULL', (user_id,))
        cursor.execute('UPDATE planner SET user_id = ? WHERE user_id = 1 OR user_id IS NULL', (user_id,))
        cursor.execute('UPDATE groceries SET user_id = ? WHERE user_id = 1 OR user_id IS NULL', (user_id,))
        cursor.execute('UPDATE stickies SET user_id = ? WHERE user_id = 1 OR user_id IS NULL', (user_id,))
        cursor.execute('UPDATE pantry SET user_id = ? WHERE user_id = 1 OR user_id IS NULL', (user_id,))

    conn.commit()
    conn.close()

    # Create session
    client_ip = request.headers.get('X-Real-IP', request.remote_addr or '')
    user_agent = request.headers.get('User-Agent', '')
    token, _ = create_user_session(user_id, client_ip, user_agent)

    user_info = {
        'id': user_id,
        'username': username,
        'email': email,
        'display_name': display_name
    }
    resp = make_response(jsonify({'message': 'Registration successful', 'user': user_info}), 201)
    return set_session_cookie(resp, token)

@app.route('/api/auth/login', methods=['POST'])
def login():
    client_ip = request.headers.get('X-Real-IP', request.remote_addr or '')
    allowed, rate_msg = check_login_rate_limit(client_ip)
    if not allowed:
        return jsonify({'error': rate_msg}), 429

    data = request.get_json() or {}
    username_or_email = data.get('username', '').strip()
    password = data.get('password', '')

    if not username_or_email or not password:
        return jsonify({'error': 'Username/email and password are required.'}), 400

    conn = get_db_connection()
    user = conn.execute(
        'SELECT * FROM users WHERE LOWER(username) = ? OR LOWER(email) = ?',
        (username_or_email.lower(), username_or_email.lower())
    ).fetchone()
    conn.close()

    if not user or not verify_password(password, user['password_hash']):
        record_login_attempt(client_ip, success=False)
        return jsonify({'error': 'Invalid username or password.'}), 401

    if not user['is_active']:
        return jsonify({'error': 'This account has been disabled.'}), 403

    record_login_attempt(client_ip, success=True)

    user_agent = request.headers.get('User-Agent', '')
    token, _ = create_user_session(user['id'], client_ip, user_agent)

    user_info = {
        'id': user['id'],
        'username': user['username'],
        'email': user['email'],
        'display_name': user['display_name'] or user['username']
    }
    resp = make_response(jsonify({'message': 'Login successful', 'user': user_info}), 200)
    return set_session_cookie(resp, token)

@app.route('/api/auth/logout', methods=['POST'])
def logout():
    token = request.cookies.get(SESSION_COOKIE_NAME)
    if not token:
        auth_header = request.headers.get('Authorization', '')
        if auth_header.startswith('Bearer '):
            token = auth_header[7:].strip()
    if token:
        conn = get_db_connection()
        conn.execute('DELETE FROM sessions WHERE token = ?', (token,))
        conn.commit()
        conn.close()

    resp = make_response(jsonify({'message': 'Logged out successfully'}), 200)
    return clear_session_cookie(resp)

@app.route('/api/auth/me', methods=['GET'])
@login_required
def get_current_user_profile():
    return jsonify({'user': request.current_user}), 200

@app.route('/api/auth/profile', methods=['PUT'])
@login_required
def update_user_profile():
    user_id = request.current_user['id']
    data = request.get_json() or {}
    display_name = data.get('display_name')
    current_password = data.get('current_password')
    new_password = data.get('new_password')

    conn = get_db_connection()
    cursor = conn.cursor()
    user_row = cursor.execute('SELECT * FROM users WHERE id = ?', (user_id,)).fetchone()

    if not user_row:
        conn.close()
        return jsonify({'error': 'User not found'}), 404

    if display_name is not None:
        cursor.execute('UPDATE users SET display_name = ? WHERE id = ?', (display_name.strip(), user_id))

    if new_password:
        if not current_password or not verify_password(current_password, user_row['password_hash']):
            conn.close()
            return jsonify({'error': 'Current password is incorrect'}), 400
        if len(new_password) < 8:
            conn.close()
            return jsonify({'error': 'New password must be at least 8 characters'}), 400
        new_hash = generate_password_hash(new_password)
        cursor.execute('UPDATE users SET password_hash = ? WHERE id = ?', (new_hash, user_id))

    conn.commit()
    conn.close()
    return jsonify({'message': 'Profile updated successfully'}), 200

def send_password_reset_email(to_email, reset_url):
    resend_api_key = os.environ.get('RESEND_API_KEY')
    smtp_host = os.environ.get('SMTP_HOST')
    email_from = os.environ.get('EMAIL_FROM', 'recipes@michaela.local')
    
    subject = "Reset Your Password - Virtual Recipe Box"
    html_content = f"""
    <div style="font-family: Arial, sans-serif; max-width: 540px; margin: 0 auto; padding: 20px; border: 1px solid #eee; border-radius: 10px;">
        <h2 style="color: #FF6B81; margin-top: 0;">Password Reset Request</h2>
        <p>Hello,</p>
        <p>We received a request to reset the password for your Virtual Recipe Box account.</p>
        <p style="margin: 25px 0;">
            <a href="{reset_url}" style="background-color: #FF6B81; color: white; padding: 12px 24px; text-decoration: none; border-radius: 6px; font-weight: bold; display: inline-block;">Reset Password</a>
        </p>
        <p style="color: #666; font-size: 0.9em;">Or copy and paste this link into your browser:<br><a href="{reset_url}">{reset_url}</a></p>
        <p style="color: #999; font-size: 0.8em; margin-top: 30px;">This link will expire in 1 hour. If you did not request a password reset, you can safely ignore this email.</p>
    </div>
    """
    
    if resend_api_key:
        try:
            resp = requests.post(
                "https://api.resend.com/emails",
                headers={
                    "Authorization": f"Bearer {resend_api_key}",
                    "Content-Type": "application/json"
                },
                json={
                    "from": os.environ.get('RESEND_FROM', 'onboarding@resend.dev'),
                    "to": [to_email],
                    "subject": subject,
                    "html": html_content
                },
                timeout=10
            )
            if resp.status_code in (200, 201):
                return True, "Email sent via Resend"
            else:
                print(f"[EMAIL ERROR] Resend returned {resp.status_code}: {resp.text}")
        except Exception as e:
            print(f"[EMAIL ERROR] Failed to send email via Resend: {e}")
            
    elif smtp_host:
        try:
            import smtplib
            from email.mime.text import MIMEText
            from email.mime.multipart import MIMEMultipart
            
            smtp_port = int(os.environ.get('SMTP_PORT', 587))
            smtp_user = os.environ.get('SMTP_USER', '')
            smtp_pass = os.environ.get('SMTP_PASS', '')
            
            msg = MIMEMultipart('alternative')
            msg['Subject'] = subject
            msg['From'] = email_from
            msg['To'] = to_email
            msg.attach(MIMEText(html_content, 'html'))
            
            with smtplib.SMTP(smtp_host, smtp_port, timeout=10) as server:
                if os.environ.get('SMTP_TLS', 'true').lower() in ('true', '1'):
                    server.starttls()
                if smtp_user and smtp_pass:
                    server.login(smtp_user, smtp_pass)
                server.sendmail(email_from, [to_email], msg.as_string())
            return True, "Email sent via SMTP"
        except Exception as e:
            print(f"[EMAIL ERROR] Failed to send email via SMTP: {e}")
    
    # Dev / local stdout fallback
    print(f"\n==================================================")
    print(f"🔑 [PASSWORD RESET EMAIL FOR {to_email}]")
    print(f"🔗 Reset URL: {reset_url}")
    print(f"==================================================\n")
    return True, "Reset link logged (Dev mode)"

@app.route('/api/auth/forgot-password', methods=['POST'])
def forgot_password():
    data = request.get_json() or {}
    identifier = (data.get('email') or data.get('username') or '').strip()
    if not identifier:
        return jsonify({'error': 'Email or username is required'}), 400

    conn = get_db_connection()
    cursor = conn.cursor()
    user = cursor.execute(
        'SELECT id, username, email FROM users WHERE LOWER(email) = ? OR LOWER(username) = ?',
        (identifier.lower(), identifier.lower())
    ).fetchone()

    if not user:
        conn.close()
        # Security: Do not leak whether user exists
        return jsonify({'message': 'If an account exists with that information, a password reset link has been sent.'}), 200

    user_id = user['id']
    user_email = user['email']

    # Generate secure reset token
    reset_token = secrets.token_urlsafe(32)
    expires_at = (datetime.now(timezone.utc) + timedelta(hours=1)).strftime('%Y-%m-%d %H:%M:%S')

    cursor.execute(
        'INSERT INTO password_resets (token, user_id, expires_at, used) VALUES (?, ?, ?, 0)',
        (reset_token, user_id, expires_at)
    )
    conn.commit()
    conn.close()

    # Determine site base URL
    origin = request.headers.get('Origin') or request.headers.get('Referer')
    if origin:
        from urllib.parse import urlparse
        parsed = urlparse(origin)
        base_url = f"{parsed.scheme}://{parsed.netloc}"
    else:
        base_url = request.host_url.rstrip('/')

    reset_url = f"{base_url}/login.html?reset_token={reset_token}"
    send_password_reset_email(user_email, reset_url)

    resp_data = {
        'message': 'If an account exists with that information, a password reset link has been sent.'
    }
    # Provide token preview if neither Resend nor SMTP is configured (for local testing convenience)
    if not os.environ.get('RESEND_API_KEY') and not os.environ.get('SMTP_HOST'):
        resp_data['dev_reset_token'] = reset_token
        resp_data['dev_reset_url'] = reset_url

    return jsonify(resp_data), 200

@app.route('/api/auth/reset-password', methods=['POST'])
def reset_password():
    data = request.get_json() or {}
    token = data.get('token', '').strip()
    new_password = data.get('new_password', '')

    if not token:
        return jsonify({'error': 'Reset token is required'}), 400
    if not new_password or len(new_password) < 8:
        return jsonify({'error': 'New password must be at least 8 characters long'}), 400

    conn = get_db_connection()
    cursor = conn.cursor()
    now_str = datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S')

    reset_row = cursor.execute(
        'SELECT token, user_id, expires_at, used FROM password_resets WHERE token = ?',
        (token,)
    ).fetchone()

    if not reset_row or reset_row['used'] == 1 or reset_row['expires_at'] <= now_str:
        conn.close()
        return jsonify({'error': 'Invalid or expired password reset link. Please request a new one.'}), 400

    user_id = reset_row['user_id']
    new_hash = generate_password_hash(new_password)

    # Update password, mark token used, and revoke existing sessions for security
    cursor.execute('UPDATE users SET password_hash = ? WHERE id = ?', (new_hash, user_id))
    cursor.execute('UPDATE password_resets SET used = 1 WHERE token = ?', (token,))
    cursor.execute('DELETE FROM sessions WHERE user_id = ?', (user_id,))

    conn.commit()
    conn.close()

    return jsonify({'message': 'Password has been successfully reset! You can now log in with your new password.'}), 200

# --- Media Upload Endpoints ---

@app.route('/api/upload/image', methods=['POST'])
@login_required
def upload_image():
    filename = None
    if 'file' in request.files:
        file = request.files['file']
        if file and file.filename:
            ext = file.filename.rsplit('.', 1)[-1].lower() if '.' in file.filename else 'jpg'
            if ext not in {'png', 'jpg', 'jpeg', 'webp', 'gif', 'heic'}:
                return jsonify({'error': 'Invalid file format. Allowed: PNG, JPG, JPEG, WEBP, GIF'}), 400
            clean_token = secrets.token_hex(16)
            filename = f"img_{clean_token}.{ext if ext != 'heic' else 'jpg'}"
            file_path = os.path.join(UPLOAD_FOLDER, filename)
            file.save(file_path)
    elif request.is_json:
        data = request.get_json() or {}
        image_data = data.get('image_data', '')
        if image_data.startswith('data:image/'):
            try:
                import base64
                header, base64_str = image_data.split(';base64,', 1)
                mime = header.replace('data:image/', '')
                ext = 'jpg' if mime in ('jpeg', 'jpg') else ('png' if mime == 'png' else 'webp')
                decoded = base64.b64decode(base64_str)
                clean_token = secrets.token_hex(16)
                filename = f"img_{clean_token}.{ext}"
                file_path = os.path.join(UPLOAD_FOLDER, filename)
                with open(file_path, 'wb') as f:
                    f.write(decoded)
            except Exception as e:
                return jsonify({'error': f'Failed to process image data: {str(e)}'}), 400

    if not filename:
        return jsonify({'error': 'No image file or image_data provided'}), 400

    image_url = f"/api/uploads/{filename}"
    return jsonify({
        'message': 'Image uploaded successfully!',
        'image_url': image_url,
        'filename': filename
    }), 201

@app.route('/api/uploads/<path:filename>', methods=['GET'])
def serve_upload(filename):
    return send_from_directory(UPLOAD_FOLDER, filename)

# --- Recipe Endpoints ---

@app.route('/api/recipes/import-url', methods=['POST'])
@login_required
def import_recipe_from_url():
    data = request.get_json()
    if not data or ('url' not in data and 'raw_text' not in data):
        return jsonify({'error': 'URL or raw_text is required'}), 400

    url = data.get('url', '').strip()
    raw_text = data.get('raw_text', '').strip() or None

    if url and not url.startswith('http://') and not url.startswith('https://'):
        url = 'https://' + url

    try:
        recipe_data = extract_recipe_from_url(url, raw_content=raw_text)
        return jsonify(recipe_data), 200
    except requests.exceptions.RequestException as e:
        return jsonify({'error': f'Could not reach website ({str(e)})'}), 400
    except ValueError as e:
        return jsonify({'error': str(e)}), 422
    except Exception as e:
        return jsonify({'error': f'Failed to scrape recipe: {str(e)}'}), 500

@app.route('/api/recipes', methods=['GET'])
@login_required
def get_recipes():
    user_id = request.current_user['id']
    conn = get_db_connection()
    recipes_db = conn.execute(
        'SELECT * FROM recipes WHERE user_id = ? ORDER BY is_favorite DESC, id DESC',
        (user_id,)
    ).fetchall()
    conn.close()

    recipes_list = []
    for recipe in recipes_db:
        keys = recipe.keys()
        recipes_list.append({
            'id': recipe['id'],
            'title': recipe['title'],
            'ingredients': recipe['ingredients'],
            'instructions': recipe['instructions'],
            'category': recipe['category'] if 'category' in keys else 'General',
            'is_favorite': bool(recipe['is_favorite']) if 'is_favorite' in keys else False,
            'prep_time': recipe['prep_time'] if 'prep_time' in keys else '',
            'cook_time': recipe['cook_time'] if 'cook_time' in keys else '',
            'difficulty': recipe['difficulty'] if 'difficulty' in keys else 'Easy',
            'servings': recipe['servings'] if 'servings' in keys else '',
            'share_token': recipe['share_token'] if 'share_token' in keys else None,
            'visibility': recipe['visibility'] if 'visibility' in keys else 'public'
        })
    return jsonify(recipes_list)

@app.route('/api/recipes/<int:recipe_id>', methods=['GET'])
@login_required
def get_recipe(recipe_id):
    user_id = request.current_user['id']
    conn = get_db_connection()
    recipe = conn.execute('SELECT * FROM recipes WHERE id = ? AND user_id = ?', (recipe_id, user_id)).fetchone()
    conn.close()
    if recipe:
        keys = recipe.keys()
        return jsonify({
            'id': recipe['id'],
            'title': recipe['title'],
            'ingredients': recipe['ingredients'],
            'instructions': recipe['instructions'],
            'category': recipe['category'] if 'category' in keys else 'General',
            'is_favorite': bool(recipe['is_favorite']) if 'is_favorite' in keys else False,
            'prep_time': recipe['prep_time'] if 'prep_time' in keys else '',
            'cook_time': recipe['cook_time'] if 'cook_time' in keys else '',
            'difficulty': recipe['difficulty'] if 'difficulty' in keys else 'Easy',
            'servings': recipe['servings'] if 'servings' in keys else '',
            'share_token': recipe['share_token'] if 'share_token' in keys else None,
            'visibility': recipe['visibility'] if 'visibility' in keys else 'public'
        })
    return jsonify({'error': 'Recipe not found'}), 404

@app.route('/api/recipes', methods=['POST'])
@login_required
def add_recipe():
    user_id = request.current_user['id']
    data = request.get_json()
    if not data or not all(k in data for k in ('title', 'ingredients', 'instructions')):
        return jsonify({'error': 'Missing data. Required: title, ingredients, instructions'}), 400

    title = data['title'].strip()
    ingredients = data['ingredients'].strip()
    instructions = data['instructions'].strip()
    category = data.get('category', 'General').strip() or 'General'
    is_favorite = 1 if data.get('is_favorite') else 0
    prep_time = data.get('prep_time', '').strip()
    cook_time = data.get('cook_time', '').strip()
    difficulty = data.get('difficulty', 'Easy').strip() or 'Easy'
    servings = data.get('servings', '').strip()
    visibility = data.get('visibility', 'public').strip() or 'public'

    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        cursor.execute(
            """INSERT INTO recipes (user_id, title, ingredients, instructions, category, is_favorite, prep_time, cook_time, difficulty, servings, visibility)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (user_id, title, ingredients, instructions, category, is_favorite, prep_time, cook_time, difficulty, servings, visibility)
        )
        conn.commit()
        new_recipe_id = cursor.lastrowid
        conn.close()
        return jsonify({'message': 'Recipe added successfully', 'id': new_recipe_id}), 201
    except sqlite3.Error as e:
        conn.rollback()
        conn.close()
        return jsonify({'error': str(e)}), 500

@app.route('/api/recipes/<int:recipe_id>', methods=['PUT'])
@login_required
def update_recipe(recipe_id):
    user_id = request.current_user['id']
    data = request.get_json()
    if not data:
        return jsonify({'error': 'No data provided'}), 400

    conn = get_db_connection()
    cursor = conn.cursor()
    updates = []
    params = []

    if 'title' in data:
        updates.append("title = ?")
        params.append(data['title'].strip())
    if 'ingredients' in data:
        updates.append("ingredients = ?")
        params.append(data['ingredients'].strip())
    if 'instructions' in data:
        updates.append("instructions = ?")
        params.append(data['instructions'].strip())
    if 'category' in data:
        updates.append("category = ?")
        params.append(data['category'].strip())
    if 'is_favorite' in data:
        updates.append("is_favorite = ?")
        params.append(1 if data['is_favorite'] else 0)
    if 'prep_time' in data:
        updates.append("prep_time = ?")
        params.append(data['prep_time'].strip())
    if 'cook_time' in data:
        updates.append("cook_time = ?")
        params.append(data['cook_time'].strip())
    if 'difficulty' in data:
        updates.append("difficulty = ?")
        params.append(data['difficulty'].strip())
    if 'servings' in data:
        updates.append("servings = ?")
        params.append(data['servings'].strip())
    if 'visibility' in data:
        updates.append("visibility = ?")
        params.append(data['visibility'].strip())

    if not updates:
        conn.close()
        return jsonify({'error': 'No fields to update'}), 400

    params.extend([recipe_id, user_id])
    query = f"UPDATE recipes SET {', '.join(updates)} WHERE id = ? AND user_id = ?"

    try:
        cursor.execute(query, tuple(params))
        conn.commit()
        rows_affected = cursor.rowcount
        conn.close()
        if rows_affected > 0:
            return jsonify({'message': 'Recipe updated successfully'}), 200
        else:
            return jsonify({'error': 'Recipe not found'}), 404
    except sqlite3.Error as e:
        conn.rollback()
        conn.close()
        return jsonify({'error': str(e)}), 500

@app.route('/api/recipes/<int:recipe_id>/toggle-favorite', methods=['POST'])
@login_required
def toggle_favorite(recipe_id):
    user_id = request.current_user['id']
    conn = get_db_connection()
    cursor = conn.cursor()
    row = conn.execute('SELECT is_favorite FROM recipes WHERE id = ? AND user_id = ?', (recipe_id, user_id)).fetchone()
    if not row:
        conn.close()
        return jsonify({'error': 'Recipe not found'}), 404
    new_fav = 0 if row['is_favorite'] else 1
    cursor.execute('UPDATE recipes SET is_favorite = ? WHERE id = ? AND user_id = ?', (new_fav, recipe_id, user_id))
    conn.commit()
    conn.close()
    return jsonify({'message': 'Favorite status toggled', 'is_favorite': bool(new_fav)}), 200

@app.route('/api/recipes/<int:recipe_id>', methods=['DELETE'])
@login_required
def delete_recipe(recipe_id):
    user_id = request.current_user['id']
    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        cursor.execute("DELETE FROM recipes WHERE id = ? AND user_id = ?", (recipe_id, user_id))
        conn.commit()
        rows_affected = cursor.rowcount
        conn.close()
        if rows_affected > 0:
            return jsonify({'message': 'Recipe deleted successfully'}), 200
        else:
            return jsonify({'error': 'Recipe not found'}), 404
    except sqlite3.Error as e:
        conn.rollback()
        conn.close()
        return jsonify({'error': str(e)}), 500

@app.route('/api/recipes/<int:recipe_id>/share', methods=['POST'])
@login_required
def share_recipe(recipe_id):
    user_id = request.current_user['id']
    conn = get_db_connection()
    cursor = conn.cursor()
    recipe = cursor.execute('SELECT id, share_token FROM recipes WHERE id = ? AND user_id = ?', (recipe_id, user_id)).fetchone()
    if not recipe:
        conn.close()
        return jsonify({'error': 'Recipe not found or unauthorized'}), 404

    share_token = recipe['share_token']
    if not share_token:
        share_token = secrets.token_urlsafe(16)
        cursor.execute('UPDATE recipes SET share_token = ? WHERE id = ?', (share_token, recipe_id))
        conn.commit()

    conn.close()

    # Determine site base URL
    origin = request.headers.get('Origin') or request.headers.get('Referer')
    if origin:
        from urllib.parse import urlparse
        parsed = urlparse(origin)
        base_url = f"{parsed.scheme}://{parsed.netloc}"
    else:
        base_url = request.host_url.rstrip('/')

    share_url = f"{base_url}/share.html?token={share_token}"
    return jsonify({
        'share_token': share_token,
        'share_url': share_url,
        'relative_url': f"share.html?token={share_token}"
    }), 200

@app.route('/api/public/recipes/<string:share_token>', methods=['GET'])
def get_public_recipe(share_token):
    conn = get_db_connection()
    recipe = conn.execute('''
        SELECT r.*, u.username as author_username, u.display_name as author_display_name
        FROM recipes r
        LEFT JOIN users u ON r.user_id = u.id
        WHERE r.share_token = ?
    ''', (share_token,)).fetchone()
    conn.close()

    if not recipe:
        return jsonify({'error': 'Recipe not found or share link is invalid'}), 404

    keys = recipe.keys()
    author_name = recipe['author_display_name'] or recipe['author_username'] or 'A Fellow Cook'
    return jsonify({
        'id': recipe['id'],
        'title': recipe['title'],
        'ingredients': recipe['ingredients'],
        'instructions': recipe['instructions'],
        'category': recipe['category'] if 'category' in keys else 'General',
        'prep_time': recipe['prep_time'] if 'prep_time' in keys else '',
        'cook_time': recipe['cook_time'] if 'cook_time' in keys else '',
        'difficulty': recipe['difficulty'] if 'difficulty' in keys else 'Easy',
        'servings': recipe['servings'] if 'servings' in keys else '',
        'share_token': recipe['share_token'],
        'author': {
            'username': recipe['author_username'] if 'author_username' in keys else '',
            'display_name': author_name
        }
    }), 200

@app.route('/api/recipes/clone/<string:share_token>', methods=['POST'])
@login_required
def clone_recipe(share_token):
    user_id = request.current_user['id']
    conn = get_db_connection()
    cursor = conn.cursor()

    recipe = cursor.execute('SELECT * FROM recipes WHERE share_token = ?', (share_token,)).fetchone()
    if not recipe:
        conn.close()
        return jsonify({'error': 'Shared recipe not found or invalid link'}), 404

    keys = recipe.keys()
    cursor.execute('''
        INSERT INTO recipes (user_id, title, ingredients, instructions, category, is_favorite, prep_time, cook_time, difficulty, servings)
        VALUES (?, ?, ?, ?, ?, 0, ?, ?, ?, ?)
    ''', (
        user_id,
        recipe['title'],
        recipe['ingredients'],
        recipe['instructions'],
        recipe['category'] if 'category' in keys else 'General',
        recipe['prep_time'] if 'prep_time' in keys else '',
        recipe['cook_time'] if 'cook_time' in keys else '',
        recipe['difficulty'] if 'difficulty' in keys else 'Easy',
        recipe['servings'] if 'servings' in keys else ''
    ))
    new_id = cursor.lastrowid
    conn.commit()
    conn.close()

    return jsonify({
        'message': f'"{recipe["title"]}" successfully saved to your Recipe Box!',
        'recipe_id': new_id
    }), 201

# --- Community Food Feed Endpoints ---

@app.route('/api/community/posts', methods=['GET'])
def get_community_posts():
    user = get_authenticated_user()
    current_user_id = user['id'] if user else None

    feed_filter = request.args.get('filter', 'all').strip().lower()
    limit = min(max(int(request.args.get('limit', 50)), 1), 100)
    offset = max(int(request.args.get('offset', 0)), 0)

    conn = get_db_connection()

    where_clauses = ["p.is_hidden = 0"]
    params = [current_user_id, current_user_id, current_user_id, current_user_id, current_user_id, current_user_id]

    if feed_filter in ('my_posts', 'mine', 'me'):
        if not current_user_id:
            conn.close()
            return jsonify([]), 200
        where_clauses.append("p.user_id = ?")
        params.append(current_user_id)
    elif feed_filter == 'friends':
        if not current_user_id:
            conn.close()
            return jsonify([]), 200
        where_clauses.append("(p.user_id = ? OR p.user_id IN (SELECT friend_id FROM friendships WHERE user_id = ?))")
        params.extend([current_user_id, current_user_id])
    elif feed_filter == 'close_friends':
        if not current_user_id:
            conn.close()
            return jsonify([]), 200
        where_clauses.append("(p.user_id = ? OR p.user_id IN (SELECT friend_id FROM friendships WHERE user_id = ? AND is_close_friend = 1))")
        params.extend([current_user_id, current_user_id])

    order_clause = "p.created_at DESC"
    if feed_filter == 'trending':
        order_clause = "((SELECT COUNT(*) FROM post_likes WHERE post_id = p.id) * 2 + (SELECT COUNT(*) FROM post_comments WHERE post_id = p.id AND is_hidden = 0)) DESC, p.created_at DESC"

    where_str = " AND ".join(where_clauses)
    query = f'''
        SELECT 
            p.id, p.user_id, p.content, p.image_url, p.recipe_id, p.created_at, p.report_count,
            u.username as author_username, u.display_name as author_display_name,
            (SELECT COUNT(*) FROM post_likes WHERE post_id = p.id) as likes_count,
            (SELECT COUNT(*) FROM post_comments WHERE post_id = p.id AND is_hidden = 0) as comments_count,
            (CASE WHEN ? IS NOT NULL AND EXISTS(SELECT 1 FROM post_likes WHERE post_id = p.id AND user_id = ?) THEN 1 ELSE 0 END) as liked_by_me,
            (CASE WHEN ? IS NOT NULL AND EXISTS(SELECT 1 FROM friendships WHERE user_id = ? AND friend_id = p.user_id) THEN 1 ELSE 0 END) as author_is_friend,
            (CASE WHEN ? IS NOT NULL AND EXISTS(SELECT 1 FROM friendships WHERE user_id = ? AND friend_id = p.user_id AND is_close_friend = 1) THEN 1 ELSE 0 END) as author_is_close_friend,
            r.title as recipe_title, r.category as recipe_category, r.prep_time as recipe_prep_time,
            r.cook_time as recipe_cook_time, r.difficulty as recipe_difficulty, r.servings as recipe_servings,
            r.share_token as recipe_share_token, r.visibility as recipe_visibility
        FROM community_posts p
        JOIN users u ON p.user_id = u.id
        LEFT JOIN recipes r ON p.recipe_id = r.id
        WHERE {where_str}
        ORDER BY {order_clause}
        LIMIT ? OFFSET ?
    '''
    params.extend([limit, offset])
    rows = conn.execute(query, tuple(params)).fetchall()
    conn.close()

    posts = []
    for row in rows:
        recipe_data = None
        if row['recipe_id'] and row['recipe_title']:
            recipe_data = {
                'id': row['recipe_id'],
                'title': row['recipe_title'],
                'category': row['recipe_category'] or 'General',
                'prep_time': row['recipe_prep_time'] or '',
                'cook_time': row['recipe_cook_time'] or '',
                'difficulty': row['recipe_difficulty'] or 'Easy',
                'servings': row['recipe_servings'] or '',
                'share_token': row['recipe_share_token'] or '',
                'visibility': row['recipe_visibility'] or 'public'
            }

        posts.append({
            'id': row['id'],
            'content': row['content'],
            'image_url': row['image_url'] or '',
            'created_at': row['created_at'],
            'author': {
                'id': row['user_id'],
                'username': row['author_username'],
                'display_name': row['author_display_name'] or row['author_username'],
                'is_friend': bool(row['author_is_friend']),
                'is_close_friend': bool(row['author_is_close_friend'])
            },
            'likes_count': row['likes_count'],
            'comments_count': row['comments_count'],
            'liked_by_me': bool(row['liked_by_me']),
            'recipe': recipe_data,
            'is_mine': (current_user_id is not None and row['user_id'] == current_user_id)
        })

    return jsonify(posts), 200

@app.route('/api/community/posts', methods=['POST'])
@login_required
def create_community_post():
    user_id = request.current_user['id']
    data = request.get_json() or {}
    content = data.get('content', '').strip()
    image_url = data.get('image_url', '').strip()
    recipe_id = data.get('recipe_id')

    if not content and not image_url:
        return jsonify({'error': 'Post must contain text or a photo'}), 400

    conn = get_db_connection()
    cursor = conn.cursor()

    if recipe_id:
        recipe = cursor.execute('SELECT id, share_token FROM recipes WHERE id = ?', (recipe_id,)).fetchone()
        if not recipe:
            conn.close()
            return jsonify({'error': 'Selected recipe not found'}), 404
        # Ensure recipe has a share_token so viewers can 1-click clone it
        if not recipe['share_token']:
            share_token = secrets.token_urlsafe(16)
            cursor.execute('UPDATE recipes SET share_token = ? WHERE id = ?', (share_token, recipe_id))

    cursor.execute(
        'INSERT INTO community_posts (user_id, content, image_url, recipe_id) VALUES (?, ?, ?, ?)',
        (user_id, content, image_url, recipe_id)
    )
    post_id = cursor.lastrowid
    conn.commit()
    conn.close()

    return jsonify({'message': 'Post created successfully!', 'post_id': post_id}), 201

@app.route('/api/community/posts/<int:post_id>', methods=['DELETE'])
@login_required
def delete_community_post(post_id):
    user_id = request.current_user['id']
    conn = get_db_connection()
    cursor = conn.cursor()

    post = cursor.execute('SELECT * FROM community_posts WHERE id = ? AND user_id = ?', (post_id, user_id)).fetchone()
    if not post:
        conn.close()
        return jsonify({'error': 'Post not found or unauthorized to delete'}), 404

    cursor.execute('DELETE FROM community_posts WHERE id = ?', (post_id,))
    conn.commit()
    conn.close()
    return jsonify({'message': 'Post deleted successfully'}), 200

@app.route('/api/community/posts/<int:post_id>/like', methods=['POST'])
@login_required
def toggle_post_like(post_id):
    user_id = request.current_user['id']
    conn = get_db_connection()
    cursor = conn.cursor()

    post = cursor.execute('SELECT id FROM community_posts WHERE id = ? AND is_hidden = 0', (post_id,)).fetchone()
    if not post:
        conn.close()
        return jsonify({'error': 'Post not found'}), 404

    existing_like = cursor.execute('SELECT 1 FROM post_likes WHERE post_id = ? AND user_id = ?', (post_id, user_id)).fetchone()
    if existing_like:
        cursor.execute('DELETE FROM post_likes WHERE post_id = ? AND user_id = ?', (post_id, user_id))
        liked = False
    else:
        cursor.execute('INSERT INTO post_likes (post_id, user_id) VALUES (?, ?)', (post_id, user_id))
        liked = True

    conn.commit()
    likes_count = cursor.execute('SELECT COUNT(*) FROM post_likes WHERE post_id = ?', (post_id,)).fetchone()[0]
    conn.close()

    return jsonify({'liked': liked, 'likes_count': likes_count}), 200

@app.route('/api/community/posts/<int:post_id>/comments', methods=['GET'])
def get_post_comments(post_id):
    user = get_authenticated_user()
    current_user_id = user['id'] if user else None

    conn = get_db_connection()
    rows = conn.execute('''
        SELECT c.id, c.post_id, c.parent_id, c.reply_to_username, c.user_id, c.comment, c.created_at,
               u.username as author_username, u.display_name as author_display_name
        FROM post_comments c
        JOIN users u ON c.user_id = u.id
        WHERE c.post_id = ? AND c.is_hidden = 0
        ORDER BY c.created_at ASC
    ''', (post_id,)).fetchall()
    conn.close()

    comment_map = {}
    top_level_comments = []

    for r in rows:
        c_obj = {
            'id': r['id'],
            'post_id': r['post_id'],
            'parent_id': r['parent_id'],
            'reply_to_username': r['reply_to_username'] or '',
            'comment': r['comment'],
            'created_at': r['created_at'],
            'author': {
                'id': r['user_id'],
                'username': r['author_username'],
                'display_name': r['author_display_name'] or r['author_username']
            },
            'is_mine': (current_user_id is not None and r['user_id'] == current_user_id),
            'replies': []
        }
        comment_map[r['id']] = c_obj

    for r in rows:
        cid = r['id']
        pid = r['parent_id']
        if pid and pid in comment_map:
            comment_map[pid]['replies'].append(comment_map[cid])
        else:
            top_level_comments.append(comment_map[cid])

    return jsonify(top_level_comments), 200

@app.route('/api/community/posts/<int:post_id>/comments', methods=['POST'])
@login_required
def add_post_comment(post_id):
    user_id = request.current_user['id']
    data = request.get_json() or {}
    comment_text = data.get('comment', '').strip()
    parent_id = data.get('parent_id')
    reply_to_username = data.get('reply_to_username', '').strip()

    if not comment_text:
        return jsonify({'error': 'Comment cannot be empty'}), 400

    conn = get_db_connection()
    cursor = conn.cursor()

    post = cursor.execute('SELECT id FROM community_posts WHERE id = ? AND is_hidden = 0', (post_id,)).fetchone()
    if not post:
        conn.close()
        return jsonify({'error': 'Post not found'}), 404

    if parent_id:
        parent_comment = cursor.execute('SELECT id, user_id FROM post_comments WHERE id = ? AND post_id = ?', (parent_id, post_id)).fetchone()
        if not parent_comment:
            conn.close()
            return jsonify({'error': 'Parent comment not found'}), 404

    cursor.execute(
        'INSERT INTO post_comments (post_id, user_id, comment, parent_id, reply_to_username) VALUES (?, ?, ?, ?, ?)',
        (post_id, user_id, comment_text, parent_id, reply_to_username)
    )
    comment_id = cursor.lastrowid
    conn.commit()
    conn.close()

    return jsonify({
        'message': 'Comment added successfully',
        'comment': {
            'id': comment_id,
            'post_id': post_id,
            'parent_id': parent_id,
            'reply_to_username': reply_to_username,
            'comment': comment_text,
            'created_at': datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S'),
            'author': {
                'id': user_id,
                'username': request.current_user['username'],
                'display_name': request.current_user['display_name']
            },
            'is_mine': True,
            'replies': []
        }
    }), 201

@app.route('/api/community/comments/<int:comment_id>', methods=['DELETE'])
@login_required
def delete_post_comment(comment_id):
    user_id = request.current_user['id']
    conn = get_db_connection()
    cursor = conn.cursor()

    comment = cursor.execute('SELECT * FROM post_comments WHERE id = ? AND user_id = ?', (comment_id, user_id)).fetchone()
    if not comment:
        conn.close()
        return jsonify({'error': 'Comment not found or unauthorized to delete'}), 404

    cursor.execute('DELETE FROM post_comments WHERE id = ?', (comment_id,))
    conn.commit()
    conn.close()
    return jsonify({'message': 'Comment deleted successfully'}), 200

# --- Moderation & Reporting Endpoints ---

@app.route('/api/community/posts/<int:post_id>/report', methods=['POST'])
@login_required
def report_community_post(post_id):
    user_id = request.current_user['id']
    data = request.get_json() or {}
    reason = data.get('reason', 'inappropriate').strip()

    conn = get_db_connection()
    cursor = conn.cursor()

    post = cursor.execute('SELECT id, is_hidden FROM community_posts WHERE id = ?', (post_id,)).fetchone()
    if not post:
        conn.close()
        return jsonify({'error': 'Post not found'}), 404

    try:
        cursor.execute(
            'INSERT INTO post_reports (post_id, reported_by, reason) VALUES (?, ?, ?)',
            (post_id, user_id, reason)
        )
    except sqlite3.IntegrityError:
        conn.close()
        return jsonify({'error': 'You have already reported this post'}), 400

    report_count = cursor.execute('SELECT COUNT(*) FROM post_reports WHERE post_id = ?', (post_id,)).fetchone()[0]
    cursor.execute('UPDATE community_posts SET report_count = ? WHERE id = ?', (report_count, post_id))

    quarantined = False
    if report_count >= 3:
        cursor.execute('UPDATE community_posts SET is_hidden = 1 WHERE id = ?', (post_id,))
        quarantined = True

    conn.commit()
    conn.close()

    return jsonify({
        'message': 'Post reported. Thank you for keeping our community friendly and safe!',
        'quarantined': quarantined,
        'report_count': report_count
    }), 200

@app.route('/api/community/comments/<int:comment_id>/report', methods=['POST'])
@login_required
def report_post_comment(comment_id):
    user_id = request.current_user['id']
    data = request.get_json() or {}
    reason = data.get('reason', 'inappropriate').strip()

    conn = get_db_connection()
    cursor = conn.cursor()

    comment = cursor.execute('SELECT id, is_hidden FROM post_comments WHERE id = ?', (comment_id,)).fetchone()
    if not comment:
        conn.close()
        return jsonify({'error': 'Comment not found'}), 404

    try:
        cursor.execute(
            'INSERT INTO post_reports (comment_id, reported_by, reason) VALUES (?, ?, ?)',
            (comment_id, user_id, reason)
        )
    except sqlite3.IntegrityError:
        conn.close()
        return jsonify({'error': 'You have already reported this comment'}), 400

    report_count = cursor.execute('SELECT COUNT(*) FROM post_reports WHERE comment_id = ?', (comment_id,)).fetchone()[0]
    quarantined = False
    if report_count >= 3:
        cursor.execute('UPDATE post_comments SET is_hidden = 1 WHERE id = ?', (comment_id,))
        quarantined = True

    conn.commit()
    conn.close()

    return jsonify({
        'message': 'Comment reported. Thank you for keeping our community friendly and safe!',
        'quarantined': quarantined,
        'report_count': report_count
    }), 200

# --- Friends & Social Relationships Endpoints ---

@app.route('/api/friends', methods=['GET'])
@login_required
def get_friends():
    user_id = request.current_user['id']
    conn = get_db_connection()
    rows = conn.execute('''
        SELECT f.friend_id as id, f.is_close_friend, f.created_at,
               u.username, u.display_name
        FROM friendships f
        JOIN users u ON f.friend_id = u.id
        WHERE f.user_id = ? AND u.is_active = 1
        ORDER BY f.is_close_friend DESC, u.username ASC
    ''', (user_id,)).fetchall()
    conn.close()

    friends = []
    for r in rows:
        friends.append({
            'id': r['id'],
            'username': r['username'],
            'display_name': r['display_name'] or r['username'],
            'is_close_friend': bool(r['is_close_friend']),
            'created_at': r['created_at']
        })

    return jsonify(friends), 200

@app.route('/api/friends/<int:friend_id>', methods=['POST'])
@login_required
def add_friend(friend_id):
    user_id = request.current_user['id']
    if user_id == friend_id:
        return jsonify({'error': 'You cannot add yourself as a friend'}), 400

    conn = get_db_connection()
    cursor = conn.cursor()

    target_user = cursor.execute('SELECT id, username, display_name FROM users WHERE id = ? AND is_active = 1', (friend_id,)).fetchone()
    if not target_user:
        conn.close()
        return jsonify({'error': 'User not found'}), 404

    cursor.execute('''
        INSERT INTO friendships (user_id, friend_id, is_close_friend)
        VALUES (?, ?, 0)
        ON CONFLICT(user_id, friend_id) DO NOTHING
    ''', (user_id, friend_id))
    conn.commit()
    conn.close()

    return jsonify({
        'message': f'You are now following {target_user["display_name"] or target_user["username"]}!',
        'friend': {
            'id': target_user['id'],
            'username': target_user['username'],
            'display_name': target_user['display_name'] or target_user['username'],
            'is_close_friend': False
        }
    }), 201

@app.route('/api/friends/<int:friend_id>', methods=['DELETE'])
@login_required
def remove_friend(friend_id):
    user_id = request.current_user['id']
    conn = get_db_connection()
    cursor = conn.cursor()

    cursor.execute('DELETE FROM friendships WHERE user_id = ? AND friend_id = ?', (user_id, friend_id))
    conn.commit()
    conn.close()

    return jsonify({'message': 'Friend removed successfully'}), 200

@app.route('/api/friends/<int:friend_id>/toggle-close-friend', methods=['POST'])
@login_required
def toggle_close_friend(friend_id):
    user_id = request.current_user['id']
    if user_id == friend_id:
        return jsonify({'error': 'Cannot set yourself as a close friend'}), 400

    conn = get_db_connection()
    cursor = conn.cursor()

    existing = cursor.execute('SELECT is_close_friend FROM friendships WHERE user_id = ? AND friend_id = ?', (user_id, friend_id)).fetchone()
    if existing:
        new_val = 0 if existing['is_close_friend'] else 1
        cursor.execute('UPDATE friendships SET is_close_friend = ? WHERE user_id = ? AND friend_id = ?', (new_val, user_id, friend_id))
    else:
        new_val = 1
        cursor.execute('INSERT INTO friendships (user_id, friend_id, is_close_friend) VALUES (?, ?, 1)', (user_id, friend_id))

    conn.commit()
    conn.close()

    return jsonify({
        'is_close_friend': bool(new_val),
        'message': '⭐ Added to Close Friends!' if new_val else 'Removed from Close Friends'
    }), 200

@app.route('/api/users/me/stats', methods=['GET'])
@login_required
def get_my_user_stats():
    user_id = request.current_user['id']
    conn = get_db_connection()

    recipes_count = conn.execute('SELECT COUNT(*) FROM recipes WHERE user_id = ?', (user_id,)).fetchone()[0]
    posts_count = conn.execute('SELECT COUNT(*) FROM community_posts WHERE user_id = ? AND is_hidden = 0', (user_id,)).fetchone()[0]

    likes_received = conn.execute('''
        SELECT COUNT(*) FROM post_likes pl 
        JOIN community_posts cp ON pl.post_id = cp.id 
        WHERE cp.user_id = ?
    ''', (user_id,)).fetchone()[0]

    comments_received = conn.execute('''
        SELECT COUNT(*) FROM post_comments pc 
        JOIN community_posts cp ON pc.post_id = cp.id 
        WHERE cp.user_id = ? AND pc.is_hidden = 0
    ''', (user_id,)).fetchone()[0]

    friends_count = conn.execute('SELECT COUNT(*) FROM friendships WHERE user_id = ?', (user_id,)).fetchone()[0]
    close_friends_count = conn.execute('SELECT COUNT(*) FROM friendships WHERE user_id = ? AND is_close_friend = 1', (user_id,)).fetchone()[0]

    groceries_count = conn.execute('SELECT COUNT(*) FROM groceries WHERE user_id = ? AND checked = 0', (user_id,)).fetchone()[0]
    stickies_count = conn.execute('SELECT COUNT(*) FROM stickies WHERE user_id = ?', (user_id,)).fetchone()[0]

    meals_planned_count = 0
    try:
        meals_planned_count = conn.execute('SELECT COUNT(*) FROM planner_v2 WHERE user_id = ?', (user_id,)).fetchone()[0]
    except Exception:
        pass

    conn.close()

    return jsonify({
        'user_id': user_id,
        'username': request.current_user['username'],
        'display_name': request.current_user['display_name'] or request.current_user['username'],
        'recipes_count': recipes_count,
        'posts_count': posts_count,
        'likes_received': likes_received,
        'comments_received': comments_received,
        'friends_count': friends_count,
        'close_friends_count': close_friends_count,
        'groceries_count': groceries_count,
        'stickies_count': stickies_count,
        'meals_planned_count': meals_planned_count
    }), 200

@app.route('/api/users/<int:target_user_id>/recipes', methods=['GET'])
def get_user_recipe_box(target_user_id):
    user = get_authenticated_user()
    current_user_id = user['id'] if user else None

    conn = get_db_connection()
    target_user = conn.execute('SELECT id, username, display_name FROM users WHERE id = ? AND is_active = 1', (target_user_id,)).fetchone()
    if not target_user:
        conn.close()
        return jsonify({'error': 'User not found'}), 404

    # Determine visibility permissions
    if current_user_id == target_user_id:
        allowed_visibilities = ('public', 'close_friends', 'private')
    elif current_user_id:
        # Check if target_user marked current_user as a close friend
        target_close_rel = conn.execute(
            'SELECT is_close_friend FROM friendships WHERE user_id = ? AND friend_id = ? AND is_close_friend = 1',
            (target_user_id, current_user_id)
        ).fetchone()
        if target_close_rel:
            allowed_visibilities = ('public', 'close_friends')
        else:
            allowed_visibilities = ('public',)
    else:
        allowed_visibilities = ('public',)

    # Check relationships from current user's perspective
    is_my_friend = False
    is_my_close_friend = False
    they_made_me_close_friend = False

    if current_user_id and current_user_id != target_user_id:
        my_rel = conn.execute('SELECT is_close_friend FROM friendships WHERE user_id = ? AND friend_id = ?', (current_user_id, target_user_id)).fetchone()
        if my_rel:
            is_my_friend = True
            is_my_close_friend = bool(my_rel['is_close_friend'])
        their_rel = conn.execute('SELECT is_close_friend FROM friendships WHERE user_id = ? AND friend_id = ?', (target_user_id, current_user_id)).fetchone()
        if their_rel and their_rel['is_close_friend']:
            they_made_me_close_friend = True

    placeholders = ','.join('?' for _ in allowed_visibilities)
    recipes_db = conn.execute(
        f'SELECT * FROM recipes WHERE user_id = ? AND visibility IN ({placeholders}) ORDER BY is_favorite DESC, id DESC',
        (target_user_id, *allowed_visibilities)
    ).fetchall()
    conn.close()

    recipes_list = []
    for recipe in recipes_db:
        keys = recipe.keys()
        recipes_list.append({
            'id': recipe['id'],
            'title': recipe['title'],
            'ingredients': recipe['ingredients'],
            'instructions': recipe['instructions'],
            'category': recipe['category'] if 'category' in keys else 'General',
            'is_favorite': bool(recipe['is_favorite']) if 'is_favorite' in keys else False,
            'prep_time': recipe['prep_time'] if 'prep_time' in keys else '',
            'cook_time': recipe['cook_time'] if 'cook_time' in keys else '',
            'difficulty': recipe['difficulty'] if 'difficulty' in keys else 'Easy',
            'servings': recipe['servings'] if 'servings' in keys else '',
            'share_token': recipe['share_token'] if 'share_token' in keys else None,
            'visibility': recipe['visibility'] if 'visibility' in keys else 'public'
        })

    return jsonify({
        'user': {
            'id': target_user['id'],
            'username': target_user['username'],
            'display_name': target_user['display_name'] or target_user['username'],
            'is_friend': is_my_friend,
            'is_close_friend': is_my_close_friend,
            'they_made_me_close_friend': they_made_me_close_friend
        },
        'recipes': recipes_list
    }), 200

# --- Planner Endpoints ---

@app.route('/api/planner', methods=['GET'])
@login_required
def get_planner():
    user_id = request.current_user['id']
    conn = get_db_connection()
    planner_db = conn.execute('SELECT * FROM planner WHERE user_id = ?', (user_id,)).fetchall()
    conn.close()

    planner_data = {}
    for entry in planner_db:
        planner_data[entry['date_key']] = {
            'meals': {
                'breakfast': entry['breakfast'],
                'lunch': entry['lunch'],
                'dinner': entry['dinner']
            },
            'tasks': entry['tasks'],
            'notes': entry['notes']
        }
    return jsonify(planner_data)

@app.route('/api/planner/<string:date_key>', methods=['GET'])
@login_required
def get_planner_day(date_key):
    user_id = request.current_user['id']
    conn = get_db_connection()
    entry = conn.execute('SELECT * FROM planner WHERE date_key = ? AND user_id = ?', (date_key, user_id)).fetchone()
    conn.close()
    if entry:
        return jsonify({
            'date_key': entry['date_key'],
            'meals': {
                'breakfast': entry['breakfast'],
                'lunch': entry['lunch'],
                'dinner': entry['dinner']
            },
            'tasks': entry['tasks'],
            'notes': entry['notes']
        })
    else:
        return jsonify({
            'date_key': date_key,
            'meals': {'breakfast': 'Not planned', 'lunch': 'Not planned', 'dinner': 'Not planned'},
            'tasks': '',
            'notes': ''
        })

@app.route('/api/planner/<string:date_key>', methods=['POST'])
@login_required
def save_planner_day(date_key):
    user_id = request.current_user['id']
    data = request.get_json()
    if not data:
        return jsonify({'error': 'No data provided'}), 400

    conn = get_db_connection()
    cursor = conn.cursor()
    existing = conn.execute('SELECT * FROM planner WHERE date_key = ? AND user_id = ?', (date_key, user_id)).fetchone()

    if existing:
        meals = data.get('meals', {})
        breakfast = meals.get('breakfast', existing['breakfast'])
        lunch = meals.get('lunch', existing['lunch'])
        dinner = meals.get('dinner', existing['dinner'])
        tasks = data.get('tasks', existing['tasks'])
        notes = data.get('notes', existing['notes'])
    else:
        meals = data.get('meals', {})
        breakfast = meals.get('breakfast', 'Not planned')
        lunch = meals.get('lunch', 'Not planned')
        dinner = meals.get('dinner', 'Not planned')
        tasks = data.get('tasks', '')
        notes = data.get('notes', '')

    try:
        cursor.execute('''
            INSERT INTO planner (user_id, date_key, breakfast, lunch, dinner, tasks, notes)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(user_id, date_key) DO UPDATE SET
                breakfast = excluded.breakfast,
                lunch = excluded.lunch,
                dinner = excluded.dinner,
                tasks = excluded.tasks,
                notes = excluded.notes
        ''', (user_id, date_key, breakfast, lunch, dinner, tasks, notes))
        conn.commit()
        conn.close()
        return jsonify({'message': f'Planner updated for {date_key}'}), 200
    except sqlite3.Error as e:
        conn.rollback()
        conn.close()
        return jsonify({'error': str(e)}), 500

@app.route('/api/planner/<string:date_key>', methods=['DELETE'])
@login_required
def clear_planner_day(date_key):
    user_id = request.current_user['id']
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("DELETE FROM planner WHERE date_key = ? AND user_id = ?", (date_key, user_id))
    conn.commit()
    rows_affected = cursor.rowcount
    conn.close()
    if rows_affected > 0:
        return jsonify({'message': f'Planner cleared for {date_key}'}), 200
    else:
        return jsonify({'error': 'Date entry not found'}), 404

# --- Grocery List Endpoints ---

@app.route('/api/groceries', methods=['GET'])
@login_required
def get_groceries():
    user_id = request.current_user['id']
    conn = get_db_connection()
    items = conn.execute('SELECT * FROM groceries WHERE user_id = ? ORDER BY checked ASC, id DESC', (user_id,)).fetchall()
    conn.close()
    return jsonify([{'id': row['id'], 'item': row['item'], 'checked': bool(row['checked'])} for row in items])

@app.route('/api/groceries', methods=['POST'])
@login_required
def add_grocery():
    user_id = request.current_user['id']
    data = request.get_json()
    if not data or 'item' not in data:
        return jsonify({'error': 'Item text is required'}), 400

    items_to_add = data['item']
    do_consolidate = data.get('consolidate', True)

    if isinstance(items_to_add, str):
        items_list = [line.strip().lstrip('-*• ') for line in items_to_add.split('\n') if line.strip()]
    elif isinstance(items_to_add, list):
        items_list = [str(x).strip().lstrip('-*• ') for x in items_to_add if str(x).strip()]
    else:
        items_list = []

    if do_consolidate and len(items_list) > 1:
        items_list = consolidate_ingredients(items_list)

    conn = get_db_connection()
    cursor = conn.cursor()
    for item in items_list:
        cursor.execute("INSERT INTO groceries (user_id, item, checked) VALUES (?, ?, 0)", (user_id, item))
    conn.commit()
    conn.close()
    return jsonify({'message': f'Added {len(items_list)} items to groceries'}), 201

@app.route('/api/groceries/consolidate', methods=['POST'])
@login_required
def consolidate_grocery_list():
    """
    Consolidates unchecked grocery items in the database by combining identical ingredients and quantities.
    """
    user_id = request.current_user['id']
    conn = get_db_connection()
    cursor = conn.cursor()
    unchecked_rows = conn.execute('SELECT id, item FROM groceries WHERE checked = 0 AND user_id = ?', (user_id,)).fetchall()

    if not unchecked_rows:
        conn.close()
        return jsonify({'message': 'No unchecked groceries to consolidate', 'count': 0}), 200

    raw_items = [r['item'] for r in unchecked_rows]
    consolidated = consolidate_ingredients(raw_items)

    # Delete existing unchecked rows and re-insert consolidated ones
    cursor.execute('DELETE FROM groceries WHERE checked = 0 AND user_id = ?', (user_id,))
    for item in consolidated:
        cursor.execute('INSERT INTO groceries (user_id, item, checked) VALUES (?, ?, 0)', (user_id, item))

    conn.commit()
    conn.close()
    return jsonify({
        'message': f'Consolidated {len(raw_items)} items into {len(consolidated)} clean items!',
        'count': len(consolidated)
    }), 200

@app.route('/api/groceries/<int:item_id>/toggle', methods=['POST'])
@login_required
def toggle_grocery(item_id):
    user_id = request.current_user['id']
    conn = get_db_connection()
    cursor = conn.cursor()
    row = conn.execute('SELECT checked FROM groceries WHERE id = ? AND user_id = ?', (item_id, user_id)).fetchone()
    if not row:
        conn.close()
        return jsonify({'error': 'Item not found'}), 404
    new_status = 0 if row['checked'] else 1
    cursor.execute("UPDATE groceries SET checked = ? WHERE id = ? AND user_id = ?", (new_status, item_id, user_id))
    conn.commit()
    conn.close()
    return jsonify({'message': 'Grocery item updated', 'checked': bool(new_status)}), 200

@app.route('/api/groceries/<int:item_id>', methods=['DELETE'])
@login_required
def delete_grocery(item_id):
    user_id = request.current_user['id']
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("DELETE FROM groceries WHERE id = ? AND user_id = ?", (item_id, user_id))
    conn.commit()
    rows_affected = cursor.rowcount
    conn.close()
    if rows_affected > 0:
        return jsonify({'message': 'Grocery item deleted'}), 200
    else:
        return jsonify({'error': 'Item not found'}), 404

@app.route('/api/groceries/clear-checked', methods=['POST'])
@login_required
def clear_checked_groceries():
    user_id = request.current_user['id']
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("DELETE FROM groceries WHERE checked = 1 AND user_id = ?", (user_id,))
    conn.commit()
    conn.close()
    return jsonify({'message': 'Cleared checked groceries'}), 200

# --- Sticky Notes Endpoints ---

@app.route('/api/stickies', methods=['GET'])
@login_required
def get_stickies():
    user_id = request.current_user['id']
    conn = get_db_connection()
    rows = conn.execute('SELECT * FROM stickies WHERE user_id = ? ORDER BY id DESC', (user_id,)).fetchall()
    conn.close()
    return jsonify([{'id': r['id'], 'content': r['content'], 'author': r['author'], 'created_at': r['created_at']} for r in rows])

@app.route('/api/stickies', methods=['POST'])
@login_required
def add_sticky():
    user_id = request.current_user['id']
    data = request.get_json() or {}
    content = data.get('content', '').strip()
    author = data.get('author', '').strip() or 'Note'
    if not content:
        return jsonify({'error': 'Content is required'}), 400

    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("INSERT INTO stickies (user_id, content, author) VALUES (?, ?, ?)", (user_id, content, author))
    conn.commit()
    new_id = cursor.lastrowid
    conn.close()
    return jsonify({'message': 'Sticky added', 'id': new_id}), 201

@app.route('/api/stickies/<int:sticky_id>', methods=['DELETE'])
@login_required
def delete_sticky(sticky_id):
    user_id = request.current_user['id']
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("DELETE FROM stickies WHERE id = ? AND user_id = ?", (sticky_id, user_id))
    conn.commit()
    rows_affected = cursor.rowcount
    conn.close()
    if rows_affected > 0:
        return jsonify({'message': 'Sticky deleted'}), 200
    else:
        return jsonify({'error': 'Sticky not found'}), 404

# --- Pantry & "What Can I Make?" Endpoints ---

@app.route('/api/pantry', methods=['GET'])
@login_required
def get_pantry():
    user_id = request.current_user['id']
    conn = get_db_connection()
    items = conn.execute('SELECT * FROM pantry WHERE user_id = ? ORDER BY item ASC', (user_id,)).fetchall()
    conn.close()
    return jsonify([{
        'id': row['id'],
        'item': row['item'],
        'category': row['category'] if 'category' in row.keys() else 'General'
    } for row in items])

@app.route('/api/pantry', methods=['POST'])
@login_required
def add_pantry_items():
    user_id = request.current_user['id']
    data = request.get_json() or {}
    raw_input = data.get('item', '')
    category = data.get('category', 'General')

    if isinstance(raw_input, str):
        # Split by comma or newline
        lines = [x.strip() for line in raw_input.split('\n') for x in line.split(',') if x.strip()]
    elif isinstance(raw_input, list):
        lines = [str(x).strip() for x in raw_input if str(x).strip()]
    else:
        lines = []

    if not lines:
        return jsonify({'error': 'No pantry items provided'}), 400

    conn = get_db_connection()
    cursor = conn.cursor()
    added_count = 0
    for item_text in lines:
        # Avoid duplicate inserts for this user
        exists = cursor.execute('SELECT id FROM pantry WHERE LOWER(item) = ? AND user_id = ?', (item_text.lower(), user_id)).fetchone()
        if not exists:
            cursor.execute('INSERT INTO pantry (user_id, item, category) VALUES (?, ?, ?)', (user_id, item_text, category))
            added_count += 1

    conn.commit()
    conn.close()
    return jsonify({'message': f'Added {added_count} items to pantry'}), 201

@app.route('/api/pantry/<int:item_id>', methods=['DELETE'])
@login_required
def delete_pantry_item(item_id):
    user_id = request.current_user['id']
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute('DELETE FROM pantry WHERE id = ? AND user_id = ?', (item_id, user_id))
    conn.commit()
    rows_affected = cursor.rowcount
    conn.close()
    if rows_affected > 0:
        return jsonify({'message': 'Pantry item deleted'}), 200
    else:
        return jsonify({'error': 'Item not found'}), 404

@app.route('/api/pantry/clear', methods=['POST'])
@login_required
def clear_pantry():
    user_id = request.current_user['id']
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute('DELETE FROM pantry WHERE user_id = ?', (user_id,))
    conn.commit()
    conn.close()
    return jsonify({'message': 'Pantry cleared'}), 200

# --- Backup & Restore Endpoints ---

@app.route('/api/backup', methods=['GET'])
@login_required
def get_backup():
    user_id = request.current_user['id']
    conn = get_db_connection()
    recipes_db = conn.execute('SELECT * FROM recipes WHERE user_id = ?', (user_id,)).fetchall()
    planner_db = conn.execute('SELECT * FROM planner WHERE user_id = ?', (user_id,)).fetchall()
    groceries_db = conn.execute('SELECT * FROM groceries WHERE user_id = ?', (user_id,)).fetchall()
    stickies_db = conn.execute('SELECT * FROM stickies WHERE user_id = ?', (user_id,)).fetchall()
    pantry_db = conn.execute('SELECT * FROM pantry WHERE user_id = ?', (user_id,)).fetchall()
    conn.close()

    backup_data = {
        'version': '2.0',
        'exported_at': datetime.now(timezone.utc).isoformat(),
        'user': request.current_user['username'],
        'recipes': [dict(r) for r in recipes_db],
        'planner': [dict(p) for p in planner_db],
        'groceries': [dict(g) for g in groceries_db],
        'stickies': [dict(s) for s in stickies_db],
        'pantry': [dict(pt) for pt in pantry_db]
    }
    return jsonify(backup_data)

@app.route('/api/restore', methods=['POST'])
@login_required
def restore_backup():
    user_id = request.current_user['id']
    payload = request.get_json()
    if not payload:
        return jsonify({'error': 'Invalid backup JSON payload'}), 400

    mode = payload.get('mode', 'merge')  # 'merge' or 'replace'
    data = payload.get('data', payload)

    conn = get_db_connection()
    cursor = conn.cursor()

    try:
        if mode == 'replace':
            cursor.execute('DELETE FROM recipes WHERE user_id = ?', (user_id,))
            cursor.execute('DELETE FROM planner WHERE user_id = ?', (user_id,))
            cursor.execute('DELETE FROM groceries WHERE user_id = ?', (user_id,))
            cursor.execute('DELETE FROM stickies WHERE user_id = ?', (user_id,))
            cursor.execute('DELETE FROM pantry WHERE user_id = ?', (user_id,))

        # Restore recipes
        recipes = data.get('recipes', [])
        for r in recipes:
            title = r.get('title', '').strip()
            if not title:
                continue
            if mode == 'merge':
                exists = cursor.execute('SELECT id FROM recipes WHERE LOWER(title) = ? AND user_id = ?', (title.lower(), user_id)).fetchone()
                if exists:
                    continue
            cursor.execute('''
                INSERT INTO recipes (user_id, title, ingredients, instructions, category, is_favorite, prep_time, cook_time, difficulty, servings)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ''', (
                user_id,
                title,
                r.get('ingredients', ''),
                r.get('instructions', ''),
                r.get('category', 'General'),
                1 if r.get('is_favorite') else 0,
                r.get('prep_time', ''),
                r.get('cook_time', ''),
                r.get('difficulty', 'Easy'),
                r.get('servings', '')
            ))

        # Restore planner
        planner = data.get('planner', [])
        if isinstance(planner, dict):
            # If exported as { "YYYY-MM-DD": { meals, tasks, notes } }
            for date_key, p_data in planner.items():
                meals = p_data.get('meals', {})
                cursor.execute('''
                    INSERT INTO planner (user_id, date_key, breakfast, lunch, dinner, tasks, notes)
                    VALUES (?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT(user_id, date_key) DO UPDATE SET
                        breakfast = excluded.breakfast,
                        lunch = excluded.lunch,
                        dinner = excluded.dinner,
                        tasks = excluded.tasks,
                        notes = excluded.notes
                ''', (
                    user_id,
                    date_key,
                    meals.get('breakfast', 'Not planned'),
                    meals.get('lunch', 'Not planned'),
                    meals.get('dinner', 'Not planned'),
                    p_data.get('tasks', ''),
                    p_data.get('notes', '')
                ))
        elif isinstance(planner, list):
            for p in planner:
                date_key = p.get('date_key', '').strip()
                if not date_key:
                    continue
                cursor.execute('''
                    INSERT INTO planner (user_id, date_key, breakfast, lunch, dinner, tasks, notes)
                    VALUES (?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT(user_id, date_key) DO UPDATE SET
                        breakfast = excluded.breakfast,
                        lunch = excluded.lunch,
                        dinner = excluded.dinner,
                        tasks = excluded.tasks,
                        notes = excluded.notes
                ''', (
                    user_id,
                    date_key,
                    p.get('breakfast', 'Not planned'),
                    p.get('lunch', 'Not planned'),
                    p.get('dinner', 'Not planned'),
                    p.get('tasks', ''),
                    p.get('notes', '')
                ))

        # Restore groceries
        groceries = data.get('groceries', [])
        for g in groceries:
            item = g.get('item', '').strip()
            if not item:
                continue
            if mode == 'merge':
                exists = cursor.execute('SELECT id FROM groceries WHERE LOWER(item) = ? AND checked = ? AND user_id = ?', (item.lower(), 1 if g.get('checked') else 0, user_id)).fetchone()
                if exists:
                    continue
            cursor.execute('INSERT INTO groceries (user_id, item, checked) VALUES (?, ?, ?)', (user_id, item, 1 if g.get('checked') else 0))

        # Restore stickies
        stickies = data.get('stickies', [])
        for s in stickies:
            content = s.get('content', '').strip()
            if not content:
                continue
            cursor.execute('INSERT INTO stickies (user_id, content, author) VALUES (?, ?, ?)', (user_id, content, s.get('author', 'Note')))

        # Restore pantry
        pantry = data.get('pantry', [])
        for pt in pantry:
            item = pt.get('item', '').strip()
            if not item:
                continue
            if mode == 'merge':
                exists = cursor.execute('SELECT id FROM pantry WHERE LOWER(item) = ? AND user_id = ?', (item.lower(), user_id)).fetchone()
                if exists:
                    continue
            cursor.execute('INSERT INTO pantry (user_id, item, category) VALUES (?, ?, ?)', (user_id, item, pt.get('category', 'General')))

        conn.commit()
        conn.close()
        return jsonify({'message': f'Backup successfully restored ({mode} mode)'}), 200

    except Exception as e:
        conn.rollback()
        conn.close()
        return jsonify({'error': str(e)}), 500

if __name__ == '__main__':
    # For development only. For production, use Gunicorn/Nginx.
    app.run(host='0.0.0.0', port=5000, debug=True)

