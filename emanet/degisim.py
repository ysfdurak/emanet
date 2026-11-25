"""Değişimler: sistem geçişi, yeni personel, ayrılan personel.

Risk haritası geçmiş çağrılardan beslenir; bu yüzden ekipte ya da sistemde bir şey değiştiğinde
geçmiş ya yanıltır ya da hiç yoktur. Bu modül değişimi kayda geçirir, risk.py ve ogrenme.py de buna
göre davranır:

  gecis_kaydet     Eski konu (ör. eski rapor küpü) geçiş günü kapanır, yerine yeni konu açılır.
                   Açık çağrılar yeni konuya taşınır. Eski sistemde bu işi yapanlar "geçiş adayı" olur.
                   Eski konuya bağlı otomasyon reçeteleri yeni sisteme uyarlanana kadar çalışmaz.
  gecisler         Her geçişin durumu: kaç gün oldu, kaç çağrı geldi, bilgi kimde toplanıyor, kim geçti.
  gecis_simule_et  DEMO: 40 gün önce rapor küpünden Power BI'a geçilmiş gibi veriyi düzenler.
  kisi_ekle        Yeni personel. Yedek sayılmaz; 3 çözümle yetkin olur. Çırak modu ona çağrı verir.
  ise_alisma       Yeni personelin konu konu ilerlemesi: kaç çözüm, yetkinliğe ne kaldı.
  kisi_ayrildi     Gerçek ayrılış: kişi pasif olur, açık çağrıları yeniden yönlendirilir.
"""
from __future__ import annotations

import json
import random
import re
import sqlite3
from datetime import date, datetime, timedelta

from . import risk

YENI_PERSONEL_GUN = 90


def _bugun() -> str:
    return date.today().isoformat()


def _tarih(s) -> str:
    try:
        return date.fromisoformat(str(s)[:10]).isoformat()
    except ValueError:
        raise ValueError("Tarih YYYY-AA-GG biçiminde olmalı")


def _kod(con, ad: str) -> str:
    harf = str.maketrans("çğıöşüÇĞİÖŞÜ", "cgiosuCGIOSU")
    taban = re.sub(r"[^A-Z0-9]+", "_", ad.translate(harf).upper()).strip("_")[:24].strip("_") or "YENI_KONU"
    kod, i = taban, 2
    while con.execute("SELECT 1 FROM kategori WHERE kod=?", (kod,)).fetchone():
        kod, i = f"{taban}_{i}", i + 1
    return kod


# ---------------------------------------------------------------- sistem geçişi

def gecis_kaydet(con: sqlite3.Connection, yeni_ad: str, tarih=None, eski_kategori_id: int | None = None,
                 anahtar_kisiler: list[int] | None = None, aciklama: str = "", kritiklik: int | None = None,
                 anahtar_kelimeler: str = "", birim_id: int | None = None) -> dict:
    """Sistem geçişini kaydeder. eski_kategori_id verilirse o konu geçiş günü kapanır; yeni konu onun
    birimini, kritikliğini ve sürelerini devralır (değiştirilebilir). Öncülsüz yeni bir sistemde birim_id gerekir."""
    yeni_ad = (yeni_ad or "").strip()
    if len(yeni_ad) < 3:
        raise ValueError("Yeni konunun adı gerekli")
    tarih = _tarih(tarih or _bugun())
    anahtar = [int(x) for x in (anahtar_kisiler or [])]
    for p in anahtar:
        if not con.execute("SELECT 1 FROM kisi WHERE id=? AND aktif=1", (p,)).fetchone():
            raise ValueError("Anahtar kullanıcı bulunamadı")
    eski = None
    if eski_kategori_id:
        eski = con.execute("SELECT * FROM kategori WHERE id=?", (eski_kategori_id,)).fetchone()
        if not eski:
            raise ValueError("Eski konu bulunamadı")
        if eski["emeklilik"]:
            raise ValueError(f"'{eski['ad']}' konusu zaten {eski['emeklilik']} tarihinde kapanmış")
        eski = dict(eski)
    elif not birim_id:
        raise ValueError("Öncülü olmayan yeni bir sistem için birim seçin")
    kaynak = dict(eski) if eski else dict(birim_id=birim_id, kritiklik=kritiklik or 2, ogrenme_saati=12,
                                           temel_sure_dk=30, kaynak="usta", anahtar_kelimeler="", aciklama="")
    kritiklik = int(kritiklik or kaynak["kritiklik"])
    if kritiklik not in (1, 2, 3):
        raise ValueError("Kritiklik 1, 2 veya 3 olmalı")
    kelimeler = ",".join(dict.fromkeys(x.strip() for x in (anahtar_kelimeler + "," + kaynak["anahtar_kelimeler"]).split(",")
                                       if x.strip()))
    kod = _kod(con, yeni_ad)
    cur = con.execute(
        "INSERT INTO kategori(kod,ad,birim_id,kritiklik,anahtar_kelimeler,aciklama,ogrenme_saati,temel_sure_dk,kaynak,acilis)"
        " VALUES(?,?,?,?,?,?,?,?,?,?)",
        (kod, yeni_ad, kaynak["birim_id"], kritiklik, kelimeler or yeni_ad.lower(),
         (f"{eski['aciklama']} (yeni sistem: {yeni_ad})" if eski else (aciklama or yeni_ad)),
         kaynak["ogrenme_saati"], kaynak["temel_sure_dk"], kaynak["kaynak"], tarih))
    yeni_id = cur.lastrowid
    tasinan = 0
    if eski:
        con.execute("UPDATE kategori SET emeklilik=? WHERE id=?", (tarih, eski["id"]))
        # Geçişten sonra açılmış ya da hâlâ açık olan çağrılar yeni sisteme aittir.
        tasinan = con.execute("UPDATE cagri SET kategori_id=? WHERE kategori_id=? AND (durum='acik' OR acilis>=?)",
                              (yeni_id, eski["id"], tarih)).rowcount
    con.execute("INSERT INTO gecis(eski_kategori_id,yeni_kategori_id,tarih,aciklama,anahtar_kisiler,olusturma)"
                " VALUES(?,?,?,?,?,?)", (eski["id"] if eski else None, yeni_id, tarih, aciklama, json.dumps(anahtar),
                                         datetime.now().isoformat(timespec="minutes")))
    con.commit()
    receteler = [r["ad"] for r in con.execute("SELECT ad FROM recete WHERE kategori_kod=?", (eski["kod"],))] if eski else []
    return dict(yeni_kategori_id=yeni_id, kod=kod, tasinan_cagri=tasinan, devre_disi_receteler=receteler,
                gecis=next(g for g in gecisler(con) if g["yeni_kategori_id"] == yeni_id))


def gecisler(con: sqlite3.Connection, simdi: datetime | None = None) -> list[dict]:
    """Kayıtlı geçişlerin durumu, en yeniden eskiye."""
    simdi = simdi or datetime.now()
    v = risk._veri(con, simdi)
    harita = {r["kategori_id"]: r for r in risk.risk_haritasi(con, _v=v)}
    sonuc = []
    for g in con.execute(
            "SELECT g.*, y.ad AS yeni_ad, y.kod AS yeni_kod, y.kritiklik, e.ad AS eski_ad, e.kod AS eski_kod, b.ad AS birim "
            "FROM gecis g JOIN kategori y ON y.id=g.yeni_kategori_id LEFT JOIN kategori e ON e.id=g.eski_kategori_id "
            "JOIN birim b ON b.id=y.birim_id ORDER BY g.tarih DESC, g.id DESC"):
        g = dict(g)
        gun = (simdi.date() - date.fromisoformat(g["tarih"])).days
        anahtar = [r[0] for r in con.execute(
            f"SELECT ad FROM kisi WHERE id IN ({','.join('?' * len(json.loads(g['anahtar_kisiler'])))})",
            json.loads(g["anahtar_kisiler"]))] if json.loads(g["anahtar_kisiler"]) else []
        cozen = con.execute(
            "SELECT p.ad, COUNT(*) n FROM cagri c JOIN kisi p ON p.id=c.cozen_kisi_id WHERE c.kategori_id=? "
            "AND c.durum='kapali' GROUP BY p.id ORDER BY n DESC", (g["yeni_kategori_id"],)).fetchall()
        toplam = sum(r["n"] for r in cozen)
        acik = con.execute("SELECT COUNT(*) FROM cagri WHERE kategori_id=? AND durum='acik'",
                           (g["yeni_kategori_id"],)).fetchone()[0]
        h = harita.get(g["yeni_kategori_id"])
        adaylar = h["gecis_adaylari"] if h else []
        receteler = [r["ad"] for r in con.execute("SELECT ad FROM recete WHERE kategori_kod=?", (g["eski_kod"],))] \
            if g["eski_kod"] else []
        eski_kart = con.execute("SELECT COUNT(*) FROM cozum_karti WHERE kategori_id=?",
                                (g["eski_kategori_id"],)).fetchone()[0] if g["eski_kategori_id"] else 0
        yeni_kart = con.execute("SELECT COUNT(*) FROM cozum_karti WHERE kategori_id=?",
                                (g["yeni_kategori_id"],)).fetchone()[0]
        yapilacak = []
        if gun < 0:
            yapilacak.append(f"Geçişe {-gun} gün var. Eski sistemde bu işi yapanları şimdiden yeni sisteme hazırlayın.")
        if h and h["yeni_konu"] and h["yeni_konu"]["erken_uyari"]:
            yapilacak.append(f"Bilgi {h['yeni_konu']['en_cok']['ad']} kişisinde toplanıyor: yeni sistemin çözümlerini "
                             "karta yazdırın ve bir kişiyi yanına verin.")
        if adaylar:
            yapilacak.append("Geçiş eğitimi (öğrenme süresinin yarısı): " + ", ".join(a["ad"] for a in adaylar[:4]) + ".")
        if eski_kart and not yeni_kart:
            yapilacak.append(f"Eski sistemin {eski_kart} çözüm kartını yeni sisteme uyarlayın.")
        if receteler:
            yapilacak.append("Otomasyon eski sisteme bağlı, yeni sistemde çalışmıyor: " + ", ".join(receteler) + ".")
        sonuc.append(dict(
            id=g["id"], tarih=g["tarih"], gun=gun, aciklama=g["aciklama"], birim=g["birim"],
            eski_kategori_id=g["eski_kategori_id"], eski_ad=g["eski_ad"],
            yeni_kategori_id=g["yeni_kategori_id"], yeni_ad=g["yeni_ad"], kritiklik=g["kritiklik"],
            anahtar=anahtar, cagri=toplam, acik_cagri=acik,
            cozenler=[dict(ad=r["ad"], adet=r["n"], pay=round(r["n"] / toplam, 2)) for r in cozen[:5]],
            puan=h["puan"] if h else None, seviye=h["seviye"] if h else None, gecici=h["gecici"] if h else None,
            yeni_konu=h["yeni_konu"] if h else None, nedenler=h["nedenler"] if h else [],
            yetkinler=h["yetkinler"] if h else [], gecis_adaylari=adaylar,
            eski_kart=eski_kart, yeni_kart=yeni_kart, devre_disi_receteler=receteler, yapilacak=yapilacak))
    return sonuc


def gecis_simule_et(con: sqlite3.Connection, gun: int = 40, tohum: int = 11) -> dict:
    """DEMO: 'gun' gün önce eski rapor küpünden Power BI'a geçilmiş gibi veriyi düzenler.

    Geçiş kaydedilir, o günden sonraki rapor çağrıları yeni konuya taşınır ve metinleri yeni sisteme
    uyarlanır. Çözenler yeniden dağıtılır: kurulumu yapan anahtar kullanıcı (Emre Çelik) çağrıların
    çoğunu çözer. Gerçek geçişlerde de ilk haftalar böyle geçer; erken uyarının yakalaması gereken budur.
    """
    if con.execute("SELECT 1 FROM meta WHERE anahtar='gecis_simule'").fetchone():
        raise ValueError("Geçiş zaten simüle edildi. Veriyi sıfırlayarak yeniden deneyebilirsiniz.")
    eski = con.execute("SELECT * FROM kategori WHERE kod='RAPOR'").fetchone()
    emre = con.execute("SELECT id FROM kisi WHERE ad='Emre Çelik'").fetchone()
    if not eski or not emre or eski["emeklilik"]:
        raise ValueError("Demo verisinde rapor konusu bulunamadı")
    rnd = random.Random(tohum)
    tarih = (date.today() - timedelta(days=gun)).isoformat()
    r = gecis_kaydet(con, "Power BI rapor yenileme hatası", tarih, eski["id"], [emre[0]],
                     "Eski rapor küpü kapatıldı, raporlar Power BI'a taşındı",
                     anahtar_kelimeler="power bi,veri kümesi,yenileme,pano,dashboard")
    yeni_id = r["yeni_kategori_id"]
    calisanlar = [x[0] for x in con.execute("SELECT id FROM kisi WHERE birim_id=? AND aktif=1", (eski["birim_id"],))]
    for c in con.execute("SELECT id, metin, cozen_kisi_id FROM cagri WHERE kategori_id=? AND durum='kapali'",
                         (yeni_id,)).fetchall():
        metin = (c["metin"].replace("küpü", "Power BI veri kümesi").replace("küp", "Power BI veri kümesi")
                 .replace("rapor", "Power BI raporu", 1))
        cozen = emre[0] if rnd.random() < 0.78 else rnd.choice(calisanlar)
        # Yeni sistemde çözüm notu henüz oturmamış: notların çoğu boş
        con.execute("UPDATE cagri SET metin=?, cozen_kisi_id=?, atanan_kisi_id=?, "
                    "cozum_notu=CASE WHEN ? THEN cozum_notu ELSE NULL END WHERE id=?",
                    (metin, cozen, cozen, rnd.random() < 0.3, c["id"]))
    con.execute("INSERT OR REPLACE INTO meta(anahtar,deger) VALUES('gecis_simule',?)",
                (datetime.now().isoformat(timespec="minutes"),))
    con.commit()
    return dict(gun=gun, tarih=tarih, yeni_kategori_id=yeni_id, tasinan_cagri=r["tasinan_cagri"],
                devre_disi_receteler=r["devre_disi_receteler"])


# ---------------------------------------------------------------- yeni ve ayrılan personel

def kisi_ekle(con: sqlite3.Connection, ad: str, birim_id: int, vardiya: str, rol: str = "Destek Uzmanı",
              ise_giris=None, beyan_kategoriler: list[int] | None = None) -> dict:
    ad = (ad or "").strip()
    if len(ad) < 3:
        raise ValueError("Ad gerekli")
    if vardiya not in ("gunduz", "aksam", "gece"):
        raise ValueError("Vardiya gunduz, aksam ya da gece olmalı")
    if not con.execute("SELECT 1 FROM birim WHERE id=?", (birim_id,)).fetchone():
        raise ValueError("Birim bulunamadı")
    if con.execute("SELECT 1 FROM kisi WHERE ad=? AND aktif=1", (ad,)).fetchone():
        raise ValueError("Bu adla çalışan biri zaten var")
    cur = con.execute("INSERT INTO kisi(ad,birim_id,rol,vardiya,ise_giris) VALUES(?,?,?,?,?)",
                      (ad, birim_id, rol or "Destek Uzmanı", vardiya, _tarih(ise_giris or _bugun())))
    for k in beyan_kategoriler or []:
        con.execute("INSERT OR IGNORE INTO yetkinlik_beyan(kisi_id,kategori_id) VALUES(?,?)", (cur.lastrowid, int(k)))
    con.commit()
    return ise_alisma(con, cur.lastrowid)


def ise_alisma(con: sqlite3.Connection, kisi_id: int, simdi: datetime | None = None) -> dict:
    """Bir kişinin birimindeki her konuda: son 90 günde kaç çözdü, yetkin sayılması için kaç kaldı,
    eğitim planında mı, çırak modu ona çağrı verebiliyor mu?"""
    simdi = simdi or datetime.now()
    p = con.execute("SELECT p.*, b.ad AS birim FROM kisi p JOIN birim b ON b.id=p.birim_id WHERE p.id=?",
                    (kisi_id,)).fetchone()
    if not p:
        raise ValueError("Kişi bulunamadı")
    v = risk._veri(con, simdi)
    planli = {r[0] for r in con.execute("SELECT kategori_id FROM egitim_plani WHERE ogrenen_id=? AND durum='planlandi'",
                                        (kisi_id,))}
    from . import usta
    cirak = usta.cirak_modu_acik(con)
    konular = []
    for k in v["kategoriler"]:
        if k["birim_id"] != p["birim_id"]:
            continue
        s = v["sayim"][k["id"]]
        esik = risk.yetkin_esigi(sum(s.values()))
        n = s.get(kisi_id, 0)
        ustalar = [v["kisiler"][q]["ad"] for q, m in sorted(s.items(), key=lambda x: -x[1]) if m >= esik and q != kisi_id]
        durum = "yetkin" if n >= esik else ("ogreniyor" if n else "baslamadi")
        konular.append(dict(
            kategori_id=k["id"], ad=k["ad"], kritiklik=k["kritiklik"], cozum=n, esik=esik, kalan=max(0, esik - n),
            durum=durum, planli=k["id"] in planli, beyan=kisi_id in v["beyan"][k["id"]], ustalar=ustalar[:3],
            cirak_uygun=(cirak and durum != "yetkin" and k["kritiklik"] < 3 and bool(ustalar) and k["kaynak"] == "usta")))
    konular.sort(key=lambda x: ({"ogreniyor": 0, "baslamadi": 1, "yetkin": 2}[x["durum"]], -x["kritiklik"], x["ad"]))
    giris = p["ise_giris"]
    gun = (simdi.date() - date.fromisoformat(giris)).days if giris else None
    son = con.execute("SELECT MAX(kapanis), COUNT(*) FROM cagri WHERE cozen_kisi_id=? AND durum='kapali'",
                      (kisi_id,)).fetchone()
    yetkin = sum(k["durum"] == "yetkin" for k in konular)
    return dict(kisi=dict(id=p["id"], ad=p["ad"], birim=p["birim"], rol=p["rol"], vardiya=p["vardiya"],
                          ise_giris=giris, gun=gun, aktif=bool(p["aktif"])),
                yetkin=yetkin, toplam_konu=len(konular), toplam_cozum=son[1], son_cozum=son[0],
                cirak_modu=cirak, konular=konular,
                ozet=((f"{p['ad']} {gun} gündür ekipte. " if gun is not None else f"{p['ad']}: ")
                      + f"Birimin {len(konular)} konusundan {yetkin} tanesini biliyor."))


def yeni_personel(con: sqlite3.Connection, simdi: datetime | None = None) -> list[dict]:
    """Son 90 günde işe girenlerin işe alışma özeti."""
    simdi = simdi or datetime.now()
    sinir = (simdi.date() - timedelta(days=YENI_PERSONEL_GUN)).isoformat()
    return [ise_alisma(con, r[0], simdi) for r in con.execute(
        "SELECT id FROM kisi WHERE aktif=1 AND ise_giris>=? ORDER BY ise_giris DESC", (sinir,))]


def yeni_personel_simule_et(con: sqlite3.Connection, gun: int = 35, tohum: int = 5) -> dict:
    """DEMO: 'gun' gün önce Depo Sistemleri'ne (gündüz) yeni biri girmiş ve çırak modu ona kolay
    çağrılar vermiş gibi geçmişi düzenler: gündüz vardiyasındaki kritik olmayan çağrıların bir kısmı
    ona geçer. Böylece işe alışma ekranı boş değil, gerçekçi bir ara durum gösterir."""
    if con.execute("SELECT 1 FROM meta WHERE anahtar='personel_simule'").fetchone():
        raise ValueError("Yeni personel zaten eklendi. Veriyi sıfırlayarak yeniden deneyebilirsiniz.")
    birim = con.execute("SELECT id FROM birim WHERE ad='Depo Sistemleri'").fetchone()
    if not birim:
        raise ValueError("Demo verisinde Depo Sistemleri birimi yok")
    giris = (date.today() - timedelta(days=gun)).isoformat()
    beyan = [r[0] for r in con.execute("SELECT id FROM kategori WHERE kod IN ('BARKOD','ADRES_HATASI')")]
    d = kisi_ekle(con, "Can Arslan", birim[0], "gunduz", "WMS Uzmanı (yeni)", giris, beyan)
    kid = d["kisi"]["id"]
    rnd = random.Random(tohum)
    hedef = {"BARKOD": 1.0, "ADRES_HATASI": 0.6, "STOK_FARKI": 0.25, "RAPOR": 0.2}
    tasinan = 0
    for kod, oran in hedef.items():
        for c in con.execute(
                "SELECT c.id FROM cagri c JOIN kategori k ON k.id=c.kategori_id WHERE k.kod=? AND c.durum='kapali' "
                "AND c.vardiya='gunduz' AND c.acilis>=? AND c.aciliyet<3 AND c.otomatik=0", (kod, giris)).fetchall():
            if rnd.random() < oran:
                con.execute("UPDATE cagri SET cozen_kisi_id=?, atanan_kisi_id=?, sure_dk=CAST(sure_dk*1.4 AS INTEGER) "
                            "WHERE id=?", (kid, kid, c["id"]))
                tasinan += 1
    con.execute("INSERT OR REPLACE INTO meta(anahtar,deger) VALUES('personel_simule',?)",
                (datetime.now().isoformat(timespec="minutes"),))
    con.commit()
    return dict(ise_alisma(con, kid), cagri=tasinan)


def kisi_ayrildi(con: sqlite3.Connection, kisi_id: int, tarih=None) -> dict:
    """Gerçek ayrılış: kişi pasif olur, risk haritası onsuz hesaplanır, açık çağrıları yeniden yönlendirilir.
    'Ya giderse' bir tahmindir; bu ise kayıttır. Önce devir dosyasını hazırlamak iyi olur."""
    from . import usta
    p = con.execute("SELECT * FROM kisi WHERE id=? AND aktif=1", (kisi_id,)).fetchone()
    if not p:
        raise ValueError("Aktif çalışan bulunamadı")
    tarih = _tarih(tarih or _bugun())
    once = risk.ozet(risk.risk_haritasi(con))
    con.execute("UPDATE kisi SET aktif=0, cikis=? WHERE id=?", (tarih, kisi_id))
    con.execute("DELETE FROM egitim_plani WHERE durum='planlandi' AND (ogrenen_id=? OR ogreten_id=?)", (kisi_id, kisi_id))
    sahipsiz = [r[0] for r in con.execute("SELECT ad FROM recete WHERE sahip=?", (p["ad"],))]
    con.execute("UPDATE recete SET sahip=NULL WHERE sahip=?", (p["ad"],))
    con.commit()
    yeniden = []
    for c in con.execute("SELECT id FROM cagri WHERE durum='acik' AND atanan_kisi_id=? AND kaynak='usta'",
                         (kisi_id,)).fetchall():
        try:
            d = usta.yeniden_ata(con, c["id"], aciklama=f"{p['ad']} ayrıldı; yeniden yönlendirildi")
            yeniden.append(dict(id=c["id"], atanan=d.get("atanan")))
        except ValueError:
            yeniden.append(dict(id=c["id"], atanan=None))
    sonra = risk.ozet(risk.risk_haritasi(con))
    return dict(kisi=dict(id=kisi_id, ad=p["ad"], cikis=tarih), yeniden_atanan=yeniden, sahipsiz_receteler=sahipsiz,
                ozet_once=once, ozet_sonra=sonra)
