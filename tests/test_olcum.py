"""Çağrı ölçüleri: ortanca süre, bilgi beklemesinin düşülmesi, konuya göre hız, yeniden açılan."""
from datetime import datetime, timedelta

import pytest

from emanet import olcum, otomasyon, usta
from emanet.db import baglan
from emanet.veri_uret import uret


@pytest.fixture(scope="module")
def con():
    c = baglan(":memory:")
    uret(c)
    return c


def test_ozet_ve_kisiler(con):
    o = olcum.cagri_olculeri(con, 30)
    z = o["ozet"]
    assert z["kapanan"] > 100 and z["ortanca_dk"] <= z["p90_dk"]
    assert 0.85 <= z["ilk_seferde"] <= 1 and z["yeniden_acilan"] > 0
    assert [k["ad"] for k in o["kisiler"]] == sorted(k["ad"] for k in o["kisiler"])   # yarış tablosu değil
    # Konuya göre hız konunun ortancasına göredir: kapattıklarının ortancası 1 civarında
    assert all(0.3 < k["konuya_gore"] < 3 for k in o["kisiler"] if k["konuya_gore"])
    assert len(o["haftalar"]) == 8 and sum(h["acilan"] for h in o["haftalar"]) > 0


def test_bilgi_beklemesi_cozene_yazilmaz(con):
    k = con.execute("SELECT id FROM kategori WHERE kod='RAPOR'").fetchone()[0]
    c = usta.cagri_ac(con, "Rapor yenilenmiyor", kategori_id=k, aciliyet=1, acan_kisi="Serdar Kurt")
    usta.soru_sor(con, c["id"], "Hangi rapor, hangi filtre?")
    # Bekleme: soru ile cevap arası 120 dk (geçmiş kaydını elle ileri al)
    olay = con.execute("SELECT id, zaman FROM cagri_olay WHERE cagri_id=? AND tur='durum'", (c["id"],)).fetchone()
    bas = datetime.fromisoformat(olay["zaman"][:16])
    m = con.execute("SELECT id FROM mesaj WHERE cagri_id=? AND tur='soru'", (c["id"],)).fetchone()[0]
    otomasyon.cevapla(con, m, "Stok raporu, dünkü tarih")
    con.execute("UPDATE cagri_olay SET zaman=? WHERE cagri_id=? AND tur='durum' AND aciklama LIKE 'Bilgi bekleniyor →%'",
                ((bas + timedelta(minutes=120)).isoformat(timespec="minutes"), c["id"]))
    usta.cagri_kapat(con, c["id"], sure_dk=150, cozum_notu="Küpü yeniledim")
    assert olcum._bekleme_dk(con, [c["id"]])[c["id"]] == pytest.approx(120)


def test_donem_sinirlari(con):
    assert olcum.cagri_olculeri(con, 1)["ozet"]["gun"] == 7
    assert olcum.cagri_olculeri(con, 999)["ozet"]["gun"] == 180
