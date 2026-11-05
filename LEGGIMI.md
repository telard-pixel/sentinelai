# SentinelAI · Vision Guard

Monitoraggio telecamere con AI locale (YOLOv8): persone, veicoli, animali e oggetti, la loro direzione,
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

Poi apri `http://<indirizzo-del-server>:8080`. La prima compilazione scarica PyTorch (CPU) e il modello YOLOv8n:
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
(e se vuoi sul desktop) e può partire insieme a Windows. Si apre in una finestra sua (Edge in modalità app) e resta
nell'area di notifica vicino all'orologio: *Apri SentinelAI*, *Avvia con Windows*, *Cartella dei dati*, *Esci*.

Differenze rispetto alla versione Docker, solo per essere un programma leggero:
- database in un file SQLite (`backend/docstore.py`, stessa interfaccia di MongoDB) invece del server MongoDB;
- YOLOv8n in formato ONNX con OpenCV invece di PyTorch (installer da ~100 MB invece di oltre 1 GB);
- clip H.264 con il codificatore di Windows invece di ffmpeg;
- nessun login (si usa sul proprio PC). Per metterlo: `%LOCALAPPDATA%\SentinelAI\config.json` → `"password": "..."`.
  Con `"rete": true` l'app risponde anche agli altri dispositivi della rete (porta 8765).

Dati in `%LOCALAPPDATA%\SentinelAI` (database, clip, registro `sentinelai.log`). Il token Telegram si mette dall'app
(Allarmi → Allarmi su Telegram).

Costruzione: GitHub Actions (`.github/workflows/windows.yml`) compila l'app, esporta YOLOv8n in ONNX, crea l'exe con
PyInstaller e l'installer con Inno Setup, **prova l'exe e l'installer** (`SentinelAI.exe --prova`) e con un tag `vX.Y.Z`
pubblica la Release.
