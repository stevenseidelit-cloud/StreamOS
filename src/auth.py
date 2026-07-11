import base64
import hashlib
import os
import platform
import subprocess
import uuid
from cryptography.fernet import Fernet, InvalidToken
from src.paths import TOKEN_PATH, USER_DATA_DIR
from src.logger import logger

MACHINE_ID_PATH = os.path.join(USER_DATA_DIR, "machine_id.txt")


def _get_stable_machine_id():
    """
    Liefert eine dauerhaft stabile ID fuer diesen PC/diese Installation.
    WMIC ist optional. Wenn WMIC fehlschlaegt, wird einmalig eine lokale ID erzeugt
    und in %APPDATA%\\StreamOS\\machine_id.txt gespeichert.
    """
    try:
        if platform.system() == "Windows":
            output = subprocess.check_output(
                "wmic csproduct get uuid",
                shell=True,
                stderr=subprocess.DEVNULL,
                timeout=5,
            ).decode("utf-8", errors="ignore")

            lines = [line.strip() for line in output.splitlines() if line.strip()]
            # Normal: erste Zeile = UUID, zweite Zeile = Wert
            for line in lines:
                if line.lower() != "uuid" and len(line) >= 8:
                    logger.info("AUTH: Machine-ID Quelle = WMIC UUID")
                    return line
    except Exception as e:
        logger.info(f"AUTH: WMIC nicht nutzbar, Fallback wird verwendet. Fehler: {e}")

    try:
        if os.path.exists(MACHINE_ID_PATH):
            with open(MACHINE_ID_PATH, "r", encoding="utf-8") as f:
                value = f.read().strip()
                if value:
                    logger.info("AUTH: Machine-ID Quelle = gespeicherter lokaler Fallback")
                    return value

        value = f"StreamOS-{uuid.uuid4()}"
        with open(MACHINE_ID_PATH, "w", encoding="utf-8") as f:
            f.write(value)
        logger.info("AUTH: Machine-ID Quelle = neuer lokaler Fallback")
        return value
    except Exception as e:
        # Letzter Notfall-Fallback, damit Fernet trotzdem nie ungueltig wird.
        logger.error(f"AUTH: Lokaler Fallback konnte nicht gespeichert werden: {e}")
        return "StreamOS-Emergency-Fallback-Key"


def _build_fernet_key(raw_id):
    """
    Baut garantiert einen Fernet-kompatiblen Key.
    Fernet erwartet urlsafe-base64, das nach dem Decodieren exakt 32 Bytes ergibt.
    SHA256 liefert immer exakt 32 Bytes; base64.urlsafe_b64encode macht daraus 44 Bytes.
    """
    if not isinstance(raw_id, str):
        raw_id = str(raw_id)

    digest = hashlib.sha256(raw_id.encode("utf-8")).digest()
    key = base64.urlsafe_b64encode(digest)

    # Harte Selbstpruefung vor Fernet(...)
    decoded = base64.urlsafe_b64decode(key)
    logger.info("--- DEBUG FERNET KEY START ---")
    logger.info(f"AUTH.PY PATH: {__file__}")
    logger.info(f"TOKEN FILE PATH: {TOKEN_PATH}")
    logger.info(f"KEY TYPE: {type(key)}")
    logger.info(f"KEY LENGTH: {len(key)}")
    logger.info(f"KEY DECODED LENGTH: {len(decoded)}")
    logger.info(f"KEY PREVIEW: {key[:8]!r}...{key[-8:]!r}")
    logger.info("--- DEBUG FERNET KEY END ---")

    if len(decoded) != 32:
        raise ValueError(f"Interner Fehler: Fernet-Key decodiert nicht auf 32 Bytes, sondern {len(decoded)} Bytes")

    return key


def get_machine_key():
    raw_id = _get_stable_machine_id()
    key = _build_fernet_key(raw_id)
    return Fernet(key)


def save_token(token):
    try:
        if not token or not str(token).strip():
            logger.error("AUTH: Kein Token uebergeben. Speichern abgebrochen.")
            return False

        cipher = get_machine_key()
        encrypted = cipher.encrypt(str(token).strip().encode("utf-8"))
        with open(TOKEN_PATH, "wb") as f:
            f.write(encrypted)
        logger.info("Auth-Token erfolgreich verschluesselt gespeichert.")
        return True
    except Exception as e:
        logger.exception(f"Fehler beim Speichern des Tokens: {e}")
        return False


def load_token():
    if not os.path.exists(TOKEN_PATH):
        return None

    try:
        cipher = get_machine_key()
        with open(TOKEN_PATH, "rb") as f:
            encrypted = f.read()
        if not encrypted:
            logger.warning("AUTH: Token-Datei ist leer. Datei wird ignoriert.")
            return None
        return cipher.decrypt(encrypted).decode("utf-8")
    except InvalidToken:
        # Alte/kaputte Token-Datei nicht endlos neu versuchen.
        invalid_path = TOKEN_PATH + ".invalid"
        try:
            if os.path.exists(invalid_path):
                os.remove(invalid_path)
            os.rename(TOKEN_PATH, invalid_path)
            logger.error(f"AUTH: Token-Datei konnte nicht entschluesselt werden und wurde umbenannt: {invalid_path}")
        except Exception as rename_error:
            logger.error(f"AUTH: Token-Datei ist ungueltig, konnte aber nicht umbenannt werden: {rename_error}")
        return None
    except Exception as e:
        logger.exception(f"Fehler beim Laden des Tokens: {e}")
        return None
