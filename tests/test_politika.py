"""Kişi modeli: kalite ağırlığı ve paylaştırma kuralı."""
from datetime import date, datetime

import pytest

from emanet import ogrenme as O
from emanet import usta, veri_uret
from emanet.db import baglan


def test_kalite_agirligi_hizli_cozume_fazla_yavasa_az_verir():
    satir = [dict(kategori_id=1, sure_dk=d, teyit=None) for d in (10, 20, 20, 20, 80)]
    w = O.kalite_agirliklari(satir)
    assert w[0] == 1.5 and w[2] == 1.0 and w[4] == 0.5          # 20/10 sınırda 1,5; 20/80 sınırda 0,5
    assert O.kalite_agirliklari([dict(kategori_id=1, sure_dk=20, teyit=1)])[0] == pytest.approx(1.1)


def test_paylastirma_baskin_uzmandan_bilen_yedege_verir():
    say = {1: 18, 2: 4}            # 1 numara vardiyadaki çözümlerin %82'si
    k = O.paylastirma_secimi([(1, 0.8), (2, 0.15)], say, esik=3)
    assert k["kisi_id"] == 2 and k["tur"] == "paylastirma" and k["baskin"] == 1


def test_paylastirma_yedek_bilmiyorsa_ya_da_acil_kritikse_dokunmaz():
    assert O.paylastirma_secimi([(1, 0.8), (2, 0.15)], {1: 18, 2: 1}, esik=3)["kisi_id"] == 1     # yedek yetkin değil
    assert O.paylastirma_secimi([(1, 0.8), (2, 0.15)], {1: 18, 2: 4}, esik=3, acil_kritik=True)["kisi_id"] == 1
    assert O.paylastirma_secimi([(1, 0.8), (2, 0.15)], {1: 10, 2: 9}, esik=3)["kisi_id"] == 1     # baskınlık yok


def test_is_yuku_cezasi():
    k = O.paylastirma_secimi([(1, 0.5), (2, 0.4)], {1: 5, 2: 5}, esik=3, acik={1: 3})
    assert k["kisi_id"] == 2 and k["tur"] == "yuk"


@pytest.fixture()
def con(tmp_path):
    c = baglan(tmp_path / "t.db")
    veri_uret.uret(c, date.today())
    return c


def test_degerlendirme_uc_yolu_karsilastirir(con):
    p = O.degerlendir(con)["politika"]
    for ad in ("gercek", "model", "model_agirliksiz", "politika"):
        assert 0 <= p[ad]["yetkin_oran"] <= 1 and 0 < p[ad]["yogunlasma"] <= 1 and p[ad]["tahmini_sure"] > 0
    assert p["gercek"]["isabet"] == 1.0
    assert p["politika"]["yogunlasma"] <= p["model"]["yogunlasma"] + 1e-9


def test_canli_yonlendirmede_yuk_dengelenir_ve_kapatilabilir(con):
    kat = con.execute("SELECT id FROM kategori WHERE kod='ETIKET_YAZICI'").fetchone()[0]
    gunduz = datetime.now().replace(hour=10)
    metin = "Yazıcı ribonu bitti, soluk basıyor"
    con.execute("INSERT OR REPLACE INTO meta(anahtar,deger) VALUES('paylastirma','0')")
    uzman = usta.yonlendir(con, kat, gunduz, "gunduz", metin, "Depolama", aciliyet=2)
    assert uzman["paylastirma"] is None
    # Uzmanın üzerine 4 açık çağrı yığılır; paylaştırma açılınca çağrı konuyu bilen başka birine gider
    for _ in range(4):
        con.execute("INSERT INTO cagri(metin,acan_birim,aciliyet,kategori_id,durum,atanan_kisi_id,acilis,kaynak) "
                    "VALUES('x','Depolama',2,?,'acik',?,?,'usta')", (kat, uzman["kisi_id"], gunduz.isoformat()))
    con.execute("INSERT OR REPLACE INTO meta(anahtar,deger) VALUES('paylastirma','1')")
    ikinci = usta.yonlendir(con, kat, gunduz, "gunduz", metin, "Depolama", aciliyet=2)
    assert ikinci["kisi_id"] != uzman["kisi_id"] and ikinci["paylastirma"]["tur"] in ("yuk", "paylastirma")
    assert ikinci["paylastirma"]["neden"] in ikinci["neden"]
