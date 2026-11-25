"""Sentetik veri üreticisi.

Aynı tohum ve aynı tarihle her zaman aynı veri çıkar. Tarihler "bugün"e göre geriye doğru üretilir.

İki kaynak üretilir:
  1. Usta çağrıları (sistemsel: BT Destek, Depo Sistemleri). Metni, alt sorunu, çözeni ve çoğunun
     çözüm notu vardır. Makine öğrenmesi modeli bunlardan öğrenir.
  2. Bakım sistemi dökümü (teknik: Bakım, İdari İşler, İSG). Yalnızca konu, çözen, tarih ve süre.
     Gerçek hayattaki gibi bir CSV olarak yazılır ve ice_aktar.yukle() ile Emanet'e alınır.

Veriye bilerek gömülen örüntüler (Emanet bunları bulmalı):
  - Sipariş dalgası   → neredeyse tek kişi (Elif Kaya, gündüz), çözüm notu az, kartı yok
  - ERP entegrasyonu  → neredeyse tek kişi (Murat Özkan), çözüm notu az, kartı yok
  - Sorter arızası    → dökümde neredeyse tek kişi (Kemal Yılmaz); kâğıtta 5 kişi yetkin
  - Kemal Yılmaz bugünden itibaren 2 hafta izinde (demo senaryosu)
  - ERP entegrasyonu  → Emre Çelik 100 günden önce düzenli yedekti, sonra bıraktı (pratiği kalmamış yedek)
Alt sorunların kendi uzmanı var (ör. yazıcının ağ sorunlarını Tolga ve Onur çözer); model kişiyi
yalnızca konudan değil, metindeki bu ayrıntıdan da öğrenebilmelidir.
"""
from __future__ import annotations

import csv
import io
import random
import re
import sqlite3
from datetime import date, datetime, timedelta

import json

from . import cagri_formu, ice_aktar, otomasyon
from .ogrenme import kucult
from . import katalog as K
from .db import bosalt, meta_yaz

# Demo verisinin biçimi değişince artırılır: sunucu yeniden başlarken gece beklemeden yeniden üretir
# (2: cihaz numaraları, 3: cihaz tablosu ve çağrı durumları, 4: kapanış onayı ve yeniden açılma geçmişi,
#  5: pazar kapalı, ilk tepki kayıtları, 6: tesisler ve ana kategoriler)
VERI_SURUMU = 6
VARDIYA_SAAT = {"gunduz": (8, 16), "aksam": (16, 24), "gece": (0, 8)}
TEK_KISI_ESIGI = 0.6
BAKIM_KAYNAGI = "Bakım sistemi dökümü"
ESKI_DONEM_GUN = 100   # agirlik_eski bu günden eski çağrılarda geçerli


def _paylar(k: dict, agirlik: dict | None, uyeler: list[str], rnd: random.Random, rastgele: dict) -> dict:
    if agirlik:
        diger = agirlik.get("*", 0)
        a = {u: agirlik.get(u, diger) for u in uyeler}
    else:
        a = rastgele
    toplam = sum(a.values())
    return {u: x / toplam for u, x in a.items()}


def _kisi_sec(pay: dict, vardiya: str, kisi_vardiya: dict, rnd: random.Random) -> str:
    """Uzmanlaşma güçlüyse (tek kişiye yığılma) vardiyaya bakılmaz: iş uzmanını bekler.
    Değilse çağrıyı o vardiyada çalışanlardan biri çözer."""
    if max(pay.values()) < TEK_KISI_ESIGI:
        vd = {u: p for u, p in pay.items() if kisi_vardiya[u] == vardiya and p > 0}
        if vd:
            pay = vd
    return rnd.choices(list(pay), weights=list(pay.values()))[0]


def _yazim_hatasi(s: str, rnd: random.Random) -> str:
    """Hızlı yazılmış çağrılar: bir sözcükten bir harf düşer."""
    sozcukler = s.split()
    uzun = [i for i, w in enumerate(sozcukler) if len(w) > 5]
    if uzun:
        i = rnd.choice(uzun)
        j = rnd.randrange(1, len(sozcukler[i]) - 1)
        sozcukler[i] = sozcukler[i][:j] + sozcukler[i][j + 1:]
    return " ".join(sozcukler)


def _metin(sablonlar: list[str], rnd: random.Random) -> str:
    if rnd.random() < 0.06:                       # ayrıntısız çağrı
        sablonlar = K.GENEL_SABLONLAR
    s = rnd.choice(sablonlar).format(yer=rnd.choice(K.YERLER), no=rnd.randint(1, 48),
                                     yazilim=rnd.choice(K._YAZILIM_ADLARI), pc=f"PC-{rnd.randint(1000, 1999)}",
                                     rol=rnd.choice(K.ROL_KATALOGU)["ad"].lower())
    if rnd.random() < 0.15:
        s = _yazim_hatasi(s, rnd)
    on, son = rnd.choice(K.ON_EKLER), rnd.choice(K.SON_EKLER)
    if on and not on.endswith("! ") and s[0] not in "İI":
        s = s[0].lower() + s[1:]
    return f"{on}{s}{son}"


def _zamanlar(adet: int, gun: int, bugun: date, rnd: random.Random) -> list[tuple[datetime, str]]:
    """Son 'gun' güne yayılmış açılış zamanları; son 3 hafta yoğun sezon (1,6 kat)."""
    agirlik = [1.6 if g <= 21 else 1.0 for g in range(1, gun + 1)]
    sonuc = []
    for _ in range(adet):
        g = rnd.choices(range(1, gun + 1), weights=agirlik)[0]
        vardiya = rnd.choices(["gunduz", "aksam", "gece"], weights=[45, 35, 20])[0]
        b, s = VARDIYA_SAAT[vardiya]
        an = datetime.combine(bugun - timedelta(days=g), datetime.min.time()) + timedelta(
            hours=rnd.randrange(b, s), minutes=rnd.randrange(60))
        sonuc.append((an, vardiya))
    return sorted(sonuc)


def bakim_dokumu_csv(bugun: date, tohum: int = 42, adet: int = 650, gun: int = 180) -> str:
    """Teknik çağrıların bakım sisteminden alınmış gibi görünen CSV dökümü."""
    rnd = random.Random(tohum + 1)
    kisi_vardiya = {ad: v for ad, _, _, v in K.KISILER}
    uyeler = {b: [ad for ad, bb, _, _ in K.KISILER if bb == b] for b in K.BIRIMLER}
    paylar = {k["kod"]: _paylar(k, k.get("agirlik"), uyeler[k["birim"]], rnd,
                                {u: rnd.uniform(3, 10) for u in uyeler[k["birim"]]}) for k in K.TEKNIK_KATEGORILER}
    cikti = io.StringIO()
    w = csv.writer(cikti, delimiter=";")
    w.writerow(["tarih", "birim", "konu", "cozen", "sure_dk", "vardiya", "kritiklik", "ogrenme_saati", "talimat_var"])
    hacim = [k["hacim"] for k in K.TEKNIK_KATEGORILER]
    for an, vardiya in _zamanlar(adet, gun, bugun, rnd):
        k = rnd.choices(K.TEKNIK_KATEGORILER, weights=hacim)[0]
        cozen = _kisi_sec(paylar[k["kod"]], vardiya, kisi_vardiya, rnd)
        sure = k["sure"] * rnd.lognormvariate(0, 0.35)
        if paylar[k["kod"]][cozen] < 0.10:
            sure *= 1.5
        if kisi_vardiya[cozen] != vardiya:
            sure += rnd.uniform(120, 480)
        w.writerow([an.strftime("%Y-%m-%d %H:%M"), k["birim"], k["ad"], cozen, max(3, round(sure)),
                    kisi_vardiya[cozen], k["kritiklik"], k["ogrenme"], int(bool(k.get("kart")))])
    return cikti.getvalue()


def _cihaz_ata(con: sqlite3.Connection, bugun: date, tohum: int) -> None:
    """Yazıcı ve terminal çağrılarına envanterden cihaz numarası verir. Ayrı tohum: diğer verinin
    sırası değişmesin. Son 30 günde birkaç cihaz sık arızalanır (tekrarlayan arıza uyarısı için)."""
    rnd = random.Random(tohum + 7)
    lok = {r["ad"]: r["id"] for r in con.execute("SELECT id, ad FROM lokasyon")}
    con.executemany("INSERT INTO cihaz(no,tur,model,yer,guncelleme,lokasyon_id) VALUES(?,?,?,?,?,?)",
                    [(n, d["tur"], d["model"], d["yer"], bugun.isoformat(), lok[d["lokasyon"]]) for n, d in K.CIHAZLAR.items()])
    lok_ad = {v: k for k, v in lok.items()}
    son30 = (datetime.combine(bugun, datetime.min.time()) - timedelta(days=30)).isoformat(timespec="minutes")
    for kod, onek in K.CIHAZ_KONULARI.items():
        cihazlar = [n for n in K.CIHAZLAR if n.startswith(onek + "-")]
        for c in con.execute("SELECT c.id, c.acilis, c.metin, c.lokasyon_id FROM cagri c JOIN kategori k ON k.id=c.kategori_id "
                             "WHERE k.kod=?", (kod,)).fetchall():
            tesis = lok_ad.get(c["lokasyon_id"], K.LOKASYONLAR[0])   # cihaz çağrının tesisinde olmalı
            # Metinde yer geçiyorsa o yerdeki cihazlardan biri (yazıcı sabittir; geçmişte yer çelişmesin)
            m = kucult(c["metin"])
            if "irsaliye" in m or "yeni etiket" in m:   # A4 yazıcı ya da henüz envantere girmemiş yeni cihaz
                continue
            no = re.search(r"(\d+)\s*(?:no|numara)", m)   # "17 no'lu", "8 numaralı": metindeki numara esas
            if no:
                n = cagri_formu.cihaz_no(f"{onek}{no.group(1)}")
                if n in K.CIHAZLAR and K.CIHAZLAR[n]["lokasyon"] == tesis:
                    con.execute("UPDATE cagri SET cihaz=? WHERE id=?", (n, c["id"]))
                continue                                    # envanterde yoksa uydurma numara verme
            yer = next((y for y in K.YERLER if kucult(y) in m), None)
            if not yer and any(max(kucult(y).split(), key=len)[:4] in m for y in K.YERLER):
                continue                                    # yer yazım hatalı geçiyor: emin olmadan cihaz verme
            tesiste = [n for n in cihazlar if K.CIHAZLAR[n]["lokasyon"] == tesis]
            aday = [n for n in tesiste if yer and K.CIHAZLAR[n]["yer"] == yer] or \
                   [n for n in tesiste if not yer or K.CIHAZLAR[n]["yer"] is None]
            if not aday:   # metindeki yerde bu türden cihaz yok: yeri bilinen bir cihaza değil, yersiz kalsın
                continue
            agirlik = [K.SORUNLU_CIHAZLAR.get(n, 1) if c["acilis"] >= son30 else 1 for n in aday]
            con.execute("UPDATE cagri SET cihaz=? WHERE id=?", (rnd.choices(aday, weights=agirlik)[0], c["id"]))


def _lokasyon_ata(con: sqlite3.Connection, tohum: int) -> None:
    """Çağrının tesisi: yerinde bakılan işler (cihaz, ağ) o tesisteki kişi tarafından çözülmüştür; program ve hesap
    işleri merkezden uzaktan çözülür, bu yüzden bir kısmı diğer tesislerden gelmiştir. Ayrı tohum."""
    rnd = random.Random(tohum + 13)
    lok = {r["ad"]: r["id"] for r in con.execute("SELECT id, ad FROM lokasyon")}
    merkez, diger = lok[K.LOKASYONLAR[0]], [lok[a] for a in K.LOKASYONLAR[1:]]
    kisi_lok = {r["id"]: r["lokasyon_id"] for r in con.execute("SELECT id, lokasyon_id FROM kisi")}
    for c in con.execute("SELECT c.id, COALESCE(c.cozen_kisi_id, c.atanan_kisi_id) k, g.grup FROM cagri c "
                         "JOIN kategori g ON g.id=c.kategori_id WHERE c.kaynak='usta'").fetchall():
        kl = kisi_lok.get(c["k"], merkez)
        if kl != merkez:
            l = kl
        elif c["grup"] in K.YERINDE_GRUPLAR:
            l = merkez
        else:
            l = rnd.choice(diger) if rnd.random() < 0.2 else merkez
        con.execute("UPDATE cagri SET lokasyon_id=? WHERE id=?", (l, c["id"]))


def _pazari_kaydir(con: sqlite3.Connection, bugun: date) -> None:
    """Depo pazar kapalı (6 gün, 3 vardiya): pazara düşen geçmiş çağrılar aynı saatte pazartesiye alınır.
    Üretimden sonra kaydırılır ki diğer verinin rastgele sırası (ve ona göre kurulmuş senaryolar) değişmesin."""
    gun = "+1 day"
    # Yalnız geçmiş günler: sıfırlama pazar günü çalışırsa bugünün açık çağrıları geleceğe kaymasın
    ids = [r[0] for r in con.execute("SELECT id FROM cagri WHERE kaynak='usta' AND strftime('%w', acilis)='0' AND date(acilis)<?",
                                     (bugun.isoformat(),))]
    for i in ids:
        con.execute("UPDATE cagri SET acilis=strftime('%Y-%m-%dT%H:%M', acilis, ?), "
                    "kapanis=CASE WHEN kapanis IS NULL THEN NULL ELSE strftime('%Y-%m-%dT%H:%M', kapanis, ?) END WHERE id=?",
                    (gun, gun, i))
        con.execute("UPDATE cagri_olay SET zaman=strftime('%Y-%m-%dT%H:%M', zaman, ?) WHERE cagri_id=?", (gun, i))
    # Cumartesi açılıp pazara sarkan çağrı pazar çözülmez, pazartesi çözülür (süreye kapalı gün eklenir)
    for r in con.execute("SELECT id FROM cagri WHERE kaynak='usta' AND kapanis IS NOT NULL AND strftime('%w', kapanis)='0' "
                         "AND date(kapanis)<?", (bugun.isoformat(),)).fetchall():
        con.execute("UPDATE cagri SET kapanis=strftime('%Y-%m-%dT%H:%M', kapanis, '+1 day'), sure_dk=sure_dk+1440 WHERE id=?", (r[0],))
        con.execute("UPDATE cagri_olay SET zaman=strftime('%Y-%m-%dT%H:%M', zaman, '+1 day') WHERE cagri_id=? AND tur='kapandi'", (r[0],))


def _kalite_gecmisi(con: sqlite3.Connection, tohum: int) -> None:
    """Geçmiş çağrılara kapanış onayı ve "ilk seferde çözülmedi" izi (ölçüler ekranı için). Ayrı tohum.
    Açanların çoğu onaylar, bir kısmı cevap vermez; kişi başına %1-8 çağrı ilk çözümden sonra yeniden açılmıştır."""
    rnd = random.Random(tohum + 11)
    oran = {}
    vardiya = {r["id"]: r["vardiya"] for r in con.execute("SELECT id, vardiya FROM kisi")}
    for c in con.execute("SELECT id, acilis, kapanis, sure_dk, cozen_kisi_id, acan_kisi FROM cagri "
                         "WHERE kaynak='usta' AND durum='kapali' ORDER BY id").fetchall():
        # İlk tepki: çözen kendi vardiyasında (pazar değil) birkaç dakika içinde işleme alır
        if rnd.random() < 0.8 and c["kapanis"]:
            b0, b1 = VARDIYA_SAAT[vardiya.get(c["cozen_kisi_id"], "gunduz")]
            t = datetime.fromisoformat(c["acilis"]) + timedelta(minutes=rnd.randint(3, 20))
            for _ in range(9):
                if b0 <= t.hour < b1 and t.weekday() != 6:
                    break
                ertesi = t.replace(hour=b0, minute=0) + (timedelta(days=1) if t.hour >= b0 else timedelta())
                t = ertesi + timedelta(minutes=rnd.randint(3, 15))
            if t < datetime.fromisoformat(c["kapanis"]):
                con.execute("INSERT INTO cagri_olay(cagri_id,zaman,tur,kisi_id,aciklama) VALUES(?,?,?,?,?)",
                            (c["id"], t.isoformat(timespec="minutes"), "durum", c["cozen_kisi_id"], "Atandı → İşlemde"))
        k = c["cozen_kisi_id"]
        if k not in oran:
            oran[k] = rnd.uniform(0.01, 0.08)
        if rnd.random() < oran[k]:
            an = datetime.fromisoformat(c["acilis"]) + timedelta(minutes=max(1, c["sure_dk"] * 0.4))
            con.execute("INSERT INTO cagri_olay(cagri_id,zaman,tur,kisi_id,aciklama) VALUES(?,?,?,?,?)",
                        (c["id"], an.isoformat(timespec="minutes"), "yeniden_acildi", k,
                         "Açan kişi çözülmedi dedi; ilk çözüm tutmadı"))
        if c["acan_kisi"] and rnd.random() < 0.82:
            con.execute("UPDATE cagri SET teyit=1 WHERE id=?", (c["id"],))


def uret(con: sqlite3.Connection, bugun: date | None = None, tohum: int = 42,
         adet: int = 900, gun: int = 180) -> dict:
    bugun = bugun or date.today()
    rnd = random.Random(tohum)
    bosalt(con)
    cur = con.cursor()

    birim_id = {}
    for ad in K.BIRIMLER:
        cur.execute("INSERT INTO birim(ad) VALUES(?)", (ad,))
        birim_id[ad] = cur.lastrowid
    lok_id = {}
    for ad in K.LOKASYONLAR:
        cur.execute("INSERT INTO lokasyon(ad) VALUES(?)", (ad,))
        lok_id[ad] = cur.lastrowid
    kisi_id, kisi_vardiya, uyeler = {}, {}, {b: [] for b in K.BIRIMLER}
    for ad, birim, rol, vardiya in K.KISILER:
        cur.execute("INSERT INTO kisi(ad,birim_id,rol,vardiya,lokasyon_id) VALUES(?,?,?,?,?)",
                    (ad, birim_id[birim], rol, vardiya, lok_id[K.KISI_LOKASYON.get(ad, K.LOKASYONLAR[0])]))
        kisi_id[ad], kisi_vardiya[ad] = cur.lastrowid, vardiya
        uyeler[birim].append(ad)

    # --- Usta konuları, alt sorunlar, yazılı kartlar, beyan edilen yetkinlik
    kart_tarihi = datetime.combine(bugun - timedelta(days=gun - 30), datetime.min.time()).replace(hour=10)
    kat = []
    for k in K.USTA_KATEGORILERI:
        cur.execute(
            "INSERT INTO kategori(kod,ad,birim_id,kritiklik,anahtar_kelimeler,aciklama,ogrenme_saati,temel_sure_dk,kaynak)"
            " VALUES(?,?,?,?,?,?,?,?,'usta')",
            (k["kod"], k["ad"], birim_id[k["birim"]], k["kritiklik"], k["anahtar"], k["aciklama"], k["ogrenme"], k["sure"]))
        kid = cur.lastrowid
        cur.execute("UPDATE kategori SET grup=? WHERE id=?", (K.KONU_GRUBU.get(k["kod"]), kid))
        ust = uyeler[k["birim"]]
        rastgele = {u: rnd.uniform(3, 10) for u in ust}
        genel = _paylar(k, k.get("agirlik"), ust, rnd, rastgele)
        altlar = [dict(a, pay=_paylar(k, a.get("agirlik") or k.get("agirlik"), ust, rnd, rastgele),
                       pay_eski=_paylar(k, k["agirlik_eski"], ust, rnd, rastgele) if k.get("agirlik_eski") else None)
                  for a in k["alt"]]
        beyan = k.get("beyan") or [u for u in ust if genel[u] >= 0.08]
        for u in beyan:
            cur.execute("INSERT INTO yetkinlik_beyan(kisi_id,kategori_id) VALUES(?,?)", (kisi_id[u], kid))
        kart_id = None
        if k.get("kart"):
            yazan = max(genel, key=genel.get)
            cur.execute("INSERT INTO cozum_karti(kategori_id,baslik,adimlar,kok_neden,yazan_kisi_id,olusturma) VALUES(?,?,?,?,?,?)",
                        (kid, k["kart"]["baslik"], k["kart"]["adimlar"], k["kart"]["kok_neden"], kisi_id[yazan],
                         kart_tarihi.isoformat(timespec="minutes")))
            kart_id = cur.lastrowid
        kat.append(dict(k, id=kid, altlar=altlar, kart_id=kart_id))

    def olay(cagri_id, zaman, tur, kisi=None, aciklama=None):
        cur.execute("INSERT INTO cagri_olay(cagri_id,zaman,tur,kisi_id,aciklama) VALUES(?,?,?,?,?)",
                    (cagri_id, zaman.isoformat(timespec="minutes"), tur, kisi, aciklama))

    def aciliyet(k):
        return rnd.choices([1, 2, 3], weights={1: [6, 3, 1], 2: [2, 5, 3], 3: [1, 3, 6]}[k["kritiklik"]])[0]

    # --- Usta: kapalı çağrılar
    hacim = [k["hacim"] for k in kat]
    for acilis, vardiya in _zamanlar(adet, gun, bugun, rnd):
        k = rnd.choices(kat, weights=hacim)[0]
        alt = rnd.choice(k["altlar"])
        # Görev değişikliği: bazı konularda eskiden başka bir yedek de çözüyordu (bkz. agirlik_eski)
        pay = alt["pay_eski"] if (alt["pay_eski"] and acilis.date() < bugun - timedelta(days=ESKI_DONEM_GUN)) else alt["pay"]
        cozen = _kisi_sec(pay, vardiya, kisi_vardiya, rnd)
        kart = k["kart_id"] if (k["kart_id"] and acilis > kart_tarihi and rnd.random() < 0.6) else None
        sure = k["sure"] * rnd.lognormvariate(0, 0.35) * (0.65 if kart else 1)
        if pay[cozen] < 0.10:
            sure *= 1.5
        if kisi_vardiya[cozen] != vardiya:
            sure += rnd.uniform(120, 480)
        sure = max(3, round(sure))
        # Çözüm notu: çoğu kişi yazar; tek uzmanlı konularda uzman pek yazmaz
        not_orani = k.get("not_orani", 0.75)
        cozum = rnd.choices(alt["cozum"], weights=[3] + [1] * (len(alt["cozum"]) - 1))[0] \
            if rnd.random() < not_orani else None
        # İlk yönlendirme: o dönemki kural tabanlı sistem %88 doğru, kalanı yeniden atanmış
        yeniden = rnd.random() > 0.88
        cur.execute(
            "INSERT INTO cagri(metin,acan_birim,aciliyet,kategori_id,onerilen_kategori_id,guven,durum,atanan_kisi_id,"
            "cozen_kisi_id,acilis,kapanis,sure_dk,kart_id,yeniden_atama,vardiya,cozum_notu,kaynak,acan_kisi)"
            " VALUES(?,?,?,?,?,NULL,'kapali',?,?,?,?,?,?,?,?,?,'usta',?)",
            (_metin(alt["sablonlar"], rnd), acan := rnd.choice(K.ACAN_BIRIMLER), aciliyet(k), k["id"], k["id"],
             kisi_id[cozen], kisi_id[cozen], acilis.isoformat(timespec="minutes"),
             (acilis + timedelta(minutes=sure)).isoformat(timespec="minutes"), sure, kart, int(yeniden), vardiya, cozum,
             rnd.choice(K.ACAN_KISILER[acan])))
        cid = cur.lastrowid
        olay(cid, acilis, "acildi")
        if yeniden:
            ilk = rnd.choice([u for u in uyeler[k["birim"]] if u != cozen])
            olay(cid, acilis, "atandi", kisi_id[ilk])
            olay(cid, acilis + timedelta(minutes=rnd.randint(5, 40)), "yeniden_atandi", kisi_id[cozen], "Yanlış kişiye gitmişti")
        else:
            olay(cid, acilis, "atandi", kisi_id[cozen])
        olay(cid, acilis + timedelta(minutes=sure), "kapandi", kisi_id[cozen])

    # --- izinler
    def izin(ad, bas, bit, tur="izin"):
        cur.execute("INSERT INTO musaitlik(kisi_id,baslangic,bitis,tur) VALUES(?,?,?,?)",
                    (kisi_id[ad], (bugun + timedelta(days=bas)).isoformat(), (bugun + timedelta(days=bit)).isoformat(), tur))
    izin("Kemal Yılmaz", -1, 12)
    izin("Zeynep Aydın", 0, 2, "rapor")
    izin("Sibel Yavuz", 3, 7)
    izin("Onur Yıldız", -30, -24)
    izin("Elif Kaya", -75, -66)

    # --- Usta: bugünün açık çağrıları
    izinli = {"Kemal Yılmaz", "Zeynep Aydın"}
    for _ in range(12):
        k = rnd.choices(kat, weights=hacim)[0]
        alt = rnd.choice(k["altlar"])
        acilis = datetime.combine(bugun, datetime.min.time()) + timedelta(hours=rnd.randrange(0, 8), minutes=rnd.randrange(60))
        aday = {u: p for u, p in alt["pay"].items() if u not in izinli and p > 0}
        atanan = rnd.choices(list(aday), weights=list(aday.values()))[0]
        cur.execute(
            "INSERT INTO cagri(metin,acan_birim,aciliyet,kategori_id,onerilen_kategori_id,durum,atanan_kisi_id,acilis,vardiya,kaynak,acan_kisi)"
            " VALUES(?,?,?,?,?,'acik',?,?,'gece','usta',?)",
            (_metin(alt["sablonlar"], rnd), acan := rnd.choice(K.ACAN_BIRIMLER), aciliyet(k), k["id"], k["id"], kisi_id[atanan],
             acilis.isoformat(timespec="minutes"), rnd.choice(K.ACAN_KISILER[acan])))
        cid = cur.lastrowid
        olay(cid, acilis, "acildi")
        olay(cid, acilis, "atandi", kisi_id[atanan])
    _pazari_kaydir(con, bugun)
    _lokasyon_ata(con, tohum)
    _cihaz_ata(con, bugun, tohum)
    _kalite_gecmisi(con, tohum)
    # Durumlar: açık çağrıların bir kısmına başlanmış, birinde açana soru sorulmuş (cevap bekleniyor)
    acik = con.execute("SELECT id, acilis, atanan_kisi_id, acan_kisi FROM cagri WHERE durum='acik' ORDER BY id").fetchall()
    for i, c in enumerate(acik[:3]):
        an = datetime.fromisoformat(c["acilis"]) + timedelta(minutes=20)
        if i == 2 and c["acan_kisi"]:
            soru = "Hata ekranının fotoğrafını gönderebilir misiniz? Hangi cihazda oluyor?"
            cur.execute("INSERT INTO mesaj(cagri_id,kime,rol,tur,metin,secenekler,serbest,zaman) VALUES(?,?,?,?,?,?,1,?)",
                        (c["id"], c["acan_kisi"], "talep_eden", "soru", f"#{c['id']} numaralı çağrınız için: {soru}", "[]",
                         an.isoformat(timespec="seconds")))
            cur.execute("UPDATE cagri SET asama='bilgi_bekleniyor' WHERE id=?", (c["id"],))
            olay(c["id"], an, "durum", c["atanan_kisi_id"], "Atandı → Bilgi bekleniyor: " + soru)
        else:
            cur.execute("UPDATE cagri SET asama='islemde' WHERE id=?", (c["id"],))
            olay(c["id"], an, "durum", c["atanan_kisi_id"], "Atandı → İşlemde")
    con.commit()

    # --- Teknik konular: bakım sisteminden gelen döküm, içe aktarma yoluyla
    dokum = ice_aktar.yukle(con, bakim_dokumu_csv(bugun, tohum), BAKIM_KAYNAGI)
    # Dökümün bilmediği tek şey kâğıt üzerindeki beyan; demo için sorter beyanı eklenir
    sorter = con.execute("SELECT id FROM kategori WHERE ad='Sorter arızası'").fetchone()["id"]
    for k in K.TEKNIK_KATEGORILER:
        if k.get("beyan"):
            kid = con.execute("SELECT id FROM kategori WHERE ad=?", (k["ad"],)).fetchone()["id"]
            con.executemany("INSERT OR IGNORE INTO yetkinlik_beyan(kisi_id,kategori_id) VALUES(?,?)",
                            [(kisi_id[u], kid) for u in k["beyan"]])
    con.commit()

    # --- Otomasyon: talep edenlerin hesapları, lisans havuzu, reçeteler
    sira = 0
    for birim, adlar in K.ACAN_KISILER.items():
        for ad in adlar:
            sira += 1
            yazilim = ["7-Zip"] if sira % 3 == 0 else []
            con.execute("INSERT INTO hesap(ad,birim,gorev,sicil,cihaz,roller,yazilimlar) VALUES(?,?,?,?,?,?,?)",
                        (ad, birim, "Operasyon personeli", f"{10400 + sira * 37}", f"PC-{1100 + sira * 7}",
                         json.dumps([f"{birim} kullanıcısı"], ensure_ascii=False), json.dumps(yazilim)))
    for y in K.YAZILIM_KATALOGU:
        if y["lisans"] is not None:   # Acrobat'ın bütün lisansları dolu: "lisans yok" senaryosu için
            con.execute("INSERT INTO lisans(yazilim,toplam,kullanilan) VALUES(?,?,?)",
                        (y["ad"], y["lisans"], y["lisans"] if "Acrobat" in y["ad"] else y["lisans"] - 3))
    otomasyon.recete_tanimlarini_yukle(con, f"{bugun.isoformat()}T00:00:00")   # otomasyon bugün devreye girdi
    # Eğitim süreleri: alan uzmanı gözüyle girilmiş değerler (katalog.UZMAN_SURELERI). Yeni açılan konular
    # bu listede olmadığı için süresi girilene kadar "tahmini" kalır.
    for ad, (kart, ogr, _) in K.UZMAN_SURELERI.items():
        con.execute("UPDATE kategori SET kart_saat=?, ogrenme_saati=?, sure_onay=1 WHERE ad=?", (kart, ogr, ad))
    con.commit()

    meta_yaz(con, "uretim_tarihi", bugun.isoformat())
    meta_yaz(con, "veri_surumu", str(VERI_SURUMU))
    meta_yaz(con, "tohum", str(tohum))
    return {"usta_cagri": adet + 12, "dokum_kaydi": dokum["satir"], "kisi": len(K.KISILER),
            "kategori": len(K.KATEGORILER), "birim": len(K.BIRIMLER), "tarih": bugun.isoformat(), "sorter_id": sorter}


if __name__ == "__main__":
    from .db import baglan
    print(uret(baglan()))
