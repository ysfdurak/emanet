"""Emanet geliştirmeleri: otomasyonun riske etkisi, izin kontrolü, plan takibi, eskime, devir, seyir."""
from datetime import date, datetime, timedelta

import pytest

from emanet import otomasyon as A
from emanet import risk, takip, veri_uret
from emanet.db import baglan

BUGUN = date.today()


@pytest.fixture()
def con(tmp_path):
    c = baglan(tmp_path / "t.db")
    veri_uret.uret(c, BUGUN)
    return c


def pid(con, ad):
    return con.execute("SELECT id FROM kisi WHERE ad=?", (ad,)).fetchone()[0]


def puan(con, ad):
    return next(r for r in risk.risk_haritasi(con) if r["ad"] == ad)


def test_otomasyon_payi_formulu():
    s = {1: 9, 2: 1}
    a = risk.puan_hesapla(s, 3, False)["ham"]
    b = risk.puan_hesapla(s, 3, False, oto_payi=0.5)["ham"]
    assert b == pytest.approx(100 * ((0.45 * 0.9 + 0.35) * 0.5 + 0.2))
    assert b < a


def test_otomasyonlu_konuda_pay_var(con):
    r = puan(con, "Etiket yazıcısı yazdırmıyor")
    assert 0 < r["otomasyon_payi"] < 1 and r["azaltanlar"]


def test_taslak_recete_riski_dusurur(con):
    f = takip.otomasyon_firsatlari(con)
    dalga = next(x for x in f if x["kategori"] == "Sipariş dalgası açılmıyor")
    once = puan(con, "Sipariş dalgası açılmıyor")["puan"]
    A.recete_olustur(con, dalga["kategori_id"], dalga["not_metni"])
    sonra = puan(con, "Sipariş dalgası açılmıyor")
    assert sonra["puan"] == dalga["puan_sonra"] < once and not sonra["kartsiz"]
    assert "Sipariş dalgası açılmıyor" not in [x["kategori"] for x in takip.otomasyon_firsatlari(con)]


def test_izin_kontrolu_yedeksiz_konu(con):
    k = takip.izin_kontrol(con, pid(con, "Elif Kaya"), BUGUN + timedelta(days=5), BUGUN + timedelta(days=14))
    assert k["karar"] == "dikkat"
    assert next(x for x in k["konular"] if x["ad"] == "Sipariş dalgası açılmıyor")["durum"] == "yedeksiz"


def test_izin_kontrolu_alternatif_tarih(con):
    # Kemal Yılmaz 12 gün izinde: Serkan'ın şimdiki izni sorter'ı yedeksiz bırakır, sonrası daha uygun
    k = takip.izin_kontrol(con, pid(con, "Serkan Doğan"), BUGUN, BUGUN + timedelta(days=6))
    assert any(x["ad"] == "Sorter arızası" and x["durum"] == "yedeksiz" for x in k["konular"])
    assert k["alternatif"] and k["alternatif"]["sorun_puani"] < k["sorun_puani"]


def test_izin_kaydi_sonraki_kontrolu_etkiler(con):
    a, b = BUGUN + timedelta(days=20), BUGUN + timedelta(days=25)
    takip.izin_kaydet(con, pid(con, "Burak Şahin"), a, b)
    k = takip.izin_kontrol(con, pid(con, "Selin Koç"), a, b)
    assert "Burak Şahin" in [i["ad"] for i in k["cakisan_izinler"]]
    with pytest.raises(ValueError):
        takip.izin_kontrol(con, pid(con, "Selin Koç"), b, a)


def test_pratigi_kalmayan_yedek(con):
    r = puan(con, "ERP entegrasyon hatası")
    assert "Emre Çelik" in [e["ad"] for e in r["pratigi_kalmayan"]]
    assert any("Pratiği kalmamış" in n for n in r["nedenler"])


def test_planda_tazeleme_ucuz(con):
    p = risk.egitim_plani(con, 60)
    t = [s for s in p["satirlar"] if s["tur"] == "tazeleme" and s["kategori"] == "ERP entegrasyon hatası"]
    assert t and t[0]["saat"] < next(k for k in con.execute("SELECT ogrenme_saati FROM kategori WHERE kod='ENTEGRASYON'"))[0]


def test_plan_takibi_ve_simulasyon(con):
    assert takip.plan_takibi(con)["var"] is False
    with pytest.raises(ValueError):
        takip.plan_simule_et(con)
    risk.egitim_plani(con, 60, kaydet=True)
    t = takip.plan_takibi(con)
    assert t["var"] and t["tutma_orani"] == 0
    r = takip.plan_simule_et(con)
    assert r["uretilen_cagri"] > 0
    t = takip.plan_takibi(con)
    assert 0 < t["tutma_orani"] <= 1 and t["simule"]
    assert sum(k["simdi"] < k["once"] for k in t["konular"]) >= len(t["konular"]) // 2
    with pytest.raises(ValueError):
        takip.plan_simule_et(con)


def test_devir_dosyasi(con):
    d = takip.devir_dosyasi(con, pid(con, "Elif Kaya"))
    dalga = next(k for k in d["konular"] if k["ad"] == "Sipariş dalgası açılmıyor")
    assert dalga["kritik"] and dalga["cozum_yollari"] and dalga["adimlar"]
    assert d["markdown"].startswith("# Devir dosyası: Elif Kaya") and "- [ ]" in d["markdown"]


def test_risk_seyri(con):
    r = takip.risk_seyri(con)
    assert len(r["noktalar"]) >= 5 and r["noktalar"][-1]["tarih"] == BUGUN.isoformat()
    assert all(len(z["seri"]) == len(r["noktalar"]) for z in r["izlenen"])
    assert any("Otomatik çözümler" in o["metin"] for o in r["olaylar"])
