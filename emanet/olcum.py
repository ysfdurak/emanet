"""Çağrı ölçüleri: kapanma süreleri, kişi başı iş yükü, ilk seferde çözme, haftalık akış.

Alan uzmanı gözüyle üç kural:
- Ortalama değil ortanca ve %90'lık dilim: birkaç günlük çağrı ortalamayı bozar, ortanca tipik çağrıyı söyler,
  %90'lık dilim "kötü günler"i.
- Kişileri ham süreyle karşılaştırmak haksızdır: ERP çağrısı şifre çağrısından uzun sürer. Kişinin hızı
  "konuya göre" ölçülür (çağrının süresi / o konunun ortancası; 1,0 = konunun tipik hızı).
- Ekran sıralama tablosu değildir: kişiler ada göre sıralanır, amaç iş yükünü dengelemek ve kimin
  yardıma ihtiyacı olduğunu görmektir, yarıştırmak değil.

Net süre: çağrının "Bilgi bekleniyor"da geçen kısmı (top açandayken) çözene yazılmaz.
"""
from __future__ import annotations

import sqlite3
from collections import defaultdict
from datetime import datetime, timedelta
from statistics import median

from . import katalog as K


def _yuzdelik(degerler: list[float], p: float) -> float | None:
    if not degerler:
        return None
    s = sorted(degerler)
    return s[min(len(s) - 1, int(round(p * (len(s) - 1))))]


def _bekleme_dk(con: sqlite3.Connection, ids: list[int]) -> dict[int, float]:
    """Çağrı başına 'Bilgi bekleniyor'da geçen dakika (durum geçişlerinden)."""
    out: dict[int, float] = defaultdict(float)
    if not ids:
        return out
    acik: dict[int, datetime] = {}
    for parca in range(0, len(ids), 500):
        dilim = ids[parca:parca + 500]
        satir = con.execute(f"SELECT cagri_id, zaman, aciklama FROM cagri_olay WHERE tur='durum' AND cagri_id IN "
                            f"({','.join('?' * len(dilim))}) ORDER BY cagri_id, zaman, id", dilim).fetchall()
        for r in satir:
            z = datetime.fromisoformat(r["zaman"][:16])
            a = r["aciklama"] or ""
            if "→ Bilgi bekleniyor" in a:
                acik[r["cagri_id"]] = z
            elif a.startswith("Bilgi bekleniyor →") and r["cagri_id"] in acik:
                out[r["cagri_id"]] += (z - acik.pop(r["cagri_id"])).total_seconds() / 60
    return out


def cagri_olculeri(con: sqlite3.Connection, gun: int = 30, simdi: datetime | None = None) -> dict:
    simdi = simdi or datetime.now()
    gun = max(7, min(int(gun), 180))
    bas = (simdi - timedelta(days=gun)).isoformat(timespec="minutes")
    usta_birim = tuple(K.USTA_BIRIMLERI)
    kapanan = [dict(r) for r in con.execute(
        "SELECT c.id, c.kategori_id, k.ad AS konu, c.cozen_kisi_id, c.sure_dk, c.otomatik, c.teyit, c.acilis, c.kapanis, c.acan_kisi "
        "FROM cagri c JOIN kategori k ON k.id=c.kategori_id WHERE c.kaynak='usta' AND c.durum='kapali' "
        "AND c.kapanis>=? AND c.sure_dk IS NOT NULL", (bas,))]
    bekleme = _bekleme_dk(con, [c["id"] for c in kapanan])
    for c in kapanan:
        c["net"] = max(1.0, c["sure_dk"] - bekleme.get(c["id"], 0))
    acilan = con.execute("SELECT COUNT(*) FROM cagri WHERE kaynak='usta' AND acilis>=?", (bas,)).fetchone()[0]
    acik = [dict(r) for r in con.execute(
        "SELECT c.id, c.atanan_kisi_id, c.asama, c.acilis, c.aciliyet, c.kategori_id FROM cagri c "
        "WHERE c.kaynak='usta' AND c.durum='acik'")]
    onay = con.execute("SELECT COUNT(*) FROM cagri WHERE kaynak='usta' AND asama='cozuldu'").fetchone()[0]
    yeniden = {r["cagri_id"]: r["kisi_id"] for r in con.execute(
        "SELECT cagri_id, kisi_id FROM cagri_olay WHERE tur='yeniden_acildi' AND zaman>=?", (bas,))}
    sorulan = [c for c in kapanan if c["acan_kisi"]]   # "çözüldü mü?" sorusu gidenler

    def yas_saat(iso: str) -> float:
        return round((simdi - datetime.fromisoformat(iso)).total_seconds() / 3600, 1)

    net = [c["net"] for c in kapanan]
    ozet = dict(gun=gun, acilan=acilan, kapanan=len(kapanan), acik=len(acik),
                bilgi_bekleniyor=sum(1 for a in acik if a["asama"] == "bilgi_bekleniyor"), onay_bekleyen=onay,
                ortanca_dk=round(median(net)) if net else None, p90_dk=round(_yuzdelik(net, 0.9)) if net else None,
                otomatik_pay=round(sum(c["otomatik"] for c in kapanan) / len(kapanan), 2) if kapanan else 0,
                yeniden_acilan=len(yeniden),
                ilk_seferde=round(1 - len(yeniden) / len(kapanan), 2) if kapanan else None,
                onaylanan_pay=round(sum(1 for c in sorulan if c["teyit"] == 1) / len(sorulan), 2) if sorulan else None,
                en_eski_acik_saat=max((yas_saat(a["acilis"]) for a in acik), default=None))

    # Konu: tipik süre (kişinin hızını konuya göre ölçmek için de gerekir)
    konu_sure: dict[int, list[float]] = defaultdict(list)
    for c in kapanan:
        konu_sure[c["kategori_id"]].append(c["net"])
    konu_ortanca = {k: median(v) for k, v in konu_sure.items()}
    konu_ad = {c["kategori_id"]: c["konu"] for c in kapanan}
    acik_konu = defaultdict(int)
    for a in acik:
        acik_konu[a["kategori_id"]] += 1
    konular = sorted(
        (dict(kategori_id=k, ad=konu_ad[k], kapanan=len(v), ortanca_dk=round(median(v)), p90_dk=round(_yuzdelik(v, 0.9)),
              acik=acik_konu.get(k, 0)) for k, v in konu_sure.items()),
        key=lambda x: -x["kapanan"])

    # Kişi: üzerindeki açık iş, kapattığı, konuya göre hızı, yeniden açılan
    kisiler = []
    for p in con.execute("SELECT k.id, k.ad, k.vardiya, b.ad AS birim FROM kisi k JOIN birim b ON b.id=k.birim_id "
                         f"WHERE b.ad IN ({','.join('?' * len(usta_birim))}) AND k.cikis IS NULL ORDER BY k.ad", usta_birim):
        uzerinde = [a for a in acik if a["atanan_kisi_id"] == p["id"]]
        kendi = [c for c in kapanan if c["cozen_kisi_id"] == p["id"]]
        oran = [c["net"] / konu_ortanca[c["kategori_id"]] for c in kendi if konu_ortanca.get(c["kategori_id"])]
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
            konu_sayisi=len({c["kategori_id"] for c in kendi}), yeniden_acilan=yn))
    ort_yuk = (sum(k["uzerinde"] for k in kisiler) / len(kisiler)) if kisiler else 0
    for k in kisiler:   # iş yükü ortalamanın iki katı ve en az 3: dengelemek gerekir
        k["yuk_fazla"] = k["uzerinde"] >= 3 and k["uzerinde"] >= 2 * ort_yuk

    # Haftalık akış: açılan ve kapanan (birikme var mı?)
    haftalar = []
    for i in range(7, -1, -1):
        hb = (simdi - timedelta(days=7 * (i + 1))).isoformat(timespec="minutes")
        hs = (simdi - timedelta(days=7 * i)).isoformat(timespec="minutes")
        a = con.execute("SELECT COUNT(*) FROM cagri WHERE kaynak='usta' AND acilis>=? AND acilis<?", (hb, hs)).fetchone()[0]
        k = con.execute("SELECT COUNT(*) FROM cagri WHERE kaynak='usta' AND kapanis>=? AND kapanis<?", (hb, hs)).fetchone()[0]
        haftalar.append(dict(bitis=hs[:10], acilan=a, kapanan=k))
    return dict(ozet=ozet, kisiler=kisiler, konular=konular, haftalar=haftalar)
