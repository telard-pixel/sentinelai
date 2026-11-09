"""Temperatura del processore e regolazione automatica (1.0.21, richiesta di Roberto: "verifica le temperature,
se superano un limite si auto regola").

Solo sul SERVER Linux (CT/Docker): si legge il sensore del processore da /sys/class/hwmon (nel CT si vede quello
del Proxmox, sola lettura). Sull'app Windows la temperatura non si legge e la regolazione non fa niente.

A scalini, e SOLO sulle telecamere di prova (le webcam pubbliche): Garage, Sala e ogni telecamera vera non
vengono MAI rallentate, la sorveglianza ha la precedenza.
  livello 0  normale
  livello 1  telecamere di prova analizzate un terzo delle volte
  livello 2  telecamere di prova in pausa (flusso chiuso: niente decodifica)
Si decide sulla MEDIA degli ultimi MEDIA_CAMPIONI campioni (30 s), non sul singolo valore che oscilla di 2-3 °C.
Si sale di un livello se la media è sopra il limite (e almeno SALITA dopo il cambio precedente); si scende di un
livello dopo DISCESA secondi con la media sotto (limite - ISTERESI); il conto della discesa riparte SOLO se la media
torna sopra il limite (agente di prova 1.0.21: con la temperatura normale fra 67 e 72 °C la pausa non finiva mai).
"""
import glob
import logging
import os
import sys
import time
from collections import deque

logger = logging.getLogger("temperatura")

SALITA = 30.0
DISCESA = 120.0
ISTERESI = 2
MEDIA_CAMPIONI = 15        # a un campione ogni 2 s = 30 s
LIMITE_PREDEFINITO = 72
#: rallentamento del livello 1: il giro delle telecamere di prova dura FATTORE volte tanto
FATTORE = 3.0
_PROCESSORI = ("coretemp", "k10temp", "zenpower", "cpu_thermal", "cpu-thermal", "soc_thermal")


def leggi_processore(base="/sys/class/hwmon"):
    """Temperatura del processore in °C: il sensore "Package" se c'è (meno ballerino), altrimenti il più alto dei
    sensori del processore; None se non si sa (Windows, sensori assenti)."""
    if not sys.platform.startswith("linux"):
        return None
    pacchetto, valori = [], []
    for h in glob.glob(os.path.join(base, "hwmon*")):
        try:
            with open(os.path.join(h, "name")) as f:
                if f.read().strip() not in _PROCESSORI:
                    continue
        except OSError:
            continue
        for t in glob.glob(os.path.join(h, "temp*_input")):
            try:
                with open(t) as f:
                    v = int(f.read().strip()) / 1000
            except (OSError, ValueError):
                continue
            if not -20 < v < 130:          # valori assurdi = sensore rotto
                continue
            valori.append(v)
            try:
                with open(t[:-len("_input")] + "_label") as f:
                    if f.read().strip().lower().startswith(("package", "tctl", "tdie")):
                        pacchetto.append(v)
            except OSError:
                pass
    if pacchetto:
        return max(pacchetto)
    return max(valori) if valori else None


class Termico:
    def __init__(self):
        self.auto = True
        self.limite = LIMITE_PREDEFINITO
        self.livello = 0
        self.temperatura = None
        self._sotto_da = None
        self._ultimo_cambio = None
        self._campioni: deque = deque(maxlen=MEDIA_CAMPIONI)

    def imposta(self, auto=None, limite=None):
        if auto is not None:
            self.auto = bool(auto)
        if limite is not None:
            self.limite = int(limite)
        if not self.auto and self.livello:
            self._cambia(0, "regolazione spenta")

    def _cambia(self, livello, perche, ora=None):
        if livello == self.livello:
            return
        nomi = {0: "telecamere di prova di nuovo normali", 1: "telecamere di prova rallentate",
                2: "telecamere di prova in pausa"}
        t = f"{self.temperatura:.0f} °C" if self.temperatura is not None else "?"
        (logger.warning if livello > self.livello else logger.info)("temperatura %s (limite %d °C): %s (%s)", t, self.limite, nomi[livello], perche)
        self.livello = livello
        self._ultimo_cambio = time.monotonic() if ora is None else ora
        self._sotto_da = None

    def aggiorna(self, temperatura, ora=None):
        """Chiamata a ogni campione (ogni 2 s) dal monitor risorse."""
        ora = time.monotonic() if ora is None else ora
        self.temperatura = temperatura
        if temperatura is None:
            self._campioni.clear()
        else:
            self._campioni.append(temperatura)
        if not self.auto or temperatura is None:
            if self.livello:
                self._cambia(0, "regolazione spenta" if not self.auto else "sensore non disponibile", ora)
            return
        if len(self._campioni) < self._campioni.maxlen:      # meno di 30 s di dati: non si decide
            return
        media = self.media
        dal_cambio = None if self._ultimo_cambio is None else ora - self._ultimo_cambio
        if media >= self.limite:
            self._sotto_da = None
            if self.livello < 2 and (dal_cambio is None or dal_cambio >= SALITA):
                self._cambia(self.livello + 1, f"media degli ultimi 30 s {media:.1f} °C", ora)
        elif media <= self.limite - ISTERESI:
            if self._sotto_da is None:
                self._sotto_da = ora
            if self.livello > 0 and ora - self._sotto_da >= DISCESA:
                self._cambia(self.livello - 1, f"media sotto {self.limite - ISTERESI} °C da {ora - self._sotto_da:.0f} s", ora)
        # fra le due soglie: il conto della discesa continua, quello della salita aspetta la media sopra il limite

    @property
    def media(self):
        return sum(self._campioni) / len(self._campioni) if self._campioni else None

    def per_prova(self, prova: bool) -> int:
        """Livello che vale per una telecamera: 0 per tutte quelle vere."""
        return self.livello if prova else 0

    def stato(self) -> dict:
        m = self.media
        return {"temperatura": None if self.temperatura is None else round(self.temperatura, 1),
                "media": None if m is None else round(m, 1), "auto": self.auto,
                "limite": self.limite, "livello": self.livello, "ripresa": self.limite - ISTERESI}


termico = Termico()
