# SentinelAI · Vision Guard

Monitoraggio telecamere con AI locale (YOLO11): persone, veicoli, animali e oggetti, la loro direzione,
linea virtuale con conteggio entrate/uscite, zone con allarme di ingresso e di sosta, clip video degli allarmi,
mappa di calore, statistiche, esportazione CSV/Excel e allarmi su Telegram. App installabile (PWA) su PC e telefono.

Ricostruito il 05/11/2026 dall'anteprima Emergent, senza Emergent:
- **frontend**: i file originali, recuperati dalla mappa del sorgente dell'anteprima (stile Tailwind già compilato in `src/index.css`);
- **backend**: `detection.py`, `clips.py`, `telegram_bot.py` originali; `models.py`, `session.py`, `server.py` riscritti
  seguendo i pezzi originali e quello che il frontend si aspetta;
- **login**: password unica (`auth_local.py`) al posto di Clerk. I file Clerk originali sono in
  `backend/_riferimento/clerk_originale/` e `frontend/_riferimento_clerk/`.

## Avvio (Docker)

```bash
cp backend/.env.example backend/.env
nano backend/.env          # metti APP_PASSWORD e, se vuoi Telegram, TELEGRAM_BOT_TOKEN
docker compose up -d --build
```

Poi apri `http://<indirizzo-del-server>:8080`. La prima compilazione scarica PyTorch (CPU) e il modello YOLO11s:
ci vogliono alcuni minuti. I dati (MongoDB e chiave dei login) stanno in `./dati/`.

## Installarla come app

Il browser offre "Installa app" solo se la pagina è in **HTTPS** (o su `localhost`).
Con Tailscale sul server basta:

```bash
tailscale serve --bg 8080
```

e aprire `https://<nome-del-server>.<tailnet>.ts.net`: compare il pulsante **Installa app** in alto
(o dal menu del browser → *Installa SentinelAI* / su iPhone *Condividi → Aggiungi alla schermata Home*).

## Telecamere

- **NVR**: Hikvision/HiLook e Dahua/Imou hanno già il percorso RTSP giusto; basta IP, utente, password e canale.
  Il flusso secondario (sub) è consigliato: meno carico, il riconoscimento lavora comunque a 640 pixel.
  La password resta sul server e non viene mai mostrata.
- **RTSP / IP**: indirizzo completo, es. `rtsp://utente:password@192.168.1.20:554/stream1`.
- **Webcam / File / Demo**: il video lo legge il browser e manda i fotogrammi al server.

## Telegram

1. Crea un bot con @BotFather e metti il token in `backend/.env` (`TELEGRAM_BOT_TOKEN=`), poi `docker compose up -d`.
2. Nell'app: **Allarmi → Allarmi su Telegram**: apri il bot, premi *Avvia*, poi *Collega chat* e *Salva regole*.

## Note

- Il video demo (`frontend/public/demo.mp4`) è il campione pubblico *person-bicycle-car-detection* di Intel
  (github.com/intel-iot-devkit/sample-videos, licenza CC-BY 4.0).
- Il riconoscimento gira sul processore (CPU). Con molte telecamere insieme conviene il flusso secondario.
- Prova automatica fatta il 05/11/2026: 48/48 controlli del backend (login, telecamere, linea, zone, sosta, clip MP4,
  mappa di calore, statistiche, esportazioni, Telegram) e prova nel browser (login, streaming, schede, telefono, PWA).

## Versione Windows (programma da installare)

`SentinelAI-Setup-<versione>.exe`: si installa per l'utente (niente permessi di amministratore), crea l'icona nel menu Start
(e se vuoi sul desktop) e può partire insieme a Windows. Si apre in una finestra sua (WebView2, il motore di Edge
già presente in Windows 10/11, dentro il programma; se manca si usa Edge) e resta nell'area di notifica vicino
all'orologio: *Apri SentinelAI*, *Avvia con Windows*, *Cartella dei dati*, *Esci*. La X chiude solo la finestra:
le telecamere restano controllate finché non scegli *Esci*.

Video delle clip (1.0.5): file `.mp4` nella cartella **Video\SentinelAI** dell'utente (una sottocartella per giorno),
oppure in quella scelta in *Impostazioni → Dove salvo i video* (anche disco esterno o cartella di rete; se non è
raggiungibile si usa la predefinita e compare un avviso). *Porta qui tutti i video* sposta anche quelli delle versioni
precedenti, che stavano dentro il database. Password: *Chiedi la password ogni volta che apri l'app* la richiede
a ogni apertura della finestra. CPU: l'AI gira solo quando c'è movimento o sta seguendo qualcosa (a scena ferma un
controllo ogni 3 s).

Differenze rispetto alla versione Docker, solo per essere un programma leggero:
- database in un file SQLite (`backend/docstore.py`, stessa interfaccia di MongoDB) invece del server MongoDB;
- YOLO11s in formato ONNX con OpenCV invece di PyTorch (installer molto più leggero: niente PyTorch da oltre 1 GB);
- clip H.264 con ffmpeg incluso nel programma (se mancasse, il codificatore di Windows);
- nessun login (si usa sul proprio PC). Per metterlo: `%LOCALAPPDATA%\SentinelAI\config.json` → `"password": "..."`.
  Con `"rete": true` l'app risponde anche agli altri dispositivi della rete (porta 8765).

Dati in `%LOCALAPPDATA%\SentinelAI` (database, clip, registro `sentinelai.log`). Il token Telegram si mette dall'app
(Allarmi → Allarmi su Telegram).

Costruzione: GitHub Actions (`.github/workflows/windows.yml`) compila l'app, esporta YOLO11s in ONNX, crea l'exe con
PyInstaller e l'installer con Inno Setup, **prova l'exe e l'installer** (`SentinelAI.exe --prova`) e con un tag `vX.Y.Z`
pubblica la Release.

## Temperatura e regolazione automatica (1.0.21)

- Solo sul server Linux (CT/Docker): SentinelAI legge la temperatura del processore da `/sys/class/hwmon` (coretemp/k10temp; nel CT si vede quella del Proxmox, in sola lettura). Si vede nel Monitor risorse, con grafico.
- Regolazione automatica (accesa di serie, limite 72 °C, si cambia nel Monitor risorse; `PUT /api/temperatura {auto, limite}`), SOLO sulle telecamere di prova:
  - 30 s sopra il limite: le telecamere di prova vengono analizzate un terzo delle volte;
  - altri 30 s sopra: le telecamere di prova vanno in pausa (flusso chiuso, niente decodifica);
  - 2 minuti sotto (limite − 5 °C): si torna indietro di uno scalino alla volta.
- Le telecamere vere (Garage, Sala…) non vengono MAI rallentate. Ogni cambio di scalino finisce nel registro.
- Sull'app Windows la temperatura non si legge: il riquadro dice "non disponibile" e la regolazione non fa niente.

## Ordine delle telecamere ed eventi in colonna (1.0.20)

- Le telecamere si spostano trascinandole per la maniglia ⋮⋮ a sinistra del nome, sia col mouse sia col dito. Da tastiera: Tab sulla maniglia e frecce. L'ordine si salva sul server (`PUT /api/camera-order`) e vale per tutti i dispositivi. Le telecamere nuove vanno in fondo. Spostarle non riavvia i flussi.
- Una pagina aperta da prima di una modifica fatta altrove non la cancella più: ogni telecamera ha un numero di revisione (`rev`) e un salvataggio con dati vecchi viene rifiutato (409); la pagina ricarica i dati e avvisa. Avvia/Ferma usano solo `POST /api/cameras/{id}/monitor`.
- Su schermo largo la colonna "Eventi in tempo reale" arriva fino in fondo alle telecamere e scorre dentro; su schermo stretto resta alta al massimo 420 px.

## Monitor risorse (1.0.19)

Icona "attività" nella barra in alto: finestra "Risorse in tempo reale", aggiornata ogni 2 s (GET /api/risorse;
il server prende un campione ogni 2 s e tiene gli ultimi 2 minuti, `backend/risorse.py`). Mostra processore e memoria
di SentinelAI e del sistema, motore dell'IA, analisi al secondo, durata media e occupazione del motore, e per ogni
telecamera sorvegliata dal server i fotogrammi ricevuti, elaborati e analizzati. Senza librerie in più: /proc su
Linux, funzioni di sistema su Windows.

## Telecamera di prova (1.0.17)

Interruttore "Telecamera di prova" nella finestra della telecamera (etichetta PROVA sulla scheda): l'IA analizza, conta e
salva gli eventi, ma non scattano mai allarmi (né regole né zone), foto su Telegram o clip, e non si comprimono i
fotogrammi per le clip. Serve per webcam pubbliche del traffico. Sul CT 111 c'è un ponte (mediamtx + yt-dlp in
/opt/ponte-webcam, unità temporanea `ponte-webcam`, si spegne al riavvio del CT) che rende le dirette YouTube
come `rtsp://127.0.0.1:8554/jackson` e `rtsp://127.0.0.1:8554/springboro`. Gli eventi delle telecamere di prova
entrano nelle statistiche generali.

## Aggiornamento dall'app (1.0.12)

**Impostazioni → Aggiornamenti → Aggiorna**: SentinelAI scarica la versione nuova e si riavvia da solo.

- Le versioni si prendono dal repository **pubblico** `telard-pixel/sentinelai-rilasci`, che contiene solo gli
  installer (il codice resta qui, privato). Ogni versione ha il certificato `rilascio.json` firmato (RSA-PSS):
  versione, commit e impronta SHA-256 di Setup e pacchetto Linux. Si installa solo una versione più nuova, con firma
  valida (chiave pubblica `backend/chiave_pubblica.pem`, quella della versione già installata) e impronta giusta.
- Windows: il Setup scaricato parte in silenzio dopo la chiusura di SentinelAI (`aggiorna.cmd` nella cartella dati
  `aggiornamento`), poi SentinelAI si riapre. Se il Setup fallisce resta la versione di prima.
- CT Linux: il servizio (utente `sentinelai`) lascia solo la richiesta `/var/lib/SentinelAI/aggiornamento/richiesta`;
  `sentinelai-aggiorna.path` avvia come root `linux/aggiorna.sh`, che verifica, installa (codice, librerie se cambiate,
  unità systemd), riavvia e se SentinelAI non resta su rimette la versione di prima (`/opt/sentinelai.prima`).
  Registro: `/var/log/sentinelai-aggiorna.log`; stato per l'app: `/run/sentinelai-aggiorna/stato.json`.
  Installazione una tantum: copiare `linux/sentinelai-aggiorna.{path,service}` in `/etc/systemd/system`, poi
  `systemctl daemon-reload && systemctl enable --now sentinelai-aggiorna.path`.
- Pubblicazione, solo dopo l'ok dell'agente di prova: `bash tools/pubblica-rilascio.sh vX.Y.Z` (chiave privata in
  `/root/code/sentinelai-chiave/firma.pem`, mai nel repository).

## Sicurezza (revisione 06/11/2026)

- Il server risponde solo alla pagina dell'app: niente CORS aperto, i comandi e lo streaming che arrivano da un altro
  sito vengono rifiutati (controllo di Origin / Sec-Fetch-Site), e nella versione Windows solo i nomi `127.0.0.1` e
  `localhost` sono ammessi (protezione dal *DNS rebinding*). In Docker: `ALLOWED_HOSTS` in `backend/.env`.
- Le password delle telecamere (NVR e dentro gli indirizzi RTSP) non arrivano mai al browser: si vedono come `****`.
  Lasciando `****` la password resta quella di prima, ma solo per la stessa telecamera (stesso IP e porta).
- Versione Windows: `"rete": true` funziona solo insieme a una `"password"`.

## Password di accesso

Si imposta dall'app: **Impostazioni → Password di accesso** (imposta, cambia o togli; almeno 6 caratteri).
Viene salvata come impronta (scrypt), mai in chiaro. Cambiandola o togliendola, tutti i dispositivi già entrati devono
rientrare. In Docker si può anche mettere `APP_PASSWORD` in `backend/.env` (in quel caso si toglie solo da lì).
Il login con Google è stato provato e poi tolto (06/11/2026) su richiesta.

Consiglio: almeno 8 caratteri. Contro chi prova password a raffica: 8 errori in 15 minuti bloccano quell'indirizzo, e
oltre 100 errori in tutto gli indirizzi che hanno già sbagliato passano in coda (1 tentativo ogni 2 secondi per tutti);
chi è già entrato da quel dispositivo non viene mai frenato.

**Password dimenticata o file rovinato** (es. dopo un calo di corrente): chiudi SentinelAI (icona → Esci), cancella
`%LOCALAPPDATA%\SentinelAI\.app_password` e riapri: l'app parte senza password e la reimposti. Un file vuoto o rovinato
non apre MAI l'app senza password: la blocca e lo scrive nel registro.

## Versione Linux (CT Proxmox) — `linux/`

Stesso motore della versione Windows (YOLO11s ONNX + OpenCV + SQLite), senza finestra: si apre dal browser su
`http://<indirizzo>:8765`. Installata il 06/11/2026 nel CT 111 "sentinelai" (Debian 12).

- Programma in `/opt/sentinelai` (backend, desktop/sentinel_desktop.py, frontend/build, models/yolo11s.onnx, venv),
  dati in `/var/lib/SentinelAI`, video in `/var/lib/SentinelAI/video` (o la cartella scelta dall'app).
- Servizio `sentinelai.service` (utente `sentinelai`, parte da solo). Registro: `journalctl -u sentinelai`.
- Senza password resta su 127.0.0.1. Password: dall'app, oppure
  `runuser -u sentinelai -- /opt/sentinelai/venv/bin/python /opt/sentinelai/linux/imposta-password.py` e `systemctl restart sentinelai`.
- Nomi ammessi nell'indirizzo: gli IP del CT e il suo nome; altri con `Environment=SENTINEL_NOMI=...` nel servizio.

### IA sulla scheda video (1.0.14)

Su Linux l'IA gira con **OpenVINO** (il motore di Intel) invece di OpenCV DNN. Misurato sul CT 111 (i5-7600T),
una analisi di YOLO11s 640x448: OpenCV 234 ms e 0,44 s di CPU; OpenVINO sul processore 123 ms e 0,22 s;
OpenVINO sulla **scheda video Intel HD 630** 68 ms e 0,07 s, con punteggi identici (si resta in f32).

- **Windows (1.0.15)**: stesso motore incluso nell'exe. Usa la scheda video se è Intel (anche accanto a una
  NVIDIA), altrimenti il processore con OpenVINO (circa il doppio più veloce di OpenCV).
- **Windows (1.0.16), scelta automatica**: a ogni avvio il programma legge le schede video (registro di Windows)
  e prova **DirectML** (Microsoft, qualsiasi scheda DirectX 12: NVIDIA, AMD, Intel). Se c'è solo la scheda
  software di Windows (PC senza scheda o macchina virtuale: >0,08 s di processore per analisi) passa a OpenVINO
  sul processore, poi OpenCV. Stessa sentinella contro i crash (DirectML → OpenVINO).
- Il motore usato si vede in fondo alle Impostazioni ("IA OpenVINO GPU ...") e nel registro all'avvio.
- Ordine: scheda video → processore → OpenCV. Se la scheda si guasta mentre gira, si passa a OpenCV fino al
  riavvio. `Environment=SENTINEL_AI_MOTORE=cpu` (solo processore) o `opencv` (come prima) nel servizio.
- Per la scheda video servono: il dispositivo nel CT (sul Proxmox, in `/etc/pve/lxc/111.conf`:
  `dev0: /dev/dri/renderD128,gid=104,mode=0660`, 104 = gruppo render del CT) e nel CT `apt install intel-opencl-icd`.
  Il servizio non ha più PrivateDevices; DevicePolicy=closed + DeviceAllow=renderD128 chiude gli altri dispositivi
  solo su una macchina vera: dentro un CT LXC systemd non lo applica e restano i permessi dei file.
- Se openvino o il driver andassero in crash (il servizio ripartirebbe di continuo): `SENTINEL_AI_MOTORE=opencv`.
- Il modello compilato per la scheda va in `/var/lib/SentinelAI/cache-openvino` (avvio in 1 s invece di 8).
- Decodificare i video con la scheda NON conviene: provato l'8/11, la Sala 1080p costa ~16% di un core col
  processore e ~20% con la scheda (riportare le immagini indietro costa quanto decodificarle).
