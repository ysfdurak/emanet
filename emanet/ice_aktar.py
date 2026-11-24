"""Döküm içe aktarma: başka bir sistemin (ör. bakım yazılımı) çağrı dökümünü Emanet'e alır.

Emanet çağrı metnine ihtiyaç duymaz; "kim, hangi konuyu, ne zaman, kaç dakikada çözdü" yeter.
Bu yüzden rapor düzeyinde bir Excel/CSV dökümü yeterlidir.

Zorunlu sütunlar : tarih, birim, konu, cozen, sure_dk
İsteğe bağlı     : vardiya (gunduz|aksam|gece), kritiklik (1-3), ogrenme_saati, talimat_var (0/1)

Ayraç noktalı virgül, virgül veya sekme olabilir. Tarih: YYYY-MM-DD HH:MM, YYYY-MM-DD veya GG.AA.YYYY SS:DD.
"""
from __future__ import annotations

import csv
import io
import sqlite3
import statistics
from collections import Counter
from datetime import datetime, timedelta

ZORUNLU = ["tarih", "birim", "konu", "cozen", "sure_dk"]
SECIMLI = ["vardiya", "kritiklik", "ogrenme_saati", "talimat_var"]
EN_FAZLA_SATIR = 20000
OGRENME_VARSAYILAN = {1: 3, 2: 5, 3: 8}

ESANLAMLI = {"çözen": "cozen", "cozen_kisi": "cozen", "kişi": "cozen", "kisi": "cozen", "süre": "sure_dk",
             "sure": "sure_dk", "süre_dk": "sure_dk", "tarih_saat": "tarih", "kategori": "konu",
             "öğrenme_saati": "ogrenme_saati", "talimat": "talimat_var"}


def _anahtar(ad: str) -> str:
    a = ad.strip().lower().replace(" ", "_").replace("İ".lower(), "i")
    return ESANLAMLI.get(a, a)


def _tarih(s: str) -> datetime:
    s = s.strip()
    for bicim in ("%Y-%m-%d %H:%M", "%Y-%m-%dT%H:%M", "%Y-%m-%d %H:%M:%S", "%Y-%m-%d",
                  "%d.%m.%Y %H:%M", "%d.%m.%Y", "%d/%m/%Y %H:%M", "%d/%m/%Y"):
        try:
            return datetime.strptime(s, bicim)
        except ValueError:
            pass
    raise ValueError(f"tarih okunamadı: '{s}'")


def _vardiya(saat: int) -> str:
    return "gece" if saat < 8 else ("gunduz" if saat < 16 else "aksam")


def oku(metin: str) -> tuple[list[dict], list[str]]:
    """CSV metnini satırlara çevirir. Hatalı satırlar atlanır ve listelenir."""
    metin = metin.lstrip("﻿").strip()
    if not metin:
        raise ValueError("Döküm boş")
    ilk = metin.splitlines()[0]
    ayrac = max([";", ",", "\t"], key=ilk.count)
    okuyucu = csv.DictReader(io.StringIO(metin), delimiter=ayrac)
    okuyucu.fieldnames = [_anahtar(a) for a in (okuyucu.fieldnames or [])]
    eksik = [z for z in ZORUNLU if z not in okuyucu.fieldnames]
    if eksik:
        raise ValueError("Eksik sütun: " + ", ".join(eksik) + ". Gerekenler: " + ", ".join(ZORUNLU))
    satirlar, hatalar = [], []
    for i, r in enumerate(okuyucu, start=2):
        if i - 1 > EN_FAZLA_SATIR:
            hatalar.append(f"{EN_FAZLA_SATIR} satırdan sonrası alınmadı")
            break
        try:
            s = dict(tarih=_tarih(r["tarih"] or ""), birim=(r["birim"] or "").strip(),
                     konu=(r["konu"] or "").strip(), cozen=(r["cozen"] or "").strip(),
                     sure_dk=int(float(str(r["sure_dk"]).replace(",", "."))))
            if not (s["birim"] and s["konu"] and s["cozen"]):
                raise ValueError("birim, konu ve çözen boş olamaz")
            if s["sure_dk"] <= 0:
                raise ValueError("süre sıfırdan büyük olmalı")
            v = (r.get("vardiya") or "").strip().lower().replace("ü", "u").replace("ş", "s")
            s["vardiya"] = v if v in ("gunduz", "aksam", "gece") else None
            k = (r.get("kritiklik") or "").strip()
            s["kritiklik"] = int(k) if k in ("1", "2", "3") else None
            o = (r.get("ogrenme_saati") or "").strip()
            s["ogrenme_saati"] = int(float(o)) if o else None
            s["talimat_var"] = (r.get("talimat_var") or "").strip().lower() in ("1", "evet", "var", "true")
            satirlar.append(s)
        except (ValueError, TypeError, KeyError) as e:
            if len(hatalar) < 10:
                hatalar.append(f"Satır {i}: {e}")
    if not satirlar:
        raise ValueError("Okunabilen satır yok. " + " ".join(hatalar[:3]))
    return satirlar, hatalar


def yukle(con: sqlite3.Connection, metin: str, kaynak: str = "Döküm") -> dict:
    """Dökümü veritabanına yazar. Var olan birim, kişi ve konuları adıyla eşleştirir."""
    satirlar, hatalar = oku(metin)
    cur = con.cursor()
    birim = {r["ad"]: r["id"] for r in con.execute("SELECT id, ad FROM birim")}
    kisi = {r["ad"]: r["id"] for r in con.execute("SELECT id, ad FROM kisi")}
    kategori = {(r["ad"], r["birim_id"]): r["id"] for r in con.execute("SELECT id, ad, birim_id FROM kategori")}
    yeni = Counter()

    for s in satirlar:
        if s["birim"] not in birim:
            cur.execute("INSERT INTO birim(ad) VALUES(?)", (s["birim"],))
            birim[s["birim"]] = cur.lastrowid
            yeni["birim"] += 1

    # Kişi: vardiya sütunu yoksa kişinin kayıtlarının en sık saat aralığından bulunur
    kisi_vardiya: dict[str, Counter] = {}
    kisi_birim: dict[str, Counter] = {}
    for s in satirlar:
        kisi_vardiya.setdefault(s["cozen"], Counter())[s["vardiya"] or _vardiya(s["tarih"].hour)] += 1
        kisi_birim.setdefault(s["cozen"], Counter())[s["birim"]] += 1
    for ad, vs in kisi_vardiya.items():
        if ad not in kisi:
            b = kisi_birim[ad].most_common(1)[0][0]
            cur.execute("INSERT INTO kisi(ad,birim_id,rol,vardiya) VALUES(?,?,?,?)",
                        (ad, birim[b], "Döküm", vs.most_common(1)[0][0]))
            kisi[ad] = cur.lastrowid
            yeni["kisi"] += 1

    # Konu: kritiklik ve öğrenme saati sütunda yoksa varsayılan; temel süre kayıtların ortancası
    gruplar: dict[tuple, list[dict]] = {}
    for s in satirlar:
        gruplar.setdefault((s["konu"], birim[s["birim"]]), []).append(s)
    for (ad, bid), ss in gruplar.items():
        krit = Counter(x["kritiklik"] for x in ss if x["kritiklik"]).most_common(1)
        krit = krit[0][0] if krit else 2
        ogr = next((x["ogrenme_saati"] for x in ss if x["ogrenme_saati"]), OGRENME_VARSAYILAN[krit])
        talimat = int(any(x["talimat_var"] for x in ss))
        temel = max(1, round(statistics.median(x["sure_dk"] for x in ss)))
        if (ad, bid) in kategori:
            con.execute("UPDATE kategori SET talimat_var=MAX(talimat_var,?) WHERE id=?", (talimat, kategori[(ad, bid)]))
            continue
        kod = f"D{len(kategori) + 1:03d}"
        cur.execute("INSERT INTO kategori(kod,ad,birim_id,kritiklik,anahtar_kelimeler,aciklama,ogrenme_saati,"
                    "temel_sure_dk,kaynak,talimat_var) VALUES(?,?,?,?,?,?,?,?,?,?)",
                    (kod, ad, bid, krit, "", f"{kaynak} kaynağından içe aktarıldı", ogr, temel, kaynak, talimat))
        kategori[(ad, bid)] = cur.lastrowid
        yeni["konu"] += 1

    veri = []
    for s in satirlar:
        bas = s["tarih"]
        veri.append((s["konu"], "Döküm", 2, kategori[(s["konu"], birim[s["birim"]])], kisi[s["cozen"]],
                     kisi[s["cozen"]], bas.isoformat(timespec="minutes"),
                     (bas + timedelta(minutes=s["sure_dk"])).isoformat(timespec="minutes"), s["sure_dk"],
                     s["vardiya"] or _vardiya(bas.hour), kaynak))
    cur.executemany(
        "INSERT INTO cagri(metin,acan_birim,aciliyet,kategori_id,atanan_kisi_id,cozen_kisi_id,acilis,kapanis,"
        "sure_dk,vardiya,kaynak,durum) VALUES(?,?,?,?,?,?,?,?,?,?,?,'kapali')", veri)
    con.commit()
    tarihler = [s["tarih"] for s in satirlar]
    return dict(kaynak=kaynak, satir=len(satirlar), hatali=len(hatalar), hatalar=hatalar,
                yeni_birim=yeni["birim"], yeni_kisi=yeni["kisi"], yeni_konu=yeni["konu"],
                ilk_tarih=min(tarihler).date().isoformat(), son_tarih=max(tarihler).date().isoformat())


def analiz_et(metin: str) -> dict:
    """Ziyaretçinin dökümünü kaydetmeden analiz eder: bellekte geçici bir veritabanı kurulur,
    risk haritası çıkarılır, bağlantı kapanınca her şey silinir."""
    from . import risk
    from .db import baglan
    con = baglan(":memory:")
    try:
        sonuc = yukle(con, metin, "Yüklenen döküm")
        son = con.execute("SELECT MAX(kapanis) FROM cagri").fetchone()[0]
        simdi = datetime.fromisoformat(son) + timedelta(days=1)   # analiz dökümün son gününe göre yapılır
        h = risk.risk_haritasi(con, simdi)
        return dict(yukleme=sonuc, ozet=risk.ozet(h), konular=h, matris=risk.matris(con, simdi),
                    pencere=f"{(simdi - timedelta(days=risk.PENCERE_GUN)).date().isoformat()} – {son[:10]}")
    finally:
        con.close()
