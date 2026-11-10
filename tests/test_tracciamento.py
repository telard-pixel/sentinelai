from detection import Tracker, category_of, heading_of
from conftest import riquadro


def test_categorie_e_direzioni():
    assert [category_of(i) for i in (0, 2, 15, 60)] == ["persona", "veicolo", "animale", "oggetto"]
    assert heading_of(0.1, 0)[0] == "Destra" and heading_of(0, -0.1)[0] == "Alto" and heading_of(0.001, 0)[0] == "Fermo"


def test_stessa_traccia_mentre_si_muove():
    t, now = Tracker(), 0.0
    ids = set()
    for i in range(10):
        active, _ = t.update([(0, 0.8, riquadro(0.2 + 0.03 * i, 0.5))], now)
        ids |= {a.id for a in active}
        now += 0.2
    assert len(ids) == 1 and next(iter(t.tracks.values())).hits == 10


def test_due_persone_che_si_incrociano_non_si_scambiano():
    t, now = Tracker(), 0.0
    for i in range(12):
        a, b = 0.2 + 0.05 * i, 0.8 - 0.05 * i
        t.update([(0, 0.8, riquadro(a, 0.4)), (0, 0.8, riquadro(b, 0.6))], now)
        now += 0.2
    fine = sorted((tr.first[0], tr.history[-1][0]) for tr in t.tracks.values())
    assert len(fine) == 2 and fine[0][1] > 0.6 and fine[1][1] < 0.4


def test_scadenza_ed_eredita():
    t, now = Tracker(), 0.0
    for i in range(6):
        t.update([(0, 0.8, riquadro(0.3 + 0.02 * i, 0.5))], now); now += 0.2
    scadute = []
    for _ in range(12):
        _, ex = t.update([], now); scadute += ex; now += 0.2
    assert len(scadute) == 1 and not t.tracks
    vecchia = scadute[0]
    vecchia.crossed = True
    active, _ = t.update([(0, 0.8, riquadro(0.41, 0.5))], now)      # ricompare lì vicino entro 10 s
    assert active[0].id != vecchia.id and active[0].inherited_crossed and active[0].born == vecchia.born


def test_classi_diverse_tracce_diverse():
    t = Tracker()
    t.update([(0, 0.8, riquadro(0.5, 0.5))], 0.0)
    active, _ = t.update([(15, 0.8, riquadro(0.5, 0.5))], 0.2)
    assert len(t.tracks) == 2
