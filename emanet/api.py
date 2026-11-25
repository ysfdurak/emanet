"""Web API. Çekirdek fonksiyonları (usta.py, risk.py) HTTP üzerinden açar.

Çalıştırma:  python -m emanet   (bkz. __main__.py; vekil başlıklarını uvicorn değil gercek_ip.py yorumlar)
"""
from __future__ import annotations

import contextlib
import contextvars
import hashlib
import hmac
import json
import logging
import os
import re
import secrets
import sqlite3
import time
from collections import OrderedDict, defaultdict, deque
from datetime import date
from http.cookies import SimpleCookie
from pathlib import Path
from urllib.parse import urlsplit

from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.responses import FileResponse, JSONResponse, PlainTextResponse
from pydantic import BaseModel, Field

from . import __version__, degisim, egitim, ice_aktar, katalog, ogrenme, otomasyon, risk, takip, takvim, usta, veri_uret
from . import mcp_sunucu
from .db import DB_YOLU, baglan, meta_al
from .gercek_ip import gercek_ip
from . import devir as devir_surec
from . import cagri_formu, olcum

WEB = Path(__file__).resolve().parent.parent / "web"
log = logging.getLogger("emanet")

# --- Sınırlar ve ayarlar (ortam değişkenleri) -----------------------------------------------------------
YAZMA_SINIRI = int(os.environ.get("EMANET_ISTEK_SINIRI", "40"))      # IP başına dakikada yazma (POST) isteği
OKUMA_SINIRI = int(os.environ.get("EMANET_OKUMA_SINIRI", "300"))     # IP başına dakikada tüm /api istekleri
MCP_SINIRI = 60                                                       # IP başına dakikada MCP isteği
GOVDE_SINIRI = 2_200_000                                              # bayt (en büyük gövde: 2 MB döküm CSV'si)
MCP_ANAHTARLARI = [a.strip() for a in os.environ.get("EMANET_MCP_ANAHTARLARI", "").split(",") if len(a.strip()) >= 24]
MCP_ACIK = os.environ.get("EMANET_MCP", "1") == "1"
ZIYARETCI_ACIK = os.environ.get("EMANET_ZIYARETCI", "1") == "1"
GUVENLI_CEREZ = os.environ.get("EMANET_GUVENLI_CEREZ", "1") == "1"   # yalnız yerel http testinde 0

# Her yanıtta tarayıcı korumaları. HTML sayfası kendi dosyalarından betik ve stil yükler (satır içi betik yok);
# satır içi style="" öznitelikleri için style-src 'unsafe-inline' gerekir (betik çalıştırmaz).
# Ortak ölçüm servisi (olcum.ysfdurak.com): yalnız betik ve olay gönderimi; betik yalnız resmî adreste yüklenir (web/app.js).
CSP_SAYFA = ("default-src 'self'; script-src 'self' https://olcum.ysfdurak.com; style-src 'self' 'unsafe-inline'; img-src 'self' data:; "
             "connect-src 'self' https://olcum.ysfdurak.com; font-src 'self'; object-src 'none'; base-uri 'self'; form-action 'self'; "
             "frame-ancestors 'none'")
BASLIKLAR = [
    (b"x-content-type-options", b"nosniff"),
    (b"strict-transport-security", b"max-age=31536000"),
    (b"referrer-policy", b"strict-origin-when-cross-origin"),
    (b"x-frame-options", b"DENY"),
    (b"cross-origin-opener-policy", b"same-origin"),
    (b"permissions-policy", b"camera=(), microphone=(), geolocation=(), payment=(), usb=()"),
]

ana_con = baglan()
KILIT = mcp_sunucu.KILIT
mcp_sunucu.baglanti_ayarla(ana_con)     # MCP (anahtarla) ortak demo verisiyle çalışır

# --- Etkin bağlantı: istek sırasında ziyaretçinin kendi kopyası, yoksa ortak demo ------------------------
_etkin: contextvars.ContextVar = contextvars.ContextVar("emanet_baglanti")


class _EtkinBaglanti:
    """Uç fonksiyonları `con` adını kullanır; bu nesne her istekte o isteğin veritabanına yönlenir."""
    def __getattr__(self, ad):
        return getattr(_etkin.get(ana_con), ad)


con = _EtkinBaglanti()


def yerel_mi() -> bool:
    """Kendi verisiyle kurulmuş (python -m emanet.yerel) veritabanı mı? O zaman demo verisi üretilmez."""
    return meta_al(ana_con, "mod") == "yerel"


class Ziyaretciler:
    """Ziyaretçi demosu: her ziyaretçi ilk yazma isteğinde ortak demonun kendine ait bir kopyasını alır
    (çerezle tanınır). Ziyaretçiler birbirinin çağrılarını, notlarını görmez. Okuma istekleri kopya yoksa
    ortak demoya gider (yalnız okunur). Kopyalar 24 saat yaşar, gece sıfırlamasında hepsi silinir;
    en çok EN_FAZLA kopya, IP başına günde GUNLUK_IP yeni kopya."""
    EN_FAZLA = 300
    GUNLUK_IP = 20
    OMUR_SN = 24 * 3600
    ACIK_BAGLANTI = 40

    def __init__(self, dizin: Path):
        self.dizin = dizin
        self.baglantilar: OrderedDict = OrderedDict()
        self.ip_sayac: dict[str, int] = defaultdict(int)
        self.ip_gun = date.today()

    def _yol(self, zid: str) -> Path:
        return self.dizin / f"{zid}.db"

    def var(self, zid: str) -> bool:
        return self._yol(zid).exists()

    def baglanti(self, zid: str):
        if zid in self.baglantilar:
            self.baglantilar.move_to_end(zid)
            return self.baglantilar[zid]
        c = baglan(self._yol(zid))
        self.baglantilar[zid] = c
        while len(self.baglantilar) > self.ACIK_BAGLANTI:
            self.baglantilar.popitem(last=False)[1].close()
        return c

    def olustur(self, zid: str, ip: str) -> bool:
        if date.today() != self.ip_gun:
            self.ip_sayac.clear()
            self.ip_gun = date.today()
        if self.ip_sayac[ip] >= self.GUNLUK_IP:
            return False
        self.ip_sayac[ip] += 1
        self.dizin.mkdir(parents=True, exist_ok=True)
        self._budama()
        hedef = sqlite3.connect(self._yol(zid))
        ana_con.backup(hedef)
        hedef.close()
        return True

    def sil(self, zid: str) -> None:
        c = self.baglantilar.pop(zid, None)
        if c:
            c.close()
        self._yol(zid).unlink(missing_ok=True)

    def _budama(self) -> None:
        dosyalar = sorted(self.dizin.glob("*.db"), key=lambda p: p.stat().st_mtime)
        simdi = time.time()
        for i, p in enumerate(dosyalar):
            if simdi - p.stat().st_mtime > self.OMUR_SN or len(dosyalar) - i >= self.EN_FAZLA:
                self.sil(p.stem)

    def temizle(self) -> None:
        for zid in list(self.baglantilar):
            self.sil(zid)
        if self.dizin.exists():
            for p in self.dizin.glob("*.db"):
                p.unlink(missing_ok=True)


ziyaretciler = Ziyaretciler(DB_YOLU.parent / "ziyaretci")


def gunluk_kontrol() -> None:
    """Veri yoksa ya da dünden kalmaysa yeniden üretir (gece sıfırlama). Yerel veride hiçbir şey yapmaz."""
    with KILIT:
        if not yerel_mi() and (meta_al(ana_con, "uretim_tarihi") != date.today().isoformat()
                               or meta_al(ana_con, "veri_surumu") != str(veri_uret.VERI_SURUMU)):
            veri_uret.uret(ana_con)
            ziyaretciler.temizle()


mcp_app = None
if MCP_ACIK and MCP_ANAHTARLARI:
    from mcp.server.transport_security import TransportSecuritySettings
    mcp_app = mcp_sunucu.sunucu.streamable_http_app(
        streamable_http_path="/mcp", stateless_http=True, json_response=True, max_request_body_size=256 * 1024,
        # Alan adı denetimini Caddy yapar; ayrıca her istek anahtar ister (aşağıda).
        transport_security=TransportSecuritySettings(enable_dns_rebinding_protection=False))


@contextlib.asynccontextmanager
async def yasam(_: FastAPI):
    gunluk_kontrol()
    if mcp_app is not None:
        async with mcp_sunucu.sunucu.session_manager.run():
            yield
    else:
        yield


# Belge sayfaları kapalı: Swagger dış CDN'den betik yükler ve şema saldırgana harita olur.
api = FastAPI(title="Emanet + Usta", version=__version__, lifespan=yasam, docs_url=None, redoc_url=None, openapi_url=None)
if mcp_app is not None:
    api.router.routes.extend(mcp_app.routes)


@api.exception_handler(ValueError)
async def deger_hatasi(_: Request, hata: ValueError):
    # Çekirdekteki kural hataları kullanıcıya yöneliktir ("Bu konu kapandı…"); ayrıntı içermez.
    return JSONResponse({"detail": str(hata)}, status_code=400)


@api.exception_handler(Exception)
async def beklenmeyen(_: Request, hata: Exception):
    log.exception("Beklenmeyen hata")
    return JSONResponse({"detail": "İstek işlenemedi."}, status_code=500)


# --- Dış kat: başlıklar, gövde ve hız sınırı, kaynak denetimi, MCP anahtarı, ziyaretçi seçimi ------------
_pencere: dict[tuple, deque] = defaultdict(deque)
# Hesap yapan ama veri değiştirmeyen POST uçları: ziyaretçi kopyası açtırmaz
SALT_OKUMA_POST = {"/api/cagri/oneri", "/api/cagri/onizle", "/api/cagri/oncelik", "/api/ya-giderse", "/api/izin/kontrol", "/api/dokum/analiz"}
_ZID = re.compile(r"^[0-9a-f]{32}$")


def _sinir_asildi(tur: str, ip: str, sinir: int) -> bool:
    k, an = _pencere[(tur, ip)], time.monotonic()
    while k and an - k[0] > 60:
        k.popleft()
    if len(k) >= sinir:
        return True
    k.append(an)
    if len(_pencere) > 50_000:
        _pencere.clear()
    return False


def _ozet(v: str) -> bytes:
    return hashlib.sha256(v.encode()).digest()


_MCP_OZETLERI = [_ozet(a) for a in MCP_ANAHTARLARI]


def _mcp_yetkili(basliklar: dict, yol: str) -> bool:
    yetki = basliklar.get("authorization", "")
    sunulan = yetki[7:].strip() if yetki.lower().startswith("bearer ") else yol[len("/mcp/"):]
    if not sunulan or not _MCP_OZETLERI:
        return False
    h = _ozet(sunulan)
    return any(hmac.compare_digest(a, h) for a in _MCP_OZETLERI)


async def _yanit(send, durum: int, ileti: str, ek=()):
    govde = json.dumps({"detail": ileti}, ensure_ascii=False).encode()
    await send({"type": "http.response.start", "status": durum,
                "headers": [(b"content-type", b"application/json; charset=utf-8"), (b"cache-control", b"no-store"),
                            *BASLIKLAR, *ek]})
    await send({"type": "http.response.body", "body": govde})


async def app(scope, receive, send):
    if scope["type"] != "http":
        return await api(scope, receive, send)
    yol = scope["path"]
    yontem = scope["method"]
    basliklar = {k.decode("latin-1").lower(): v.decode("latin-1") for k, v in scope.get("headers", [])}
    ip = gercek_ip((scope.get("client") or ("", 0))[0], basliklar)

    # Gövde sınırı (Content-Length'e göre; parçalı gövde kabul edilmez)
    if yontem in ("POST", "PUT", "PATCH"):
        try:
            uzunluk = int(basliklar.get("content-length", "-1"))
        except ValueError:
            uzunluk = -1
        if uzunluk < 0 and "chunked" in basliklar.get("transfer-encoding", ""):
            return await _yanit(send, 411, "İstek gövdesinin uzunluğu belirtilmeli.")
        if uzunluk > GOVDE_SINIRI:
            return await _yanit(send, 413, "İstek çok büyük.")

    ek_baslik: list = []
    token = None
    if yol == "/mcp" or yol.startswith("/mcp/"):
        if _sinir_asildi("mcp", ip, MCP_SINIRI):
            return await _yanit(send, 429, "Çok hızlı istek. Bir dakika sonra yeniden deneyin.", [(b"retry-after", b"60")])
        if mcp_app is None:
            return await _yanit(send, 404, "MCP bu kurulumda kapalı (EMANET_MCP_ANAHTARLARI tanımlı değil).")
        if not _mcp_yetkili(basliklar, yol):
            return await _yanit(send, 401, "Geçerli bir MCP erişim anahtarı gerekli.")
        scope = {**scope, "path": "/mcp", "raw_path": b"/mcp"}
    elif yol.startswith("/api/"):
        gunluk_kontrol()
        if _sinir_asildi("okuma", ip, OKUMA_SINIRI):
            return await _yanit(send, 429, "Çok fazla istek. Bir dakika sonra yeniden deneyin.", [(b"retry-after", b"60")])
        if yontem == "POST":
            # CSRF: tarayıcıdan gelen yazma isteği yalnız bu sitenin sayfasından
            kaynak = basliklar.get("origin")
            if kaynak and urlsplit(kaynak).netloc != basliklar.get("host", ""):
                return await _yanit(send, 403, "Bu istek başka bir siteden geldi.")
            if not kaynak and basliklar.get("sec-fetch-site") == "cross-site":
                return await _yanit(send, 403, "Bu istek başka bir siteden geldi.")
            if _sinir_asildi("yazma", ip, YAZMA_SINIRI):
                return await _yanit(send, 429, "Çok fazla istek. Bir dakika sonra yeniden deneyin.", [(b"retry-after", b"60")])
        # Ziyaretçi demosu: yazma isteği ziyaretçinin kendi kopyasına gider
        if ZIYARETCI_ACIK and not yerel_mi():
            cerez = SimpleCookie(basliklar.get("cookie", ""))
            zid = cerez["emanet_z"].value if "emanet_z" in cerez and _ZID.match(cerez["emanet_z"].value) else None
            yazma = yontem == "POST" and yol not in SALT_OKUMA_POST
            with KILIT:
                if yol == "/api/sifirla" and zid:
                    ziyaretciler.sil(zid)
                    return await _yanit(send, 200, "Kendi demo alanın başlangıç hâline döndü.")
                if zid and ziyaretciler.var(zid):
                    token = _etkin.set(ziyaretciler.baglanti(zid))
                elif yazma:
                    zid = zid or secrets.token_hex(16)
                    if not ziyaretciler.olustur(zid, ip):
                        return await _yanit(send, 429, "Bugün bu adresten çok sayıda demo alanı açıldı. Yarın yeniden deneyin.")
                    token = _etkin.set(ziyaretciler.baglanti(zid))
                    ek_baslik.append((b"set-cookie", (f"emanet_z={zid}; Path=/; Max-Age={Ziyaretciler.OMUR_SN}; HttpOnly; "
                                                      f"SameSite=Lax{'; Secure' if GUVENLI_CEREZ else ''}").encode()))

    async def basliklarla(mesaj):
        if mesaj["type"] == "http.response.start":
            var = {k.lower() for k, _ in mesaj.get("headers", [])}
            ek = [(k, v) for k, v in BASLIKLAR if k not in var]
            tur = dict(mesaj.get("headers", [])).get(b"content-type", b"")
            if tur.startswith(b"text/html") and b"content-security-policy" not in var:
                ek.append((b"content-security-policy", CSP_SAYFA.encode()))
            elif not tur.startswith(b"text/html"):
                ek.append((b"content-security-policy", b"default-src 'none'; frame-ancestors 'none'"))
            if yol.startswith(("/api/", "/mcp")) and b"cache-control" not in var:
                ek.append((b"cache-control", b"no-store"))
            mesaj["headers"] = [*mesaj.get("headers", []), *ek, *ek_baslik]
        await send(mesaj)

    try:
        return await api(scope, receive, basliklarla)
    finally:
        if token is not None:
            _etkin.reset(token)


# ------------------------------------------------------------------ modeller

class OneriIstek(BaseModel):
    metin: str = Field(min_length=3, max_length=600)
    vardiya: str | None = Field(None, pattern="^(gunduz|aksam|gece)$")
    acan_birim: str = "Depolama"
    alan: str | None = Field(None, pattern="^(donanim|ag|wms|erp|bt)$")
    lokasyon_id: int | None = None


class CagriIstek(BaseModel):
    metin: str = Field(min_length=5, max_length=600)
    acan_birim: str = "Depolama"
    acan_kisi: str | None = Field(None, max_length=80)
    aciliyet: int = Field(2, ge=1, le=3)
    kategori_id: int | None = None
    vardiya: str | None = Field(None, pattern="^(gunduz|aksam|gece)$")
    lokasyon_id: int | None = None
    alan: str | None = Field(None, pattern="^(donanim|ag|wms|erp|bt)$")   # kişinin seçtiği alan (isteğe bağlı)
    # İki aşamalı form: verilirse öncelik bunlardan hesaplanır, 'aciliyet' yok sayılır
    yer: str | None = Field(None, max_length=60)
    cevaplar: dict[str, str] | None = Field(None, max_length=6)
    etki: str | None = Field(None, pattern="^(durdu|yavas|yok)$")
    kapsam: str | None = Field(None, pattern="^(ben|ekip|alan)$")
    sevkiyat: bool = False
    ne_zaman: str | None = Field(None, pattern="^(bugun|hafta|acele_yok)$")


class OncelikIstek(BaseModel):
    kategori_id: int
    etki: str | None = Field(None, pattern="^(durdu|yavas|yok)$")
    kapsam: str | None = Field(None, pattern="^(ben|ekip|alan)$")
    sevkiyat: bool = False
    ne_zaman: str | None = Field(None, pattern="^(bugun|hafta|acele_yok)$")


class YenidenAtaIstek(BaseModel):
    kategori_id: int | None = None
    kisi_id: int | None = None
    vardiya: str | None = Field(None, pattern="^(gunduz|aksam|gece)$")
    aciklama: str | None = Field(None, max_length=200)


class KapatIstek(BaseModel):
    sure_dk: int | None = Field(None, ge=1, le=10000)
    cozum_notu: str | None = Field(None, max_length=2000)
    karta_donustur: bool = False
    baslik: str | None = Field(None, max_length=120)
    kok_neden: str | None = Field(None, max_length=300)


class IzinIstek(BaseModel):
    kisi_id: int
    baslangic: str = Field(pattern=r"^\d{4}-\d{2}-\d{2}$")
    bitis: str = Field(pattern=r"^\d{4}-\d{2}-\d{2}$")


class CevapIstek(BaseModel):
    cevap: str = Field(min_length=1, max_length=200)


class SenaryoIstek(BaseModel):
    ad: str = Field(max_length=40)


class ReceteIstek(BaseModel):
    kategori_id: int
    not_metni: str = Field(min_length=3, max_length=2000)


class GirisIstek(BaseModel):
    ad: str = Field(min_length=5, max_length=60)
    birim: str
    gorev: str


class CikisIstek(BaseModel):
    ad: str = Field(min_length=3, max_length=60)


class DokumIstek(BaseModel):
    csv: str = Field(min_length=10, max_length=2_000_000)


class YaGiderseIstek(BaseModel):
    kisi_id: int
    gun: int = Field(21, ge=1, le=365)
    dakika_maliyeti: float = Field(0, ge=0, le=100000)


class GecisIstek(BaseModel):
    yeni_ad: str = Field(min_length=3, max_length=80)
    tarih: str | None = Field(None, pattern=r"^\d{4}-\d{2}-\d{2}$")
    eski_kategori_id: int | None = None
    birim_id: int | None = None
    anahtar_kisiler: list[int] = Field(default_factory=list, max_length=10)
    aciklama: str = Field("", max_length=300)
    kritiklik: int | None = Field(None, ge=1, le=3)
    anahtar_kelimeler: str = Field("", max_length=300)


class KisiIstek(BaseModel):
    ad: str = Field(min_length=3, max_length=60)
    birim_id: int
    vardiya: str = Field(pattern="^(gunduz|aksam|gece)$")
    rol: str = Field("Destek Uzmanı", max_length=60)
    ise_giris: str | None = Field(None, pattern=r"^\d{4}-\d{2}-\d{2}$")
    beyan_kategoriler: list[int] = Field(default_factory=list, max_length=30)


class AyrilisIstek(BaseModel):
    tarih: str | None = Field(None, pattern=r"^\d{4}-\d{2}-\d{2}$")


class AcikIstek(BaseModel):
    acik: bool


class PlanIstek(BaseModel):
    butce_saat: int = Field(60, ge=0, le=500)
    yontem: str = Field("optimum", pattern="^(optimum|kural)$")
    kaydet: bool = False
    # Takvim ayarları (takvim.py): kişi başı haftalık saat, oturum süresi, günlük oturum, çalışma günü, başlangıç
    haftalik_sinir: float = Field(2.0, ge=0.5, le=40)
    oturum_saat: float = Field(1.0, ge=0.5, le=4)
    gunluk_oturum: int = Field(1, ge=1, le=4)
    calisma_gunu: int = Field(5, ge=5, le=6)
    baslangic: date | None = None
    # Elle değişiklikler: haftaya özel sınır (0 = ötelendi) ve o hafta olmayan kişiler
    hafta_sinir: dict[int, float] = Field(default_factory=dict, max_length=104)
    kisi_yok: list[tuple[int, int]] = Field(default_factory=list, max_length=500)


# ------------------------------------------------------------------ ortak

@api.get("/api/ozet")
def ozet():
    with KILIT:
        h = risk.risk_haritasi(con)
        pot = otomasyon.potansiyel(con)
        return dict(surum=__version__, veri_tarihi=meta_al(con, "uretim_tarihi"), usta=usta.olculer(con),
                    otomasyon=dict(insansiz_oran=pot["insansiz_oran"], kazanc_saat_ay=pot["kazanc_saat_ay"],
                                   recete=len(pot["satirlar"]), **otomasyon.ozet(con)),
                    emanet=risk.ozet(h), en_riskli=[dict(ad=r["ad"], puan=r["puan"]) for r in h[:3]],
                    dikkat=takip.dikkat(con))


@api.get("/api/tanimlar")
def tanimlar():
    with KILIT:
        return dict(
            birimler=[dict(r) for r in con.execute("SELECT * FROM birim ORDER BY id")],
            kisiler=[dict(r) for r in con.execute(
                "SELECT p.id, p.ad, p.rol, p.vardiya, p.birim_id, p.ise_giris, b.ad AS birim FROM kisi p "
                "JOIN birim b ON b.id=p.birim_id WHERE p.aktif=1 ORDER BY b.id, p.ad")],
            kategoriler=[dict(r) for r in con.execute(
                "SELECT k.id, k.kod, k.ad, k.kritiklik, k.aciklama, k.birim_id, k.kaynak, k.acilis, k.alan, b.ad AS birim "
                "FROM kategori k JOIN birim b ON b.id=k.birim_id WHERE k.kaynak='usta' "
                "AND (k.emeklilik IS NULL OR k.emeklilik>?) AND (k.acilis IS NULL OR k.acilis<=?) ORDER BY b.id, k.ad",
                (date.today().isoformat(), date.today().isoformat()))],
            usta_birimleri=[r[0] for r in con.execute(
                "SELECT DISTINCT b.ad FROM birim b JOIN kategori k ON k.birim_id=b.id WHERE k.kaynak='usta'")],
            mod="yerel" if yerel_mi() else "demo",
            # Yerel veride çağrı ekranındaki örnekler kendi çağrılarından gelir (her konudan en yeni biri)
            ornek_metinler=[r[0][:90] for r in con.execute(
                "SELECT c.metin FROM cagri c WHERE c.kaynak='usta' AND c.id IN (SELECT MAX(id) FROM cagri "
                "WHERE kaynak='usta' GROUP BY kategori_id) ORDER BY c.id DESC LIMIT 6")] if yerel_mi() else [],
            hesaplar=[dict(r) for r in con.execute("SELECT ad, birim, gorev, durum FROM hesap ORDER BY birim, ad")],
            gorevler=list(katalog.GOREV_PAKETLERI),
            acan_birimler=katalog.ACAN_BIRIMLER, vardiyalar=katalog.VARDIYALAR,
            lokasyonlar=[dict(r) for r in con.execute("SELECT id, ad FROM lokasyon ORDER BY id")],
            alanlar=[dict(kod=k, ad=v[0], aciklama=v[1]) for k, v in katalog.ALANLAR.items()],
            izinliler=risk.tek_kisiye_kalanlar(con, 1)["izinliler"],
            simdiki_vardiya=ogrenme.vardiya_bul(__import__("datetime").datetime.now()))


# ------------------------------------------------------------------ Usta

@api.post("/api/cagri/oneri")
def cagri_oneri(i: OneriIstek):
    """Çağrı açılmadan önce: konu tahmini, kime gideceği ve geçmişte nasıl çözüldüğü."""
    with KILIT:
        o = usta.kategori_oner(con, i.metin, alan=i.alan)
        if o["soru_gerekli"]:
            return dict(o, atama=None, yol=None)
        ilk = o["oneriler"][0]["kategori_id"]
        a = cagri_formu.alan_bul(o["oneriler"][0]["kod"], None, i.alan)["alan"]
        return dict(o, atama=usta.yonlendir(con, ilk, vardiya=i.vardiya, metin=i.metin, acan_birim=i.acan_birim,
                                            lokasyon_id=i.lokasyon_id, alan=a),
                    yol=usta.yol_goster(con, i.metin, ilk))


@api.post("/api/cagri/onizle")
def cagri_onizle(i: CagriIstek):
    """Kullanıcı konuyu kendisi seçtiyse: o konuya göre atama ve yol gösterme."""
    if not i.kategori_id:
        raise HTTPException(400, "Konu seçilmedi")
    with KILIT:
        kod = (con.execute("SELECT kod FROM kategori WHERE id=?", (i.kategori_id,)).fetchone() or [None])[0]
        a = cagri_formu.alan_bul(kod, i.cevaplar, i.alan)
        return dict(atama=usta.yonlendir(con, i.kategori_id, vardiya=i.vardiya, metin=i.metin, acan_birim=i.acan_birim,
                                         lokasyon_id=i.lokasyon_id, alan=a["alan"]), alan=a,
                    yol=usta.yol_goster(con, i.metin, i.kategori_id))


def _oncelik(kategori_id: int, etki, kapsam, sevkiyat, ne_zaman) -> dict:
    k = con.execute("SELECT kod, kritiklik FROM kategori WHERE id=?", (kategori_id,)).fetchone()
    if not k:
        raise HTTPException(404, "Konu bulunamadı")
    return cagri_formu.aciliyet_hesapla(etki, kapsam, sevkiyat, k["kritiklik"], k["kod"] in cagri_formu.TALEP_KONULARI,
                                        ne_zaman)


@api.post("/api/cagri")
def cagri_ac(i: CagriIstek):
    with KILIT:
        aciliyet, ek, iki_asama = i.aciliyet, None, bool(i.etki or i.ne_zaman or i.cevaplar or i.yer)
        if iki_asama:
            if not i.kategori_id:
                raise HTTPException(400, "Konu seçilmedi")
            kod = con.execute("SELECT kod FROM kategori WHERE id=?", (i.kategori_id,)).fetchone()
            if not kod:
                raise HTTPException(404, "Konu bulunamadı")
            try:
                cevap = cagri_formu.cevaplari_dogrula(kod["kod"], i.cevaplar, con=con)
            except ValueError as e:
                raise HTTPException(400, str(e))
            onc = _oncelik(i.kategori_id, i.etki, i.kapsam, i.sevkiyat, i.ne_zaman)
            aciliyet = onc["seviye"]
            ek = cagri_formu.ek_bilgi_json(kod["kod"], cevap, i.etki, i.kapsam, i.sevkiyat, i.ne_zaman, onc)
            cihaz = cevap.get("cihaz")
            alan = cagri_formu.alan_bul(kod["kod"], cevap, i.alan)["alan"]
            yer = i.yer or ((cagri_formu.cihaz_kaydi(con, cihaz) or {}).get("yer"))   # envanterdeki yer
        else:
            cihaz, yer, alan = None, i.yer, i.alan
        if i.lokasyon_id and not con.execute("SELECT 1 FROM lokasyon WHERE id=?", (i.lokasyon_id,)).fetchone():
            raise HTTPException(400, "Tesis bulunamadı")
        return usta.cagri_ac(con, i.metin, i.acan_birim, aciliyet, i.kategori_id, i.vardiya, acan_kisi=i.acan_kisi,
                             yer=yer, ek_bilgi=ek, cihaz=cihaz, lokasyon_id=i.lokasyon_id, alan=alan)


@api.get("/api/cihaz/{no}")
def cihaz(no: str):
    """Formda numara yazılınca: envanter kaydı (model, yer) ve son 90 günün çağrıları."""
    if len(no) > 30:
        raise HTTPException(400, "Cihaz numarası çok uzun")
    with KILIT:
        return cagri_formu.cihaz_gecmisi(con, no)


class EnvanterIstek(BaseModel):
    csv: str = Field(min_length=3, max_length=2_000_000)
    tam: bool = False


@api.post("/api/cihazlar/envanter")
def cihaz_envanter(i: EnvanterIstek):
    """Demirbaş sisteminden alınan cihaz listesini (CSV) içe aktarır."""
    with KILIT:
        try:
            return cagri_formu.envanter_ice_aktar(con, i.csv, i.tam)
        except ValueError as e:
            raise HTTPException(400, str(e))


@api.get("/api/cihazlar/ozet")
def cihazlar_ozet():
    with KILIT:
        return cagri_formu.envanter_ozeti(con)


@api.get("/api/olcumler")
def olcumler(gun: int = Query(30, ge=7, le=180), lokasyon_id: int | None = None):
    """Kapanma süreleri, kişi başı iş yükü, ilk seferde çözme, haftalık akış (istenirse tek tesis)."""
    with KILIT:
        usta.onaysizlari_kapat(con)
        return olcum.cagri_olculeri(con, gun, lokasyon_id=lokasyon_id)


class HedefIstek(BaseModel):
    aciliyet: int = Field(ge=1, le=3)
    tepki_dk: int | None = Field(None, ge=5, le=20160)
    cozum_dk: int | None = Field(None, ge=5, le=20160)


@api.post("/api/olcumler/hedef")
def olcum_hedef(i: HedefIstek):
    """Öncelik hedefi (ilk tepki ve çözüm, hizmet süresiyle). İkisi de boşsa o önceliğin hedefi kalkar."""
    with KILIT:
        try:
            return olcum.hedef_kaydet(con, i.aciliyet, i.tepki_dk, i.cozum_dk)
        except ValueError as e:
            raise HTTPException(400, str(e))


@api.get("/api/tesis-kapsama")
def tesis_kapsamasi():
    """Her tesiste her vardiyada yerinde (donanım, ağ) bakan kişiler."""
    with KILIT:
        return olcum.tesis_kapsama(con)


@api.get("/api/cihazlar/tekrarlayan")
def cihazlar_tekrarlayan():
    with KILIT:
        return cagri_formu.tekrarlayan_cihazlar(con)


@api.get("/api/cagri/form/{kategori_id}")
def cagri_form(kategori_id: int, yer: str | None = Query(None, max_length=60), lokasyon_id: int | None = None):
    """İkinci aşama: konuya özel sorular, kendin dene adımları ve aynı sorunun açık bir çağrısı var mı."""
    with KILIT:
        try:
            return cagri_formu.form(con, kategori_id, yer, lokasyon_id)
        except ValueError as e:
            raise HTTPException(404, str(e))


@api.post("/api/cagri/oncelik")
def cagri_oncelik(i: OncelikIstek):
    with KILIT:
        return _oncelik(i.kategori_id, i.etki, i.kapsam, i.sevkiyat, i.ne_zaman)


@api.post("/api/cagri/kendin-cozdu/{kategori_id}")
def cagri_kendin_cozdu(kategori_id: int):
    """Kişi 'önce bunu dene' adımlarıyla çözdü, çağrı açmadı."""
    with KILIT:
        try:
            return dict(sayi=cagri_formu.kendin_cozdu(con, kategori_id))
        except ValueError as e:
            raise HTTPException(404, str(e))


@api.get("/api/cagri")
def cagri_liste(durum: str = "acik", birim_id: int | None = None, kisi_id: int | None = None,
                kategori_id: int | None = None, limit: int = 50, lokasyon_id: int | None = None):
    with KILIT:
        return usta.cagrilari_listele(con, durum, birim_id, kisi_id, kategori_id, limit, lokasyon_id)


@api.get("/api/cagri/{cagri_id}")
def cagri_detay(cagri_id: int):
    with KILIT:
        try:
            return usta.cagri_detay(con, cagri_id)
        except ValueError as e:
            raise HTTPException(404, str(e))


class SoruIstek(BaseModel):
    soru: str = Field(min_length=5, max_length=300)


@api.post("/api/cagri/{cagri_id}/isleme-al")
def cagri_isleme_al(cagri_id: int):
    with KILIT:
        try:
            return usta.isleme_al(con, cagri_id)
        except ValueError as e:
            raise HTTPException(400, str(e))


@api.post("/api/cagri/{cagri_id}/soru")
def cagri_soru(cagri_id: int, i: SoruIstek):
    """Çözen kişi açana soru sorar; durum Bilgi bekleniyor olur, cevapla İşlemde'ye döner."""
    with KILIT:
        try:
            return usta.soru_sor(con, cagri_id, i.soru)
        except ValueError as e:
            raise HTTPException(400, str(e))


@api.post("/api/cagri/{cagri_id}/yeniden-ata")
def cagri_yeniden_ata(cagri_id: int, i: YenidenAtaIstek):
    with KILIT:
        return usta.yeniden_ata(con, cagri_id, i.kategori_id, i.kisi_id, i.vardiya, i.aciklama)


@api.post("/api/cagri/{cagri_id}/kapat")
def cagri_kapat(cagri_id: int, i: KapatIstek):
    with KILIT:
        return usta.cagri_kapat(con, cagri_id, None, i.sure_dk, i.cozum_notu, i.karta_donustur, i.baslik, i.kok_neden)


@api.get("/api/kartlar")
def kart_liste(q: str | None = None):
    with KILIT:
        return usta.kartlar(con, q)


@api.get("/api/model")
def model_durumu():
    with KILIT:
        o = usta.olculer(con)
        return dict(bilgi=ogrenme.bilgi(con), degerlendirme=o.pop("model"), olculer=o,
                    esikler=dict(soru=ogrenme.SORU_ESIGI, fark=ogrenme.FARK_ESIGI, komsu=ogrenme.KOMSU,
                                 pay=ogrenme.PAY_ESIGI, yuk=ogrenme.YUK_SINIR),
                    paylastirma=usta.paylastirma_acik(con))


@api.post("/api/model/egit")
def model_egit():
    with KILIT:
        ogrenme.model(con, zorla=True)
        return ogrenme.bilgi(con)


# ------------------------------------------------------------------ Otomasyon

@api.get("/api/otomasyon")
def otomasyon_ozet():
    with KILIT:
        return dict(ozet=otomasyon.ozet(con), calismalar=otomasyon.son_calismalar(con, 12),
                    bekleyen=otomasyon.mesajlar(con, bekleyen=True, limit=20), receteler=otomasyon.receteler(con),
                    adaylar=otomasyon.recete_adaylari(con), potansiyel=otomasyon.potansiyel(con),
                    toplu=[dict(r) for r in con.execute(
                        "SELECT t.*, k.ad AS kategori, (SELECT COUNT(*) FROM cagri c WHERE c.olay_id=t.id) AS cagri "
                        "FROM toplu_olay t JOIN kategori k ON k.id=t.kategori_id ORDER BY t.id DESC LIMIT 5")])


@api.get("/api/otomasyon/{oto_id}")
def otomasyon_detay(oto_id: int):
    with KILIT:
        try:
            return otomasyon.oto_detay(con, oto_id)
        except ValueError as e:
            raise HTTPException(404, str(e))


@api.post("/api/otomasyon/senaryo")
def otomasyon_senaryo(i: SenaryoIstek):
    with KILIT:
        r = otomasyon.senaryo(con, i.ad)
        return dict(r, cagri=usta.cagri_detay(con, r["cagri_id"]))


@api.post("/api/mesaj/{mesaj_id}/cevap")
def mesaj_cevap(mesaj_id: int, i: CevapIstek):
    with KILIT:
        return otomasyon.cevapla(con, mesaj_id, i.cevap)


@api.post("/api/otomasyon/recete")
def recete_olustur(i: ReceteIstek):
    with KILIT:
        return otomasyon.recete_olustur(con, i.kategori_id, i.not_metni)


@api.post("/api/otomasyon/ise-giris")
def ise_giris(i: GirisIstek):
    with KILIT:
        return otomasyon.ise_giris(con, i.ad, i.birim, i.gorev)


@api.post("/api/otomasyon/isten-cikis")
def isten_cikis(i: CikisIstek):
    with KILIT:
        return otomasyon.isten_cikis(con, i.ad)


# ------------------------------------------------------------------ Emanet

@api.get("/api/risk")
def risk_listesi():
    with KILIT:
        h = risk.risk_haritasi(con)
        return dict(ozet=risk.ozet(h), konular=h, matris=risk.matris(con), kaynaklar=risk.veri_tazeligi(con),
                    formul=dict(yogunlasma=risk.A_YOGUNLASMA, yedek=risk.A_YEDEK, kart=risk.A_KART,
                                kritiklik=risk.KRITIKLIK_CARPANI, kirmizi=risk.KIRMIZI, sari=risk.SARI,
                                pencere_gun=risk.PENCERE_GUN, yetkin_esigi=risk.YETKIN_ESIGI))


_SAYI = re.compile(r"^-?[\d.]+(,\d+)?$")


def _csv_hucre(x):
    """Excel formül enjeksiyonu: =, +, -, @, sekme, satır başıyla başlayan metne ' eklenir; sayılar olduğu gibi kalır.
    (Konu ve kişi adları içe aktarılan dökümden gelebilir.)"""
    if isinstance(x, (int, float)) or x is None:
        return x
    x = str(x)
    if x and x[0] in "=+-@\t\r" and not _SAYI.match(x):
        return "'" + x
    return x


@api.get("/api/risk.csv")
def risk_csv():
    """Risk haritası, Excel'de açılacak biçimde (noktalı virgül, UTF-8 BOM)."""
    import csv
    import io
    with KILIT:
        h = risk.risk_haritasi(con)
    b = io.StringIO()
    w = csv.writer(b, delimiter=";")
    w.writerow(["Konu", "Birim", "Kaynak", "Kritiklik", "Puan", "Seviye", "En çok çözen", "Payı", "Bilen sayısı",
                "Kâğıtta bilen", "Yazılı çözüm", "Otomasyon payı", "Nedenler"])
    for r in h:
        w.writerow([_csv_hucre(x) for x in [r["ad"], r["birim"], r["kaynak"], r["kritiklik"], r["puan"],
                    {"kirmizi": "Yüksek", "sari": "Orta", "yesil": "Düşük"}[r["seviye"]] + (" (geçici)" if r["gecici"] else ""),
                    r["en_cok_cozen"]["ad"] if r["en_cok_cozen"] else "", str(r["yogunlasma"]).replace(".", ","),
                    r["yetkin_sayisi"], r["beyan_sayisi"], "yok" if r["kartsiz"] else "var",
                    str(r["otomasyon_payi"]).replace(".", ","), " · ".join(r["nedenler"])]])
    return PlainTextResponse("\ufeff" + b.getvalue(), media_type="text/csv; charset=utf-8",
                             headers={"Content-Disposition": 'attachment; filename="emanet-risk-haritasi.csv"'})


@api.get("/api/risk/seyri")
def risk_seyri():
    with KILIT:
        return takip.risk_seyri(con)


@api.get("/api/risk/firsatlar")
def risk_firsatlar():
    with KILIT:
        return takip.otomasyon_firsatlari(con)


@api.post("/api/izin/kontrol")
def izin_kontrol(i: IzinIstek):
    with KILIT:
        return takip.izin_kontrol(con, i.kisi_id, i.baslangic, i.bitis)


@api.post("/api/izin/kaydet")
def izin_kaydet(i: IzinIstek):
    with KILIT:
        return takip.izin_kaydet(con, i.kisi_id, i.baslangic, i.bitis)


@api.get("/api/izinler")
def izinler():
    with KILIT:
        return [dict(r) for r in con.execute(
            "SELECT m.*, p.ad FROM musaitlik m JOIN kisi p ON p.id=m.kisi_id WHERE m.bitis>=? ORDER BY m.baslangic",
            (date.today().isoformat(),))]


@api.get("/api/plan/takip")
def plan_takip():
    with KILIT:
        return takip.plan_takibi(con)


@api.post("/api/plan/simule")
def plan_simule():
    with KILIT:
        return takip.plan_simule_et(con)


@api.get("/api/devir/{kisi_id}")
def devir(kisi_id: int):
    with KILIT:
        return takip.devir_dosyasi(con, kisi_id)


@api.get("/api/devir/{kisi_id}/indir")
def devir_md(kisi_id: int):
    with KILIT:
        d = takip.devir_dosyasi(con, kisi_id)
    ad = d["kisi"]["ad"].lower().replace(" ", "-")
    return PlainTextResponse(d["markdown"], media_type="text/markdown; charset=utf-8",
                             headers={"Content-Disposition": f'attachment; filename="devir-{kisi_id}.md"'})


@api.post("/api/ya-giderse")
def ya_giderse(i: YaGiderseIstek):
    with KILIT:
        return risk.ya_giderse(con, i.kisi_id, i.gun, i.dakika_maliyeti)


def _plan_ve_takvim(i: PlanIstek) -> dict:
    # Ayarlar plan kaydedilmeden önce denetlenir: geçersiz ayar yarım kalmış kayıt bırakmasın
    takvim.ayar_dogrula(i.haftalik_sinir, i.oturum_saat, i.gunluk_oturum, i.calisma_gunu)
    with KILIT:
        p = egitim.plani_zenginlestir(con, risk.egitim_plani(con, i.butce_saat, i.yontem, i.kaydet))
    p["takvim"] = takvim.takvim_olustur(
        p["satirlar"], i.baslangic or takvim.sonraki_pazartesi(date.today()), i.haftalik_sinir,
        i.oturum_saat, i.gunluk_oturum, i.calisma_gunu, i.hafta_sinir, set(i.kisi_yok))
    return p


@api.post("/api/egitim-plani")
def egitim_plani(i: PlanIstek):
    return _plan_ve_takvim(i)


class DevirIstek(BaseModel):
    kisi_id: int
    cikis_tarihi: str = Field(pattern=r"^\d{4}-\d{2}-\d{2}$")
    haftalik_sinir: float = Field(4, ge=0.5, le=40)


class DevirKonuIstek(BaseModel):
    devralan_id: int | None = None
    izledi: bool | None = None


class DevirMaddeIstek(BaseModel):
    yapildi: bool


class DevirGorusmeIstek(BaseModel):
    cevap: str = Field(max_length=2000)


class DevirSahipIstek(BaseModel):
    recete_kod: str = Field(max_length=40)
    yeni_sahip_id: int


class DevirSinirIstek(BaseModel):
    saat: float | None = Field(None, ge=1, le=40)            # ayrılan
    devralan_saat: float | None = Field(None, ge=1, le=40)   # devralanlar


@api.get("/api/devir-sureci")
def devir_listesi():
    with KILIT:
        return devir_surec.acik_devirler(con)


@api.post("/api/devir-sureci")
def devir_baslat(i: DevirIstek):
    with KILIT:
        return devir_surec.baslat(con, i.kisi_id, i.cikis_tarihi, i.haftalik_sinir)


@api.get("/api/devir-sureci/{devir_id}")
def devir_durum(devir_id: int):
    with KILIT:
        return devir_surec.durum(con, devir_id)


@api.post("/api/devir-sureci/{devir_id}/konu/{kategori_id}")
def devir_konu(devir_id: int, kategori_id: int, i: DevirKonuIstek):
    with KILIT:
        devir_surec.konu_guncelle(con, devir_id, kategori_id, i.devralan_id, i.izledi)
        return devir_surec.durum(con, devir_id)


@api.post("/api/devir-sureci/{devir_id}/madde/{kod}")
def devir_madde(devir_id: int, kod: str, i: DevirMaddeIstek):
    with KILIT:
        devir_surec.madde_isaretle(con, devir_id, kod, i.yapildi)
        return devir_surec.durum(con, devir_id)


@api.post("/api/devir-sureci/{devir_id}/gorusme/{soru_no}")
def devir_gorusme(devir_id: int, soru_no: int, i: DevirGorusmeIstek):
    with KILIT:
        devir_surec.gorusme_kaydet(con, devir_id, soru_no, i.cevap)
        return devir_surec.durum(con, devir_id)


@api.post("/api/devir-sureci/{devir_id}/sahip")
def devir_sahip(devir_id: int, i: DevirSahipIstek):
    with KILIT:
        devir_surec.sahip_degistir(con, devir_id, i.recete_kod, i.yeni_sahip_id)
        return devir_surec.durum(con, devir_id)


@api.post("/api/devir-sureci/{devir_id}/sinir")
def devir_sinir(devir_id: int, i: DevirSinirIstek):
    with KILIT:
        devir_surec.haftalik_sinir_ayarla(con, devir_id, i.saat, i.devralan_saat)
        return devir_surec.durum(con, devir_id)


@api.post("/api/devir-sureci/{devir_id}/kapat")
def devir_kapat(devir_id: int):
    with KILIT:
        devir_surec.kapat(con, devir_id)
        return {"ok": True}


@api.post("/api/devir-sureci/{devir_id}/ilerlet")
def devir_ilerlet(devir_id: int):
    """DEMO: devri iki hafta ilerletir."""
    with KILIT:
        r = devir_surec.ilerlet_demo(con, devir_id)
        return {**r, "devir": devir_surec.durum(con, devir_id)}


@api.get("/api/devir-sureci/{devir_id}/tutanak.md")
def devir_tutanak(devir_id: int):
    with KILIT:
        md = devir_surec.tutanak(con, devir_id)
    return PlainTextResponse(md, media_type="text/markdown; charset=utf-8",
                             headers={"Content-Disposition": f'attachment; filename="devir-tutanagi-{devir_id}.md"'})


class SureIstek(BaseModel):
    kart_saat: float = Field(ge=0.5, le=200)
    ogrenme_saati: float = Field(ge=0.5, le=200)


@api.get("/api/konu-sureleri")
def konu_sureleri():
    with KILIT:
        return egitim.sureler(con)


@api.post("/api/konu-sureleri/{kategori_id}")
def konu_suresi_kaydet(kategori_id: int, i: SureIstek):
    with KILIT:
        return egitim.sure_kaydet(con, kategori_id, i.kart_saat, i.ogrenme_saati)


@api.get("/api/egitim-icerigi/{kategori_id}")
def egitim_icerigi(kategori_id: int):
    """Konunun çözüm yolları ve temsilci vakaları: eğitimde üzerinden geçilecek eski çağrılar."""
    with KILIT:
        return dict(yollar=egitim.cozum_yollari(con, kategori_id))


@api.get("/api/egitim-plani/takvim.csv")
def egitim_takvimi_csv(butce_saat: int = 60, yontem: str = "optimum", haftalik_sinir: float = 2.0,
                       oturum_saat: float = 1.0, gunluk_oturum: int = 1, calisma_gunu: int = 5,
                       baslangic: date | None = None, degisiklik: str = ""):
    """Eğitim takvimi, Excel'de açılacak biçimde: İK'ya ya da vardiya amirine verilecek liste.

    degisiklik: ekrandaki elle değişiklikler, JSON: {"hafta_sinir": {"3": 0}, "kisi_yok": [[13, 2]]}.
    """
    import csv
    import io
    import json
    if len(degisiklik) > 20000:
        raise ValueError("Değişiklik listesi çok uzun")
    d = json.loads(degisiklik) if degisiklik else {}
    if not isinstance(d, dict):
        raise ValueError("Değişiklik biçimi geçersiz")
    i = PlanIstek(butce_saat=butce_saat, yontem=yontem, haftalik_sinir=haftalik_sinir, oturum_saat=oturum_saat,
                  gunluk_oturum=gunluk_oturum, calisma_gunu=calisma_gunu, baslangic=baslangic,
                  hafta_sinir=d.get("hafta_sinir", {}), kisi_yok=d.get("kisi_yok", []))
    t = _plan_ve_takvim(i)["takvim"]
    b = io.StringIO()
    w = csv.writer(b, delimiter=";")
    w.writerow(["Hafta", "Tarih", "Gün", "Konu", "Ne yapılacak", "Veren", "Alan", "Süre (saat)", "Oturum", "Oturumun gündemi"])
    for o in t["oturumlar"]:
        g = date.fromisoformat(o["tarih"])
        w.writerow([_csv_hucre(x) for x in [o["hafta"], g.strftime("%d.%m.%Y"), o["gun"], o["kategori"], o["tur_adi"],
                    o["ogreten"] or "", o["ogrenen"] or "", f"{o['saat']:g}".replace(".", ","),
                    f"{o['parca']}/{o['parca_sayisi']}", " | ".join(o.get("gundem") or [])]])
    return PlainTextResponse("\ufeff" + b.getvalue(), media_type="text/csv; charset=utf-8",
                             headers={"Content-Disposition": 'attachment; filename="emanet-egitim-takvimi.csv"'})


@api.get("/api/tek-kisiye-kalanlar")
def tek_kisi(gun_sayisi: int = 7):
    with KILIT:
        return risk.tek_kisiye_kalanlar(con, gun_sayisi)


@api.get("/api/dokum/usta-ornek.csv")
def usta_ornek():
    """Yerel kurulum için örnek çağrı dosyası (kurgusal). Biçim: python -m emanet.yerel ile aynı."""
    import tempfile
    from . import yerel
    with tempfile.TemporaryDirectory() as d:
        yol = Path(d) / "ornek.csv"
        yerel.ornek_uret(yol)
        metin = yol.read_text(encoding="utf-8-sig")
    return PlainTextResponse("\ufeff" + metin, media_type="text/csv; charset=utf-8",
                             headers={"Content-Disposition": 'attachment; filename="ornek-usta-cagrilari.csv"'})


@api.get("/api/dokum/ornek.csv")
def ornek_dokum():
    """Bakım sistemi dökümü örneği (demo verisinin kaynağı)."""
    metin = veri_uret.bakim_dokumu_csv(date.today())
    return PlainTextResponse("\ufeff" + metin, media_type="text/csv; charset=utf-8",
                             headers={"Content-Disposition": 'attachment; filename="ornek-bakim-dokumu.csv"'})


@api.post("/api/dokum/analiz")
def dokum_analiz(i: DokumIstek):
    """Ziyaretçinin dökümünü kaydetmeden analiz eder (bellekte geçici veritabanı)."""
    return ice_aktar.analiz_et(i.csv)


# ------------------------------------------------------------------ Değişimler

@api.get("/api/degisim")
def degisim_ozet():
    with KILIT:
        return dict(gecisler=degisim.gecisler(con), yeni_personel=degisim.yeni_personel(con),
                    cirak_modu=usta.cirak_modu_acik(con),
                    receteler=[dict(kod=r["kod"], ad=r["ad"], kategori_kod=r["kategori_kod"], saglik=r["saglik"])
                               for r in otomasyon.receteler(con) if r["saglik"]],
                    ayrilanlar=[dict(r) for r in con.execute(
                        "SELECT p.id, p.ad, p.cikis, b.ad AS birim FROM kisi p JOIN birim b ON b.id=p.birim_id "
                        "WHERE p.aktif=0 ORDER BY p.cikis DESC LIMIT 10")],
                    simule=dict(gecis=bool(meta_al(con, "gecis_simule")), personel=bool(meta_al(con, "personel_simule"))))


@api.post("/api/gecis")
def gecis_kaydet(i: GecisIstek):
    with KILIT:
        return degisim.gecis_kaydet(con, i.yeni_ad, i.tarih, i.eski_kategori_id, i.anahtar_kisiler, i.aciklama,
                                    i.kritiklik, i.anahtar_kelimeler, i.birim_id)


@api.post("/api/gecis/simule")
def gecis_simule():
    with KILIT:
        return degisim.gecis_simule_et(con)


@api.post("/api/personel")
def personel_ekle(i: KisiIstek):
    with KILIT:
        return degisim.kisi_ekle(con, i.ad, i.birim_id, i.vardiya, i.rol, i.ise_giris, i.beyan_kategoriler)


@api.post("/api/personel/simule")
def personel_simule():
    with KILIT:
        return degisim.yeni_personel_simule_et(con)


@api.get("/api/personel/{kisi_id}/alisma")
def personel_alisma(kisi_id: int):
    with KILIT:
        return degisim.ise_alisma(con, kisi_id)


@api.post("/api/personel/{kisi_id}/ayrildi")
def personel_ayrildi(kisi_id: int, i: AyrilisIstek):
    with KILIT:
        return degisim.kisi_ayrildi(con, kisi_id, i.tarih)


@api.post("/api/paylastirma")
def paylastirma(i: AcikIstek):
    with KILIT:
        from .db import meta_yaz
        meta_yaz(con, "paylastirma", "1" if i.acik else "0")
        return dict(paylastirma=i.acik)


@api.post("/api/cirak-modu")
def cirak_modu(i: AcikIstek):
    with KILIT:
        from .db import meta_yaz
        meta_yaz(con, "cirak_modu", "1" if i.acik else "0")
        return dict(cirak_modu=i.acik)


@api.post("/api/otomasyon/recete/{kod}/devreye-al")
def recete_devreye_al(kod: str):
    with KILIT:
        if not con.execute("SELECT 1 FROM recete WHERE kod=?", (kod,)).fetchone():
            raise HTTPException(404, "Otomatik çözüm bulunamadı")
        return otomasyon.yeniden_devreye_al(con, kod)


# ------------------------------------------------------------------ yönetim

@api.post("/api/sifirla")
def sifirla():
    """Demo verisini başlangıç hâline döndürür."""
    with KILIT:
        if yerel_mi():
            raise HTTPException(400, "Yerel veride sıfırlama kapalı; veriyi yenilemek için içe aktarmayı yeniden çalıştırın.")
        return veri_uret.uret(con)


@api.get("/saglik")
def saglik():
    return {"durum": "iyi", "surum": __version__}


@api.get("/healthz")
def healthz():
    return {"ok": True}


@api.get("/")
def anasayfa():
    return FileResponse(WEB / "index.html", media_type="text/html; charset=utf-8", headers={"Cache-Control": "no-cache"})


# Sayfanın kendi dosyaları (satır içi betik yok; CSP script-src 'self'). Yol kullanıcıdan alınmaz.
@api.get("/app.js")
def betik():
    return FileResponse(WEB / "app.js", media_type="text/javascript; charset=utf-8", headers={"Cache-Control": "no-cache"})


@api.get("/stil.css")
def stil():
    return FileResponse(WEB / "stil.css", media_type="text/css; charset=utf-8", headers={"Cache-Control": "no-cache"})
