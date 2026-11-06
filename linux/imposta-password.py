"""Imposta (o cambia) la password di SentinelAI sul server, senza aprire l'app.
Uso:  sudo -u sentinelai python3 imposta-password.py [/var/lib/SentinelAI]   poi  systemctl restart sentinelai
La password si chiede a schermo (non resta nella cronologia). Dopo si può cambiare anche dall'app."""
import getpass
import hashlib
import os
import secrets
import sys
from pathlib import Path

SCRYPT = {"n": 2 ** 14, "r": 8, "p": 1, "dklen": 32}     # uguale a backend/auth_local.py

data = Path(sys.argv[1] if len(sys.argv) > 1 else "/var/lib/SentinelAI")
da_env = os.environ.pop("SENTINEL_NUOVA_PASSWORD", "")
pw = da_env or getpass.getpass("Nuova password (almeno 6 caratteri): ")
if len(pw.strip()) < 6:
    sys.exit("Troppo corta: almeno 6 caratteri.")
if not da_env and sys.stdin.isatty() and getpass.getpass("Ripetila: ") != pw:
    sys.exit("Le due password non coincidono.")
salt = secrets.token_bytes(16)
h = f"scrypt${salt.hex()}${hashlib.scrypt(pw.encode(), salt=salt, **SCRYPT).hex()}"
data.mkdir(parents=True, exist_ok=True)
tmp = data / ".app_password.tmp"
old = os.umask(0o077)
try:
    tmp.write_text(h)
    os.replace(tmp, data / ".app_password")
finally:
    os.umask(old)
print("Password salvata. Riavvia il servizio: systemctl restart sentinelai")
