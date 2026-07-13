import hashlib
import asyncio
import os
import re
import subprocess
from pathlib import Path

import aiohttp

from src.logger import logger


CURRENT_VERSION = "0.0.1"
GITHUB_REPOSITORY = "stevenseidelit-cloud/StreamOS"
LATEST_RELEASE_URL = f"https://api.github.com/repos/{GITHUB_REPOSITORY}/releases/latest"
VERSION_PATTERN = re.compile(r"^\d+\.\d+\.\d+$")


class UpdateError(Exception):
    pass


class GitHubUpdater:
    def __init__(self):
        downloads_dir = Path.home() / "Downloads" / "StreamOS"
        self.downloads_dir = downloads_dir
        self._latest_release = None
        self._verified_setup_path = None
        self._downloaded_portable_path = None

    @staticmethod
    def _version_tuple(version):
        return tuple(int(part) for part in version.split('.'))

    async def _request_json(self, url):
        timeout = aiohttp.ClientTimeout(total=30)
        headers = {
            'Accept': 'application/vnd.github+json',
            'User-Agent': f'StreamOS/{CURRENT_VERSION}',
            'X-GitHub-Api-Version': '2022-11-28'
        }
        try:
            async with aiohttp.ClientSession(timeout=timeout, headers=headers) as session:
                async with session.get(url) as response:
                    if response.status != 200:
                        raise UpdateError(
                            f"GitHub antwortete beim Abruf des Releases mit HTTP {response.status}."
                        )
                    return await response.json()
        except (aiohttp.ClientError, asyncio.TimeoutError) as e:
            raise UpdateError(f"GitHub konnte nicht erreicht werden: {e}") from e

    async def _fetch_latest_release(self):
        release = await self._request_json(LATEST_RELEASE_URL)
        version = str(release.get('tag_name', '')).removeprefix('v')
        if not VERSION_PATTERN.fullmatch(version):
            raise UpdateError(
                f"Das neueste GitHub-Release hat keinen gültigen vX.Y.Z-Tag: "
                f"{release.get('tag_name')!r}"
            )

        assets = {
            asset.get('name'): asset
            for asset in release.get('assets', [])
            if asset.get('name') and asset.get('browser_download_url')
        }
        release['_streamos_version'] = version
        release['_streamos_assets'] = assets
        self._latest_release = release
        return release

    async def check_for_update(self):
        release = await self._fetch_latest_release()
        version = release['_streamos_version']
        assets = release['_streamos_assets']
        portable_name = f"StreamOS_{version}_Portable.zip"
        setup_name = f"StreamOS_{version}_Setup.exe"

        return {
            'current_version': CURRENT_VERSION,
            'latest_version': version,
            'update_available': self._version_tuple(version) > self._version_tuple(CURRENT_VERSION),
            'portable_available': (
                portable_name in assets and f"{portable_name}.sha256" in assets
            ),
            'setup_available': (
                setup_name in assets and f"{setup_name}.sha256" in assets
            ),
            'release_url': release.get('html_url')
        }

    async def _download_text(self, url):
        timeout = aiohttp.ClientTimeout(total=60)
        headers = {'User-Agent': f'StreamOS/{CURRENT_VERSION}'}
        try:
            async with aiohttp.ClientSession(timeout=timeout, headers=headers) as session:
                async with session.get(url) as response:
                    if response.status != 200:
                        raise UpdateError(
                            f"Prüfsumme konnte nicht geladen werden (HTTP {response.status})."
                        )
                    return await response.text()
        except (aiohttp.ClientError, asyncio.TimeoutError) as e:
            raise UpdateError(f"Prüfsumme konnte nicht geladen werden: {e}") from e

    async def _download_file(self, url, target_path):
        timeout = aiohttp.ClientTimeout(total=900, connect=30, sock_read=120)
        headers = {'User-Agent': f'StreamOS/{CURRENT_VERSION}'}
        temp_path = target_path.with_suffix(target_path.suffix + '.part')
        target_path.parent.mkdir(parents=True, exist_ok=True)

        try:
            async with aiohttp.ClientSession(timeout=timeout, headers=headers) as session:
                async with session.get(url) as response:
                    if response.status != 200:
                        raise UpdateError(
                            f"Release-Datei konnte nicht geladen werden (HTTP {response.status})."
                        )
                    with open(temp_path, 'wb') as file_handle:
                        async for chunk in response.content.iter_chunked(1024 * 1024):
                            file_handle.write(chunk)
            return temp_path
        except Exception as e:
            try:
                temp_path.unlink(missing_ok=True)
            except OSError:
                pass
            if isinstance(e, (aiohttp.ClientError, asyncio.TimeoutError)):
                raise UpdateError(f"Release-Datei konnte nicht geladen werden: {e}") from e
            raise

    @staticmethod
    def _sha256(path):
        digest = hashlib.sha256()
        with open(path, 'rb') as file_handle:
            for chunk in iter(lambda: file_handle.read(1024 * 1024), b''):
                digest.update(chunk)
        return digest.hexdigest().lower()

    async def download_release(self, release_kind):
        if release_kind not in {'portable', 'setup'}:
            raise UpdateError(f"Unbekannte Release-Art: {release_kind!r}")

        release = await self._fetch_latest_release()
        version = release['_streamos_version']
        assets = release['_streamos_assets']
        if release_kind == 'portable':
            filename = f"StreamOS_{version}_Portable.zip"
        else:
            filename = f"StreamOS_{version}_Setup.exe"

        checksum_name = f"{filename}.sha256"
        if filename not in assets or checksum_name not in assets:
            raise UpdateError(
                f"GitHub-Release {version} enthält {filename} oder die SHA-256-Datei nicht."
            )

        checksum_text = await self._download_text(
            assets[checksum_name]['browser_download_url']
        )
        checksum_parts = checksum_text.strip().split()
        expected_hash = checksum_parts[0].lower() if checksum_parts else ''
        if not re.fullmatch(r"[0-9a-f]{64}", expected_hash):
            raise UpdateError(f"Ungültige SHA-256-Datei für {filename}.")

        target_path = self.downloads_dir / filename
        temp_path = await self._download_file(
            assets[filename]['browser_download_url'],
            target_path
        )
        actual_hash = self._sha256(temp_path)
        if actual_hash != expected_hash:
            temp_path.unlink(missing_ok=True)
            raise UpdateError(
                f"SHA-256-Prüfung für {filename} fehlgeschlagen. Datei wurde verworfen."
            )

        os.replace(temp_path, target_path)
        logger.info(f"Update-Datei verifiziert gespeichert: {target_path}")
        if release_kind == 'portable':
            self._downloaded_portable_path = target_path
        else:
            self._verified_setup_path = target_path

        return {
            'kind': release_kind,
            'version': version,
            'filename': filename,
            'local_path': str(target_path),
            'folder_path': str(target_path.parent),
            'sha256': actual_hash
        }

    def open_portable_folder(self):
        if not self._downloaded_portable_path or not self._downloaded_portable_path.exists():
            raise UpdateError("Es wurde noch keine portable Version heruntergeladen.")
        os.startfile(str(self._downloaded_portable_path.parent))

    def launch_verified_installer(self):
        if not self._verified_setup_path or not self._verified_setup_path.exists():
            raise UpdateError("Es wurde noch kein verifizierter Installer heruntergeladen.")
        subprocess.Popen([str(self._verified_setup_path)])
