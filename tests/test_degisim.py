"""Değişimler: sistem geçişi, yeni personel ve çırak modu, otomasyon sağlığı, ayrılış, Türkçe ekler."""
from datetime import date, datetime, timedelta

import pytest

from emanet import degisim, ogrenme, risk, usta, veri_uret
from emanet import otomasyon as A
from emanet.db import baglan
from emanet.dil import ek, sayi, yuzde

BUGUN = date.today()


@pytest.fixture()
def con(tmp_path):
    c = baglan(tmp_path / "t.db")
    veri_uret.uret(c, BUGUN)
    return c


def pid(con, ad):
    return con.execute("SELECT id FROM kisi WHERE ad=?", (ad,)).fetchone()[0]


def kid(con, kod):
    return con.execute("SELECT id FROM kategori WHERE kod=?", (kod,)).fetchone()[0]


def konu(con, ad):
    return next((r for r in risk.risk_haritasi(con) if r["ad"] == ad), None)


# ---------------------------------------------------------------- Türkçe ekler

def test_turkce_ekler():
    assert [sayi(n, "i") for n in (1, 2, 3, 6, 9, 10, 40)] == ["1'i", "2'yi", "3'ü", "6'yı", "9'u", "10'u", "40'ı"]
    assert [yuzde(x, "ini") for x in (0.67, 0.4, 0.3, 0.5)] == ["%67'sini", "%40'ını", "%30'unu", "%50'sini"]
    assert ek(5, "de") == "te" and ek(6, "e") == "ya" and ek(45, "in") == "in" and yuzde(0.6, "inden") == "%60'ından"


# ---------------------------------------------------------------- sistem geçişi

def test_gecis_eski_konuyu_kapatir_yeniyi_acar(con):
    eski = kid(con, "RAPOR")
    acik_once = con.execute("SELECT COUNT(*) FROM cagri WHERE kategori_id=? AND durum='acik'", (eski,)).fetchone()[0]
    r = degisim.gecis_kaydet(con, "Power BI rapor hatası", BUGUN, eski, [pid(con, "Emre Çelik")])
    assert konu(con, "Rapor ve küp yenilenmiyor") is None
    yeni = konu(con, "Power BI rapor hatası")
    assert yeni and yeni["yeni_konu"] and yeni["gecici"]
    assert r["tasinan_cagri"] >= acik_once
    assert r["devre_disi_receteler"]          # eski konunun reçetesi yeni sistemde çalışmaz
    # Geçmişteki bir tarihte eski konu hâlâ haritada, yenisi yok
    gecmis = {x["ad"] for x in risk.risk_haritasi(con, datetime.now() - timedelta(days=5))}
    assert "Rapor ve küp yenilenmiyor" in gecmis and "Power BI rapor hatası" not in gecmis


def test_yeni_konuda_gecici_puan_beyana_dayanir(con):
    eski = kid(con, "RAPOR")
    degisim.gecis_kaydet(con, "Yeni rapor A", BUGUN, eski, [])
    bos = konu(con, "Yeni rapor A")
    assert bos["gecici"] and bos["yetkin_sayisi"] == 0
    con2 = con
    degisim.gecis_kaydet(con2, "Yeni sistem B", BUGUN, kid(con, "BARKOD"), [pid(con, "Elif Kaya"), pid(con, "Derya Güneş")])
    b = konu(con, "Yeni sistem B")
    assert b["gecici"] and b["yetkin_sayisi"] == 2 and b["puan"] < bos["puan"]


def test_gecis_simule_erken_uyari_ve_gecis_adaylari(con):
    degisim.gecis_simule_et(con)
    g = degisim.gecisler(con)[0]
    assert g["yeni_konu"]["erken_uyari"] and not g["gecici"]
    assert g["cozenler"][0]["ad"] == "Emre Çelik" and g["cozenler"][0]["pay"] >= 0.6
    assert any("tek kişide" in n for n in g["nedenler"])
    assert g["gecis_adaylari"] and g["yapilacak"]
    with pytest.raises(ValueError):
        degisim.gecis_simule_et(con)


def test_planda_gecis_egitimi_yari_sure(con):
    degisim.gecis_simule_et(con)
    p = risk.egitim_plani(con, 80)
    satir = [s for s in p["satirlar"] if s["tur"] == "gecis"]
    assert satir
    k = con.execute("SELECT ogrenme_saati FROM kategori WHERE id=?", (satir[0]["kategori_id"],)).fetchone()[0]
    assert satir[0]["saat"] == max(1, -(-k // 2))


def test_model_yeni_konuyu_eski_cagrilardan_tanir(con):
    degisim.gecis_kaydet(con, "Power BI rapor hatası", BUGUN, kid(con, "RAPOR"), [])
    o = usta.kategori_oner(con, "Günlük verimlilik raporu bu sabah gelmedi")
    assert o["oneriler"][0]["ad"] == "Power BI rapor hatası"
    assert all(x["kod"] != "RAPOR" for x in o["oneriler"])
    with pytest.raises(ValueError, match="kapandı"):
        usta.yonlendir(con, kid(con, "RAPOR"))


def test_gecis_hatalari(con):
    with pytest.raises(ValueError):
        degisim.gecis_kaydet(con, "x", BUGUN, kid(con, "RAPOR"))
    with pytest.raises(ValueError):
        degisim.gecis_kaydet(con, "Öncülsüz sistem", BUGUN)           # birim yok
    degisim.gecis_kaydet(con, "Bir", BUGUN, kid(con, "RAPOR"))
    with pytest.raises(ValueError, match="zaten"):
        degisim.gecis_kaydet(con, "İki", BUGUN, kid(con, "RAPOR"))


# ---------------------------------------------------------------- yeni personel ve çırak modu

def test_cirak_modu_yeni_personele_kolay_cagri_verir(con):
    b = con.execute("SELECT id FROM birim WHERE ad='Depo Sistemleri'").fetchone()[0]
    d = degisim.kisi_ekle(con, "Deneme Kişi", b, "gunduz")
    yeni = d["kisi"]["id"]
    gunduz = datetime.now().replace(hour=10)
    a = usta.yonlendir(con, kid(con, "BARKOD"), gunduz, "gunduz", "Barkod okunmuyor", "Depolama", aciliyet=2)
    assert a["kisi_id"] == yeni and a["cirak"]["usta"]
    # Acil çağrı ya da kritik konu çırağa gitmez
    assert usta.yonlendir(con, kid(con, "BARKOD"), gunduz, "gunduz", "Barkod okunmuyor", "", aciliyet=3)["kisi_id"] != yeni
    assert usta.yonlendir(con, kid(con, "DALGA"), gunduz, "gunduz", "Dalga açılmıyor", "", aciliyet=1)["kisi_id"] != yeni
    # Çırak modu kapalıysa
    con.execute("INSERT OR REPLACE INTO meta(anahtar,deger) VALUES('cirak_modu','0')")
    assert usta.yonlendir(con, kid(con, "BARKOD"), gunduz, "gunduz", "Barkod okunmuyor", "", aciliyet=2)["kisi_id"] != yeni


def test_yeni_personel_yedek_sayilmaz_ve_ise_alisma(con):
    once = konu(con, "Barkod okunmuyor")["yetkin_sayisi"]
    r = degisim.yeni_personel_simule_et(con)
    assert r["kisi"]["gun"] == 35 and r["cagri"] > 0
    assert any(k["durum"] != "baslamadi" for k in r["konular"])
    assert all(k["esik"] >= 2 for k in r["konular"])
    assert konu(con, "Barkod okunmuyor")["yetkin_sayisi"] >= once - 1
    assert degisim.yeni_personel(con)[0]["kisi"]["ad"] == "Can Arslan"


def test_kisi_ayrildi(con):
    elif_ = pid(con, "Elif Kaya")
    r = degisim.kisi_ayrildi(con, elif_)
    assert r["kisi"]["ad"] == "Elif Kaya"
    assert con.execute("SELECT COUNT(*) FROM cagri WHERE durum='acik' AND atanan_kisi_id=?", (elif_,)).fetchone()[0] == 0
    assert all(r2["en_cok_cozen"] is None or r2["en_cok_cozen"]["ad"] != "Elif Kaya" for r2 in risk.risk_haritasi(con))
    with pytest.raises(ValueError):
        degisim.kisi_ayrildi(con, elif_)


# ---------------------------------------------------------------- otomasyon sağlığı

def test_otomasyon_bozulunca_askiya_alinir_ve_risk_artar(con):
    once = konu(con, "Etiket yazıcısı yazdırmıyor")
    assert once["otomasyon_payi"] > 0
    r = A.senaryo(con, "bozulma")
    assert r["saglik"]["durum"] == "askida"
    sonra = konu(con, "Etiket yazıcısı yazdırmıyor")
    assert sonra["otomasyon_payi"] == 0 and sonra["puan"] > once["puan"]
    assert any("askıya" in n for n in sonra["nedenler"])
    # Askıdaki reçete yeni çağrıda çalışmaz
    assert A.eslesen_recete(con, "Yazıcı çevrimdışı, basmıyor", kid(con, "ETIKET_YAZICI")) is None
    A.yeniden_devreye_al(con, "YAZICI")
    assert A.saglik(con, "YAZICI")["durum"] == "yetersiz_veri"
    assert konu(con, "Etiket yazıcısı yazdırmıyor")["otomasyon_payi"] > 0


def test_saglik_az_denemede_beklenen_basariyi_kullanir(con):
    s = A.saglik(con, "YAZICI")
    assert s["durum"] == "yetersiz_veri" and s["kullanilan"] == s["beklenen"]


def test_eski_veritabani_gocu(tmp_path):
    import sqlite3
    yol = tmp_path / "eski.db"
    c = sqlite3.connect(yol)
    c.execute("CREATE TABLE kisi (id INTEGER PRIMARY KEY, ad TEXT NOT NULL, birim_id INTEGER NOT NULL, rol TEXT NOT NULL, "
              "vardiya TEXT NOT NULL, aktif INTEGER NOT NULL DEFAULT 1)")
    c.commit()
    c.close()
    con = baglan(yol)
    sutun = {r[1] for r in con.execute("PRAGMA table_info(kisi)")}
    assert {"ise_giris", "cikis"} <= sutun


# ---------------------------------------------------------------- denetimden çıkan eklemeler

def test_otomasyon_sahibi_ya_giderse_ve_ayrilista(con):
    from emanet import takip
    deniz = pid(con, "Deniz Aksoy")
    y = risk.ya_giderse(con, deniz)
    assert {o["kod"] for o in y["otomasyonlar"]} >= {"KURULUM", "SIFRE"}
    assert takip.devir_dosyasi(con, deniz)["otomasyonlar"]
    assert "Bakımını yaptığı otomasyonlar" in takip.devir_dosyasi(con, deniz)["markdown"]
    r = degisim.kisi_ayrildi(con, deniz)
    assert "Yazılım kurulumu" in r["sahipsiz_receteler"]
    assert any("sahibi yok" in d["metin"] for d in takip.dikkat(con))


def test_dikkat_listesi(con):
    from emanet import takip
    d = takip.dikkat(con)
    assert d and d[0]["seviye"] == "kirmizi" and all(x["sayfa"] for x in d)
    degisim.gecis_simule_et(con)
    A.senaryo(con, "bozulma")
    metinler = " ".join(x["metin"] for x in takip.dikkat(con))
    assert "askıda" in metinler and "tek kişide" in metinler and "eski sisteme bağlı" in metinler


def test_veri_tazeligi_eski_dokumu_yakalar(con):
    t = {x["kaynak"]: x for x in risk.veri_tazeligi(con)}
    assert not t["Usta"]["eski"]
    ileri = datetime.now() + timedelta(days=30)
    assert all(x["eski"] for x in risk.veri_tazeligi(con, ileri))


def test_yersiz_cagri_farkli_yerlerdeki_cagrilarla_birlesmez(con):
    kat = kid(con, "ETIKET_YAZICI")
    kisiler = [r[0] for r in con.execute("SELECT ad FROM hesap WHERE durum='aktif' LIMIT 4")]
    for yer, k in zip(["A koridoru", "iade alanı", "ofis katı"], kisiler):
        usta.cagri_ac(con, f"{yer} yazıcısında ribon bitti, soluk basıyor", "Depolama", 2, kategori_id=kat, acan_kisi=k)
    c = usta.cagri_ac(con, "Yazıcıda ribon bitti galiba, soluk basıyor", "Depolama", 2, kategori_id=kat, acan_kisi=kisiler[3])
    assert not c["toplu"]
