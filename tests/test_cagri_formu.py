"""İki aşamalı çağrı formu: öncelik hesabı, cevap doğrulama, aynı sorun uyarısı, kendin çözdü sayacı."""
import json

import pytest

from emanet import cagri_formu as F
from emanet import usta
from emanet.db import baglan
from emanet.veri_uret import uret


@pytest.fixture(scope="module")
def con():
    c = baglan(":memory:")
    uret(c)
    return c


def kid(con, kod):
    return con.execute("SELECT id FROM kategori WHERE kod=?", (kod,)).fetchone()[0]


def test_oncelik_matrisi():
    assert F.aciliyet_hesapla("durdu", "alan")["seviye"] == 3
    assert F.aciliyet_hesapla("durdu", "ben")["seviye"] == 2
    assert F.aciliyet_hesapla("yok", "ben")["seviye"] == 1
    # Sevkiyat bekliyorsa tek kişilik durma da yüksek; iş etkilenmiyorsa sevkiyat öne almaz
    assert F.aciliyet_hesapla("durdu", "ben", sevkiyat=True)["seviye"] == 3
    assert F.aciliyet_hesapla("yok", "ben", sevkiyat=True)["seviye"] == 1
    # Talep: iş durdu sorusu yok; en fazla orta
    assert F.aciliyet_hesapla(talep=True, ne_zaman="bugun")["seviye"] == 2
    assert "→ Yüksek" in F.aciliyet_hesapla("durdu", "alan")["gerekce"]


def test_cevap_dogrulama():
    # Numara tek biçime gelir; envanterde kayıtlıysa model oradan dolar
    assert F.cevaplari_dogrula("ETIKET_YAZICI", {"cihaz": " yz 7 ", "bilinmeyen": "x"}) == {"cihaz": "YZ-07", "model": "Zebra ZD621"}
    with pytest.raises(ValueError):   # yazıcı numarası gerekli
        F.cevaplari_dogrula("ETIKET_YAZICI", {"belirti": "Kâğıt sıkıştı"})
    assert F.cevaplari_dogrula("ETIKET_YAZICI", {}, zorunlu_denetle=False) == {}
    assert F.cevaplari_dogrula("ETIKET_YAZICI", {"cihaz": "YZ-99", "model": "Bilmiyorum"})["model"] == "Bilmiyorum"
    with pytest.raises(ValueError):
        F.cevaplari_dogrula("ETIKET_YAZICI", {"belirti": "uydurma seçenek"})
    assert len(F.cevaplari_dogrula("DALGA", {"hata": "x" * 999})["hata"]) == 200
    # Sorusu tanımlanmamış konu genel soruları alır
    assert F.sorular("YENI_SISTEM") == F.GENEL_SORULAR


def test_form_ve_ayni_sorun_uyarisi(con):
    k = kid(con, "DALGA")
    f = F.form(con, k)
    assert [s["kod"] for s in f["sorular"]] == ["dalga", "hata"] and not f["talep"]
    assert F.form(con, kid(con, "YETKI_TALEBI"))["talep"]
    m = "Sipariş dalgası açılmıyor, toplama görevleri düşmedi"
    c = usta.cagri_ac(con, m, kategori_id=k, aciliyet=3, yer="A koridoru",
                      ek_bilgi=F.ek_bilgi_json("DALGA", {"dalga": "D-118"}, "durdu", "alan", False, None,
                                               F.aciliyet_hesapla("durdu", "alan")))
    assert c["yer"] == "A koridoru" and c["ek"]["cevaplar"] == [{"soru": "Dalga ya da sipariş numarası", "cevap": "D-118"}]
    assert any(b["id"] == c["id"] for b in F.benzer_acik(con, k, "a koridoru"))     # yazılış farkı önemsiz
    assert not any(b["id"] == c["id"] for b in F.benzer_acik(con, k, "B koridoru"))  # başka yer başka sorun


def test_toplu_ariza_formdaki_yeri_kullanir(con):
    """Metinde yer geçmese de formda yazılan yer üzerinden aynı yerdeki çağrılar birleşir."""
    k = kid(con, "BARKOD")
    son = None
    for i in range(3):
        son = usta.cagri_ac(con, "Okuyucu barkodu okumuyor", kategori_id=k, aciliyet=2, yer="İade alanı",
                            acan_kisi=f"Kişi {i}")
    assert son["toplu"] and son["toplu"]["yer"] == "iade alanı" and son["toplu"]["cagri_sayisi"] == 3


def test_kendin_cozdu_sayaci(con):
    k = kid(con, "ETIKET_YAZICI")
    assert F.form(con, k)["kendin_dene"]
    assert F.kendin_cozdu(con, k) == 1 and F.kendin_cozdu(con, k) == 2
    assert F.form(con, k)["kendin_cozdu"] == 2
    assert json.loads(F.ek_bilgi_json("ETIKET_YAZICI", {}, "yok", "ben", False, None,
                                      F.aciliyet_hesapla("yok", "ben")))["etki"] == "İşimi etkilemiyor"


def test_cihaz_no_bicimi():
    assert [F.cihaz_no(x) for x in ["yz 7", "YZ07", "yz-007", "el14", "EL-014", "  "]] == \
        ["YZ-07", "YZ-07", "YZ-07", "EL-014", "EL-014", None]


def test_tekrarlayan_cihaz_izlenir(con):
    """Demo verisinde YZ-07 son ayda sık arızalanır; geçmiş ve Bugün uyarısı numarayla gelir."""
    t = {c["no"]: c for c in F.tekrarlayan_cihazlar(con)}
    assert "YZ-07" in t and t["YZ-07"]["cagri"] >= F.TEKRAR_ESIK and t["YZ-07"]["model"]
    k = kid(con, "ETIKET_YAZICI")
    c = usta.cagri_ac(con, "Yazıcı basmıyor", kategori_id=k, aciliyet=2, cihaz="YZ-07")
    d = usta.cagri_detay(con, c["id"])
    assert d["cihaz_gecmisi"]["tekrarlayan"] and all(x["id"] != c["id"] for x in d["cihaz_gecmisi"]["cagrilar"])
    from emanet import takip
    assert any(x["sayfa"] == "cihaz" and "YZ-07" in x["metin"] for x in takip.dikkat(con))
