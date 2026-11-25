"""Emanet: kişiye bağımlılık risk haritası, "ya giderse" simülasyonu, çapraz eğitim planı.

Kendi ham verisi yoktur. Her şey kapalı çağrılardan (kim, hangi konuyu, kaç kez çözdü) türetilir.
İki kaynak birlikte okunur: Usta'nın sistemsel çağrıları ve içe aktarılan teknik dökümler
(bkz. ice_aktar.py). "Yazılı çözüm" = çözüm kartı ya da dökümdeki "talimat var" işareti.

Risk puanı (konu başına, 0-100):

    puan = 100 × ((0,45 × yoğunlaşma + 0,35 × yedek riski) × (1 − otomasyon payı) + 0,20 × yazısızlık)
           × kritiklik çarpanı

    yoğunlaşma       : en çok çözen kişinin o konudaki payı (0-1)
    yedek riski      : son 90 günde konuyu en az 3 kez çözmüş kişi sayısına göre
                       0-1 kişi → 1,0 · 2 kişi → 0,5 · 3 kişi → 0,2 · 4+ kişi → 0
    yazısızlık       : çözüm kartı, reçete (taslak dahil) ya da dökümde yazılı talimat yoksa 1, varsa 0
    otomasyon payı   : konunun çağrılarından otomasyonla insansız kapanması beklenen pay (kişiye bağlı değil)
    kritiklik çarpanı: kritiklik 1 → 0,6 · 2 → 0,8 · 3 → 1,0

Değişimler:
    Sistem geçişi  : eski konu geçiş günü haritadan çıkar, yeni konu o gün başlar. Yeni konu ilk
                     60 gün (ya da 10 çağrıya ulaşana kadar) "yeni konu"dur: puan, kâğıttaki beyanlar ve
                     anahtar kullanıcılar yetkin sayılarak geçici hesaplanır. Ama yeni sistemde çağrıların
                     %60'ından fazlasını tek kişi çözüyorsa (en az 5 çağrı) erken uyarı verilir ve gerçek
                     veriyle hesaplanan puan kullanılır: bilgi daha ilk haftalarda tek kişide toplanıyordur.
    Yeni personel  : kimse işe girdiği için yedek sayılmaz; 3 çözümle yetkin olur (çırak modu, usta.py).
"""
from __future__ import annotations

import json
import math
import sqlite3
from datetime import date, datetime, timedelta

from .dil import yuzde

PENCERE_GUN = 90
ESKI_PENCERE_GUN = 365          # pratiği kalmamış yedekleri bulmak için geriye bakılan süre
TAZELEME_ORANI = 1 / 3          # eskiden bilen birinin yeniden öğrenmesi, sıfırdan öğrenmenin üçte biri
PRATIK_KAYBI_GUN = 60          # son çözümünden bu yana en az bu kadar gün geçmişse "pratiği kalmamış"
YETKIN_ESIGI = 3
GECIS_ORANI = 0.5               # eski sistemde bu işi yapan birinin yenisini öğrenmesi, sıfırdan öğrenmenin yarısı
YENI_KONU_GUN = 60              # yeni konu bu kadar gün "yeni" sayılır...
YENI_KONU_MIN = 10              # ...ya da bu kadar çağrıya ulaşana kadar
ANAHTAR_PAY, ANAHTAR_MIN = 0.6, 5   # yeni konuda tek kişinin payı bunu geçerse erken uyarı (en az 5 çağrıyla)
A_YOGUNLASMA, A_YEDEK, A_KART = 0.45, 0.35, 0.20
KRITIKLIK_CARPANI = {1: 0.6, 2: 0.8, 3: 1.0}
YEDEK_RISKI = {0: 1.0, 1: 1.0, 2: 0.5, 3: 0.2}
KIRMIZI, SARI = 60, 35
KART_YAZMA_SAATI = 2
VARDIYALAR = ("gunduz", "aksam", "gece")


def yetkin_esigi(toplam_cozum: int) -> int:
    """Bir kişinin 'yetkin' sayılması için gereken çözüm sayısı.

    Normalde 3. Seyrek konularda (pencerede 9'dan az çağrı) 2 yeterlidir; yoksa nadir ama
    kritik konularda kimse yetkin görünmez.
    """
    return YETKIN_ESIGI if toplam_cozum >= 9 else 2


def seviye(puan: float) -> str:
    return "kirmizi" if puan >= KIRMIZI else ("sari" if puan >= SARI else "yesil")


def puan_hesapla(sayim: dict[int, int], kritiklik: int, kart_var: bool,
                 ek_yetkin: int = 0, ek_kart: bool = False, esik: int | None = None,
                 yog_taban: float = 0.0, oto_payi: float = 0.0) -> dict:
    """Tek bir konu için risk bileşenleri.

    ek_yetkin: eğitim planıyla eklenecek kişi sayısı. Varsayım: eğitilen kişi işi eşit paylaşır,
    yani yoğunlaşma m/(m+ek) oranında düşer (m = mevcut yetkin sayısı).
    oto_payi: konunun çağrılarının otomasyonla insansız kapanması beklenen payı. Bu pay kişiye
    bağımlı değildir; bu yüzden bağımlılık bileşenleri (yoğunlaşma ve yedek) (1 − pay) ile çarpılır.
    """
    toplam = sum(sayim.values())
    esik = esik or yetkin_esigi(toplam)
    yetkin = sum(1 for n in sayim.values() if n >= esik)
    # Konuyu düzenli çözen kimse yoksa bağımlılık en yüksek sayılır (yoğunlaşma = 1).
    yog = (max(sayim.values()) / toplam) if (toplam and yetkin) else 1.0
    yog = max(yog, yog_taban)   # "ya giderse"de: bir kişinin gidişi yoğunlaşmayı iyileştirmiş sayılmaz
    if ek_yetkin:
        yog = yog * yetkin / (yetkin + ek_yetkin) if yetkin else 1.0 / ek_yetkin
        yetkin += ek_yetkin
    yedek = YEDEK_RISKI.get(yetkin, 0.0)
    kartsiz = 0.0 if (kart_var or ek_kart) else 1.0
    ham = 100 * ((A_YOGUNLASMA * yog + A_YEDEK * yedek) * (1 - oto_payi) + A_KART * kartsiz) \
        * KRITIKLIK_CARPANI[kritiklik]
    return dict(puan=round(ham), ham=ham, seviye=seviye(round(ham)), yogunlasma=round(yog, 3),
                yetkin_sayisi=yetkin, yedek_riski=yedek, kartsiz=bool(kartsiz), toplam_cozum=toplam,
                oto_payi=round(oto_payi, 3))


def _veri(con: sqlite3.Connection, simdi: datetime | None = None) -> dict:
    """Hesaplarda kullanılan ham tabloları bir kez okur. simdi geçmiş bir tarih olabilir (risk seyri)."""
    from .otomasyon import otomasyon_paylari, saglik_uyarilari
    simdi = simdi or datetime.now()
    son = simdi.isoformat(timespec="seconds")
    esik = (simdi - timedelta(days=PENCERE_GUN)).isoformat(timespec="minutes")
    eski_esik = (simdi - timedelta(days=ESKI_PENCERE_GUN)).isoformat(timespec="minutes")
    kategoriler = [dict(r) for r in con.execute(
        "SELECT k.*, b.ad AS birim, "
        "(k.talimat_var OR EXISTS(SELECT 1 FROM cozum_karti ck WHERE ck.kategori_id=k.id AND ck.olusturma<=?) "
        " OR EXISTS(SELECT 1 FROM recete r WHERE r.kategori_kod=k.kod AND r.olusturma<=?)) AS kart_var, "
        "(SELECT r.tur FROM recete r WHERE r.kategori_kod=k.kod AND r.olusturma<=? "
        " ORDER BY r.tur='taslak' LIMIT 1) AS recete_turu, "
        "(SELECT AVG(c.cozum_notu IS NOT NULL) FROM cagri c WHERE c.kategori_id=k.id AND c.durum='kapali' "
        " AND c.otomatik=0) AS not_orani "
        "FROM kategori k JOIN birim b ON b.id=k.birim_id "
        "WHERE (k.acilis IS NULL OR k.acilis<=?) AND (k.emeklilik IS NULL OR k.emeklilik>?) "
        "ORDER BY k.birim_id, k.id", (son, son, son, son, son))]
    paylar = otomasyon_paylari(con, esik, son)
    uyarilar = saglik_uyarilari(con, son)
    for k in kategoriler:
        k["oto_payi"] = paylar.get(k["kod"], 0.0)
        k["oto_uyari"] = uyarilar.get(k["kod"], [])
    kisiler = {r["id"]: dict(r) for r in con.execute(
        "SELECT p.*, b.ad AS birim FROM kisi p JOIN birim b ON b.id=p.birim_id WHERE p.aktif=1 ORDER BY p.id")}
    sayim: dict[int, dict[int, int]] = {k["id"]: {} for k in kategoriler}
    eski: dict[int, dict[int, int]] = {k["id"]: {} for k in kategoriler}
    son_cozum: dict[int, dict[int, str]] = {k["id"]: {} for k in kategoriler}
    for r in con.execute(
            "SELECT kategori_id, cozen_kisi_id, SUM(kapanis>=?) yeni, SUM(kapanis<? AND kapanis>=?) eski, "
            "MAX(kapanis) son FROM cagri WHERE durum='kapali' AND kapanis<=? AND kapanis>=? "
            "AND cozen_kisi_id IS NOT NULL GROUP BY 1,2", (esik, esik, eski_esik, son, eski_esik)):
        if r["cozen_kisi_id"] not in kisiler or r["kategori_id"] not in sayim:
            continue   # ayrılmış kişi ya da o tarihte geçerli olmayan (kapanmış / henüz açılmamış) konu
        if r["yeni"]:
            sayim[r["kategori_id"]][r["cozen_kisi_id"]] = r["yeni"]
        if r["eski"]:
            eski[r["kategori_id"]][r["cozen_kisi_id"]] = r["eski"]
        son_cozum[r["kategori_id"]][r["cozen_kisi_id"]] = r["son"]
    beyan: dict[int, set[int]] = {k["id"]: set() for k in kategoriler}
    for r in con.execute("SELECT kisi_id, kategori_id FROM yetkinlik_beyan"):
        if r["kategori_id"] in beyan:
            beyan[r["kategori_id"]].add(r["kisi_id"])
    # Geçişler: yeni konunun öncülünde son 90 günde (geçiş gününe kadar) yetkin olanlar = geçiş adayları
    gecis: dict[int, dict] = {}
    ids = {k["id"] for k in kategoriler}
    for g in con.execute("SELECT g.*, e.ad AS eski_ad FROM gecis g LEFT JOIN kategori e ON e.id=g.eski_kategori_id "
                         "WHERE g.tarih<=?", (son,)):
        if g["yeni_kategori_id"] not in ids:
            continue
        eski_yetkin, eski_kart = [], 0
        if g["eski_kategori_id"]:
            bas = (date.fromisoformat(g["tarih"]) - timedelta(days=PENCERE_GUN)).isoformat()
            say = {r[0]: r[1] for r in con.execute(
                "SELECT cozen_kisi_id, COUNT(*) FROM cagri WHERE kategori_id=? AND durum='kapali' AND kapanis>=? "
                "AND kapanis<? AND cozen_kisi_id IS NOT NULL GROUP BY 1", (g["eski_kategori_id"], bas, g["tarih"]))}
            e = yetkin_esigi(sum(say.values()))
            eski_yetkin = [p for p, n in sorted(say.items(), key=lambda x: -x[1]) if n >= e and p in kisiler]
            eski_kart = con.execute("SELECT COUNT(*) FROM cozum_karti WHERE kategori_id=?",
                                    (g["eski_kategori_id"],)).fetchone()[0]
        gecis[g["yeni_kategori_id"]] = dict(
            id=g["id"], tarih=g["tarih"], eski_kategori_id=g["eski_kategori_id"], eski_ad=g["eski_ad"],
            anahtar=[p for p in json.loads(g["anahtar_kisiler"]) if p in kisiler],
            eski_yetkin=eski_yetkin, eski_kart=eski_kart)
    return dict(kategoriler=kategoriler, kisiler=kisiler, sayim=sayim, eski=eski, son_cozum=son_cozum,
                beyan=beyan, simdi=simdi, gecis=gecis)


def yeni_konu_durumu(v: dict, k: dict) -> dict | None:
    """Konu yeni bir sistemle başladıysa ve hâlâ 'yeni' ise durumu; değilse None."""
    if not k.get("acilis"):
        return None
    yas = (v["simdi"].date() - date.fromisoformat(k["acilis"][:10])).days
    s = v["sayim"][k["id"]]
    toplam = sum(s.values())
    if yas >= YENI_KONU_GUN and toplam >= YENI_KONU_MIN:
        return None
    g = v["gecis"].get(k["id"], {})
    en = max(s.items(), key=lambda x: x[1]) if s else None
    erken = bool(en and toplam >= ANAHTAR_MIN and en[1] / toplam >= ANAHTAR_PAY)
    beyanli = sorted((v["beyan"][k["id"]] | set(g.get("anahtar", []))) & set(v["kisiler"]))
    return dict(yas_gun=yas, cagri=toplam, erken_uyari=erken, beyanli=beyanli,
                beyanli_ad=[v["kisiler"][p]["ad"] for p in beyanli],
                en_cok=(dict(ad=v["kisiler"][en[0]]["ad"], pay=round(en[1] / toplam, 2)) if en else None))


def etkin_sayim(v: dict, k: dict) -> tuple[dict[int, int], dict | None]:
    """Risk hesabında kullanılan çözüm sayıları. Yeni konuda (erken uyarı yoksa) beyan edenler ve
    anahtar kullanıcılar yetkin sayılır: veri azken puan kâğıda dayanır ve geçicidir."""
    s = v["sayim"][k["id"]]
    y = yeni_konu_durumu(v, k)
    if not y or y["erken_uyari"] or not y["beyanli"]:
        return s, y
    e = dict(s)
    for p in y["beyanli"]:
        e[p] = max(e.get(p, 0), YETKIN_ESIGI)
    return e, y


def gecis_adaylari(v: dict, kategori_id: int, haric_kisi: int | None = None) -> list[dict]:
    """Eski sistemde bu işi düzenli yapan ama yeni konuda henüz yetkin olmayan kişiler."""
    g = v["gecis"].get(kategori_id)
    if not g:
        return []
    s = v["sayim"][kategori_id]
    esik = yetkin_esigi(sum(s.values()))
    return [dict(kisi_id=p, ad=v["kisiler"][p]["ad"], cozum=s.get(p, 0))
            for p in g["eski_yetkin"] if p != haric_kisi and s.get(p, 0) < esik]


def pratigi_kalmayanlar(v: dict, kategori_id: int, haric_kisi: int | None = None) -> list[dict]:
    """Eskiden konuyu düzenli çözen (91-365 gün önce en az 3 kez) ama son 90 günde yetkin
    sayılmayacak kadar az çözen ve son çözümünün üzerinden en az 60 gün geçmiş kişiler. Kâğıtta ve hafızada yedek görünürler, pratikleri kalmamıştır."""
    s, e = v["sayim"][kategori_id], v["eski"][kategori_id]
    esik = yetkin_esigi(sum(s.values()))
    sonuc = []
    for p, n in sorted(e.items(), key=lambda x: -x[1]):
        if p == haric_kisi or n < YETKIN_ESIGI or s.get(p, 0) >= esik:
            continue
        son = v["son_cozum"][kategori_id].get(p)
        gun = (v["simdi"] - datetime.fromisoformat(son)).days if son else 999
        if gun < PRATIK_KAYBI_GUN:      # yakın zamanda çözmüş: pratiği azalmış ama kalmamış değil
            continue
        ay = max(1, round(gun / 30))
        sonuc.append(dict(kisi_id=p, ad=v["kisiler"][p]["ad"], eski_cozum=n, son_cozum=son, ay_once=ay))
    return sonuc


def risk_haritasi(con: sqlite3.Connection, simdi: datetime | None = None, haric_kisi: int | None = None,
                  ek_yetkin: dict[int, int] | None = None, ek_kart: set[int] | None = None,
                  _v: dict | None = None) -> list[dict]:
    """Konu bazında risk puanı ve nedenleri, puana göre azalan sırada.

    haric_kisi: "ya giderse" için o kişinin çözümleri yok sayılır.
    ek_yetkin / ek_kart: eğitim planı sonrası durumu görmek için.
    """
    v = _v or _veri(con, simdi)
    ek_yetkin, ek_kart = ek_yetkin or {}, ek_kart or set()
    sonuc = []
    for k in v["kategoriler"]:
        tam, yeni = etkin_sayim(v, k)
        s = {p: n for p, n in tam.items() if p != haric_kisi}
        # Eşik, kişi çıkarılmadan önceki çağrı sayısına göre belirlenir; yoksa biri gidince eşik düşer.
        esik = yetkin_esigi(sum(tam.values()))
        taban = (max(tam.values()) / sum(tam.values())) if (haric_kisi and tam) else 0.0
        h = puan_hesapla(s, k["kritiklik"], bool(k["kart_var"]), ek_yetkin.get(k["id"], 0), k["id"] in ek_kart,
                         esik, taban, k["oto_payi"])
        eskiyen = pratigi_kalmayanlar(v, k["id"], haric_kisi)
        sirali = sorted(s.items(), key=lambda x: -x[1])
        yetkinler = [p for p, n in sirali if n >= esik]
        beyan = v["beyan"][k["id"]] - ({haric_kisi} if haric_kisi else set())
        vardiya = {vd: sum(1 for p in yetkinler if v["kisiler"][p]["vardiya"] == vd) for vd in VARDIYALAR}
        en_cok = sirali[0] if sirali else None
        nedenler = []
        gecis = v["gecis"].get(k["id"])
        adaylar = gecis_adaylari(v, k["id"], haric_kisi)
        if yeni and yeni["erken_uyari"]:
            nedenler.append(f"Yeni sistemde bilgi tek kişide toplanıyor: çağrıların {yuzde(yeni['en_cok']['pay'], 'ini')} "
                            f"{yeni['en_cok']['ad']} çözüyor (ilk {yeni['yas_gun']} gün)")
        elif yeni:
            nedenler.append(f"Yeni konu ({yeni['yas_gun']} gündür, {yeni['cagri']} çağrı): puan geçici, "
                            + ("kâğıtta bilenler bilen sayıldı" if yeni["beyanli"] else "kâğıtta bilen de yok"))
        if en_cok and h["yogunlasma"] >= 0.6 and not (yeni and yeni["erken_uyari"]):
            nedenler.append(f"Çağrıların {yuzde(h['yogunlasma'], 'ini')} {v['kisiler'][en_cok[0]]['ad']} çözüyor")
        if h["yetkin_sayisi"] <= 1:
            nedenler.append("Yedek yok" if h["yetkin_sayisi"] == 1 else "Konuyu düzenli çözen kimse yok")
        if h["kartsiz"]:
            nedenler.append("Yazılı çözüm yok")
            if k["kaynak"] == "usta" and k["not_orani"] is not None and k["not_orani"] < 0.4:
                nedenler.append(f"Çözümlerin yalnızca {yuzde(k['not_orani'], 'ine')} not düşülmüş")
        if h["kartsiz"] and gecis and gecis["eski_kart"]:
            nedenler.append(f"Eski sistemin {gecis['eski_kart']} çözüm kartı var; yeni sisteme uyarlanırsa yazılı çözüm sayılır")
        nedenler.extend(k["oto_uyari"])
        for e in eskiyen[:2]:
            nedenler.append(f"Pratiği kalmamış yedek: {e['ad']} (son çözüm {e['ay_once']} ay önce)")
        bos = [vd for vd in VARDIYALAR if vardiya[vd] == 0]
        if bos and h["yetkin_sayisi"] > 0:
            ad = {"gunduz": "gündüz", "aksam": "akşam", "gece": "gece"}
            nedenler.append(f"{', '.join(ad[b] for b in bos)} vardiyasında bilen yok")
        sonuc.append(dict(
            kategori_id=k["id"], kod=k["kod"], ad=k["ad"], birim=k["birim"], birim_id=k["birim_id"],
            kaynak=("Usta" if k["kaynak"] == "usta" else k["kaynak"]),
            kritiklik=k["kritiklik"], puan=h["puan"], ham=round(h["ham"], 2), seviye=h["seviye"],
            yogunlasma=h["yogunlasma"], yetkin_sayisi=h["yetkin_sayisi"], yedek_riski=h["yedek_riski"],
            kartsiz=h["kartsiz"], toplam_cozum=h["toplam_cozum"],
            gunluk_cagri=round(h["toplam_cozum"] / PENCERE_GUN, 2),
            en_cok_cozen=(dict(kisi_id=en_cok[0], ad=v["kisiler"][en_cok[0]]["ad"], adet=en_cok[1]) if en_cok else None),
            yetkinler=[v["kisiler"][p]["ad"] for p in yetkinler],
            beyan_sayisi=len(beyan), gercek_sayisi=len([p for p in yetkinler]),
            beyanda_var_gercekte_yok=[v["kisiler"][p]["ad"] for p in sorted(beyan) if p in v["kisiler"] and s.get(p, 0) < esik],
            vardiya_kapsama=vardiya, nedenler=nedenler,
            otomasyon_payi=h["oto_payi"], recete_turu=k["recete_turu"], pratigi_kalmayan=eskiyen,
            yeni_konu=yeni, gecici=bool(yeni and not yeni["erken_uyari"]), gecis_adaylari=adaylar,
            gecis=(dict(tarih=gecis["tarih"], eski_ad=gecis["eski_ad"],
                        anahtar=[v["kisiler"][p]["ad"] for p in gecis["anahtar"]]) if gecis else None),
            azaltanlar=([f"Çağrıların {yuzde(h['oto_payi'], 'i')} otomasyonla kapanabiliyor"] if h["oto_payi"] else [])
            + (["Taslak otomatik çözüm var (adım adım rehber)"] if k["recete_turu"] == "taslak" else []),
        ))
    sonuc.sort(key=lambda r: (-r["puan"], r["ad"]))
    return sonuc


TAZELIK_GUN = 14   # bir kaynaktan bu kadar gündür kayıt gelmiyorsa o kaynağın konuları eksik veriyle hesaplanıyordur


def veri_tazeligi(con: sqlite3.Connection, simdi: datetime | None = None) -> list[dict]:
    """Her veri kaynağının (Usta, içe aktarılan dökümler) son kaydı. Döküm güncellenmezse son haftaların
    çözümleri eksik kalır; yetkinler azalmış görünür ve risk yapay olarak yükselir."""
    simdi = simdi or datetime.now()
    esik = (simdi - timedelta(days=PENCERE_GUN)).isoformat(timespec="minutes")
    sonuc = []
    for r in con.execute("SELECT kaynak, MAX(kapanis) son, SUM(kapanis>=?) pencere FROM cagri WHERE durum='kapali' "
                         "GROUP BY kaynak ORDER BY kaynak='usta' DESC, kaynak", (esik,)):
        gun = (simdi - datetime.fromisoformat(r["son"])).days if r["son"] else None
        sonuc.append(dict(kaynak="Usta" if r["kaynak"] == "usta" else r["kaynak"], son_kayit=r["son"], gun=gun,
                          pencerede=r["pencere"] or 0, eski=gun is not None and gun > TAZELIK_GUN))
    return sonuc


def ozet(harita: list[dict]) -> dict:
    return dict(
        ortalama=round(sum(r["puan"] for r in harita) / max(1, len(harita)), 1),
        kirmizi=sum(r["seviye"] == "kirmizi" for r in harita),
        sari=sum(r["seviye"] == "sari" for r in harita),
        yesil=sum(r["seviye"] == "yesil" for r in harita),
    )


def matris(con: sqlite3.Connection, simdi: datetime | None = None) -> list[dict]:
    """Birim bazında konu × kişi ısı haritası verisi."""
    v = _veri(con, simdi)
    harita = {r["kategori_id"]: r for r in risk_haritasi(con, _v=v)}
    birimler: dict[int, dict] = {}
    for k in v["kategoriler"]:
        b = birimler.setdefault(k["birim_id"], dict(
            birim=k["birim"], kisiler=[dict(id=p["id"], ad=p["ad"], vardiya=p["vardiya"])
                                       for p in v["kisiler"].values() if p["birim_id"] == k["birim_id"]],
            satirlar=[]))
        s, toplam = v["sayim"][k["id"]], sum(v["sayim"][k["id"]].values()) or 1
        r = harita[k["id"]]
        b["satirlar"].append(dict(
            kategori_id=k["id"], ad=k["ad"], puan=r["puan"], seviye=r["seviye"], nedenler=r["nedenler"],
            beyan_sayisi=r["beyan_sayisi"], gercek_sayisi=r["gercek_sayisi"],
            hucreler=[dict(n=s.get(p["id"], 0), pay=round(s.get(p["id"], 0) / toplam, 2),
                           beyan=p["id"] in v["beyan"][k["id"]],
                           eski=any(e["kisi_id"] == p["id"] for e in r["pratigi_kalmayan"])) for p in b["kisiler"]]))
    for b in birimler.values():
        b["satirlar"].sort(key=lambda x: -x["puan"])
    return list(birimler.values())


# ---------------------------------------------------------------- ya giderse

def ya_giderse(con: sqlite3.Connection, kisi_id: int, gun: int = 21, dakika_maliyeti: float = 0,
               simdi: datetime | None = None) -> dict:
    """Bir kişi 'gun' gün yoksa ne olur?

    Beklenen çağrı = konunun günlük çağrı sayısı × gün × kişinin o konudaki payı
    Süre çarpanı   = geride yetkin biri varsa 1,1 · yoksa ama kart varsa 1,5 · ikisi de yoksa 2,5
    Ek bekleme     = beklenen çağrı × konunun temel çözüm süresi × (çarpan − 1)
    """
    v = _veri(con, simdi)
    if kisi_id not in v["kisiler"]:
        raise ValueError("Kişi bulunamadı")
    gun = max(1, min(int(gun), 365))
    once = {r["kategori_id"]: r for r in risk_haritasi(con, _v=v)}
    sonra = {r["kategori_id"]: r for r in risk_haritasi(con, haric_kisi=kisi_id, _v=v)}
    etkilenen = []
    for k in v["kategoriler"]:
        s = v["sayim"][k["id"]]
        benim = s.get(kisi_id, 0)
        if not benim:
            continue
        toplam = sum(s.values())
        o, y = once[k["id"]], sonra[k["id"]]
        beklenen = toplam / PENCERE_GUN * gun * benim / toplam
        carpan = 1.1 if y["yetkin_sayisi"] >= 1 else (1.5 if k["kart_var"] else 2.5)
        ek_dk = beklenen * k["temel_sure_dk"] * (carpan - 1)
        etkilenen.append(dict(
            kategori_id=k["id"], ad=k["ad"], kritiklik=k["kritiklik"], pay=round(benim / toplam, 2),
            puan_once=o["puan"], puan_sonra=y["puan"], seviye_once=o["seviye"], seviye_sonra=y["seviye"],
            kalan_yetkin=y["yetkin_sayisi"], kalan_yetkinler=y["yetkinler"], kart_var=bool(k["kart_var"]),
            beklenen_cagri=round(beklenen, 1), sure_carpani=carpan, ek_dakika=round(ek_dk),
            yedeksiz=y["yetkin_sayisi"] == 0))
    etkilenen.sort(key=lambda e: (-e["puan_sonra"], -e["ek_dakika"]))
    toplam_dk = sum(e["ek_dakika"] for e in etkilenen)
    p = v["kisiler"][kisi_id]
    yedeksiz = [e["ad"] for e in etkilenen if e["yedeksiz"]]
    kizaran = [e["ad"] for e in etkilenen if e["seviye_sonra"] == "kirmizi" and e["seviye_once"] != "kirmizi"]
    # Kişiye bağlı olan yalnızca çağrı çözmek değil: bakımını yaptığı otomasyonlar bozulursa düzelten kalmaz
    otomasyonlar = [dict(kod=r["kod"], ad=r["ad"], tur=r["tur"]) for r in con.execute(
        "SELECT kod, ad, tur FROM recete WHERE sahip=? ORDER BY tur, ad", (v["kisiler"][kisi_id]["ad"],))]
    return dict(
        kisi=dict(id=kisi_id, ad=p["ad"], birim=p["birim"], rol=p["rol"], vardiya=p["vardiya"]), gun=gun,
        etkilenen=etkilenen, yedeksiz_kalan=yedeksiz, kirmiziya_donen=kizaran, otomasyonlar=otomasyonlar,
        beklenen_cagri=round(sum(e["beklenen_cagri"] for e in etkilenen), 1),
        ek_dakika=toplam_dk, ek_saat=round(toplam_dk / 60, 1),
        dakika_maliyeti=dakika_maliyeti, tl_etkisi=round(toplam_dk * dakika_maliyeti),
        ozet_once=ozet(list(once.values())), ozet_sonra=ozet(list(sonra.values())),
        ozet=(f"{p['ad']} {gun} gün yoksa {len(etkilenen)} konu etkilenir, "
              f"{len(yedeksiz)} konu yedeksiz kalır; beklenen ek bekleme {str(round(toplam_dk / 60, 1)).replace('.', ',')} saat."),
    )


# ---------------------------------------------------------------- eğitim planı

def _ogrenme_maliyeti(k: dict, ek: int, ucuzlar: list[float] | int = ()) -> int:
    """ek kişi eğitmenin saati. ucuzlar: daha ucuza öğrenecek adayların oranları, ucuzdan pahalıya
    (pratiği kalmamış yedek 1/3, eski sistemden gelen 1/2). Sonrakiler sıfırdan öğrenir."""
    if isinstance(ucuzlar, int):
        ucuzlar = [TAZELEME_ORANI] * ucuzlar
    ucuzlar = sorted(ucuzlar)
    return sum(max(1, math.ceil(k["ogrenme_saati"] * ucuzlar[i])) if i < len(ucuzlar) else k["ogrenme_saati"]
               for i in range(ek))


def _secenekler(k: dict, sayim: dict[int, int], eskiyen: list[float] | int = 0) -> list[dict]:
    """Bir konu için yapılabilecekler: kart yaz (2 saat) ve/veya 1-2 kişi eğit (pratiği kalmamış
    ya da eski sistemden gelen biri varsa önce o, daha ucuza öğrenir)."""
    simdiki = puan_hesapla(sayim, k["kritiklik"], bool(k["kart_var"]), oto_payi=k["oto_payi"])["ham"]
    liste = []
    for kart in ((False, True) if not k["kart_var"] else (False,)):
        for ek in (0, 1, 2):
            if not kart and not ek:
                continue
            saat = (KART_YAZMA_SAATI if kart else 0) + _ogrenme_maliyeti(k, ek, eskiyen)
            yeni = puan_hesapla(sayim, k["kritiklik"], bool(k["kart_var"]), ek, kart, oto_payi=k["oto_payi"])["ham"]
            if simdiki - yeni > 0.01:
                # Amaç: önce yeşil sınırının (35) üzerindeki riski düşürmek. Sınırın altındaki
                # düşüş de sayılır ama onda biri ağırlıkla; böylece plan önce kırmızıları söndürür.
                esik_ustu = max(0.0, simdiki - SARI) - max(0.0, yeni - SARI)
                liste.append(dict(kart=kart, ek=ek, saat=saat, dusus=simdiki - yeni,
                                  kazanc=esik_ustu + 0.1 * (simdiki - yeni)))
    return liste


def _kural_sec(konular: list[tuple[dict, list[dict]]], butce: int) -> dict[int, dict]:
    """Basit kural: her adımda 'saat başına en çok risk düşüren' ek adımı seç."""
    secim: dict[int, dict] = {}
    kalan = butce
    while True:
        en_iyi = None
        for k, secenekler in konular:
            mevcut = secim.get(k["id"], dict(saat=0, kazanc=0.0))
            for s in secenekler:
                ek_saat, ek_kazanc = s["saat"] - mevcut["saat"], s["kazanc"] - mevcut["kazanc"]
                if ek_saat <= 0 or ek_saat > kalan or ek_kazanc <= 0:
                    continue
                if "ek" in mevcut and (s["ek"] < mevcut["ek"] or (mevcut["kart"] and not s["kart"])):
                    continue  # verilen kararı geri alma
                oran = ek_kazanc / ek_saat
                if not en_iyi or oran > en_iyi[0]:
                    en_iyi = (oran, k["id"], s, ek_saat)
        if not en_iyi:
            return secim
        secim[en_iyi[1]] = en_iyi[2]
        kalan -= en_iyi[3]


def _optimum_sec(konular: list[tuple[dict, list[dict]]], butce: int) -> dict[int, dict]:
    """Çok seçenekli sırt çantası (dinamik programlama).

    Her konudan en fazla bir seçenek alınır; toplam saat bütçeyi aşmadan toplam risk düşüşü
    en büyük olan birleşim bulunur. dp[b] = b saatle ulaşılabilen en iyi kazanç.
    """
    dp = [0.0] * (butce + 1)
    iz: list[list[dict | None]] = []
    for _, secenekler in konular:
        yeni, sec = dp[:], [None] * (butce + 1)
        for s in secenekler:
            for b in range(s["saat"], butce + 1):
                aday = dp[b - s["saat"]] + s["kazanc"]
                if aday > yeni[b] + 1e-9:
                    yeni[b], sec[b] = aday, s
        dp = yeni
        iz.append(sec)
    secim, b = {}, max(range(butce + 1), key=lambda i: (dp[i], -i))
    for (k, _), sec in zip(reversed(konular), reversed(iz)):
        s = sec[b]
        if s:
            secim[k["id"]] = s
            b -= s["saat"]
    return secim


def egitim_plani(con: sqlite3.Connection, butce_saat: int = 40, yontem: str = "optimum",
                 kaydet: bool = False, simdi: datetime | None = None) -> dict:
    """Verilen saat bütçesiyle riski en çok düşüren kart yazma ve eğitim eşleşmeleri."""
    if yontem not in ("optimum", "kural"):
        raise ValueError("Yöntem 'optimum' veya 'kural' olmalı")
    butce = max(0, min(int(butce_saat), 500))
    v = _veri(con, simdi)
    eskiyen = {k["id"]: pratigi_kalmayanlar(v, k["id"]) for k in v["kategoriler"]}
    gecenler = {k["id"]: gecis_adaylari(v, k["id"]) for k in v["kategoriler"]}
    etkin = {k["id"]: etkin_sayim(v, k)[0] for k in v["kategoriler"]}
    konular = [(k, _secenekler(k, etkin[k["id"]], [TAZELEME_ORANI] * len(eskiyen[k["id"]])
                               + [GECIS_ORANI] * len(gecenler[k["id"]]))) for k in v["kategoriler"]]
    secimler = {"kural": _kural_sec(konular, butce), "optimum": _optimum_sec(konular, butce)}
    secim = secimler[yontem]

    once = risk_haritasi(con, _v=v)
    once_s = {r["kategori_id"]: r for r in once}
    sonra = risk_haritasi(con, _v=v, ek_yetkin={i: s["ek"] for i, s in secim.items() if s["ek"]},
                          ek_kart={i for i, s in secim.items() if s["kart"]})
    sonra_s = {r["kategori_id"]: r for r in sonra}

    # Kişi eşleştirme: öğreten = konuyu en çok çözen. Öğrenen = aynı birimde, konuda yetkin olmayan,
    # önce yetkin sayısı en az olan vardiyadan, sonra bu planda en az eğitim saati almış kişi.
    yuk: dict[int, int] = {}
    satirlar = []
    for k in sorted((k for k, _ in konular if k["id"] in secim), key=lambda k: -once_s[k["id"]]["puan"]):
        s, sayim = secim[k["id"]], etkin[k["id"]]
        sirali = sorted(v["sayim"][k["id"]].items(), key=lambda x: -x[1]) or sorted(sayim.items(), key=lambda x: -x[1])
        ogreten = sirali[0][0] if sirali else None
        if s["kart"]:
            satirlar.append(dict(kategori_id=k["id"], kategori=k["ad"], tur="kart", saat=KART_YAZMA_SAATI,
                                 ogreten_id=ogreten, ogreten=v["kisiler"][ogreten]["ad"] if ogreten else None,
                                 ogrenen_id=None, ogrenen=None, neden="Konunun yazılı çözümü yok"))
        yetkin = {p for p, n in sayim.items() if n >= yetkin_esigi(sum(sayim.values()))}
        kapsama = {vd: sum(1 for p in yetkin if v["kisiler"][p]["vardiya"] == vd) for vd in VARDIYALAR}
        adaylar = [p for p in v["kisiler"].values()
                   if p["birim_id"] == k["birim_id"] and p["id"] not in yetkin and p["id"] != ogreten]
        eski_ids = {e["kisi_id"]: e for e in eskiyen[k["id"]]}
        gecen_ids = {e["kisi_id"]: e for e in gecenler[k["id"]]}
        for _ in range(s["ek"]):
            if not adaylar:
                break
            # Önce pratiği kalmamış eski yedekler (tazeleme ucuz), sonra eski sistemden gelenler, sonra en zayıf vardiya
            adaylar.sort(key=lambda p: (p["id"] not in eski_ids, p["id"] not in gecen_ids, kapsama[p["vardiya"]],
                                        yuk.get(p["id"], 0), -sayim.get(p["id"], 0), p["id"]))
            p = adaylar.pop(0)
            if p["id"] in eski_ids:
                saat = max(1, math.ceil(k["ogrenme_saati"] * TAZELEME_ORANI))
                neden = f"Tazeleme: bu konuyu eskiden çözüyordu, son çözümü {eski_ids[p['id']]['ay_once']} ay önce"
            elif p["id"] in gecen_ids:
                saat = max(1, math.ceil(k["ogrenme_saati"] * GECIS_ORANI))
                neden = f"Geçiş eğitimi: eski sistemde ({v['gecis'][k['id']]['eski_ad']}) bu işi düzenli yapıyordu"
            else:
                saat = k["ogrenme_saati"]
                vardiya = {'gunduz': 'Gündüz', 'aksam': 'Akşam', 'gece': 'Gece'}[p['vardiya']]
                bilen = kapsama[p['vardiya']]
                neden = (f"{vardiya} vardiyasında bu konuyu bilen kimse yok" if bilen == 0
                         else f"{vardiya} vardiyasında bu konuyu yalnız {bilen} kişi biliyor")
            kapsama[p["vardiya"]] += 1
            yuk[p["id"]] = yuk.get(p["id"], 0) + saat
            satirlar.append(dict(kategori_id=k["id"], kategori=k["ad"],
                                 tur="tazeleme" if p["id"] in eski_ids else ("gecis" if p["id"] in gecen_ids else "egitim"),
                                 saat=saat, ogreten_id=ogreten, ogreten=v["kisiler"][ogreten]["ad"] if ogreten else None,
                                 ogrenen_id=p["id"], ogrenen=p["ad"], neden=neden))
    for r in satirlar:
        r["puan_once"], r["puan_sonra"] = once_s[r["kategori_id"]]["puan"], sonra_s[r["kategori_id"]]["puan"]

    if kaydet:
        con.execute("DELETE FROM egitim_plani WHERE durum='planlandi'")
        zaman = datetime.now().isoformat(timespec="minutes")
        for r in satirlar:
            con.execute("INSERT INTO egitim_plani(kategori_id,tur,ogreten_id,ogrenen_id,saat,olusturma,puan_once,puan_hedef)"
                        " VALUES(?,?,?,?,?,?,?,?)", (r["kategori_id"], r["tur"], r["ogreten_id"], r["ogrenen_id"],
                                                    r["saat"], zaman, r["puan_once"], r["puan_sonra"]))
        con.commit()

    def kazanc(sec):
        return round(sum(s["dusus"] for s in sec.values()), 1)

    def amac(sec):
        return round(sum(s["kazanc"] for s in sec.values()), 1)

    return dict(
        yontem=yontem, butce_saat=butce, kullanilan_saat=sum(r["saat"] for r in satirlar),
        satirlar=satirlar, ozet_once=ozet(once), ozet_sonra=ozet(sonra), harita_sonra=sonra,
        toplam_risk_dususu=kazanc(secim),
        karsilastirma={y: dict(amac_puani=amac(secimler[y]), risk_dususu=kazanc(secimler[y]),
                               saat=sum(s["saat"] for s in secimler[y].values())) for y in ("kural", "optimum")},
        kaydedildi=kaydet,
    )


def tek_kisiye_kalanlar(con: sqlite3.Connection, gun_sayisi: int = 7, simdi: datetime | None = None) -> dict:
    """Önümüzdeki günlerde izinler yüzünden yedeksiz veya tek kişiye kalan konular."""
    simdi = simdi or datetime.now()
    bas, bit = simdi.date().isoformat(), (simdi.date() + timedelta(days=max(0, gun_sayisi - 1))).isoformat()
    izinli = {r["kisi_id"]: dict(r) for r in con.execute(
        "SELECT m.kisi_id, m.baslangic, m.bitis, m.tur, p.ad FROM musaitlik m JOIN kisi p ON p.id=m.kisi_id "
        "WHERE m.baslangic<=? AND m.bitis>=?", (bit, bas))}
    v = _veri(con, simdi)
    konular = []
    for k in v["kategoriler"]:
        s = v["sayim"][k["id"]]
        yetkin = [p for p, n in s.items() if n >= yetkin_esigi(sum(s.values()))]
        kalan = [p for p in yetkin if p not in izinli]
        giden = [p for p in yetkin if p in izinli]
        if giden and len(kalan) <= 1:
            konular.append(dict(
                kategori_id=k["id"], ad=k["ad"], birim=k["birim"], kritiklik=k["kritiklik"],
                kart_var=bool(k["kart_var"]),
                izindeki_yetkinler=[v["kisiler"][p]["ad"] for p in giden],
                kalan_yetkinler=[v["kisiler"][p]["ad"] for p in kalan],
                durum="yedeksiz" if not kalan else "tek kişi"))
    konular.sort(key=lambda x: (x["durum"] != "yedeksiz", -x["kritiklik"]))
    return dict(baslangic=bas, bitis=bit,
                izinliler=[dict(ad=i["ad"], baslangic=i["baslangic"], bitis=i["bitis"], tur=i["tur"])
                           for i in izinli.values()], konular=konular)
