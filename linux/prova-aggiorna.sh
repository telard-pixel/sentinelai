#!/bin/sh
# Prova di linux/aggiorna.sh in una cartella finta (CI e a mano): niente rete, niente systemd, chiave di prova.
#   sh linux/prova-aggiorna.sh
# Casi: versione buona installata; firma falsa rifiutata; versione che non parte rimessa indietro;
# versione non più nuova ignorata; pacchetto diverso dal certificato rifiutato.
set -eu
QUI=$(cd "$(dirname "$0")/.." && pwd)
W=$(mktemp -d)
trap 'rm -rf "$W"' EXIT
FALLITI=0

openssl genpkey -algorithm RSA -pkeyopt rsa_keygen_bits:2048 -out "$W/k.pem" 2>/dev/null
openssl pkey -in "$W/k.pem" -pubout -out "$W/pub.pem" 2>/dev/null
openssl genpkey -algorithm RSA -pkeyopt rsa_keygen_bits:2048 -out "$W/falsa.pem" 2>/dev/null

# finto systemctl: registra i comandi; "show" dà sempre lo stesso processo
cat > "$W/systemctl" <<'EOF'
#!/bin/sh
echo "$*" >> "$W_LOG"
case "$1" in show) echo 4242 ;; is-active) exit 0 ;; esac
exit 0
EOF
chmod +x "$W/systemctl"

installa_vecchia() {   # /opt finto con la versione 1.0.11
    rm -rf "$W/opt" "$W/opt.prima" "$W/unita" "$W/run" "$W/dati"
    mkdir -p "$W/opt/backend" "$W/opt/desktop" "$W/opt/frontend/build" "$W/opt/linux" "$W/opt/venv/bin" "$W/unita" "$W/dati/aggiornamento"
    echo "1.0.11" > "$W/opt/VERSIONE"
    echo "vecchio" > "$W/opt/backend/server.py"
    cp "$W/pub.pem" "$W/opt/backend/chiave_pubblica.pem"
    echo "vecchio" > "$W/opt/linux/sentinel_server.py"
    cp "$QUI/linux/requirements-linux.txt" "$W/opt/linux/"
    echo "<html>vecchio" > "$W/opt/frontend/build/index.html"
    ln -s "$(command -v python3)" "$W/opt/venv/bin/python"
    echo "unita vecchia" > "$W/unita/sentinelai.service"
    echo "richiesta" > "$W/dati/aggiornamento/richiesta"
    : > "$W/systemctl.log"
}

pubblica() {   # tag, chiave per firmare, [contenuto server.py], [sha256 da scrivere al posto di quello vero]
    tag=$1; v=${tag#v}
    rm -rf "$W/rel" "$W/pk"; mkdir -p "$W/rel/$tag" "$W/pk/backend" "$W/pk/desktop" "$W/pk/frontend/build" "$W/pk/linux"
    echo "$v" > "$W/pk/VERSIONE"
    echo "${3:-print('nuovo')}" > "$W/pk/backend/server.py"
    cp "$W/pub.pem" "$W/pk/backend/chiave_pubblica.pem"
    echo "print('nuovo')" > "$W/pk/linux/sentinel_server.py"
    echo "print('nuovo')" > "$W/pk/desktop/sentinel_desktop.py"
    cp "$QUI/linux/requirements-linux.txt" "$QUI/linux/sentinelai.service" "$QUI/linux/sentinelai-aggiorna.path" "$W/pk/linux/"
    [ "${SENZA_DESKTOP:-0}" = 1 ] && rm -rf "$W/pk/desktop" && mkdir "$W/pk/desktop"
    echo "<html>nuovo" > "$W/pk/frontend/build/index.html"
    nome="SentinelAI-linux-$v.tar.gz"
    tar -czf "$W/rel/$tag/$nome" -C "$W/pk" VERSIONE backend desktop frontend linux
    sha=${4:-$(sha256sum "$W/rel/$tag/$nome" | cut -d' ' -f1)}
    printf '{"progetto":"sentinelai","tag":"%s","versione":"%s","linux":{"nome":"%s","sha256":"%s"}}' "$tag" "$v" "$nome" "$sha" > "$W/rel/$tag/rilascio.json"
    openssl dgst -sha256 -sigopt rsa_padding_mode:pss -sigopt rsa_pss_saltlen:-1 -sign "$2" \
        -out "$W/rel/$tag/rilascio.json.sig" "$W/rel/$tag/rilascio.json"
    printf '{"tag_name":"%s"}' "$tag" > "$W/rel/ultima.json"
}

esegui() {   # [salute: ok | ko]
    if [ "${1:-ok}" = ok ]; then echo '{"status":"ok"}' > "$W/salute.json"; else echo '{}' > "$W/salute.json"; fi
    W_LOG="$W/systemctl.log" DIR="$W/opt" DATI="$W/dati" STATO_DIR="$W/run" UNITA="$W/unita" LOG="$W/agg.log" \
        API="file://$W/rel/ultima.json" SCARICA="file://$W/rel" SALUTE="file://$W/salute.json" ATTESA=3 \
        SYSTEMCTL="$W/systemctl" sh "$QUI/linux/aggiorna.sh" || true
}

controlla() {   # descrizione, condizione
    if eval "$2"; then echo "ok   $1"; else echo "NO   $1"; FALLITI=$((FALLITI + 1)); cat "$W/agg.log" 2>/dev/null | tail -5; fi
}

export W_LOG="$W/systemctl.log"

echo "== 1. versione buona"
installa_vecchia; pubblica v1.0.12 "$W/k.pem"; esegui ok
controlla "VERSIONE nuova" '[ "$(cat $W/opt/VERSIONE)" = 1.0.12 ]'
controlla "codice nuovo" 'grep -q nuovo $W/opt/backend/server.py'
controlla "venv e modelli non toccati" '[ -L $W/opt/venv/bin/python ]'
controlla "stato fatto" 'grep -q "\"fase\":\"fatto\"" $W/run/stato.json'
controlla "richiesta cancellata" '[ ! -e $W/dati/aggiornamento/richiesta ]'
controlla "riavvio fatto" 'grep -q "restart sentinelai" $W/systemctl.log'
controlla "unità aggiornata" 'cmp -s $QUI/linux/sentinelai.service $W/unita/sentinelai.service'
controlla "copia di riserva" '[ "$(cat $W/opt.prima/VERSIONE)" = 1.0.11 ]'
controlla "stato leggibile da tutti" '[ "$(stat -c %a $W/run/stato.json)" = 644 ]'
controlla "permessi file 644" '[ "$(stat -c %a $W/opt/backend/server.py)" = 644 ]'

echo "== 2. firma falsa"
installa_vecchia; pubblica v1.0.12 "$W/falsa.pem"; esegui ok
controlla "resta la vecchia" '[ "$(cat $W/opt/VERSIONE)" = 1.0.11 ] && grep -q vecchio $W/opt/backend/server.py'
controlla "stato errore firma" 'grep -q "FIRMA NON VALIDA" $W/run/stato.json'
controlla "nessun riavvio" '! grep -q restart $W/systemctl.log'

echo "== 3. la nuova non parte"
installa_vecchia; pubblica v1.0.12 "$W/k.pem"; esegui ko
controlla "rimessa la vecchia" '[ "$(cat $W/opt/VERSIONE)" = 1.0.11 ] && grep -q vecchio $W/opt/backend/server.py && grep -q vecchio $W/opt/frontend/build/index.html'
controlla "unità vecchia rimessa" 'grep -q "unita vecchia" $W/unita/sentinelai.service'
controlla "unità aggiunta tolta" '[ ! -e $W/unita/sentinelai-aggiorna.path ]'
controlla "stato errore con ritorno" 'grep -q "rimessa la 1.0.11" $W/run/stato.json'
controlla "riavviata la vecchia (2 restart)" '[ "$(grep -c "restart sentinelai" $W/systemctl.log)" = 2 ]'

echo "== 4. versione non più nuova"
installa_vecchia; pubblica v1.0.11 "$W/k.pem"; esegui ok
controlla "niente da fare" 'grep -q "Già all" $W/run/stato.json && ! grep -q restart $W/systemctl.log'

echo "== 5. pacchetto diverso dal certificato"
installa_vecchia; pubblica v1.0.12 "$W/k.pem" "" "0000000000000000000000000000000000000000000000000000000000000000"; esegui ok
controlla "rifiutato" 'grep -q "non corrisponde al certificato" $W/run/stato.json && [ "$(cat $W/opt/VERSIONE)" = 1.0.11 ]'

echo "== 6. codice con errori di sintassi"
installa_vecchia; pubblica v1.0.12 "$W/k.pem" "def ("; esegui ok
controlla "rifiutato prima di toccare" 'grep -q "Pacchetto con errori" $W/run/stato.json && grep -q vecchio $W/opt/backend/server.py'

echo "== 7. pacchetto senza desktop/"
installa_vecchia; SENZA_DESKTOP=1 pubblica v1.0.12 "$W/k.pem"; esegui ok
controlla "rifiutato" 'grep -q "Pacchetto incompleto" $W/run/stato.json && [ "$(cat $W/opt/VERSIONE)" = 1.0.11 ]'

echo "== 8. cartella della richiesta come collegamento simbolico"
installa_vecchia; mkdir -p "$W/vittima"; echo x > "$W/vittima/richiesta"
rm -rf "$W/dati/aggiornamento"; ln -s "$W/vittima" "$W/dati/aggiornamento"; pubblica v1.0.11 "$W/k.pem"; esegui ok
controlla "il collegamento non si attraversa" '[ -e $W/vittima/richiesta ]'

[ "$FALLITI" = 0 ] && echo "TUTTE LE PROVE PASSATE" || { echo "$FALLITI PROVE FALLITE"; exit 1; }
