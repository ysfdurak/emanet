"""Pilot bitiş ölçütü 2: kirli veride model hedefin üstünde ve basit kuralı geçiyor."""
from araclar import gurultu_testi


def test_gurultulu_veride_olcut_gecer():
    sonuc, tabanlar = gurultu_testi.calistir()
    r = dict(sonuc)["Hepsi birlikte (ölçüt)"]
    assert r["konu"] >= 0.75
    assert r["kisi_ilk3"] >= 0.80
    assert r["kisi_ilk3"] > tabanlar["kural_ilk3"] > tabanlar["rastgele_ilk3"]
