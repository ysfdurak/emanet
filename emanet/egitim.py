"""Eğitimin içeriği ve konu süreleri.

Plan (risk.egitim_plani) "kim, kime, kaç saat" der; bu modül "o saatlerde ne yapılacak" sorusunu
geçmiş çağrılardan cevaplar:

  - Çözüm yolları: konunun kapanmış çağrılarındaki çözüm notları, ilk adımına göre gruplanır.
    Her grup bir "çözüm yolu"dur (ERP: "günlükte bul, düzelt, yeniden gönder" ile "servisi yeniden
    başlat" iki ayrı yol). Kart yazmak = bu yolları adım adım yazıya dökmek.
  - Vakalar: her yoldan bir temsilci çağrı (en yenisi, teyitli olan önce). Eğitimde usta ile
    öğrenen bu çağrıların üzerinden geçer: belirti → teşhis → çözüm.
  - Yanında öğrenme ve ölçüt: sonraki gerçek çağrıyı öğrenen usta yanındayken çözer; BILEN_ESIK
    çağrıyı tek başına kapatınca "biliyor" sayılır (beyanla değil, çağrıyla ölçülür).

Süreler kullanıcıdan gelir: kart yazma ve sıfırdan öğretme saati konu başına girilir. Girilmeyen
konuda plan varsayılanla hesaplar ama satır "tahmini süre" diye işaretlenir; yeni açılan konunun
süresi hiç girilmemiş sayılır.
"""
from __future__ import annotations

import re
import sqlite3

BILEN_ESIK = 3          # tek başına kapatılan çağrı sayısı: "biliyor" sayılmak için
EN_FAZLA_VAKA = 5
TAZELEME_VAKA = 2       # tazelemede yalnız en sık iki yol hatırlatılır


def _ilk_adim(notu: str) -> str:
    ilk = notu.strip().splitlines()[0] if notu.strip() else ""
    return re.sub(r"\s+", " ", re.sub(r"\d+", "#", ilk.lower())).strip(" .")


def cozum_yollari(con: sqlite3.Connection, kategori_id: int) -> list[dict]:
    """Konunun çözüm yolları, en sık olandan aza; her yol için temsilci vaka."""
    anahtar = [a.strip().lower() for a in (con.execute("SELECT anahtar_kelimeler FROM kategori WHERE id=?",
               (kategori_id,)).fetchone() or [""])[0].split(",") if a.strip()]
    satirlar = con.execute(
        "SELECT c.id, c.metin, c.cozum_notu, c.sure_dk, c.teyit, c.acilis, k.ad AS cozen "
        "FROM cagri c LEFT JOIN kisi k ON k.id=c.cozen_kisi_id "
        "WHERE c.kategori_id=? AND c.durum='kapali' AND c.otomatik=0 AND c.cozum_notu IS NOT NULL "
        "AND TRIM(c.cozum_notu)!=''", (kategori_id,)).fetchall()
    # Temsilci vaka eğitimde okunacak: belirtisi açık olan seçilsin. Konunun anahtar kelimesini
    # içeren, selamlama/genel şikâyet ("çalışmıyor, acil bakar mısınız") olmayan, teyitli ve yeni olan önce.
    def bilgi(r) -> tuple:
        m = r["metin"].lower()
        return (any(a in m for a in anahtar), len(re.sub(r"(merhaba|iyi çalışmalar|acil|rica ederim|bakar mısınız)", "", m)) > 40,
                r["teyit"] or 0, r["acilis"])
    satirlar = sorted(satirlar, key=bilgi, reverse=True)
    gruplar: dict[str, dict] = {}
    for r in satirlar:
        anahtar = _ilk_adim(r["cozum_notu"])
        if not anahtar:
            continue
        g = gruplar.setdefault(anahtar, dict(adet=0, vaka=None))
        g["adet"] += 1
        if g["vaka"] is None:        # sıralama gereği en açıklayıcı olan ilk gelir
            g["vaka"] = dict(cagri_id=r["id"], belirti=r["metin"], tarih=r["acilis"][:10], cozen=r["cozen"],
                             sure_dk=r["sure_dk"], adimlar=[a.strip() for a in r["cozum_notu"].splitlines() if a.strip()])
    return sorted(({"adet": g["adet"], **g["vaka"]} for g in gruplar.values()), key=lambda y: -y["adet"])


def icerik(con: sqlite3.Connection, satir: dict, kart_planda: bool = False) -> dict:
    """Bir plan adımının içeriği: gündem maddeleri ve tamamlanma ölçütü."""
    kid, tur = satir["kategori_id"], satir["tur"]
    yollar = cozum_yollari(con, kid)
    kart = con.execute("SELECT adimlar FROM cozum_karti WHERE kategori_id=? ORDER BY olusturma DESC LIMIT 1",
                       (kid,)).fetchone()
    ogreten, ogrenen = satir.get("ogreten") or "Usta", satir.get("ogrenen") or "Öğrenen"
    if tur == "kart":
        gundem = ([f"Çözüm yolu {i}: “{y['adimlar'][0]}” ile başlayan yolu adım adım yaz ({y['adet']} çağrıda kullanıldı)"
                   for i, y in enumerate(yollar[:EN_FAZLA_VAKA], 1)]
                  or ["Çözüm notu yok: konuyu bilen kişi en sık yaptığı çözümü baştan yazar"])
        olcut = "Kart yayımlanır; bir sonraki çağrıda çözüm ekranında görünür"
        return dict(gundem=gundem, olcut=olcut, yol_sayisi=len(yollar), vakalar=yollar[:EN_FAZLA_VAKA])
    n = TAZELEME_VAKA if tur == "tazeleme" else EN_FAZLA_VAKA
    vakalar = yollar[:n]
    gundem = []
    if kart or kart_planda:
        gundem.append("Kartı birlikte oku" + ("" if kart else " (bu planda yazılıyor)"))
    elif tur != "tazeleme":
        gundem.append("Konunun genel akışını anlat (yazılı çözüm yok)")
    gundem += [f"Vaka #{v['cagri_id']}: “{v['belirti'][:70]}” → {v['adimlar'][0]}" for v in vakalar]
    if not vakalar:
        gundem.append(f"Çözüm notu yok: {ogreten} en sık karşılaştığı durumları anlatır, {ogrenen} not alır")
    # Kalan oturumlar uygulamadır: öğrenen işi yapar, usta yanındadır (gerçek çağrı geldikçe ya da sahada)
    gundem.append(f"Birlikte uygulama: işi {ogrenen} yapar, {ogreten} yanında")
    olcut = (f"{ogrenen} bu konuda {BILEN_ESIK} çağrıyı tek başına kapatınca “biliyor” sayılır; "
             "sıradaki çağrılar yanında öğrenme ile önce ona gider")
    return dict(gundem=gundem, olcut=olcut, yol_sayisi=len(yollar), vakalar=vakalar)


def plani_zenginlestir(con: sqlite3.Connection, plan: dict) -> dict:
    """Plan satırlarına içerik (gündem, ölçüt, vakalar) ekler; aynı konunun yolları bir kez hesaplanır."""
    kartli = {s["kategori_id"] for s in plan["satirlar"] if s["tur"] == "kart"}
    for s in plan["satirlar"]:
        s.update(icerik(con, s, kart_planda=s["kategori_id"] in kartli))
    eksik = sorted({s["kategori"] for s in plan["satirlar"] if s.get("sure_tahmini")})
    plan["tahmini_sureli_konular"] = eksik
    return plan


# ---------------------------------------------------------------- süreler

def sureler(con: sqlite3.Connection) -> list[dict]:
    """Geçerli konuların kart ve öğretme süreleri; kim girdi (kullanıcı / tahmin)."""
    from .risk import KART_YAZMA_SAATI
    return [dict(r, kart_saat_etkin=r["kart_saat"] or KART_YAZMA_SAATI) for r in con.execute(
        "SELECT k.id AS kategori_id, k.ad, b.ad AS birim, k.kart_saat, k.ogrenme_saati, k.sure_onay, k.acilis "
        "FROM kategori k JOIN birim b ON b.id=k.birim_id WHERE k.emeklilik IS NULL ORDER BY b.id, k.ad")]


def sure_kaydet(con: sqlite3.Connection, kategori_id: int, kart_saat: float, ogrenme_saati: float) -> dict:
    for ad, v in (("Kart yazma", kart_saat), ("Öğretme", ogrenme_saati)):
        if not 0.5 <= v <= 200:
            raise ValueError(f"{ad} süresi 0,5 ile 200 saat arasında olmalı")
        if (v * 2) != int(v * 2):
            raise ValueError(f"{ad} süresi yarım saatin katı olmalı (ör. 1,5)")
    if not con.execute("SELECT 1 FROM kategori WHERE id=?", (kategori_id,)).fetchone():
        raise ValueError("Konu bulunamadı")
    con.execute("UPDATE kategori SET kart_saat=?, ogrenme_saati=?, sure_onay=1 WHERE id=?",
                (kart_saat, ogrenme_saati, kategori_id))
    con.commit()
    return next(s for s in sureler(con) if s["kategori_id"] == kategori_id)
