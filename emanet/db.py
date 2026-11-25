"""Veritabanı katmanı: şema ve bağlantı.

Usta, Emanet ve otomasyon tabloları birlikte durur. Emanet'in kendine ait ham verisi yoktur; her şeyi
çağrı kayıtlarından (cagri, cagri_olay, cozum_karti) türetir.

cagri tablosunda iki kaynak birlikte durur:
  kaynak='usta'  : Usta'da açılıp kapanan sistemsel çağrılar (metni ve çözüm notu var)
  başka bir ad   : içe aktarılan teknik dökümler (yalnızca konu, çözen, tarih, süre)
"""
from __future__ import annotations

import os
import sqlite3
from pathlib import Path

DB_YOLU = Path(os.environ.get("EMANET_DB", Path(__file__).resolve().parent.parent / "veri" / "emanet.db"))

SEMA = """
CREATE TABLE IF NOT EXISTS meta (
    anahtar TEXT PRIMARY KEY,
    deger   TEXT NOT NULL
);

-- Çağrıyı çözen birimler (BT Destek, Bakım ...)
CREATE TABLE IF NOT EXISTS birim (
    id  INTEGER PRIMARY KEY,
    ad  TEXT NOT NULL UNIQUE
);

-- Çağrı çözen kişiler
CREATE TABLE IF NOT EXISTS kisi (
    id       INTEGER PRIMARY KEY,
    ad       TEXT NOT NULL,
    birim_id INTEGER NOT NULL REFERENCES birim(id),
    rol      TEXT NOT NULL,
    vardiya  TEXT NOT NULL CHECK (vardiya IN ('gunduz','aksam','gece')),
    aktif    INTEGER NOT NULL DEFAULT 1,
    ise_giris TEXT,          -- YYYY-MM-DD; NULL = eskiden beri çalışıyor
    cikis     TEXT           -- ayrıldıysa YYYY-MM-DD (aktif=0 ile birlikte)
);

-- İzin / rapor kayıtları (tarih aralığı)
CREATE TABLE IF NOT EXISTS musaitlik (
    id        INTEGER PRIMARY KEY,
    kisi_id   INTEGER NOT NULL REFERENCES kisi(id),
    baslangic TEXT NOT NULL,   -- YYYY-MM-DD
    bitis     TEXT NOT NULL,   -- YYYY-MM-DD (dahil)
    tur       TEXT NOT NULL    -- izin | rapor
);

-- Konu ağacı. Usta'nın konuları (kaynak='usta') ve içe aktarılan dökümlerin konuları
CREATE TABLE IF NOT EXISTS kategori (
    id                 INTEGER PRIMARY KEY,
    kod                TEXT NOT NULL UNIQUE,
    ad                 TEXT NOT NULL,
    birim_id           INTEGER NOT NULL REFERENCES birim(id),
    kritiklik          INTEGER NOT NULL CHECK (kritiklik BETWEEN 1 AND 3),
    anahtar_kelimeler  TEXT NOT NULL,     -- virgülle ayrılmış
    aciklama           TEXT NOT NULL,     -- netleştirme sorusunda gösterilir
    ogrenme_saati      INTEGER NOT NULL,  -- bir kişinin konuyu öğrenmesi için saat
    temel_sure_dk      INTEGER NOT NULL,  -- deneyimli kişinin ortalama çözüm süresi
    kaynak             TEXT NOT NULL DEFAULT 'usta',  -- usta | içe aktarılan dökümün adı
    talimat_var        INTEGER NOT NULL DEFAULT 0,    -- dökümde "yazılı talimat var" işareti
    acilis             TEXT,          -- konu bu tarihte başladıysa (yeni sistem); NULL = baştan beri var
    emeklilik          TEXT,          -- konu bu tarihte kapandıysa (eski sistem); NULL = hâlâ geçerli
    kart_saat          REAL,          -- çözüm kartını yazma süresi (saat); NULL = girilmedi, varsayılan kullanılır
    sure_onay          INTEGER NOT NULL DEFAULT 0  -- 1 = kart ve öğretme sürelerini kullanıcı girdi; 0 = tahmin
);

CREATE TABLE IF NOT EXISTS cagri (
    id               INTEGER PRIMARY KEY,
    metin            TEXT NOT NULL,
    acan_birim       TEXT NOT NULL,
    aciliyet         INTEGER NOT NULL CHECK (aciliyet BETWEEN 1 AND 3),
    kategori_id      INTEGER NOT NULL REFERENCES kategori(id),
    onerilen_kategori_id INTEGER REFERENCES kategori(id), -- sistemin ilk önerisi
    guven            REAL,
    durum            TEXT NOT NULL CHECK (durum IN ('acik','kapali')),
    atanan_kisi_id   INTEGER REFERENCES kisi(id),
    cozen_kisi_id    INTEGER REFERENCES kisi(id),
    acilis           TEXT NOT NULL,   -- ISO tarih-saat
    kapanis          TEXT,
    sure_dk          INTEGER,
    kart_id          INTEGER REFERENCES cozum_karti(id), -- çözümde kullanılan kart
    yeniden_atama    INTEGER NOT NULL DEFAULT 0,
    vardiya          TEXT,            -- çağrının açıldığı vardiya
    cozum_notu       TEXT,            -- "nasıl çözdün?" (satır satır adımlar)
    kaynak           TEXT NOT NULL DEFAULT 'usta',  -- usta | içe aktarılan dökümün adı
    acan_kisi        TEXT,            -- çağrıyı açan kişi (Teams mesajlarının alıcısı)
    olay_id          INTEGER REFERENCES toplu_olay(id),  -- toplu arızaya bağlandıysa
    otomatik         INTEGER NOT NULL DEFAULT 0,         -- otomasyonla kapandıysa 1
    teyit            INTEGER          -- kapanış teyidi: 1 çözüldü, 0 çözülmedi, NULL cevap yok
);
CREATE INDEX IF NOT EXISTS ix_cagri_kat ON cagri(kategori_id, durum);
CREATE INDEX IF NOT EXISTS ix_cagri_cozen ON cagri(cozen_kisi_id);
-- Cihaz envanteri (yazıcı, el terminali…). Gerçekte demirbaş sisteminden CSV ile gelir; numara etikettir.
CREATE TABLE IF NOT EXISTS cihaz (
    no        TEXT PRIMARY KEY,          -- tek biçimde: YZ-07, EL-014
    tur       TEXT NOT NULL,             -- yazici | terminal | diğer
    model     TEXT,
    yer       TEXT,
    seri_no   TEXT,
    durum     TEXT NOT NULL DEFAULT 'aktif',   -- aktif | hurda
    guncelleme TEXT
);
CREATE INDEX IF NOT EXISTS ix_cagri_kaynak ON cagri(kaynak, durum);

-- Çağrının geçmişi: açılış, atama, yeniden atama, kapanış
CREATE TABLE IF NOT EXISTS cagri_olay (
    id        INTEGER PRIMARY KEY,
    cagri_id  INTEGER NOT NULL REFERENCES cagri(id),
    zaman     TEXT NOT NULL,
    tur       TEXT NOT NULL,   -- acildi | atandi | yeniden_atandi | kapandi
    kisi_id   INTEGER REFERENCES kisi(id),
    aciklama  TEXT
);

CREATE TABLE IF NOT EXISTS cozum_karti (
    id           INTEGER PRIMARY KEY,
    kategori_id  INTEGER NOT NULL REFERENCES kategori(id),
    baslik       TEXT NOT NULL,
    adimlar      TEXT NOT NULL,   -- satır satır
    kok_neden    TEXT,
    yazan_kisi_id INTEGER REFERENCES kisi(id),
    olusturma    TEXT NOT NULL
);

-- Kâğıt üzerindeki "kim neyi yapabilir"
CREATE TABLE IF NOT EXISTS yetkinlik_beyan (
    kisi_id     INTEGER NOT NULL REFERENCES kisi(id),
    kategori_id INTEGER NOT NULL REFERENCES kategori(id),
    PRIMARY KEY (kisi_id, kategori_id)
);

-- ---------------------------------------------------------------- otomasyon
-- Talep eden kişilerin hesapları (kurgusal kimlik sistemi): cihaz, roller, kurulu yazılımlar
CREATE TABLE IF NOT EXISTS hesap (
    ad         TEXT PRIMARY KEY,
    birim      TEXT NOT NULL,
    gorev      TEXT NOT NULL,
    sicil      TEXT NOT NULL,
    cihaz      TEXT,
    roller     TEXT NOT NULL DEFAULT '[]',   -- JSON liste
    yazilimlar TEXT NOT NULL DEFAULT '[]',   -- JSON liste
    durum      TEXT NOT NULL DEFAULT 'aktif',
    kilitli    INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS lisans (
    yazilim    TEXT PRIMARY KEY,
    toplam     INTEGER NOT NULL,
    kullanilan INTEGER NOT NULL
);

-- Otomasyon reçeteleri. tanim: adımlar, gereken bilgiler vb. (JSON)
CREATE TABLE IF NOT EXISTS recete (
    kod        TEXT PRIMARY KEY,
    ad         TEXT NOT NULL,
    tur        TEXT NOT NULL,      -- talep | onarim | paket | taslak
    seviye     TEXT NOT NULL,      -- otomatik | onayli | insan
    kategori_kod TEXT,
    tanim      TEXT NOT NULL,
    deneme     INTEGER NOT NULL DEFAULT 0,
    basari     INTEGER NOT NULL DEFAULT 0,   -- otomasyon kendi doğrulamasıyla başardı
    teyit_hayir INTEGER NOT NULL DEFAULT 0,  -- kullanıcı "çözülmedi" dedi
    kaynak_not TEXT,                         -- notlardan türetildiyse kaynağı
    olusturma  TEXT NOT NULL,
    askida     INTEGER NOT NULL DEFAULT 0,   -- başarısı düştüğü için otomatik durduruldu
    askida_neden TEXT,
    askida_zaman TEXT,
    saglik_bas TEXT,                         -- başarı ölçümü bu andan itibaren (yeniden devreye alınınca)
    sahip      TEXT                          -- reçetenin bakımını yapan kişi (bozulursa düzelten)
);

-- Bir otomasyon çalışması
CREATE TABLE IF NOT EXISTS oto (
    id         INTEGER PRIMARY KEY,
    cagri_id   INTEGER REFERENCES cagri(id),
    recete_kod TEXT NOT NULL REFERENCES recete(kod),
    kisi       TEXT,              -- talep eden ya da işe giren/çıkan kişi
    durum      TEXT NOT NULL,     -- bilgi_bekliyor | onay_bekliyor | basarili | insana_devredildi | reddedildi
    bilgiler   TEXT NOT NULL DEFAULT '{}',
    gunluk     TEXT NOT NULL DEFAULT '[]',
    baslangic  TEXT NOT NULL,
    bitis      TEXT
);

-- Teams benzeri mesajlar
CREATE TABLE IF NOT EXISTS mesaj (
    id         INTEGER PRIMARY KEY,
    oto_id     INTEGER REFERENCES oto(id),
    cagri_id   INTEGER REFERENCES cagri(id),
    kime       TEXT NOT NULL,
    rol        TEXT NOT NULL,     -- talep_eden | yonetici
    tur        TEXT NOT NULL,     -- soru | onay | bilgi | teyit
    alan       TEXT,              -- sorunun doldurduğu bilgi alanı
    metin      TEXT NOT NULL,
    secenekler TEXT NOT NULL DEFAULT '[]',
    serbest    INTEGER NOT NULL DEFAULT 0,  -- serbest metin cevabı kabul eder mi
    cevap      TEXT,
    zaman      TEXT NOT NULL,
    cevap_zamani TEXT
);

CREATE TABLE IF NOT EXISTS toplu_olay (
    id          INTEGER PRIMARY KEY,
    kategori_id INTEGER NOT NULL REFERENCES kategori(id),
    yer         TEXT,
    baslangic   TEXT NOT NULL,
    durum       TEXT NOT NULL DEFAULT 'acik'
);

-- Sistem geçişi: eski konu kapanır, yerine yeni konu açılır (ör. eski rapor küpü → Power BI)
CREATE TABLE IF NOT EXISTS gecis (
    id               INTEGER PRIMARY KEY,
    eski_kategori_id INTEGER REFERENCES kategori(id),   -- NULL: öncülü olmayan yeni sistem
    yeni_kategori_id INTEGER NOT NULL REFERENCES kategori(id),
    tarih            TEXT NOT NULL,          -- YYYY-MM-DD, geçiş günü
    aciklama         TEXT,
    anahtar_kisiler  TEXT NOT NULL DEFAULT '[]',  -- JSON: kurulumu yapan / eğitimi alan anahtar kullanıcılar
    olusturma        TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS devir (
    id           INTEGER PRIMARY KEY,
    kisi_id      INTEGER NOT NULL REFERENCES kisi(id),   -- ayrılan (ya da uzun süre olmayacak) kişi
    cikis_tarihi TEXT NOT NULL,                          -- son çalışma günü
    baslangic    TEXT NOT NULL,                          -- devrin başladığı an; ilerleme bundan sonraki çağrılarla ölçülür
    durum        TEXT NOT NULL DEFAULT 'acik',           -- acik | tamam | iptal
    haftalik_sinir REAL NOT NULL DEFAULT 4,              -- devir oturumları için kişi başı haftalık saat
    gorusme      TEXT NOT NULL DEFAULT '{}'              -- bilgi aktarım görüşmesi: {soru_no: cevap}
);
CREATE TABLE IF NOT EXISTS devir_konu (
    devir_id     INTEGER NOT NULL REFERENCES devir(id),
    kategori_id  INTEGER NOT NULL REFERENCES kategori(id),
    devralan_id  INTEGER REFERENCES kisi(id),
    izledi       INTEGER NOT NULL DEFAULT 0,             -- 1. aşama: devralan ustanın çözümünü en az bir kez izledi
    PRIMARY KEY (devir_id, kategori_id)
);
CREATE TABLE IF NOT EXISTS devir_madde (
    devir_id     INTEGER NOT NULL REFERENCES devir(id),
    kod          TEXT NOT NULL,                          -- elle işaretlenen kontrol maddesi
    yapildi      INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY (devir_id, kod)
);
CREATE TABLE IF NOT EXISTS egitim_plani (
    id           INTEGER PRIMARY KEY,
    kategori_id  INTEGER NOT NULL REFERENCES kategori(id),
    tur          TEXT NOT NULL,   -- egitim | kart
    ogreten_id   INTEGER REFERENCES kisi(id),
    ogrenen_id   INTEGER REFERENCES kisi(id),
    saat         INTEGER NOT NULL,
    durum        TEXT NOT NULL DEFAULT 'planlandi',
    olusturma    TEXT NOT NULL,
    puan_once    INTEGER,         -- plan kaydedilirken konunun risk puanı
    puan_hedef   INTEGER          -- plan uygulanırsa beklenen puan
);
"""

TABLOLAR = ["cihaz", "devir_madde", "devir_konu", "devir", "mesaj", "oto", "recete", "lisans", "hesap", "egitim_plani", "gecis", "yetkinlik_beyan", "cagri_olay", "cagri", "toplu_olay", "cozum_karti",
            "kategori", "musaitlik", "kisi", "birim", "meta"]


def baglan(yol: Path | str | None = None) -> sqlite3.Connection:
    """Veritabanına bağlanır. yol=':memory:' geçici, bellekte bir veritabanı açar."""
    if yol == ":memory:":
        con = sqlite3.connect(":memory:", check_same_thread=False)
    else:
        yol = Path(yol) if yol else DB_YOLU
        yol.parent.mkdir(parents=True, exist_ok=True)
        con = sqlite3.connect(yol, check_same_thread=False)
    con.row_factory = sqlite3.Row
    con.execute("PRAGMA foreign_keys = ON")
    con.executescript(SEMA)
    _gocler(con)
    return con


# Eski bir veritabanı açılırsa sonradan eklenen sütunlar eklenir (veri silinmez).
GOCLER = {
    "kategori": [("acilis", "TEXT"), ("emeklilik", "TEXT"), ("kart_saat", "REAL"),
                 ("sure_onay", "INTEGER NOT NULL DEFAULT 0")],
    "kisi": [("ise_giris", "TEXT"), ("cikis", "TEXT")],
    "cagri": [("yer", "TEXT"), ("ek_bilgi", "TEXT"), ("cihaz", "TEXT"),
              ("asama", "TEXT")],   # çağrı durumu: acik | atandi | islemde | bilgi_bekleniyor | cozuldu | kapali   # cihaz: etiket no, tekrarlayan arıza izlenir
    "devir": [("devralan_sinir", "REAL NOT NULL DEFAULT 4")],   # devralanların haftalık devir saati (ayrılanınkinden ayrı)   # iki aşamalı form: yer ve konuya özel cevaplar (JSON)
    "recete": [("askida", "INTEGER NOT NULL DEFAULT 0"), ("askida_neden", "TEXT"), ("askida_zaman", "TEXT"),
               ("saglik_bas", "TEXT"), ("sahip", "TEXT")],
}


def _gocler(con: sqlite3.Connection) -> None:
    for tablo, sutunlar in GOCLER.items():
        var = {r[1] for r in con.execute(f"PRAGMA table_info({tablo})")}
        for ad, tip in sutunlar:
            if ad not in var:
                con.execute(f"ALTER TABLE {tablo} ADD COLUMN {ad} {tip}")
    con.execute("CREATE INDEX IF NOT EXISTS ix_cagri_cihaz ON cagri(cihaz, acilis)")
    # Durumu verilmeden eklenen çağrı (döküm, eski kod yolları) durumunu kaba duruma göre alır
    con.execute("UPDATE cagri SET asama = CASE WHEN durum='kapali' THEN 'kapali' WHEN atanan_kisi_id IS NULL THEN 'acik' "
                "ELSE 'atandi' END WHERE asama IS NULL")
    con.execute("CREATE TRIGGER IF NOT EXISTS cagri_asama AFTER INSERT ON cagri WHEN NEW.asama IS NULL BEGIN "
                "UPDATE cagri SET asama = CASE WHEN NEW.durum='kapali' THEN 'kapali' WHEN NEW.atanan_kisi_id IS NULL "
                "THEN 'acik' ELSE 'atandi' END WHERE id=NEW.id; END")
    con.commit()


def bosalt(con: sqlite3.Connection) -> None:
    """Tüm tabloları boşaltır (demo sıfırlama)."""
    con.execute("PRAGMA foreign_keys = OFF")
    for t in TABLOLAR:
        con.execute(f"DELETE FROM {t}")
    con.execute("PRAGMA foreign_keys = ON")
    con.commit()


def meta_al(con: sqlite3.Connection, anahtar: str, varsayilan: str | None = None) -> str | None:
    r = con.execute("SELECT deger FROM meta WHERE anahtar=?", (anahtar,)).fetchone()
    return r["deger"] if r else varsayilan


def meta_yaz(con: sqlite3.Connection, anahtar: str, deger: str) -> None:
    con.execute("INSERT INTO meta(anahtar,deger) VALUES(?,?) "
                "ON CONFLICT(anahtar) DO UPDATE SET deger=excluded.deger", (anahtar, deger))
    con.commit()
