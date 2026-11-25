"""Yanlış yönlendirme: ileri aktarım, top oynatma kuralı (BT müdürü), sistemin kaydı, kural önerisi, ölçü."""
import pytest

from emanet import cagri_formu as F
from emanet import olcum, takip, usta
from emanet import yonlendirme as Y
from emanet.db import baglan
from emanet.veri_uret import uret


@pytest.fixture(scope="module")
def con():
    c = baglan(":memory:")
    uret(c)
    return c


def kid(con, kod):
    return con.execute("SELECT id FROM kategori WHERE kod=?", (kod,)).fetchone()[0]


def test_mudure_cagri_atanmaz(con):
    m = Y.koordinator(con)
    assert m and m["rol"] == "BT Müdürü"
    for kod in ("EL_TERMINALI", "SIFRE_HESAP", "DALGA"):
        assert usta.yonlendir(con, kid(con, kod), alan=None)["kisi_id"] != m["id"]


def test_ileri_aktarim_ve_top_oynatma(con):
    k = kid(con, "EL_TERMINALI")
    c = usta.cagri_ac(con, "Terminal ekranı donuyor", kategori_id=k, aciliyet=2, alan="wms")
    gonderen = c["atanan_kisi_id"]
    d = Y.aktar(con, c["id"], "yanlis_ekip", "donanim", aciklama="Pil şişmiş")
    donanim = {r[0] for r in con.execute("SELECT kisi_id FROM kisi_alan WHERE alan='donanim'")}
    assert d["alan"] == "donanim" and d["atanan_kisi_id"] in donanim and d["atanan_kisi_id"] != gonderen
    assert not d["mudurde"] and d["aktarim_sayisi"] == 1
    with pytest.raises(ValueError):
        Y.aktar(con, c["id"], "yanlis_ekip", "donanim")          # zaten o ekipte
    e = Y.aktar(con, c["id"], "yanlis_ekip", "ag")              # ikinci aktarım → BT müdürü
    assert e["mudurde"] and e["atanan_kisi_id"] == Y.koordinator(con)["id"]
    assert any("kararını bekliyor" in x["metin"] for x in takip.dikkat(con))
    f = Y.mudur_karari(con, c["id"], gonderen)                  # müdürün kararı aktarım sayılmaz
    assert f["atanan_kisi_id"] == gonderen and f["aktarim_sayisi"] == 2 and not f["mudurde"]


def test_bilmiyorum_dogrudan_mudure(con):
    c = usta.cagri_ac(con, "Stok tutmuyor", kategori_id=kid(con, "STOK_FARKI"), aciliyet=1)   # otomasyonu olmayan konu
    assert Y.aktar(con, c["id"], "yanlis_ekip", None)["mudurde"]


def test_yanlis_konu_yeni_konunun_ekibine(con):
    c = usta.cagri_ac(con, "Etiket basmıyor", kategori_id=kid(con, "STOK_FARKI"), aciliyet=1)
    d = Y.aktar(con, c["id"], "yanlis_konu", kategori_id=kid(con, "ETIKET_YAZICI"))
    assert d["kategori_id"] == kid(con, "ETIKET_YAZICI") and d["alan"] == "donanim"


def test_kural_onerisi_ve_karar(con):
    o = Y.kural_onerileri(con)
    assert o and o[0]["belirti"].startswith("Ekran donuyor") and o[0]["onerilen"] == "donanim" and o[0]["aktarilan"] >= 3
    assert F.alan_bul("EL_TERMINALI", {"belirti": o[0]["belirti"]}, kurallar=Y.belirti_kurallari(con))["alan"] == "wms"
    Y.kural_karari(con, o[0]["kod"], o[0]["belirti"], "donanim", True)       # insan onayladı
    assert F.alan_bul("EL_TERMINALI", {"belirti": o[0]["belirti"]}, kurallar=Y.belirti_kurallari(con))["alan"] == "donanim"
    assert not Y.kural_onerileri(con)


def test_yonlendirme_kaybi_cozene_yazilmaz(con):
    z = olcum.cagri_olculeri(con, 90)
    assert z["ozet"]["yonlendirme_kaybi_saat"] > 0 and z["yonlendirme"]["aktarilan"] >= 4
