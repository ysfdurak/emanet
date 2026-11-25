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


def test_parcala_vardiya_pazar_bilgi():
    # Cumartesi 22:00 açıldı, pazartesi 09:00 kapandı; çözen gündüzcü
    p = olcum.parcala(datetime(2026, 11, 21, 22), datetime(2026, 11, 23, 9), "gunduz")
    assert p == dict(calisma=60, bekleme=600, bilgi=0, kapali=1440)
    # Gündüzcü 10:00-12:00 arası; 30 dk açandan bilgi beklendi; izinliyse hepsi vardiya beklemesi
    b = [(datetime(2026, 11, 24, 10, 30), datetime(2026, 11, 24, 11))]
    assert olcum.parcala(datetime(2026, 11, 24, 10), datetime(2026, 11, 24, 12), "gunduz", bilgi=b)["calisma"] == 90
    izinli = olcum.parcala(datetime(2026, 11, 24, 10), datetime(2026, 11, 24, 12), "gunduz", {datetime(2026, 11, 24).date()})
    assert izinli["calisma"] == 0 and izinli["bekleme"] == 120


def test_hedef_ve_asim(con):
    with pytest.raises(ValueError):
        olcum.hedef_kaydet(con, 3, 1, None)
    olcum.hedef_kaydet(con, 3, 30, 240)
    z = olcum.cagri_olculeri(con, 30)["ozet"]
    assert z["hedefler"]["3"]["cozum_dk"] == 240 and z["hedef_asimi"]["cozum"] >= 0
    olcum.hedef_kaydet(con, 3, None, None)                 # ikisi de boş: hedef kalkar
    assert olcum.hedefler(con) == {}


def test_vardiya_boslugu_tek_kisilik_konuda(con):
    """Bilen tek kişi gündüzcü olan konular vardiya beklemesinde öne çıkar; pazar çağrı yok."""
    v = olcum.vardiya_boslugu(con)
    assert v and v["ad"] in ("Sipariş dalgası açılmıyor", "ERP entegrasyon hatası")
    assert con.execute("SELECT COUNT(*) FROM cagri WHERE kaynak='usta' AND strftime('%w', acilis)='0' "
                       "AND date(acilis)<date('now', 'localtime')").fetchone()[0] == 0
    assert olcum.cagri_olculeri(con, 30)["ozet"]["tepki_ortanca_dk"] is not None
