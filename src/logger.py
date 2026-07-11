import logging
import os
from logging.handlers import RotatingFileHandler
from src.paths import LOGS_DIR

log_formatter = logging.Formatter('%(asctime)s - %(levelname)s - %(message)s')

log_file = os.path.join(LOGS_DIR, 'twitchbot.log')

# Max 5 MB, 5 backups
file_handler = RotatingFileHandler(log_file, maxBytes=5*1024*1024, backupCount=5, encoding='utf-8')
file_handler.setFormatter(log_formatter)
file_handler.setLevel(logging.INFO)

console_handler = logging.StreamHandler()
console_handler.setFormatter(log_formatter)
console_handler.setLevel(logging.INFO)

logger = logging.getLogger('TwitchBot')
logger.setLevel(logging.INFO)
logger.addHandler(file_handler)
logger.addHandler(console_handler)

def get_recent_logs(limit=100):
    if not os.path.exists(log_file):
        return []
    try:
        with open(log_file, 'r', encoding='utf-8') as f:
            lines = f.readlines()
            return lines[-limit:]
    except:
        return []
