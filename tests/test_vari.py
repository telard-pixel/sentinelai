import pytest

import aggiornamento
import temperatura
from session import in_window, point_in_polygon


def test_versioni():
    assert aggiornamento.numero("v1.0.12") == (1, 0, 12) and aggiornamento.numero("1.0.0-prova.5") == (1, 0, 0)
    assert aggiornamento.piu_nuova("v1.0.10", "1.0.9") and not aggiornamento.piu_nuova("v1.0.9", "1.0.9")
    assert not aggiornamento.piu_nuova("v1.0.8", "1.0.9") and aggiornamento.piu_nuova("v1.0.1", "sviluppo")


def test_firma_falsa_rifiutata():
    assert aggiornamento.firma_valida(b"prova", b"\0" * 384) is False
    with pytest.raises(aggiornamento.ErroreAggiornamento):
        aggiornamento.leggi_manifesto(b'{"progetto":"sentinelai","tag":"v9.0.0","versione":"9.0.0"}', b"\0" * 384, "v9.0.0", "1.0.0")


def test_finestra_oraria_e_poligono():
    assert in_window("23:30", "22:00", "06:00") and in_window("05:00", "22:00", "06:00") and not in_window("12:00", "22:00", "06:00")
    assert in_window("12:00", "08:00", "18:00") and not in_window("19:00", "08:00", "18:00")
    q = [[0, 0], [1, 0], [1, 1], [0, 1]]
    assert point_in_polygon(0.5, 0.5, q) and not point_in_polygon(1.5, 0.5, q)


def test_temperatura_sale_e_scende():
    t = temperatura.Termico()
    t.imposta(auto=True, limite=72)
    ora = 0.0
    for _ in range(40):                    # 80 s a 80 gradi
        t.aggiorna(80.0, ora); ora += 2
    assert t.livello == 2 and t.per_prova(True) == 2 and t.per_prova(False) == 0
    for _ in range(200):                   # 400 s a 60 gradi
        t.aggiorna(60.0, ora); ora += 2
    assert t.livello == 0
    for _ in range(40):
        t.aggiorna(80.0, ora); ora += 2
    t.imposta(auto=False)
    assert t.livello == 0


def test_temperatura_fra_le_soglie_la_pausa_finisce():
    t = temperatura.Termico()
    ora = 0.0
    for _ in range(40):
        t.aggiorna(80.0, ora); ora += 2
    for i in range(400):                   # oscilla fra 67 e 71: sotto il limite, la discesa deve arrivare
        t.aggiorna(69.0 if i % 2 else 70.0, ora); ora += 2
    assert t.livello == 0
