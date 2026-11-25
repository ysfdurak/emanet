"""Emanet'in "karar ve sonuç" katmanı: riski görmekten, karar almaya ve sonucu ölçmeye.

  izin_kontrol      İzin onaylanmadan önce: o tarihlerde hangi konular yedeksiz ya da tek kişiye kalır?
                    Daha uygun bir tarih var mı?
  plan_takibi       Kaydedilen eğitim planı tuttu mu? Öğrenen kişi o konuda çağrı çözmeye başladı mı,
                    kart yazıldı mı, risk puanı hedefe indi mi?
  plan_simule_et    Demo için: planın 30 gün uygulandığını varsayıp o dönemin çağrılarını üretir.
  devir_dosyasi     Biri ayrılırken: kişiye bağlı konular, çözüm notları, açık işleri, önerilen devralanlar.
  risk_seyri        Son aylarda risk nasıl değişti, hangi kararlar etkiledi?
  otomasyon_firsatlari  Riskli konulardan hangisinin notları reçeteye çevrilirse risk ne kadar düşer?
  dikkat            Genel bakışın "bugün neye bakmalıyım" listesi: her uyarı ilgili ekrana götürür.
"""
from __future__ import annotations

import random
import sqlite3
from collections import Counter
from datetime import date, datetime, timedelta

from . import katalog as K
from . import otomasyon, risk
from .dil import yuzde

VARDIYA_ADI = {"gunduz": "gündüz", "aksam": "akşam", "gece": "gece"}


def _tarih(s: str | date) -> date:
    return s if isinstance(s, date) else date.fromisoformat(str(s)[:10])


# ---------------------------------------------------------------- 2. izin kontrolü

def _izinliler(con, bas: date, bit: date, haric: int | None = None) -> dict[int, dict]:
    return {r["kisi_id"]: dict(r) for r in con.execute(
        "SELECT m.kisi_id, m.baslangic, m.bitis, m.tur, p.ad FROM musaitlik m JOIN kisi p ON p.id=m.kisi_id "
        "WHERE m.baslangic<=? AND m.bitis>=?", (bit.isoformat(), bas.isoformat())) if r["kisi_id"] != haric}


def _izin_etkisi(con, v: dict, kisi_id: int, bas: date, bit: date) -> list[dict]:
    """Kişinin yetkin olduğu her konu için, o tarihlerde geride kimin kalacağı."""
    diger_izin = _izinliler(con, bas, bit, haric=kisi_id)
    kisi = v["kisiler"][kisi_id]
    sonuc = []
    for k in v["kategoriler"]:
        s = v["sayim"][k["id"]]
        esik = risk.yetkin_esigi(sum(s.values()))
        yetkin = [p for p, n in s.items() if n >= esik]
        if kisi_id not in yetkin:
            continue
        kalan = [p for p in yetkin if p != kisi_id and p not in diger_izin]
        izinde = [p for p in yetkin if p != kisi_id and p in diger_izin]
        ayni_vardiya = [p for p in kalan if v["kisiler"][p]["vardiya"] == kisi["vardiya"]]
        durum = "yedeksiz" if not kalan else ("tek kişi" if len(kalan) == 1 else "güvenli")
        sonuc.append(dict(
            kategori_id=k["id"], ad=k["ad"], kritiklik=k["kritiklik"], kart_var=bool(k["kart_var"]),
            otomasyon_payi=k["oto_payi"], durum=durum, kalan=[v["kisiler"][p]["ad"] for p in kalan],
            izindeki_yedekler=[v["kisiler"][p]["ad"] for p in izinde],
            vardiya_bosalir=not ayni_vardiya and bool(kalan),
            gunluk_cagri=round(sum(s.values()) / risk.PENCERE_GUN, 2)))
    sira = {"yedeksiz": 0, "tek kişi": 1, "güvenli": 2}
    return sorted(sonuc, key=lambda x: (sira[x["durum"]], -x["kritiklik"]))


def _sorun_puani(etki: list[dict]) -> int:
    """Bir tarih aralığının ne kadar sorunlu olduğu: yedeksiz kritik konular en ağır."""
    return sum((10 if e["durum"] == "yedeksiz" else 3 if e["durum"] == "tek kişi" else 0) * e["kritiklik"]
               + (1 if e["vardiya_bosalir"] else 0) for e in etki)


def izin_kontrol(con: sqlite3.Connection, kisi_id: int, baslangic, bitis, simdi: datetime | None = None,
                 alternatif_gun: int = 60) -> dict:
    """İzin talebi onaylanmadan önceki kontrol. Karar yöneticinindir; araç yalnızca etkiyi gösterir."""
    bas, bit = _tarih(baslangic), _tarih(bitis)
    if bit < bas:
        raise ValueError("Bitiş, başlangıçtan önce olamaz")
    if (bit - bas).days > 60:
        raise ValueError("En fazla 60 günlük izin kontrol edilir")
    v = risk._veri(con, simdi)
    if kisi_id not in v["kisiler"]:
        raise ValueError("Kişi bulunamadı")
    etki = _izin_etkisi(con, v, kisi_id, bas, bit)
    puan = _sorun_puani(etki)
    yedeksiz_kritik = [e for e in etki if e["durum"] == "yedeksiz" and e["kritiklik"] >= 2]
    sure = (bit - bas).days
    # Aynı uzunlukta, önümüzdeki günlerde daha az sorunlu bir aralık var mı?
    alternatif = None
    if puan > 0:
        en_iyi = (puan, None)
        bugun = (simdi or datetime.now()).date()
        for kay in range(-14, alternatif_gun + 1):
            b = bas + timedelta(days=kay)
            if b < bugun or kay == 0:
                continue
            p = _sorun_puani(_izin_etkisi(con, v, kisi_id, b, b + timedelta(days=sure)))
            if p < en_iyi[0]:
                en_iyi = (p, b)
                if p == 0:
                    break
        if en_iyi[1]:
            b = en_iyi[1]
            alternatif = dict(baslangic=b.isoformat(), bitis=(b + timedelta(days=sure)).isoformat(),
                              sorun_puani=en_iyi[0], fark_gun=(b - bas).days)
    if yedeksiz_kritik:
        karar = "dikkat"
        mesaj = (f"Bu izin onaylanırsa {len(yedeksiz_kritik)} kritik konu yedeksiz kalır: "
                 + ", ".join(e["ad"] for e in yedeksiz_kritik) + ".")
        if not alternatif or alternatif["sorun_puani"] >= puan:
            hic = [e["ad"] for e in yedeksiz_kritik if not e["izindeki_yedekler"]]
            if hic:
                mesaj += (f" Tarihi kaydırmak çözmez: {', '.join(hic)} konusunun hiç yedeği yok. "
                          "İzin onaylanabilir ama önce yazılı çözüm ve bir yedek planlanmalı.")
    elif any(e["durum"] != "güvenli" for e in etki):
        karar = "uyari"
        mesaj = "Bazı konular tek kişiye kalır; o kişinin de aynı dönemde müsait olduğundan emin olun."
    else:
        karar = "uygun"
        mesaj = "Bu tarihlerde kişinin bildiği bütün konuların yedeği var."
    p = v["kisiler"][kisi_id]
    return dict(kisi=dict(id=kisi_id, ad=p["ad"], birim=p["birim"], vardiya=p["vardiya"]),
                baslangic=bas.isoformat(), bitis=bit.isoformat(), gun=sure + 1, karar=karar, mesaj=mesaj,
                sorun_puani=puan, konular=etki,
                cakisan_izinler=[dict(ad=i["ad"], baslangic=i["baslangic"], bitis=i["bitis"], tur=i["tur"])
                                 for i in _izinliler(con, bas, bit, haric=kisi_id).values()],
                alternatif=alternatif)


def izin_kaydet(con: sqlite3.Connection, kisi_id: int, baslangic, bitis, tur: str = "izin") -> dict:
    bas, bit = _tarih(baslangic), _tarih(bitis)
    if bit < bas:
        raise ValueError("Bitiş, başlangıçtan önce olamaz")
    if not con.execute("SELECT 1 FROM kisi WHERE id=?", (kisi_id,)).fetchone():
        raise ValueError("Kişi bulunamadı")
    con.execute("INSERT INTO musaitlik(kisi_id,baslangic,bitis,tur) VALUES(?,?,?,?)",
                (kisi_id, bas.isoformat(), bit.isoformat(), tur))
    con.commit()
    return dict(kaydedildi=True, kisi_id=kisi_id, baslangic=bas.isoformat(), bitis=bit.isoformat())


# ---------------------------------------------------------------- 3. eğitim planı takibi

def plan_takibi(con: sqlite3.Connection, simdi: datetime | None = None) -> dict:
    """Kayıtlı planın her satırı için: yapıldı mı, işe yaradı mı?

    Eğitim / tazeleme : öğrenen kişi plan tarihinden sonra o konuda kaç çağrı çözdü?
                        3 ve üzeri → yetkin oldu · 1-2 → başladı · 0 → henüz çözmedi
    Kart              : plan tarihinden sonra o konuya kart ya da reçete yazıldı mı?
    Planın tutma oranı = tamamlanan satırlar / bütün satırlar
    """
    satirlar = [dict(r) for r in con.execute(
        "SELECT e.*, k.ad AS kategori, k.kod, k.temel_sure_dk, a.ad AS ogreten, b.ad AS ogrenen "
        "FROM egitim_plani e JOIN kategori k ON k.id=e.kategori_id LEFT JOIN kisi a ON a.id=e.ogreten_id "
        "LEFT JOIN kisi b ON b.id=e.ogrenen_id ORDER BY e.id")]
    if not satirlar:
        return dict(var=False)
    plan_tarihi = min(s["olusturma"] for s in satirlar)
    harita = {r["kategori_id"]: r for r in risk.risk_haritasi(con, simdi)}
    tamam = 0
    for s in satirlar:
        if s["tur"] in ("egitim", "tazeleme", "gecis"):
            r = con.execute("SELECT COUNT(*) n, AVG(sure_dk) ort FROM cagri WHERE cozen_kisi_id=? AND kategori_id=? "
                            "AND durum='kapali' AND acilis>=?", (s["ogrenen_id"], s["kategori_id"], s["olusturma"])).fetchone()
            s["cozulen"], s["ort_sure"] = r["n"], round(r["ort"]) if r["ort"] else None
            s["sonuc"] = "yetkin oldu" if r["n"] >= risk.YETKIN_ESIGI else ("başladı" if r["n"] else "henüz çözmedi")
            s["tamam"] = r["n"] >= risk.YETKIN_ESIGI
        else:
            yazildi = con.execute(
                "SELECT (EXISTS(SELECT 1 FROM cozum_karti WHERE kategori_id=? AND olusturma>=?) "
                " OR EXISTS(SELECT 1 FROM recete WHERE kategori_kod=? AND olusturma>=?) "
                " OR (SELECT talimat_var FROM kategori WHERE id=?))",
                (s["kategori_id"], s["olusturma"], s["kod"], s["olusturma"], s["kategori_id"])).fetchone()[0]
            s["sonuc"], s["tamam"] = ("yazıldı", True) if yazildi else ("yazılmadı", False)
        s["puan_simdi"] = harita[s["kategori_id"]]["puan"] if s["kategori_id"] in harita else None  # konu geçişle kapandıysa
        tamam += s["tamam"]
    konular = {}
    for s in satirlar:
        konular.setdefault(s["kategori_id"], dict(kategori=s["kategori"], once=s["puan_once"], hedef=s["puan_hedef"],
                                                  simdi=s["puan_simdi"]))
    for k in konular.values():
        k["hedefe_ulasti"] = k["simdi"] is not None and k["hedef"] is not None and k["simdi"] <= k["hedef"] + 3
    return dict(var=True, plan_tarihi=plan_tarihi, satirlar=satirlar, tutma_orani=round(tamam / len(satirlar), 2),
                tamamlanan=tamam, toplam=len(satirlar), konular=list(konular.values()),
                simule=con.execute("SELECT deger FROM meta WHERE anahtar='plan_simule'").fetchone() is not None)


def _usta_metni(kod: str, rnd: random.Random) -> str | None:
    k = next((x for x in K.USTA_KATEGORILERI if x["kod"] == kod), None)
    if not k:
        return None
    s = rnd.choice(rnd.choice(k["alt"])["sablonlar"])
    return s.format(yer=rnd.choice(K.YERLER), no=rnd.randint(1, 48), yazilim="Power BI", pc="PC-1234",
                    rol="sayım onaylayıcı")


def plan_simule_et(con: sqlite3.Connection, gun: int = 30, tohum: int = 7) -> dict:
    """DEMO: kayıtlı planın 'gun' gün önce kaydedildiğini ve uygulandığını varsayar.

    Planın tarihi geriye alınır ve o dönem için çağrılar üretilir: öğrenenlerin bir kısmı (%75)
    konuyu çözmeye başlar, kart görevlerinin çoğu (%85) yazılır. Bir kısmının tutmaması bilinçlidir:
    takip ekranı gerçek hayattaki gibi karışık bir tablo göstermelidir.
    """
    if con.execute("SELECT 1 FROM meta WHERE anahtar='plan_simule'").fetchone():
        raise ValueError("Plan zaten simüle edildi. Yeni bir plan kaydedin ya da veriyi sıfırlayın.")
    satirlar = [dict(r) for r in con.execute(
        "SELECT e.*, k.kod, k.kaynak, k.temel_sure_dk, k.ad AS kategori FROM egitim_plani e "
        "JOIN kategori k ON k.id=e.kategori_id ORDER BY e.id")]
    if not satirlar:
        raise ValueError("Önce bir planı kaydedin")
    rnd = random.Random(tohum)
    simdi = datetime.now()
    plan_an = simdi - timedelta(days=gun + 2)
    con.execute("UPDATE egitim_plani SET olusturma=?", (plan_an.isoformat(timespec="minutes"),))
    kisi_vardiya = {r["id"]: r["vardiya"] for r in con.execute("SELECT id, vardiya FROM kisi")}
    saat = {"gunduz": (8, 16), "aksam": (16, 24), "gece": (0, 8)}
    uretilen, yazilan = 0, 0
    for s in satirlar:
        if s["tur"] in ("egitim", "tazeleme", "gecis"):
            basari = rnd.random() < 0.75
            adet = rnd.randint(3, 5) if basari else rnd.randint(0, 1)
            for _ in range(adet):
                g = rnd.randint(1, gun)
                vd = kisi_vardiya[s["ogrenen_id"]]
                acilis = (simdi - timedelta(days=g)).replace(hour=rnd.randrange(*saat[vd]), minute=rnd.randrange(60))
                sure = max(5, round(s["temel_sure_dk"] * rnd.uniform(1.1, 1.6)))   # yeni öğrenen biraz yavaş
                metin = _usta_metni(s["kod"], rnd) if s["kaynak"] == "usta" else s["kategori"]
                con.execute(
                    "INSERT INTO cagri(metin,acan_birim,aciliyet,kategori_id,onerilen_kategori_id,durum,atanan_kisi_id,"
                    "cozen_kisi_id,acilis,kapanis,sure_dk,vardiya,kaynak) VALUES(?,?,?,?,?,'kapali',?,?,?,?,?,?,?)",
                    (metin, "Döküm" if s["kaynak"] != "usta" else rnd.choice(K.ACAN_BIRIMLER), 2, s["kategori_id"],
                     s["kategori_id"], s["ogrenen_id"], s["ogrenen_id"], acilis.isoformat(timespec="minutes"),
                     (acilis + timedelta(minutes=sure)).isoformat(timespec="minutes"), sure, vd, s["kaynak"]))
                uretilen += 1
        elif rnd.random() < 0.85:
            an = (plan_an + timedelta(days=rnd.randint(2, gun))).isoformat(timespec="minutes")
            if s["kaynak"] == "usta":
                notu = con.execute("SELECT cozum_notu FROM cagri WHERE kategori_id=? AND cozum_notu IS NOT NULL "
                                   "GROUP BY cozum_notu ORDER BY COUNT(*) DESC LIMIT 1", (s["kategori_id"],)).fetchone()
                con.execute("INSERT INTO cozum_karti(kategori_id,baslik,adimlar,kok_neden,yazan_kisi_id,olusturma) "
                            "VALUES(?,?,?,?,?,?)", (s["kategori_id"], f"{s['kategori']}: eğitim planıyla yazıldı",
                                                    notu[0] if notu else "Adımlar uzmanla birlikte yazıldı",
                                                    None, s["ogreten_id"], an))
            else:
                con.execute("UPDATE kategori SET talimat_var=1 WHERE id=?", (s["kategori_id"],))
            yazilan += 1
    con.execute("INSERT OR REPLACE INTO meta(anahtar,deger) VALUES('plan_simule',?)", (simdi.isoformat(timespec="minutes"),))
    con.commit()
    return dict(gun=gun, uretilen_cagri=uretilen, yazilan_kart=yazilan)


# ---------------------------------------------------------------- 5. devir dosyası

def devir_dosyasi(con: sqlite3.Connection, kisi_id: int, simdi: datetime | None = None) -> dict:
    """Bir kişi ayrılırken (ya da uzun izne çıkarken) devredilmesi gerekenler."""
    v = risk._veri(con, simdi)
    if kisi_id not in v["kisiler"]:
        raise ValueError("Kişi bulunamadı")
    p = v["kisiler"][kisi_id]
    yg = risk.ya_giderse(con, kisi_id, 30, simdi=simdi)
    etkilenen = {e["kategori_id"]: e for e in yg["etkilenen"]}
    konular = []
    for k in v["kategoriler"]:
        s = v["sayim"][k["id"]]
        n = s.get(kisi_id, 0)
        if not n:
            continue
        toplam = sum(s.values())
        e = etkilenen[k["id"]]
        notlar = Counter(r[0] for r in con.execute(
            "SELECT cozum_notu FROM cagri WHERE cozen_kisi_id=? AND kategori_id=? AND cozum_notu IS NOT NULL",
            (kisi_id, k["id"])))
        cozdugu = con.execute("SELECT COUNT(*) FROM cagri WHERE cozen_kisi_id=? AND kategori_id=? AND durum='kapali'",
                              (kisi_id, k["id"])).fetchone()[0]
        # Devralan önerisi: aynı birimden, bu konuyu en çok çözmüş diğer kişi (yoksa pratiği kalmamış eski yedek)
        # Devralan önerisi, sırayla: konuda yetkin başka biri → pratiği kalmamış eski yedek →
        # kâğıtta yetkin görünen biri → konuyu birkaç kez çözmüş biri → birimden biri (sıfırdan eğitim)
        esik = risk.yetkin_esigi(toplam)
        digerleri = sorted(((q, m) for q, m in s.items() if q != kisi_id), key=lambda x: -x[1])
        yetkin_diger = [(q, m) for q, m in digerleri if m >= esik]
        eski = risk.pratigi_kalmayanlar(v, k["id"], haric_kisi=kisi_id)
        beyanli = sorted((q for q in v["beyan"][k["id"]] if q != kisi_id and q in v["kisiler"]),
                         key=lambda q: -s.get(q, 0))
        if yetkin_diger:
            devralan, dneden = v["kisiler"][yetkin_diger[0][0]]["ad"], f"son 90 günde {yetkin_diger[0][1]} çağrı çözdü"
        elif eski:
            devralan, dneden = eski[0]["ad"], f"eskiden çözüyordu, tazeleme yeter ({eski[0]['ay_once']} ay önce)"
        elif beyanli:
            q = beyanli[0]
            devralan, dneden = v["kisiler"][q]["ad"], (f"kâğıtta biliyor görünüyor, son 90 günde {s.get(q, 0)} çağrı "
                                                        "çözdü; uzmanla birlikte çalışarak pratiğe dökmeli")
        elif digerleri:
            devralan, dneden = v["kisiler"][digerleri[0][0]]["ad"], f"yalnızca {digerleri[0][1]} çağrı çözdü"
        else:
            aday = next((q for q in v["kisiler"].values() if q["birim_id"] == k["birim_id"] and q["id"] != kisi_id), None)
            devralan, dneden = (aday["ad"] if aday else None), "konuyu bilen başka kimse yok; sıfırdan eğitim gerekir"
        kritik = e["yedeksiz"] or (n / toplam >= 0.6)
        adimlar = []
        if not k["kart_var"]:
            adimlar.append(f"Çözüm yollarını karta yazsın ({risk.KART_YAZMA_SAATI} saat)"
                           + (f"; elinde {len(notlar)} farklı çözüm notu var" if notlar else "; hiç çözüm notu yok"))
        if e["yedeksiz"] or n / toplam >= 0.6:
            adimlar.append(f"{devralan or 'Bir yedek'} ile birlikte çalışarak devretsin "
                           f"(yaklaşık {k['ogrenme_saati']} saat)")
        konular.append(dict(kategori_id=k["id"], ad=k["ad"], kritiklik=k["kritiklik"], pay=round(n / toplam, 2),
                            son_90_gun=n, toplam_cozdugu=cozdugu, kalan_yetkinler=e["kalan_yetkinler"],
                            yedeksiz=e["yedeksiz"], kart_var=bool(k["kart_var"]),
                            not_orani=round(sum(notlar.values()) / max(1, cozdugu), 2),
                            cozum_yollari=[dict(adimlar=nt.split("\n"), kez=c) for nt, c in notlar.most_common(3)],
                            devralan=devralan, devralan_neden=dneden, kritik=kritik, adimlar=adimlar))
    konular.sort(key=lambda x: (not x["kritik"], -x["kritiklik"], -x["pay"]))
    acik = [dict(r) for r in con.execute(
        "SELECT c.id, c.metin, c.acilis, k.ad AS kategori FROM cagri c JOIN kategori k ON k.id=c.kategori_id "
        "WHERE c.atanan_kisi_id=? AND c.durum='acik' ORDER BY c.acilis", (kisi_id,))]
    kartlar = [dict(r) for r in con.execute(
        "SELECT ck.baslik, k.ad AS kategori FROM cozum_karti ck JOIN kategori k ON k.id=ck.kategori_id "
        "WHERE ck.yazan_kisi_id=?", (kisi_id,))]
    otomasyonlar = yg["otomasyonlar"]
    kritik = [k for k in konular if k["kritik"]]
    saat = sum((risk.KART_YAZMA_SAATI if not k["kart_var"] else 0) + (k["kritik"] and next(
        x["ogrenme_saati"] for x in v["kategoriler"] if x["id"] == k["kategori_id"]) or 0) for k in kritik)
    d = dict(kisi=dict(id=kisi_id, ad=p["ad"], birim=p["birim"], rol=p["rol"], vardiya=p["vardiya"]),
             tarih=(simdi or datetime.now()).date().isoformat(), konular=konular, acik_isler=acik, kartlar=kartlar,
             otomasyonlar=otomasyonlar,
             ozet=dict(konu=len(konular), kritik=len(kritik), acik_is=len(acik), tahmini_devir_saati=saat,
                       yedeksiz=[k["ad"] for k in konular if k["yedeksiz"]]))
    d["markdown"] = _devir_md(d)
    return d


def _devir_md(d: dict) -> str:
    k, o = d["kisi"], d["ozet"]
    satir = [f"# Devir dosyası: {k['ad']}", "",
             f"{k['birim']} · {k['rol']} · {VARDIYA_ADI[k['vardiya']]} vardiyası · hazırlanma: {d['tarih']}", "",
             f"**Özet:** {o['konu']} konu, {o['kritik']} tanesi kritik devir. Açık iş: {o['acik_is']}. "
             f"Kritik devirlerin tahmini süresi: {o['tahmini_devir_saati']} saat.", ""]
    if o["yedeksiz"]:
        satir += [f"**Yedeksiz kalacak konular:** {', '.join(o['yedeksiz'])}", ""]
    satir += ["## Konular", ""]
    for x in d["konular"]:
        satir += [f"### {x['ad']}{' (kritik)' if x['kritik'] else ''}",
                  f"- Son 90 günde çağrıların {yuzde(x['pay'], 'ini')} çözdü ({x['son_90_gun']} çağrı)",
                  f"- Geride bilen: {', '.join(x['kalan_yetkinler']) or 'kimse'}",
                  f"- Yazılı çözüm: {'var' if x['kart_var'] else 'yok'} · çözümlerinin {yuzde(x['not_orani'], 'ine')} not düşmüş",
                  f"- Önerilen devralan: {x['devralan'] or '-'} ({x['devralan_neden']})"]
        for a in x["adimlar"]:
            satir.append(f"- [ ] {a}")
        for y in x["cozum_yollari"]:
            satir.append(f"- Çözüm yolu ({y['kez']} kez): " + " → ".join(y["adimlar"]))
        satir.append("")
    satir += ["## Açık işler", ""] + ([f"- #{a['id']} {a['metin']} ({a['kategori']})" for a in d["acik_isler"]] or ["- Yok"])
    satir += ["", "## Yazdığı çözüm kartları", ""] + ([f"- {c['baslik']} ({c['kategori']})" for c in d["kartlar"]] or ["- Yok"])
    satir += ["", "## Bakımını yaptığı otomasyonlar", ""] + (
        [f"- [ ] {o['ad']}: betikleri, servis hesabını ve doğrulama adımlarını yeni sahibine devret" for o in d["otomasyonlar"]]
        or ["- Yok"])
    return "\n".join(satir) + "\n"


# ---------------------------------------------------------------- 6. risk seyri

def risk_seyri(con: sqlite3.Connection, adim_gun: int = 14, simdi: datetime | None = None) -> dict:
    """Risk haritasının zaman içindeki seyri. Her nokta, o tarihten geriye 90 günlük pencereyle hesaplanır.
    Yalnızca penceresi verinin tamamen içinde kalan tarihler gösterilir (yoksa ilk noktalar eksik
    veriyle yapay olarak yüksek çıkar). En son nokta bugündür."""
    simdi = simdi or datetime.now()
    ilk = con.execute("SELECT MIN(acilis) FROM cagri").fetchone()[0]
    baslangic = datetime.fromisoformat(ilk) + timedelta(days=risk.PENCERE_GUN)
    tarihler = []
    t = simdi
    while t >= baslangic:
        tarihler.append(t)
        t -= timedelta(days=adim_gun)
    tarihler.reverse()
    noktalar = []
    for t in tarihler:
        h = risk.risk_haritasi(con, t)
        noktalar.append(dict(tarih=t.date().isoformat(), **risk.ozet(h),
                             konular={r["kategori_id"]: r["puan"] for r in h}))
    son = risk.risk_haritasi(con, simdi)
    ilk_puan = noktalar[0]["konular"] if noktalar else {}
    # İzlenen konular: bugünün en riskli 4'ü ve dönem başına göre en çok değişen 2'si
    degisim = sorted(son, key=lambda r: -abs(r["puan"] - ilk_puan.get(r["kategori_id"], r["puan"])))
    secilen = list(dict.fromkeys([r["kategori_id"] for r in son[:4]] + [r["kategori_id"] for r in degisim[:2]]))
    adlar = {r["kategori_id"]: r["ad"] for r in son}
    izlenen = [dict(kategori_id=i, ad=adlar[i], seri=[n["konular"].get(i) for n in noktalar]) for i in secilen]
    bas = noktalar[0]["tarih"] if noktalar else simdi.date().isoformat()
    olaylar = [dict(tarih=r[0][:10], metin=r[1]) for r in con.execute(
        "SELECT MIN(olusturma), 'Eğitim planı kaydedildi (' || COUNT(*) || ' adım)' FROM egitim_plani HAVING COUNT(*)>0 "
        "UNION ALL SELECT MIN(olusturma), 'Otomatik çözümler devreye girdi' FROM recete WHERE tur!='taslak' "
        "UNION ALL SELECT olusturma, 'Taslak otomatik çözüm: ' || ad FROM recete WHERE tur='taslak' "
        "UNION ALL SELECT olusturma, 'Çözüm kartı: ' || baslik FROM cozum_karti WHERE olusturma>=?", (bas,)) if r[0]]
    for n in noktalar:
        n.pop("konular")
    return dict(noktalar=noktalar, izlenen=izlenen, adim_gun=adim_gun,
                olaylar=sorted((o for o in olaylar if o["tarih"] >= bas), key=lambda o: o["tarih"]))


# ---------------------------------------------------------------- 1. otomasyon fırsatları

def otomasyon_firsatlari(con: sqlite3.Connection, simdi: datetime | None = None) -> list[dict]:
    """Riskli (puanı 35 ve üzeri) ve yazılı çözümü olmayan konulardan, sık tekrar eden çözüm notu olanlar:
    bu not reçeteye (taslak) çevrilirse yazısızlık kalkar; puan ne olur?"""
    v = risk._veri(con, simdi)
    harita = {r["kategori_id"]: r for r in risk.risk_haritasi(con, _v=v)}
    adaylar = otomasyon.recete_adaylari(con, esik=5)
    sonuc, gorulen = [], set()
    for a in adaylar:
        h = harita.get(a["kategori_id"])
        if not h or h["puan"] < risk.SARI or not h["kartsiz"] or a["kategori_id"] in gorulen:
            continue
        gorulen.add(a["kategori_id"])
        k = next(x for x in v["kategoriler"] if x["id"] == a["kategori_id"])
        sonra = risk.puan_hesapla(v["sayim"][k["id"]], k["kritiklik"], True, oto_payi=k["oto_payi"])["puan"]
        sonuc.append(dict(a, puan_once=h["puan"], puan_sonra=sonra, seviye_once=h["seviye"],
                          seviye_sonra=risk.seviye(sonra), uzman=h["en_cok_cozen"]["ad"] if h["en_cok_cozen"] else None))
    return sorted(sonuc, key=lambda x: -(x["puan_once"] - x["puan_sonra"]))


# ---------------------------------------------------------------- dikkat listesi

def sayi_tr(x: float) -> str:
    return f"{x:g}".replace(".", ",")


def dikkat(con: sqlite3.Connection, simdi: datetime | None = None) -> list[dict]:
    """Yöneticinin bugün bakması gerekenler, önem sırasıyla. Her madde: seviye (kirmizi|sari|mavi),
    metin, gidilecek sayfa ve sayfaya verilecek değer."""
    from . import degisim
    simdi = simdi or datetime.now()
    liste = []
    for r in otomasyon.receteler(con):
        sg = r.get("saglik")
        if sg and sg["durum"] == "askida":
            liste.append(dict(seviye="kirmizi", metin=f"Otomasyon askıda: {r['ad']}. Çağrılar insana gidiyor.", sayfa="otomasyon"))
        elif sg and sg["durum"] == "dususte":
            liste.append(dict(seviye="sari", metin=f"Otomasyonun başarısı düşüyor: {r['ad']} ({sg['metin']})", sayfa="otomasyon"))
        elif sg and sg["durum"] == "eski_sistem":
            liste.append(dict(seviye="sari", metin=f"Otomasyon eski sisteme bağlı kaldı: {r['ad']}. Yeni sisteme uyarlanmalı.",
                              sayfa="degisim"))
        if r["tur"] != "taslak" and not r.get("sahip"):
            liste.append(dict(seviye="sari", metin=f"Otomasyonun sahibi yok: {r['ad']}. Bozulursa düzeltecek kişi belli değil.",
                              sayfa="otomasyon"))
    for g in degisim.gecisler(con, simdi):
        if g["yeni_konu"] and g["yeni_konu"]["erken_uyari"]:
            en = g["yeni_konu"]["en_cok"]
            liste.append(dict(seviye="kirmizi", metin=f"Yeni sistemde bilgi tek kişide toplanıyor: {g['yeni_ad']}, "
                                                      f"çağrıların {yuzde(en['pay'], 'ini')} {en['ad']} çözüyor.", sayfa="degisim"))
        elif g["gun"] < 0:
            liste.append(dict(seviye="mavi", metin=f"{-g['gun']} gün sonra sistem geçişi: {g['yeni_ad']}. Geçiş adaylarını hazırlayın.",
                              sayfa="degisim"))
    harita = risk.risk_haritasi(con, simdi)
    # Eğitim süreleri kullanıcıdan gelir; riskli bir konunun süresi girilmediyse plan tahminle hesaplar
    onaysiz = {r["id"] for r in con.execute("SELECT id FROM kategori WHERE sure_onay=0 AND emeklilik IS NULL")}
    riskli_suresiz = [r["ad"] for r in harita if r["seviye"] in ("kirmizi", "sari") and r["kategori_id"] in onaysiz]
    if riskli_suresiz:
        liste.append(dict(seviye="mavi", metin=f"{len(riskli_suresiz)} riskli konunun eğitim süresi girilmedi "
                          f"({', '.join(riskli_suresiz[:3])}{'…' if len(riskli_suresiz) > 3 else ''}); "
                          "plan bu konularda tahmini süre kullanıyor.", sayfa="plan", veri="sureler"))
    for r in [r for r in harita if r["seviye"] == "kirmizi" and r["yetkin_sayisi"] <= 1
              and r["en_cok_cozen"] and not r["yeni_konu"]][:2]:
        liste.append(dict(seviye="kirmizi", metin=f"{r['ad']}: çağrıların {yuzde(r['yogunlasma'], 'ini')} "
                                                  f"{r['en_cok_cozen']['ad']} çözüyor, yedeği yok.",
                          sayfa="giderse", veri=r["en_cok_cozen"]["ad"]))
    from .cagri_formu import tekrarlayan_cihazlar
    tekrar = tekrarlayan_cihazlar(con, simdi)
    if tekrar:   # tek satır: cihazlar ayrı ayrı listeyi doldurmasın
        ilk = tekrar[0]
        liste.append(dict(seviye="sari", metin=(f"{ilk['no']}{' (' + ilk['yer'] + ')' if ilk['yer'] else ''} son 30 günde "
                          f"{ilk['cagri']} kez arızalandı" + (f"; {len(tekrar) - 1} cihaz daha tekrar tekrar arızalanıyor ("
                          + ", ".join(f"{c['no']} {c['cagri']}" for c in tekrar[1:4]) + ")" if len(tekrar) > 1 else "")
                          + ". Tekrar onarmak yerine değişim ya da bakım konuşulmalı."), sayfa="cihaz", veri=ilk["no"]))
    # Tesis kapsaması: yerinde donanım ekibi hangi vardiyalarda yok? (cihaz arızası o saatlerde uzaktan kalır)
    eksik = []
    for l in con.execute("SELECT id, ad FROM lokasyon ORDER BY id"):
        var = {r[0] for r in con.execute("SELECT DISTINCT p.vardiya FROM kisi p JOIN kisi_alan a ON a.kisi_id=p.id "
                                         "WHERE p.lokasyon_id=? AND a.alan='donanim' AND p.cikis IS NULL", (l["id"],))}
        yok = [v for v in ("gunduz", "aksam", "gece") if v not in var]
        if con.execute("SELECT 1 FROM cagri WHERE lokasyon_id=? LIMIT 1", (l["id"],)).fetchone() and yok:
            eksik.append(f"{l['ad'].split()[0]} ({', '.join({'gunduz': 'gündüz', 'aksam': 'akşam', 'gece': 'gece'}[v] for v in yok)})")
    if eksik:
        liste.append(dict(seviye="mavi", metin="Yerinde donanım ekibi olmayan vardiyalar: " + "; ".join(eksik)
                          + ". Bu saatlerde cihaz ve ağ arızaları uzaktan yönlendiriliyor.", sayfa="risk"))
    from .yonlendirme import kural_onerileri, yonlendirme_olculeri
    yo = yonlendirme_olculeri(con, (simdi - timedelta(days=30)).isoformat(timespec="minutes"))
    if yo["mudurde"] and yo["koordinator"]:
        liste.append(dict(seviye="kirmizi", metin=f"{len(yo['mudurde'])} çağrı ekipler arasında gidip geldi ya da ekibi "
                          f"bilinmiyor; {yo['koordinator']['ad']} ({yo['koordinator']['rol']}) kararını bekliyor.",
                          sayfa="kuyruk"))
    for o in kural_onerileri(con, simdi)[:1]:
        liste.append(dict(seviye="mavi", metin=f"Kural önerisi: “{o['belirti']}” diyen çağrılar son 90 günde {o['aktarilan']} kez "
                          + (f"(aynı belirtili {o['toplam']} çağrıdan) " if o["toplam"] else "")
                          + f"{o['su_an_ad']} ekibinden {o['onerilen_ad']} ekibine aktarıldı. Kural değişsin mi?", sayfa="olcum"))
    from .olcum import vardiya_boslugu
    vb = vardiya_boslugu(con, simdi)
    if vb:
        liste.append(dict(seviye="sari", metin=f"Son 30 günde {vb['ad']} çağrıları toplam {sayi_tr(vb['bekleme_saat'])} saat "
                          f"bilen birinin vardiyasını bekledi (çağrı başına {sayi_tr(round(vb['bekleme_cagri_basi_dk'] / 60, 1))} saat). "
                          "Başka vardiyada bu işi bilen yetiştirin.", sayfa="plan"))
    tk = risk.tek_kisiye_kalanlar(con, 7, simdi)
    yedeksiz = [k for k in tk["konular"] if k["durum"] == "yedeksiz"]
    tek = [k for k in tk["konular"] if k["durum"] == "tek kişi" and k["kritiklik"] == 3]
    if yedeksiz:
        liste.append(dict(seviye="kirmizi", metin="Bu hafta izinler yüzünden yedeksiz: " + ", ".join(k["ad"] for k in yedeksiz[:3])
                          + ("…" if len(yedeksiz) > 3 else ""), sayfa="izin"))
    if tek:
        liste.append(dict(seviye="sari", metin="Bu hafta izinler yüzünden tek kişiye kalan kritik konu: "
                          + ", ".join(f"{k['ad']} ({', '.join(k['kalan_yetkinler'])})" for k in tek[:3]), sayfa="izin"))
    for t in risk.veri_tazeligi(con, simdi):
        if t["eski"]:
            liste.append(dict(seviye="sari", metin=f"{t['kaynak']} {t['gun']} gündür güncellenmedi; bu kaynağın konuları "
                                                    "eksik veriyle hesaplanıyor, risk yapay olarak yüksek görünebilir.", sayfa="risk"))
    bekleyen = con.execute("SELECT COUNT(*) FROM mesaj WHERE cevap IS NULL AND tur='onay'").fetchone()[0]
    if bekleyen:
        liste.append(dict(seviye="mavi", metin=f"{bekleyen} otomasyon yönetici onayı bekliyor.", sayfa="otomasyon"))
    plan = plan_takibi(con, simdi)
    tutmayan = [x for x in plan.get("satirlar", []) if x["sonuc"] in ("henüz çözmedi", "yazılmadı")]
    yas = (simdi - datetime.fromisoformat(plan["plan_tarihi"])).days if plan.get("var") else 0
    if tutmayan and yas >= 14:
        liste.append(dict(seviye="sari", metin=f"Eğitim planında {len(tutmayan)} adım ilerlemiyor.", sayfa="plan"))
    for p in degisim.yeni_personel(con, simdi):
        if p["kisi"]["gun"] is not None and p["kisi"]["gun"] >= 30 and p["toplam_cozum"] == 0:
            liste.append(dict(seviye="sari", metin=f"{p['kisi']['ad']} {p['kisi']['gun']} gündür ekipte ama hiç çağrı çözmedi.",
                              sayfa="degisim"))
    from . import devir
    for dv in devir.acik_devirler(con):
        d = devir.durum(con, dv["id"], simdi)
        acik_konu = d["ozet"]["konu"] - d["ozet"]["tamam"]
        if any(u["seviye"] == "kirmizi" for u in d["uyarilar"]):
            liste.append(dict(seviye="kirmizi", metin=f"{d['kisi']['ad']} devri çıkış gününe yetişmiyor ({d['gun_kaldi']} gün kaldı).",
                              sayfa="devir", veri=str(d["id"])))
        elif acik_konu or d["ozet"]["madde_tamam"] < d["ozet"]["madde"]:
            liste.append(dict(seviye="sari", metin=f"{d['kisi']['ad']} devri sürüyor: {d['gun_kaldi']} gün kaldı, "
                              f"{acik_konu} konu ve {d['ozet']['madde'] - d['ozet']['madde_tamam']} madde açık.",
                              sayfa="devir", veri=str(d["id"])))
    sira = {"kirmizi": 0, "sari": 1, "mavi": 2}
    return sorted(liste, key=lambda x: sira[x["seviye"]])
