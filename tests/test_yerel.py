"""Kendi verinle yerel kurulum (emanet.yerel)."""
import pytest

from emanet import ogrenme, usta, yerel
from emanet.db import baglan, meta_al


@pytest.fixture(scope="module")
def ornek(tmp_path_factory):
    d = tmp_path_factory.mktemp("yerel")
    yol = d / "ornek.csv"
    assert yerel.ornek_uret(yol) > 500
    return d, yol.read_text(encoding="utf-8-sig")


def test_esnek_sutun_adlari_okunur(ornek):
    _, metin = ornek
    satirlar, hatalar = yerel.oku(metin)
    s = satirlar[0]
    assert not hatalar and s["metin"] and s["konu"] and s["birim"] and s["cozen"] and s["sure_dk"]
    assert any(x["cozum_notu"] and "\n" in x["cozum_notu"] for x in satirlar)


def test_eksik_sutun_ve_az_veri_anlasilir_hata_verir():
    with pytest.raises(ValueError, match="Eksik sütun: metin"):
        yerel.oku("tarih;konu;birim;cozen\n2026-01-01;a;b;c")
    az = "tarih;açıklama;kategori;grup;çözen\n" + "\n".join(f"2026-01-0{i % 9 + 1} 10:00;yazıcı basmıyor;Yazıcı;BT;Ali" for i in range(20))
    with pytest.raises(ValueError, match="En az 50"):
        yerel.usta_yukle(baglan(":memory:"), az)


def test_kurulum_takma_ad_ve_rapor(ornek):
    d, metin = ornek
    s = yerel.kur(d / "yerel.db", metin, takma_ad=True, kaydir=True)
    y = s["yukleme"]
    assert y["cagri"] > 500 and y["konu"] >= 10 and y["takma_ad"]
    assert s["degerlendirme"]["konu"]["model"] > s["degerlendirme"]["konu"]["kural"]
    con = baglan(d / "yerel.db")
    assert meta_al(con, "mod") == "yerel"
    adlar = {r[0] for r in con.execute("SELECT ad FROM kisi")}
    assert all(a.startswith("Kişi ") for a in adlar)
    gercek = set(y["takma_ad"])
    assert not any(g in (r[0] or "") for r in con.execute("SELECT metin FROM cagri") for g in gercek)
    # Usta yerel veriyle çalışır
    o = usta.kategori_oner(con, "Yazıcı çevrimdışı görünüyor, etiket basmıyor")
    assert "yazıcı" in o["oneriler"][0]["ad"].lower()
    assert "Model başarısı" in yerel.rapor(s, d / "yerel.db")


def test_komut_satiri(ornek, capsys):
    d, _ = ornek
    assert yerel.main([str(d / "ornek.csv"), "--db", str(d / "yerel2.db"), "--bugune-kaydir"]) == 0
    assert (d / "yerel2_rapor.md").exists()
    assert yerel.main([str(d / "ornek.csv"), "--db", str(d / "yerel2.db")]) == 0   # kendi kurulumunun üzerine yazar
    from datetime import date
    from emanet import veri_uret
    demo = baglan(d / "demo.db")
    veri_uret.uret(demo, date.today())
    demo.close()
    with pytest.raises(SystemExit):
        yerel.main([str(d / "ornek.csv"), "--db", str(d / "demo.db")])      # demo veritabanı korunur
