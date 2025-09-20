# database.py
import os
import psycopg2
from psycopg2.extras import DictCursor
import uuid
import logging

# --- Database Connection ---
def get_db_connection():
    """Establishes a connection to the PostgreSQL database."""
    try:
        conn = psycopg2.connect(os.environ.get('DATABASE_URL'))
        return conn
    except psycopg2.OperationalError as e:
        logging.error(f"Could not connect to the database: {e}")
        raise

# --- Database Setup ---
def setup_database():
    """Creates all necessary tables if they don't exist."""
    conn = get_db_connection()
    with conn.cursor() as cur:
        # Users table to store user info, balance, referral data, and premium status
        cur.execute('''
            CREATE TABLE IF NOT EXISTS users (
                user_id BIGINT PRIMARY KEY,
                first_name TEXT,
                balance REAL DEFAULT 10.0,
                referral_code TEXT UNIQUE,
                referred_by BIGINT DEFAULT NULL,
                is_premium BOOLEAN DEFAULT FALSE,
                premium_expiry TIMESTAMPTZ DEFAULT NULL
            );
        ''')
        # Staff table for moderators
        cur.execute('''
            CREATE TABLE IF NOT EXISTS staff (
                user_id BIGINT PRIMARY KEY,
                role TEXT NOT NULL,
                referral_link TEXT UNIQUE,
                commission_balance REAL DEFAULT 0.0
            );
        ''')
        # Activity log for tracking staff actions
        cur.execute('''
            CREATE TABLE IF NOT EXISTS activity_log (
                id SERIAL PRIMARY KEY,
                staff_id BIGINT,
                action TEXT,
                target_user_id BIGINT,
                details TEXT,
                timestamp TIMESTAMPTZ DEFAULT NOW()
            );
        ''')
        # Settings table for prices and other configurations
        cur.execute('''
            CREATE TABLE IF NOT EXISTS settings (
                key TEXT PRIMARY KEY,
                value TEXT
            );
        ''')
        # Insert default prices and settings if they don't exist
        defaults = {
            'price_email_ad': '0.0',
            'price_email_credit': '1.0',
            'price_number_other': '15.0',
            'price_number_facebook': '30.0',
            'price_number_google': '50.0',
            'referral_bonus': '5.0',
            'signup_bonus': '10.0'
        }
        for key, value in defaults.items():
            cur.execute("INSERT INTO settings (key, value) VALUES (%s, %s) ON CONFLICT (key) DO NOTHING;", (key, value))

    conn.commit()
    conn.close()
    print("Database setup checked/completed.")

# --- Helper Functions ---
# (These will be used by the bot logic files)
def get_user(user_id):
    conn = get_db_connection()
    with conn.cursor(cursor_factory=DictCursor) as cur:
        cur.execute("SELECT * FROM users WHERE user_id = %s", (user_id,))
        user = cur.fetchone()
    conn.close()
    return user

def get_setting(key):
    conn = get_db_connection()
    with conn.cursor() as cur:
        cur.execute("SELECT value FROM settings WHERE key = %s", (key,))
        result = cur.fetchone()
    conn.close()
    # Return a default value of 0.0 if not found, to prevent errors
    return float(result[0]) if result else 0.0

def add_user_if_not_exists(user_id, first_name, referral_code=None):
    conn = get_db_connection()
    with conn.cursor(cursor_factory=DictCursor) as cur:
        cur.execute("SELECT * FROM users WHERE user_id = %s", (user_id,))
        user = cur.fetchone()
        if not user:
            new_referral_code = str(uuid.uuid4())[:8]
            signup_bonus = get_setting('signup_bonus')

            referred_by_id = None
            if referral_code:
                cur.execute("SELECT user_id FROM users WHERE referral_code = %s", (referral_code,))
                referrer = cur.fetchone()
                if referrer:
                    referred_by_id = referrer['user_id']
                    referral_bonus = get_setting('referral_bonus')
                    cur.execute("UPDATE users SET balance = balance + %s WHERE user_id = %s", (referral_bonus, referred_by_id))

            cur.execute(
                "INSERT INTO users (user_id, first_name, balance, referral_code, referred_by) VALUES (%s, %s, %s, %s, %s)",
                (user_id, first_name, signup_bonus, new_referral_code, referred_by_id)
            )
    conn.commit()
    conn.close()

# Initialize the database on startup
try:
    setup_database()
except Exception as e:
    print(f"Could not set up database on startup: {e}")