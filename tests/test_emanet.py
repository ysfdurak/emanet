"""Çekirdek testleri. Çalıştırma: pytest"""
import random
from datetime import date, datetime

import pytest

from emanet import ice_aktar, ogrenme, risk, usta, veri_uret
from emanet import katalog as K
from emanet.db import baglan

BUGUN = date(2026, 11, 16)
GECE = datetime(2026, 11, 16, 2, 30)
GUNDUZ = datetime(2026, 11, 16, 10, 0)


@pytest.fixture(scope="module")
def con(tmp_path_factory):
    c = baglan(tmp_path_factory.mktemp("db") / "t.db")
    veri_uret.uret(c, BUGUN)
    return c


def kid(con, kod):
    return con.execute("SELECT id FROM kategori WHERE kod=?", (kod,)).fetchone()[0]


def pid(con, ad):
    return con.execute("SELECT id FROM kisi WHERE ad=?", (ad,)).fetchone()[0]


# ---- veri
def test_veri_tekrarlanabilir(tmp_path):
    a, b = baglan(tmp_path / "a.db"), baglan(tmp_path / "b.db")
    veri_uret.uret(a, BUGUN); veri_uret.uret(b, BUGUN)
    s = "SELECT metin, kategori_id, cozen_kisi_id, sure_dk, cozum_notu, kaynak FROM cagri ORDER BY id"
    assert [tuple(r) for r in a.execute(s)] == [tuple(r) for r in b.execute(s)]


def test_iki_kaynak(con):
    k = dict(con.execute("SELECT kaynak, COUNT(*) FROM cagri GROUP BY kaynak").fetchall())
    assert k["usta"] == 912 and k[veri_uret.BAKIM_KAYNAGI] == 650
    usta_birimleri = {r[0] for r in con.execute(
        "SELECT DISTINCT b.ad FROM kategori k JOIN birim b ON b.id=k.birim_id WHERE k.kaynak='usta'")}
    assert usta_birimleri == set(K.USTA_BIRIMLERI)


# ---- içe aktarma
def test_ice_aktarma_esnek_bicim():
    con = baglan(":memory:")
    csv = ("Tarih,Birim,Konu,Çözen,Süre\n"
           "02.11.2026 09:15,Bakım,Konveyör durması,Ali,35\n"
           "2026-11-03 23:10,Bakım,Konveyör durması,Veli,40\n"
           "bozuk,Bakım,Konveyör durması,Ali,10\n")
    r = ice_aktar.yukle(con, csv, "Test")
    assert r["satir"] == 2 and r["hatali"] == 1 and r["yeni_konu"] == 1 and r["yeni_kisi"] == 2
    assert con.execute("SELECT vardiya FROM kisi WHERE ad='Veli'").fetchone()[0] == "aksam"


def test_ice_aktarma_eksik_sutun():
    with pytest.raises(ValueError, match="Eksik sütun"):
        ice_aktar.oku("tarih;konu\n2026-11-01;x\n")


def test_dokum_analizi_kaydetmez(con):
    once = con.execute("SELECT COUNT(*) FROM cagri").fetchone()[0]
    r = ice_aktar.analiz_et(veri_uret.bakim_dokumu_csv(BUGUN))
    assert r["konular"][0]["ad"] == "Sorter arızası"
    assert con.execute("SELECT COUNT(*) FROM cagri").fetchone()[0] == once


# ---- öğrenme
def test_model_kuraldan_iyi(con):
    d = ogrenme.degerlendir(con)
    assert d["konu"]["model"] >= 0.9 and d["konu"]["model"] > d["konu"]["kural"]
    assert d["kisi"]["model"] > d["kisi"]["kural"]
    assert d["kisi"]["model_ilk3"] > d["kisi"]["kural_ilk3"]
    assert d["konu"]["emin_oldugunda"] >= 0.97


def test_yeni_metinlerde_konu(con):
    rnd, dogru, n = random.Random(1), 0, 0
    for k in K.USTA_KATEGORILERI:
        for a in k["alt"]:
            for s in a["sablonlar"]:
                o = usta.kategori_oner(con, s.format(yer=rnd.choice(K.YERLER), no=rnd.randint(1, 48), yazilim="Power BI",
                                                     pc="PC-1234", rol="sayım onaylayıcı"))
                dogru += o["oneriler"][0]["kod"] == k["kod"]; n += 1
    assert dogru / n >= 0.95


def test_belirsiz_metinde_soru(con):
    assert usta.kategori_oner(con, "Sistem hata veriyor, devam edemiyorum")["soru_gerekli"]
    o = usta.kategori_oner(con, "Yazıcı çevrimdışı görünüyor")
    assert not o["soru_gerekli"] and o["oneriler"][0]["kod"] == "ETIKET_YAZICI"


def test_teknik_ariza_kapsam_disi(con):
    o = usta.kategori_oner(con, "Sorter durdu, koliler şutlara gitmiyor")
    assert o["kapsam_disi"]["ad"] == "Sorter arızası" and o["soru_gerekli"]


def test_alt_sorunun_uzmanini_ogrenir(con):
    """Aynı konu (yazıcı), farklı alt sorun: ağ sorunu Tolga/Onur'a, ribon sorunu Burak/Selin'e."""
    m = ogrenme.model(con)
    k = kid(con, "ETIKET_YAZICI")
    ag = m.kisi_olasiliklari("Yazıcı çevrimdışı görünüyor, ağdan ulaşılamıyor", k, "gunduz", "Paketleme")
    ribon = m.kisi_olasiliklari("Yazıcı etiketleri boş çıkarıyor, ribon bitmiş", k, "gunduz", "Paketleme")
    assert max(ag, key=ag.get) == pid(con, "Tolga Demir")
    assert max(ribon, key=ribon.get) == pid(con, "Burak Şahin")


def test_vardiyada_olmayan_uzmana_atanmaz(con):
    a = usta.yonlendir(con, kid(con, "DALGA"), GECE, "gece", "Sipariş dalgası açılmıyor", "Sevkiyat")
    assert a["ad"] != "Elif Kaya" and a["uzman"]["ad"] == "Elif Kaya"
    assert con.execute("SELECT vardiya FROM kisi WHERE id=?", (a["kisi_id"],)).fetchone()[0] == "gece"


def test_izindeki_kisiye_atanmaz(con):
    a = usta.yonlendir(con, kid(con, "STOK_FARKI"), GUNDUZ, "aksam", "Stok eksi bakiyeye düşmüş", "Sevkiyat")
    assert a["ad"] != "Zeynep Aydın"   # akşamcı, raporlu


def test_nasil_cozuldu(con):
    y = usta.yol_goster(con, "Sipariş dalgası açılmıyor, toplama görevleri düşmedi", kid(con, "DALGA"))
    assert y["yollar"] and "Elif Kaya" in y["yollar"][0]["kisiler"]
    assert any("dalga" in a.lower() for g in y["yollar"] for a in g["adimlar"])


def test_kapanan_cagridan_ogrenir(tmp_path):
    c = baglan(tmp_path / "o.db"); veri_uret.uret(c, BUGUN)
    yeni = "Lazer okuyucu bağlantısı kopuyor, el terminali okutmuyor"
    cg = usta.cagri_ac(c, yeni, kategori_id=kid(c, "EL_TERMINALI"), vardiya="gunduz", simdi=GUNDUZ)
    usta.cagri_kapat(c, cg["id"], sure_dk=12, cozum_notu="Okuyucu modülü yeniden eşlendi\nTest okutması yapıldı")
    y = usta.yol_goster(c, yeni, kid(c, "EL_TERMINALI"))
    assert any(g["adimlar"][0] == "Okuyucu modülü yeniden eşlendi" for g in y["yollar"])


def test_cagri_yasam_dongusu(con):
    with pytest.raises(ValueError, match="belirsiz"):
        usta.cagri_ac(con, "Sistem hata veriyor, devam edemiyorum", simdi=GUNDUZ)
    c = usta.cagri_ac(con, "El terminali sisteme bağlanmıyor", vardiya="gunduz", simdi=GUNDUZ)
    assert c["kategori_kod"] == "EL_TERMINALI" and c["durum"] == "acik" and c["atanan"]
    c = usta.yeniden_ata(con, c["id"], kategori_id=kid(con, "WIFI"), vardiya="gunduz")
    assert c["kategori_kod"] == "WIFI" and c["yeniden_atama"] >= 1
    with pytest.raises(ValueError):
        usta.yeniden_ata(con, c["id"], kategori_id=con.execute("SELECT id FROM kategori WHERE kaynak!='usta'").fetchone()[0])
    once = len(usta.kartlar(con)["kartlar"])
    c = usta.cagri_kapat(con, c["id"], sure_dk=25, cozum_notu="Erişim noktası yeniden başlatıldı", karta_donustur=True)
    assert c["durum"] == "kapali" and c["kart_id"] and c["cozum_notu"]
    assert len(usta.kartlar(con)["kartlar"]) == once + 1
    with pytest.raises(ValueError):
        usta.cagri_kapat(con, c["id"])


# ---- Emanet
def test_puan_formulu():
    h = risk.puan_hesapla({1: 9, 2: 1}, kritiklik=3, kart_var=False)
    assert h["puan"] == round(100 * (0.45 * 0.9 + 0.35 * 1.0 + 0.20))
    h = risk.puan_hesapla({1: 5, 2: 5, 3: 5, 4: 5}, kritiklik=1, kart_var=True)
    assert h["puan"] == round(100 * 0.45 * 0.25 * 0.6) and h["seviye"] == "yesil"


def test_iki_kaynaktan_oruntuler(con):
    h = risk.risk_haritasi(con, GUNDUZ)
    assert {h[0]["kod"], h[1]["kod"]} == {"DALGA", "ENTEGRASYON"}
    dalga = next(r for r in h if r["kod"] == "DALGA")
    assert dalga["kaynak"] == "Usta" and dalga["en_cok_cozen"]["ad"] == "Elif Kaya"
    sorter = next(r for r in h if r["ad"] == "Sorter arızası")
    assert sorter["kaynak"] == veri_uret.BAKIM_KAYNAGI and sorter["seviye"] == "kirmizi"
    assert sorter["en_cok_cozen"]["ad"] == "Kemal Yılmaz" and sorter["beyan_sayisi"] > sorter["gercek_sayisi"]


def test_ya_giderse_riski_dusurmez(con):
    for p in con.execute("SELECT id FROM kisi").fetchall():
        y = risk.ya_giderse(con, p["id"], 21, simdi=GUNDUZ)
        assert all(e["puan_sonra"] >= e["puan_once"] for e in y["etkilenen"])
    y = risk.ya_giderse(con, pid(con, "Elif Kaya"), 21, 40, GUNDUZ)
    assert "Sipariş dalgası açılmıyor" in y["yedeksiz_kalan"]
    assert y["tl_etkisi"] == y["ek_dakika"] * 40


def test_plan_butceyi_asmaz_ve_riski_dusurur(con):
    for b in (0, 10, 37, 60, 150):
        for y in ("kural", "optimum"):
            p = risk.egitim_plani(con, b, y, simdi=GUNDUZ)
            assert p["kullanilan_saat"] <= b
            assert p["ozet_sonra"]["ortalama"] <= p["ozet_once"]["ortalama"]
            assert all(s["ogreten_id"] != s["ogrenen_id"] for s in p["satirlar"])


def test_optimum_kuraldan_kotu_degil(con):
    for b in range(5, 130, 7):
        k = risk.egitim_plani(con, b, simdi=GUNDUZ)["karsilastirma"]
        assert k["optimum"]["amac_puani"] >= k["kural"]["amac_puani"] - 0.05


def test_altmis_saatle_kirmizi_kalmaz(con):
    assert risk.egitim_plani(con, 60, simdi=GUNDUZ)["ozet_sonra"]["kirmizi"] == 0


def test_tek_kisiye_kalanlar(con):
    t = risk.tek_kisiye_kalanlar(con, 7, GUNDUZ)
    assert any(k["ad"] == "Sorter arızası" for k in t["konular"])
