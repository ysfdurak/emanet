"""İki aşamalı çağrı formu: konuya özel sorular, kendin dene adımları ve öncelik hesabı.

1. aşama: kişi sorunu kendi cümlesiyle yazar, model konuyu tahmin eder (usta.kategori_oner).
2. aşama: konuya göre 2-3 soru açılır. Cevaplar çağrıya ek bilgi olarak yazılır; metne eklenmez,
   çünkü metin modelin öğrenme verisidir ve form sorularıyla kirlenmemeli.

Öncelik kişiye sorulmaz ("aciliyet: yüksek" herkesin seçtiği şeydir); etki ve kapsamdan hesaplanır.
Bu, BT hizmet yönetimindeki etki x aciliyet matrisinin sahaya uyarlanmış hâlidir.

Sorular ve "kendin dene" adımları alan uzmanı gözüyle yazıldı. Çözüm notlarından türetilmedi:
notlar uzmanın uzmana yazdığı adımlardır ("entegrasyon günlüğünde belgeyi bul"), çağrıyı açan
kişinin yapabileceği şeyler değildir. Kendin dene yalnız kullanıcının güvenle yapabileceği adımları içerir.
"""
from __future__ import annotations

import json
import re
import sqlite3
from datetime import datetime, timedelta

from . import katalog as K
from .otomasyon import kucult

# Soru türleri: metin (kısa serbest yazı) | secim (seçeneklerden biri)
SORULAR: dict[str, list[dict]] = {
    "EL_TERMINALI": [
        dict(kod="cihaz", soru="Cihaz numarası", tur="metin", ipucu="Arkasındaki etiket, örn. EL-014", zorunlu=True,
             neden="Aynı cihaz sık arızalanıyorsa değişim gerekir; bu numarayla izlenir."),
        dict(kod="belirti", soru="Ne oluyor?", tur="secim",
             secenekler=["Açılmıyor", "Şarj olmuyor", "Ekran kırık ya da dokunmatik çalışmıyor",
                         "Ekran donuyor ya da uygulama kapanıyor", "Oturum açılmıyor", "Ağa bağlanmıyor"],
             neden="Cevaba göre doğru ekibe gider: açılmıyor, şarj, kırık → donanım; donma, oturum → WMS; ağ → ağ ekibi."),
        dict(kod="baska", soru="Başka bir terminal denedin mi?", tur="secim",
             secenekler=["O da çalışmıyor", "O çalışıyor", "Deneyemedim"],
             neden="İkisi de çalışmıyorsa sorun cihazda değil ağda ya da sistemdedir."),
    ],
    "ETIKET_YAZICI": [
        dict(kod="cihaz", soru="Yazıcı numarası", tur="metin", ipucu="Yazıcının üstündeki etiket, örn. YZ-07", zorunlu=True,
             neden="Aynı yazıcı sık arızalanıyorsa değişim gerekir; bu numarayla izlenir."),
        dict(kod="model", soru="Yazıcı modeli", tur="secim", secenekler=K.YAZICI_MODELLERI + ["Bilmiyorum"],
             neden="Ribon, sürücü ve yedek parça modele göre değişir. Numara envanterde kayıtlıysa kendiliğinden gelir."),
        dict(kod="belirti", soru="Ne oluyor?", tur="secim",
             secenekler=["Hiç basmıyor ya da çevrimdışı", "Boş ya da soluk basıyor", "Kayık ya da yanlış basıyor", "Kâğıt sıkıştı"]),
        dict(kod="etiket", soru="Hangi baskı?", tur="secim", secenekler=["Koli etiketi", "Raf etiketi", "İrsaliye ya da A4"]),
    ],
    "SIFRE_HESAP": [
        dict(kod="sistem", soru="Hangi sistem?", tur="secim", secenekler=["Windows", "WMS", "ERP", "E-posta"]),
        dict(kod="kullanici", soru="Kullanıcı adın", tur="metin", ipucu="Şifreni yazma; kimse şifreni sormaz"),
    ],
    "WIFI": [
        dict(kod="belirti", soru="Ne oluyor?", tur="secim", secenekler=["Hiç bağlanmıyor", "Sık kopuyor", "Çok yavaş"]),
        dict(kod="kapsam_yer", soru="Her yerde mi?", tur="secim", secenekler=["Yalnız bir bölgede", "Her yerde"],
             neden="Tek bölgedeyse erişim noktası, her yerdeyse ağın kendisi."),
    ],
    "BILGISAYAR": [
        dict(kod="cihaz", soru="Demirbaş numarası", tur="metin", ipucu="Kasanın üstündeki etiket"),
        dict(kod="belirti", soru="Ne oluyor?", tur="secim",
             secenekler=["Açılmıyor", "Ekranda görüntü yok", "Çok yavaş", "Fare, klavye ya da okuyucu çalışmıyor"]),
    ],
    "EPOSTA": [
        dict(kod="belirti", soru="Ne oluyor?", tur="secim",
             secenekler=["Gönderemiyorum", "Gelen posta yok", "Takvim ya da ortak kutu", "Telefonda çalışmıyor"]),
    ],
    "YAZILIM_KURULUM": [
        dict(kod="program", soru="Hangi program?", tur="metin", ipucu="Adı ve sürümü, biliyorsan"),
        dict(kod="cihaz", soru="Hangi bilgisayara?", tur="metin", ipucu="Demirbaş numarası"),
    ],
    "YETKI_TALEBI": [
        dict(kod="sistem", soru="Hangi sistem?", tur="secim", secenekler=["WMS", "ERP", "Paylaşılan klasör", "Rapor"]),
        dict(kod="yetki", soru="Hangi yetki?", tur="metin", ipucu="örn. WMS sayım onayı"),
        dict(kod="onaylayan", soru="Onaylayan yöneticin", tur="metin", ipucu="Yetki yönetici onayı olmadan verilmez"),
    ],
    "ADRES_HATASI": [
        dict(kod="adres", soru="Adres", tur="metin", ipucu="örn. A-12-03-B"),
        dict(kod="belirti", soru="Ne oluyor?", tur="secim",
             secenekler=["Adres önerilmiyor", "Dolu görünüyor ama boş", "Yanlış adrese yönlendiriyor"]),
    ],
    "STOK_FARKI": [
        dict(kod="urun", soru="Ürün kodu", tur="metin"),
        dict(kod="adres", soru="Adres", tur="metin", ipucu="örn. A-12-03-B"),
        dict(kod="fark", soru="Sistemde kaç, rafta kaç?", tur="metin", ipucu="örn. sistem 40, rafta 36"),
    ],
    "DALGA": [
        dict(kod="dalga", soru="Dalga ya da sipariş numarası", tur="metin"),
        dict(kod="hata", soru="Ekrandaki hata mesajı", tur="metin", ipucu="Aynen yaz ya da fotoğrafını hazır tut"),
    ],
    "BARKOD": [
        dict(kod="belirti", soru="Nerede okunmuyor?", tur="secim",
             secenekler=["Tek üründe", "Bütün ürünlerde", "Yalnız bir cihazda"],
             neden="Tek üründeyse etiket, bütün ürünlerdeyse okuyucu ya da sistem."),
        dict(kod="urun", soru="Ürün kodu", tur="metin", ipucu="Tek üründeyse"),
    ],
    "ENTEGRASYON": [
        dict(kod="belge", soru="Belge numarası", tur="metin", ipucu="İrsaliye, sipariş ya da fatura"),
        dict(kod="tur", soru="Hangi işlem?", tur="secim", secenekler=["Mal kabul", "Sevkiyat", "İade", "Stok transferi"]),
        dict(kod="hata", soru="Ekrandaki hata mesajı", tur="metin"),
    ],
    "RAPOR": [
        dict(kod="rapor", soru="Rapor adı", tur="metin"),
        dict(kod="son", soru="En son ne zaman güncel görünüyordu?", tur="metin", ipucu="örn. dün akşam"),
    ],
}
# Sorusu tanımlanmamış konu (yeni sistem, kendi verinle kurulum): genel sorular
GENEL_SORULAR = [
    dict(kod="cihaz", soru="Cihaz ya da ekran", tur="metin", ipucu="Hangi cihazda, hangi ekranda?"),
    dict(kod="hata", soru="Ekrandaki hata mesajı", tur="metin", ipucu="Varsa aynen yaz"),
]

# Arıza değil talep: "iş durdu mu" sorulmaz, "ne zamana lazım" sorulur
TALEP_KONULARI = {"YAZILIM_KURULUM", "YETKI_TALEBI"}

KENDIN_DENE: dict[str, list[str]] = {
    "ETIKET_YAZICI": ["Kâğıt ve ribon takılı mı, kapak tam kapalı mı bak.",
                      "Yazıcıyı kapat, 10 saniye bekle, aç.",
                      "Ekranda kırmızı ışık ya da hata yazısı varsa not al; çağrıya yaz."],
    "EL_TERMINALI": ["Terminali yeniden başlat (güç tuşuna uzun bas).",
                     "Pil azsa yedek pille değiştir.",
                     "Wi-Fi simgesi yoksa bilinen iyi çeken bir noktaya yürüyüp tekrar dene."],
    "WIFI": ["Wi-Fi'yi kapatıp aç.", "Başka bir noktada bağlanıyor mu dene; bağlanıyorsa sorunlu yeri çağrıya yaz."],
    "SIFRE_HESAP": ["Şifre sıfırlama sayfasını dene.", "Hesap kilitlendiyse arka arkaya deneme; bir süre bekleyip tekrar dene."],
    "BILGISAYAR": ["Güç ve ekran kablolarını kontrol et.", "Bilgisayarı yeniden başlat."],
    "EPOSTA": ["Outlook'u kapatıp aç.", "Web üzerinden girebiliyor musun dene; giriyorsan sorun bilgisayarda."],
    "BARKOD": ["Okuyucunun camını sil.", "Etiket buruşuksa düzelt; başka bir ürünü okutup dene."],
    "STOK_FARKI": ["Yan gözlere ve alt-üst katlara bak; ürün komşu adrese konmuş olabilir."],
    "RAPOR": ["Raporu yenile ve tarih filtresine bak."],
}

ETKI = {"durdu": ("İş tamamen durdu", 3), "yavas": ("Yavaşladı ya da geçici yolla devam ediyorum", 2),
        "yok": ("İşimi etkilemiyor", 1)}
KAPSAM = {"ben": ("Yalnız ben", 1), "ekip": ("Ekibim ya da birkaç kişi", 2), "alan": ("Bütün alan ya da vardiya", 3)}
NE_ZAMAN = {"bugun": ("Bugün lazım", 2), "hafta": ("Bu hafta içinde", 1), "acele_yok": ("Acelesi yok", 1)}
ACILIYET_AD = {1: "Düşük", 2: "Orta", 3: "Yüksek"}
BENZER_PENCERE_DK = 60


def sorular(kod: str | None) -> list[dict]:
    return SORULAR.get(kod or "", GENEL_SORULAR)


def aciliyet_hesapla(etki: str | None = None, kapsam: str | None = None, sevkiyat: bool = False,
                     kritiklik: int = 2, talep: bool = False, ne_zaman: str | None = None) -> dict:
    """Etki x kapsam → öncelik (1-3) ve düz cümleyle gerekçe."""
    if talep:
        n = ne_zaman if ne_zaman in NE_ZAMAN else "hafta"
        seviye = NE_ZAMAN[n][1]
        return dict(seviye=seviye, ad=ACILIYET_AD[seviye],
                    gerekce=f"Talep ({NE_ZAMAN[n][0].lower()}); talepler arızaların önüne geçmez.")
    e = etki if etki in ETKI else "yavas"
    k = kapsam if kapsam in KAPSAM else "ben"
    puan = ETKI[e][1] + KAPSAM[k][1]
    seviye = 3 if puan >= 5 else 2 if puan == 4 else 1
    neden = [ETKI[e][0].lower(), KAPSAM[k][0].lower()]
    if sevkiyat and e != "yok" and seviye < 3:
        seviye = 3
        neden.append("bekleyen araç ya da sevkiyat saati var")
    if kritiklik >= 3 and e == "durdu" and seviye < 2:
        seviye = 2
        neden.append("konu kritik")
    return dict(seviye=seviye, ad=ACILIYET_AD[seviye], gerekce=" + ".join(neden).capitalize() + f" → {ACILIYET_AD[seviye]}")


def cihaz_no(metin: str | None) -> str | None:
    """Etiket numarasını tek biçime getirir: "yz 7", "YZ07", "yz-007" → "YZ-07". Bilinmeyen biçim büyük harfle kalır."""
    if not metin or not metin.strip():
        return None
    s = metin.strip().upper().replace("İ", "I")
    m = re.match(r"^([A-Z]{1,4})[\s\-_./]*0*(\d{1,5})$", s)
    if not m:
        return re.sub(r"\s+", "-", s)[:30]
    genislik = {"YZ": 2, "EL": 3}.get(m.group(1), 0)
    return f"{m.group(1)}-{int(m.group(2)):0{genislik}d}"


def cihaz_kaydi(con: sqlite3.Connection | None, no: str | None) -> dict | None:
    if not no or con is None:
        return None
    r = con.execute("SELECT d.*, l.ad AS lokasyon FROM cihaz d LEFT JOIN lokasyon l ON l.id=d.lokasyon_id WHERE d.no=?",
                    (no,)).fetchone()
    return dict(r) if r else None


def cevaplari_dogrula(kod: str | None, cevaplar: dict | None, zorunlu_denetle: bool = True,
                      con: sqlite3.Connection | None = None) -> dict:
    """Yalnız konunun sorularına ait, sınırlı uzunlukta cevaplar kalır; seçim cevabı seçeneklerden olmalı.
    Zorunlu soru boşsa hata. Cihaz numarası tek biçime getirilir; envanterde kayıtlıysa model oradan gelir."""
    temiz = {}
    cevaplar = dict(cevaplar or {})
    if cevaplar.get("cihaz"):
        cevaplar["cihaz"] = cihaz_no(cevaplar["cihaz"])
        kayit = cihaz_kaydi(con, cevaplar["cihaz"])
        if kayit and any(s["kod"] == "model" for s in sorular(kod)):
            cevaplar["model"] = kayit["model"]
    for s in sorular(kod):
        v = str(cevaplar.get(s["kod"], "")).strip()[:200]
        if not v:
            if s.get("zorunlu") and zorunlu_denetle:
                raise ValueError(f"'{s['soru']}' gerekli")
            continue
        if s["tur"] == "secim" and v not in s["secenekler"]:
            raise ValueError(f"'{s['soru']}' için geçersiz seçim")
        temiz[s["kod"]] = v
    return temiz


def cagri_yeri(c) -> str | None:
    """Çağrının yeri: formda yazılan yer, yoksa metinde geçen bilinen yer."""
    yer = (c["yer"] if "yer" in c.keys() else None) or None
    if yer:
        return yer
    k = kucult(c["metin"])
    return next((y for y in K.YERLER if kucult(y) in k), None)


def benzer_acik(con: sqlite3.Connection, kategori_id: int, yer: str | None, simdi: datetime | None = None,
                lokasyon_id: int | None = None) -> list[dict]:
    """Aynı konuda son 60 dakikada açılmış açık çağrılar (yer verilmişse aynı yer ya da yeri bilinmeyenler)."""
    simdi = simdi or datetime.now()
    esik = (simdi - timedelta(minutes=BENZER_PENCERE_DK)).isoformat(timespec="minutes")
    satir = con.execute(
        "SELECT c.*, p.ad AS atanan FROM cagri c LEFT JOIN kisi p ON p.id=c.atanan_kisi_id "
        "WHERE c.kaynak='usta' AND c.durum='acik' AND c.kategori_id=? AND c.acilis>=? "
        + ("AND c.lokasyon_id=? " if lokasyon_id else "") + "ORDER BY c.acilis DESC",
        (kategori_id, esik, lokasyon_id) if lokasyon_id else (kategori_id, esik)).fetchall()
    sonuc = []
    for c in satir:
        cy = cagri_yeri(c)
        if yer and cy and kucult(cy) != kucult(yer):
            continue
        dk = max(0, round((simdi - datetime.fromisoformat(c["acilis"])).total_seconds() / 60))
        sonuc.append(dict(id=c["id"], metin=c["metin"], yer=cy, dakika_once=dk, atanan=c["atanan"]))
    return sonuc[:5]


def alan_bul(kod: str | None, cevaplar: dict | None, secilen: str | None = None, varsayilan: str | None = None,
             kurallar: dict | None = None) -> dict:
    """Çağrının gideceği alan. Sıra: belirti cevabı > kişinin seçtiği alan > konunun varsayılan alanı.
    Belirti öne geçer: "Ekran donuyor" diyen biri alanı "Donanım" seçmiş olsa da iş WMS ekibinindir."""
    for soru, harita in (kurallar if kurallar is not None else K.BELIRTI_ALANI).get(kod or "", {}).items():
        a = harita.get((cevaplar or {}).get(soru, ""))
        if a:
            return dict(alan=a, kaynak="belirti", secilenle_farkli=bool(secilen and secilen != a))
    if secilen in K.ALANLAR:
        return dict(alan=secilen, kaynak="secim", secilenle_farkli=False)
    a = varsayilan or K.KONU_ALANI.get(kod or "")
    return dict(alan=a, kaynak="konu", secilenle_farkli=False)


def _kurallar(con: sqlite3.Connection) -> dict:
    from .yonlendirme import belirti_kurallari
    return belirti_kurallari(con)


def form(con: sqlite3.Connection, kategori_id: int, yer: str | None = None, lokasyon_id: int | None = None) -> dict:
    k = con.execute("SELECT id, kod, ad, kritiklik, alan FROM kategori WHERE id=?", (kategori_id,)).fetchone()
    if not k:
        raise ValueError("Konu bulunamadı")
    kendin = con.execute("SELECT deger FROM meta WHERE anahtar=?", (f"kendin_cozdu:{k['kod']}",)).fetchone()
    oto = con.execute("SELECT ad FROM recete WHERE kategori_kod=? AND tur IN ('talep','onarim') AND askida=0 LIMIT 1",
                      (k["kod"],)).fetchone()
    return dict(kategori_id=k["id"], kategori=k["ad"], kritiklik=k["kritiklik"], talep=k["kod"] in TALEP_KONULARI,
                sorular=sorular(k["kod"]), kendin_dene=KENDIN_DENE.get(k["kod"], []),
                kendin_cozdu=int(kendin[0]) if kendin else 0, otomatik_cozum=oto["ad"] if oto else None,
                alan=k["alan"], alan_haritasi=_kurallar(con).get(k["kod"], {}), benzer=benzer_acik(con, kategori_id, yer, lokasyon_id=lokasyon_id),
                yerler=K.YERLER, etki=[dict(kod=a, ad=b[0]) for a, b in ETKI.items()],
                kapsam=[dict(kod=a, ad=b[0]) for a, b in KAPSAM.items()],
                ne_zaman=[dict(kod=a, ad=b[0]) for a, b in NE_ZAMAN.items()])


def kendin_cozdu(con: sqlite3.Connection, kategori_id: int) -> int:
    """Kişi kendin dene adımlarıyla çözüp çağrı açmadı: konu başına sayılır (açılmayan çağrı ölçüsü)."""
    k = con.execute("SELECT kod FROM kategori WHERE id=?", (kategori_id,)).fetchone()
    if not k:
        raise ValueError("Konu bulunamadı")
    anahtar = f"kendin_cozdu:{k['kod']}"
    con.execute("INSERT INTO meta(anahtar, deger) VALUES(?, '1') "
                "ON CONFLICT(anahtar) DO UPDATE SET deger=CAST(deger AS INTEGER)+1", (anahtar,))
    con.commit()
    return int(con.execute("SELECT deger FROM meta WHERE anahtar=?", (anahtar,)).fetchone()[0])


def ek_bilgi_json(kod: str | None, cevaplar: dict, etki: str | None, kapsam: str | None, sevkiyat: bool,
                  ne_zaman: str | None, oncelik: dict) -> str:
    """Çağrıya yazılan ek bilgi. Cevaplar soru metniyle saklanır: soru listesi sonradan değişse de kayıt okunur kalır."""
    etiket = {s["kod"]: s["soru"] for s in sorular(kod)}
    return json.dumps(dict(cevaplar=[dict(soru=etiket[k], cevap=v) for k, v in cevaplar.items()],
                           etki=ETKI[etki][0] if etki in ETKI else None, kapsam=KAPSAM[kapsam][0] if kapsam in KAPSAM else None,
                           sevkiyat=sevkiyat, ne_zaman=NE_ZAMAN[ne_zaman][0] if ne_zaman in NE_ZAMAN else None,
                           oncelik_gerekce=oncelik["gerekce"]), ensure_ascii=False)


TEKRAR_GUN, TEKRAR_ESIK = 30, 3   # 30 günde 3 ve üzeri çağrı: tekrarlayan arıza


def cihaz_gecmisi(con: sqlite3.Connection, no: str, gun: int = 90, simdi: datetime | None = None) -> dict:
    """Bir cihazın kaydı ve son çağrıları. Formda numara yazılınca ve çağrı detayında gösterilir."""
    no = cihaz_no(no)
    simdi = simdi or datetime.now()
    esik = (simdi - timedelta(days=gun)).isoformat(timespec="minutes")
    cagrilar = [dict(r) for r in con.execute(
        "SELECT c.id, c.metin, c.acilis, c.durum, c.cozum_notu, k.ad AS kategori, p.ad AS cozen FROM cagri c "
        "JOIN kategori k ON k.id=c.kategori_id LEFT JOIN kisi p ON p.id=c.cozen_kisi_id "
        "WHERE c.cihaz=? AND c.acilis>=? ORDER BY c.acilis DESC", (no, esik))]
    son30 = (simdi - timedelta(days=TEKRAR_GUN)).isoformat(timespec="minutes")
    return dict(no=no, kayit=cihaz_kaydi(con, no), gun=gun, cagrilar=cagrilar[:10], toplam=len(cagrilar),
                son_30_gun=sum(1 for c in cagrilar if c["acilis"] >= son30),
                tekrarlayan=sum(1 for c in cagrilar if c["acilis"] >= son30) >= TEKRAR_ESIK)


def tekrarlayan_cihazlar(con: sqlite3.Connection, simdi: datetime | None = None) -> list[dict]:
    """Son 30 günde 3 ve üzeri çağrısı olan cihazlar: onarım yerine değişim ya da bakım konuşulmalı."""
    simdi = simdi or datetime.now()
    esik = (simdi - timedelta(days=TEKRAR_GUN)).isoformat(timespec="minutes")
    out = []
    for r in con.execute("SELECT cihaz, COUNT(*) n, MAX(acilis) son FROM cagri WHERE cihaz IS NOT NULL AND acilis>=? "
                         "GROUP BY cihaz HAVING COUNT(*)>=? ORDER BY n DESC, cihaz", (esik, TEKRAR_ESIK)):
        kayit = cihaz_kaydi(con, r["cihaz"])
        out.append(dict(no=r["cihaz"], cagri=r["n"], son=r["son"], model=kayit["model"] if kayit else None,
                        yer=kayit["yer"] if kayit else None))
    return out


# ---------------------------------------------------------------- cihaz envanteri

ENVANTER_SATIR = 20_000
_ENVANTER_AD = {"no": "no", "numara": "no", "cihaz": "no", "cihaz no": "no", "etiket": "no", "demirbaş no": "no",
                "demirbas no": "no", "tur": "tur", "tür": "tur", "tip": "tur", "model": "model", "yer": "yer",
                "konum": "yer", "lokasyon": "yer", "seri no": "seri_no", "seri": "seri_no", "seri_no": "seri_no",
                "durum": "durum", "tesis": "lokasyon", "lokasyon": "lokasyon", "depo": "lokasyon", "şube": "lokasyon"}
_TUR = {"yazici": "yazici", "yazıcı": "yazici", "etiket yazıcısı": "yazici", "terminal": "terminal",
        "el terminali": "terminal", "rf terminal": "terminal"}


def envanter_ice_aktar(con: sqlite3.Connection, metin: str, tam: bool = False) -> dict:
    """Demirbaş sisteminden alınan CSV'yi cihaz tablosuna yazar (varsa günceller).
    Sütunlar: no (gerekli), tür, model, yer, seri no, durum. tam=True: listede olmayan aktif cihazlar hurdaya ayrılır
    (tam döküm geldiğinde; kısmi dökümde kullanılmaz)."""
    import csv
    import io
    metin = (metin or "").lstrip("﻿").strip()
    if not metin:
        raise ValueError("Envanter boş")
    ayrac = max([";", ",", "\t"], key=metin.splitlines()[0].count)
    okuyucu = csv.DictReader(io.StringIO(metin), delimiter=ayrac)
    okuyucu.fieldnames = [_ENVANTER_AD.get((a or "").strip().lower(), (a or "").strip().lower()) for a in okuyucu.fieldnames or []]
    if "no" not in okuyucu.fieldnames:
        raise ValueError("Eksik sütun: no (cihaz numarası)")
    simdi = datetime.now().date().isoformat()
    eklenen = guncellenen = 0
    hatalar, gorulen = [], set()
    for i, r in enumerate(okuyucu, start=2):
        if i - 1 > ENVANTER_SATIR:
            hatalar.append(f"{ENVANTER_SATIR} satırdan sonrası alınmadı")
            break
        no = cihaz_no(r.get("no"))
        if not no:
            hatalar.append(f"{i}. satır: numara boş")
            continue
        tur = _TUR.get((r.get("tur") or "").strip().lower(), (r.get("tur") or "diğer").strip().lower()[:20] or "diğer")
        durum = "hurda" if (r.get("durum") or "").strip().lower() in ("hurda", "pasif", "kayıttan düşüldü") else "aktif"
        lok = None
        if (r.get("lokasyon") or "").strip():   # tesis adı yoksa eklenir (envanter tesisin kaynağıdır)
            ad = r["lokasyon"].strip()[:60]
            row = next((x for x in con.execute("SELECT id, ad FROM lokasyon") if kucult(x["ad"]) == kucult(ad)), None)
            lok = row["id"] if row else con.execute("INSERT INTO lokasyon(ad) VALUES(?)", (ad,)).lastrowid
        vals = [tur, (r.get("model") or "").strip()[:60] or None, (r.get("yer") or "").strip()[:60] or None,
                (r.get("seri_no") or "").strip()[:60] or None, durum, simdi, lok]
        var = con.execute("SELECT 1 FROM cihaz WHERE no=?", (no,)).fetchone()
        if var:
            con.execute("UPDATE cihaz SET tur=?, model=?, yer=?, seri_no=?, durum=?, guncelleme=?, "
                        "lokasyon_id=COALESCE(?, lokasyon_id) WHERE no=?", (*vals, no))
            guncellenen += 1
        else:
            con.execute("INSERT INTO cihaz(tur,model,yer,seri_no,durum,guncelleme,lokasyon_id,no) VALUES(?,?,?,?,?,?,?,?)", (*vals, no))
            eklenen += 1
        gorulen.add(no)
    hurdaya = 0
    if tam and gorulen:
        for (n,) in con.execute("SELECT no FROM cihaz WHERE durum='aktif'").fetchall():
            if n not in gorulen:
                con.execute("UPDATE cihaz SET durum='hurda', guncelleme=? WHERE no=?", (simdi, n))
                hurdaya += 1
    con.commit()
    return dict(eklenen=eklenen, guncellenen=guncellenen, hurdaya=hurdaya, hatalar=hatalar[:20],
                toplam=con.execute("SELECT COUNT(*) FROM cihaz WHERE durum='aktif'").fetchone()[0])


def envanter_ozeti(con: sqlite3.Connection, simdi: datetime | None = None) -> dict:
    """Cihaz çoksa tek tek değil grup olarak bakılır: model başına cihaz başı arıza (son 90 gün) ve
    envanterde olmayan numaralar (yazım hatası ya da envantere girmemiş yeni cihaz)."""
    simdi = simdi or datetime.now()
    esik = (simdi - timedelta(days=90)).isoformat(timespec="minutes")
    modeller = [dict(r) for r in con.execute(
        "SELECT d.tur, d.model, COUNT(DISTINCT d.no) cihaz, "
        "(SELECT COUNT(*) FROM cagri c JOIN cihaz e ON e.no=c.cihaz WHERE e.model IS d.model AND e.tur=d.tur AND c.acilis>=?) cagri "
        "FROM cihaz d WHERE d.durum='aktif' GROUP BY d.tur, d.model ORDER BY d.tur, d.model", (esik,))]
    for m in modeller:
        m["cihaz_basi"] = round(m["cagri"] / m["cihaz"], 1) if m["cihaz"] else 0
    for tur in {m["tur"] for m in modeller}:   # aynı türde ortalamanın iki katı: model sorunu olabilir
        grup = [m for m in modeller if m["tur"] == tur]
        ort = sum(m["cagri"] for m in grup) / max(1, sum(m["cihaz"] for m in grup))
        for m in grup:
            m["dikkat"] = bool(ort and m["cihaz_basi"] >= 2 * ort and m["cagri"] >= 5)
    kayitsiz = [dict(r) for r in con.execute(
        "SELECT c.cihaz AS no, COUNT(*) cagri, MAX(c.acilis) son FROM cagri c LEFT JOIN cihaz d ON d.no=c.cihaz "
        "WHERE c.cihaz IS NOT NULL AND d.no IS NULL AND c.acilis>=? GROUP BY c.cihaz ORDER BY cagri DESC LIMIT 20", (esik,))]
    sayi = con.execute("SELECT COUNT(*) FROM cihaz WHERE durum='aktif'").fetchone()[0]
    return dict(cihaz_sayisi=sayi, modeller=modeller, kayitsiz=kayitsiz)
