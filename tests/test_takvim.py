"""Eğitim takvimi: sınırlar her kişi ve her hafta için tutuluyor mu, sıra korunuyor mu?"""
from collections import defaultdict
from datetime import date

import pytest

from emanet import takvim

PZT = date(2026, 11, 30)


def adim(kid, ad, tur, saat, ogreten, ogrenen=None, puan=(90, 40)):
    return dict(kategori_id=kid, kategori=ad, tur=tur, saat=saat, ogreten_id=ogreten[0], ogreten=ogreten[1],
                ogrenen_id=ogrenen[0] if ogrenen else None, ogrenen=ogrenen[1] if ogrenen else None,
                puan_once=puan[0], puan_sonra=puan[1])


MURAT, EMRE, ELIF, ZEYNEP = (1, "Murat"), (2, "Emre"), (3, "Elif"), (4, "Zeynep")
PLAN = [
    adim(11, "ERP", "kart", 2, MURAT),
    adim(11, "ERP", "tazeleme", 4, MURAT, EMRE),
    adim(9, "Sipariş", "kart", 2, ELIF),
    adim(9, "Sipariş", "egitim", 10, ELIF, ZEYNEP, puan=(99, 39)),
]


def sinirlar_tutuyor(t, haftalik, gunluk):
    hafta, gun = defaultdict(float), defaultdict(int)
    for o in t["oturumlar"]:
        for k in (o["ogreten_id"], o["ogrenen_id"]):
            if k is not None:
                hafta[(k, o["hafta"])] += o["saat"]
                gun[(k, o["tarih"])] += 1
    return max(hafta.values()) <= haftalik + 1e-9 and max(gun.values()) <= gunluk


def test_varsayilan_sinirlar_ve_toplam_saat():
    t = takvim.takvim_olustur(PLAN, PZT)
    assert sinirlar_tutuyor(t, 2.0, 1)
    assert sum(o["saat"] for o in t["oturumlar"]) == t["toplam_saat"] == 18
    assert all(o["saat"] <= 1 for o in t["oturumlar"])
    assert all(o["gun"] in takvim.GUN_ADLARI[:5] for o in t["oturumlar"])
    # Elif 12 saat veriyor, haftada 2 saatle 6 hafta: takvimi o belirler
    assert t["darbogaz"]["ad"] == "Elif" and t["hafta_sayisi"] == 6


def test_haftalik_sinir_artinca_takvim_kisalir():
    kisa = takvim.takvim_olustur(PLAN, PZT, haftalik_sinir=4)
    uzun = takvim.takvim_olustur(PLAN, PZT, haftalik_sinir=2)
    assert kisa["hafta_sayisi"] < uzun["hafta_sayisi"]
    assert sinirlar_tutuyor(kisa, 4, 1)


def test_parametreler_uygulanir():
    t = takvim.takvim_olustur(PLAN, PZT, haftalik_sinir=3, oturum_saat=0.5, gunluk_oturum=2, calisma_gunu=6)
    assert sinirlar_tutuyor(t, 3, 2)
    assert all(o["saat"] == 0.5 for o in t["oturumlar"])
    assert any(o["gun"] == "Cumartesi" for o in t["oturumlar"])
    assert t["ayarlar"]["calisma_gunu"] == 6


def test_adimin_parcalari_sirali_ve_en_riskli_once():
    t = takvim.takvim_olustur(PLAN, PZT)
    for adim_no in {o["adim"] for o in t["oturumlar"]}:
        parcalar = [o for o in t["oturumlar"] if o["adim"] == adim_no]
        tarihler = [o["tarih"] for o in sorted(parcalar, key=lambda o: o["parca"])]
        assert tarihler == sorted(tarihler) and len(set(tarihler)) == len(tarihler)
    assert t["oturumlar"][0]["kategori"] == "ERP"   # plan sırası: en riskli konu ilk gün


def test_baslangic_pazartesiye_cekilir_ve_bitis():
    t = takvim.takvim_olustur(PLAN, date(2026, 12, 3))   # perşembe
    assert t["ayarlar"]["baslangic"] == "2026-11-30"
    assert t["bitis"] == max(o["tarih"] for o in t["oturumlar"])
    assert takvim.sonraki_pazartesi(date(2026, 11, 25)) == date(2026, 11, 30)
    assert takvim.sonraki_pazartesi(date(2026, 11, 30)) == date(2026, 12, 7)


def test_bos_plan():
    t = takvim.takvim_olustur([], PZT)
    assert t["oturumlar"] == [] and t["hafta_sayisi"] == 0 and t["bitis"] is None and t["darbogaz"] is None


@pytest.mark.parametrize("ayar", [dict(haftalik_sinir=0.25), dict(oturum_saat=0.7), dict(oturum_saat=4, haftalik_sinir=2),
                                  dict(gunluk_oturum=0), dict(calisma_gunu=7)])
def test_gecersiz_ayar(ayar):
    with pytest.raises(ValueError):
        takvim.takvim_olustur(PLAN, PZT, **ayar)


def test_hafta_otelenir():
    t = takvim.takvim_olustur(PLAN, PZT, hafta_sinir={2: 0})
    duz = takvim.takvim_olustur(PLAN, PZT)
    assert all(o["hafta"] != 2 for o in t["oturumlar"])
    assert t["hafta_sayisi"] == duz["hafta_sayisi"] + 1
    assert t["degisiklikler"]["hafta_sinir"] == {"2": 0.0}


def test_haftaya_ozel_sinir_artirilir():
    t = takvim.takvim_olustur(PLAN, PZT, hafta_sinir={1: 5})
    h1 = defaultdict(float)
    for o in t["oturumlar"]:
        if o["hafta"] == 1:
            for k in (o["ogreten_id"], o["ogrenen_id"]):
                if k is not None:
                    h1[k] += o["saat"]
    assert max(h1.values()) == 5   # Elif ilk hafta 5 gün x 1 oturum
    assert sinirlar_tutuyor(dict(oturumlar=[o for o in t["oturumlar"] if o["hafta"] > 1]), 2, 1)
    assert t["hafta_sayisi"] < takvim.takvim_olustur(PLAN, PZT)["hafta_sayisi"]


def test_kisi_o_hafta_yok():
    t = takvim.takvim_olustur(PLAN, PZT, kisi_yok={(3, 1), (3, 2)})   # Elif iki hafta izinde
    assert all(not (3 in (o["ogreten_id"], o["ogrenen_id"]) and o["hafta"] in (1, 2)) for o in t["oturumlar"])
    # Murat'ın oturumları yerinde kalır
    assert any(o["ogreten_id"] == 1 and o["hafta"] == 1 for o in t["oturumlar"])
    assert t["degisiklikler"]["kisi_yok"] == [[3, 1], [3, 2]]


def test_gecersiz_degisiklik():
    with pytest.raises(ValueError):
        takvim.takvim_olustur(PLAN, PZT, hafta_sinir={0: 2})
    with pytest.raises(ValueError):
        takvim.takvim_olustur(PLAN, PZT, haftalik_sinir=2, hafta_sinir={h: 0 for h in range(1, 105)})
