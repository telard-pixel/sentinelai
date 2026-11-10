import pytest

import models
from models import Camera, CameraIn, Settings, Zone


def test_password_oscurata_negli_indirizzi():
    assert models.mask_url_password("rtsp://admin:segreta@10.0.0.5:554/a") == "rtsp://admin:****@10.0.0.5:554/a"
    assert models.mask_url_password("rtsp://admin:se@gr#e/ta@10.0.0.5/a") == "rtsp://admin:****@10.0.0.5/a"
    assert models.mask_url_password("rtsp://10.0.0.5/a") == "rtsp://10.0.0.5/a"
    t = models.mask_text("apro rtsp://u:pw1@h/x poi rtsp://v:pw 2@k/y fine")
    assert "pw1" not in t and "pw 2" not in t and "u:****" in t


def test_password_rimessa_solo_alla_stessa_telecamera():
    vecchio = "rtsp://admin:vera@10.0.0.5:554/a"
    assert models.restore_url_password("rtsp://admin:****@10.0.0.5:554/b", vecchio) == "rtsp://admin:vera@10.0.0.5:554/b"
    assert "vera" not in models.restore_url_password("rtsp://admin:****@10.0.0.9:554/a", vecchio)
    assert "vera" not in models.restore_url_password("rtsp://altro:****@10.0.0.5:554/a", vecchio)


def test_solo_rtsp():
    assert models.rtsp_url_allowed(CameraIn(name="a", type="rtsp", url="RTSP://h/x"))
    for u in ("file:///etc/passwd", "http://127.0.0.1/", "concat:a|b"):
        assert not models.rtsp_url_allowed(CameraIn(name="a", type="rtsp", url=u))


def test_nvr_e_pubblico():
    c = Camera(name="n", type="nvr", nvr_host="10.0.0.2", nvr_username="u", nvr_password="p@ss", nvr_channel=3, nvr_stream="main")
    assert models.stream_url(c) == "rtsp://u:p%40ss@10.0.0.2:554/Streaming/Channels/301"
    pub = models.camera_public(c)
    assert pub["nvr_password"] == "" and pub["has_nvr_password"] and "p%40ss" not in pub["url"]


def test_valori_non_validi():
    with pytest.raises(ValueError):
        Zone(name="z", points=[[0, 0], [float("nan"), 1], [1, 1]])
    with pytest.raises(ValueError):
        Settings(conf=float("inf"))
    with pytest.raises(ValueError):
        CameraIn(name="a", type="nvr", nvr_host="10.0.0.1/../x")
