"""Otomasyon: bazı çağrıları belirli yetkiler dahilinde insansız çözer.

Altı akış:
  1. TALEP KARŞILAMA    Kurulum, yetki, kilit açma. Eksik bilgi Teams'ten sorulur, gerekiyorsa yöneticiden
                        onay alınır, işlem yapılır, çağrı kapanır.
  2. BİLİNEN ÇÖZÜMÜ DENE Yazıcı, rapor işi, terminal ağı. Önce teşhis, sonra adımlar sırayla denenir; her
                        adımdan sonra kontrol edilir. Hiçbiri tutmazsa çağrı, denenenlerle birlikte insana kalır.
  3. NOTLARDAN REÇETE   Aynı çözüm yolu sık tekrarlanıyorsa "reçeteye çevirelim mi?" önerisi. Çevrilen reçete
                        taslaktır: adımların gerçek sistemlere bağlanması BT'nin işidir.
  4. TOPLU ARIZA        Aynı konuda kısa sürede çok çağrı gelirse tek olayda birleşir; herkese tek bilgi gider,
                        ana çağrı kapanınca hepsi kapanır.
  5. KAPANIŞ TEYİDİ      Her kapanışta açan kişiye "çözüldü mü?" sorulur. Hayır derse çağrı yeniden açılır;
                        o çözüm notu öğrenmeye girmez, reçetenin başarı sayacı düşer.
  6. İŞE GİRİŞ / ÇIKIŞ  İK kaydıyla hesap, rol, terminal, e-posta ve yazılımlar tek seferde açılır ya da kapanır.

SAĞLIK İZLEME
  Her reçetenin son 30 gündeki gerçek başarısı ölçülür (insana devredilen ve "çözülmedi" denenler başarısız).
  En az 5 deneme varsa risk hesabı beklenen değil gerçek başarıyı kullanır. Başarı beklenenin 25 puan
  altına inerse uyarı verilir; en az 8 denemede %40'ın altına inerse reçete kendiliğinden ASKIYA alınır:
  yeni çağrılarda çalışmaz, çağrılar doğrudan insana gider ve risk indirimi geri alınır. Sorun giderilince
  "yeniden devreye al" ile ölçüm sıfırdan başlar.

YETKİ ÇERÇEVESİ
  otomatik : kendi başına yapar (kilit açma, onarım adımları, işe giriş paketi)
  onayli   : yöneticinin Teams onayından sonra yapar (lisanslı yazılım, rol ekleme)
  insan    : yalnızca önerir (taslak reçeteler, katalog dışı talepler)
  Karar her zaman burada yazılı kurallarla verilir; makine öğrenmesi yalnızca konuyu tanır.

Bu demoda Teams, kimlik sistemi ve kurulum aracı SİMÜLE edilir. Gerçek kullanımda her adım ilgili
aracın (Intune/SCCM, Active Directory/Entra ID, MDM, yazdırma sunucusu) API'sine bağlanır ve otomasyon
yalnızca kendi işine yetecek kadar yetkili bir servis hesabıyla çalışır.
"""
from __future__ import annotations

import json
import random
import re
import sqlite3
from datetime import datetime, timedelta

from . import katalog as K
from .dil import sayi
from .ogrenme import kucult as _kucult


def kucult(s: str) -> str:
    """Eşleştirme için sadeleştirme: küçük harf ve ı→i. ("Power BI" → "power bi", "BİLGİ" → "bilgi")"""
    return _kucult(s).replace("ı", "i")

SEVIYE_ADI = {"otomatik": "Otomatik", "onayli": "Onaylı otomatik", "insan": "Yalnızca insan"}
TOPLU_PENCERE_DK = 60
TOPLU_ESIK = 3                 # en az bu kadar farklı kişiden
TOPLU_HARIC = {"YAZILIM_KURULUM", "YETKI_TALEBI", "SIFRE_HESAP"}   # talepler arıza değildir, birleşmez
ADAY_ESIK = 8

RECETELER = [
    dict(kod="KURULUM", sahip="Deniz Aksoy", ad="Yazılım kurulumu", tur="talep", seviye="onayli", kategori_kod="YAZILIM_KURULUM",
         aciklama="Onaylı katalogdaki yazılımı kişinin kendi cihazına kurar. Lisans gerektiren yazılımlar yönetici onayı ister.",
         bilgiler=["yazilim", "cihaz"], arac="Intune / SCCM", manuel_dk=35,
         adimlar=["Yazılım onaylı katalogda mı", "Cihaz talep edene mi kayıtlı", "Boş lisans var mı",
                  "Gerekiyorsa yönetici onayı", "Kurulum paketini gönder", "Kurulumu doğrula"],
         geri_alma="Kaldırma paketi gönderilir, lisans havuza döner"),
    dict(kod="YETKI", sahip="Deniz Aksoy", ad="Rol ve erişim ekleme", tur="talep", seviye="onayli", kategori_kod="YETKI_TALEBI",
         aciklama="Rol kataloğundaki bir rolü kişiye ekler. Her zaman yönetici onayı ister.",
         bilgiler=["rol", "gerekce"], arac="Active Directory / Entra ID", manuel_dk=20,
         adimlar=["Rol katalogda mı", "Gerekçe alındı mı", "Yönetici onayı", "Kişiyi gruba ekle", "Erişimi doğrula"],
         geri_alma="Kişi gruptan çıkarılır"),
    dict(kod="SIFRE", sahip="Deniz Aksoy", ad="Hesap kilidi açma", tur="talep", seviye="otomatik", kategori_kod="SIFRE_HESAP",
         ifadeler=["şifre", "parola", "kilit"], haric=["yeni başla", "yeni personel", "bölüm değiştir"],
         aciklama="Kimliği doğrulanan kişinin hesap kilidini açar ve geçici şifre verir.",
         bilgiler=["kimlik"], arac="Active Directory / Entra ID", manuel_dk=10,
         adimlar=["Kimlik doğrulama (sicil)", "Kilidi aç", "Geçici şifre gönder"], geri_alma="Gerekmez"),
    dict(kod="YAZICI", sahip="Tolga Demir", ad="Yazıcı bağlantı ve kuyruk onarımı", tur="onarim", seviye="otomatik",
         kategori_kod="ETIKET_YAZICI", ifadeler=["çevrimdışı", "kuyruk", "ağdan", "ip ", "tanımlı değil", "basmıyor"],
         haric=["ribon", "kağıt", "soluk", "kayık"],
         aciklama="Ağ ve kuyruk kaynaklı yazıcı sorunlarında bilinen çözümleri sırayla dener.",
         arac="Yazdırma sunucusu betikleri", manuel_dk=25,
         teshis="Yazıcıya ağdan ulaşılabiliyor mu (ping)",
         denemeler=[["Yazdırma kuyruğunu temizle", "Test etiketi basıldı mı?", 0.45],
                    ["Yazıcı sürücüsünü yeniden yükle", "Test etiketi basıldı mı?", 0.5],
                    ["Yazıcıyı uzaktan yeniden başlat", "Yazıcı çevrimiçi ve test etiketi basıldı mı?", 0.4]],
         geri_alma="Gerekmez"),
    dict(kod="RAPOR", sahip="Emre Çelik", ad="Gece rapor işini yeniden çalıştırma", tur="onarim", seviye="otomatik",
         kategori_kod="RAPOR", ifadeler=["gelmedi", "yenilenme", "güncel değil", "dünkü", "açılmıyor", "veri kaynağı"],
         aciklama="Gelmeyen ya da güncel olmayan raporlarda veri yükleme işini yeniden çalıştırır.",
         arac="Zamanlanmış iş yöneticisi", manuel_dk=30,
         teshis="Gece veri yükleme işinin son durumu",
         denemeler=[["Başarısız yükleme işini yeniden başlat", "Küp bugünün verisiyle işlendi mi?", 0.6],
                    ["Küpü elle yeniden işle", "Küp güncel mi?", 0.5]],
         son_adim="Rapor aboneliğini alıcılara yeniden gönder", geri_alma="Gerekmez"),
    dict(kod="TERMINAL", sahip="Tolga Demir", ad="El terminali ağ profili", tur="onarim", seviye="otomatik",
         kategori_kod="EL_TERMINALI", ifadeler=["ağa", "wi-fi", "wifi", "bağlantı yok", "bağlanamadı", " ağ"],
         haric=["şarj", "batarya", "tuş", "ekranı"],
         aciklama="Ağa bağlanamayan terminale profil gönderir, gerekirse uzaktan yeniden başlatır.",
         arac="Mobil cihaz yönetimi (MDM)", manuel_dk=20,
         teshis="Cihaz yönetim panelinde terminal en son ne zaman görüldü",
         denemeler=[["Ağ profilini yeniden gönder", "Terminal ağa bağlandı mı?", 0.55],
                    ["Terminali uzaktan yeniden başlat", "Terminal ağa bağlandı mı?", 0.45]],
         geri_alma="Gerekmez"),
    dict(kod="ISE_GIRIS", sahip="Deniz Aksoy", ad="İşe giriş paketi", tur="paket", seviye="otomatik", kategori_kod=None,
         aciklama="İK'nın işe giriş kaydı gelince kullanıcı, roller, terminal hesabı, e-posta ve yazılımlar tek seferde açılır. İK kaydı yetki belgesi sayılır.",
         arac="İK sistemi + kimlik yönetimi", manuel_dk=90,
         adimlar=["Kullanıcı hesabı", "Göreve göre roller", "Terminal hesabı", "E-posta kutusu", "Yazılımlar", "Yöneticiye bilgi"],
         geri_alma="İşten çıkış paketi"),
    dict(kod="ISTEN_CIKIS", sahip="Deniz Aksoy", ad="İşten çıkış paketi", tur="paket", seviye="otomatik", kategori_kod=None,
         aciklama="İK'nın çıkış kaydıyla hesaplar kapatılır, roller alınır, lisanslar havuza döner; cihaz iadesi insana kalır.",
         arac="İK sistemi + kimlik yönetimi", manuel_dk=60,
         adimlar=["Hesabı kapat", "Rolleri kaldır", "Lisansları geri al", "Cihaz iadesi (insan)", "Yöneticiye bilgi"],
         geri_alma="Hesap yeniden açılabilir (30 gün)"),
]


# ---------------------------------------------------------------- yardımcılar

def _simdi() -> str:
    return datetime.now().isoformat(timespec="seconds")


def _js(x) -> str:
    return json.dumps(x, ensure_ascii=False)


def recete_tanimlarini_yukle(con: sqlite3.Connection, olusturma: str | None = None) -> None:
    """Hazır reçeteleri yükler. olusturma: reçetelerin devreye girdiği an (risk seyrinde bu andan
    önceki dönemlerde otomasyon yok sayılır)."""
    for r in RECETELER:
        tanim = {k: v for k, v in r.items() if k not in ("kod", "ad", "tur", "seviye", "kategori_kod", "sahip")}
        con.execute("INSERT OR REPLACE INTO recete(kod,ad,tur,seviye,kategori_kod,tanim,olusturma,sahip) VALUES(?,?,?,?,?,?,?,?)",
                    (r["kod"], r["ad"], r["tur"], r["seviye"], r["kategori_kod"], _js(tanim), olusturma or _simdi(), r["sahip"]))
    con.commit()


def _recete(con, kod: str) -> dict:
    r = con.execute("SELECT * FROM recete WHERE kod=?", (kod,)).fetchone()
    d = dict(r)
    d["tanim"] = json.loads(d["tanim"])
    return d


def _oto(con, oto_id: int) -> dict:
    r = con.execute("SELECT * FROM oto WHERE id=?", (oto_id,)).fetchone()
    if not r:
        raise ValueError("Otomasyon kaydı bulunamadı")
    d = dict(r)
    d["bilgiler"], d["gunluk"] = json.loads(d["bilgiler"]), json.loads(d["gunluk"])
    return d


def _kaydet(con, o: dict) -> None:
    con.execute("UPDATE oto SET durum=?, bilgiler=?, gunluk=?, bitis=? WHERE id=?",
                (o["durum"], _js(o["bilgiler"]), _js(o["gunluk"]), o.get("bitis"), o["id"]))


def _yaz(o: dict, kim: str, tur: str, metin: str, sonuc: str | None = None) -> None:
    o["gunluk"].append(dict(zaman=_simdi(), kim=kim, tur=tur, metin=metin, sonuc=sonuc))


def _mesaj(con, o: dict | None, cagri_id, kime: str, rol: str, tur: str, metin: str,
           secenekler: list[str] | None = None, alan: str | None = None, serbest: bool = False) -> int:
    cur = con.execute(
        "INSERT INTO mesaj(oto_id,cagri_id,kime,rol,tur,alan,metin,secenekler,serbest,zaman) VALUES(?,?,?,?,?,?,?,?,?,?)",
        (o["id"] if o else None, cagri_id, kime, rol, tur, alan, metin, _js(secenekler or []), int(serbest), _simdi()))
    if o is not None:
        _yaz(o, "Teams", "mesaj", f"{kime} kişisine: {metin}", "bekliyor" if tur in ("soru", "onay") else None)
    return cur.lastrowid


def _hesap(con, ad: str) -> dict | None:
    r = con.execute("SELECT * FROM hesap WHERE ad=?", (ad,)).fetchone()
    if not r:
        return None
    d = dict(r)
    d["roller"], d["yazilimlar"] = json.loads(d["roller"]), json.loads(d["yazilimlar"])
    return d


def _hesap_yaz(con, h: dict) -> None:
    con.execute("UPDATE hesap SET roller=?, yazilimlar=?, durum=?, kilitli=? WHERE ad=?",
                (_js(h["roller"]), _js(h["yazilimlar"]), h["durum"], h["kilitli"], h["ad"]))


# ---------------------------------------------------------------- bilgi çıkarma

def _yazilim_bul(metin: str) -> str | None:
    k = kucult(metin)
    for y in K.YAZILIM_KATALOGU:
        if any(kucult(a) in k for a in y["anahtar"]) or kucult(y["ad"]) in k:
            return y["ad"]
    for y in K.KATALOG_DISI_YAZILIMLAR:
        if kucult(y) in k:
            return "KATALOG_DISI:" + y
    return None


def _rol_bul(metin: str) -> str | None:
    k = kucult(metin)
    for r in K.ROL_KATALOGU:
        if any(kucult(a) in k for a in r["anahtar"]) or kucult(r["ad"]) in k:
            return r["ad"]
    return None


def bilgi_cikar(recete_kod: str, metin: str) -> dict:
    """Çağrı metninden reçetenin ihtiyaç duyduğu bilgileri çıkarır (bulamadığını sorar)."""
    b = {}
    if recete_kod == "KURULUM":
        y = _yazilim_bul(metin)
        if y:
            b["yazilim"] = y
        m = re.search(r"\bPC-?(\d{4})\b", metin, re.I)
        if m:
            b["cihaz"] = f"PC-{m.group(1)}"
    elif recete_kod == "YETKI":
        r = _rol_bul(metin)
        if r:
            b["rol"] = r
    return b


def eslesen_recete(con: sqlite3.Connection, metin: str, kategori_id: int) -> dict | None:
    kod = con.execute("SELECT kod FROM kategori WHERE id=?", (kategori_id,)).fetchone()
    if not kod:
        return None
    k = kucult(metin)
    for r in con.execute("SELECT kod FROM recete WHERE kategori_kod=? AND tur IN ('talep','onarim') AND askida=0",
                         (kod[0],)):
        rc = _recete(con, r["kod"])
        t = rc["tanim"]
        if t.get("ifadeler") and not any(kucult(i) in k for i in t["ifadeler"]):
            continue
        if any(kucult(h) in k for h in t.get("haric", [])):
            continue
        return rc
    return None


# ---------------------------------------------------------------- başlat ve ilerlet

def baslat(con: sqlite3.Connection, cagri_id: int) -> dict | None:
    """Yeni açılan çağrıya uyan bir reçete varsa otomasyonu başlatır."""
    c = con.execute("SELECT c.*, p.ad AS atanan FROM cagri c LEFT JOIN kisi p ON p.id=c.atanan_kisi_id WHERE c.id=?",
                    (cagri_id,)).fetchone()
    if not c or c["olay_id"]:
        return None
    rc = eslesen_recete(con, c["metin"], c["kategori_id"])
    if not rc:
        return None
    o = dict(cagri_id=cagri_id, recete_kod=rc["kod"], kisi=c["acan_kisi"], durum="basladi",
             bilgiler=bilgi_cikar(rc["kod"], c["metin"]), gunluk=[], bitis=None)
    cur = con.execute("INSERT INTO oto(cagri_id,recete_kod,kisi,durum,bilgiler,gunluk,baslangic) VALUES(?,?,?,?,?,?,?)",
                      (cagri_id, rc["kod"], c["acan_kisi"], "basladi", _js(o["bilgiler"]), "[]", _simdi()))
    o["id"] = cur.lastrowid
    _yaz(o, "Otomasyon", "karar", f"'{rc['ad']}' reçetesi uydu ({SEVIYE_ADI[rc['seviye']]}). "
         f"Otomasyon başarısız olursa çağrı {c['atanan'] or 'birime'} kalır.")
    if o["bilgiler"]:
        _yaz(o, "Otomasyon", "bilgi", "Metinden alınan bilgiler: " + ", ".join(
            f"{k}={v.replace('KATALOG_DISI:', '')}" for k, v in o["bilgiler"].items()))
    con.execute("UPDATE recete SET deneme=deneme+1 WHERE kod=?", (rc["kod"],))
    _ilerlet(con, o, rc)
    con.commit()
    return oto_detay(con, o["id"])


def _ilerlet(con, o: dict, rc: dict) -> None:
    c = con.execute("SELECT * FROM cagri WHERE id=?", (o["cagri_id"],)).fetchone()
    if rc["tur"] == "onarim":
        _onarim(con, o, rc, c)
    elif rc["kod"] == "KURULUM":
        _kurulum(con, o, rc, c)
    elif rc["kod"] == "YETKI":
        _yetki(con, o, rc, c)
    elif rc["kod"] == "SIFRE":
        _sifre(con, o, rc, c)
    _kaydet(con, o)


def _bekleyen(con, o: dict) -> bool:
    return con.execute("SELECT 1 FROM mesaj WHERE oto_id=? AND cevap IS NULL AND tur IN ('soru','onay')",
                       (o["id"],)).fetchone() is not None


def _insana(con, o: dict, neden: str) -> None:
    o["durum"], o["bitis"] = "insana_devredildi", _simdi()
    _yaz(o, "Otomasyon", "karar", f"İnsana devredildi: {neden}", "hata")
    c = con.execute("SELECT c.*, p.ad AS atanan FROM cagri c LEFT JOIN kisi p ON p.id=c.atanan_kisi_id WHERE c.id=?",
                    (o["cagri_id"],)).fetchone()
    con.execute("INSERT INTO cagri_olay(cagri_id,zaman,tur,kisi_id,aciklama) VALUES(?,?,?,?,?)",
                (o["cagri_id"], _simdi()[:16], "otomasyon", c["atanan_kisi_id"],
                 f"Otomasyon insana devretti: {neden}"))
    if o.get("kisi"):
        _mesaj(con, o, o["cagri_id"], o["kisi"], "talep_eden", "bilgi",
               f"Talebiniz otomatik karşılanamadı ({neden}). {c['atanan'] or 'Destek ekibi'} ilgilenecek.")
    saglik_kontrol(con, o["recete_kod"], o)


def _sor(con, o, c, alan: str, metin: str, secenekler: list[str], serbest: bool = False) -> None:
    o["durum"] = "bilgi_bekliyor"
    _mesaj(con, o, c["id"], o["kisi"], "talep_eden", "soru", metin, secenekler, alan, serbest)


def _onay_iste(con, o, c, ozet: str) -> bool:
    """Onay alındıysa True. Bekleniyorsa ya da reddedildiyse False."""
    karar = o["bilgiler"].get("onay")
    if karar == "Onayla":
        return True
    if karar == "Reddet":
        o["durum"], o["bitis"] = "reddedildi", _simdi()
        _yaz(o, "Otomasyon", "karar", "Yönetici onaylamadı; talep kapatıldı.", "hata")
        kapat(con, c["id"], None, "Talep yönetici tarafından onaylanmadı", otomatik=True)
        return False
    if not _bekleyen(con, o):
        hesap = _hesap(con, o["kisi"]) or {}
        yonetici = K.BIRIM_YONETICI.get(hesap.get("birim") or c["acan_birim"], "Birim yöneticisi")
        o["durum"] = "onay_bekliyor"
        _mesaj(con, o, c["id"], yonetici, "yonetici", "onay", f"{o['kisi']} için onay isteniyor: {ozet}",
               ["Onayla", "Reddet"])
    return False


def _calistir(o: dict, adimlar: list[str], tohum: int, basari: float = 0.95) -> bool:
    rnd = random.Random(tohum)
    for a in adimlar:
        ok = rnd.random() < basari
        _yaz(o, "Otomasyon", "adim", a, "ok" if ok else "hata")
        if not ok:
            return False
    return True


def _basarili(con, o, rc, c, notu: str) -> None:
    o["durum"], o["bitis"] = "basarili", _simdi()
    _yaz(o, "Otomasyon", "karar", "Tamamlandı; çağrı otomatik kapatıldı.", "ok")
    con.execute("UPDATE recete SET basari=basari+1 WHERE kod=?", (rc["kod"],))
    kapat(con, c["id"], None, notu, otomatik=True)
    saglik_kontrol(con, rc["kod"], o)


def _kurulum(con, o, rc, c) -> None:
    b = o["bilgiler"]
    hesap = _hesap(con, o["kisi"]) if o["kisi"] else None
    if not hesap:
        return _insana(con, o, "talep eden kişinin hesabı bulunamadı")
    if "yazilim" not in b:
        if not _bekleyen(con, o):
            _sor(con, o, c, "yazilim", "Hangi yazılımın kurulmasını istiyorsunuz?",
                 [y["ad"] for y in K.YAZILIM_KATALOGU] + ["Listede yok"])
        return
    if b["yazilim"] == "Listede yok" or b["yazilim"].startswith("KATALOG_DISI:"):
        return _insana(con, o, f"'{b['yazilim'].replace('KATALOG_DISI:', '')}' onaylı katalogda yok; satın alma ve güvenlik değerlendirmesi gerekir")
    if "cihaz" not in b:
        if not _bekleyen(con, o):
            _sor(con, o, c, "cihaz", f"{b['yazilim']} hangi bilgisayara kurulsun?",
                 [hesap["cihaz"], "Başka bir cihaz"])
        return
    _yaz(o, "Otomasyon", "kontrol", f"{b['yazilim']} onaylı katalogda", "ok")
    if b["cihaz"] != hesap["cihaz"]:
        _yaz(o, "Otomasyon", "kontrol", f"{b['cihaz']} {o['kisi']} adına kayıtlı değil", "hata")
        return _insana(con, o, f"{b['cihaz']} talep edene kayıtlı değil")
    _yaz(o, "Otomasyon", "kontrol", f"{b['cihaz']} {o['kisi']} adına kayıtlı", "ok")
    if b["yazilim"] in hesap["yazilimlar"]:
        _yaz(o, "Otomasyon", "kontrol", "Yazılım bu cihazda zaten kurulu", "ok")
        return _basarili(con, o, rc, c, f"{b['yazilim']} {b['cihaz']} üzerinde zaten kurulu; kullanıcıya bilgi verildi")
    y = next(x for x in K.YAZILIM_KATALOGU if x["ad"] == b["yazilim"])
    if y["lisans"] is not None:
        l = con.execute("SELECT * FROM lisans WHERE yazilim=?", (y["ad"],)).fetchone()
        bos = l["toplam"] - l["kullanilan"]
        _yaz(o, "Otomasyon", "kontrol", f"Boş lisans: {bos}/{l['toplam']}", "ok" if bos > 0 else "hata")
        if bos <= 0:
            return _insana(con, o, f"{y['ad']} için boş lisans yok; lisans geri alma ya da satın alma gerekir")
    if y["onay"] and not _onay_iste(con, o, c, f"{y['ad']} kurulumu ({b['cihaz']})"):
        return
    if y["onay"]:
        _yaz(o, "Teams", "karar", "Yönetici onayladı", "ok")
    if not _calistir(o, [f"Kurulum paketi {b['cihaz']} cihazına gönderildi", "Kurulum doğrulandı"], c["id"] * 7):
        return _insana(con, o, "kurulum doğrulanamadı")
    hesap["yazilimlar"].append(y["ad"])
    _hesap_yaz(con, hesap)
    if y["lisans"] is not None:
        con.execute("UPDATE lisans SET kullanilan=kullanilan+1 WHERE yazilim=?", (y["ad"],))
    _basarili(con, o, rc, c, f"{y['ad']} {b['cihaz']} cihazına otomatik kuruldu"
              + (" (yönetici onaylı)" if y["onay"] else "") + "\nKurulum doğrulandı")


def _yetki(con, o, rc, c) -> None:
    b = o["bilgiler"]
    hesap = _hesap(con, o["kisi"]) if o["kisi"] else None
    if not hesap:
        return _insana(con, o, "talep eden kişinin hesabı bulunamadı")
    if "rol" not in b:
        if not _bekleyen(con, o):
            _sor(con, o, c, "rol", "Hangi yetkiye ihtiyacınız var?", [r["ad"] for r in K.ROL_KATALOGU] + ["Listede yok"])
        return
    if b["rol"] == "Listede yok":
        return _insana(con, o, "istenen rol katalogda yok")
    if "gerekce" not in b:
        if not _bekleyen(con, o):
            _sor(con, o, c, "gerekce", f"'{b['rol']}' yetkisine neden ihtiyacınız var?",
                 ["Görevim değişti", "Vardiya sorumlusuna vekâlet", "Geçici proje"], serbest=True)
        return
    _yaz(o, "Otomasyon", "kontrol", f"{b['rol']} rol kataloğunda", "ok")
    if b["rol"] in hesap["roller"]:
        return _basarili(con, o, rc, c, f"{b['rol']} rolü zaten tanımlı; kullanıcıya bilgi verildi")
    if not _onay_iste(con, o, c, f"'{b['rol']}' rolü — gerekçe: {b['gerekce']}"):
        return
    _yaz(o, "Teams", "karar", "Yönetici onayladı", "ok")
    if not _calistir(o, [f"{o['kisi']} '{b['rol']}' grubuna eklendi", "Erişim doğrulandı"], c["id"] * 11):
        return _insana(con, o, "rol eklenemedi")
    hesap["roller"].append(b["rol"])
    _hesap_yaz(con, hesap)
    _basarili(con, o, rc, c, f"Yönetici onayıyla '{b['rol']}' rolü eklendi (gerekçe: {b['gerekce']})\nErişim doğrulandı")


def _sifre(con, o, rc, c) -> None:
    hesap = _hesap(con, o["kisi"]) if o["kisi"] else None
    if not hesap:
        return _insana(con, o, "talep eden kişinin hesabı bulunamadı")
    dogru = hesap["sicil"][-3:]
    if "kimlik" not in o["bilgiler"]:
        if not _bekleyen(con, o):
            rnd = random.Random(c["id"])
            yanlis = {f"{rnd.randint(100, 999)}" for _ in range(4)} - {dogru}
            secenek = sorted([dogru] + list(yanlis)[:2])
            _sor(con, o, c, "kimlik", f"Kimliğinizi doğrulamak için sicil numaranızın son üç hanesini seçin. "
                 f"(Demo: doğru cevap {dogru})", secenek)
        return
    if o["bilgiler"]["kimlik"] != dogru:
        _yaz(o, "Otomasyon", "kontrol", "Kimlik doğrulanamadı", "hata")
        return _insana(con, o, "kimlik doğrulanamadı; güvenlik gereği BT ilgilenecek")
    _yaz(o, "Otomasyon", "kontrol", "Kimlik doğrulandı", "ok")
    if not _calistir(o, ["Hesap kilidi açıldı", "Geçici şifre Teams'ten gönderildi; ilk girişte değiştirilecek"], c["id"] * 13):
        return _insana(con, o, "hesap işlemi başarısız")
    hesap["kilitli"] = 0
    _hesap_yaz(con, hesap)
    _basarili(con, o, rc, c, "Kimlik sicil ile doğrulandı\nHesap kilidi açıldı\nGeçici şifre gönderildi")


def _onarim(con, o, rc, c) -> None:
    """Teşhis, sonra adımlar sırayla; her adımdan sonra kontrol. Biri tutarsa dur."""
    t = rc["tanim"]
    rnd = random.Random(c["id"] * 17 + 3)
    # Demo: ortam bozulduysa (sunucu güncellemesi vb.) adımların tutma olasılığı düşer; reçete aynı kalır.
    bozulma = con.execute("SELECT deger FROM meta WHERE anahtar=?", (f"bozulma_{rc['kod']}",)).fetchone()
    carpan = float(bozulma[0]) if bozulma else 1.0
    _yaz(o, "Otomasyon", "kontrol", f"Teşhis: {t['teshis']}", "ok")
    denenen = []
    for eylem, kontrol, p in t["denemeler"]:
        _yaz(o, "Otomasyon", "adim", eylem, "ok")
        tuttu = rnd.random() < p * carpan
        _yaz(o, "Otomasyon", "kontrol", kontrol, "ok" if tuttu else "hata")
        denenen.append(eylem)
        if tuttu:
            if t.get("son_adim"):
                _yaz(o, "Otomasyon", "adim", t["son_adim"], "ok")
            return _basarili(con, o, rc, c, "\n".join(denenen + ([t["son_adim"]] if t.get("son_adim") else [])))
    _insana(con, o, "bilinen adımların hiçbiri sorunu çözmedi. Denenenler: " + "; ".join(denenen))


# ---------------------------------------------------------------- mesaj cevabı

def cevapla(con: sqlite3.Connection, mesaj_id: int, cevap: str) -> dict:
    """Teams mesajına cevap (ziyaretçi talep edeni ya da yöneticiyi oynar)."""
    m = con.execute("SELECT * FROM mesaj WHERE id=?", (mesaj_id,)).fetchone()
    if not m:
        raise ValueError("Mesaj bulunamadı")
    if m["cevap"] is not None:
        raise ValueError("Bu mesaj zaten cevaplandı")
    if m["tur"] == "bilgi":
        raise ValueError("Bilgi mesajı cevap beklemiyor")
    cevap = (cevap or "").strip()
    secenek = json.loads(m["secenekler"])
    if cevap not in secenek and not (m["serbest"] and len(cevap) >= 3):
        raise ValueError("Geçerli bir seçenek seçin" + (" ya da en az 3 harf yazın" if m["serbest"] else ""))
    con.execute("UPDATE mesaj SET cevap=?, cevap_zamani=? WHERE id=?", (cevap[:200], _simdi(), mesaj_id))
    if m["tur"] == "teyit":
        teyit(con, m["cagri_id"], cevap == "Evet, çözüldü")
        con.commit()
        return dict(mesaj_id=mesaj_id, cagri_id=m["cagri_id"])
    o = _oto(con, m["oto_id"])
    rc = _recete(con, o["recete_kod"])
    _yaz(o, m["kime"], "mesaj", f"Cevap: {cevap}", "ok")
    if m["tur"] == "onay":
        o["bilgiler"]["onay"] = cevap
    else:
        o["bilgiler"][m["alan"]] = cevap
    _ilerlet(con, o, rc)
    con.commit()
    return oto_detay(con, o["id"])


# ---------------------------------------------------------------- kapanış, teyit, toplu arıza

def kapat(con: sqlite3.Connection, cagri_id: int, cozen_kisi_id, notu: str, otomatik: bool = False,
          sure_dk: int | None = None, kardes: bool = False) -> None:
    """Otomasyonun çağrı kapatması. İnsanın kapatması usta.cagri_kapat üzerinden olur; ikisi de
    sonunda kapanis_sonrasi() çağırır."""
    c = con.execute("SELECT * FROM cagri WHERE id=?", (cagri_id,)).fetchone()
    if c["durum"] != "acik":
        return
    simdi = datetime.now()
    if sure_dk is None:
        sure_dk = max(1, round((simdi - datetime.fromisoformat(c["acilis"])).total_seconds() / 60))
    con.execute("UPDATE cagri SET durum='kapali', cozen_kisi_id=?, kapanis=?, sure_dk=?, cozum_notu=?, otomatik=?, "
                "teyit=NULL WHERE id=?", (cozen_kisi_id, simdi.isoformat(timespec="minutes"), sure_dk, notu,
                                          int(otomatik), cagri_id))
    con.execute("INSERT INTO cagri_olay(cagri_id,zaman,tur,kisi_id,aciklama) VALUES(?,?,?,?,?)",
                (cagri_id, simdi.isoformat(timespec="minutes"), "kapandi", cozen_kisi_id,
                 "Otomasyonla kapandı" if otomatik else None))
    kapanis_sonrasi(con, cagri_id, notu, cozen_kisi_id, kardes)


def kapanis_sonrasi(con: sqlite3.Connection, cagri_id: int, notu: str | None, cozen_kisi_id=None,
                    kardes: bool = False) -> None:
    """Her kapanıştan sonra: açana teyit sorusu; toplu arızaysa bağlı çağrıları da kapat."""
    c = con.execute("SELECT * FROM cagri WHERE id=?", (cagri_id,)).fetchone()
    if c["acan_kisi"]:
        ozet = (notu or "çözüm notu yazılmadı").split("\n")[0]
        _mesaj(con, None, cagri_id, c["acan_kisi"], "talep_eden", "teyit",
               f"#{cagri_id} numaralı çağrınız kapandı ({ozet}). Sorununuz çözüldü mü?",
               ["Evet, çözüldü", "Hayır, devam ediyor"])
    if c["olay_id"] and not kardes:
        for k in con.execute("SELECT id FROM cagri WHERE olay_id=? AND durum='acik' AND id!=?",
                             (c["olay_id"], cagri_id)).fetchall():
            kapat(con, k["id"], cozen_kisi_id, f"Toplu arıza #{c['olay_id']} kapsamında çözüldü"
                  + (f"\n{notu}" if notu else ""), otomatik=bool(c["otomatik"]), kardes=True)
        con.execute("UPDATE toplu_olay SET durum='kapali' WHERE id=?", (c["olay_id"],))


def teyit(con: sqlite3.Connection, cagri_id: int, cozuldu: bool) -> None:
    c = con.execute("SELECT * FROM cagri WHERE id=?", (cagri_id,)).fetchone()
    if c["durum"] != "kapali":
        return
    if cozuldu:
        con.execute("UPDATE cagri SET teyit=1 WHERE id=?", (cagri_id,))
        return
    # Çözülmedi: çağrı yeniden açılır; o çözüm notu öğrenmeye girmez
    con.execute("UPDATE cagri SET durum='acik', kapanis=NULL, sure_dk=NULL, cozum_notu=NULL, cozen_kisi_id=NULL, "
                "teyit=0, otomatik=0, olay_id=NULL WHERE id=?", (cagri_id,))
    con.execute("INSERT INTO cagri_olay(cagri_id,zaman,tur,kisi_id,aciklama) VALUES(?,?,?,?,?)",
                (cagri_id, _simdi()[:16], "yeniden_acildi", c["atanan_kisi_id"],
                 "Açan kişi çözülmedi dedi. Önceki çözüm: " + (c["cozum_notu"] or "-").replace("\n", " / ")))
    o = con.execute("SELECT * FROM oto WHERE cagri_id=? AND durum='basarili' ORDER BY id DESC", (cagri_id,)).fetchone()
    if o:
        con.execute("UPDATE recete SET teyit_hayir=teyit_hayir+1 WHERE kod=?", (o["recete_kod"],))
        od = _oto(con, o["id"])
        od["durum"] = "tutmadi"
        _yaz(od, c["acan_kisi"] or "Talep eden", "karar", "Kullanıcı çözülmedi dedi; çağrı insana döndü.", "hata")
        _kaydet(con, od)
        saglik_kontrol(con, o["recete_kod"])


def _yer(metin: str) -> str | None:
    k = kucult(metin)
    return next((y for y in K.YERLER if kucult(y) in k), None)


def toplu_kontrol(con: sqlite3.Connection, cagri_id: int, simdi: datetime | None = None) -> dict | None:
    """Aynı konuda (ve aynı yerde) son 60 dakikada 3 ya da daha fazla açık çağrı varsa tek olayda birleştirir."""
    simdi = simdi or datetime.now()
    c = con.execute("SELECT c.*, k.kod AS kategori_kod FROM cagri c JOIN kategori k ON k.id=c.kategori_id WHERE c.id=?",
                    (cagri_id,)).fetchone()
    if c["kategori_kod"] in TOPLU_HARIC:
        return None
    yer = _yer(c["metin"])
    esik = (simdi - timedelta(minutes=TOPLU_PENCERE_DK)).isoformat(timespec="minutes")
    adaylar = [dict(r) for r in con.execute(
        "SELECT * FROM cagri WHERE kaynak='usta' AND durum='acik' AND kategori_id=? AND acilis>=? ORDER BY acilis, id",
        (c["kategori_id"], esik))]
    if yer:
        adaylar = [a for a in adaylar if _yer(a["metin"]) in (yer, None)]
    else:
        # Yer yazılmamışsa yalnızca yer yazılmamış çağrılarla birleşir: farklı yerlerden gelen
        # çağrılar aynı arıza değildir (ör. üç ayrı rampadaki üç ayrı yazıcı).
        adaylar = [a for a in adaylar if _yer(a["metin"]) is None]
    if len({a["acan_kisi"] or f"#{a['id']}" for a in adaylar}) < TOPLU_ESIK:
        return None
    olay_id = next((a["olay_id"] for a in adaylar if a["olay_id"]), None)
    if not olay_id:
        cur = con.execute("INSERT INTO toplu_olay(kategori_id,yer,baslangic) VALUES(?,?,?)",
                          (c["kategori_id"], yer, adaylar[0]["acilis"]))
        olay_id = cur.lastrowid
    ana = adaylar[0]
    for a in adaylar:
        if a["olay_id"] == olay_id:
            continue
        con.execute("UPDATE cagri SET olay_id=? WHERE id=?", (olay_id, a["id"]))
        con.execute("INSERT INTO cagri_olay(cagri_id,zaman,tur,aciklama) VALUES(?,?,?,?)",
                    (a["id"], _simdi()[:16], "toplu_ariza", f"Toplu arıza #{olay_id} ile birleşti (ana çağrı #{ana['id']})"))
        if a["acan_kisi"]:
            _mesaj(con, None, a["id"], a["acan_kisi"], "talep_eden", "bilgi",
                   f"Bildirdiğiniz sorun{(' (' + yer + ')') if yer else ''} başka kişilerce de bildirildi. "
                   f"Tek kayıt altında (#{ana['id']}) çalışılıyor; çözülünce haber vereceğiz.")
    con.commit()
    return dict(olay_id=olay_id, yer=yer, cagri_sayisi=len(adaylar), ana_cagri=ana["id"])


# ---------------------------------------------------------------- notlardan reçete

def recete_adaylari(con: sqlite3.Connection, esik: int = ADAY_ESIK) -> list[dict]:
    """Aynı çözüm notu esik ve üzeri kez tekrar ettiyse reçete adayı. Teyidi 'hayır' olanlar sayılmaz."""
    cevrilen = {r[0] for r in con.execute("SELECT kaynak_not FROM recete WHERE kaynak_not IS NOT NULL")}
    satirlar = con.execute(
        "SELECT c.kategori_id, k.ad AS kategori, k.kod AS kategori_kod, k.temel_sure_dk, c.cozum_notu, COUNT(*) n, "
        "AVG(c.sure_dk) ort, MIN(c.kapanis) ilk, MAX(c.kapanis) son, GROUP_CONCAT(DISTINCT p.ad) kisiler "
        "FROM cagri c JOIN kategori k ON k.id=c.kategori_id LEFT JOIN kisi p ON p.id=c.cozen_kisi_id "
        "WHERE c.kaynak='usta' AND c.durum='kapali' AND c.cozum_notu IS NOT NULL AND c.otomatik=0 "
        "AND COALESCE(c.teyit,1)=1 GROUP BY c.kategori_id, c.cozum_notu HAVING COUNT(*)>=? ORDER BY n DESC", (esik,))
    var = {r[0] for r in con.execute("SELECT kategori_kod FROM recete WHERE tur IN ('talep','onarim')")}
    sonuc = []
    for r in satirlar:
        if r["cozum_notu"] in cevrilen:
            continue
        gun = max(30, (datetime.fromisoformat(r["son"]) - datetime.fromisoformat(r["ilk"])).days)
        ayda = r["n"] / gun * 30
        sonuc.append(dict(kategori_id=r["kategori_id"], kategori=r["kategori"], adimlar=r["cozum_notu"].split("\n"),
                          not_metni=r["cozum_notu"], tekrar=r["n"], ayda=round(ayda, 1),
                          ort_kapanma_dk=round(r["ort"] or 0), kisiler=(r["kisiler"] or "").split(",")[:4],
                          tahmini_saat_ay=round(ayda * r["temel_sure_dk"] / 60, 1),
                          konuda_recete_var=r["kategori_kod"] in var))
    sonuc.sort(key=lambda a: (a["konuda_recete_var"], -a["tekrar"]))
    return sonuc


def recete_olustur(con: sqlite3.Connection, kategori_id: int, not_metni: str, ad: str | None = None) -> dict:
    """Bir çözüm notunu taslak reçeteye çevirir. Taslak çalıştırılmaz; BT adımları sistemlere bağlayınca
    seviyesi yükseltilir. O zamana kadar yalnızca adım adım rehber olarak gösterilir."""
    k = con.execute("SELECT kod, ad FROM kategori WHERE id=? AND kaynak='usta'", (kategori_id,)).fetchone()
    if not k:
        raise ValueError("Konu bulunamadı")
    if con.execute("SELECT 1 FROM recete WHERE kaynak_not=?", (not_metni,)).fetchone():
        raise ValueError("Bu çözüm yolu zaten reçeteye çevrildi")
    n = con.execute("SELECT COUNT(*) FROM cagri WHERE kategori_id=? AND cozum_notu=?", (kategori_id, not_metni)).fetchone()[0]
    if n == 0:
        raise ValueError("Bu çözüm notu geçmiş çağrılarda yok")
    kod = f"T{con.execute('SELECT COUNT(*) FROM recete').fetchone()[0] + 1:03d}"
    adimlar = not_metni.split("\n")
    tanim = dict(aciklama=f"{n} geçmiş çağrıdaki çözüm notundan türetildi. Adımlar henüz sistemlere bağlanmadı.",
                 adimlar=adimlar, arac="Tanımlanmadı (BT)", manuel_dk=None, geri_alma="Tanımlanmadı",
                 bekleyen_is="Her adım için hangi sistemde hangi işlemin çalışacağı ve nasıl doğrulanacağı tanımlanmalı")
    # Taslağın sahibi: bu çözüm yolunu en çok yazan kişi (adımları BT ile o netleştirir)
    sahip = con.execute("SELECT p.ad FROM cagri c JOIN kisi p ON p.id=c.cozen_kisi_id WHERE c.kategori_id=? AND c.cozum_notu=? "
                        "AND p.aktif=1 GROUP BY p.id ORDER BY COUNT(*) DESC LIMIT 1", (kategori_id, not_metni)).fetchone()
    con.execute("INSERT INTO recete(kod,ad,tur,seviye,kategori_kod,tanim,kaynak_not,olusturma,sahip) VALUES(?,?,?,?,?,?,?,?,?)",
                (kod, ad or f"{k['ad']}: {adimlar[0][:50]}", "taslak", "insan", k["kod"], _js(tanim), not_metni, _simdi(),
                 sahip[0] if sahip else None))
    con.commit()
    return _recete(con, kod)


# ---------------------------------------------------------------- işe giriş / çıkış

def ise_giris(con: sqlite3.Connection, ad: str, birim: str, gorev: str) -> dict:
    ad = " ".join(ad.split())
    if len(ad) < 5 or " " not in ad:
        raise ValueError("Ad ve soyad girin")
    if birim not in K.ACAN_KISILER:
        raise ValueError("Birim geçersiz")
    if gorev not in K.GOREV_PAKETLERI:
        raise ValueError("Görev geçersiz")
    eski = _hesap(con, ad)
    if eski and eski["durum"] == "aktif":
        raise ValueError("Bu adla aktif bir hesap zaten var")
    paket = K.GOREV_PAKETLERI[gorev]
    o = dict(cagri_id=None, recete_kod="ISE_GIRIS", kisi=ad, durum="basladi", bilgiler=dict(birim=birim, gorev=gorev),
             gunluk=[], bitis=None)
    o["id"] = con.execute("INSERT INTO oto(recete_kod,kisi,durum,bilgiler,gunluk,baslangic) VALUES(?,?,?,?,?,?)",
                          ("ISE_GIRIS", ad, "basladi", _js(o["bilgiler"]), "[]", _simdi())).lastrowid
    _yaz(o, "İK sistemi", "bilgi", f"İşe giriş kaydı: {ad}, {birim}, {gorev}. Kayıt yetki belgesi sayılır.")
    sicil = f"{20000 + con.execute('SELECT COUNT(*) FROM hesap').fetchone()[0]}"
    cihaz = f"PC-{1500 + con.execute('SELECT COUNT(*) FROM hesap').fetchone()[0]}" if paket["eposta"] else None
    _yaz(o, "Otomasyon", "adim", f"Kullanıcı hesabı açıldı (sicil {sicil})", "ok")
    roller = list(dict.fromkeys([f"{birim} kullanıcısı"] + paket["roller"]))
    _yaz(o, "Otomasyon", "adim", "Roller atandı: " + ", ".join(roller), "ok")
    if paket["terminal"]:
        _yaz(o, "Otomasyon", "adim", "El terminali hesabı açıldı", "ok")
    if paket["eposta"]:
        _yaz(o, "Otomasyon", "adim", f"E-posta kutusu açıldı; {cihaz} bilgisayarı kullanıcıya tanımlandı", "ok")
    kurulan, eksik = [], []
    for y in paket["yazilimlar"]:
        tanim = next(x for x in K.YAZILIM_KATALOGU if x["ad"] == y)
        if tanim["lisans"] is not None:
            l = con.execute("SELECT * FROM lisans WHERE yazilim=?", (y,)).fetchone()
            if l["kullanilan"] >= l["toplam"]:
                eksik.append(y)
                _yaz(o, "Otomasyon", "kontrol", f"{y}: boş lisans yok", "hata")
                continue
            con.execute("UPDATE lisans SET kullanilan=kullanilan+1 WHERE yazilim=?", (y,))
        kurulan.append(y)
        _yaz(o, "Otomasyon", "adim", f"{y} kuruldu", "ok")
    if eksik:
        _yaz(o, "Otomasyon", "karar", "Lisansı olmayan yazılımlar için BT'ye iş açılmalı: " + ", ".join(eksik), "hata")
    if eski:
        con.execute("DELETE FROM hesap WHERE ad=?", (ad,))
    con.execute("INSERT INTO hesap(ad,birim,gorev,sicil,cihaz,roller,yazilimlar) VALUES(?,?,?,?,?,?,?)",
                (ad, birim, gorev, sicil, cihaz, _js(roller), _js(kurulan)))
    yon = K.BIRIM_YONETICI[birim]
    _mesaj(con, o, None, yon, "yonetici", "bilgi",
           f"Yeni çalışanınız {ad} için hesaplar hazır: {', '.join(roller)}"
           + ("; terminal hesabı açıldı" if paket["terminal"] else "") + (f"; yazılımlar: {', '.join(kurulan)}" if kurulan else "")
           + ". İlk giriş bilgileri kendisine iletildi.")
    o["durum"], o["bitis"] = ("basarili" if not eksik else "kismi"), _simdi()
    con.execute("UPDATE recete SET deneme=deneme+1, basari=basari+? WHERE kod='ISE_GIRIS'", (int(not eksik),))
    _kaydet(con, o)
    con.commit()
    return oto_detay(con, o["id"])


def isten_cikis(con: sqlite3.Connection, ad: str) -> dict:
    h = _hesap(con, ad)
    if not h or h["durum"] != "aktif":
        raise ValueError("Aktif hesap bulunamadı")
    o = dict(cagri_id=None, recete_kod="ISTEN_CIKIS", kisi=ad, durum="basladi", bilgiler=dict(birim=h["birim"]),
             gunluk=[], bitis=None)
    o["id"] = con.execute("INSERT INTO oto(recete_kod,kisi,durum,bilgiler,gunluk,baslangic) VALUES(?,?,?,?,?,?)",
                          ("ISTEN_CIKIS", ad, "basladi", _js(o["bilgiler"]), "[]", _simdi())).lastrowid
    _yaz(o, "İK sistemi", "bilgi", f"İşten çıkış kaydı: {ad} ({h['birim']})")
    _yaz(o, "Otomasyon", "adim", "Kullanıcı hesabı ve e-posta kapatıldı (30 gün geri açılabilir)", "ok")
    _yaz(o, "Otomasyon", "adim", "Roller kaldırıldı: " + (", ".join(h["roller"]) or "-"), "ok")
    geri = [y for y in h["yazilimlar"] if next((x for x in K.YAZILIM_KATALOGU if x["ad"] == y and x["lisans"]), None)]
    for y in geri:
        con.execute("UPDATE lisans SET kullanilan=MAX(0,kullanilan-1) WHERE yazilim=?", (y,))
    _yaz(o, "Otomasyon", "adim", "Lisanslar havuza döndü: " + (", ".join(geri) or "lisanslı yazılım yok"), "ok")
    if h["cihaz"]:
        _yaz(o, "Otomasyon", "karar", f"{h['cihaz']} cihazının teslim alınması insana kaldı (fiziksel iş)", "bekliyor")
    h["durum"], h["roller"], h["yazilimlar"] = "kapali", [], []
    _hesap_yaz(con, h)
    _mesaj(con, o, None, K.BIRIM_YONETICI.get(h["birim"], "Birim yöneticisi"), "yonetici", "bilgi",
           f"{ad} için hesaplar kapatıldı, lisanslar geri alındı." + (f" {h['cihaz']} cihazının teslim alınması gerekiyor." if h["cihaz"] else ""))
    o["durum"], o["bitis"] = "basarili", _simdi()
    con.execute("UPDATE recete SET deneme=deneme+1, basari=basari+1 WHERE kod='ISTEN_CIKIS'")
    _kaydet(con, o)
    con.commit()
    return oto_detay(con, o["id"])


# ---------------------------------------------------------------- okuma ve ölçüler

def oto_detay(con: sqlite3.Connection, oto_id: int) -> dict:
    o = _oto(con, oto_id)
    rc = con.execute("SELECT ad, seviye, tur FROM recete WHERE kod=?", (o["recete_kod"],)).fetchone()
    o.update(recete=rc["ad"], seviye=rc["seviye"], tur=rc["tur"])
    o["mesajlar"] = mesajlar(con, oto_id=oto_id)
    if o["cagri_id"]:
        c = con.execute("SELECT metin, durum, teyit FROM cagri WHERE id=?", (o["cagri_id"],)).fetchone()
        o["cagri"] = dict(c)
        o["mesajlar"] += [m for m in mesajlar(con, cagri_id=o["cagri_id"]) if m["oto_id"] is None]
    return o


def mesajlar(con: sqlite3.Connection, oto_id: int | None = None, cagri_id: int | None = None,
             bekleyen: bool = False, limit: int = 50) -> list[dict]:
    kosul, arg = ["1=1"], []
    if oto_id:
        kosul.append("oto_id=?"); arg.append(oto_id)
    if cagri_id:
        kosul.append("cagri_id=?"); arg.append(cagri_id)
    if bekleyen:
        kosul.append("cevap IS NULL AND tur IN ('soru','onay','teyit')")
    arg.append(limit)
    sonuc = []
    for r in con.execute("SELECT * FROM mesaj WHERE " + " AND ".join(kosul) + " ORDER BY id DESC LIMIT ?", arg):
        d = dict(r)
        d["secenekler"] = json.loads(d["secenekler"])
        sonuc.append(d)
    return sonuc[::-1] if (oto_id or cagri_id) else sonuc


def son_calismalar(con: sqlite3.Connection, limit: int = 20) -> list[dict]:
    return [oto_detay(con, r["id"]) for r in con.execute("SELECT id FROM oto ORDER BY id DESC LIMIT ?", (limit,))]


def receteler(con: sqlite3.Connection) -> list[dict]:
    sira = {"talep": 0, "onarim": 1, "paket": 2, "taslak": 3}
    liste = [_recete(con, r["kod"]) for r in con.execute("SELECT kod FROM recete")]
    for r in liste:
        r["seviye_adi"] = SEVIYE_ADI[r["seviye"]]
        r["saglik"] = saglik(con, r["kod"]) if r["tur"] in ("talep", "onarim") else None
    return sorted(liste, key=lambda r: (sira[r["tur"]], r["kod"]))


def _beklenen_basari(rc: dict) -> float:
    if rc["tur"] == "onarim":
        kalan = 1.0
        for _, _, p in rc["tanim"]["denemeler"]:
            kalan *= 1 - p
        return round(1 - kalan, 2)
    return 0.85     # talep: katalog dışı, lisanssız ve reddedilen talepler hariç tutulur


SAGLIK_GUN, SAGLIK_MIN, ASKIYA_MIN, ASKIYA_ORAN, DUSUS_FARK = 30, 5, 8, 0.40, 0.25


def saglik(con: sqlite3.Connection, kod: str, son: str | None = None) -> dict:
    """Reçetenin son 30 gündeki gerçek başarısı ve durumu: yetersiz_veri | iyi | dususte | askida."""
    son = son or _simdi()
    rc = _recete(con, kod)
    bas = (datetime.fromisoformat(son) - timedelta(days=SAGLIK_GUN)).isoformat(timespec="seconds")
    yeniden = rc.get("saglik_bas") or ""
    d = dict(con.execute("SELECT durum, COUNT(*) FROM oto WHERE recete_kod=? AND baslangic>=? AND baslangic>? "
                         "AND baslangic<=? AND durum IN ('basarili','insana_devredildi','tutmadi') GROUP BY durum",
                         (kod, bas, yeniden, son)).fetchall())
    n, ok = sum(d.values()), d.get("basarili", 0)
    beklenen = _beklenen_basari(rc) if rc["tur"] in ("talep", "onarim") else None
    oran = round(ok / n, 2) if n else None
    askida = bool(rc.get("askida")) and (rc.get("askida_zaman") or "") <= son
    kat = con.execute("SELECT emeklilik FROM kategori WHERE kod=?", (rc["kategori_kod"],)).fetchone() if rc["kategori_kod"] else None
    gecersiz = bool(kat and kat[0] and kat[0] <= son)
    if gecersiz:
        durum = "eski_sistem"
    elif askida:
        durum = "askida"
    elif n < SAGLIK_MIN or beklenen is None:
        durum = "yetersiz_veri"
    elif oran < beklenen - DUSUS_FARK:
        durum = "dususte"
    else:
        durum = "iyi"
    metin = {
        "eski_sistem": "Bağlı olduğu konu sistem geçişiyle kapandı; reçete yeni sisteme uyarlanana kadar çalışmaz.",
        "askida": f"Askıda: {rc.get('askida_neden') or ''}",
        "dususte": f"Son {SAGLIK_GUN} günde {n} denemenin {sayi(ok, 'i')} başarılı (%{round((oran or 0) * 100)}); "
                   f"beklenen %{round((beklenen or 0) * 100)}. Bir şey değişmiş olabilir.",
        "iyi": f"Son {SAGLIK_GUN} günde {n} denemenin {sayi(ok, 'i')} başarılı (%{round((oran or 0) * 100)}).",
        "yetersiz_veri": f"Son {SAGLIK_GUN} günde {n} deneme var; ölçmek için en az {SAGLIK_MIN} gerekir." if beklenen is not None else "",
    }[durum]
    return dict(kod=kod, deneme=n, basarili=ok, oran=oran, beklenen=beklenen, durum=durum, metin=metin,
                sahip=rc.get("sahip"),
                kullanilan=(0.0 if askida or gecersiz else (oran if n >= SAGLIK_MIN and oran is not None else beklenen)))


def saglik_kontrol(con: sqlite3.Connection, kod: str, o: dict | None = None) -> dict:
    """Bir çalışma bittikten sonra çağrılır. Başarı çok düştüyse reçeteyi askıya alır."""
    if o is not None and o.get("id"):
        _kaydet(con, o)          # bu çalışmanın sonucu da sayılsın
    s = saglik(con, kod)
    if s["durum"] != "askida" and s["deneme"] >= ASKIYA_MIN and s["oran"] is not None and s["oran"] < ASKIYA_ORAN:
        neden = (f"son {s['deneme']} denemenin yalnızca {sayi(s['basarili'], 'i')} başarılı (%{round(s['oran'] * 100)}); "
                 "yeni çağrılar doğrudan insana gidiyor")
        con.execute("UPDATE recete SET askida=1, askida_neden=?, askida_zaman=? WHERE kod=?", (neden, _simdi(), kod))
        if o is not None:
            _yaz(o, "Otomasyon", "karar", f"Reçete askıya alındı: {neden}.", "hata")
        s = saglik(con, kod)
    return s


def yeniden_devreye_al(con: sqlite3.Connection, kod: str) -> dict:
    """Askıdaki reçeteyi yeniden açar; başarı ölçümü bu andan başlar
    (demoda 'bozulma' senaryosunun etkisini de geri alır: ortam düzeltilmiş sayılır)."""
    rc = _recete(con, kod)
    con.execute("DELETE FROM meta WHERE anahtar=?", (f"bozulma_{kod}",))   # demo: ortam düzeltildi
    con.execute("UPDATE recete SET askida=0, askida_neden=NULL, askida_zaman=NULL, saglik_bas=? WHERE kod=?",
                (_simdi(), kod))
    con.commit()
    return dict(kod=kod, ad=rc["ad"], saglik=saglik(con, kod))


def saglik_uyarilari(con: sqlite3.Connection, son: str | None = None) -> dict[str, list[str]]:
    """Konu kodu → otomasyon sağlık uyarıları (risk haritasının nedenlerine eklenir)."""
    sonuc: dict[str, list[str]] = {}
    for r in con.execute("SELECT kod, ad, kategori_kod FROM recete WHERE tur IN ('talep','onarim') AND olusturma<=?",
                         (son or _simdi(),)):
        s = saglik(con, r["kod"], son)
        if s["durum"] in ("askida", "dususte"):
            sonuc.setdefault(r["kategori_kod"], []).append(
                f"Otomasyon '{r['ad']}' " + ("askıya alındı; risk indirimi geri alındı" if s["durum"] == "askida"
                                             else f"beklenenden kötü çalışıyor (%{round(s['oran'] * 100)})"))
    return sonuc


def otomasyon_paylari(con: sqlite3.Connection, bas: str, son: str) -> dict[str, float]:
    """Konu kodu → otomasyonla insansız kapanması beklenen çağrı payı (risk hesabında kullanılır).
    pay = [bas, son] aralığında reçeteye uyan çağrıların oranı × reçetenin başarısı. Başarı: son 30
    günde en az 5 deneme varsa gerçekleşen, yoksa beklenen. Askıdaki reçete sayılmaz.
    Yalnızca o tarihte var olan, çalıştırılabilir (talep/onarım) reçeteler sayılır."""
    sonuc: dict[str, float] = {}
    for r in con.execute("SELECT kod FROM recete WHERE tur IN ('talep','onarim') AND olusturma<=?", (son,)):
        rc = _recete(con, r["kod"])
        basari = saglik(con, r["kod"], son)["kullanilan"]
        if not basari:
            continue
        t = rc["tanim"]
        metinler = [x[0] for x in con.execute(
            "SELECT c.metin FROM cagri c JOIN kategori k ON k.id=c.kategori_id WHERE k.kod=? AND c.durum='kapali' "
            "AND c.kapanis>=? AND c.kapanis<=?", (rc["kategori_kod"], bas, son))]
        if not metinler:
            continue
        uyan = 0
        for m in metinler:
            m = kucult(m)
            if t.get("ifadeler") and not any(kucult(i) in m for i in t["ifadeler"]):
                continue
            if any(kucult(h) in m for h in t.get("haric", [])):
                continue
            uyan += 1
        pay = uyan / len(metinler) * basari
        sonuc[rc["kategori_kod"]] = round(min(0.95, sonuc.get(rc["kategori_kod"], 0) + pay), 3)
    return sonuc


def potansiyel(con: sqlite3.Connection, gun: int = 180) -> dict:
    """Geçmiş çağrılara reçeteleri uygular: bu reçeteler olsaydı ayda kaç çağrı ve kaç saat insansız kapanırdı?
    Kazanç, konunun temel çözüm süresinden (iş yükü) hesaplanır; bekleme süresi ayrıca gösterilir."""
    esik = (datetime.now() - timedelta(days=gun)).isoformat(timespec="minutes")
    satirlar = []
    for r in con.execute("SELECT kod FROM recete WHERE tur IN ('talep','onarim')"):
        rc = _recete(con, r["kod"])
        k = con.execute("SELECT id, temel_sure_dk FROM kategori WHERE kod=?", (rc["kategori_kod"],)).fetchone()
        if not k:
            continue
        t = rc["tanim"]
        eslesen = []
        for c in con.execute("SELECT metin, sure_dk FROM cagri WHERE kaynak='usta' AND durum='kapali' AND otomatik=0 "
                             "AND kategori_id=? AND kapanis>=?", (k["id"], esik)):
            m = kucult(c["metin"])
            if t.get("ifadeler") and not any(kucult(i) in m for i in t["ifadeler"]):
                continue
            if any(kucult(h) in m for h in t.get("haric", [])):
                continue
            eslesen.append(c["sure_dk"])
        if not eslesen:
            continue
        ayda = len(eslesen) / gun * 30
        oran = _beklenen_basari(rc)
        satirlar.append(dict(kod=rc["kod"], ad=rc["ad"], seviye=rc["seviye"], seviye_adi=SEVIYE_ADI[rc["seviye"]],
                             cagri=len(eslesen), ayda=round(ayda, 1), basari_beklentisi=oran,
                             ort_kapanma_dk=round(sum(x for x in eslesen if x) / max(1, sum(1 for x in eslesen if x))),
                             kazanc_saat_ay=round(ayda * oran * (t.get("manuel_dk") or k["temel_sure_dk"]) / 60, 1)))
    satirlar.sort(key=lambda s: -s["kazanc_saat_ay"])
    toplam = con.execute("SELECT COUNT(*) FROM cagri WHERE kaynak='usta' AND durum='kapali' AND kapanis>=?",
                         (esik,)).fetchone()[0]
    return dict(gun=gun, satirlar=satirlar, toplam_cagri=toplam,
                kapsanan_oran=round(sum(s["cagri"] for s in satirlar) / max(1, toplam), 3),
                insansiz_oran=round(sum(s["cagri"] * s["basari_beklentisi"] for s in satirlar) / max(1, toplam), 3),
                kazanc_saat_ay=round(sum(s["kazanc_saat_ay"] for s in satirlar), 1))


def ozet(con: sqlite3.Connection) -> dict:
    d = dict(con.execute("SELECT durum, COUNT(*) FROM oto GROUP BY durum").fetchall())
    return dict(calisma=sum(d.values()), basarili=d.get("basarili", 0), bekleyen=d.get("bilgi_bekliyor", 0) + d.get("onay_bekliyor", 0),
                insana=d.get("insana_devredildi", 0), tutmadi=d.get("tutmadi", 0), reddedildi=d.get("reddedildi", 0),
                bekleyen_mesaj=con.execute("SELECT COUNT(*) FROM mesaj WHERE cevap IS NULL AND tur IN ('soru','onay','teyit')").fetchone()[0],
                toplu_olay=con.execute("SELECT COUNT(*) FROM toplu_olay WHERE durum='acik'").fetchone()[0])


# ---------------------------------------------------------------- demo senaryoları

def senaryo(con: sqlite3.Connection, ad: str) -> dict:
    """Demo için hazır çağrılar. Talep eden, gerçek bir hesabı olan kurgusal bir kişidir."""
    from . import usta
    hesaplar = [dict(r) for r in con.execute("SELECT * FROM hesap WHERE durum='aktif' ORDER BY ad")]
    rnd = random.Random()
    h = rnd.choice(hesaplar)
    ozel = {
        "kurulum_eksik": ("Bilgisayarıma BarTender kurulabilir mi? Etiket şablonu hazırlayacağım.", 2),
        "kurulum_hizli": (f"Power BI kurulumu gerekiyor, bilgisayarım {h['cihaz']}.", 1),
        "kurulum_lisanssiz": (f"Acrobat lazım, PDF düzenleyeceğim. Bilgisayarım {h['cihaz']}.", 1),
        "kurulum_katalog_disi": (f"AutoCAD kurulumu gerekiyor, bilgisayarım {h['cihaz']}.", 1),
        "yetki": ("WMS'te sayım onaylayıcı yetkim yok, tanımlanabilir mi?", 2),
        "sifre": ("Hesabım kilitlendi, şifremi de unuttum.", 2),
        "yazici": ("Yazıcı çevrimdışı görünüyor, etiket basmıyor.", 3),
        "rapor": ("Günlük verimlilik raporu bu sabah gelmedi.", 2),
        "terminal": ("El terminali ağa bağlanmıyor, Wi-Fi simgesi çarpı gösteriyor.", 3),
    }
    if ad == "toplu":
        sonuc = []
        for i, kisi in enumerate(rnd.sample(hesaplar, 3)):
            metin = ["B koridoru bölgesinde kablosuz ağ sürekli kopuyor.", "Wi-Fi çekmiyor, tüm cihazlar düştü, B koridoru.",
                     "B koridoru tarafında kablosuz ağ hiç görünmüyor."][i]
            sonuc.append(usta.cagri_ac(con, metin, kisi["birim"], 3, acan_kisi=kisi["ad"]))
        return dict(senaryo=ad, cagrilar=[dict(id=c["id"], olay=c.get("toplu")) for c in sonuc], cagri_id=sonuc[-1]["id"])
    if ad == "bozulma":
        return _bozulma(con, hesaplar, rnd)
    if ad not in ozel:
        raise ValueError("Bilinmeyen senaryo")
    metin, acil = ozel[ad]
    c = usta.cagri_ac(con, metin, h["birim"], acil, acan_kisi=h["ad"])
    return dict(senaryo=ad, cagri_id=c["id"], oto=c.get("otomasyon"))


def _bozulma(con, hesaplar: list[dict], rnd: random.Random) -> dict:
    """DEMO: yazdırma sunucusuna güncelleme geldi, yazıcı reçetesinin adımları artık pek tutmuyor.
    Sekiz yazıcı çağrısı açılır; otomasyon çoğunda başarısız olur ve reçete kendiliğinden askıya alınır."""
    from . import usta
    rc = _recete(con, "YAZICI")
    if rc["askida"]:
        raise ValueError("Yazıcı reçetesi zaten askıda. Önce yeniden devreye alın.")
    con.execute("INSERT OR REPLACE INTO meta(anahtar,deger) VALUES('bozulma_YAZICI','0.15')")
    kat = con.execute("SELECT id FROM kategori WHERE kod='ETIKET_YAZICI'").fetchone()[0]
    metinler = ["{y} yazıcısı çevrimdışı görünüyor, etiket basmıyor.", "{y} etiket yazıcısında kuyruk takıldı.",
                "{y} yazıcısı ağdan düştü, basmıyor.", "Yazıcı {y} çevrimdışı, sevkiyat etiketleri çıkmıyor.",
                "{y} yazıcısında baskı kuyrukta bekliyor.", "{y} yazıcısı basmıyor, çevrimdışı yazıyor.",
                "Etiket yazıcısı ({y}) kuyruk hatası veriyor.", "{y} yazıcısı yine çevrimdışı."]
    sonuc = []
    for m, yer in zip(metinler, rnd.sample(K.YERLER, len(metinler))):   # farklı yerler: toplu arıza değil
        h = rnd.choice(hesaplar)
        c = usta.cagri_ac(con, m.format(y=yer), h["birim"], 2, kategori_id=kat, acan_kisi=h["ad"])
        sonuc.append(c["id"])
    return dict(senaryo="bozulma", cagrilar=sonuc, cagri_id=sonuc[-1], saglik=saglik(con, "YAZICI"))
