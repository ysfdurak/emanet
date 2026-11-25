"""Eğitim içeriği (eski çağrılardan) ve kullanıcının girdiği konu süreleri."""
from datetime import date, datetime

import pytest

from emanet import db, egitim, risk, takip, takvim, veri_uret

BUGUN = date(2026, 11, 25)
SIMDI = datetime(2026, 11, 25, 12)
ERP = 11


@pytest.fixture()
def con():
    c = db.baglan(":memory:")
    veri_uret.uret(c, BUGUN)
    return c


def test_cozum_yollari_farkli_ve_temsilcili(con):
    y = egitim.cozum_yollari(con, ERP)
    assert len(y) >= 2 and y[0]["adet"] >= y[-1]["adet"]
    assert len({v["adimlar"][0] for v in y}) == len(y)          # her yol ayrı bir ilk adımla başlar
    v = y[0]
    assert v["cagri_id"] and v["belirti"] and len(v["adimlar"]) >= 2
    kat = con.execute("SELECT kategori_id FROM cagri WHERE id=?", (v["cagri_id"],)).fetchone()[0]
    assert kat == ERP


def test_plan_adimlari_gundem_ve_olcut_tasir(con):
    p = egitim.plani_zenginlestir(con, risk.egitim_plani(con, 60, simdi=SIMDI))
    kart = next(s for s in p["satirlar"] if s["tur"] == "kart" and s["kategori_id"] == ERP)
    assert all(m.startswith("Çözüm yolu") for m in kart["gundem"])
    egt = next(s for s in p["satirlar"] if s["tur"] in ("egitim", "tazeleme") and s["kategori_id"] == ERP)
    assert egt["gundem"][0].startswith("Kartı birlikte oku")      # kart aynı planda yazılıyor
    assert any(m.startswith("Vaka #") for m in egt["gundem"])
    assert egt["gundem"][-1].startswith("Birlikte uygulama")
    assert "3 çağrıyı tek başına" in egt["olcut"]


def test_takvim_oturumlari_gundemi_sirayla_paylasir():
    g = ["Kartı oku", "Vaka #1", "Vaka #2", "Birlikte uygulama"]
    parcalar = [takvim.oturum_gundemi(g, i, 6) for i in range(1, 7)]
    assert parcalar[:3] == [["Kartı oku"], ["Vaka #1"], ["Vaka #2"]]
    assert parcalar[3] == ["Birlikte uygulama (1/3)"] and parcalar[5] == ["Birlikte uygulama (3/3)"]
    assert sum(len(x) for x in [takvim.oturum_gundemi(g, i, 2) for i in (1, 2)]) == 4


def _suresiz(con, kid):
    con.execute("UPDATE kategori SET kart_saat=NULL, sure_onay=0 WHERE id=?", (kid,))
    con.commit()


def test_demo_sureleri_uzman_tablosundan(con):
    from emanet import katalog
    assert not con.execute("SELECT COUNT(*) FROM kategori WHERE sure_onay=0 AND emeklilik IS NULL").fetchone()[0]
    kart, ogr, _ = katalog.UZMAN_SURELERI["ERP entegrasyon hatası"]
    r = con.execute("SELECT kart_saat, ogrenme_saati FROM kategori WHERE id=?", (ERP,)).fetchone()
    assert (r[0], r[1]) == (kart, ogr)


def test_sure_kullanicidan_gelir_ve_plani_degistirir(con):
    _suresiz(con, ERP)
    once = risk.egitim_plani(con, 60, simdi=SIMDI)
    erp_kart = next(s for s in once["satirlar"] if s["tur"] == "kart" and s["kategori_id"] == ERP)
    assert erp_kart["sure_tahmini"] and erp_kart["saat"] == risk.KART_YAZMA_SAATI
    egitim.sure_kaydet(con, ERP, 4, 30)
    sonra = risk.egitim_plani(con, 60, simdi=SIMDI)
    k = next(s for s in sonra["satirlar"] if s["tur"] == "kart" and s["kategori_id"] == ERP)
    assert k["saat"] == 4 and not k["sure_tahmini"]
    taz = [s for s in sonra["satirlar"] if s["tur"] == "tazeleme" and s["kategori_id"] == ERP]
    assert all(s["saat"] == 10 for s in taz)                        # 30 / 3, yarım saate yuvarlanır


@pytest.mark.parametrize("kart,ogr", [(0, 5), (1.3, 5), (2, 500)])
def test_gecersiz_sure(con, kart, ogr):
    with pytest.raises(ValueError):
        egitim.sure_kaydet(con, ERP, kart, ogr)


def test_yarim_saatlik_sure_optimizasyonda(con):
    egitim.sure_kaydet(con, ERP, 0.5, 1.5)
    p = risk.egitim_plani(con, 3, simdi=SIMDI)
    assert sum(s["saat"] for s in p["satirlar"]) <= 3
    assert any(s["kategori_id"] == ERP for s in p["satirlar"])


def test_suresi_girilmemis_riskli_konu_uyarisi(con):
    assert not [x for x in takip.dikkat(con) if "eğitim süresi girilmedi" in x["metin"]]
    _suresiz(con, ERP)
    d = [x for x in takip.dikkat(con) if "eğitim süresi girilmedi" in x["metin"]]
    assert d and d[0]["sayfa"] == "plan" and d[0]["veri"] == "sureler"
    for r in risk.risk_haritasi(con):
        if r["seviye"] in ("kirmizi", "sari"):
            egitim.sure_kaydet(con, r["kategori_id"], 2, 8)
    assert not [x for x in takip.dikkat(con) if "eğitim süresi girilmedi" in x["metin"]]


def test_yeni_acilan_konu_suresi_tahmini(con):
    from emanet import degisim
    degisim.gecis_kaydet(con, "Yeni WMS dalga hatası", tarih=BUGUN.isoformat(), eski_kategori_id=9,
                         anahtar_kelimeler="yeni wms, dalga hata")
    r = con.execute("SELECT sure_onay, kart_saat FROM kategori WHERE ad='Yeni WMS dalga hatası'").fetchone()
    assert tuple(r) == (0, None)
