"""Devir süreci: bir kişi ayrılırken (ya da uzun süre olmayacakken) bilgisinin el değiştirmesi.

Eskiden "devir dosyası" tek seferlik bir rapordu. Gerçekte devir, ayrılış tarihine kadar süren bir
süreçtir; her konu için bir devralan seçilir ve üç aşamadan geçer:

  1. İzle       usta çözer, devralan yanında izler          (elle işaretlenir: bunu sistem göremez)
  2. Birlikte   devralan çözer, usta yanında                (devralanın ilk kapattığı çağrı)
  3. Tek başına devralan kendisi çözer                      (devralan BILEN_ESIK çağrı kapatınca)

2. ve 3. aşama beyanla değil kapanan gerçek çağrılarla ölçülür. Devir sürerken yanında öğrenme
kuralı devralana kritik konularda da çağrı verir (usta.py); yoksa kritik bir konunun devralanı
ayrılış gününe kadar hiç pratik yapamazdı.

Konu dışı devirler kontrol listesidir: açık çağrılar, ustanın bakımını yaptığı otomatik çözümlerin
yeni sahibi, yazılı çözümü olmayan konuların kartı, bilgi aktarım görüşmesi, hesapların kapatılması.
Görüşme soruları sistemin tek başına çıkaramayacağı bilgiyi (dış iletişim, yazılmamış pratikler,
dönemsel işler) yakalar. Çıktı, ayrılan, devralanlar ve yöneticinin onaylayacağı devir tutanağıdır.
"""
from __future__ import annotations

import json
import math
import random
import sqlite3
from datetime import date, datetime, timedelta

from . import egitim, risk, takip, takvim
from .egitim import BILEN_ESIK

GORUSME_SORULARI = [
    "En sık karşılaştığın üç sorun ne, ilk nereye bakıyorsun?",
    "Hiçbir yerde yazmayan ama senin bildiğin püf noktaları neler?",
    "İş için kimleri arıyorsun (tedarikçi, üretici, BT, başka depo)? Ne için, nasıl ulaşılır?",
    "Dönemsel yaptığın, kimsenin fark etmediği işler var mı (haftalık kontrol, ay sonu, sezon öncesi)?",
    "Yarım kalan ya da yakında beklenen bir iş, değişiklik var mı?",
]
ELLE_MADDELER = {
    "hesap": "Hesaplar ve yetkiler çıkış günü kapatılsın (İK kaydıyla işten çıkış paketi)",
    "ekipman": "Cihazlar, anahtarlar ve kartlar teslim alınsın",
}


AYLAR = ["Ocak", "Şubat", "Mart", "Nisan", "Mayıs", "Haziran", "Temmuz", "Ağustos", "Eylül", "Ekim", "Kasım", "Aralık"]


def tarih_tr(iso: str) -> str:
    g = date.fromisoformat(iso[:10])
    return f"{g.day} {AYLAR[g.month - 1]}"


def _simdi(simdi: datetime | None) -> datetime:
    return simdi or datetime.now()


def baslat(con: sqlite3.Connection, kisi_id: int, cikis_tarihi: str, haftalik_sinir: float = 4,
           simdi: datetime | None = None) -> dict:
    """Devri başlatır: kişinin çözdüğü konular için devralan önerileriyle devir kaydı açar.
    Kişinin açık bir devri varsa onu döner (aynı kişi için iki devir olmaz)."""
    simdi = _simdi(simdi)
    try:
        cikis = date.fromisoformat(cikis_tarihi)
    except ValueError as e:
        raise ValueError("Çıkış tarihi YYYY-AA-GG biçiminde olmalı") from e
    if cikis <= simdi.date():
        raise ValueError("Çıkış tarihi bugünden sonra olmalı")
    if not 0.5 <= haftalik_sinir <= 40:
        raise ValueError("Haftalık sınır 0,5 ile 40 saat arasında olmalı")
    var = con.execute("SELECT id FROM devir WHERE kisi_id=? AND durum='acik'", (kisi_id,)).fetchone()
    if var:
        return durum(con, var[0], simdi)
    dosya = takip.devir_dosyasi(con, kisi_id, simdi)        # devralan önerileri buradan
    ad_id = {r["ad"]: r["id"] for r in con.execute("SELECT id, ad FROM kisi")}
    cur = con.execute("INSERT INTO devir(kisi_id,cikis_tarihi,baslangic,haftalik_sinir) VALUES(?,?,?,?)",
                      (kisi_id, cikis.isoformat(), simdi.isoformat(timespec="minutes"), haftalik_sinir))
    did = cur.lastrowid
    for k in dosya["konular"]:
        con.execute("INSERT INTO devir_konu(devir_id,kategori_id,devralan_id) VALUES(?,?,?)",
                    (did, k["kategori_id"], ad_id.get(k["devralan"])))
    con.commit()
    return durum(con, did, simdi)


def _konu_durumu(con, d: dict, k: dict, v: dict) -> dict:
    """Bir konunun devir aşaması; devralanın devirden önceki ve sonraki çözümleriyle."""
    kid, dv = k["kategori_id"], k["devralan_id"]
    kat = next(x for x in v["kategoriler"] if x["id"] == kid) if any(x["id"] == kid for x in v["kategoriler"]) else None
    sayim = v["sayim"].get(kid, {})
    toplam = sum(sayim.values())
    esik = risk.yetkin_esigi(toplam) if toplam else BILEN_ESIK
    # Devirden önceki 90 gün (devir sırasında kapananlar "sonra"ya sayılır, ikisi karışmasın)
    bas = datetime.fromisoformat(d["baslangic"])
    once = con.execute("SELECT COUNT(*) FROM cagri WHERE kategori_id=? AND cozen_kisi_id=? AND durum='kapali' "
                       "AND kapanis>=? AND kapanis<?", (kid, dv, (bas - timedelta(days=risk.PENCERE_GUN)).isoformat(timespec="minutes"),
                                                       d["baslangic"])).fetchone()[0] if dv else 0
    sonra = con.execute("SELECT COUNT(*) FROM cagri WHERE kategori_id=? AND cozen_kisi_id=? AND durum='kapali' "
                        "AND kapanis>=?", (kid, dv, d["baslangic"])).fetchone()[0] if dv else 0
    zaten = dv is not None and once >= esik
    if zaten:
        asama, adim = 3, "Zaten biliyor: yalnız kartı ve özel durumları aktarın"
    elif sonra >= BILEN_ESIK:
        asama, adim = 3, f"Tek başına {sonra} çağrı kapattı"
    elif sonra >= 1:
        asama, adim = 2, f"{sonra} çağrıyı usta yanındayken çözdü; {BILEN_ESIK - sonra} çağrı daha"
    elif k["izledi"]:
        asama, adim = 1, "İzledi; sıradaki çağrıyı kendisi çözmeli"
    else:
        asama, adim = 0, "Henüz başlamadı: ustanın bir çözümünü izlesin"
    # Kalan temas saati: aşamaya göre öğretmenin kalan kısmı (+ kart yoksa kart)
    ogr = kat["ogrenme_saati"] if kat else 8
    eski = {e["kisi_id"] for e in risk.pratigi_kalmayanlar(v, kid)} if kat else set()
    tam = 0 if zaten else (math.ceil(ogr / 3 * 2) / 2 if dv in eski else ogr)
    kalan_saat = round(tam * (3 - asama) / 3 * 2) / 2
    ayrilan_pay = round(sayim.get(d["kisi_id"], 0) / toplam, 2) if toplam else 0.0
    return dict(kategori_id=kid, ad=k["ad"], kritiklik=k["kritiklik"], devralan_id=dv, devralan=k["devralan"], ayrilan_pay=ayrilan_pay,
                devralan_vardiya=k["devralan_vardiya"], izledi=bool(k["izledi"]), asama=asama, aciklama=adim,
                devirden_once=once, devirden_sonra=sonra, zaten_biliyor=zaten,
                kart_var=bool(kat["kart_var"]) if kat else False, kalan_saat=kalan_saat,
                ogretme_saati=tam, tazeleme=dv in eski)


def durum(con: sqlite3.Connection, devir_id: int, simdi: datetime | None = None) -> dict:
    simdi = _simdi(simdi)
    r = con.execute("SELECT d.*, k.ad, k.vardiya, k.birim_id, b.ad AS birim FROM devir d JOIN kisi k ON k.id=d.kisi_id "
                    "JOIN birim b ON b.id=k.birim_id WHERE d.id=?", (devir_id,)).fetchone()
    if not r:
        raise ValueError("Devir bulunamadı")
    d = dict(r)
    v = risk._veri(con, simdi)
    konular_ham = [dict(x) for x in con.execute(
        "SELECT dk.*, c.ad, c.kritiklik, p.ad AS devralan, p.vardiya AS devralan_vardiya FROM devir_konu dk "
        "JOIN kategori c ON c.id=dk.kategori_id LEFT JOIN kisi p ON p.id=dk.devralan_id "
        "WHERE dk.devir_id=? ORDER BY c.kritiklik DESC, c.ad", (devir_id,))]
    konular = [_konu_durumu(con, d, k, v) for k in konular_ham]
    gun_kaldi = (date.fromisoformat(d["cikis_tarihi"]) - simdi.date()).days

    # Kontrol listesi: kendiliğinden ölçülenler + elle işaretlenenler
    elle = {x["kod"]: bool(x["yapildi"]) for x in con.execute("SELECT kod, yapildi FROM devir_madde WHERE devir_id=?", (devir_id,))}
    acik = con.execute("SELECT COUNT(*) FROM cagri WHERE atanan_kisi_id=? AND durum='acik'", (d["kisi_id"],)).fetchone()[0]
    receteler = [dict(x) for x in con.execute("SELECT kod, ad, sahip FROM recete WHERE sahip=? AND tur!='taslak'", (d["ad"],))]
    gorusme = json.loads(d["gorusme"] or "{}")
    maddeler = [dict(kod="acik", metin=f"Açık çağrılar başkasına atansın ({acik} açık)" if acik else "Açık çağrısı kalmadı",
                     yapildi=acik == 0, otomatik=True)]
    maddeler += [dict(kod=f"sahip:{x['kod']}", metin=f"“{x['ad']}” otomatik çözümünün bakımı başka birine verilsin",
                      yapildi=False, otomatik=True, recete=x["kod"]) for x in receteler]
    # Sahipliği bu devirde devredilenler listede "yapıldı" olarak kalır
    for x in con.execute("SELECT m.kod, r.ad, r.sahip FROM devir_madde m JOIN recete r ON 'sahip:' || r.kod = m.kod "
                         "WHERE m.devir_id=? AND m.yapildi=1", (devir_id,)):
        maddeler.append(dict(kod=x["kod"], metin=f"“{x['ad']}” otomatik çözümünün bakımı devredildi (yeni sahibi {x['sahip']})",
                             yapildi=True, otomatik=True))
    # Kart: yazılı çözümü olmayan konular ve devir sırasında kartı yazılanlar
    yazilan = {r[0] for r in con.execute("SELECT DISTINCT kategori_id FROM cozum_karti WHERE olusturma>=?", (d["baslangic"],))}
    # Kartı ayrılan kişi yazar, ama yalnız asıl ustası olduğu (çözümlerin en az %40'ı onda) konularda
    maddeler += [dict(kod=f"kart:{k['kategori_id']}", metin=f"{k['ad']}: çözüm yolları karta yazılsın (ayrılmadan önce, {d['ad']} yazar)",
                      yapildi=False, otomatik=True) for k in konular if not k["kart_var"] and k["ayrilan_pay"] >= 0.4]
    maddeler += [dict(kod=f"kart:{k['kategori_id']}", metin=f"{k['ad']}: kart yazıldı", yapildi=True, otomatik=True)
                 for k in konular if k["kart_var"] and k["kategori_id"] in yazilan]
    maddeler.append(dict(kod="gorusme", metin=f"Bilgi aktarım görüşmesi ({sum(1 for c in gorusme.values() if c.strip())}/{len(GORUSME_SORULARI)} soru)",
                         yapildi=all((gorusme.get(str(i)) or "").strip() for i in range(len(GORUSME_SORULARI))), otomatik=True))
    maddeler += [dict(kod=k, metin=m, yapildi=elle.get(k, False), otomatik=False) for k, m in ELLE_MADDELER.items()]

    # Takvim: kalan devir oturumları (kart + kalan öğretme), çıkış tarihine yetişiyor mu?
    satirlar = []
    for k in konular:
        if k["devralan_id"] is None or k["asama"] >= 3:
            continue
        ogreten_id = d["kisi_id"]
        if not k["kart_var"] and k["ayrilan_pay"] >= 0.4:
            satirlar.append(dict(kategori_id=k["kategori_id"], kategori=k["ad"], tur="kart",
                                 saat=risk.kart_saati(next(x for x in v["kategoriler"] if x["id"] == k["kategori_id"])),
                                 ogreten_id=ogreten_id, ogreten=d["ad"], ogrenen_id=None, ogrenen=None,
                                 puan_once=0, puan_sonra=0))
        if k["kalan_saat"] > 0:
            satirlar.append(dict(kategori_id=k["kategori_id"], kategori=k["ad"], tur="tazeleme" if k["tazeleme"] else "egitim",
                                 saat=k["kalan_saat"], ogreten_id=ogreten_id, ogreten=d["ad"],
                                 ogrenen_id=k["devralan_id"], ogrenen=k["devralan"], puan_once=0, puan_sonra=0))
    kartli = {s["kategori_id"] for s in satirlar if s["tur"] == "kart"}
    for s in satirlar:
        s.update(egitim.icerik(con, s, kart_planda=s["kategori_id"] in kartli))
    t = (takvim.takvim_olustur(satirlar, simdi.date(), d["haftalik_sinir"], 1.0, 1, 5, ilk_gun=simdi.date())
         if satirlar else None)
    def gec_kalanlar(tk) -> list[dict]:
        out = []
        for k in konular:
            son = max((o["tarih"] for o in tk["oturumlar"] if o["kategori_id"] == k["kategori_id"]), default=None)
            if son and son > d["cikis_tarihi"]:
                out.append(dict(ad=k["ad"], bitis=son))
        return out
    yetismeyen = gec_kalanlar(t) if t else []
    onerilen_sinir = None
    if yetismeyen:   # hangi haftalık saatle yetişir? (yarım saat adımlarla, en fazla 20 saat)
        saat = d["haftalik_sinir"] + 0.5
        while saat <= 20 and onerilen_sinir is None:
            tk = takvim.takvim_olustur(satirlar, simdi.date(), saat, 1.0, 1, 5, ilk_gun=simdi.date())
            if not gec_kalanlar(tk):
                onerilen_sinir = saat
            saat += 0.5
    farkli_vardiya = [k["ad"] for k in konular if k["devralan_vardiya"] and k["devralan_vardiya"] != d["vardiya"] and k["asama"] < 3]
    uyarilar = []
    if yetismeyen:
        cozum = (f"Haftalık devir saatini {onerilen_sinir:g} saate çıkarırsanız yetişir".replace(".", ",")
                 if onerilen_sinir else "Haftada 20 saat bile yetmiyor: konuyu birden çok devralana bölün ya da çıkışı erteleyin")
        uyarilar.append(dict(seviye="kirmizi", metin=f"{len(yetismeyen)} konu çıkış gününe yetişmiyor: "
                             + ", ".join(f"{y['ad']} (devir {tarih_tr(y['bitis'])} biter)" for y in yetismeyen)
                             + f". {cozum}; ya da konuyu başka biriyle paylaştırın."))
    if farkli_vardiya:
        uyarilar.append(dict(seviye="sari", metin="Devralan farklı vardiyada: " + ", ".join(farkli_vardiya)
                             + ". Yanında öğrenme için usta ile devralanın vardiyalarını birkaç gün çakıştırın."))
    if not [k for k in konular if k["devralan_id"]]:
        uyarilar.append(dict(seviye="kirmizi", metin="Hiçbir konuya devralan seçilmedi."))
    tamam_konu = sum(1 for k in konular if k["asama"] >= 3)
    ilerleme = round((sum(k["asama"] for k in konular) / (3 * len(konular)) if konular else 1) * 0.7
                     + (sum(m["yapildi"] for m in maddeler) / len(maddeler)) * 0.3, 2)
    adaylar = [dict(id=x["id"], ad=x["ad"], vardiya=x["vardiya"]) for x in con.execute(
        "SELECT id, ad, vardiya FROM kisi WHERE birim_id=? AND id!=? AND cikis IS NULL ORDER BY ad", (d["birim_id"], d["kisi_id"]))]
    return dict(id=devir_id, durum=d["durum"], kisi=dict(id=d["kisi_id"], ad=d["ad"], birim=d["birim"], vardiya=d["vardiya"]),
                cikis_tarihi=d["cikis_tarihi"], baslangic=d["baslangic"][:10], gun_kaldi=gun_kaldi,
                haftalik_sinir=d["haftalik_sinir"], konular=konular, maddeler=maddeler, adaylar=adaylar,
                gorusme=[dict(no=i, soru=q, cevap=gorusme.get(str(i), "")) for i, q in enumerate(GORUSME_SORULARI)],
                takvim=t, uyarilar=uyarilar, ilerleme=ilerleme, onerilen_sinir=onerilen_sinir,
                ozet=dict(konu=len(konular), tamam=tamam_konu, zaten=sum(1 for k in konular if k["zaten_biliyor"]), madde=len(maddeler), madde_tamam=sum(m["yapildi"] for m in maddeler)))


def acik_devirler(con: sqlite3.Connection) -> list[dict]:
    return [dict(r) for r in con.execute(
        "SELECT d.id, d.kisi_id, k.ad, d.cikis_tarihi FROM devir d JOIN kisi k ON k.id=d.kisi_id "
        "WHERE d.durum='acik' ORDER BY d.cikis_tarihi")]


def devralanlar(con: sqlite3.Connection, kategori_id: int) -> set[int]:
    """Açık devirlerde bu konunun devralanları: yanında öğrenme onlara kritik konuda da çağrı verir."""
    return {r[0] for r in con.execute(
        "SELECT dk.devralan_id FROM devir_konu dk JOIN devir d ON d.id=dk.devir_id "
        "WHERE d.durum='acik' AND dk.kategori_id=? AND dk.devralan_id IS NOT NULL", (kategori_id,))}


def _acik_devir(con, devir_id: int) -> None:
    r = con.execute("SELECT durum FROM devir WHERE id=?", (devir_id,)).fetchone()
    if not r:
        raise ValueError("Devir bulunamadı")
    if r[0] != "acik":
        raise ValueError("Bu devir kapanmış")


def konu_guncelle(con: sqlite3.Connection, devir_id: int, kategori_id: int, devralan_id: int | None = None,
                  izledi: bool | None = None) -> None:
    _acik_devir(con, devir_id)
    if not con.execute("SELECT 1 FROM devir_konu WHERE devir_id=? AND kategori_id=?", (devir_id, kategori_id)).fetchone():
        raise ValueError("Bu konu devirde yok")
    if devralan_id is not None:
        ayni = con.execute("SELECT 1 FROM kisi k JOIN devir d ON d.id=? JOIN kisi a ON a.id=d.kisi_id "
                           "WHERE k.id=? AND k.birim_id=a.birim_id AND k.id!=a.id AND k.cikis IS NULL",
                           (devir_id, devralan_id)).fetchone()
        if not ayni:
            raise ValueError("Devralan aynı birimden, ayrılan kişi dışında biri olmalı")
        con.execute("UPDATE devir_konu SET devralan_id=?, izledi=0 WHERE devir_id=? AND kategori_id=?",
                    (devralan_id, devir_id, kategori_id))
    if izledi is not None:
        con.execute("UPDATE devir_konu SET izledi=? WHERE devir_id=? AND kategori_id=?", (int(izledi), devir_id, kategori_id))
    con.commit()


def madde_isaretle(con: sqlite3.Connection, devir_id: int, kod: str, yapildi: bool) -> None:
    _acik_devir(con, devir_id)
    if kod not in ELLE_MADDELER:
        raise ValueError("Bu madde kendiliğinden ölçülüyor ya da yok")
    con.execute("INSERT INTO devir_madde(devir_id,kod,yapildi) VALUES(?,?,?) "
                "ON CONFLICT(devir_id,kod) DO UPDATE SET yapildi=excluded.yapildi", (devir_id, kod, int(yapildi)))
    con.commit()


def gorusme_kaydet(con: sqlite3.Connection, devir_id: int, soru_no: int, cevap: str) -> None:
    _acik_devir(con, devir_id)
    if not 0 <= soru_no < len(GORUSME_SORULARI):
        raise ValueError("Soru bulunamadı")
    if len(cevap) > 2000:
        raise ValueError("Cevap en fazla 2000 karakter olabilir")
    g = json.loads(con.execute("SELECT gorusme FROM devir WHERE id=?", (devir_id,)).fetchone()[0] or "{}")
    g[str(soru_no)] = cevap.strip()
    con.execute("UPDATE devir SET gorusme=? WHERE id=?", (json.dumps(g, ensure_ascii=False), devir_id))
    con.commit()


def sahip_degistir(con: sqlite3.Connection, devir_id: int, recete_kod: str, yeni_sahip_id: int) -> None:
    """Ayrılan kişinin bakımını yaptığı otomatik çözümü başka birine verir."""
    _acik_devir(con, devir_id)
    ad = con.execute("SELECT k.ad FROM devir d JOIN kisi k ON k.id=d.kisi_id WHERE d.id=?", (devir_id,)).fetchone()[0]
    yeni = con.execute("SELECT ad FROM kisi WHERE id=? AND cikis IS NULL", (yeni_sahip_id,)).fetchone()
    if not yeni:
        raise ValueError("Yeni sahip bulunamadı")
    n = con.execute("UPDATE recete SET sahip=? WHERE kod=? AND sahip=?", (yeni[0], recete_kod, ad)).rowcount
    if not n:
        raise ValueError("Bu otomatik çözüm ayrılan kişiye ait değil")
    con.execute("INSERT OR REPLACE INTO devir_madde(devir_id,kod,yapildi) VALUES(?,?,1)", (devir_id, f"sahip:{recete_kod}"))
    con.commit()


def haftalik_sinir_ayarla(con: sqlite3.Connection, devir_id: int, saat: float) -> None:
    _acik_devir(con, devir_id)
    if not 0.5 <= saat <= 40:
        raise ValueError("Haftalık sınır 0,5 ile 40 saat arasında olmalı")
    con.execute("UPDATE devir SET haftalik_sinir=? WHERE id=?", (saat, devir_id))
    con.commit()


def kapat(con: sqlite3.Connection, devir_id: int) -> None:
    _acik_devir(con, devir_id)
    con.execute("UPDATE devir SET durum='tamam' WHERE id=?", (devir_id,))
    con.commit()


ASAMA_ADI = ["Başlamadı", "İzledi", "Birlikte çözüyor", "Tek başına"]


def tutanak(con: sqlite3.Connection, devir_id: int, simdi: datetime | None = None) -> str:
    """Onaylanacak devir tutanağı (Markdown)."""
    d = durum(con, devir_id, simdi)
    s = [f"# Devir tutanağı: {d['kisi']['ad']}", "",
         f"- Birim: {d['kisi']['birim']}  ", f"- Devir başlangıcı: {d['baslangic']}  ",
         f"- Son çalışma günü: {d['cikis_tarihi']} ({d['gun_kaldi']} gün kaldı)  ",
         f"- Durum: {d['ozet']['tamam'] - d['ozet']['zaten']}/{d['ozet']['konu'] - d['ozet']['zaten']} konu devredildi "
         f"({d['ozet']['zaten']} konuda devralan işi zaten biliyordu), "
         f"{d['ozet']['madde_tamam']}/{d['ozet']['madde']} madde tamam", "", "## Konular", "",
         "| Konu | Devralan | Aşama | Kanıt |", "| --- | --- | --- | --- |"]
    for k in d["konular"]:
        s.append(f"| {k['ad']} | {k['devralan'] or '—'} | {ASAMA_ADI[k['asama']]} | {k['aciklama']} |")
    s += ["", "## Kontrol listesi", ""] + [f"- [{'x' if m['yapildi'] else ' '}] {m['metin']}" for m in d["maddeler"]]
    s += ["", "## Bilgi aktarım görüşmesi", ""]
    for g in d["gorusme"]:
        s += [f"**{g['soru']}**", "", (g["cevap"] or "_(cevaplanmadı)_"), ""]
    if d["uyarilar"]:
        s += ["## Açık riskler", ""] + [f"- {u['metin']}" for u in d["uyarilar"]] + [""]
    s += ["## Onay", "", "| Rol | Ad | İmza / tarih |", "| --- | --- | --- |", f"| Ayrılan | {d['kisi']['ad']} | |"]
    s += [f"| Devralan | {ad} | |" for ad in dict.fromkeys(k["devralan"] for k in d["konular"] if k["devralan"])]
    s += ["| Yönetici | | |", ""]
    return "\n".join(s)


def ilerlet_demo(con: sqlite3.Connection, devir_id: int, gun: int = 14, tohum: int = 11,
                 simdi: datetime | None = None) -> dict:
    """DEMO: devir 'gun' gün önce başlamış gibi davranır; devralanların bir kısmı izlemiş, birkaç çağrı
    çözmüş olur. Bazı konular bilerek geride kalır: ekran gerçek hayattaki gibi karışık görünmeli."""
    _acik_devir(con, devir_id)
    simdi = _simdi(simdi)
    rnd = random.Random(tohum)
    bas = simdi - timedelta(days=gun)
    con.execute("UPDATE devir SET baslangic=? WHERE id=?", (bas.isoformat(timespec="minutes"), devir_id))
    saat = {"gunduz": (8, 16), "aksam": (16, 24), "gece": (0, 8)}
    uretilen = 0
    for k in con.execute("SELECT dk.kategori_id, dk.devralan_id, p.vardiya, c.temel_sure_dk, c.kaynak, c.ad "
                         "FROM devir_konu dk JOIN kategori c ON c.id=dk.kategori_id JOIN kisi p ON p.id=dk.devralan_id "
                         "WHERE dk.devir_id=?", (devir_id,)).fetchall():
        r = rnd.random()
        if r < 0.15:
            continue                                   # hiç başlamamış
        con.execute("UPDATE devir_konu SET izledi=1 WHERE devir_id=? AND kategori_id=?", (devir_id, k["kategori_id"]))
        adet = 0 if r < 0.35 else rnd.randint(1, 2)   # iki haftada "birlikte" aşaması gerçekçi; tek başına değil
        for _ in range(adet):
            g = rnd.uniform(1, gun - 1)
            acilis = (simdi - timedelta(days=g)).replace(hour=rnd.randrange(*saat[k["vardiya"]]), minute=rnd.randrange(60))
            sure = max(5, round(k["temel_sure_dk"] * rnd.uniform(1.1, 1.5)))
            con.execute(
                "INSERT INTO cagri(metin,acan_birim,aciliyet,kategori_id,onerilen_kategori_id,durum,atanan_kisi_id,"
                "cozen_kisi_id,acilis,kapanis,sure_dk,vardiya,kaynak) VALUES(?,?,?,?,?,'kapali',?,?,?,?,?,?,?)",
                (f"{k['ad']} (devir sürecinde)", "Depolama", 2, k["kategori_id"], k["kategori_id"], k["devralan_id"],
                 k["devralan_id"], acilis.isoformat(timespec="minutes"),
                 (acilis + timedelta(minutes=sure)).isoformat(timespec="minutes"), sure, k["vardiya"], k["kaynak"]))
            uretilen += 1
    con.commit()
    return dict(uretilen_cagri=uretilen, gun=gun)
