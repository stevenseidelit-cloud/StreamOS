import asyncio
from aiohttp import web
import json
import os
from src.db import db
from src.paths import get_base_dir
from src.logger import get_recent_logs
from src.auth import save_token, load_token

class ApiServer:
    def __init__(self, engine):
        self.engine = engine
        self.app = web.Application()
        self.app.add_routes([
            web.get('/api/status', self.get_status),
            web.get('/api/channels', self.get_channels),
            web.get('/api/settings', self.get_settings),
            web.post('/api/settings', self.post_settings),
            web.get('/api/logs', self.get_logs),
            web.post('/api/action', self.post_action),
            web.post('/api/token', self.post_token),
            web.get('/api/token/status', self.get_token_status),
            
            # Serve static UI files
            web.static('/', os.path.join(get_base_dir(), 'ui'))
        ])

    async def start(self):
        runner = web.AppRunner(self.app)
        await runner.setup()
        site = web.TCPSite(runner, 'localhost', 8080)
        await site.start()

    async def get_status(self, request):
        return web.json_response({
            'is_running': self.engine.is_running,
            'active_workers': len(self.engine.active_workers),
            'worker_limit': int(db.get_setting('worker_limit', '3'))
        })

    async def get_channels(self, request):
        return web.json_response(db.get_all_channels())

    async def get_settings(self, request):
        return web.json_response(db.get_all_settings())

    async def post_settings(self, request):
        data = await request.json()
        for k, v in data.items():
            db.set_setting(k, v)
        return web.json_response({'status': 'ok'})

    async def get_logs(self, request):
        return web.json_response({'logs': get_recent_logs(200)})

    async def post_action(self, request):
        data = await request.json()
        action = data.get('action')
        
        if action == 'start':
            if not self.engine.is_running:
                asyncio.create_task(self.engine.start())
        elif action == 'stop':
            if self.engine.is_running:
                asyncio.create_task(self.engine.stop())
        elif action == 'sync':
            if self.engine.is_running:
                asyncio.create_task(self.engine._sync_mode())
        elif action == 'reset_channel':
            name = data.get('channel')
            db.upsert_channel(name, status='Bereit', error_count=0)
        elif action == 'delete_db':
            db.reset_database()
        elif action == 'backup_db':
            db.backup_database()
            
        return web.json_response({'status': 'ok'})

    async def post_token(self, request):
        data = await request.json()
        token = data.get('token')
        success = save_token(token)
        return web.json_response({'success': success})

    async def get_token_status(self, request):
        token = load_token()
        return web.json_response({'has_token': token is not None})
