#!/bin/sh
# SentinelAI (CT Proxmox): installa l'ultima versione pubblicata, su richiesta dal pulsante "Aggiorna" dell'app.
# 1.0.12 (richiesta di Roberto). Lo avvia come root sentinelai-aggiorna.service, quando il servizio SentinelAI
# (utente sentinelai, che non può scrivere in /opt) crea /var/lib/SentinelAI/aggiornamento/richiesta.
#
# - Da quella richiesta non si legge niente: la versione si chiede a GitHub qui.
# - Si installa SOLO una versione più nuova, con il certificato rilascio.json firmato e verificato con la chiave
#   pubblica della versione GIÀ installata, e solo il pacchetto con l'impronta scritta nel certificato.
# - Dopo il riavvio SentinelAI deve rispondere e restare su con lo stesso processo; se no si rimette la versione
#   di prima (codice, dipendenze e unità systemd) e si riavvia quella.
# - Lo stato per l'app va in /run/sentinelai-aggiorna/stato.json (mai scritto nelle cartelle dell'utente sentinelai).
set -u
DIR=${DIR:-/opt/sentinelai}
DATI=${DATI:-/var/lib/SentinelAI}
STATO_DIR=${STATO_DIR:-/run/sentinelai-aggiorna}
UNITA=${UNITA:-/etc/systemd/system}
API=${API:-https://api.github.com/repos/telard-pixel/sentinelai-rilasci/releases/latest}
SCARICA=${SCARICA:-https://github.com/telard-pixel/sentinelai-rilasci/releases/download}
ALLEGATI=${ALLEGATI:-https://api.github.com/repos/telard-pixel/sentinelai-rilasci/releases/assets}
SALUTE=${SALUTE:-http://127.0.0.1:8765/api/health}
ATTESA=${ATTESA:-120}
SYSTEMCTL=${SYSTEMCTL:-systemctl}
LOG=${LOG:-/var/log/sentinelai-aggiorna.log}
PY="$DIR/venv/bin/python"
PARTI="backend desktop frontend linux VERSIONE"
UNITA_NOSTRE="sentinelai.service sentinelai-aggiorna.service sentinelai-aggiorna.path"

# la cartella è dell'utente sentinelai: se fosse un collegamento simbolico non la si attraversa (agente 112)
[ -L "$DATI/aggiornamento" ] || rm -f "$DATI/aggiornamento/richiesta"
mkdir -p "$STATO_DIR" && chmod 755 "$STATO_DIR"
exec >>"$LOG" 2>&1
TAG=""
ORA=$(cat "$DIR/VERSIONE" 2>/dev/null || echo "?")

stato() {   # fase, messaggio (testi fissi di questo script, senza virgolette)
    printf '{"fase":"%s","messaggio":"%s","tag":"%s","ora":"%s"}\n' "$1" "$2" "$TAG" "$(date -Iseconds)" > "$STATO_DIR/stato.tmp"
    chmod 644 "$STATO_DIR/stato.tmp" && mv -f "$STATO_DIR/stato.tmp" "$STATO_DIR/stato.json"
    echo "$(date '+%F %T') [$1] $2 ${TAG:-}"
}
fine() { stato errore "$1"; exit 1; }

stato controllo "Cerco la versione nuova"
T=$(mktemp -d /var/tmp/sentinelai-aggiorna.XXXXXX) || fine "Cartella temporanea non creata"
trap 'rm -rf "$T"' EXIT
curl -fsSL --max-time 30 -H "Accept: application/vnd.github+json" -o "$T/ultima.json" "$API" || fine "GitHub non raggiungibile"
TAG=$("$PY" -I - "$T/ultima.json" <<'EOF'
import json, re, sys
t = json.load(open(sys.argv[1], encoding="utf-8")).get("tag_name", "")
print(t if re.fullmatch(r"v\d+\.\d+\.\d+", t) else "")
EOF
)
[ -n "$TAG" ] || fine "Nessuna versione pubblicata"
if ! "$PY" -I -c 'import re,sys; n=lambda v: tuple(int(x) for x in re.match(r"v?(\d+)\.(\d+)\.(\d+)", v).groups()) if re.match(r"v?\d+\.\d+\.\d+", v) else (0,); sys.exit(0 if n(sys.argv[1]) > n(sys.argv[2]) else 1)' "$TAG" "$ORA"; then
    stato fatto "Già all'ultima versione"
    exit 0
fi

# 1.0.13: prima dall'API (allegato per numero), poi dall'indirizzo github.com/.../releases/download: l'8/11/2026
# quest'ultimo dava 504 per ore mentre l'API funzionava. Chi lo manda non conta: vale solo la firma.
scarica() {   # nome, destinazione, secondi massimi
    id=$("$PY" -I - "$T/ultima.json" "$1" <<'EOF2'
import json, sys
for a in json.load(open(sys.argv[1], encoding="utf-8")).get("assets", []):
    if a.get("name") == sys.argv[2] and str(a.get("id", "")).isdigit():
        print(a["id"]); break
EOF2
)
    if [ -n "$id" ] && curl -fsSL --retry 2 --max-time "$3" -H "Accept: application/octet-stream" -o "$2" "$ALLEGATI/$id"; then return 0; fi
    curl -fsSL --retry 2 --max-time "$3" -o "$2" "$SCARICA/$TAG/$1"
}

stato scarico "Scarico e controllo la firma"
for f in rilascio.json rilascio.json.sig; do
    scarica "$f" "$T/$f" 60 || fine "Versione non scaricabile da GitHub (o non ancora firmata)"
done
openssl dgst -sha256 -sigopt rsa_padding_mode:pss -sigopt rsa_pss_saltlen:auto -verify "$DIR/backend/chiave_pubblica.pem" \
    -signature "$T/rilascio.json.sig" "$T/rilascio.json" >/dev/null 2>&1 || fine "FIRMA NON VALIDA: non installata"
INFO=$("$PY" -I - "$T/rilascio.json" "$TAG" <<'EOF'
import json, re, sys
m = json.load(open(sys.argv[1], encoding="utf-8"))
tag = sys.argv[2]
l = m.get("linux") or {}
nome, sha = str(l.get("nome", "")), str(l.get("sha256", ""))
ok = (m.get("progetto") == "sentinelai" and m.get("tag") == tag and m.get("versione") == tag[1:]
      and re.fullmatch(r"SentinelAI-linux-\d+\.\d+\.\d+\.tar\.gz", nome) and re.fullmatch(r"[0-9a-f]{64}", sha))
print(f"{nome} {sha}" if ok else "")
EOF
)
[ -n "$INFO" ] || fine "Il certificato non corrisponde alla versione"
NOME=${INFO% *}
SHA=${INFO#* }
scarica "$NOME" "$T/$NOME" 600 || fine "Pacchetto non scaricato"
[ "$(sha256sum "$T/$NOME" | cut -d' ' -f1)" = "$SHA" ] || fine "Il pacchetto non corrisponde al certificato"

stato installo "Installo la versione nuova"
mkdir "$T/nuova"
(umask 022; tar -xzf "$T/$NOME" -C "$T/nuova" --no-same-owner --no-same-permissions) || fine "Pacchetto illeggibile"
[ "$(cat "$T/nuova/VERSIONE" 2>/dev/null)" = "${TAG#v}" ] && [ -f "$T/nuova/backend/server.py" ] \
    && [ -f "$T/nuova/linux/sentinel_server.py" ] && [ -f "$T/nuova/frontend/build/index.html" ] \
    && [ -f "$T/nuova/backend/chiave_pubblica.pem" ] && [ -f "$T/nuova/desktop/sentinel_desktop.py" ] \
    || fine "Pacchetto incompleto"
"$PY" -I -m compileall -q "$T/nuova/backend" "$T/nuova/linux" "$T/nuova/desktop" >/dev/null || fine "Pacchetto con errori"

PRIMA="$DIR.prima"
rm -rf "$PRIMA" && mkdir -p "$PRIMA/unita" || fine "Copia di riserva non creata"
for u in $UNITA_NOSTRE; do [ -f "$UNITA/$u" ] && cp -p "$UNITA/$u" "$PRIMA/unita/"; done
torna_indietro() {
    # solo le parti già spostate in .prima: le altre sono ancora quelle vecchie e restano dove sono (agente 112)
    for p in $PARTI; do
        if [ -e "$PRIMA/$p" ]; then rm -rf "$DIR/$p"; mv "$PRIMA/$p" "$DIR/$p"; fi
    done
    for u in $UNITA_NOSTRE; do
        if [ -f "$PRIMA/unita/$u" ]; then cp -p "$PRIMA/unita/$u" "$UNITA/$u"
        else rm -f "$UNITA/$u"; fi      # unità aggiunte dalla versione nuova: via anche loro (agente 112)
    done
    $SYSTEMCTL daemon-reload
    if [ "${DIPENDENZE:-0}" = 1 ]; then "$PY" -m pip install -q -r "$DIR/linux/requirements-linux.txt"; fi
    $SYSTEMCTL restart sentinelai
}

for p in $PARTI; do
    if [ -e "$DIR/$p" ]; then mv "$DIR/$p" "$PRIMA/$p" || { torna_indietro; fine "Installazione non riuscita: resta la $ORA"; }; fi
    mv "$T/nuova/$p" "$DIR/$p" || { torna_indietro; fine "Installazione non riuscita: resta la $ORA"; }
done

DIPENDENZE=0
if ! cmp -s "$PRIMA/linux/requirements-linux.txt" "$DIR/linux/requirements-linux.txt"; then
    DIPENDENZE=1
    stato installo "Installo le librerie nuove"
    "$PY" -m pip install -q -r "$DIR/linux/requirements-linux.txt" || { torna_indietro; fine "Librerie non installate: resta la $ORA"; }
fi
# Unità systemd: quella del servizio con le difese e le aggiunte locali (.d) restano; si copiano solo se cambiano.
for u in $UNITA_NOSTRE; do
    if [ -f "$DIR/linux/$u" ] && ! cmp -s "$DIR/linux/$u" "$UNITA/$u"; then cp "$DIR/linux/$u" "$UNITA/$u" && chmod 644 "$UNITA/$u"; fi
done
$SYSTEMCTL daemon-reload

stato riavvio "Riavvio SentinelAI"
$SYSTEMCTL restart sentinelai
sleep 5
PID1=$($SYSTEMCTL show -p MainPID --value sentinelai)
OK=0
i=0
while [ $i -lt "$ATTESA" ]; do
    if curl -fs --max-time 3 "$SALUTE" | grep -q '"status":"ok"'; then OK=1; break; fi
    sleep 1; i=$((i + 1))
done
sleep 10
PID2=$($SYSTEMCTL show -p MainPID --value sentinelai)
if [ "$OK" != 1 ] || ! $SYSTEMCTL is-active -q sentinelai || [ "${PID1:-0}" = 0 ] || [ "$PID1" != "$PID2" ]; then
    torna_indietro
    fine "La versione nuova non partiva: rimessa la $ORA"
fi
stato fatto "Installata la versione ${TAG#v} (prima $ORA)"
