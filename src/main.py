import os
import sys
import ctypes
# Add Neu path to sys path to allow absolute imports
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import asyncio
import webview
import threading
from src.bot_engine import TwitchBotEngine
from src.server import ApiServer
from src.logger import logger

def start_background_loop(loop):
    asyncio.set_event_loop(loop)
    loop.run_forever()

def show_startup_error(message):
    logger.error(message)
    try:
        ctypes.windll.user32.MessageBoxW(
            0,
            message,
            'StreamOS 0.0.1',
            0x10
        )
    except Exception:
        pass

if __name__ == '__main__':
    logger.info("===== NEUER START =====")
    logger.info("BUILD: STREAMOS-0.0.1")
    logger.info("Starte StreamOS...")
    
    # We need a separate asyncio thread because webview runs on the main thread
    loop = asyncio.new_event_loop()
    t = threading.Thread(target=start_background_loop, args=(loop,), daemon=True)
    t.start()

    engine = TwitchBotEngine()
    server = ApiServer(engine)
    
    # Start server in the background loop
    server_future = asyncio.run_coroutine_threadsafe(server.start(), loop)
    try:
        server_future.result(timeout=10)
    except Exception as e:
        show_startup_error(
            "StreamOS konnte den lokalen Dienst auf Port 8080 nicht starten.\n\n"
            "Möglicherweise läuft StreamOS bereits. Bitte schließe die andere Instanz "
            f"und versuche es erneut.\n\nTechnischer Fehler: {e}"
        )
        loop.call_soon_threadsafe(loop.stop)
        t.join(timeout=3)
        sys.exit(1)
    
    # Create the webview window
    webview.create_window(
        'StreamOS 0.0.1',
        'http://localhost:8080/index.html',
        width=1200,
        height=800,
        background_color='#18181b',
        frameless=False
    )
    
    # Start the webview loop. This will block until the window is closed.
    webview.start()
    
    logger.info("Applikation beendet.")
    # Graceful shutdown
    if engine.is_running:
        asyncio.run_coroutine_threadsafe(engine.stop(), loop)
    loop.call_soon_threadsafe(loop.stop)
    t.join(timeout=3)
