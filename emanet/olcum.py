"""Çağrı ölçüleri: kapanma süreleri, kişi başı iş yükü, ilk seferde çözme, haftalık akış.

Alan uzmanı gözüyle üç kural:
- Ortalama değil ortanca ve %90'lık dilim: birkaç günlük çağrı ortalamayı bozar, ortanca tipik çağrıyı söyler,
  %90'lık dilim "kötü günler"i.
- Kişileri ham süreyle karşılaştırmak haksızdır: ERP çağrısı şifre çağrısından uzun sürer. Kişinin hızı
  "konuya göre" ölçülür (çağrının süresi / o konunun ortancası; 1,0 = konunun tipik hızı).
- Ekran sıralama tablosu değildir: kişiler ada göre sıralanır, amaç iş yükünü dengelemek ve kimin
  yardıma ihtiyacı olduğunu görmektir, yarıştırmak değil.

Süre dört parçaya ayrılır (depo 6 gün, 3 vardiya; pazar kapalı):
- çalışma: çözenin kendi vardiyasında (ve izinde değilken) geçen süre; kişinin süresi budur,
- vardiya beklemesi: çözen vardiyada ya da işte değilken geçen süre; kişinin değil kapsama boşluğunun
  süresidir ve konu bazında toplanır ("bu konu ayda kaç saat bilen birini bekledi"),
- bilgi bekleme: açandan cevap beklenen süre (top açanda),
- depo kapalı: pazar.
Hizmet süresi (açanın gözünden, hedeflerin ölçtüğü) = çalışma + vardiya beklemesi.
"""
from __future__ import annotations

import json
import sqlite3
from collections import defaultdict
from datetime import date, datetime, timedelta
from statistics import median

from . import katalog as K


VARDIYA_SAAT = {"gunduz": (8, 16), "aksam": (16, 24), "gece": (0, 8)}
KAPALI_GUNLER = {6}   # pazar (Python: pazartesi 0)


def parcala(bas: datetime, bit: datetime, vardiya: str | None, izin_gunleri: set[date] | frozenset = frozenset(),
            bilgi: list[tuple[datetime, datetime]] | None = None) -> dict[str, float]:
    """[bas, bit) aralığını dakika olarak çalışma / vardiya beklemesi / bilgi / kapalı diye böler."""
    sonuc = dict(calisma=0.0, bekleme=0.0, bilgi=0.0, kapali=0.0)
    if bit <= bas:
        return sonuc
    bilgi = bilgi or []
    noktalar = {bas, bit}
    g = datetime.combine(bas.date(), datetime.min.time())
    while g < bit:   # vardiya ve gün sınırları
        for s in (0, 8, 16):
            t = g + timedelta(hours=s)
            if bas < t < bit:
                noktalar.add(t)
        g += timedelta(days=1)
    for a, b in bilgi:
        for t in (a, b):
            if bas < t < bit:
                noktalar.add(t)
    sirali = sorted(noktalar)
    b0, b1 = VARDIYA_SAAT.get(vardiya, (None, None))
    for x, y in zip(sirali, sirali[1:]):
        m = x + (y - x) / 2
        dk = (y - x).total_seconds() / 60
        if any(a <= m < b for a, b in bilgi):
            sonuc["bilgi"] += dk
        elif m.weekday() in KAPALI_GUNLER:
            sonuc["kapali"] += dk
        elif b0 is not None and b0 <= m.hour < b1 and m.date() not in izin_gunleri:
            sonuc["calisma"] += dk
        else:
            sonuc["bekleme"] += dk
    return {k: round(v, 1) for k, v in sonuc.items()}


def hedefler(con: sqlite3.Connection) -> dict[int, dict]:
    """Öncelik hedefleri (kullanıcı girer; girilmeyen öncelikte hedef yok). {aciliyet: {tepki_dk, cozum_dk}}"""
    r = con.execute("SELECT deger FROM meta WHERE anahtar='oncelik_hedefleri'").fetchone()
    return {int(k): v for k, v in json.loads(r[0]).items()} if r else {}


def hedef_kaydet(con: sqlite3.Connection, aciliyet: int, tepki_dk: int | None, cozum_dk: int | None) -> dict:
    if aciliyet not in (1, 2, 3):
        raise ValueError("Öncelik 1, 2 ya da 3 olmalı")
    for x in (tepki_dk, cozum_dk):
        if x is not None and not 5 <= x <= 60 * 24 * 14:
            raise ValueError("Hedef 5 dakika ile 14 gün arasında olmalı")
    h = hedefler(con)
    if tepki_dk is None and cozum_dk is None:
        h.pop(aciliyet, None)
    else:
        h[aciliyet] = dict(tepki_dk=tepki_dk, cozum_dk=cozum_dk)
    con.execute("INSERT INTO meta(anahtar, deger) VALUES('oncelik_hedefleri', ?) ON CONFLICT(anahtar) DO UPDATE SET deger=excluded.deger",
                (json.dumps({str(k): v for k, v in h.items()}),))
    con.commit()
    return h


def _yuzdelik(degerler: list[float], p: float) -> float | None:
    if not degerler:
        return None
    s = sorted(degerler)
    return s[min(len(s) - 1, int(round(p * (len(s) - 1))))]


def _gecisler(con: sqlite3.Connection, ids: list[int]) -> tuple[dict[int, list], dict[int, datetime]]:
    """Çağrı başına bilgi bekleme aralıkları ve ilk işleme alınma anı (durum geçişlerinden)."""
    araliklar: dict[int, list] = defaultdict(list)
    ilk_islem: dict[int, datetime] = {}
    if not ids:
        return araliklar, ilk_islem
    acik: dict[int, datetime] = {}
    for parca in range(0, len(ids), 500):
        dilim = ids[parca:parca + 500]
        satir = con.execute(f"SELECT cagri_id, zaman, aciklama FROM cagri_olay WHERE tur='durum' AND cagri_id IN "
                            f"({','.join('?' * len(dilim))}) ORDER BY cagri_id, zaman, id", dilim).fetchall()
        for r in satir:
            z = datetime.fromisoformat(r["zaman"][:16])
            a = r["aciklama"] or ""
            if "→ İşlemde" in a and r["cagri_id"] not in ilk_islem and a.startswith(("Atandı", "Açık")):
                ilk_islem[r["cagri_id"]] = z
            if "→ Bilgi bekleniyor" in a:
                acik[r["cagri_id"]] = z
            elif a.startswith("Bilgi bekleniyor →") and r["cagri_id"] in acik:
                araliklar[r["cagri_id"]].append((acik.pop(r["cagri_id"]), z))
    return araliklar, ilk_islem


def _bekleme_dk(con: sqlite3.Connection, ids: list[int]) -> dict[int, float]:
    """Çağrı başına 'Bilgi bekleniyor'da geçen dakika."""
    ar, _ = _gecisler(con, ids)
    return {k: sum((b - a).total_seconds() / 60 for a, b in v) for k, v in ar.items()}


def _izinler(con: sqlite3.Connection) -> dict[int, set[date]]:
    out: dict[int, set[date]] = defaultdict(set)
    for r in con.execute("SELECT kisi_id, baslangic, bitis FROM musaitlik"):
        g, s = date.fromisoformat(r["baslangic"]), date.fromisoformat(r["bitis"])
        while g <= s:
            out[r["kisi_id"]].add(g)
            g += timedelta(days=1)
    return out


def cagri_olculeri(con: sqlite3.Connection, gun: int = 30, simdi: datetime | None = None,
                   lokasyon_id: int | None = None) -> dict:
    simdi = simdi or datetime.now()
    gun = max(7, min(int(gun), 180))
    bas = (simdi - timedelta(days=gun)).isoformat(timespec="minutes")
    usta_birim = tuple(K.USTA_BIRIMLERI)
    vardiya = {r["id"]: r["vardiya"] for r in con.execute("SELECT id, vardiya FROM kisi")}
    izin = _izinler(con)
    hd = hedefler(con)
    kapanan = [dict(r) for r in con.execute(
        "SELECT c.id, c.kategori_id, k.ad AS konu, c.cozen_kisi_id, c.sure_dk, c.otomatik, c.teyit, c.acilis, c.kapanis, "
        "c.acan_kisi, c.aciliyet, c.lokasyon_id FROM cagri c JOIN kategori k ON k.id=c.kategori_id WHERE c.kaynak='usta' "
        "AND c.durum='kapali' AND c.kapanis>=? AND c.sure_dk IS NOT NULL", (bas,))
        if not lokasyon_id or r["lokasyon_id"] == lokasyon_id]
    acik = [dict(r) for r in con.execute(
        "SELECT c.id, c.atanan_kisi_id, c.asama, c.acilis, c.aciliyet, c.kategori_id, c.lokasyon_id, k.ad AS konu FROM cagri c "
        "JOIN kategori k ON k.id=c.kategori_id WHERE c.kaynak='usta' AND c.durum='acik'")
        if not lokasyon_id or r["lokasyon_id"] == lokasyon_id]
    bilgi, ilk_islem = _gecisler(con, [c["id"] for c in kapanan] + [a["id"] for a in acik])

    def ayir(c: dict, kisi: int | None, son: datetime) -> dict:
        a = datetime.fromisoformat(c["acilis"])
        return parcala(a, son, vardiya.get(kisi), izin.get(kisi, frozenset()), bilgi.get(c["id"]))

    for c in kapanan:
        p = ayir(c, c["cozen_kisi_id"], datetime.fromisoformat(c["kapanis"]))
        c.update(p, net=max(1.0, p["calisma"]), hizmet=p["calisma"] + p["bekleme"])
        if c["id"] in ilk_islem:
            t = ayir(c, c["cozen_kisi_id"], ilk_islem[c["id"]])
            c["tepki"] = t["calisma"] + t["bekleme"]
    for a in acik:   # açık çağrının şimdiye kadarki hizmet süresi (hedef aşımı için)
        p = ayir(a, a["atanan_kisi_id"], simdi)
        a["hizmet"] = p["calisma"] + p["bekleme"]
    lk = " AND lokasyon_id=?" if lokasyon_id else ""
    la = (lokasyon_id,) if lokasyon_id else ()
    acilan = con.execute("SELECT COUNT(*) FROM cagri WHERE kaynak='usta' AND acilis>=?" + lk, (bas, *la)).fetchone()[0]
    onay = con.execute("SELECT COUNT(*) FROM cagri WHERE kaynak='usta' AND asama='cozuldu'" + lk, la).fetchone()[0]
    yeniden = {r["cagri_id"]: r["kisi_id"] for r in con.execute(
        "SELECT o.cagri_id, o.kisi_id FROM cagri_olay o JOIN cagri c ON c.id=o.cagri_id WHERE o.tur='yeniden_acildi' AND o.zaman>=?"
        + (" AND c.lokasyon_id=?" if lokasyon_id else ""), (bas, *la))}
    sorulan = [c for c in kapanan if c["acan_kisi"]]   # "çözüldü mü?" sorusu gidenler

    def yas_saat(iso: str) -> float:
        return round((simdi - datetime.fromisoformat(iso)).total_seconds() / 3600, 1)

    net = [c["net"] for c in kapanan]
    hizmet = [c["hizmet"] for c in kapanan]
    tepki = [c["tepki"] for c in kapanan if "tepki" in c]
    toplam = {k: round(sum(c[k] for c in kapanan) / 60) for k in ("calisma", "bekleme", "bilgi", "kapali")}
    # Hedef aşımı: hizmet süresi (açanın gözünden) öncelik hedefini geçti mi
    asim = dict(cozum=0, tepki=0, acik=0)
    for c in kapanan:
        h = hd.get(c["aciliyet"]) or {}
        if h.get("cozum_dk") and c["hizmet"] > h["cozum_dk"]:
            asim["cozum"] += 1
        if h.get("tepki_dk") and "tepki" in c and c["tepki"] > h["tepki_dk"]:
            asim["tepki"] += 1
    for a in acik:
        h = hd.get(a["aciliyet"]) or {}
        if h.get("cozum_dk") and a["hizmet"] > h["cozum_dk"]:
            asim["acik"] += 1
    ozet = dict(gun=gun, acilan=acilan, kapanan=len(kapanan), acik=len(acik),
                bilgi_bekleniyor=sum(1 for a in acik if a["asama"] == "bilgi_bekleniyor"), onay_bekleyen=onay,
                ortanca_dk=round(median(net)) if net else None, p90_dk=round(_yuzdelik(net, 0.9)) if net else None,
                hizmet_ortanca_dk=round(median(hizmet)) if hizmet else None,
                hizmet_p90_dk=round(_yuzdelik(hizmet, 0.9)) if hizmet else None,
                tepki_ortanca_dk=round(median(tepki)) if tepki else None, tepki_olculen=len(tepki),
                toplam_saat=toplam,
                otomatik_pay=round(sum(c["otomatik"] for c in kapanan) / len(kapanan), 2) if kapanan else 0,
                yeniden_acilan=len(yeniden),
                ilk_seferde=round(1 - len(yeniden) / len(kapanan), 2) if kapanan else None,
                onaylanan_pay=round(sum(1 for c in sorulan if c["teyit"] == 1) / len(sorulan), 2) if sorulan else None,
                en_eski_acik_saat=max((yas_saat(a["acilis"]) for a in acik), default=None),
                hedefler={str(k): v for k, v in hd.items()}, hedef_asimi=asim)

    # Konu: tipik çalışma süresi ve vardiya beklemesi (kapsama boşluğu)
    konu_sure: dict[int, list[float]] = defaultdict(list)
    konu_bekleme: dict[int, float] = defaultdict(float)
    for c in kapanan:
        konu_sure[c["kategori_id"]].append(c["net"])
        konu_bekleme[c["kategori_id"]] += c["bekleme"]
    konu_ortanca = {k: median(v) for k, v in konu_sure.items()}
    konu_ad = {c["kategori_id"]: c["konu"] for c in kapanan}
    acik_konu = defaultdict(int)
    for a in acik:
        acik_konu[a["kategori_id"]] += 1
    konular = sorted(
        (dict(kategori_id=k, ad=konu_ad[k], kapanan=len(v), ortanca_dk=round(median(v)), p90_dk=round(_yuzdelik(v, 0.9)),
              bekleme_saat=round(konu_bekleme[k] / 60, 1),
              bekleme_cagri_basi_dk=round(konu_bekleme[k] / len(v)), acik=acik_konu.get(k, 0)) for k, v in konu_sure.items()),
        key=lambda x: -x["kapanan"])

    # Kişi: üzerindeki açık iş, kapattığı, konuya göre hızı (yalnız kendi vardiyasındaki süre), ilk tepki
    kisiler = []
    for p in con.execute("SELECT k.id, k.ad, k.vardiya, b.ad AS birim FROM kisi k JOIN birim b ON b.id=k.birim_id "
                         f"WHERE b.ad IN ({','.join('?' * len(usta_birim))}) AND k.cikis IS NULL ORDER BY k.ad", usta_birim):
        uzerinde = [a for a in acik if a["atanan_kisi_id"] == p["id"]]
        kendi = [c for c in kapanan if c["cozen_kisi_id"] == p["id"]]
        oran = [c["net"] / konu_ortanca[c["kategori_id"]] for c in kendi if konu_ortanca.get(c["kategori_id"])]
        tp = [c["tepki"] for c in kendi if "tepki" in c]
        yn = sum(1 for k in yeniden.values() if k == p["id"])
        if not uzerinde and not kendi:
            continue
        kisiler.append(dict(
            kisi_id=p["id"], ad=p["ad"], birim=p["birim"], vardiya=p["vardiya"],
            uzerinde=len(uzerinde), islemde=sum(1 for a in uzerinde if a["asama"] == "islemde"),
            bekliyor=sum(1 for a in uzerinde if a["asama"] == "bilgi_bekleniyor"),
            yuksek=sum(1 for a in uzerinde if a["aciliyet"] == 3),
            en_eski_saat=max((yas_saat(a["acilis"]) for a in uzerinde), default=None),
            kapattigi=len(kendi), ortanca_dk=round(median([c["net"] for c in kendi])) if kendi else None,
            konuya_gore=round(median(oran), 2) if oran else None,
            tepki_ortanca_dk=round(median(tp)) if tp else None,
            konu_sayisi=len({c["kategori_id"] for c in kendi}), yeniden_acilan=yn))
    ort_yuk = (sum(k["uzerinde"] for k in kisiler) / len(kisiler)) if kisiler else 0
    for k in kisiler:   # iş yükü ortalamanın iki katı ve en az 3: dengelemek gerekir
        k["yuk_fazla"] = k["uzerinde"] >= 3 and k["uzerinde"] >= 2 * ort_yuk

    # Haftalık akış: açılan ve kapanan (birikme var mı?)
    haftalar = []
    for i in range(7, -1, -1):
        hb = (simdi - timedelta(days=7 * (i + 1))).isoformat(timespec="minutes")
        hs = (simdi - timedelta(days=7 * i)).isoformat(timespec="minutes")
        a = con.execute("SELECT COUNT(*) FROM cagri WHERE kaynak='usta' AND acilis>=? AND acilis<?" + lk, (hb, hs, *la)).fetchone()[0]
        k = con.execute("SELECT COUNT(*) FROM cagri WHERE kaynak='usta' AND kapanis>=? AND kapanis<?" + lk, (hb, hs, *la)).fetchone()[0]
        haftalar.append(dict(bitis=hs[:10], acilan=a, kapanan=k))
    # Tesis başına: açılan, yerinde bakılan işler (cihaz, ağ) ve tesiste bu işlere bakabilen kişi
    tesisler = []
    for l in con.execute("SELECT id, ad FROM lokasyon ORDER BY id"):
        if lokasyon_id and l["id"] != lokasyon_id:
            continue
        kc = [c for c in kapanan if c["lokasyon_id"] == l["id"]]
        yerinde = [k for k in con.execute(
            "SELECT DISTINCT p.ad, p.vardiya FROM kisi p JOIN kisi_alan a ON a.kisi_id=p.id "
            "WHERE p.lokasyon_id=? AND p.cikis IS NULL AND a.alan IN ('donanim','ag') ORDER BY p.ad", (l["id"],))]
        tesisler.append(dict(lokasyon_id=l["id"], ad=l["ad"], kapanan=len(kc),
                             ortanca_hizmet_dk=round(median([c["hizmet"] for c in kc])) if kc else None,
                             acik=sum(1 for a in acik if a["lokasyon_id"] == l["id"]),
                             yerinde_kisi=[dict(ad=k["ad"], vardiya=k["vardiya"]) for k in yerinde]))
    return dict(ozet=ozet, kisiler=kisiler, konular=konular, haftalar=haftalar, tesisler=tesisler)


def vardiya_boslugu(con: sqlite3.Connection, simdi: datetime | None = None, esik_saat: float = 8) -> dict | None:
    """Son 30 günde çağrıları en çok "bilen birinin vardiyasını" bekleten konu (Bugün uyarısı için)."""
    o = cagri_olculeri(con, 30, simdi)
    en = max(o["konular"], key=lambda k: k["bekleme_saat"], default=None)
    return en if en and en["bekleme_saat"] >= esik_saat else None


def tesis_kapsama(con: sqlite3.Connection) -> dict:
    """Kişiye bağımlılığın tesis boyutu: her tesiste, her vardiyada yerinde (donanım, ağ) kim var?
    Program işleri (WMS, ERP, BT genel) uzaktan çözüldüğü için tesisten bağımsızdır; yerinde işlerde bir
    vardiyada tek kişi ya da hiç kimse yoksa o kişinin yokluğu o tesiste cihaz arızalarını uzaktan bırakır."""
    alanlar = sorted(K.YERINDE_ALANLAR)
    satirlar = []
    for l in con.execute("SELECT id, ad FROM lokasyon ORDER BY id"):
        hucreler = {}
        for v in ("gunduz", "aksam", "gece"):
            for a in alanlar:
                kisiler = [r["ad"] for r in con.execute(
                    "SELECT p.ad FROM kisi p JOIN kisi_alan k ON k.kisi_id=p.id WHERE p.lokasyon_id=? AND p.vardiya=? "
                    "AND k.alan=? AND p.aktif=1 AND p.cikis IS NULL ORDER BY p.ad", (l["id"], v, a))]
                hucreler[f"{v}:{a}"] = kisiler
        cagri = con.execute("SELECT COUNT(*) FROM cagri WHERE lokasyon_id=? AND alan IN ('donanim','ag') "
                            "AND acilis>=date('now','-90 day')", (l["id"],)).fetchone()[0]
        bos = sum(1 for k in hucreler.values() if not k)
        tek = sum(1 for k in hucreler.values() if len(k) == 1)
        satirlar.append(dict(lokasyon_id=l["id"], ad=l["ad"], hucreler=hucreler, yerinde_cagri_90=cagri, bos=bos, tek=tek))
    return dict(alanlar=[dict(kod=a, ad=K.ALANLAR[a][0]) for a in alanlar], tesisler=satirlar)
