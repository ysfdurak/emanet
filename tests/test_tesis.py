"""Çok tesisli kurulum ve ana kategoriler: yerinde atama, grupla daraltma, tesis bazında toplu arıza ve ölçüler."""
from datetime import datetime

import pytest

from emanet import cagri_formu as F
from emanet import olcum, takip, usta
from emanet.db import baglan
from emanet.veri_uret import uret

GUNDUZ, AKSAM = datetime(2026, 11, 25, 10), datetime(2026, 11, 25, 18)


@pytest.fixture(scope="module")
def con():
    c = baglan(":memory:")
    uret(c)
    return c


def lok(con, bas):
    return next(r["id"] for r in con.execute("SELECT id, ad FROM lokasyon") if r["ad"].startswith(bas))


def kid(con, kod):
    return con.execute("SELECT id FROM kategori WHERE kod=?", (kod,)).fetchone()[0]


def test_cihaz_arizasi_once_tesisteki_kisiye(con):
    k, tuzla = kid(con, "ETIKET_YAZICI"), lok(con, "Tuzla")
    a = usta.yonlendir(con, k, AKSAM, "aksam", "Yazıcı basmıyor", "", 2, tuzla)
    assert a["ad"] == "Onur Yıldız" and a["yerinde"] is True
    g = usta.yonlendir(con, k, GUNDUZ, "gunduz", "Yazıcı basmıyor", "", 2, tuzla)   # Onur akşamcı
    assert g["ad"] != "Onur Yıldız" and g["yerinde"] is False and "yerinde bakabilecek kimse yok" in g["neden"]
    # Program işi uzaktan çözülür: tesis atamayı değiştirmez
    d = kid(con, "DALGA")
    assert usta.yonlendir(con, d, GUNDUZ, "gunduz", "Dalga açılmıyor", "", 2, tuzla)["yerinde"] is None


def test_grup_daraltir_ama_kesinlik_uydurmaz(con):
    o = usta.kategori_oner(con, "Sistem hata veriyor, devam edemiyorum", grup="donanim")
    assert o["soru_gerekli"] and all(x["ad"] in {"El terminali bağlanmıyor", "Etiket yazıcısı yazdırmıyor", "Barkod okunmuyor",
                                                  "Bilgisayar ve ekran arızası"} for x in o["oneriler"])
    assert not usta.kategori_oner(con, "Bağlantı kopuyor", grup="ag")["soru_gerekli"]   # grupta tek konu


def test_toplu_ariza_tesis_bazinda(con):
    k = kid(con, "WIFI")
    for i, t in enumerate(["Gebze", "Gebze", "İzmir"]):
        son = usta.cagri_ac(con, "Wi-Fi koptu", kategori_id=k, aciliyet=2, acan_kisi=f"Kişi {i}", lokasyon_id=lok(con, t))
    assert not son["toplu"]                                   # İzmir'deki üçüncü, Gebze'deki ikiyle birleşmez
    assert all(b["id"] != son["id"] for b in F.benzer_acik(con, k, None, lokasyon_id=lok(con, "Gebze")))


def test_olcum_ve_bugun_tesis(con):
    o = olcum.cagri_olculeri(con, 30)
    assert {t["ad"] for t in o["tesisler"]} == {"Gebze Merkez Depo", "Tuzla Aktarma Deposu", "İzmir Bölge Deposu"}
    tuzla = olcum.cagri_olculeri(con, 30, lokasyon_id=lok(con, "Tuzla"))
    assert 0 < tuzla["ozet"]["kapanan"] < o["ozet"]["kapanan"] and len(tuzla["tesisler"]) == 1
    assert any(d["metin"].startswith("Yerinde BT olmayan vardiyalar") for d in takip.dikkat(con))


def test_envanter_tesis_sutunu(con):
    s = F.envanter_ice_aktar(con, "no;tesis;model\nYZ-21;Ankara Deposu;Zebra ZT410\nyz 11;tuzla aktarma deposu;Honeywell PM43")
    assert s["eklenen"] == 1 and F.cihaz_kaydi(con, "YZ-21")["lokasyon"] == "Ankara Deposu"   # yeni tesis eklendi
    assert F.cihaz_kaydi(con, "YZ-11")["lokasyon"] == "Tuzla Aktarma Deposu"                   # büyük/küçük harf farkı
