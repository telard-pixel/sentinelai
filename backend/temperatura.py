"""Temperatura del processore e regolazione automatica (1.0.21, richiesta di Roberto: "verifica le temperature,
se superano un limite si auto regola").

Solo sul SERVER Linux (CT/Docker): si legge il sensore del processore da /sys/class/hwmon (nel CT si vede quello
del Proxmox, sola lettura). Sull'app Windows la temperatura non si legge e la regolazione non fa niente.

A scalini, e SOLO sulle telecamere di prova (le webcam pubbliche): Garage, Sala e ogni telecamera vera non
vengono MAI rallentate, la sorveglianza ha la precedenza.
  livello 0  normale
  livello 1  telecamere di prova analizzate un terzo delle volte
  livello 2  telecamere di prova in pausa (flusso chiuso: niente decodifica)
Si sale di un livello se si resta sopra il limite per SALITA secondi (e almeno SALITA dopo il cambio precedente);
si scende di un livello se si resta sotto (limite - ISTERESI) per DISCESA secondi.
"""
import glob
import logging
import os
import sys
import time

logger = logging.getLogger("temperatura")

SALITA = 30.0
DISCESA = 120.0
ISTERESI = 5
LIMITE_PREDEFINITO = 72
#: rallentamento del livello 1: il giro delle telecamere di prova dura FATTORE volte tanto
FATTORE = 3.0
_PROCESSORI = ("coretemp", "k10temp", "zenpower", "cpu_thermal", "cpu-thermal", "soc_thermal")


def leggi_processore(base="/sys/class/hwmon"):
    """Temperatura del processore in °C (la più alta fra pacchetto e core), o None se non si sa."""
    if not sys.platform.startswith("linux"):
        return None
    valori = []
    for h in glob.glob(os.path.join(base, "hwmon*")):
        try:
            with open(os.path.join(h, "name")) as f:
                if f.read().strip() not in _PROCESSORI:
                    continue
            for t in glob.glob(os.path.join(h, "temp*_input")):
                try:
                    with open(t) as f:
                        v = int(f.read().strip()) / 1000
                    if -20 < v < 130:          # valori assurdi = sensore rotto
                        valori.append(v)
                except (OSError, ValueError):
                    continue
        except OSError:
            continue
    return max(valori) if valori else None


class Termico:
    def __init__(self):
        self.auto = True
        self.limite = LIMITE_PREDEFINITO
        self.livello = 0
        self.temperatura = None
        self._sopra_da = None
        self._sotto_da = None
        self._ultimo_cambio = 0.0

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
        self._sopra_da = self._sotto_da = None

    def aggiorna(self, temperatura, ora=None):
        """Chiamata a ogni campione (ogni 2 s) dal monitor risorse."""
        ora = time.monotonic() if ora is None else ora
        self.temperatura = temperatura
        if not self.auto or temperatura is None:
            if self.livello:
                self._cambia(0, "regolazione spenta" if not self.auto else "sensore non disponibile", ora)
            return
        if temperatura >= self.limite:
            self._sotto_da = None
            self._sopra_da = self._sopra_da or ora
            if self.livello < 2 and ora - self._sopra_da >= SALITA and ora - self._ultimo_cambio >= SALITA:
                self._cambia(self.livello + 1, f"sopra il limite da {ora - self._sopra_da:.0f} s", ora)
        elif temperatura <= self.limite - ISTERESI:
            self._sopra_da = None
            self._sotto_da = self._sotto_da or ora
            if self.livello > 0 and ora - self._sotto_da >= DISCESA:
                self._cambia(self.livello - 1, f"sotto {self.limite - ISTERESI} °C da {ora - self._sotto_da:.0f} s", ora)
        else:                                   # fra le due soglie: si resta come si è
            self._sopra_da = self._sotto_da = None

    def per_prova(self, prova: bool) -> int:
        """Livello che vale per una telecamera: 0 per tutte quelle vere."""
        return self.livello if prova else 0

    def stato(self) -> dict:
        return {"temperatura": None if self.temperatura is None else round(self.temperatura, 1), "auto": self.auto,
                "limite": self.limite, "livello": self.livello, "ripresa": self.limite - ISTERESI}


termico = Termico()
