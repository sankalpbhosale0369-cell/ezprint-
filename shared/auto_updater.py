"""
Auto-update mechanism for EzPrint Agent
Checks for updates from SaaS platform and installs them automatically
"""
import os
import sys
import requests
import subprocess
import tempfile
import hashlib
import logging
from pathlib import Path
from datetime import datetime, timedelta

from shared import version
from shared import config as cfg

logger = logging.getLogger(__name__)

# Update check frequency (don't check more than once per hour)
UPDATE_CHECK_COOLDOWN = timedelta(hours=1)
last_update_check = None


class AutoUpdater:
    """
    Handles automatic updates for the EzPrint Agent
    """

    def __init__(self, shop_id=None, api_token=None):
        """
        Initialize auto-updater

        Args:
            shop_id (str): Shop identifier
            api_token (str): API authentication token
        """
        self.shop_id = shop_id
        self.api_token = api_token or cfg.SHOP_API_TOKEN
        self.current_version = version.VERSION
        self.update_check_url = cfg.UPDATE_CHECK_URL
        self.update_download_url = cfg.UPDATE_DOWNLOAD_URL
        self.channel = cfg.UPDATE_CHANNEL

    def check_for_updates(self, force=False):
        """
        Check if newer version is available

        Args:
            force (bool): Force check even if cooldown hasn't expired

        Returns:
            dict: Update information or None if no update available
                {
                    'update_available': bool,
                    'version': str,
                    'download_url': str,
                    'checksum': str,
                    'critical': bool,
                    'release_notes': str,
                    'size_bytes': int
                }
        """
        global last_update_check

        # Check cooldown
        if not force and last_update_check:
            if datetime.now() - last_update_check < UPDATE_CHECK_COOLDOWN:
                logger.debug("Update check skipped (cooldown active)")
                return {'update_available': False}

        try:
            logger.info(f"Checking for updates (current: v{self.current_version}, channel: {self.channel})")

            headers = {}
            if self.api_token:
                headers['Authorization'] = f'Bearer {self.api_token}'

            params = {
                'current_version': self.current_version,
                'channel': self.channel,
                'platform': sys.platform,
                'shop_id': self.shop_id
            }

            response = requests.get(
                self.update_check_url,
                headers=headers,
                params=params,
                timeout=10
            )

            # Update last check time
            last_update_check = datetime.now()

            if response.status_code == 200:
                data = response.json()

                latest_version = data.get('latest_version')
                if not latest_version:
                    logger.warning("Update check response missing latest_version")
                    return {'update_available': False}

                # Compare versions
                if version.is_newer_version(self.current_version, latest_version):
                    logger.info(f"Update available: v{self.current_version} → v{latest_version}")
                    return {
                        'update_available': True,
                        'version': latest_version,
                        'download_url': data.get('download_url', self.update_download_url),
                        'checksum': data.get('sha256'),
                        'critical': data.get('critical', False),
                        'release_notes': data.get('release_notes', ''),
                        'size_bytes': data.get('size_bytes', 0),
                        'release_date': data.get('release_date')
                    }
                else:
                    logger.info(f"Already on latest version: v{self.current_version}")
                    return {'update_available': False}

            elif response.status_code == 204:
                # No updates available (explicit response)
                logger.info("No updates available")
                return {'update_available': False}

            else:
                logger.warning(f"Update check failed with status {response.status_code}")
                return {'update_available': False}

        except requests.exceptions.Timeout:
            logger.warning("Update check timed out")
            return {'update_available': False}
        except requests.exceptions.ConnectionError:
            logger.warning("Update check failed: No internet connection")
            return {'update_available': False}
        except Exception as e:
            logger.error(f"Update check error: {e}")
            return {'update_available': False}

    def download_and_install_update(self, update_info, progress_callback=None):
        """
        Download and install update

        Args:
            update_info (dict): Update information from check_for_updates()
            progress_callback (callable): Optional callback(bytes_downloaded, total_bytes)

        Returns:
            bool: True if download and installation started successfully
        """
        try:
            version_str = update_info['version']
            download_url = update_info['download_url']
            expected_checksum = update_info.get('checksum')

            logger.info(f"Downloading update v{version_str} from {download_url}")

            # Create temp directory for download
            temp_dir = Path(tempfile.gettempdir()) / 'ezprint_updates'
            temp_dir.mkdir(exist_ok=True)

            installer_filename = f"EzPrintAgentSetup_v{version_str}.exe"
            installer_path = temp_dir / installer_filename

            # Download with progress
            headers = {}
            if self.api_token:
                headers['Authorization'] = f'Bearer {self.api_token}'

            response = requests.get(
                download_url,
                headers=headers,
                stream=True,
                timeout=300  # 5 minutes timeout
            )
            response.raise_for_status()

            total_size = int(response.headers.get('content-length', 0))
            downloaded = 0

            logger.info(f"Downloading {total_size / 1024 / 1024:.2f} MB...")

            with open(installer_path, 'wb') as f:
                for chunk in response.iter_content(chunk_size=8192):
                    if chunk:
                        f.write(chunk)
                        downloaded += len(chunk)

                        # Call progress callback
                        if progress_callback:
                            try:
                                progress_callback(downloaded, total_size)
                            except Exception:
                                pass

            logger.info(f"Download complete: {installer_path}")

            # Verify checksum if provided
            if expected_checksum:
                logger.info("Verifying file integrity...")
                if not self._verify_checksum(installer_path, expected_checksum):
                    logger.error("Checksum verification failed! Update aborted.")
                    os.remove(installer_path)
                    return False
                logger.info("Checksum verified successfully")

            # Launch installer
            logger.info("Launching installer...")
            self._launch_installer(installer_path)

            return True

        except requests.exceptions.HTTPError as e:
            logger.error(f"Download failed: HTTP {e.response.status_code}")
            return False
        except requests.exceptions.Timeout:
            logger.error("Download timed out")
            return False
        except Exception as e:
            logger.error(f"Update installation failed: {e}")
            return False

    def _verify_checksum(self, file_path, expected_checksum):
        """
        Verify file SHA256 checksum

        Args:
            file_path (Path): Path to file
            expected_checksum (str): Expected SHA256 hex digest

        Returns:
            bool: True if checksum matches
        """
        try:
            sha256_hash = hashlib.sha256()
            with open(file_path, "rb") as f:
                for byte_block in iter(lambda: f.read(4096), b""):
                    sha256_hash.update(byte_block)

            actual_checksum = sha256_hash.hexdigest()
            matches = actual_checksum.lower() == expected_checksum.lower()

            if not matches:
                logger.error(f"Checksum mismatch!")
                logger.error(f"  Expected: {expected_checksum}")
                logger.error(f"  Actual:   {actual_checksum}")

            return matches

        except Exception as e:
            logger.error(f"Checksum verification error: {e}")
            return False

    def _launch_installer(self, installer_path):
        """
        Launch installer and exit current app

        Args:
            installer_path (Path): Path to installer executable
        """
        try:
            # Windows: Run installer with silent install flag
            # /SILENT = show progress
            # /VERYSILENT = completely silent
            # /CLOSEAPPLICATIONS = close running instances
            # /RESTARTAPPLICATIONS = restart after install

            if sys.platform == 'win32':
                # Launch installer in detached process
                subprocess.Popen(
                    [str(installer_path), '/SILENT', '/CLOSEAPPLICATIONS'],
                    creationflags=subprocess.DETACHED_PROCESS | subprocess.CREATE_NEW_PROCESS_GROUP,
                    close_fds=True
                )

                logger.info("Installer launched. Exiting application...")

                # Give installer time to start
                import time
                time.sleep(2)

                # Exit current application to allow installer to replace files
                sys.exit(0)

            else:
                logger.warning(f"Auto-update not implemented for platform: {sys.platform}")
                # For non-Windows platforms, just open the installer
                subprocess.Popen([str(installer_path)])

        except Exception as e:
            logger.error(f"Failed to launch installer: {e}")
            raise


def check_for_updates_async(shop_id=None, callback=None):
    """
    Check for updates in background (non-blocking)

    Args:
        shop_id (str): Shop identifier
        callback (callable): Called with update_info when check completes
    """
    import threading

    def _check():
        try:
            updater = AutoUpdater(shop_id=shop_id)
            update_info = updater.check_for_updates()

            if callback and update_info.get('update_available'):
                callback(update_info)
        except Exception as e:
            logger.error(f"Background update check failed: {e}")

    thread = threading.Thread(target=_check, daemon=True)
    thread.start()


def download_and_install_async(update_info, progress_callback=None, complete_callback=None):
    """
    Download and install update in background

    Args:
        update_info (dict): Update information
        progress_callback (callable): Progress callback(bytes_downloaded, total_bytes)
        complete_callback (callable): Called when download completes (success: bool)
    """
    import threading

    def _download():
        try:
            updater = AutoUpdater()
            success = updater.download_and_install_update(update_info, progress_callback)

            if complete_callback:
                complete_callback(success)
        except Exception as e:
            logger.error(f"Background update download failed: {e}")
            if complete_callback:
                complete_callback(False)

    thread = threading.Thread(target=_download, daemon=True)
    thread.start()


# Convenience function for quick update check
def quick_update_check(shop_id=None):
    """
    Perform quick update check and return result

    Args:
        shop_id (str): Shop identifier

    Returns:
        dict: Update information or None
    """
    if not cfg.AUTO_UPDATE_ENABLED:
        logger.debug("Auto-update disabled in configuration")
        return {'update_available': False}

    try:
        updater = AutoUpdater(shop_id=shop_id)
        return updater.check_for_updates()
    except Exception as e:
        logger.error(f"Quick update check failed: {e}")
        return {'update_available': False}
