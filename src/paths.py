import os
import sys

def get_appdata_dir():
    # User data (settings, db, logs, cache, token)
    appdata = os.environ.get('APPDATA', '')
    if not appdata:
        appdata = os.path.expanduser('~')
    path = os.path.join(appdata, 'StreamOS')
    os.makedirs(path, exist_ok=True)
    return path

def get_localappdata_dir():
    # Application binaries/installation dir
    localappdata = os.environ.get('LOCALAPPDATA', '')
    if not localappdata:
        localappdata = os.path.expanduser('~')
    path = os.path.join(localappdata, 'StreamOS')
    os.makedirs(path, exist_ok=True)
    return path

def get_base_dir():
    if getattr(sys, 'frozen', False):
        return sys._MEIPASS
    return os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

USER_DATA_DIR = get_appdata_dir()
DB_PATH = os.path.join(USER_DATA_DIR, 'streamos.db')
LOGS_DIR = os.path.join(USER_DATA_DIR, 'logs')
BACKUP_DIR = os.path.join(USER_DATA_DIR, 'backups')
TOKEN_PATH = os.path.join(USER_DATA_DIR, 'auth_token.dat')

os.makedirs(LOGS_DIR, exist_ok=True)
os.makedirs(BACKUP_DIR, exist_ok=True)
