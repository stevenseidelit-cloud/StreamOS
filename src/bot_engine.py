import asyncio
import time
import re
from playwright.async_api import async_playwright
from src.db import db
from src.logger import logger
from src.auth import load_token

class TwitchBotEngine:
    def __init__(self):
        self.is_running = False
        self.tasks = []
        self.active_workers = {}
        self.browser = None
        self.context = None

    async def start(self):
        if self.is_running: return
        self.is_running = True
        logger.info("Starte StreamOS Engine...")
        db.backup_database()
        
        token = load_token()
        if not token:
            logger.error("Kein Token gefunden. Bitte im Dashboard eintragen.")
            self.is_running = False
            return False

        try:
            self.playwright = await async_playwright().start()
            headless = db.get_setting('headless_mode', '1') == '1'
            # Launch in hidden mode or window mode depending on extensions
            args = []
            # TODO: BetterTTV Extension Sideloading
            
            self.browser = await self.playwright.firefox.launch(headless=headless, args=args)
            self.context = await self.browser.new_context(viewport={'width': 1280, 'height': 720})
            await self.context.add_cookies([{'name': 'auth-token', 'value': token, 'domain': '.twitch.tv', 'path': '/'}])
            
            # Start Background Tasks
            self.tasks.append(asyncio.create_task(self._main_loop()))
            return True
        except Exception as e:
            logger.error(f"Fehler beim Starten der Engine: {e}")
            self.is_running = False
            return False

    async def stop(self):
        self.is_running = False
        logger.info("Stoppe Engine...")
        for task in self.tasks:
            task.cancel()
        for worker in self.active_workers.values():
            worker.cancel()
        if self.context: await self.context.close()
        if self.browser: await self.browser.close()
        if hasattr(self, 'playwright'): await self.playwright.stop()
        logger.info("Engine gestoppt.")

    async def _main_loop(self):
        # 1. Sync
        await self._sync_mode()
        
        # 2. Infinite Loop
        while self.is_running:
            await self._radar_mode()
            await self._manage_workers()
            
            radar_interval = int(db.get_setting('radar_interval_minutes', '15'))
            # Wait with interrupt check
            for _ in range(radar_interval * 60):
                if not self.is_running: break
                await asyncio.sleep(1)

    async def _click_banners(self, page):
        if db.get_setting('auto_18plus', '1') == '1':
            try:
                btn_18 = page.locator('button[data-a-target="player-overlay-mature-accept"]')
                if await btn_18.count() > 0: await btn_18.first.click(force=True)
                else:
                    btn_18_alt = page.locator('button:has-text("Anschauen")')
                    if await btn_18_alt.count() > 0: await btn_18_alt.first.click(force=True)
            except: pass
        if db.get_setting('auto_cookie', '1') == '1':
            try:
                cookie_btn = page.locator('button[data-a-target="consent-banner-accept"]')
                if await cookie_btn.count() > 0: await cookie_btn.first.click(force=True)
            except: pass
        if db.get_setting('auto_rules', '1') == '1':
            try:
                btn_rules = await page.wait_for_selector('button[data-test-selector="chat-rules-ok-button"]', timeout=1000)
                if btn_rules: await btn_rules.click(force=True)
            except: pass

    async def _fetch_followers(self):
        try:
            page = await self.context.new_page()
            await page.goto("https://www.twitch.tv/directory/following/channels", timeout=30000)
            await asyncio.sleep(5)
            await self._click_banners(page)
            
            # Scroll down to load all
            for _ in range(10):
                await page.keyboard.press("End")
                await asyncio.sleep(1)
                
            links = await page.locator('div[data-a-target="followed-channel"] a[href^="/"], a[data-a-target="side-nav-live-channel"]').all()
            if not links:
                links = await page.locator('div[aria-label="Kanäle, denen du folgst"] a[href^="/"], div[aria-label="Folge ich"] a[href^="/"], div[aria-label="Followed Channels"] a[href^="/"]').all()
            
            found = []
            for link in links:
                href = await link.get_attribute('href')
                if href:
                    clean_href = href.split('?')[0].strip('/')
                    if len(clean_href.split('/')) == 1:
                        name = clean_href.lower()
                        if len(name) > 2 and " " not in name:
                            found.append(name)
                            
            await page.close()
            found = list(set(found))
            logger.info(f"Habe {len(found)} Follower gefunden.")
            
            for c in found:
                db.upsert_channel(c) # will keep existing data due to upsert logic
                
            return found
        except Exception as e:
            logger.error(f"Fehler beim Laden der Follower: {e}")
            return []

    async def _sync_mode(self):
        logger.info("Starte Initiale Erfassung (Sync Modus)...")
        channels = self._fetch_followers()
        if asyncio.iscoroutine(channels):
            channels = await channels
            
        all_channels = db.get_all_channels()
        to_sync = [c for c, data in all_channels.items() if data['status'] == 'baseline']
        
        if not to_sync:
            logger.info("Keine Kanäle für Sync gefunden.")
            return

        for c in to_sync:
            if not self.is_running: break
            logger.info(f"Sync für {c}...")
            try:
                page = await self.context.new_page()
                await page.goto(f"https://www.twitch.tv/popout/{c}/chat", timeout=20000)
                await asyncio.sleep(3)
                await self._click_banners(page)
                
                try:
                    btn = await page.wait_for_selector('.community-points-summary button:last-child', timeout=15000)
                    if btn: await btn.click(force=True)
                    await asyncio.sleep(2)
                    try:
                        intro_btn = await page.wait_for_selector("text=Los geht", timeout=1000)
                        if intro_btn: await intro_btn.click(force=True)
                    except: pass
                    
                    all_text = await page.evaluate("document.body.innerText")
                    match = re.search(r'(?i)(?:serie|streak):\s*(\d+)', all_text)
                    if match:
                        streak = match.group(1)
                        logger.info(f"✅ {c} Serie: {streak}")
                        db.upsert_channel(c, streak=streak, status='Bereit')
                    else:
                        logger.info(f"❌ {c} keine Serie gefunden, setze auf 0.")
                        db.upsert_channel(c, streak="0", status='Bereit')
                except Exception as e:
                    logger.info(f"❌ {c} Fehler im Sync ({e}), setze auf 0.")
                    db.upsert_channel(c, streak="0", status='Bereit')
            except Exception as e:
                logger.error(f"❌ Schwerer Fehler beim Sync von {c}: {e}")
                db.upsert_channel(c, streak="0", status='Bereit')
            finally:
                try: await page.close()
                except: pass
                
        logger.info("Sync beendet.")

    async def _radar_mode(self):
        if not self.is_running: return
        logger.info("Starte Radar (Live-Prüfung)...")
        # In a real scenario we could use Twitch API or scrape the sidebar. 
        # Using sidebar scrape for now to avoid needing Twitch Client IDs.
        try:
            page = await self.context.new_page()
            await page.goto("https://www.twitch.tv/", timeout=30000)
            await asyncio.sleep(5)
            await self._click_banners(page)
            
            try:
                show_more = page.locator('button:has-text("Mehr anzeigen")')
                for _ in range(3):
                    if await show_more.count() > 0: 
                        await show_more.first.click(force=True)
                        await asyncio.sleep(1)
                    else: break
            except: pass
            
            links = await page.locator('div[aria-label="Kanäle, denen du folgst"] a[href^="/"], div[aria-label="Folge ich"] a[href^="/"], div[aria-label="Followed Channels"] a[href^="/"]').all()
            if not links:
                links = await page.locator('div[data-a-target="followed-channel"] a[href^="/"], a[data-a-target="side-nav-live-channel"]').all()

            live_channels = []
            for link in links:
                href = await link.get_attribute('href')
                if href:
                    clean_href = href.split('?')[0].strip('/')
                    if len(clean_href.split('/')) == 1:
                        name = clean_href.lower()
                        live_channels.append(name)
            
            await page.close()
            
            all_channels = db.get_all_channels()
            
            for c, data in all_channels.items():
                if c in live_channels:
                    db.upsert_channel(c, is_live=True, offline_checks=0)
                    if data['status'] == 'Offline-Warteschleife':
                        db.upsert_channel(c, status='Bereit')
                else:
                    db.upsert_channel(c, is_live=False)
                    if data['status'] == 'Erledigt':
                        # Offline Reset logic
                        checks = data.get('offline_checks', 0) + 1
                        if checks >= 3:
                            db.upsert_channel(c, status='Offline-Warteschleife', offline_checks=0)
                        else:
                            db.upsert_channel(c, offline_checks=checks)
                            
            logger.info(f"Radar beendet. {len(live_channels)} Kanäle live.")
        except Exception as e:
            logger.error(f"Fehler im Radar: {e}")

    async def _manage_workers(self):
        if not self.is_running: return
        all_channels = db.get_all_channels()
        limit = int(db.get_setting('worker_limit', '3'))
        
        # Clean up dead tasks
        done_workers = [c for c, t in self.active_workers.items() if t.done()]
        for c in done_workers:
            del self.active_workers[c]
            
        if len(self.active_workers) >= limit:
            return
            
        # Start new workers
        for c, data in all_channels.items():
            if len(self.active_workers) >= limit:
                break
            if data['is_live'] and data['status'] == 'Bereit' and c not in self.active_workers:
                db.upsert_channel(c, status='Live: Überwachung läuft')
                task = asyncio.create_task(self._worker_task(c))
                self.active_workers[c] = task

    async def _worker_task(self, channel_name):
        logger.info(f"[{channel_name}] Worker gestartet...")
        try:
            page = await self.context.new_page()
            await page.goto(f"https://www.twitch.tv/{channel_name}")
            await asyncio.sleep(4)
            
            await self._click_banners(page)
            
            # Start Series Check
            initial_streak = None
            try:
                btn = await page.wait_for_selector('.community-points-summary button:last-child', timeout=15000)
                if btn: await btn.click(force=True)
                await asyncio.sleep(2)
                try:
                    intro_btn = await page.wait_for_selector("text=Los geht", timeout=1000)
                    if intro_btn: await intro_btn.click(force=True)
                except: pass
                
                all_text = await page.evaluate("document.body.innerText")
                match = re.search(r'(?i)(?:serie|streak):\s*(\d+)', all_text)
                if match: initial_streak = match.group(1)
                else: initial_streak = "0"
                await page.keyboard.press("Escape")
            except Exception as e:
                logger.warning(f"[{channel_name}] Fehler beim initialen Lesen: {e}")
                initial_streak = "0"
                
            db.upsert_channel(channel_name, streak=initial_streak)
            saved_streak = int(initial_streak)
            
            max_minutes = int(db.get_setting('max_watch_minutes', '45'))
            check_interval = int(db.get_setting('series_check_minutes', '3'))
            start_time = time.time()
            checks = 0
            
            while self.is_running and (time.time() - start_time) < (max_minutes * 60):
                await asyncio.sleep(check_interval * 60)
                if not self.is_running: break
                
                try:
                    btn = await page.wait_for_selector('.community-points-summary button:last-child', timeout=5000)
                    if btn: await btn.click(force=True)
                    await asyncio.sleep(2)
                    all_text = await page.evaluate("document.body.innerText")
                    match = re.search(r'(?i)(?:serie|streak):\s*(\d+)', all_text)
                    if match:
                        current = int(match.group(1))
                        if current > saved_streak:
                            logger.info(f"[{channel_name}] 🎉 Serie erhöht auf {current}!")
                            db.upsert_channel(channel_name, streak=str(current), status='Erledigt')
                            await page.close()
                            return
                    await page.keyboard.press("Escape")
                except: pass
                
                # Check for bonus chest
                try:
                    chest = page.locator('button[aria-label="Bonus abholen"]')
                    if await chest.count() > 0:
                        await chest.first.click(force=True)
                        logger.info(f"[{channel_name}] 🎁 Bonustruhe abgeholt!")
                except: pass
                
                checks += 1
                
            # Timeout
            logger.info(f"[{channel_name}] Timeout nach {max_minutes} Minuten erreicht.")
            db.upsert_channel(channel_name, status='Bereit')
            await page.close()
            
        except Exception as e:
            logger.error(f"[{channel_name}] Worker Fehler: {e}")
            channel = db.get_channel(channel_name)
            errors = channel.get('error_count', 0) + 1
            if errors >= 3:
                db.upsert_channel(channel_name, status='Fehler', error_count=errors)
            else:
                db.upsert_channel(channel_name, status='Bereit', error_count=errors)
            try: await page.close()
            except: pass
