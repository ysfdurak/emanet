"""Otomasyon akışlarının testleri."""
from datetime import date

import pytest

from emanet import otomasyon as A
from emanet import usta, veri_uret
from emanet.db import baglan

BUGUN = date(2026, 11, 16)


@pytest.fixture()
def con(tmp_path):
    c = baglan(tmp_path / "o.db")
    veri_uret.uret(c, BUGUN)
    return c


def hesap(con, ad=None):
    r = con.execute("SELECT * FROM hesap WHERE durum='aktif' ORDER BY ad LIMIT 1" if not ad else
                    "SELECT * FROM hesap WHERE ad=?", () if not ad else (ad,)).fetchone()
    return dict(r)


def ac(con, metin, h):
    return usta.cagri_ac(con, metin, h["birim"], 2, acan_kisi=h["ad"])


def bekleyen(con, cagri_id):
    o = usta.cagri_detay(con, cagri_id)["otomasyon"]
    return [m for m in o["mesajlar"] if m["cevap"] is None and m["tur"] in ("soru", "onay")]


def test_kurulum_eksik_bilgi_ve_onay(con):
    h = hesap(con)
    once = con.execute("SELECT kullanilan FROM lisans WHERE yazilim='BarTender Designer'").fetchone()[0]
    c = ac(con, "Bilgisayarıma BarTender kurulabilir mi?", h)
    assert c["otomasyon"]["durum"] == "bilgi_bekliyor"
    m = bekleyen(con, c["id"])[0]
    assert m["alan"] == "cihaz" and m["kime"] == h["ad"] and h["cihaz"] in m["secenekler"]
    A.cevapla(con, m["id"], h["cihaz"])
    m = bekleyen(con, c["id"])[0]
    assert m["tur"] == "onay" and m["rol"] == "yonetici"
    A.cevapla(con, m["id"], "Onayla")
    d = usta.cagri_detay(con, c["id"])
    assert d["durum"] == "kapali" and d["otomatik"] == 1 and d["otomasyon"]["durum"] == "basarili"
    assert con.execute("SELECT kullanilan FROM lisans WHERE yazilim='BarTender Designer'").fetchone()[0] == once + 1
    assert "BarTender Designer" in A._hesap(con, h["ad"])["yazilimlar"]
    assert any(m["tur"] == "teyit" for m in d["mesajlar"])


def test_onaysiz_kurulum_hemen(con):
    h = hesap(con)
    c = ac(con, f"Power BI kurulumu gerekiyor, bilgisayarım {h['cihaz']}.", h)
    assert c["durum"] == "kapali" and c["otomasyon"]["durum"] == "basarili"


def test_baskasinin_cihazi_insana(con):
    h = hesap(con)
    baska = con.execute("SELECT cihaz FROM hesap WHERE ad!=? LIMIT 1", (h["ad"],)).fetchone()[0]
    c = ac(con, f"Power BI kurulumu gerekiyor, bilgisayarım {baska}.", h)
    assert c["durum"] == "acik" and c["otomasyon"]["durum"] == "insana_devredildi"


def test_lisans_yok_ve_katalog_disi_insana(con):
    h = hesap(con)
    for metin in (f"Acrobat lazım, bilgisayarım {h['cihaz']}.", f"AutoCAD kurulumu gerekiyor, bilgisayarım {h['cihaz']}."):
        c = ac(con, metin, h)
        assert c["otomasyon"]["durum"] == "insana_devredildi" and c["durum"] == "acik"


def test_yetki_reddedilir(con):
    h = hesap(con)
    c = ac(con, "WMS'te sayım onaylayıcı yetkim yok, tanımlanabilir mi?", h)
    A.cevapla(con, bekleyen(con, c["id"])[0]["id"], "Geçici bir iş için")   # serbest metin
    A.cevapla(con, bekleyen(con, c["id"])[0]["id"], "Reddet")
    d = usta.cagri_detay(con, c["id"])
    assert d["otomasyon"]["durum"] == "reddedildi" and "Sayım onaylayıcı" not in A._hesap(con, h["ad"])["roller"]


def test_sifre_yanlis_kimlik_insana(con):
    h = hesap(con)
    c = ac(con, "Hesabım kilitlendi, şifremi de unuttum.", h)
    m = bekleyen(con, c["id"])[0]
    yanlis = [x for x in m["secenekler"] if x != h["sicil"][-3:]][0]
    A.cevapla(con, m["id"], yanlis)
    assert usta.cagri_detay(con, c["id"])["otomasyon"]["durum"] == "insana_devredildi"
    with pytest.raises(ValueError):
        A.cevapla(con, m["id"], yanlis)            # aynı mesaj ikinci kez cevaplanamaz


def test_onarim_sonucu_tutarli(con):
    h = hesap(con)
    c = ac(con, "Yazıcı çevrimdışı görünüyor, etiket basmıyor.", h)
    o = c["otomasyon"]
    assert o["durum"] in ("basarili", "insana_devredildi")
    assert (c["durum"] == "kapali") == (o["durum"] == "basarili")
    assert o["gunluk"][1]["metin"].startswith("Teşhis")


def test_ribon_sorunu_onarima_girmez(con):
    h = hesap(con)
    c = ac(con, "Yazıcı etiketleri boş çıkarıyor, ribon bitmiş olabilir.", h)
    assert c["otomasyon"] is None


def test_toplu_ariza_ve_teyit(con):
    kisiler = [dict(r) for r in con.execute("SELECT * FROM hesap LIMIT 3")]
    metinler = ["B koridoru bölgesinde kablosuz ağ sürekli kopuyor.", "Wi-Fi çekmiyor, tüm cihazlar düştü, B koridoru.",
                "B koridoru tarafında kablosuz ağ hiç görünmüyor."]
    cs = [ac(con, m, k) for m, k in zip(metinler, kisiler)]
    assert cs[-1]["toplu"]["cagri_sayisi"] == 3
    usta.cagri_kapat(con, cs[0]["id"], sure_dk=20, cozum_notu="Erişim noktası yeniden başlatıldı")
    for c in cs:
        assert usta.cagri_detay(con, c["id"])["durum"] == "kapali"
    t = [m for m in usta.cagri_detay(con, cs[1]["id"])["mesajlar"] if m["tur"] == "teyit"][0]
    A.cevapla(con, t["id"], "Hayır, devam ediyor")
    d = usta.cagri_detay(con, cs[1]["id"])
    assert d["durum"] == "acik" and d["teyit"] == 0 and d["cozum_notu"] is None


def test_ayni_kisinin_talepleri_birlesmez(con):
    h = hesap(con)
    for _ in range(3):
        c = ac(con, "Bilgisayarıma 7-Zip kurulabilir mi?", h)
    assert c["toplu"] is None


def test_recete_adayi_ve_taslak(con):
    adaylar = A.recete_adaylari(con)
    assert adaylar and all(a["tekrar"] >= A.ADAY_ESIK for a in adaylar)
    r = A.recete_olustur(con, adaylar[0]["kategori_id"], adaylar[0]["not_metni"])
    assert r["tur"] == "taslak" and r["seviye"] == "insan"
    assert adaylar[0]["not_metni"] not in [a["not_metni"] for a in A.recete_adaylari(con)]
    with pytest.raises(ValueError):
        A.recete_olustur(con, adaylar[0]["kategori_id"], adaylar[0]["not_metni"])


def test_potansiyel(con):
    p = A.potansiyel(con)
    assert 0 < p["insansiz_oran"] <= p["kapsanan_oran"] < 1 and p["kazanc_saat_ay"] > 0


def test_ise_giris_ve_cikis(con):
    o = A.ise_giris(con, "Ece Yalın", "Toplama", "Vardiya sorumlusu")
    h = A._hesap(con, "Ece Yalın")
    assert o["durum"] == "basarili" and "Power BI Desktop" in h["yazilimlar"] and len(h["roller"]) == len(set(h["roller"]))
    with pytest.raises(ValueError):
        A.ise_giris(con, "Ece Yalın", "Toplama", "Toplayıcı")
    once = con.execute("SELECT kullanilan FROM lisans WHERE yazilim='BarTender Designer'").fetchone()[0]
    con.execute("UPDATE hesap SET yazilimlar='[\"BarTender Designer\"]' WHERE ad='Ece Yalın'")
    o = A.isten_cikis(con, "Ece Yalın")
    assert o["durum"] == "basarili" and A._hesap(con, "Ece Yalın")["durum"] == "kapali"
    assert con.execute("SELECT kullanilan FROM lisans WHERE yazilim='BarTender Designer'").fetchone()[0] == once - 1
