#!/bin/bash
# Pubblica una versione GIÀ approvata (agente di prova) per l'aggiornamento dall'app (1.0.12).
# Prende Setup e pacchetto Linux dalla release del repository privato, scrive il certificato rilascio.json
# (versione, commit, impronte), lo firma con la chiave privata e mette tutto nel repository PUBBLICO
# telard-pixel/sentinelai-rilasci (solo installer, niente codice).
#   bash tools/pubblica-rilascio.sh v1.0.12      (chiave: /root/code/sentinelai-chiave/firma.pem)
set -euo pipefail
TAG=${1:?serve il tag, es. v1.0.12}
[[ "$TAG" =~ ^v[0-9]+\.[0-9]+\.[0-9]+$ ]] || { echo "tag non valido: $TAG"; exit 1; }
V=${TAG#v}
CHIAVE=${CHIAVE:-/root/code/sentinelai-chiave/firma.pem}
PRIVATO=telard-pixel/sentinelai
PUBBLICO=telard-pixel/sentinelai-rilasci
QUI=$(cd "$(dirname "$0")/.." && pwd)
TMP=$(mktemp -d); trap 'rm -rf "$TMP"' EXIT

SETUP="SentinelAI-Setup-$V.exe"
LINUX="SentinelAI-linux-$V.tar.gz"
gh release download "$TAG" -R "$PRIVATO" -p "$SETUP" -p "$LINUX" -D "$TMP"
# il pacchetto deve dire la stessa versione
[ "$(tar -xzOf "$TMP/$LINUX" VERSIONE)" = "$V" ] || { echo "il pacchetto Linux non è la $V"; exit 1; }
# e deve avere la stessa chiave pubblica di questo repository (sennò il prossimo aggiornamento non si verifica)
tar -xzOf "$TMP/$LINUX" backend/chiave_pubblica.pem | cmp -s - "$QUI/backend/chiave_pubblica.pem" \
    || { echo "chiave pubblica nel pacchetto diversa da backend/chiave_pubblica.pem"; exit 1; }

TIPO=$(gh api "repos/$PRIVATO/git/ref/tags/$TAG" -q .object.type)
COMMIT=$(gh api "repos/$PRIVATO/git/ref/tags/$TAG" -q .object.sha)
if [ "$TIPO" = tag ]; then COMMIT=$(gh api "repos/$PRIVATO/git/tags/$COMMIT" -q .object.sha); fi
python3 - "$TMP" "$TAG" "$COMMIT" "$SETUP" "$LINUX" <<'EOF'
import hashlib, json, os, sys
d, tag, commit, setup, linux = sys.argv[1:6]
sha = lambda n: hashlib.sha256(open(os.path.join(d, n), "rb").read()).hexdigest()
m = {"progetto": "sentinelai", "tag": tag, "versione": tag[1:], "commit": commit,
     "windows": {"nome": setup, "sha256": sha(setup)}, "linux": {"nome": linux, "sha256": sha(linux)}}
json.dump(m, open(os.path.join(d, "rilascio.json"), "w", encoding="utf-8"), sort_keys=True, indent=1)
EOF
openssl dgst -sha256 -sigopt rsa_padding_mode:pss -sigopt rsa_pss_saltlen:-1 -sign "$CHIAVE" \
    -out "$TMP/rilascio.json.sig" "$TMP/rilascio.json"
# la stessa verifica che fanno il CT (openssl) e il PC (Python)
openssl dgst -sha256 -sigopt rsa_padding_mode:pss -sigopt rsa_pss_saltlen:auto -verify "$QUI/backend/chiave_pubblica.pem" \
    -signature "$TMP/rilascio.json.sig" "$TMP/rilascio.json"
cat "$TMP/rilascio.json"

NOTE=${NOTE:-"SentinelAI $V. Si installa dall'app: Impostazioni → Aggiornamenti → Aggiorna."}
gh release create "$TAG" -R "$PUBBLICO" --title "SentinelAI $V" --notes "$NOTE" \
    "$TMP/$SETUP" "$TMP/$LINUX" "$TMP/rilascio.json" "$TMP/rilascio.json.sig"
echo "Pubblicata $TAG su $PUBBLICO (commit $COMMIT)"
