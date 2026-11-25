"""Yanlış yönlendirme: atanan kişinin "bu benim işim değil" demesi, top oynatma kuralı ve kural önerileri.

İlkeler (alan uzmanı ve kullanıcıyla kararlaştırıldı):
- Geri değil ileri: aktarılan çağrı doğru ekipte vardiyadaki en uygun kişiye gider; gönderene ya da açana dönmez.
  Açana "yanlış seçmişsin, yeniden aç" denmez; sınıflandırmayı düzeltmek sistemin işidir.
- Top oynatma kuralı: bir çağrı ikinci kez aktarılırsa artık ekipten ekibe gitmez; tek karar vericiye,
  BT müdürüne düşer. Ekibi bilinmeyen ("Bilmiyorum") çağrı da doğrudan ona gider.
- Süre adaleti: çağrının yanlış ekipte geçirdiği süre o ekibin hızına yazılmaz (ölçülerde "yönlendirme kaybı").
- Sistem öğrenir ama kuralı kendisi değiştirmez: bir belirti kuralı sık düzeltiliyorsa öneri çıkar, insan onaylar.
"""
from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timedelta

from . import katalog as K

NEDENLER = {"yanlis_ekip": "Yanlış ekip", "yanlis_konu": "Yanlış konu"}
ONERI_GUN, ONERI_EN_AZ, ONERI_ORAN = 90, 3, 0.3


def koordinator(con: sqlite3.Connection) -> dict | None:
    r = con.execute("SELECT id, ad, rol FROM kisi WHERE koordinator=1 AND aktif=1 ORDER BY id LIMIT 1").fetchone()
    return dict(r) if r else None


def _belirti(con: sqlite3.Connection, c) -> str | None:
    """Çağrının belirti cevabı (ek bilgide "Ne oluyor?" sorusunun cevabı)."""
    from .cagri_formu import sorular
    kod = con.execute("SELECT kod FROM kategori WHERE id=?", (c["kategori_id"],)).fetchone()[0]
    soru = {s["kod"]: s["soru"] for s in sorular(kod)}.get("belirti")
    if not soru or not c["ek_bilgi"]:
        return None
    return next((x["cevap"] for x in json.loads(c["ek_bilgi"]).get("cevaplar", []) if x["soru"] == soru), None)


def aktarim_sayisi(con: sqlite3.Connection, cagri_id: int) -> int:
    return con.execute("SELECT COUNT(*) FROM aktarim WHERE cagri_id=?", (cagri_id,)).fetchone()[0]


def aktar(con: sqlite3.Connection, cagri_id: int, neden: str, alan: str | None = None, kategori_id: int | None = None,
          aciklama: str | None = None, gonderen_id: int | None = None, simdi: datetime | None = None) -> dict:
    """Atanan kişi çağrıyı aktarır. alan=None ya da "bilmiyorum" → BT müdürüne. İkinci aktarım → BT müdürüne."""
    from . import usta
    simdi = simdi or datetime.now()
    c = con.execute("SELECT * FROM cagri WHERE id=? AND kaynak='usta'", (cagri_id,)).fetchone()
    if not c:
        raise ValueError("Çağrı bulunamadı")
    if c["durum"] != "acik":
        raise ValueError("Kapalı çağrı aktarılamaz")
    if neden not in NEDENLER:
        raise ValueError("Neden: yanlış ekip ya da yanlış konu")
    gonderen_id = gonderen_id or c["atanan_kisi_id"]
    yeni_kat = kategori_id or c["kategori_id"]
    if yeni_kat not in usta._usta_kategorileri(con, yalniz_gecerli=True):
        raise ValueError("Bu konu Usta'nın kapsamında değil")
    if neden == "yanlis_konu" and yeni_kat == c["kategori_id"]:
        raise ValueError("Doğru konuyu seçin")
    yeni_alan = alan if alan in K.ALANLAR else None
    if neden == "yanlis_konu" and not yeni_alan:   # konu değişti: yeni konunun alanı (belirti cevabı geçerliyse o)
        from .cagri_formu import alan_bul
        kod = con.execute("SELECT kod, alan FROM kategori WHERE id=?", (yeni_kat,)).fetchone()
        yeni_alan = alan_bul(kod["kod"], {"belirti": _belirti(con, c) or ""}, None, kod["alan"],
                             kurallar=belirti_kurallari(con))["alan"]
    if neden == "yanlis_ekip" and yeni_alan == c["alan"]:
        raise ValueError("Çağrı zaten bu ekipte; başka bir ekip seçin ya da 'Bilmiyorum' deyin")
    onceki = aktarim_sayisi(con, cagri_id)
    k = koordinator(con)
    mudur_neden = None
    if onceki >= 1:
        mudur_neden = "ikinci aktarım (top oynatma kuralı)"
    elif neden == "yanlis_ekip" and not yeni_alan:
        mudur_neden = "doğru ekip bilinmiyor"
    if mudur_neden and k:
        kisi_id, atama_notu = k["id"], f"{k['rol']} {k['ad']} karar verecek: {mudur_neden}"
    else:
        a = usta.yonlendir(con, yeni_kat, simdi, c["vardiya"], c["metin"], c["acan_birim"], c["aciliyet"],
                           c["lokasyon_id"], yeni_alan, haric={gonderen_id} if gonderen_id else None)
        kisi_id, atama_notu = a["kisi_id"], a["neden"]
    ad = lambda x: K.ALANLAR.get(x, (x or "-",))[0]
    con.execute("INSERT INTO aktarim(cagri_id,zaman,gonderen_id,alici_id,neden,eski_alan,yeni_alan,eski_kategori_id,"
                "yeni_kategori_id,belirti,aciklama,mudure) VALUES(?,?,?,?,?,?,?,?,?,?,?,?)",
                (cagri_id, simdi.isoformat(timespec="minutes"), gonderen_id, kisi_id, neden, c["alan"], yeni_alan,
                 c["kategori_id"], yeni_kat, _belirti(con, c), (aciklama or "").strip()[:200] or None, int(bool(mudur_neden))))
    con.execute("UPDATE cagri SET kategori_id=?, alan=COALESCE(?, alan), atanan_kisi_id=?, yeniden_atama=yeniden_atama+1 "
                "WHERE id=?", (yeni_kat, yeni_alan, kisi_id, cagri_id))
    gonderen = (con.execute("SELECT ad FROM kisi WHERE id=?", (gonderen_id,)).fetchone() or ["-"])[0]
    metin = (f"{NEDENLER[neden]}: {ad(c['alan'])} → {ad(yeni_alan) if yeni_alan else 'bilinmiyor'} (gönderen {gonderen})"
             + (f". {aciklama.strip()[:120]}" if aciklama and aciklama.strip() else "") + f". {atama_notu}")
    usta._olay(con, cagri_id, simdi, "aktarildi", kisi_id, metin)
    if c["asama"] in ("islemde", "bilgi_bekleniyor"):
        usta._asama(con, cagri_id, "atandi", kisi_id, "aktarıldı", simdi)
    con.commit()
    return usta.cagri_detay(con, cagri_id)


def mudur_karari(con: sqlite3.Connection, cagri_id: int, kisi_id: int, alan: str | None = None) -> dict:
    """BT müdürü çağrıyı doğrudan bir kişiye verir; bu karar bir aktarım sayılmaz (son karar)."""
    from . import usta
    c = con.execute("SELECT * FROM cagri WHERE id=? AND kaynak='usta' AND durum='acik'", (cagri_id,)).fetchone()
    if not c:
        raise ValueError("Açık çağrı bulunamadı")
    k = con.execute("SELECT ad FROM kisi WHERE id=? AND aktif=1 AND koordinator=0", (kisi_id,)).fetchone()
    if not k:
        raise ValueError("Kişi bulunamadı")
    con.execute("UPDATE cagri SET atanan_kisi_id=?, alan=COALESCE(?, alan) WHERE id=?",
                (kisi_id, alan if alan in K.ALANLAR else None, cagri_id))
    m = koordinator(con)
    usta._olay(con, cagri_id, datetime.now(), "mudur_karari", kisi_id,
               f"{m['ad'] if m else 'BT müdürü'} kararı: {k['ad']}" + (f" ({K.ALANLAR[alan][0]})" if alan in K.ALANLAR else ""))
    con.commit()
    return usta.cagri_detay(con, cagri_id)


# ---------------------------------------------------------------- belirti kuralları

def belirti_kurallari(con: sqlite3.Connection) -> dict:
    """Katalogdaki kurallar + onaylanmış değişiklikler (meta.belirti_kurali)."""
    kural = {k: {s: dict(h) for s, h in v.items()} for k, v in K.BELIRTI_ALANI.items()}
    r = con.execute("SELECT deger FROM meta WHERE anahtar='belirti_kurali'").fetchone()
    for d in json.loads(r[0]) if r else []:
        kural.setdefault(d["kod"], {}).setdefault("belirti", {})[d["belirti"]] = d["alan"]
    return kural


def _meta_liste(con, anahtar: str) -> list:
    r = con.execute("SELECT deger FROM meta WHERE anahtar=?", (anahtar,)).fetchone()
    return json.loads(r[0]) if r else []


def _meta_yaz(con, anahtar: str, deger) -> None:
    con.execute("INSERT INTO meta(anahtar, deger) VALUES(?, ?) ON CONFLICT(anahtar) DO UPDATE SET deger=excluded.deger",
                (anahtar, json.dumps(deger, ensure_ascii=False)))


def kural_onerileri(con: sqlite3.Connection, simdi: datetime | None = None) -> list[dict]:
    """Aynı belirti sık sık aynı ekibe aktarılıyorsa kural değişikliği önerisi (insan onaylar)."""
    simdi = simdi or datetime.now()
    bas = (simdi - timedelta(days=ONERI_GUN)).isoformat(timespec="minutes")
    kural = belirti_kurallari(con)
    reddedilen = {(d["kod"], d["belirti"], d["alan"]) for d in _meta_liste(con, "belirti_kurali_red")}
    out = []
    for r in con.execute(
            "SELECT k.kod, k.ad AS konu, a.belirti, a.eski_alan, a.yeni_alan, COUNT(*) n FROM aktarim a "
            "JOIN kategori k ON k.id=a.eski_kategori_id WHERE a.zaman>=? AND a.belirti IS NOT NULL AND a.yeni_alan IS NOT NULL "
            "AND a.neden='yanlis_ekip' GROUP BY 1,2,3,4,5 HAVING COUNT(*)>=?", (bas, ONERI_EN_AZ)):
        su_an = kural.get(r["kod"], {}).get("belirti", {}).get(r["belirti"])
        if su_an == r["yeni_alan"] or (r["kod"], r["belirti"], r["yeni_alan"]) in reddedilen:
            continue
        toplam = con.execute("SELECT COUNT(*) FROM cagri c JOIN kategori k ON k.id=c.kategori_id WHERE k.kod=? "
                             "AND c.acilis>=? AND c.ek_bilgi LIKE ?", (r["kod"], bas, f'%"{r["belirti"]}"%')).fetchone()[0]
        oran = r["n"] / toplam if toplam else None
        if oran is not None and oran < ONERI_ORAN:
            continue
        out.append(dict(kod=r["kod"], konu=r["konu"], belirti=r["belirti"], su_an=su_an, onerilen=r["yeni_alan"],
                        su_an_ad=K.ALANLAR.get(su_an, (su_an,))[0], onerilen_ad=K.ALANLAR[r["yeni_alan"]][0],
                        aktarilan=r["n"], toplam=toplam, oran=round(oran, 2) if oran is not None else None))
    return out


def kural_karari(con: sqlite3.Connection, kod: str, belirti: str, alan: str, onay: bool) -> dict:
    if alan not in K.ALANLAR:
        raise ValueError("Geçersiz alan")
    anahtar = "belirti_kurali" if onay else "belirti_kurali_red"
    liste = [d for d in _meta_liste(con, anahtar) if not (d["kod"] == kod and d["belirti"] == belirti)]
    liste.append(dict(kod=kod, belirti=belirti, alan=alan, zaman=datetime.now().isoformat(timespec="minutes")))
    _meta_yaz(con, anahtar, liste)
    con.commit()
    return dict(kod=kod, belirti=belirti, alan=alan, onay=onay)


def yonlendirme_olculeri(con: sqlite3.Connection, bas: str, lokasyon_id: int | None = None) -> dict:
    """Yanlış yönlendirme oranı (ekibe göre) ve BT müdüründe bekleyenler."""
    lk = " AND c.lokasyon_id=?" if lokasyon_id else ""
    la = (lokasyon_id,) if lokasyon_id else ()
    acilan = {r["alan"]: r["n"] for r in con.execute(
        "SELECT c.alan, COUNT(*) n FROM cagri c WHERE c.kaynak='usta' AND c.acilis>=?" + lk + " GROUP BY c.alan", (bas, *la))}
    aktarilan = {r["eski_alan"]: r["n"] for r in con.execute(
        "SELECT a.eski_alan, COUNT(DISTINCT a.cagri_id) n FROM aktarim a JOIN cagri c ON c.id=a.cagri_id "
        "WHERE a.zaman>=?" + lk + " GROUP BY a.eski_alan", (bas, *la))}
    alanlar = []
    for a, (ad, _) in K.ALANLAR.items():
        n, x = acilan.get(a, 0) + 0, aktarilan.get(a, 0)
        if n or x:
            alanlar.append(dict(alan=a, ad=ad, acilan=n, aktarilan=x, oran=round(x / n, 3) if n else None))
    k = koordinator(con)
    mudurde = [dict(r) for r in con.execute(
        "SELECT c.id, c.metin, c.acilis FROM cagri c WHERE c.durum='acik' AND c.atanan_kisi_id=?" + lk + " ORDER BY c.acilis",
        ((k["id"] if k else -1), *la))]
    toplam_acilan = sum(acilan.values())
    toplam_aktarilan = con.execute("SELECT COUNT(DISTINCT a.cagri_id) FROM aktarim a JOIN cagri c ON c.id=a.cagri_id "
                                   "WHERE a.zaman>=?" + lk, (bas, *la)).fetchone()[0]
    return dict(alanlar=alanlar, mudurde=mudurde, koordinator=k, aktarilan=toplam_aktarilan,
                oran=round(toplam_aktarilan / toplam_acilan, 3) if toplam_acilan else None)
