"""Kendi verinle yerelde çalıştırma: gerçek çağrı dökümünü içe aktarır, Usta'yı onunla eğitir.

Veri bu bilgisayardan (ya da kendi sunucundan) çıkmaz. Site ziyaretçilerinden çağrı metni
istenmez; gerçek veriyle denemek isteyen uygulamayı kendi makinesinde bu komutla kurar.

Kullanım:
    python -m emanet.yerel cagrilar.csv                    # veri/yerel.db kurulur, rapor yazılır
    python -m emanet.yerel cagrilar.csv --dokum bakim.csv  # teknik arıza dökümü de eklenir (Emanet)
    python -m emanet.yerel cagrilar.csv --takma-ad         # kişi adları "Kişi 01"... olarak saklanır
    python -m emanet.yerel cagrilar.csv --bugune-kaydir    # tarihler, son kayıt bugün olacak şekilde kaydırılır
    python -m emanet.yerel --ornek ornek_cagrilar.csv      # biçimi görmek için örnek dosya üretir

Sonra uygulamayı bu veritabanıyla aç:
    EMANET_DB=veri/yerel.db python -m emanet          # http://localhost:8000

Çağrı dosyası (CSV; ayraç ; , ya da sekme):
    Zorunlu : tarih, metin, konu, birim, cozen
    İsteğe bağlı: sure_dk (ya da kapanis), cozum_notu, vardiya, aciliyet (1-3), kritiklik (1-3),
                  acan_birim, atanan (ilk atanan kişi; çözenden farklıysa yeniden atama sayılır)
Sütun adları esnektir: "Açıklama", "Kategori", "Destek grubu", "Çözen kişi", "Çözüm" gibi adlar tanınır.
"""
from __future__ import annotations

import argparse
import csv
import io
import re
import sqlite3
import statistics
import sys
from collections import Counter, defaultdict
from datetime import datetime, timedelta
from pathlib import Path

from .ice_aktar import _tarih, _vardiya
from .ogrenme import kucult

ZORUNLU = ["tarih", "metin", "konu", "birim", "cozen"]
EN_AZ_CAGRI = 50
ONERILEN_CAGRI = 300
EN_AZ_KONU_CAGRI = 5
EN_FAZLA_SATIR = 100_000

ESANLAMLI = {
    "metin": ["metin", "aciklama", "açıklama", "sorun", "problem", "baslik", "başlık", "ozet", "özet", "talep",
              "cagri_metni", "çağrı_metni", "konu_detayi", "detay", "description", "summary"],
    "konu": ["konu", "kategori", "alt_kategori", "sorun_turu", "sorun_türü", "category"],
    "birim": ["birim", "grup", "ekip", "destek_grubu", "çözüm_grubu", "cozum_grubu", "team", "group"],
    "cozen": ["cozen", "çözen", "cozen_kisi", "çözen_kişi", "kapatan", "resolved_by", "cozumleyen", "çözümleyen"],
    "tarih": ["tarih", "acilis", "açılış", "acilis_tarihi", "açılış_tarihi", "olusturma", "oluşturma", "created"],
    "kapanis": ["kapanis", "kapanış", "kapanis_tarihi", "kapanış_tarihi", "closed"],
    "sure_dk": ["sure_dk", "süre_dk", "sure", "süre", "cozum_suresi", "çözüm_süresi"],
    "cozum_notu": ["cozum_notu", "çözüm_notu", "cozum", "çözüm", "cozum_aciklamasi", "çözüm_açıklaması", "not",
                   "resolution"],
    "vardiya": ["vardiya"], "aciliyet": ["aciliyet", "öncelik", "oncelik", "priority"],
    "kritiklik": ["kritiklik"], "acan_birim": ["acan_birim", "açan_birim", "talep_eden_birim", "departman"],
    "atanan": ["atanan", "ilk_atanan", "assigned_to"],
}
_ESLE = {kucult(a): hedef for hedef, adlar in ESANLAMLI.items() for a in adlar}

DURAK = set("ve ile bir bu şu da de mi mı için gibi çok daha var yok ama ya ki olarak olan oldu olmuyor "
            "değil sonra önce şimdi hala hâlâ yine lütfen acil merhaba rica ederim teşekkürler sistem "
            "sorun hata problem çalışmıyor yapamıyorum".split())


def _sutun(ad: str) -> str:
    a = re.sub(r"[^\w]+", "_", kucult(ad.strip())).strip("_")      # "Süre (dk)" → "süre_dk"
    return _ESLE.get(a, a)


def oku(metin: str) -> tuple[list[dict], list[str]]:
    """Çağrı CSV'sini okur. Hatalı satırlar atlanır ve (ilk 10'u) listelenir."""
    metin = metin.lstrip("﻿").strip()
    if not metin:
        raise ValueError("Dosya boş")
    ayrac = max([";", ",", "\t"], key=metin.splitlines()[0].count)
    r = csv.DictReader(io.StringIO(metin), delimiter=ayrac)
    r.fieldnames = [_sutun(a) for a in (r.fieldnames or [])]
    eksik = [z for z in ZORUNLU if z not in r.fieldnames]
    if eksik:
        raise ValueError(f"Eksik sütun: {', '.join(eksik)}. Bulunan sütunlar: {', '.join(r.fieldnames)}. "
                         f"Gerekenler: {', '.join(ZORUNLU)}")
    satirlar, hatalar = [], []
    for i, x in enumerate(r, start=2):
        if i - 1 > EN_FAZLA_SATIR:
            hatalar.append(f"{EN_FAZLA_SATIR} satırdan sonrası alınmadı")
            break
        try:
            s = {k: (x.get(k) or "").strip() for k in ESANLAMLI}
            if not all(s[z] for z in ZORUNLU if z != "tarih"):
                raise ValueError("metin, konu, birim ve çözen boş olamaz")
            s["tarih"] = _tarih(s["tarih"])
            if s["sure_dk"]:
                s["sure_dk"] = max(1, int(float(s["sure_dk"].replace(",", "."))))
            elif s["kapanis"]:
                s["sure_dk"] = max(1, round((_tarih(s["kapanis"]) - s["tarih"]).total_seconds() / 60))
            else:
                s["sure_dk"] = None
            v = s["vardiya"].lower().replace("ü", "u").replace("ş", "s")
            s["vardiya"] = v if v in ("gunduz", "aksam", "gece") else _vardiya(s["tarih"].hour)
            s["aciliyet"] = int(s["aciliyet"]) if s["aciliyet"] in ("1", "2", "3") else 2
            s["kritiklik"] = int(s["kritiklik"]) if s["kritiklik"] in ("1", "2", "3") else None
            s["cozum_notu"] = s["cozum_notu"].replace(" / ", "\n").replace("|", "\n") or None
            satirlar.append(s)
        except (ValueError, TypeError) as e:
            if len(hatalar) < 10:
                hatalar.append(f"Satır {i}: {e}")
    if not satirlar:
        raise ValueError("Okunabilen satır yok. " + " ".join(hatalar[:3]))
    return satirlar, hatalar


def _anahtar_kelimeler(metinler: list[str], tum: Counter, n: int = 4) -> str:
    """Konunun ayırt edici sözcükleri: bu konuda sık, diğerlerinde seyrek geçenler (kural yöntemi ve
    modelin henüz görmediği yeni konular için)."""
    say = Counter()
    for m in metinler:
        say.update({w for w in re.findall(r"[a-zçğıöşü0-9]{4,}", kucult(m)) if w not in DURAK})
    puan = {w: c / len(metinler) * (c / tum[w]) for w, c in say.items() if c >= max(2, 0.15 * len(metinler))}
    return ",".join(w for w, _ in sorted(puan.items(), key=lambda x: -x[1])[:n])


def usta_yukle(con: sqlite3.Connection, metin: str, takma_ad: bool = False, kaydir: bool = False) -> dict:
    """Çağrıları boş bir veritabanına yazar: birimler, kişiler, Usta konuları ve kapalı çağrılar."""
    satirlar, hatalar = oku(metin)
    if len(satirlar) < EN_AZ_CAGRI:
        raise ValueError(f"En az {EN_AZ_CAGRI} çağrı gerekiyor; dosyada okunabilen {len(satirlar)} çağrı var")
    konular = Counter((s["birim"], s["konu"]) for s in satirlar)
    kisiler = Counter(s["cozen"] for s in satirlar)
    if len(konular) < 2 or len(kisiler) < 2:
        raise ValueError("Öğrenmek için en az iki konu ve iki çözen kişi gerekiyor")
    uyarilar = []
    if kaydir:
        fark = datetime.now() - max(s["tarih"] for s in satirlar)
        fark = timedelta(days=fark.days)
        for s in satirlar:
            s["tarih"] += fark
        uyarilar.append(f"Tarihler {fark.days} gün ileri kaydırıldı (son kayıt bugün).")

    takma = {}
    if takma_ad:
        for i, (ad, _) in enumerate(kisiler.most_common(), start=1):
            takma[ad] = f"Kişi {i:02d}"
        desen = re.compile("|".join(re.escape(a) for a in sorted(takma, key=len, reverse=True)))
        for s in satirlar:
            for alan in ("metin", "cozum_notu"):
                if s[alan]:
                    s[alan] = desen.sub(lambda m: takma[m.group(0)], s[alan])
            s["cozen"] = takma[s["cozen"]]
            if s["atanan"]:
                s["atanan"] = takma.get(s["atanan"], "Kişi ?")

    cur = con.cursor()
    birim = {}
    for b in dict.fromkeys(s["birim"] for s in satirlar):
        cur.execute("INSERT INTO birim(ad) VALUES(?)", (b,))
        birim[b] = cur.lastrowid
    # Kişinin birimi ve vardiyası: kayıtlarında en sık geçen
    kb, kv = defaultdict(Counter), defaultdict(Counter)
    for s in satirlar:
        kb[s["cozen"]][s["birim"]] += 1
        kv[s["cozen"]][s["vardiya"]] += 1
    kisi = {}
    for ad in kb:
        cur.execute("INSERT INTO kisi(ad,birim_id,rol,vardiya) VALUES(?,?,?,?)",
                    (ad, birim[kb[ad].most_common(1)[0][0]], "Çağrı çözen", kv[ad].most_common(1)[0][0]))
        kisi[ad] = cur.lastrowid
    # Konu: kod, ortanca süre, kritiklik (sütunda yoksa 2), anahtar kelimeler metinlerden
    tum = Counter()
    for s in satirlar:
        tum.update({w for w in re.findall(r"[a-zçğıöşü0-9]{4,}", kucult(s["metin"]))})
    kategori = {}
    for i, (b, k) in enumerate(konular, start=1):
        ss = [s for s in satirlar if (s["birim"], s["konu"]) == (b, k)]
        krit = Counter(s["kritiklik"] for s in ss if s["kritiklik"]).most_common(1)
        krit = krit[0][0] if krit else 2
        sureler = [s["sure_dk"] for s in ss if s["sure_dk"]]
        cur.execute(
            "INSERT INTO kategori(kod,ad,birim_id,kritiklik,anahtar_kelimeler,aciklama,ogrenme_saati,temel_sure_dk,kaynak)"
            " VALUES(?,?,?,?,?,?,?,?,'usta')",
            (f"K{i:03d}", k, birim[b], krit, _anahtar_kelimeler([s["metin"] for s in ss], tum) or kucult(k),
             k, {1: 3, 2: 5, 3: 8}[krit], round(statistics.median(sureler)) if sureler else 30))
        kategori[(b, k)] = cur.lastrowid
    yeniden = 0
    for s in sorted(satirlar, key=lambda s: s["tarih"]):
        bas = s["tarih"]
        son = bas + timedelta(minutes=s["sure_dk"] or 0)
        kid, cid = kategori[(s["birim"], s["konu"])], kisi[s["cozen"]]
        ilk = kisi.get(s["atanan"]) if s["atanan"] else None
        yeniden_mi = int(bool(ilk and ilk != cid))
        yeniden += yeniden_mi
        cur.execute(
            "INSERT INTO cagri(metin,acan_birim,aciliyet,kategori_id,onerilen_kategori_id,durum,atanan_kisi_id,"
            "cozen_kisi_id,acilis,kapanis,sure_dk,yeniden_atama,vardiya,cozum_notu,kaynak) "
            "VALUES(?,?,?,?,?,'kapali',?,?,?,?,?,?,?,?,'usta')",
            (s["metin"], s["acan_birim"] or "Bilinmiyor", s["aciliyet"], kid, kid, cid, cid,
             bas.isoformat(timespec="minutes"), son.isoformat(timespec="minutes"), s["sure_dk"], yeniden_mi,
             s["vardiya"], s["cozum_notu"]))
        c = cur.lastrowid
        cur.execute("INSERT INTO cagri_olay(cagri_id,zaman,tur) VALUES(?,?,'acildi')", (c, bas.isoformat(timespec="minutes")))
        cur.execute("INSERT INTO cagri_olay(cagri_id,zaman,tur,kisi_id) VALUES(?,?,'kapandi',?)",
                    (c, son.isoformat(timespec="minutes"), cid))
    con.commit()

    az = [f"{k} ({n})" for (b, k), n in konular.items() if n < EN_AZ_KONU_CAGRI]
    if az:
        uyarilar.append(f"{len(az)} konuda {EN_AZ_KONU_CAGRI}'ten az çağrı var; model bunları zor tanır: "
                        + ", ".join(az[:8]) + ("…" if len(az) > 8 else ""))
    if len(satirlar) < ONERILEN_CAGRI:
        uyarilar.append(f"{len(satirlar)} çağrı az; anlamlı sonuç için {ONERILEN_CAGRI}+ önerilir.")
    notlu = sum(1 for s in satirlar if s["cozum_notu"])
    if notlu / len(satirlar) < 0.3:
        uyarilar.append(f"Çağrıların yalnızca %{round(notlu / len(satirlar) * 100)}'inde çözüm notu var; "
                        "'nasıl çözüldü' önerileri zayıf kalır.")
    if not any(s["kritiklik"] for s in satirlar):
        uyarilar.append("Kritiklik sütunu yok: bütün konular orta (2) sayıldı. İşi durduran konular için "
                        "kritiklik=3 vermek risk puanını doğru ölçekler.")
    if not any(s["sure_dk"] for s in satirlar):
        uyarilar.append("Süre ya da kapanış sütunu yok: kalite ağırlığı ve 'ya giderse' süreleri hesaplanamaz.")
    gun = (datetime.now() - max(s["tarih"] for s in satirlar)).days
    if gun > 14 and not kaydir:
        uyarilar.append(f"Son kayıt {gun} gün önce. Risk haritası bugünden geriye 90 güne bakar; "
                        "eski bir dökümde --bugune-kaydir kullanın.")
    tarihler = [s["tarih"] for s in satirlar]
    return dict(cagri=len(satirlar), hatali=len(hatalar), hatalar=hatalar, birim=len(birim), kisi=len(kisi),
                konu=len(kategori), notlu=notlu, yeniden_atama=yeniden, uyarilar=uyarilar, takma_ad=takma,
                ilk_tarih=min(tarihler).date().isoformat(), son_tarih=max(tarihler).date().isoformat())


def kur(db_yolu: Path, cagri_csv: str, dokum_csv: str | None = None, takma_ad: bool = False,
        kaydir: bool = False) -> dict:
    """Yerel veritabanını sıfırdan kurar, modeli eğitir ve ölçer."""
    from . import ice_aktar, ogrenme, risk
    from .db import baglan, bosalt, meta_yaz
    con = baglan(db_yolu)
    bosalt(con)
    y = usta_yukle(con, cagri_csv, takma_ad, kaydir)
    d = ice_aktar.yukle(con, dokum_csv, "Bakım dökümü") if dokum_csv else None
    meta_yaz(con, "mod", "yerel")
    meta_yaz(con, "yerel_kurulum", datetime.now().isoformat(timespec="minutes"))
    meta_yaz(con, "uretim_tarihi", datetime.now().date().isoformat())
    ogrenme.model(con, zorla=True)
    try:
        degerlendirme = ogrenme.degerlendir(con)
    except ValueError as e:          # test kümesi çok küçükse
        degerlendirme = dict(hata=str(e))
    h = risk.risk_haritasi(con)
    con.close()
    return dict(yukleme=y, dokum=d, degerlendirme=degerlendirme, risk=risk.ozet(h),
                en_riskli=[dict(ad=r["ad"], puan=r["puan"], nedenler=r["nedenler"][:2]) for r in h[:5]])


def rapor(s: dict, db_yolu: Path) -> str:
    """Kurulum sonucunu okunur bir Markdown rapora çevirir."""
    y, d = s["yukleme"], s["degerlendirme"]
    yz = lambda x: f"%{round(x * 100)}"
    satir = [f"# Usta: kendi verinle sonuç ({datetime.now():%Y-%m-%d %H:%M})", "",
             f"- Çağrı: {y['cagri']} ({y['ilk_tarih']} – {y['son_tarih']}), atlanan satır: {y['hatali']}",
             f"- Birim: {y['birim']}, kişi: {y['kisi']}, konu: {y['konu']}",
             f"- Çözüm notu olan çağrı: {y['notlu']}, yeniden atanmış: {y['yeniden_atama']}"]
    if s["dokum"]:
        satir.append(f"- Bakım dökümü: {s['dokum']['satir']} kayıt, {s['dokum']['yeni_konu']} konu")
    satir += ["", "## Model başarısı (en yeni %20 çağrıda, eğitimde görülmeden)", ""]
    if "hata" in d:
        satir.append(f"Ölçülemedi: {d['hata']}")
    else:
        satir += [f"| Soru | Model | Eski kural |", "| --- | --- | --- |",
                  f"| Konu doğru mu? | {yz(d['konu']['model'])} | {yz(d['konu']['kural'])} |",
                  f"| Çözen kişi ilk sırada mı? | {yz(d['kisi']['model'])} | {yz(d['kisi']['kural'])} |",
                  f"| Çözen kişi ilk üçte mi? | {yz(d['kisi']['model_ilk3'])} | {yz(d['kisi']['kural_ilk3'])} |", "",
                  f"Model test çağrılarının {yz(d['konu']['soru_orani'])} kadarında emin olamayıp soru sorardı; "
                  f"emin olduğunda konu doğruluğu {yz(d['konu']['emin_oldugunda'])}.",
                  "Eski kural: konunun anahtar kelimeleri (metinlerden otomatik çıkarıldı) metinde geçiyor mu.", ""]
    satir += ["## Risk haritası", "",
              f"Yüksek {s['risk']['kirmizi']}, orta {s['risk']['sari']}, düşük {s['risk']['yesil']} konu; "
              f"ortalama puan {s['risk']['ortalama']}.", ""]
    for r in s["en_riskli"]:
        satir.append(f"- **{r['ad']}** ({r['puan']}): {' · '.join(r['nedenler']) or '-'}")
    if y["uyarilar"]:
        satir += ["", "## Uyarılar", ""] + [f"- {u}" for u in y["uyarilar"]]
    satir += ["", "## Sonraki adım", "", f"`EMANET_DB={db_yolu} python -m emanet` ile aç; "
              "tarayıcıda http://localhost:8000 adresinde kendi verinle çalışır. Veri bu makineden çıkmaz."]
    return "\n".join(satir) + "\n"


def ornek_uret(yol: Path) -> int:
    """Biçimi göstermek için sentetik veriden örnek çağrı dosyası üretir (sütun adları Türkçe başlıklarla)."""
    from datetime import date
    from . import veri_uret
    from .db import baglan
    con = baglan(":memory:")
    veri_uret.uret(con, date.today())
    satirlar = con.execute(
        "SELECT c.acilis, c.metin, k.ad konu, b.ad birim, p.ad cozen, c.sure_dk, c.cozum_notu, c.aciliyet, c.acan_birim "
        "FROM cagri c JOIN kategori k ON k.id=c.kategori_id JOIN birim b ON b.id=k.birim_id "
        "JOIN kisi p ON p.id=c.cozen_kisi_id WHERE c.kaynak='usta' AND c.durum='kapali' ORDER BY c.acilis").fetchall()
    with open(yol, "w", newline="", encoding="utf-8-sig") as f:
        w = csv.writer(f, delimiter=";")
        w.writerow(["Açılış tarihi", "Açıklama", "Kategori", "Destek grubu", "Çözen kişi", "Süre (dk)",
                    "Çözüm", "Öncelik", "Açan birim"])
        for r in satirlar:
            w.writerow([r[0].replace("T", " "), r[1], r[2], r[3], r[4], r[5],
                        (r[6] or "").replace("\n", " / "), r[7], r[8]])
    con.close()
    return len(satirlar)


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="python -m emanet.yerel", description="Kendi çağrı verinle Usta ve Emanet'i yerelde kur.")
    p.add_argument("cagrilar", nargs="?", help="çağrı dökümü (CSV)")
    p.add_argument("--dokum", help="isteğe bağlı teknik arıza dökümü (tarih;birim;konu;cozen;sure_dk)")
    p.add_argument("--db", default="veri/yerel.db", help="oluşturulacak veritabanı (varsayılan veri/yerel.db)")
    p.add_argument("--takma-ad", action="store_true", help="kişi adlarını 'Kişi 01'... olarak sakla")
    p.add_argument("--bugune-kaydir", action="store_true", help="tarihleri son kayıt bugün olacak şekilde kaydır")
    p.add_argument("--ornek", metavar="DOSYA", help="biçimi gösteren örnek çağrı dosyası üret ve çık")
    a = p.parse_args(argv)
    if a.ornek:
        n = ornek_uret(Path(a.ornek))
        print(f"{a.ornek} yazıldı ({n} çağrı). Kurmak için: python -m emanet.yerel {a.ornek} --bugune-kaydir")
        return 0
    if not a.cagrilar:
        p.error("çağrı dosyası gerekli (ya da --ornek)")
    oku_ = lambda y: Path(y).read_text(encoding="utf-8-sig", errors="replace")
    db = Path(a.db)
    if db.exists() and db.stat().st_size:
        # Yalnızca daha önce bu komutla kurulmuş bir veritabanının üzerine yazılır (demo verisi korunur)
        c = sqlite3.connect(db)
        try:
            mod = c.execute("SELECT deger FROM meta WHERE anahtar='mod'").fetchone()
        except sqlite3.Error:
            mod = None
        c.close()
        if not mod or mod[0] != "yerel":
            p.error(f"{db} zaten var ve yerel kurulum değil; üzerine yazmamak için başka bir ad verin")
    try:
        s = kur(db, oku_(a.cagrilar), oku_(a.dokum) if a.dokum else None, a.takma_ad, a.bugune_kaydir)
    except ValueError as e:
        print(f"Hata: {e}", file=sys.stderr)
        return 1
    md = rapor(s, db)
    (db.parent / f"{db.stem}_rapor.md").write_text(md, encoding="utf-8")
    if s["yukleme"]["takma_ad"]:
        with open(db.parent / f"{db.stem}_takma_adlar.csv", "w", newline="", encoding="utf-8-sig") as f:
            w = csv.writer(f, delimiter=";")
            w.writerow(["Takma ad", "Gerçek ad"])
            for gercek, takma in s["yukleme"]["takma_ad"].items():
                w.writerow([takma, gercek])
    print(md)
    print(f"Rapor: {db.parent / (db.stem + '_rapor.md')}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
