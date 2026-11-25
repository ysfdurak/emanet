"""Usta: sistemsel çağrıları (BT Destek, Depo Sistemleri) öğrenerek yönlendirir ve yol gösterir.

Kararlar ogrenme.py'deki modellerden gelir; burası onları iş kurallarıyla birleştirir:
  - Teknik bir arıza yazılmışsa (sorter, forklift...) Usta bunu kendi konusu saymaz, bakım sistemine yönlendirir.
  - Kişi seçiminde izindekiler ve vardiyada olmayanlar elenir.
  - Her önerinin yanında nedeni döner.
"""
from __future__ import annotations

import json
import sqlite3
from collections import Counter
from datetime import datetime, timedelta

from . import katalog as K
from . import ogrenme as O
from . import otomasyon
from .dil import yuzde
from .ogrenme import kucult, vardiya_bul

TEKNIK_ESIK = 0.60      # konu olasılığı bunun altındaysa ve metinde teknik bir anahtar kelime geçiyorsa kapsam dışı
CIRAK_GUN = 90          # işe girişinden bu kadar gün geçmemiş kişi "yeni personel" sayılır
CIRAK_ACIK_SINIR = 2    # çırağın üzerinde bundan az açık çağrı varsa ona yeni çağrı verilir


def _usta_kategorileri(con, yalniz_gecerli: bool = False):
    """Usta'nın konuları. yalniz_gecerli: bugün açık olanlar (geçişle kapananlar ve henüz başlamayanlar hariç)."""
    bugun = datetime.now().date().isoformat()
    sart = " AND (k.emeklilik IS NULL OR k.emeklilik>?) AND (k.acilis IS NULL OR k.acilis<=?)" if yalniz_gecerli else ""
    return {r["id"]: dict(r) for r in con.execute(
        "SELECT k.*, b.ad AS birim FROM kategori k JOIN birim b ON b.id=k.birim_id WHERE k.kaynak='usta'" + sart
        + " ORDER BY k.id", (bugun, bugun) if yalniz_gecerli else ())}


def _teknik_konu(metin: str) -> dict | None:
    k = kucult(metin)
    for kat in K.TEKNIK_KATEGORILER:
        if any(a.strip() and kucult(a.strip()) in k for a in kat["anahtar"].split(",")):
            return dict(ad=kat["ad"], birim=kat["birim"])
    return None


# ---------------------------------------------------------------- konu

def kategori_oner(con: sqlite3.Connection, metin: str, n: int = 3) -> dict:
    """Metnin konusunu model olasılıklarıyla tahmin eder; emin değilse soru sorulmasını ister."""
    m = O.model(con)
    kat = _usta_kategorileri(con, yalniz_gecerli=True)
    # Geçişle kapanan konular önerilmez; olasılıklar kalanlar arasında yeniden ölçeklenir.
    olas = [(k, p) for k, p in m.konu_olasiliklari(metin) if k in kat]
    toplam = sum(p for _, p in olas) or 1.0
    olas = [(k, p / toplam) for k, p in olas]
    # Modelin henüz hiç örnek görmediği yeni konu (öncülsüz yeni sistem): anahtar kelime tutarsa öne alınır
    # ve kullanıcıya sorulur.
    bilinen = {k for k, _ in olas}
    kk = kucult(metin)
    yeni = [k for k, d in kat.items() if k not in bilinen
            and any(a.strip() and kucult(a.strip()) in kk for a in d["anahtar_kelimeler"].split(","))]
    olas = [(k, 0.5) for k in yeni] + olas + [(k, 0.0) for k in kat if k not in bilinen and k not in yeni]
    ilk, ikinci = olas[0], olas[1]
    soru = ilk[1] < O.SORU_ESIGI or ilk[1] - ikinci[1] < O.FARK_ESIGI or bool(yeni)
    # Teknik arıza ayrımı demo şirketin bakım konularına göredir; kendi verinle kurulumda konular senindir.
    yerel = con.execute("SELECT deger FROM meta WHERE anahtar='mod'").fetchone()
    teknik = _teknik_konu(metin) if ilk[1] < TEKNIK_ESIK and not (yerel and yerel[0] == "yerel") else None
    oneriler = [dict(kategori_id=k, kod=kat[k]["kod"], ad=kat[k]["ad"], birim=kat[k]["birim"],
                     aciklama=kat[k]["aciklama"], puan=round(p, 3)) for k, p in olas[:n]]
    sozcukler = m.belirleyici_sozcukler(metin, ilk[0]) if not soru and ilk[0] in m.konu.classes_ else []
    neden = (f"'{kat[ilk[0]]['ad']}' yeni bir konu; model henüz örnek görmedi, anahtar kelime tuttu. Doğru mu?"
             if yeni else
             f"Model bu metni %{round(ilk[1] * 100)} olasılıkla '{kat[ilk[0]]['ad']}' konusuna koydu"
             + (f"; belirleyici sözcükler: {', '.join(sozcukler)}." if sozcukler else "."))
    return dict(oneriler=oneriler, guven=round(ilk[1], 3), soru_gerekli=soru or bool(teknik),
                soru=("Sorun aşağıdakilerden hangisine daha yakın?" if soru else None),
                neden=neden, belirleyici=sozcukler, kapsam_disi=teknik)


# ---------------------------------------------------------------- yönlendirme

def izinliler(con: sqlite3.Connection, gun: str) -> dict[int, str]:
    return {r["kisi_id"]: r["tur"] for r in con.execute(
        "SELECT kisi_id, tur FROM musaitlik WHERE baslangic<=? AND bitis>=?", (gun, gun))}


def cirak_modu_acik(con: sqlite3.Connection) -> bool:
    r = con.execute("SELECT deger FROM meta WHERE anahtar='cirak_modu'").fetchone()
    return not r or r[0] != "0"


def paylastirma_acik(con: sqlite3.Connection) -> bool:
    r = con.execute("SELECT deger FROM meta WHERE anahtar='paylastirma'").fetchone()
    return not r or r[0] != "0"


def _cirak_sec(con, kat: dict, adaylar: list[dict], olas: dict, aciliyet: int, simdi: datetime) -> dict | None:
    """Çırak modu: model geçmişe bakarak hep aynı uzmanı seçer; yeni personel ve eğitim planındaki
    öğrenen hiç çağrı almaz, pratik kazanamaz. Bu kısır döngüyü kırmak için kritik ve acil olmayan
    çağrılar, aynı vardiyada konuyu bilen bir usta varken öğrenene verilir. Usta takılırsa destek olur."""
    from .risk import yetkin_esigi
    from .devir import devralanlar
    if not cirak_modu_acik(con) or aciliyet >= 3:
        return None
    devralan = devralanlar(con, kat["id"])
    # Kritik konuda yanında öğrenme yalnız devir sürerken: usta ayrılıyorsa devralanın pratiğe başka yolu yok
    if kat["kritiklik"] >= 3 and not devralan:
        return None
    bas = (simdi - timedelta(days=90)).isoformat(timespec="minutes")
    say = {r[0]: r[1] for r in con.execute(
        "SELECT cozen_kisi_id, COUNT(*) FROM cagri WHERE kategori_id=? AND durum='kapali' AND kapanis>=? "
        "AND cozen_kisi_id IS NOT NULL GROUP BY 1", (kat["id"], bas))}
    esik = yetkin_esigi(sum(say.values()))
    ustalar = [u for u in adaylar if say.get(u["id"], 0) >= esik]
    if not ustalar:
        return None     # yanında bilen yoksa çırağa verilmez
    planli = {r[0] for r in con.execute(
        "SELECT ogrenen_id FROM egitim_plani WHERE kategori_id=? AND durum='planlandi' AND ogrenen_id IS NOT NULL",
        (kat["id"],))}
    yeni_sinir = (simdi.date() - timedelta(days=CIRAK_GUN)).isoformat()
    acik = {r[0]: r[1] for r in con.execute(
        "SELECT atanan_kisi_id, COUNT(*) FROM cagri WHERE durum='acik' AND atanan_kisi_id IS NOT NULL GROUP BY 1")}
    ciraklar = [u for u in adaylar if say.get(u["id"], 0) < esik
                and (u["id"] in planli or u["id"] in devralan or (u.get("ise_giris") or "") >= yeni_sinir)
                and (kat["kritiklik"] < 3 or u["id"] in devralan)
                and acik.get(u["id"], 0) < CIRAK_ACIK_SINIR]
    if not ciraklar:
        return None
    c = min(ciraklar, key=lambda u: (say.get(u["id"], 0), u["id"]))
    usta = max(ustalar, key=lambda u: olas.get(u["id"], 0.0))
    return dict(kisi=c, usta=usta, cozum=say.get(c["id"], 0), kalan=esik - say.get(c["id"], 0),
                neden=("devir sürecinde bu konuyu devralıyor" if c["id"] in devralan
                       else "eğitim planında bu konuyu öğreniyor" if c["id"] in planli else "yeni personel"))


def yonlendir(con: sqlite3.Connection, kategori_id: int, simdi: datetime | None = None, vardiya: str | None = None,
              metin: str = "", acan_birim: str = "", aciliyet: int = 2) -> dict:
    """Kişi modelinin olasılıklarına göre atar.

    1. Konunun birimindeki kişiler alınır, izindekiler elenir.
    2. O vardiyada çalışan varsa yalnızca onlar kalır.
    3. Kalanlar arasından modelin en yüksek olasılık verdiği kişi seçilir.
    4. Çırak modu: çağrı kritik ve acil değilse, vardiyada bir usta varken öğrenen kişiye verilir.
    Model "bu tür çağrıyı en iyi X çözer" diyor ama X müsait değilse bu not olarak döner.
    """
    simdi = simdi or datetime.now()
    vardiya = vardiya or vardiya_bul(simdi)
    kat = _usta_kategorileri(con).get(kategori_id)
    if not kat:
        raise ValueError("Bu konu Usta'nın kapsamında değil")
    if kat.get("emeklilik") and kat["emeklilik"] <= simdi.date().isoformat():
        yeni = con.execute("SELECT k.ad FROM gecis g JOIN kategori k ON k.id=g.yeni_kategori_id "
                           "WHERE g.eski_kategori_id=?", (kategori_id,)).fetchone()
        raise ValueError(f"'{kat['ad']}' konusu {kat['emeklilik']} tarihinde sistem geçişiyle kapandı"
                         + (f"; yerine '{yeni[0]}' konusunu seçin." if yeni else "."))
    m = O.model(con)
    olas = m.kisi_olasiliklari(metin or kat["ad"], kategori_id, vardiya, acan_birim)
    izinli = izinliler(con, simdi.date().isoformat())
    uyeler = [dict(r) for r in con.execute("SELECT * FROM kisi WHERE birim_id=? AND aktif=1", (kat["birim_id"],))]
    for u in uyeler:
        u["p"] = olas.get(u["id"], 0.0)
        u["durum"] = (izinli[u["id"]] + "de") if u["id"] in izinli else (
            "vardiyada" if u["vardiya"] == vardiya else "vardiyada değil")
    uyeler.sort(key=lambda u: -u["p"])
    musait = [u for u in uyeler if u["id"] not in izinli]
    adaylar = [u for u in musait if u["vardiya"] == vardiya] or musait
    if not adaylar:
        return dict(kisi_id=None, ad=None, birim=kat["birim"], vardiya=vardiya, olasilik=0,
                    neden="Birimde atanabilecek kimse yok.", uzman_notu=None, siralama=[])
    secilen = adaylar[0]
    toplam = sum(u["p"] for u in adaylar) or 1.0
    cirak = _cirak_sec(con, kat, adaylar, olas, aciliyet, simdi)
    if cirak:
        c, u = cirak["kisi"], cirak["usta"]
        return dict(kisi_id=c["id"], ad=c["ad"], birim=kat["birim"], vardiya=vardiya, olasilik=None,
                    neden=(f"Yanında öğrenme: {c['ad']} {cirak['neden']}; bilen sayılmasına {cirak['kalan']} çözüm kaldı. "
                           f"Takılırsa {u['ad']} destek verecek. Benzer çözümler aşağıda."),
                    uzman_notu=None, uzman=None,
                    cirak=dict(usta_id=u["id"], usta=u["ad"], cozum=cirak["cozum"], kalan=cirak["kalan"]),
                    siralama=[dict(kisi_id=x["id"], ad=x["ad"], olasilik=round(x["p"], 3), durum=x["durum"])
                              for x in uyeler[:5]])

    # Paylaştırma: model yetkinliği söyler, kime verileceğine iş yükü ve bilginin dağılması da karar verir
    pay_karar = None
    if paylastirma_acik(con):
        from .risk import yetkin_esigi
        bas = (simdi - timedelta(days=90)).isoformat(timespec="minutes")
        say = {r[0]: r[1] for r in con.execute(
            "SELECT cozen_kisi_id, COUNT(*) FROM cagri WHERE kategori_id=? AND durum='kapali' AND kapanis>=? "
            "AND cozen_kisi_id IS NOT NULL GROUP BY 1", (kategori_id, bas))}
        acik = {r[0]: r[1] for r in con.execute(
            "SELECT atanan_kisi_id, COUNT(*) FROM cagri WHERE durum='acik' AND atanan_kisi_id IS NOT NULL GROUP BY 1")}
        k = O.paylastirma_secimi([(u["id"], u["p"]) for u in adaylar], say, yetkin_esigi(sum(say.values())),
                                 acil_kritik=(kat["kritiklik"] == 3 and aciliyet == 3), acik=acik)
        if k["tur"]:
            ad = {u["id"]: u for u in adaylar}
            secilen = ad[k["kisi_id"]]
            ilk = ad[k["model_ilk"]]
            if k["tur"] == "paylastirma":
                b = ad[k["baskin"]]
                pay_karar = dict(tur="paylastirma", baskin=b["ad"], pay=k["pay"],
                                 neden=(f"Paylaştırma: bu vardiyada konunun {yuzde(k['pay'], 'ini')} {b['ad']} çözüyor. "
                                        f"Bilgi tek kişide toplanmasın ve yedeğin pratiği körelmesin diye konuyu bilen "
                                        f"{secilen['ad']} seçildi; gerekirse {b['ad']} destek olur."))
            else:
                pay_karar = dict(tur="yuk", baskin=ilk["ad"], acik=acik.get(ilk["id"], 0),
                                 neden=(f"İş yükü: {ilk['ad']} üzerinde {acik.get(ilk['id'], 0)} açık çağrı var; "
                                        f"sıra beklemesin diye {secilen['ad']} seçildi."))

    # Açıklama: en benzer geçmiş çağrıları kim çözmüş?
    komsu = m.komsular(metin, kategori_id) if metin else []
    cozenler = Counter(s["cozen_kisi_id"] for s, _ in komsu)
    n = cozenler.get(secilen["id"], 0)
    if komsu and n:
        neden = f"En benzer {len(komsu)} geçmiş çağrının {n} tanesini o çözmüş."
    elif komsu:
        neden = "Vardiyadakiler arasında modelin en uygun bulduğu kişi; benzer çağrıları daha önce çözmemiş, yol gösterici aşağıda."
    else:
        neden = "Vardiyadakiler arasında modelin en uygun bulduğu kişi."
    if adaylar is musait and musait[0]["vardiya"] != vardiya:
        neden = "Bu vardiyada birimden kimse yok; izinde olmayan en uygun kişiye atandı. " + neden
    if pay_karar:
        neden = pay_karar["neden"] + " " + neden
    uzman = uyeler[0]
    uzman_notu = None
    if uzman["id"] != secilen["id"] and uzman["p"] >= 0.35 and not (pay_karar and pay_karar["baskin"] == uzman["ad"]):
        uzman_notu = (f"Bu tür çağrıları en çok {uzman['ad']} çözüyor (model olasılığı %{round(uzman['p'] * 100)}) "
                      f"ama şu an {uzman['durum']}.")
    return dict(kisi_id=secilen["id"], ad=secilen["ad"], birim=kat["birim"], vardiya=vardiya,
                olasilik=round(secilen["p"] / toplam, 3), neden=neden, uzman_notu=uzman_notu, paylastirma=pay_karar,
                uzman=dict(ad=uzman["ad"], durum=uzman["durum"]) if uzman_notu else None,
                siralama=[dict(kisi_id=u["id"], ad=u["ad"], olasilik=round(u["p"], 3), durum=u["durum"])
                          for u in uyeler[:5]])


# ---------------------------------------------------------------- yol gösterme

def yol_goster(con: sqlite3.Connection, metin: str, kategori_id: int | None = None) -> dict:
    """Yazılı çözüm kartları + benzer geçmiş çağrıların nasıl çözüldüğü."""
    nc = O.nasil_cozuldu(con, metin, kategori_id)
    kat = kategori_id
    if kat is None and nc["cagrilar"]:
        kat = con.execute("SELECT kategori_id FROM cagri WHERE id=?", (nc["cagrilar"][0]["id"],)).fetchone()[0]
    kartlar = [dict(r) for r in con.execute(
        "SELECT ck.*, p.ad AS yazan, k.ad AS kategori FROM cozum_karti ck JOIN kategori k ON k.id=ck.kategori_id "
        "LEFT JOIN kisi p ON p.id=ck.yazan_kisi_id WHERE ck.kategori_id=? ORDER BY ck.id DESC", (kat,))] if kat else []
    return dict(nc, kartlar=kartlar)


# ---------------------------------------------------------------- çağrı yaşam döngüsü

def _olay(con, cagri_id, zaman, tur, kisi=None, aciklama=None):
    con.execute("INSERT INTO cagri_olay(cagri_id,zaman,tur,kisi_id,aciklama) VALUES(?,?,?,?,?)",
                (cagri_id, zaman.isoformat(timespec="minutes"), tur, kisi, aciklama))


def cagri_ac(con: sqlite3.Connection, metin: str, acan_birim: str = "Depolama", aciliyet: int = 2,
             kategori_id: int | None = None, vardiya: str | None = None, simdi: datetime | None = None,
             acan_kisi: str | None = None, yer: str | None = None, ek_bilgi: str | None = None) -> dict:
    metin = metin.strip()
    if len(metin) < 5:
        raise ValueError("Çağrı metni çok kısa")
    if aciliyet not in (1, 2, 3):
        raise ValueError("Aciliyet 1, 2 veya 3 olmalı")
    simdi = simdi or datetime.now()
    vardiya = vardiya or vardiya_bul(simdi)
    oneri = kategori_oner(con, metin)
    onerilen = oneri["oneriler"][0]["kategori_id"]
    if kategori_id is None and oneri["soru_gerekli"]:
        raise ValueError("Konu belirsiz; önce önerilen konulardan birini seçin")
    kategori_id = kategori_id or onerilen
    atama = yonlendir(con, kategori_id, simdi, vardiya, metin, acan_birim, aciliyet)
    cur = con.execute(
        "INSERT INTO cagri(metin,acan_birim,aciliyet,kategori_id,onerilen_kategori_id,guven,durum,atanan_kisi_id,"
        "acilis,vardiya,kaynak,acan_kisi,yer,ek_bilgi) VALUES(?,?,?,?,?,?,'acik',?,?,?,'usta',?,?,?)",
        (metin, acan_birim, aciliyet, kategori_id, onerilen, oneri["guven"], atama["kisi_id"],
         simdi.isoformat(timespec="minutes"), vardiya, acan_kisi, (yer or "").strip()[:60] or None, ek_bilgi))
    cid = cur.lastrowid
    _olay(con, cid, simdi, "acildi")
    _olay(con, cid, simdi, "atandi", atama["kisi_id"], atama["neden"])
    con.commit()
    toplu = otomasyon.toplu_kontrol(con, cid, simdi)        # aynı konuda çok çağrı → tek olay
    oto = None if toplu else otomasyon.baslat(con, cid)     # uyan reçete varsa otomasyon
    return dict(cagri_detay(con, cid), atama=atama, oneri=oneri, toplu=toplu, otomasyon=oto)


def yeniden_ata(con: sqlite3.Connection, cagri_id: int, kategori_id: int | None = None,
                kisi_id: int | None = None, vardiya: str | None = None, aciklama: str | None = None) -> dict:
    """Yanlış yönlendirme düzeltmesi. Çağrı kapanınca düzeltilmiş hâliyle modelin öğrenme verisine girer."""
    c = con.execute("SELECT * FROM cagri WHERE id=? AND kaynak='usta'", (cagri_id,)).fetchone()
    if not c:
        raise ValueError("Çağrı bulunamadı")
    if c["durum"] != "acik":
        raise ValueError("Kapalı çağrı yeniden atanamaz")
    kategori_id = kategori_id or c["kategori_id"]
    if kategori_id not in _usta_kategorileri(con):
        raise ValueError("Bu konu Usta'nın kapsamında değil")
    if not kisi_id:
        kisi_id = yonlendir(con, kategori_id, datetime.now(), vardiya or c["vardiya"], c["metin"], c["acan_birim"],
                            c["aciliyet"])["kisi_id"]
    con.execute("UPDATE cagri SET kategori_id=?, atanan_kisi_id=?, yeniden_atama=yeniden_atama+1 WHERE id=?",
                (kategori_id, kisi_id, cagri_id))
    _olay(con, cagri_id, datetime.now(), "yeniden_atandi", kisi_id, aciklama or "Yönlendirme düzeltildi")
    con.commit()
    return cagri_detay(con, cagri_id)


def cagri_kapat(con: sqlite3.Connection, cagri_id: int, cozen_kisi_id: int | None = None, sure_dk: int | None = None,
                cozum_notu: str | None = None, karta_donustur: bool = False, baslik: str | None = None,
                kok_neden: str | None = None, kart_id: int | None = None) -> dict:
    """Çağrıyı kapatır. Çözüm notu modelin "nasıl çözüldü" hafızasına girer.
    karta_donustur=True ise not ayrıca konunun yazılı çözüm kartı olarak kaydedilir."""
    c = con.execute("SELECT * FROM cagri WHERE id=? AND kaynak='usta'", (cagri_id,)).fetchone()
    if not c:
        raise ValueError("Çağrı bulunamadı")
    if c["durum"] != "acik":
        raise ValueError("Çağrı zaten kapalı")
    simdi = datetime.now()
    cozen = cozen_kisi_id or c["atanan_kisi_id"]
    if sure_dk is None:
        sure_dk = max(1, round((simdi - datetime.fromisoformat(c["acilis"])).total_seconds() / 60))
    notu = "\n".join(s.strip() for s in (cozum_notu or "").splitlines() if s.strip()) or None
    if karta_donustur:
        if not notu:
            raise ValueError("Karta dönüştürmek için çözüm adımlarını yazın")
        kart_id = cozum_karti_ekle(con, c["kategori_id"], baslik or c["metin"][:60], notu, kok_neden, cozen,
                                   kaydet=False)["id"]
    con.execute("UPDATE cagri SET durum='kapali', cozen_kisi_id=?, kapanis=?, sure_dk=?, kart_id=?, cozum_notu=?, "
                "teyit=NULL WHERE id=?", (cozen, simdi.isoformat(timespec="minutes"), sure_dk, kart_id, notu, cagri_id))
    _olay(con, cagri_id, simdi, "kapandi", cozen)
    otomasyon.kapanis_sonrasi(con, cagri_id, notu, cozen)   # teyit sorusu, toplu arızanın diğer çağrıları
    con.commit()
    return cagri_detay(con, cagri_id)


def cozum_karti_ekle(con: sqlite3.Connection, kategori_id: int, baslik: str, adimlar: str,
                     kok_neden: str | None = None, yazan_kisi_id: int | None = None, kaydet: bool = True) -> dict:
    if not adimlar.strip():
        raise ValueError("Çözüm adımları boş olamaz")
    cur = con.execute(
        "INSERT INTO cozum_karti(kategori_id,baslik,adimlar,kok_neden,yazan_kisi_id,olusturma) VALUES(?,?,?,?,?,?)",
        (kategori_id, baslik.strip()[:120], adimlar.strip(), kok_neden, yazan_kisi_id,
         datetime.now().isoformat(timespec="minutes")))
    if kaydet:
        con.commit()
    return dict(con.execute("SELECT * FROM cozum_karti WHERE id=?", (cur.lastrowid,)).fetchone())


# ---------------------------------------------------------------- okuma

_CAGRI_SQL = (
    "SELECT c.*, k.ad AS kategori, k.kod AS kategori_kod, b.ad AS birim, a.ad AS atanan, z.ad AS cozen "
    "FROM cagri c JOIN kategori k ON k.id=c.kategori_id JOIN birim b ON b.id=k.birim_id "
    "LEFT JOIN kisi a ON a.id=c.atanan_kisi_id LEFT JOIN kisi z ON z.id=c.cozen_kisi_id ")


def cagrilari_listele(con: sqlite3.Connection, durum: str | None = "acik", birim_id: int | None = None,
                      kisi_id: int | None = None, kategori_id: int | None = None, limit: int = 50) -> list[dict]:
    kosul, arg = ["c.kaynak='usta'"], []
    if durum in ("acik", "kapali"):
        kosul.append("c.durum=?"); arg.append(durum)
    if birim_id:
        kosul.append("k.birim_id=?"); arg.append(birim_id)
    if kisi_id:
        kosul.append("(c.atanan_kisi_id=? OR c.cozen_kisi_id=?)"); arg += [kisi_id, kisi_id]
    if kategori_id:
        kosul.append("c.kategori_id=?"); arg.append(kategori_id)
    arg.append(max(1, min(int(limit), 200)))
    return [dict(r) for r in con.execute(
        _CAGRI_SQL + "WHERE " + " AND ".join(kosul) + " ORDER BY c.acilis DESC, c.id DESC LIMIT ?", arg)]


def cagri_detay(con: sqlite3.Connection, cagri_id: int) -> dict:
    c = con.execute(_CAGRI_SQL + "WHERE c.id=? AND c.kaynak='usta'", (cagri_id,)).fetchone()
    if not c:
        raise ValueError("Çağrı bulunamadı")
    olaylar = [dict(r) for r in con.execute(
        "SELECT o.*, p.ad AS kisi FROM cagri_olay o LEFT JOIN kisi p ON p.id=o.kisi_id "
        "WHERE o.cagri_id=? ORDER BY o.zaman, o.id", (cagri_id,))]
    yol = yol_goster(con, c["metin"], c["kategori_id"])
    yol["cagrilar"] = [x for x in yol["cagrilar"] if x["id"] != cagri_id]
    o = con.execute("SELECT id FROM oto WHERE cagri_id=? ORDER BY id DESC", (cagri_id,)).fetchone()
    toplu = None
    if c["olay_id"]:
        toplu = dict(olay_id=c["olay_id"], cagrilar=[dict(r) for r in con.execute(
            "SELECT id, metin, acan_kisi, durum FROM cagri WHERE olay_id=? ORDER BY id", (c["olay_id"],))])
    return dict(c, ek=json.loads(c["ek_bilgi"]) if c["ek_bilgi"] else None, olaylar=olaylar, yol=yol, otomasyon=otomasyon.oto_detay(con, o["id"]) if o else None,
                mesajlar=[m for m in otomasyon.mesajlar(con, cagri_id=cagri_id) if m["oto_id"] is None],
                toplu_olay=toplu)


def kartlar(con: sqlite3.Connection, q: str | None = None) -> dict:
    satirlar = [dict(r) for r in con.execute(
        "SELECT ck.*, k.ad AS kategori, b.ad AS birim, p.ad AS yazan, "
        "(SELECT COUNT(*) FROM cagri c WHERE c.kart_id=ck.id) AS kullanim "
        "FROM cozum_karti ck JOIN kategori k ON k.id=ck.kategori_id JOIN birim b ON b.id=k.birim_id "
        "LEFT JOIN kisi p ON p.id=ck.yazan_kisi_id WHERE k.kaynak='usta' ORDER BY k.birim_id, k.ad, ck.id")]
    if q and q.strip():
        aranan = kucult(q.strip())
        satirlar = [s for s in satirlar
                    if aranan in kucult(" ".join([s["baslik"], s["adimlar"], s["kategori"], s["kok_neden"] or ""]))]
    kartsiz = [dict(r) for r in con.execute(
        "SELECT k.id, k.ad, b.ad AS birim, k.kritiklik, "
        "(SELECT COUNT(*) FROM cagri c WHERE c.kategori_id=k.id AND c.cozum_notu IS NOT NULL) AS notlu, "
        "(SELECT COUNT(*) FROM cagri c WHERE c.kategori_id=k.id AND c.durum='kapali') AS toplam "
        "FROM kategori k JOIN birim b ON b.id=k.birim_id WHERE k.kaynak='usta' "
        "AND NOT EXISTS (SELECT 1 FROM cozum_karti ck WHERE ck.kategori_id=k.id) ORDER BY k.kritiklik DESC, k.ad")]
    return dict(kartlar=satirlar, kartsiz_kategoriler=kartsiz)


def olculer(con: sqlite3.Connection) -> dict:
    """Usta'nın işletme ölçüleri (geçmiş çağrılardan) ve modelin test başarısı."""
    r = con.execute(
        "SELECT COUNT(*) n, SUM(yeniden_atama>0) yeniden, SUM(cozum_notu IS NOT NULL) notlu, "
        "AVG(CASE WHEN kart_id IS NOT NULL THEN sure_dk END) kartli, "
        "AVG(CASE WHEN kart_id IS NULL AND EXISTS(SELECT 1 FROM cozum_karti ck WHERE ck.kategori_id=cagri.kategori_id) "
        "THEN sure_dk END) kartsiz FROM cagri WHERE durum='kapali' AND kaynak='usta'").fetchone()
    kat = con.execute(
        "SELECT COUNT(*) n, SUM(EXISTS(SELECT 1 FROM cozum_karti ck WHERE ck.kategori_id=k.id)) kartli "
        "FROM kategori k WHERE k.kaynak='usta'").fetchone()
    acik = con.execute("SELECT COUNT(*) FROM cagri WHERE durum='acik' AND kaynak='usta'").fetchone()[0]
    n = r["n"] or 1
    oto_kapanan = con.execute("SELECT COUNT(*) FROM cagri WHERE otomatik=1 AND durum='kapali'").fetchone()[0]
    return dict(kapali_cagri=r["n"], acik_cagri=acik, otomatik_kapanan=oto_kapanan,
                yeniden_atama_orani=round((r["yeniden"] or 0) / n, 3),
                cozum_notu_orani=round((r["notlu"] or 0) / n, 3),
                ort_sure_kartli_dk=round(r["kartli"] or 0, 1), ort_sure_kartsiz_dk=round(r["kartsiz"] or 0, 1),
                kart_kapsami=round((kat["kartli"] or 0) / (kat["n"] or 1), 3),
                model=O.degerlendir(con))
