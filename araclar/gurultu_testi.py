"""Gürültü testi (pilot bitiş ölçütü 2): model kirli veride de ayakta kalıyor mu?

Demo veri üretilir, zamana göre %80 eğitim / %20 test ayrılır (degerlendir() ile aynı kural).
Sonra eğitim ve test metinleri bozulur:
  - yazım hatası: harf düşürme, yer değiştirme, Türkçe karakter kaybı (ş→s, ı→i ...)
  - kısa metin: metin ilk 2-3 sözcüğe indirilir ("yazıcı çalışmıyor")
  - yanlış etiket: eğitim çağrılarının bir kısmında konu başka bir konuyla değiştirilir
Yanlış etiket yalnız EĞİTİME konur; test etiketleri doğru kalır. Böylece "kirli geçmişten öğrenen
model, yeni çağrıda doğruyu buluyor mu?" sorusu ölçülür (test de kirli olsaydı en iyi model bile
yanlış etiketler yüzünden düşük görünürdü).

Çalıştırma:  python -m araclar.gurultu_testi            (yaklaşık 1 dakika)
"""
from __future__ import annotations

import random
import sqlite3
import sys
from datetime import date

from emanet import db, ogrenme, veri_uret

BUGUN = date(2026, 11, 25)
TR = str.maketrans("şçğıöüŞÇĞİÖÜ", "scgiouSCGIOU")

SENARYOLAR = [
    # ad, yazım hatası oranı, kısa metin oranı, yanlış etiket oranı
    ("Temiz (demo olduğu gibi)", 0.0, 0.0, 0.00),
    ("Yazım hatası %40", 0.4, 0.0, 0.00),
    ("Kısa metin %30", 0.0, 0.3, 0.00),
    ("Yanlış etiket %15", 0.0, 0.0, 0.15),
    ("Hepsi birlikte (ölçüt)", 0.4, 0.3, 0.15),
    ("Sert: hepsi, etiket %25", 0.6, 0.5, 0.25),
]


def boz_metin(metin: str, hata: float, kisa: float, rnd: random.Random) -> str:
    if rnd.random() < kisa:
        sozcukler = metin.split()
        metin = " ".join(sozcukler[: rnd.choice((2, 3))])
    if rnd.random() < hata:
        if rnd.random() < 0.5:
            metin = metin.translate(TR)            # klavyede Türkçe karakter yok
        harfler = list(metin)
        for _ in range(rnd.randint(1, 2)):
            if len(harfler) < 6:
                break
            i = rnd.randrange(1, len(harfler) - 1)
            if rnd.random() < 0.5:
                del harfler[i]                     # harf düşürme
            else:
                harfler[i], harfler[i + 1] = harfler[i + 1], harfler[i]   # yer değiştirme
        metin = "".join(harfler)
    return metin


def olc(egitim: list[dict], test: list[dict], birim: dict, kisi_birim: dict) -> dict:
    m = ogrenme.Model(egitim)
    konu = ilk3 = ilk1 = 0
    for s in test:
        tahmin = m.konu_olasiliklari(s["metin"])[0][0]
        konu += tahmin == s["kategori_id"]
        pk = m.kisi_olasiliklari(s["metin"], tahmin, s["vardiya"], s["acan_birim"])
        aday = sorted((p for p in pk if kisi_birim.get(p) == birim[tahmin]), key=lambda p: -pk[p])
        ilk1 += bool(aday) and aday[0] == s["cozen_kisi_id"]
        ilk3 += s["cozen_kisi_id"] in aday[:3]
    n = len(test)
    return dict(konu=konu / n, kisi_ilk1=ilk1 / n, kisi_ilk3=ilk3 / n)


def calistir(tohum: int = 7) -> tuple[list[tuple[str, dict]], dict]:
    con = db.baglan(":memory:")
    veri_uret.uret(con, BUGUN)
    satirlar = [s for s in ogrenme._egitim_verisi(con) if s["acilis"] < BUGUN.isoformat()]
    kes = int(len(satirlar) * (1 - ogrenme.TEST_PAYI))
    egitim0, test0 = satirlar[:kes], satirlar[kes:]
    kategoriler = [dict(r) for r in con.execute("SELECT id, birim_id FROM kategori WHERE kaynak='usta'")]
    birim = {k["id"]: k["birim_id"] for k in kategoriler}
    ayni_birim = {k["id"]: [x["id"] for x in kategoriler if x["birim_id"] == k["birim_id"] and x["id"] != k["id"]]
                  for k in kategoriler}
    kisi_birim = {r["id"]: r["birim_id"] for r in con.execute("SELECT id, birim_id FROM kisi")}

    # Karşılaştırma tabanı: rastgele 3 kişi (birim boyutuna göre) ve "konuda en çok çözen 3 kişi" kuralı
    from collections import Counter, defaultdict
    boyut = Counter(kisi_birim[p] for p in kisi_birim
                    if con.execute("SELECT cikis FROM kisi WHERE id=?", (p,)).fetchone()[0] is None)
    say = defaultdict(Counter)
    for s in egitim0:
        say[s["kategori_id"]][s["cozen_kisi_id"]] += 1
    tabanlar = dict(
        rastgele_ilk3=sum(min(1, 3 / boyut[birim[s["kategori_id"]]]) for s in test0) / len(test0),
        kural_ilk3=sum(s["cozen_kisi_id"] in [p for p, _ in say[s["kategori_id"]].most_common(3)]
                       for s in test0) / len(test0))

    sonuc = []
    for ad, hata, kisa, etiket in SENARYOLAR:
        rnd = random.Random(tohum)
        egitim = []
        for s in egitim0:
            s = dict(s, metin=boz_metin(s["metin"], hata, kisa, rnd))
            if rnd.random() < etiket and ayni_birim[s["kategori_id"]]:
                # Gerçekte yanlış etiket çoğu zaman aynı birimdeki komşu konuya atılır
                s["kategori_id"] = rnd.choice(ayni_birim[s["kategori_id"]])
            egitim.append(s)
        test = [dict(s, metin=boz_metin(s["metin"], hata, kisa, rnd)) for s in test0]
        sonuc.append((ad, olc(egitim, test, birim, kisi_birim) | dict(egitim=len(egitim), test=len(test))))
    return sonuc, tabanlar


def main() -> int:
    sonuc, tabanlar = calistir()
    print(f"{'Senaryo':28} {'Konu':>6} {'Kişi 1.':>8} {'Kişi ilk 3':>11}")
    for ad, r in sonuc:
        print(f"{ad:28} {r['konu']:6.1%} {r['kisi_ilk1']:8.1%} {r['kisi_ilk3']:11.1%}")
    print(f"\nKarşılaştırma (kişi ilk 3, temiz veri, konu bilinirken): rastgele {tabanlar['rastgele_ilk3']:.0%}, "
          f"'en çok çözen 3' kuralı {tabanlar['kural_ilk3']:.0%}")
    hedef = dict(sonuc)["Hepsi birlikte (ölçüt)"]
    gecti = hedef["konu"] >= 0.75 and hedef["kisi_ilk3"] >= 0.80
    print(f"\nÖlçüt (konu ≥ %75, kişi ilk 3 ≥ %80): {'GEÇTİ' if gecti else 'KALDI'}  "
          f"(eğitim {hedef['egitim']}, test {hedef['test']} çağrı)")
    return 0 if gecti else 1


if __name__ == "__main__":
    sys.exit(main())
