"""Eğitim planını takvime çevirir.

Plan (risk.egitim_plani) "hangi adımlar" sorusunu cevaplar; takvim "ne zaman ve kimin saatinden"
sorusunu. Depoda personel iş varken uzun süre eğitime çekilemez, bu yüzden:
  - her adım kısa oturumlara bölünür (oturum_saat),
  - bir kişi haftada en fazla `haftalik_sinir` saat eğitimde olur (veren de alan da sayılır),
  - bir kişi günde en fazla `gunluk_oturum` oturuma girer,
  - oturumlar yalnız çalışma günlerine konur.

Yerleştirme açgözlüdür (greedy): adımlar plan sırasıyla (en riskli konu önce) ele alınır ve her
oturum, iki katılımcının da hem o hafta hem o gün yeri olan en erken güne konur. Bu en kısa
takvimi garanti etmez ama anlaşılır ve öngörülebilirdir: "önce en tehlikeli iş" kuralı korunur.
Saf işlevdir (veritabanına dokunmaz); test ve MCP aynı kodu kullanır.
"""
from __future__ import annotations

import math
from collections import defaultdict
from datetime import date, timedelta

GUN_ADLARI = ["Pazartesi", "Salı", "Çarşamba", "Perşembe", "Cuma", "Cumartesi", "Pazar"]
TUR_ADI = {"kart": "Çözümü yazar", "egitim": "Öğretir", "tazeleme": "Tazeler", "gecis": "Yeni sisteme geçirir"}
EN_FAZLA_HAFTA = 104   # iki yıldan uzun takvim üretme; ayarlar imkânsızsa uyar

VARSAYILAN = dict(haftalik_sinir=2.0, oturum_saat=1.0, gunluk_oturum=1, calisma_gunu=5)


def sonraki_pazartesi(gun: date) -> date:
    return gun + timedelta(days=(7 - gun.weekday()) % 7 or 7)


def ayar_dogrula(haftalik_sinir: float, oturum_saat: float, gunluk_oturum: int, calisma_gunu: int) -> None:
    if not 0.5 <= haftalik_sinir <= 40:
        raise ValueError("Haftalık sınır 0,5 ile 40 saat arasında olmalı")
    if oturum_saat not in (0.5, 1.0, 1.5, 2.0, 3.0, 4.0):
        raise ValueError("Oturum süresi 0,5, 1, 1,5, 2, 3 ya da 4 saat olmalı")
    if oturum_saat > haftalik_sinir:
        raise ValueError("Oturum süresi haftalık sınırdan uzun olamaz")
    if not 1 <= gunluk_oturum <= 4:
        raise ValueError("Günlük oturum sayısı 1 ile 4 arasında olmalı")
    if calisma_gunu not in (5, 6):
        raise ValueError("Çalışma günü 5 (Pzt–Cum) ya da 6 (Pzt–Cmt) olmalı")


def takvim_olustur(satirlar: list[dict], baslangic: date, haftalik_sinir: float = 2.0,
                   oturum_saat: float = 1.0, gunluk_oturum: int = 1, calisma_gunu: int = 5) -> dict:
    """Plan satırlarını haftalara ve günlere yerleştirir.

    satirlar: risk.egitim_plani()["satirlar"] (sırası korunur: en riskli konu önce).
    baslangic: takvimin ilk haftasının pazartesisi (başka bir gün verilirse o haftanın pazartesisine çekilir).
    """
    ayar_dogrula(haftalik_sinir, oturum_saat, gunluk_oturum, calisma_gunu)
    baslangic = baslangic - timedelta(days=baslangic.weekday())

    haftalik: dict[tuple[int, int], float] = defaultdict(float)   # (kişi, hafta) → saat
    gunluk: dict[tuple[int, int], int] = defaultdict(int)          # (kişi, gün sırası) → oturum
    oturumlar: list[dict] = []
    konu_bitis: dict[int, int] = {}

    for adim_no, s in enumerate(satirlar, 1):
        kisiler = [k for k in (s.get("ogreten_id"), s.get("ogrenen_id")) if k is not None]
        parca_sayisi = max(1, math.ceil(s["saat"] / oturum_saat - 1e-9))
        kalan = float(s["saat"])
        gun_sira = 0          # adımın oturumları sırayla ilerler: bir sonraki oturum öncekinden önce olamaz
        for parca in range(1, parca_sayisi + 1):
            sure = min(oturum_saat, kalan)
            kalan = round(kalan - sure, 2)
            while True:
                hafta, gun_ici = divmod(gun_sira, calisma_gunu)
                if hafta >= EN_FAZLA_HAFTA:
                    raise ValueError("Bu ayarlarla takvim iki yıldan uzun sürüyor; haftalık sınırı artırın")
                if all(haftalik[(k, hafta)] + sure <= haftalik_sinir + 1e-9 and gunluk[(k, gun_sira)] < gunluk_oturum
                       for k in kisiler):
                    break
                gun_sira += 1
            for k in kisiler:
                haftalik[(k, hafta)] += sure
                gunluk[(k, gun_sira)] += 1
            tarih = baslangic + timedelta(weeks=hafta, days=gun_ici)
            oturumlar.append(dict(
                hafta=hafta + 1, tarih=tarih.isoformat(), gun=GUN_ADLARI[tarih.weekday()],
                adim=adim_no, parca=parca, parca_sayisi=parca_sayisi, saat=sure,
                kategori_id=s["kategori_id"], kategori=s["kategori"], tur=s["tur"], tur_adi=TUR_ADI.get(s["tur"], s["tur"]),
                ogreten_id=s.get("ogreten_id"), ogreten=s.get("ogreten"),
                ogrenen_id=s.get("ogrenen_id"), ogrenen=s.get("ogrenen")))
            konu_bitis[s["kategori_id"]] = max(konu_bitis.get(s["kategori_id"], 0), hafta + 1)
            if parca < parca_sayisi:
                gun_sira += 1   # aynı adımın sonraki parçası en erken ertesi gün

    oturumlar.sort(key=lambda o: (o["tarih"], o["adim"], o["parca"]))

    kisi: dict[int, dict] = {}
    for o in oturumlar:
        for rol, kid, ad in (("verdigi", o["ogreten_id"], o["ogreten"]), ("aldigi", o["ogrenen_id"], o["ogrenen"])):
            if kid is None:
                continue
            r = kisi.setdefault(kid, dict(kisi_id=kid, ad=ad, verdigi=0.0, aldigi=0.0, oturum=0, haftalar=set()))
            r[rol] += o["saat"]
            r["oturum"] += 1
            r["haftalar"].add(o["hafta"])
    kisi_ozet = sorted(
        (dict(r, toplam=r["verdigi"] + r["aldigi"], hafta_sayisi=len(r["haftalar"]), haftalar=None) for r in kisi.values()),
        key=lambda r: (-r["toplam"], r["ad"]))
    for r in kisi_ozet:
        r.pop("haftalar")

    hafta_sayisi = max((o["hafta"] for o in oturumlar), default=0)
    bitis = max((o["tarih"] for o in oturumlar), default=None)
    konular = []
    for s in satirlar:
        if s["kategori_id"] in konu_bitis and all(k["kategori_id"] != s["kategori_id"] for k in konular):
            konular.append(dict(kategori_id=s["kategori_id"], kategori=s["kategori"],
                                puan_once=s["puan_once"], puan_sonra=s["puan_sonra"], bitis_haftasi=konu_bitis[s["kategori_id"]]))
    return dict(
        ayarlar=dict(baslangic=baslangic.isoformat(), haftalik_sinir=haftalik_sinir, oturum_saat=oturum_saat,
                     gunluk_oturum=gunluk_oturum, calisma_gunu=calisma_gunu),
        oturumlar=oturumlar, kisiler=kisi_ozet, konular=konular,
        hafta_sayisi=hafta_sayisi, bitis=bitis, toplam_saat=round(sum(s["saat"] for s in satirlar), 1),
        darbogaz=kisi_ozet[0] if kisi_ozet else None)
