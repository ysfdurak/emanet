"""API ve MCP uçlarının duman testi."""
import os
import tempfile

os.environ["EMANET_DB"] = os.path.join(tempfile.mkdtemp(), "api.db")
os.environ["EMANET_GUVENLI_CEREZ"] = "0"          # TestClient http kullanır; Secure çerez geri gönderilmez
os.environ["EMANET_MCP_ANAHTARLARI"] = "test-anahtari-0123456789abcdef"
MCP_ANAHTAR = os.environ["EMANET_MCP_ANAHTARLARI"]
import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from emanet.api import app  # noqa: E402

BASLIK = {"accept": "application/json, text/event-stream", "MCP-Protocol-Version": "2025-06-18",
          "authorization": f"Bearer {MCP_ANAHTAR}"}


@pytest.fixture(scope="module")
def c():
    with TestClient(app) as istemci:
        yield istemci


def mcp(c, ad, arg):
    r = c.post("/mcp", headers=BASLIK, json={"jsonrpc": "2.0", "id": 9, "method": "tools/call",
                                             "params": {"name": ad, "arguments": arg}}).json()
    return r["result"]


def test_api_akisi(c):
    assert c.get("/").status_code == 200
    o = c.get("/api/ozet").json()
    assert o["usta"]["kapali_cagri"] == 900 and o["usta"]["model"]["konu"]["model"] > 0.9
    r = c.post("/api/cagri/oneri", json={"metin": "Sipariş dalgası açılmıyor, toplama görevleri düşmedi", "vardiya": "gece"}).json()
    assert r["oneriler"][0]["kod"] == "DALGA" and r["atama"]["uzman"]["ad"] == "Elif Kaya" and r["yol"]["yollar"]
    r = c.post("/api/cagri/oneri", json={"metin": "Sorter durdu, koliler şutlara gitmiyor"}).json()
    assert r["kapsam_disi"] and r["atama"] is None
    assert c.post("/api/cagri", json={"metin": "Sistem hata veriyor, devam edemiyorum"}).status_code == 400
    cg = c.post("/api/cagri", json={"metin": "Yazıcı etiketleri boş çıkarıyor, ribon bitmiş", "vardiya": "gunduz"}).json()
    assert cg["atama"]["ad"]
    assert c.get(f"/api/cagri/{cg['id']}").json()["durum"] == "acik"
    k = c.post(f"/api/cagri/{cg['id']}/kapat", json={"sure_dk": 30, "cozum_notu": "IP adresi düzeltildi"}).json()
    assert k["durum"] == "kapali" and k["cozum_notu"] == "IP adresi düzeltildi"
    assert c.post(f"/api/cagri/{cg['id']}/kapat", json={}).status_code == 400
    assert c.get("/api/cagri/999999").status_code == 404
    m = c.get("/api/model").json()
    assert m["bilgi"]["ornek"] == 901
    assert len(c.get("/api/risk").json()["konular"]) == 28
    assert c.post("/api/ya-giderse", json={"kisi_id": 7}).json()["etkilenen"]
    assert c.post("/api/egitim-plani", json={"butce_saat": 60}).json()["ozet_sonra"]["kirmizi"] == 0
    assert c.post("/api/egitim-plani", json={"butce_saat": 9999}).status_code == 422
    csv = c.get("/api/dokum/ornek.csv").text
    assert c.post("/api/dokum/analiz", json={"csv": csv}).json()["ozet"]["kirmizi"] >= 1
    assert c.post("/api/dokum/analiz", json={"csv": "tarih;konu\n2026-11-01;x\n"}).status_code == 400
    r = c.post("/api/otomasyon/senaryo", json={"ad": "kurulum_eksik"}).json()
    m = [x for x in r["cagri"]["otomasyon"]["mesajlar"] if x["cevap"] is None][0]
    assert c.post(f"/api/mesaj/{m['id']}/cevap", json={"cevap": m["secenekler"][0]}).json()["durum"] == "onay_bekliyor"
    assert c.post(f"/api/mesaj/{m['id']}/cevap", json={"cevap": "x"}).status_code == 400
    o = c.get("/api/otomasyon").json()
    assert o["ozet"]["bekleyen_mesaj"] >= 1 and o["potansiyel"]["satirlar"] and o["receteler"]
    assert c.post("/api/otomasyon/ise-giris", json={"ad": "Ece Yalın", "birim": "Toplama", "gorev": "Toplayıcı"}).json()["durum"] == "basarili"
    assert c.post("/api/otomasyon/senaryo", json={"ad": "yok"}).status_code == 400
    assert len(c.get("/api/risk/seyri").json()["noktalar"]) >= 5
    assert c.get("/api/risk/firsatlar").status_code == 200
    from datetime import date, timedelta
    b, e = (date.today() + timedelta(days=3)).isoformat(), (date.today() + timedelta(days=8)).isoformat()
    assert c.post("/api/izin/kontrol", json={"kisi_id": 7, "baslangic": b, "bitis": e}).json()["karar"] in ("dikkat", "uyari", "uygun")
    assert c.post("/api/izin/kontrol", json={"kisi_id": 7, "baslangic": "x", "bitis": e}).status_code == 422
    assert c.get("/api/devir/7").json()["konular"]
    assert c.get("/api/devir/7/indir").text.startswith("# Devir dosyası")
    assert c.post("/api/egitim-plani", json={"butce_saat": 40, "kaydet": True}).json()["kaydedildi"]
    assert c.post("/api/plan/simule").json()["uretilen_cagri"] >= 0
    assert c.get("/api/plan/takip").json()["var"]
    # Ziyaretçi demosu: sıfırlama yalnız bu ziyaretçinin alanını siler, ortak demo yerinde
    assert "alanın" in c.post("/api/sifirla").json()["detail"]
    assert c.get("/api/ozet").json()["usta"]["kapali_cagri"] == 900


def test_mcp_araclari(c):
    r = c.post("/mcp", headers=BASLIK, json={"jsonrpc": "2.0", "id": 1, "method": "tools/list"}).json()
    assert {t["name"] for t in r["result"]["tools"]} == {
        "cagri_ac", "cagrilari_listele", "nasil_cozuldu", "cagriyi_kapat", "model_basarimi",
        "otomasyon_durumu", "mesaja_cevap_ver", "otomasyon_potansiyeli",
        "izin_kontrolu", "devir_dosyasi", "plan_takibi", "risk_seyri",
        "risk_haritasi", "tek_kisiye_kalanlar", "ya_giderse", "egitim_plani_oner",
        "degisimler", "ise_alisma", "gecis_kaydet", "konu_sureleri", "konu_suresi_ayarla", "egitim_icerigi", "devir_baslat", "devir_durumu", "cihaz_gecmisi", "cagri_islem", "cagri_olculeri", "cagri_aktar"}
    r = mcp(c, "degisimler", {})
    assert not r.get("isError") and "otomasyon_sagligi" in r["content"][0]["text"]
    r = mcp(c, "ya_giderse", {"kisi": "Elif", "gun": 14})
    assert not r.get("isError") and "Sipariş dalgası" in r["content"][0]["text"]
    r = mcp(c, "nasil_cozuldu", {"sorun": "Yazıcı çevrimdışı görünüyor"})
    assert not r.get("isError") and "gecmiste_nasil_cozuldu" in r["content"][0]["text"]
    r = mcp(c, "otomasyon_potansiyeli", {})
    assert not r.get("isError") and "insansiz_oran" in r["content"][0]["text"]
    r = mcp(c, "cagri_ac", {"metin": "Sorter durdu, koliler gitmiyor"})
    assert r.get("isError") and "teknik" in r["content"][0]["text"]


def test_degisim_uclari(c):
    assert c.post("/api/gecis/simule").status_code == 200
    d = c.get("/api/degisim").json()
    assert d["gecisler"] and d["simule"]["gecis"]
    assert c.post("/api/gecis/simule").status_code == 400
    r = c.post("/api/personel", json={"ad": "Test Kişi", "birim_id": 2, "vardiya": "gunduz"})
    assert r.status_code == 200 and r.json()["kisi"]["ad"] == "Test Kişi"
    assert c.post("/api/personel", json={"ad": "Test Kişi", "birim_id": 2, "vardiya": "gunduz"}).status_code == 400
    assert c.post("/api/cirak-modu", json={"acik": False}).json() == {"cirak_modu": False}
    assert c.get("/api/degisim").json()["cirak_modu"] is False
    assert c.post("/api/otomasyon/recete/YOK/devreye-al").status_code == 404
    kats = {k["kod"] for k in c.get("/api/tanimlar").json()["kategoriler"]}
    assert "RAPOR" not in kats


def test_risk_csv_ve_ozet_dikkat(c):
    r = c.get("/api/risk.csv")
    assert r.status_code == 200 and r.text.startswith("﻿Konu;Birim") and "attachment" in r.headers["content-disposition"]
    assert isinstance(c.get("/api/ozet").json()["dikkat"], list)
    assert c.get("/api/risk").json()["kaynaklar"]


def test_paylastirma_ucu(c):
    m = c.get("/api/model").json()
    assert "politika" in m["degerlendirme"] and m["paylastirma"] is True
    assert c.post("/api/paylastirma", json={"acik": False}).json() == {"paylastirma": False}
    assert c.get("/api/model").json()["paylastirma"] is False
    c.post("/api/paylastirma", json={"acik": True})


def test_yerel_modda_demo_uretilmez_ve_sifirlama_kapali(c):
    from emanet import api
    from emanet.db import meta_yaz
    meta_yaz(api.con, "mod", "yerel")
    try:
        assert c.get("/api/tanimlar").json()["mod"] == "yerel"
        assert c.post("/api/sifirla").status_code == 400
    finally:
        api.con.execute("DELETE FROM meta WHERE anahtar='mod'")
        api.con.commit()
    assert c.get("/api/dokum/usta-ornek.csv").text.startswith("﻿Açılış tarihi;Açıklama")



# ---------------------------------------------------------------- güvenlik temeli (docs/GUVENLIK_TEMELI.md)

def test_guvenlik_basliklari_ve_csp(c):
    r = c.get("/")
    csp = r.headers["content-security-policy"]
    assert "script-src 'self'" in csp and "unsafe-eval" not in csp and "frame-ancestors 'none'" in csp
    assert "<script>" not in r.text and 'src="/app.js"' in r.text
    for b in ("x-content-type-options", "x-frame-options", "referrer-policy", "permissions-policy", "cross-origin-opener-policy"):
        assert b in r.headers
    a = c.get("/api/tanimlar")
    assert a.headers["cache-control"] == "no-store" and a.headers["content-security-policy"].startswith("default-src 'none'")
    assert c.get("/app.js").headers["content-type"].startswith("text/javascript")
    for yol in ("/docs", "/api/docs", "/openapi.json", "/redoc"):
        assert c.get(yol).status_code == 404


def test_kaynak_denetimi_govde_ve_mcp_anahtari(c):
    assert c.post("/api/cagri/oneri", json={"metin": "Yazıcı basmıyor"}, headers={"origin": "https://kotu.example"}).status_code == 403
    assert c.post("/api/cagri/oneri", json={"metin": "Yazıcı basmıyor"}, headers={"sec-fetch-site": "cross-site"}).status_code == 403
    assert c.post("/api/cagri/oneri", json={"metin": "Yazıcı basmıyor"}, headers={"origin": "http://testserver"}).status_code == 200
    assert c.post("/api/dokum/analiz", content=b"x" * 2_300_000, headers={"content-type": "application/json"}).status_code == 413
    istek = {"jsonrpc": "2.0", "id": 1, "method": "tools/list"}
    temel = {k: v for k, v in BASLIK.items() if k != "authorization"}
    assert c.post("/mcp", headers=temel, json=istek).status_code == 401
    assert c.post("/mcp", headers={**temel, "authorization": "Bearer yanlis-anahtar-yanlis-anahtar"}, json=istek).status_code == 401
    assert c.post(f"/mcp/{MCP_ANAHTAR}", headers=temel, json=istek).status_code == 200


def test_ziyaretciler_birbirinin_verisini_gormez(c):
    a, b = TestClient(app), TestClient(app)      # ayrı çerez kutuları = iki ziyaretçi (yaşam döngüsü c'de çalışıyor)
    if True:
        cg = a.post("/api/cagri", json={"metin": "Yazıcı ribonu bitti, soluk basıyor", "vardiya": "gunduz"})
        assert cg.status_code == 200 and "emanet_z=" in cg.headers["set-cookie"] and "HttpOnly" in cg.headers["set-cookie"]
        cid = cg.json()["id"]
        assert a.get(f"/api/cagri/{cid}").status_code == 200
        assert b.get(f"/api/cagri/{cid}").status_code == 404           # başka ziyaretçi (ve ortak demo) görmez
        b.post("/api/cagri", json={"metin": "El terminali ağa bağlanmıyor", "vardiya": "gunduz"})
        acik_a = {x["id"] for x in a.get("/api/cagri?durum=acik").json()}
        acik_b = {x["id"] for x in b.get("/api/cagri?durum=acik").json()}
        assert cid in acik_a and cid not in acik_b
        # Sahte çerez (biçimi bozuk) yok sayılır
        assert a.get("/api/ozet", headers={"cookie": "emanet_z=../../etc"}).status_code == 200


def test_csv_formul_enjeksiyonu():
    from emanet.api import _csv_hucre
    assert _csv_hucre("=HYPERLINK(\"x\")") == "'=HYPERLINK(\"x\")" and _csv_hucre("@SUM(A1)") == "'@SUM(A1)"
    assert _csv_hucre("-5") == "-5" and _csv_hucre("1.250,75") == "1.250,75" and _csv_hucre(42) == 42


def test_egitim_takvimi_api_ve_csv():
    c = TestClient(app)
    r = c.post("/api/egitim-plani", json={"butce_saat": 20, "haftalik_sinir": 3, "calisma_gunu": 6},
               headers={"origin": "http://testserver"})
    assert r.status_code == 200
    t = r.json()["takvim"]
    assert t["ayarlar"]["haftalik_sinir"] == 3 and t["oturumlar"] and t["darbogaz"]
    r = c.post("/api/egitim-plani", json={"butce_saat": 20, "oturum_saat": 4, "haftalik_sinir": 2},
               headers={"origin": "http://testserver"})
    assert r.status_code in (400, 422)
    r = c.post("/api/egitim-plani", json={"butce_saat": 20, "hafta_sinir": {"1": 0}, "kisi_yok": [[13, 2]]},
               headers={"origin": "http://testserver"})
    assert r.status_code == 200 and all(o["hafta"] > 1 for o in r.json()["takvim"]["oturumlar"])
    r = c.get('/api/egitim-plani/takvim.csv?butce_saat=20&degisiklik={"hafta_sinir":{"1":0}}')
    assert r.status_code == 200 and "\n1;" not in r.text
    assert c.get("/api/egitim-plani/takvim.csv?degisiklik=[1]").status_code == 400
    r = c.get("/api/egitim-plani/takvim.csv?butce_saat=20")
    assert r.status_code == 200 and "attachment" in r.headers["content-disposition"]
    assert r.text.startswith("﻿Hafta;Tarih;Gün;Konu")


def test_iki_asamali_cagri_formu(c):
    m = "Sipariş dalgası açılmıyor, toplama görevleri düşmedi"
    kid = c.post("/api/cagri/oneri", json={"metin": m}).json()["oneriler"][0]["kategori_id"]
    f = c.get(f"/api/cagri/form/{kid}").json()
    assert f["sorular"] and f["etki"] and not f["talep"]
    assert c.post("/api/cagri/oncelik", json={"kategori_id": kid, "etki": "durdu", "kapsam": "alan"}).json()["seviye"] == 3
    r = c.post("/api/cagri", json={"metin": m, "kategori_id": kid, "yer": "C koridoru", "etki": "yavas", "kapsam": "ben",
                                   "aciliyet": 3, "cevaplar": {"dalga": "D-7"}}).json()
    assert r["aciliyet"] == 1 and r["yer"] == "C koridoru"          # öncelik hesaplanır, gönderilen aciliyet yok sayılır
    assert any(b["id"] == r["id"] for b in c.get(f"/api/cagri/form/{kid}?yer=C koridoru").json()["benzer"])
    assert c.post("/api/cagri", json={"metin": m, "kategori_id": kid, "etki": "uydurma"}).status_code == 422
