import sqlite3
import os
import shutil
import datetime
from src.paths import DB_PATH, BACKUP_DIR

_UNSET = object()

class Database:
    def __init__(self):
        self.conn = sqlite3.connect(DB_PATH, check_same_thread=False)
        self.conn.row_factory = sqlite3.Row
        self._init_db()

    def _init_db(self):
        with self.conn:
            self.conn.execute('''
                CREATE TABLE IF NOT EXISTS channels (
                    name TEXT PRIMARY KEY,
                    streak TEXT DEFAULT '?',
                    status TEXT DEFAULT 'baseline',
                    is_live BOOLEAN DEFAULT 0,
                    last_update TEXT DEFAULT 'Nie',
                    error_count INTEGER DEFAULT 0,
                    offline_checks INTEGER DEFAULT 0,
                    offline_since TEXT DEFAULT NULL
                )
            ''')
            cursor = self.conn.execute("PRAGMA table_info(channels)")
            channel_columns = {row['name'] for row in cursor.fetchall()}
            if 'offline_since' not in channel_columns:
                self.conn.execute("ALTER TABLE channels ADD COLUMN offline_since TEXT DEFAULT NULL")

            self.conn.execute('''
                CREATE TABLE IF NOT EXISTS settings (
                    key TEXT PRIMARY KEY,
                    value TEXT
                )
            ''')
            # Initialize default settings if not exists
            cursor = self.conn.cursor()
            cursor.execute("SELECT COUNT(*) FROM settings")
            if cursor.fetchone()[0] == 0:
                defaults = [
                    ('radar_interval_minutes', '15'),
                    ('worker_limit', '3'),
                    ('series_check_minutes', '3'),
                    ('max_watch_minutes', '45'),
                    ('headless_mode', '1'),
                    ('mute_audio', '1'),
                    ('auto_chat', '1'),
                    ('auto_cookie', '1'),
                    ('auto_rules', '1'),
                    ('auto_18plus', '1')
                ]
                cursor.executemany("INSERT INTO settings (key, value) VALUES (?, ?)", defaults)

    def get_setting(self, key, default=None):
        cursor = self.conn.cursor()
        cursor.execute("SELECT value FROM settings WHERE key = ?", (key,))
        row = cursor.fetchone()
        return row['value'] if row else default

    def set_setting(self, key, value):
        with self.conn:
            self.conn.execute("INSERT OR REPLACE INTO settings (key, value) VALUES (?, ?)", (key, str(value)))

    def get_all_settings(self):
        cursor = self.conn.cursor()
        cursor.execute("SELECT key, value FROM settings")
        return {row['key']: row['value'] for row in cursor.fetchall()}

    def get_channel(self, name):
        cursor = self.conn.cursor()
        cursor.execute("SELECT * FROM channels WHERE name = ?", (name,))
        row = cursor.fetchone()
        return dict(row) if row else None

    def get_all_channels(self):
        cursor = self.conn.cursor()
        cursor.execute("SELECT * FROM channels")
        return {row['name']: dict(row) for row in cursor.fetchall()}

    def upsert_channel(self, name, streak=None, status=None, is_live=None, last_update=None, error_count=None, offline_checks=None, offline_since=_UNSET):
        channel = self.get_channel(name)
        if not channel:
            channel = {
                'name': name,
                'streak': '?',
                'status': 'baseline',
                'is_live': 0,
                'last_update': 'Nie',
                'error_count': 0,
                'offline_checks': 0,
                'offline_since': None
            }
        
        if streak is not None: channel['streak'] = streak
        if status is not None: channel['status'] = status
        if is_live is not None: channel['is_live'] = 1 if is_live else 0
        if last_update is not None: channel['last_update'] = last_update
        if error_count is not None: channel['error_count'] = error_count
        if offline_checks is not None: channel['offline_checks'] = offline_checks
        if offline_since is not _UNSET: channel['offline_since'] = offline_since

        with self.conn:
            self.conn.execute('''
                INSERT OR REPLACE INTO channels 
                (name, streak, status, is_live, last_update, error_count, offline_checks, offline_since)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            ''', (
                channel['name'], channel['streak'], channel['status'], 
                channel['is_live'], channel['last_update'], channel['error_count'], channel['offline_checks'],
                channel['offline_since']
            ))

    def delete_channel(self, name):
        with self.conn:
            self.conn.execute("DELETE FROM channels WHERE name = ?", (name,))

    def backup_database(self):
        today = datetime.datetime.now().strftime("%Y-%m-%d")
        backup_file = os.path.join(BACKUP_DIR, f"twitchbot_backup_{today}.db")
        if not os.path.exists(backup_file):
            shutil.copy2(DB_PATH, backup_file)
            
            # Keep only last 5 backups
            backups = sorted([f for f in os.listdir(BACKUP_DIR) if f.endswith('.db')])
            while len(backups) > 5:
                oldest = backups.pop(0)
                try:
                    os.remove(os.path.join(BACKUP_DIR, oldest))
                except: pass

    def reset_database(self):
        with self.conn:
            self.conn.execute("DELETE FROM channels")
            # we keep settings
            
db = Database()
