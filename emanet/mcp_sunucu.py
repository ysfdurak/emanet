"""MCP sunucusu: web arayüzüyle aynı çekirdeği çağıran 19 araç.

Burada iş mantığı yoktur. Her araç usta.py veya risk.py içindeki bir fonksiyonu çağırır
ve sonucunu döndürür. Web API'si (api.py) de aynı fonksiyonları çağırır.

Tek başına çalıştırmak için (stdio):  python -m emanet.mcp_sunucu
Web sunucusuyla birlikte:             /mcp adresinde (bkz. api.py)
"""
from __future__ import annotations

import functools
import threading
from datetime import date

from mcp.server.mcpserver import MCPServer
from mcp.server.mcpserver.exceptions import ToolError

from . import degisim, ogrenme, otomasyon, risk, takip, takvim, usta
from .db import baglan

sunucu = MCPServer(
    name="Emanet",
    instructions=(
        "Emanet + Usta, Yıldız Ev & Yaşam adlı kurgusal deponun verisiyle çalışır. Usta sistemsel destek "
        "çağrılarını (BT, depo sistemleri) geçmiş çağrılardan öğrenen bir modelle yönlendirir ve nasıl "
        "çözüldüğünü gösterir. Emanet, Usta çağrıları ile içe aktarılan bakım dökümünden kişiye bağımlılık "
        "riskini hesaplar. Veriler sentetiktir ve her gece sıfırlanır. "
        "Kişi ve konu numaralarını bilmiyorsan önce risk_haritasi veya cagrilari_listele ile bul. "
        "Risk puanı 0-100 arasıdır: 60 ve üzeri kırmızı, 35-59 sarı, altı yeşil."
    ),
)

_con = None
KILIT = threading.RLock()


def arac(f):
    """Aracı kaydeder; çekirdekten gelen ValueError mesajını olduğu gibi Claude'a iletir."""
    @functools.wraps(f)
    def sarmal(*a, **k):
        try:
            return f(*a, **k)
        except ValueError as e:
            raise ToolError(str(e)) from e
    return sunucu.tool()(sarmal)


def baglanti():
    global _con
    if _con is None:
        _con = baglan()
    return _con


def baglanti_ayarla(con) -> None:
    """Web sunucusu kendi bağlantısını ve kilidini paylaşmak için çağırır."""
    global _con
    _con = con


def _kisi_bul(con, kisi: str) -> int:
    """Kişiyi numarası veya adının bir parçasıyla bulur."""
    if str(kisi).isdigit():
        return int(kisi)
    satirlar = con.execute("SELECT id, ad FROM kisi WHERE aktif=1").fetchall()
    aranan = usta.kucult(str(kisi))
    bulunan = [r for r in satirlar if aranan in usta.kucult(r["ad"])]
    if len(bulunan) != 1:
        raise ValueError(f"'{kisi}' için {len(bulunan)} kişi bulundu. Tam ad veya numara verin: "
                         + ", ".join(r["ad"] for r in (bulunan or satirlar)))
    return bulunan[0]["id"]


def _sade_cagri(c: dict) -> dict:
    return {k: c.get(k) for k in ("id", "metin", "kategori", "birim", "aciliyet", "durum", "atanan",
                                  "cozen", "acilis", "kapanis", "sure_dk", "guven")}


def _konu_bul(con, konu: str) -> int:
    satirlar = con.execute("SELECT id, ad, kod FROM kategori WHERE kaynak='usta'").fetchall()
    aranan = usta.kucult(konu)
    bulunan = [r for r in satirlar if aranan in usta.kucult(r["ad"]) or aranan == r["kod"].lower()]
    if len(bulunan) != 1:
        raise ValueError(f"'{konu}' için {len(bulunan)} konu bulundu. Usta konuları: " + ", ".join(r["ad"] for r in satirlar))
    return bulunan[0]["id"]


def _yol_sade(y: dict) -> dict:
    return dict(
        cozum_kartlari=[dict(baslik=k["baslik"], adimlar=k["adimlar"].split("\n"), yazan=k["yazan"]) for k in y["kartlar"]],
        gecmiste_nasil_cozuldu=[dict(adimlar=g["adimlar"], kac_cagrida=g["kac_kez"], ort_kapanma_dk=g["ort_sure_dk"],
                                     cozenler=g["kisiler"]) for g in y["yollar"]],
        bakilan_benzer_cagri=y["bakilan"], notsuz_cagri=y["notsuz"])


@arac
def cagri_ac(metin: str, acan_birim: str = "Depolama", aciliyet: int = 2, vardiya: str | None = None,
             konu: str | None = None, acan_kisi: str | None = None) -> dict:
    """Sistemsel bir destek çağrısı (BT veya depo sistemi) açar. Makine öğrenmesi modeli konuyu tahmin eder,
    vardiyada olan en uygun kişiye atar ve geçmişte nasıl çözüldüğünü döndürür.

    Model konudan emin değilse hata döner ve aday konuları listeler; o zaman 'konu' parametresiyle tekrar çağır.
    Teknik arızalar (sorter, konveyör, forklift...) Usta'nın kapsamında değildir.
    aciliyet: 1 düşük, 2 orta, 3 yüksek. vardiya: gunduz | aksam | gece (boşsa o anki saat). Demo verisine yazar.
    """
    with KILIT:
        con = baglanti()
        kid = _konu_bul(con, konu) if konu else None
        if kid is None:
            o = usta.kategori_oner(con, metin)
            if o["kapsam_disi"]:
                raise ValueError(f"Bu bir teknik arıza gibi görünüyor ({o['kapsam_disi']['ad']}). Usta yalnızca sistemsel "
                                 f"çağrılara bakar; bakım sistemine bildirilmeli.")
            if o["soru_gerekli"]:
                raise ValueError("Konu belirsiz. Adaylar: " + ", ".join(f"{x['ad']} (%{round(x['puan'] * 100)})"
                                 for x in o["oneriler"]) + ". 'konu' parametresiyle yeniden çağır.")
        c = usta.cagri_ac(con, metin, acan_birim, aciliyet, kid, vardiya=vardiya, acan_kisi=acan_kisi)
    o = c.get("otomasyon")
    return dict(otomasyon=(dict(recete=o["recete"], durum=o["durum"], son_adim=o["gunluk"][-1]["metin"],
                                bekleyen_mesajlar=[dict(id=m["id"], kime=m["kime"], metin=m["metin"], secenekler=m["secenekler"])
                                                   for m in o["mesajlar"] if m["cevap"] is None and m["tur"] in ("soru", "onay")])
                           if o else None),
                toplu_ariza=c.get("toplu"),cagri=_sade_cagri(c), konu_guveni=c["oneri"]["guven"], belirleyici_sozcukler=c["oneri"]["belirleyici"],
                atama=dict(kisi=c["atama"]["ad"], neden=c["atama"]["neden"], uzman_notu=c["atama"]["uzman_notu"],
                           model_siralamasi=c["atama"]["siralama"]),
                yol=_yol_sade(c["yol"]))


@arac
def cagrilari_listele(durum: str = "acik", birim: str | None = None, kisi: str | None = None,
                      limit: int = 20) -> list[dict]:
    """Usta çağrılarını listeler. durum: acik | kapali | hepsi. birim ve kisi ad ile verilebilir."""
    with KILIT:
        con = baglanti()
        birim_id = None
        if birim:
            r = con.execute("SELECT id FROM birim WHERE lower(ad) LIKE ?", (f"%{birim.lower()}%",)).fetchone()
            birim_id = r["id"] if r else -1
        kisi_id = _kisi_bul(con, kisi) if kisi else None
        return [_sade_cagri(c) for c in usta.cagrilari_listele(
            con, durum if durum in ("acik", "kapali") else None, birim_id, kisi_id, limit=limit)]


@arac
def nasil_cozuldu(sorun: str) -> dict:
    """Bir sorun metnine en benzer geçmiş çağrıların nasıl çözüldüğünü gruplar: hangi adımlar, kaç çağrıda,
    ortalama kaç dakikada, kimler çözmüş. Varsa yazılı çözüm kartlarını da verir."""
    with KILIT:
        con = baglanti()
        o = usta.kategori_oner(con, sorun)
        kid = None if o["soru_gerekli"] else o["oneriler"][0]["kategori_id"]
        y = usta.yol_goster(con, sorun, kid)
    return dict(tahmini_konu=o["oneriler"][0]["ad"], konu_guveni=o["guven"], **_yol_sade(y),
                benzer_cagrilar=[dict(metin=c["metin"], cozen=c["cozen"], sure_dk=c["sure_dk"], benzerlik=c["benzerlik"])
                                 for c in y["cagrilar"]])


@arac
def cagriyi_kapat(cagri_id: int, cozum_notu: str, karta_donustur: bool = False, kok_neden: str | None = None) -> dict:
    """Açık bir Usta çağrısını kapatır. cozum_notu: nasıl çözüldü, her adım ayrı satırda. Not, modelin
    "nasıl çözüldü" hafızasına girer. karta_donustur=True ise konunun yazılı çözüm kartı da olur."""
    with KILIT:
        c = usta.cagri_kapat(baglanti(), cagri_id, cozum_notu=cozum_notu, karta_donustur=karta_donustur, kok_neden=kok_neden)
    return dict(cagri=_sade_cagri(c), kart_id=c["kart_id"])


@arac
def model_basarimi() -> dict:
    """Usta'nın makine öğrenmesi modellerinin test başarısı ve eski kural tabanlı yöntemle karşılaştırması."""
    with KILIT:
        con = baglanti()
        return dict(egitim=ogrenme.bilgi(con), test=ogrenme.degerlendir(con))


@arac
def otomasyon_durumu() -> dict:
    """Otomasyonun özeti, cevap bekleyen Teams mesajları (soru, onay, kapanış teyidi) ve son çalışmalar."""
    with KILIT:
        con = baglanti()
        return dict(ozet=otomasyon.ozet(con),
                    bekleyen_mesajlar=[dict(id=m["id"], kime=m["kime"], rol=m["rol"], tur=m["tur"], metin=m["metin"],
                                            secenekler=m["secenekler"], serbest_metin=bool(m["serbest"]))
                                       for m in otomasyon.mesajlar(con, bekleyen=True, limit=20)],
                    son_calismalar=[dict(id=o["id"], recete=o["recete"], kisi=o["kisi"], durum=o["durum"],
                                         cagri_id=o["cagri_id"], son=o["gunluk"][-1]["metin"] if o["gunluk"] else None)
                                    for o in otomasyon.son_calismalar(con, 10)])


@arac
def mesaja_cevap_ver(mesaj_id: int, cevap: str) -> dict:
    """Bekleyen bir Teams mesajına (talep edenin ya da yöneticinin yerine) cevap verir; otomasyon kaldığı
    yerden devam eder. cevap seçeneklerden biri olmalı (serbest metin kabul eden sorularda en az 3 harf)."""
    with KILIT:
        r = otomasyon.cevapla(baglanti(), mesaj_id, cevap)
    return dict(durum=r.get("durum"), son_adimlar=[g["metin"] for g in r.get("gunluk", [])[-4:]])


@arac
def otomasyon_potansiyeli() -> dict:
    """Son 180 günün çağrılarına reçeteler uygulansaydı ayda kaç çağrı ve kaç saat insansız kapanırdı;
    ayrıca sık tekrar eden çözüm notlarından reçete adayları."""
    with KILIT:
        con = baglanti()
        return dict(potansiyel=otomasyon.potansiyel(con),
                    recete_adaylari=[{k: a[k] for k in ("kategori", "adimlar", "tekrar", "ayda", "tahmini_saat_ay",
                                                         "konuda_recete_var")} for a in otomasyon.recete_adaylari(con)[:8]])


@arac
def izin_kontrolu(kisi: str, baslangic: str, bitis: str) -> dict:
    """İzin talebi onaylanmadan önce: kişi (ad veya numara) bu tarihlerde (YYYY-AA-GG) yoksa hangi konular
    yedeksiz ya da tek kişiye kalır, çakışan izinler, varsa daha uygun bir tarih. Kaydetmez."""
    with KILIT:
        con = baglanti()
        r = takip.izin_kontrol(con, _kisi_bul(con, kisi), baslangic, bitis)
    return {k: r[k] for k in ("kisi", "baslangic", "bitis", "karar", "mesaj", "cakisan_izinler", "alternatif")} | dict(
        konular=[{k: x[k] for k in ("ad", "durum", "kalan", "kritiklik")} for x in r["konular"]])


@arac
def devir_dosyasi(kisi: str) -> dict:
    """Bir kişi ayrılırken devredilmesi gerekenler: kişiye bağlı konular, çözüm yolları, açık işleri,
    önerilen devralanlar ve yapılacaklar. 'markdown' alanı doğrudan belge olarak kullanılabilir."""
    with KILIT:
        con = baglanti()
        d = takip.devir_dosyasi(con, _kisi_bul(con, kisi))
    return dict(ozet=d["ozet"], markdown=d["markdown"])


@arac
def plan_takibi() -> dict:
    """Kayıtlı eğitim planı tuttu mu: öğrenenler çağrı çözmeye başladı mı, kartlar yazıldı mı, risk hedefe indi mi."""
    with KILIT:
        t = takip.plan_takibi(baglanti())
    if not t["var"]:
        return dict(var=False, not_="Kayıtlı plan yok. Önce egitim_plani_oner ile plan çıkarıp web arayüzünden kaydedin.")
    return dict(plan_tarihi=t["plan_tarihi"], tutma_orani=t["tutma_orani"], konular=t["konular"],
                satirlar=[{k: x[k] for k in ("tur", "kategori", "ogrenen", "sonuc")} for x in t["satirlar"]])


@arac
def risk_seyri() -> dict:
    """Risk haritasının son aylardaki seyri (iki haftalık noktalar), en riskli konuların puan serisi ve
    bu dönemde alınan kararlar (plan, reçete, kart)."""
    with KILIT:
        return takip.risk_seyri(baglanti())


@arac
def risk_haritasi(sadece: str = "hepsi", birim: str | None = None) -> dict:
    """Konu bazında kişiye bağımlılık risk puanları ve nedenleri (Usta çağrıları + bakım dökümü).
    sadece: hepsi | kirmizi | sari."""
    with KILIT:
        h = risk.risk_haritasi(baglanti())
    tum_ozet = risk.ozet(h)
    if birim:
        h = [r for r in h if birim.lower() in r["birim"].lower()]
    if sadece in ("kirmizi", "sari"):
        h = [r for r in h if r["seviye"] == sadece]
    return dict(ozet=tum_ozet, konular=[dict(
        kategori_id=r["kategori_id"], ad=r["ad"], birim=r["birim"], kaynak=r["kaynak"], puan=r["puan"], seviye=r["seviye"],
        nedenler=r["nedenler"], azaltanlar=r["azaltanlar"], en_cok_cozen=r["en_cok_cozen"], yetkinler=r["yetkinler"],
        kagit_uzerinde_yetkin=r["beyan_sayisi"], gercekte_yetkin=r["gercek_sayisi"],
        yeni_konu=r["yeni_konu"], puan_gecici=r["gecici"]) for r in h])


@arac
def tek_kisiye_kalanlar(gun_sayisi: int = 7) -> dict:
    """Bugünden itibaren verilen gün içinde, izinler yüzünden yedeksiz veya tek kişiye kalan konular."""
    with KILIT:
        return risk.tek_kisiye_kalanlar(baglanti(), gun_sayisi)


@arac
def ya_giderse(kisi: str, gun: int = 21, dakika_maliyeti: float = 0) -> dict:
    """Bir kişi (ad veya numara) 'gun' gün yoksa hangi konular etkilenir, ne kadar ek bekleme oluşur.

    dakika_maliyeti verilirse (TL/dakika) ek beklemenin parasal karşılığı da hesaplanır.
    """
    with KILIT:
        con = baglanti()
        y = risk.ya_giderse(con, _kisi_bul(con, kisi), gun, dakika_maliyeti)
    y.pop("ozet_once", None)
    return y


@arac
def egitim_plani_oner(butce_saat: int = 40, yontem: str = "optimum", haftalik_sinir: float = 2.0,
                      oturum_saat: float = 1.0, gunluk_oturum: int = 1, calisma_gunu: int = 5) -> dict:
    """Verilen eğitim saati bütçesiyle riski en çok düşüren kart yazma ve çapraz eğitim eşleşmeleri,
    ve bunların haftalara yayılmış takvimi.

    yontem: optimum (çok seçenekli sırt çantası) | kural (saat başına en iyi adımı sırayla seç).
    haftalik_sinir: bir kişinin haftada eğitimde geçirebileceği en fazla saat (veren ve alan sayılır).
    oturum_saat: bir oturumun süresi (0,5-4). gunluk_oturum: kişi başı günde en fazla oturum.
    calisma_gunu: 5 (Pzt-Cum) ya da 6 (Pzt-Cmt). Takvim gelecek pazartesi başlar.
    Yanıttaki takvim.darbogaz takvimin uzunluğunu belirleyen kişidir.
    """
    takvim.ayar_dogrula(haftalik_sinir, oturum_saat, gunluk_oturum, calisma_gunu)
    with KILIT:
        p = risk.egitim_plani(baglanti(), butce_saat, yontem)
    p.pop("harita_sonra", None)
    t = takvim.takvim_olustur(p["satirlar"], takvim.sonraki_pazartesi(date.today()), haftalik_sinir,
                              oturum_saat, gunluk_oturum, calisma_gunu)
    # Sohbette okunur kalsın: oturumlar haftaya göre kısa satırlar
    t["haftalar"] = {}
    for o in t.pop("oturumlar"):
        kim = o["ogreten"] + (f" → {o['ogrenen']}" if o["ogrenen"] else "")
        t["haftalar"].setdefault(f"{o['hafta']}. hafta", []).append(
            f"{o['gun']} {o['tarih']}: {o['kategori']} · {o['tur_adi']} · {kim} · {o['saat']} sa")
    p["takvim"] = t
    return p


@arac
def degisimler() -> dict:
    """Ekipte ve sistemde neler değişti: sistem geçişleri (yeni konu, bilgi kimde toplanıyor, kim geçmeli,
    neler yapılmalı), son 90 günde işe girenlerin işe alışması ve otomasyon reçetelerinin sağlığı
    (başarısı düşen ya da askıya alınan reçeteler)."""
    with KILIT:
        con = baglanti()
        return dict(gecisler=degisim.gecisler(con),
                    yeni_personel=[dict(kisi=p["kisi"], ozet=p["ozet"], konular=[
                        dict(ad=k["ad"], durum=k["durum"], cozum=k["cozum"], kalan=k["kalan"]) for k in p["konular"]])
                        for p in degisim.yeni_personel(con)],
                    cirak_modu=usta.cirak_modu_acik(con),
                    otomasyon_sagligi=[dict(recete=r["ad"], **r["saglik"]) for r in otomasyon.receteler(con) if r["saglik"]])


@arac
def ise_alisma(kisi: str) -> dict:
    """Bir kişinin (ad veya numara) birimindeki her konuda ilerlemesi: son 90 günde kaç çözdü,
    yetkin sayılmasına kaç çözüm kaldı, kim ustası olabilir, çırak modu ona çağrı verebilir mi."""
    with KILIT:
        con = baglanti()
        return degisim.ise_alisma(con, _kisi_bul(con, kisi))


@arac
def gecis_kaydet(yeni_konu_adi: str, eski_konu: str | None = None, tarih: str | None = None,
                 anahtar_kullanicilar: list[str] | None = None, aciklama: str = "", birim: str | None = None) -> dict:
    """Sistem geçişini kaydeder (ör. eski rapor küpünden Power BI'a). eski_konu (ad veya kod) geçiş günü
    kapanır; yeni konu açılır, açık çağrılar ona taşınır. anahtar_kullanicilar: kurulumu yapan ya da
    eğitimi alan kişiler (ad veya numara). tarih: YYYY-AA-GG, verilmezse bugün. Öncülü olmayan yepyeni
    bir sistemde eski_konu boş bırakılır ve birim (ör. "BT Destek") verilir."""
    with KILIT:
        con = baglanti()
        eski = _konu_bul(con, eski_konu) if eski_konu else None
        kisiler = [_kisi_bul(con, k) for k in (anahtar_kullanicilar or [])]
        birim_id = None
        if not eski:
            b = con.execute("SELECT id FROM birim WHERE ad=?", (birim or "",)).fetchone()
            if not b:
                raise ValueError("Öncülü olmayan bir sistem için birim adını verin: "
                                 + ", ".join(r[0] for r in con.execute("SELECT ad FROM birim")))
            birim_id = b[0]
        r = degisim.gecis_kaydet(con, yeni_konu_adi, tarih, eski, kisiler, aciklama, birim_id=birim_id)
    return r


if __name__ == "__main__":
    sunucu.run()
