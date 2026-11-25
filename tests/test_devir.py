"""Devir süreci: aşamalar gerçek çağrılarla ilerler, çıkışa yetişme hesabı, kontrol listesi, tutanak."""
from datetime import date, datetime

import pytest

from emanet import db, devir, usta, veri_uret

BUGUN = date(2026, 11, 25)
S = datetime(2026, 11, 25, 12)


@pytest.fixture()
def con():
    c = db.baglan(":memory:")
    veri_uret.uret(c, BUGUN)
    return c


def kid(con, ad):
    return con.execute("SELECT id FROM kisi WHERE ad=?", (ad,)).fetchone()[0]


def erp(d):
    return next(k for k in d["konular"] if k["ad"] == "ERP entegrasyon hatası")


def test_baslat_devralan_onerir_ve_tekrar_acmaz(con):
    d = devir.baslat(con, kid(con, "Murat Özkan"), "2026-12-16", simdi=S)
    assert d["gun_kaldi"] == 21 and d["konular"]
    k = erp(d)
    assert k["devralan"] == "Emre Çelik" and k["tazeleme"] and k["asama"] == 0
    assert devir.baslat(con, kid(con, "Murat Özkan"), "2026-12-30", simdi=S)["id"] == d["id"]
    with pytest.raises(ValueError):
        devir.baslat(con, kid(con, "Elif Kaya"), "2026-11-20", simdi=S)


def test_asamalar_cagriyla_ilerler(con):
    d = devir.baslat(con, kid(con, "Murat Özkan"), "2026-12-16", simdi=S)
    devir.konu_guncelle(con, d["id"], 11, izledi=True)
    assert erp(devir.durum(con, d["id"], S))["asama"] == 1
    emre = kid(con, "Emre Çelik")

    def cagri(n):
        for i in range(n):
            con.execute("INSERT INTO cagri(metin,acan_birim,aciliyet,kategori_id,durum,atanan_kisi_id,cozen_kisi_id,"
                        "acilis,kapanis,sure_dk,vardiya) VALUES('x','Depolama',2,11,'kapali',?,?,?,?,60,'aksam')",
                        (emre, emre, f"2026-11-26T1{i}:00", f"2026-11-26T1{i}:50"))
        con.commit()
    cagri(1)
    k = erp(devir.durum(con, d["id"], datetime(2026, 11, 27, 9)))
    assert k["asama"] == 2 and k["devirden_sonra"] == 1
    cagri(2)
    assert erp(devir.durum(con, d["id"], datetime(2026, 11, 27, 9)))["asama"] == 3


def test_yetismezse_onerilen_haftalik_saat(con):
    d = devir.baslat(con, kid(con, "Murat Özkan"), "2026-12-16", simdi=S)
    # Ortak kartla 4 saat yetişiyor; haftada 1 saatte yetişmez ve sistem yetecek saati önerir
    devir.haftalik_sinir_ayarla(con, d["id"], 1.0)
    d = devir.durum(con, d["id"], S)
    assert d["uyarilar"][0]["seviye"] == "kirmizi" and d["onerilen_sinir"] > d["haftalik_sinir"]
    devir.haftalik_sinir_ayarla(con, d["id"], d["onerilen_sinir"])
    assert all(u["seviye"] != "kirmizi" for u in devir.durum(con, d["id"], S)["uyarilar"])


def test_kontrol_listesi_ve_sahiplik(con):
    d = devir.baslat(con, kid(con, "Deniz Aksoy"), "2026-12-30", simdi=S)
    sahip = [m for m in d["maddeler"] if m["kod"].startswith("sahip:")]
    assert sahip, "Deniz otomatik çözümlerin sahibi"
    yeni = next(a for a in d["adaylar"])
    devir.sahip_degistir(con, d["id"], sahip[0]["recete"], yeni["id"])
    d2 = devir.durum(con, d["id"], S)
    m = next(x for x in d2["maddeler"] if x["kod"] == sahip[0]["kod"])
    assert m["yapildi"] and yeni["ad"] in m["metin"]
    devir.madde_isaretle(con, d["id"], "hesap", True)
    with pytest.raises(ValueError):
        devir.madde_isaretle(con, d["id"], "acik", True)      # kendiliğinden ölçülen elle işaretlenmez
    devir.gorusme_kaydet(con, d["id"], 0, "Yazıcı kuyruğu sunucuda takılır")
    g = devir.durum(con, d["id"], S)["gorusme"][0]
    assert g["cevap"].startswith("Yazıcı")


def test_devralan_kritik_konuda_yaninda_ogrenir(con):
    # Devir yokken kritik konuda yanında öğrenme kapalı; devir başlayınca devralan aday olur
    from emanet import devir as dv
    assert not dv.devralanlar(con, 11)
    d = devir.baslat(con, kid(con, "Murat Özkan"), "2026-12-16", simdi=S)
    assert kid(con, "Emre Çelik") in dv.devralanlar(con, 11)
    devir.kapat(con, d["id"])
    assert not dv.devralanlar(con, 11)


def test_tutanak_ve_devralan_birim_kurali(con):
    d = devir.baslat(con, kid(con, "Murat Özkan"), "2026-12-16", simdi=S)
    with pytest.raises(ValueError):
        devir.konu_guncelle(con, d["id"], 11, devralan_id=kid(con, "Kemal Yılmaz"))   # başka birim
    md = devir.tutanak(con, d["id"], S)
    assert md.startswith("# Devir tutanağı: Murat Özkan") and "| Devralan | Emre Çelik |" in md and "## Onay" in md


def test_karti_devralan_yazar_ayrilan_duzeltir(con):
    """Kart yoksa ve devralan seçiliyse: taslak devralanda, düzeltme ikisinde ve taslaktan sonra; öğretme kısalır."""
    d = devir.baslat(con, kid(con, "Murat Özkan"), "2026-12-16", simdi=S)
    os_ = d["takvim"]["oturumlar"]
    taslak = [o for o in os_ if o["tur"] == "kart_taslak"]
    duzelt = [o for o in os_ if o["tur"] == "kart_duzelt"]
    if not taslak:
        pytest.skip("Bu veride kartı ayrılanın yazacağı konu yok")
    assert taslak[0]["ogreten"] != "Murat Özkan" and taslak[0]["ogrenen_id"] is None
    assert duzelt and duzelt[0]["ogreten"] == "Murat Özkan" and duzelt[0]["ogrenen"] == taslak[0]["ogreten"]
    assert min(o["tarih"] for o in duzelt) > max(o["tarih"] for o in taslak)
    ogretme = [o for o in os_ if o["tur"] in ("tazeleme", "egitim") and o["kategori_id"] == taslak[0]["kategori_id"]]
    assert all("Vaka #" not in m for o in ogretme for m in o["gundem"])     # vakalar taslakta geçildi
    assert any("taslağı yazar" in m["metin"] for m in d["maddeler"])


def test_devralanin_sinirini_ayri_ayarlanir(con):
    d = devir.baslat(con, kid(con, "Murat Özkan"), "2026-12-16", simdi=S)
    devir.haftalik_sinir_ayarla(con, d["id"], 6, 1)            # ayrılan bol, devralan haftada 1 saat
    d = devir.durum(con, d["id"], S)
    if not d["takvim"]:
        pytest.skip("Kalan oturum yok")
    assert d["devralan_sinir"] == 1
    hafta = {}
    for o in d["takvim"]["oturumlar"]:
        if o["ogrenen_id"] or o["tur"] == "kart_taslak":
            dv = o["ogrenen_id"] or o["ogreten_id"]
            hafta[(dv, o["hafta"])] = hafta.get((dv, o["hafta"]), 0) + o["saat"]
    assert max(hafta.values()) <= 1
    # Darboğaz devralansa öneri devralanın saatini artırır, ayrılanınkini değil
    if d["uyarilar"] and d["uyarilar"][0]["seviye"] == "kirmizi":
        assert d["onerilen_devralan_sinir"] and not d["onerilen_sinir"]
    with pytest.raises(ValueError):
        devir.haftalik_sinir_ayarla(con, d["id"], devralan_saat=0.5)
    devir.haftalik_sinir_ayarla(con, d["id"], 4, 4)
