"""Usta'nın makine öğrenmesi katmanı.

Geçmiş (kapalı) Usta çağrılarından üç şey öğrenilir:

  1. KONU MODELİ  — çağrı metni → konu
       Metin harf dizilerine bölünür ("sorter" → "sor", "ort", "rte", ... 3-5 harflik parçalar).
       Bu, Türkçe eklerle başa çıkar: "terminali", "terminalde", "terminal" ortak parçaları paylaşır.
       Her parçaya TF-IDF ağırlığı verilir; lojistik regresyon her konu için bir olasılık üretir.

  2. KİŞİ MODELİ  — metin + konu + vardiya + açan birim → çağrıyı kimin iyi çözdüğü
       Aynı konunun içinde bile alt sorunların farklı uzmanı olabilir (yazıcının ağ sorunu ile
       ribon sorunu farklı kişilere gider). Model bunu metindeki ayrıntıdan öğrenir.
       Her geçmiş çağrı çözümün kalitesine göre ağırlık alır: konunun olağan süresinden hızlı
       çözülen ve açan kişinin "çözüldü" dediği çağrılar daha çok, yavaş çözülenler daha az sayılır.
       Böylece model "kime verilirdi"yi değil, "kim iyi çözer"i öğrenmeye yaklaşır.
       Model yalnızca yetkinliği tahmin eder. Kime verileceğine paylaştırma kuralı karar verir
       (paylastirma_secimi): iş yükü dengelenir ve bilgi tek kişide toplanmasın diye, baskın uzman
       yerine konuyu bilen başka biri seçilebilir.

  3. NASIL ÇÖZÜLDÜ — en benzer geçmiş çağrıların çözüm notları gruplanır:
       "Benzer 9 çağrının 7'si şu adımlarla, ortalama 18 dakikada çözülmüş."

Model her kapanan çağrıyla yeniden eğitilir; yanlış yönlendirilip düzeltilen çağrılar düzeltilmiş
hâliyle öğrenmeye girer. Başarı, zamana göre ayrılmış bir test kümesinde (en yeni %20) ölçülür ve
eski kural tabanlı yöntemle karşılaştırılır.

Sistem geçişi (degisim.py): eski konu kapanıp yerine yeni konu açıldıysa, eski konunun çağrıları
konu modelinde yeni konunun etiketiyle öğrenilir (sorunlar aynı, sistem yeni). Kişi modelinde bu eski
çağrıların ağırlığı 0,4'tür: eski sistemde çözen kişi yeni sistemde de muhtemelen doğru adrestir ama
yeni sistemde biriken her çağrı daha çok sayılır.

Yapay zekâ servisi kullanılmaz; her şey sunucuda, birkaç yüz kilobaytlık bir modelle çalışır.
"""
from __future__ import annotations

import sqlite3
import threading
import time
from collections import Counter, OrderedDict, defaultdict
from datetime import datetime

import numpy as np
from scipy.sparse import csr_matrix, hstack
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.linear_model import LogisticRegression
from sklearn.preprocessing import OneHotEncoder

SORU_ESIGI = 0.45       # konu olasılığı bunun altındaysa sistem sorar
FARK_ESIGI = 0.12       # birinci ile ikinci arasındaki fark bunun altındaysa sistem sorar
KOMSU = 15              # "nasıl çözüldü" ve açıklama için bakılan en benzer çağrı sayısı
BENZERLIK_ALT = 0.20    # bunun altındaki çağrılar benzer sayılmaz
TEST_PAYI = 0.20
GECIS_AGIRLIGI = 0.4    # geçişten önceki (eski sistem) çağrılarının kişi modelindeki ağırlığı
KALITE_ALT, KALITE_UST = 0.5, 1.5   # çözüm kalitesi ağırlığının sınırları
TEYIT_BONUSU = 1.1      # açan kişi "çözüldü" dediyse
PAY_ESIGI = 0.60        # konunun bu kadarını tek kişi çözüyorsa paylaştırma devreye girer
ALT_ORAN = 0.10         # yedek uzmanın model olasılığı baskın uzmanınkinin en az bu katı olmalı (yetkinliği zaten eşikle aranıyor)
YUK_SINIR = 3           # seçilen kişinin üzerinde bu kadar açık çağrı varsa, konuyu bilen daha boş biri tercih edilir


def kucult(metin: str) -> str:
    """Türkçeye uygun küçük harf (İ→i, I→ı)."""
    return metin.replace("İ", "i").replace("I", "ı").lower()


def _metin_vektorleyici() -> TfidfVectorizer:
    return TfidfVectorizer(analyzer="char_wb", ngram_range=(3, 5), min_df=2, sublinear_tf=True,
                           preprocessor=kucult, max_features=40000)


def vardiya_bul(zaman: datetime) -> str:
    return "gece" if zaman.hour < 8 else ("gunduz" if zaman.hour < 16 else "aksam")


def gecis_haritasi(con: sqlite3.Connection, bugun: str | None = None) -> dict[int, int]:
    """Kapanmış (geçiş günü gelmiş) eski konu → bugünkü karşılığı. Zincirleme geçişler (A→B→C) izlenir."""
    bugun = bugun or datetime.now().date().isoformat()
    h = {r[0]: r[1] for r in con.execute(
        "SELECT eski_kategori_id, yeni_kategori_id FROM gecis WHERE eski_kategori_id IS NOT NULL AND tarih<=? "
        "ORDER BY tarih", (bugun,))}
    for e in list(h):
        hedef, gorulen = h[e], {e}
        while hedef in h and hedef not in gorulen:
            gorulen.add(hedef)
            hedef = h[hedef]
        h[e] = hedef
    return h


def _egitim_verisi(con: sqlite3.Connection) -> list[dict]:
    satirlar = [dict(r) for r in con.execute(
        "SELECT c.id, c.metin, c.kategori_id, c.cozen_kisi_id, c.vardiya, c.acan_birim, c.cozum_notu, "
        "c.sure_dk, c.acilis, c.aciliyet, c.teyit, p.ad AS cozen FROM cagri c JOIN kisi p ON p.id=c.cozen_kisi_id "
        "WHERE c.kaynak='usta' AND c.durum='kapali' ORDER BY c.acilis, c.id")]
    harita = gecis_haritasi(con)
    for s in satirlar:
        s["agirlik"] = 1.0
        if s["kategori_id"] in harita:
            s["asil_kategori_id"], s["kategori_id"], s["agirlik"] = s["kategori_id"], harita[s["kategori_id"]], GECIS_AGIRLIGI
    return satirlar


def kalite_agirliklari(satirlar: list[dict]) -> list[float]:
    """Her çağrının çözüm kalitesi ağırlığı: konunun ortanca süresi / bu çağrının süresi (0,5–1,5 arası),
    açan kişi "çözüldü" dediyse ×1,1. Ortanca, verilen satırların kendisinden hesaplanır (test sızmaz)."""
    sureler = defaultdict(list)
    for s in satirlar:
        if s.get("sure_dk"):
            sureler[s["kategori_id"]].append(s["sure_dk"])
    ortanca = {k: float(np.median(v)) for k, v in sureler.items()}
    sonuc = []
    for s in satirlar:
        w = 1.0
        if s.get("sure_dk") and s["kategori_id"] in ortanca:
            w = min(KALITE_UST, max(KALITE_ALT, ortanca[s["kategori_id"]] / s["sure_dk"]))
        if s.get("teyit") == 1:
            w *= TEYIT_BONUSU
        sonuc.append(w)
    return sonuc


class Model:
    """Bir veri kümesi üzerinde eğitilmiş konu ve kişi modelleri."""

    def __init__(self, satirlar: list[dict], kalite: bool = True):
        if len(satirlar) < 30:
            raise ValueError("Öğrenmek için en az 30 kapalı çağrı gerekiyor")
        self.satirlar = satirlar
        self.kalite = kalite
        metinler = [s["metin"] for s in satirlar]

        # 1) konu
        self.konu_vek = _metin_vektorleyici()
        X = self.konu_vek.fit_transform(metinler)
        self.konu = LogisticRegression(C=8.0, max_iter=3000)
        self.konu.fit(X, [s["kategori_id"] for s in satirlar])
        self.X = X                                   # benzer çağrı araması için (satırlar L2 birim uzunlukta)

        # 2) kişi: metin + bağlam (konu, vardiya, açan birim)
        self.baglam = OneHotEncoder(handle_unknown="ignore")
        B = self.baglam.fit_transform([[s["kategori_id"], s["vardiya"] or "", s["acan_birim"]] for s in satirlar])
        self.kisi = LogisticRegression(C=4.0, max_iter=3000)
        kal = kalite_agirliklari(satirlar) if kalite else [1.0] * len(satirlar)
        self.kisi.fit(hstack([X, B * 2.0]).tocsr(), [s["cozen_kisi_id"] for s in satirlar],
                      sample_weight=[s.get("agirlik", 1.0) * k for s, k in zip(satirlar, kal)])

    # ---------------------------------------------------------------- konu
    def konu_olasiliklari(self, metin: str) -> list[tuple[int, float]]:
        p = self.konu.predict_proba(self.konu_vek.transform([metin]))[0]
        return sorted(zip(self.konu.classes_.tolist(), p.tolist()), key=lambda x: -x[1])

    def belirleyici_sozcukler(self, metin: str, kategori_id: int, n: int = 3) -> list[str]:
        """Bir sözcük metinden çıkarılınca o konunun puanı ne kadar düşüyor? En çok düşürenler."""
        sinif = self.konu.classes_.tolist().index(kategori_id)
        temel = self.konu.decision_function(self.konu_vek.transform([metin]))[0][sinif]
        sozcukler = [s for s in dict.fromkeys(metin.replace(",", " ").replace(".", " ").split()) if len(s) >= 3]
        if not sozcukler:
            return []
        eksik = [" ".join(x for x in metin.split() if x.strip(",.") != s.strip(",.")) for s in sozcukler]
        puan = self.konu.decision_function(self.konu_vek.transform(eksik))[:, sinif]
        katki = sorted(zip(sozcukler, temel - puan), key=lambda x: -x[1])
        return [s.strip(",.!?").lower() for s, k in katki[:n] if k > 0.3]

    # ---------------------------------------------------------------- kişi
    def kisi_olasiliklari(self, metin: str, kategori_id: int, vardiya: str, acan_birim: str) -> dict[int, float]:
        X = self.konu_vek.transform([metin])
        B = self.baglam.transform([[kategori_id, vardiya, acan_birim]])
        p = self.kisi.predict_proba(hstack([X, B * 2.0]).tocsr())[0]
        return dict(zip(self.kisi.classes_.tolist(), p.tolist()))

    # ---------------------------------------------------------------- benzer çağrılar
    def komsular(self, metin: str, kategori_id: int | None = None, n: int = KOMSU) -> list[tuple[dict, float]]:
        benzerlik = (self.X @ self.konu_vek.transform([metin]).T).toarray().ravel()
        sira = np.argsort(-benzerlik)
        sonuc = []
        for i in sira:
            if benzerlik[i] < BENZERLIK_ALT or len(sonuc) >= n:
                break
            s = self.satirlar[i]
            if kategori_id is None or s["kategori_id"] == kategori_id:
                sonuc.append((s, float(benzerlik[i])))
        return sonuc


# ---------------------------------------------------------------- paylaştırma kuralı

def paylastirma_secimi(adaylar: list[tuple[int, float]], sayim: dict[int, int], esik: int,
                       acil_kritik: bool = False, acik: dict[int, int] | None = None) -> dict:
    """Modelin skorlarından kime verileceğine karar verir.

    adaylar  : (kişi, model olasılığı) — zaten müsait ve vardiyada olanlar
    sayim    : konuda son 90 günde kim kaç çağrı çözdü
    1. İş yükü: modelin seçtiği kişinin üzerinde 3 ya da daha fazla açık çağrı varsa, konuyu bilen
       (eşiği geçen) ve daha az açık çağrısı olan kişiye verilir. Model olasılıkları geçmiş atamalar
       yüzünden uzmanda yığıldığı için olasılığı cezalandırmak yetmez; kural açık konuşur.
    2. Paylaştırma: seçilen kişi bu vardiyada konunun %60'ından fazlasını tek başına çözüyorsa ve konuyu bilen
       (eşiği geçen) başka biri skorunun en az %35'ine sahipse çağrı ona verilir. Acil ve kritik
       çağrıda bu adım atlanır: o an en iyi uzman gerekir.
    """
    acik = acik or {}
    if not adaylar:
        return dict(kisi_id=None, tur=None)
    skor = dict(adaylar)
    sirali = sorted(skor, key=lambda k: -skor[k])
    model_ilk = ilk = sirali[0]
    tur = None
    if acik.get(ilk, 0) >= YUK_SINIR:
        bos = [k for k in sirali[1:] if sayim.get(k, 0) >= esik and acik.get(k, 0) < acik[ilk]]
        if bos:
            return dict(kisi_id=bos[0], tur="yuk", model_ilk=model_ilk)
    # Baskınlık, o an seçilebilecek kişiler (vardiyadakiler) arasında ölçülür: vardiyada bilgi tek
    # kişide toplanıyorsa yedeklerin pratiği de körelir.
    yerel = {k: n for k, n in sayim.items() if k in skor and n}
    toplam = sum(yerel.values())
    if not acil_kritik and toplam:
        baskin = max(yerel, key=yerel.get)
        pay = yerel[baskin] / toplam
        if ilk == baskin and pay >= PAY_ESIGI:
            for k in sirali[1:]:
                if sayim.get(k, 0) >= esik and skor[k] >= ALT_ORAN * skor[ilk] and acik.get(k, 0) < YUK_SINIR:
                    return dict(kisi_id=k, tur="paylastirma", baskin=baskin, pay=round(pay, 2), model_ilk=model_ilk)
    return dict(kisi_id=ilk, tur=tur, model_ilk=model_ilk)


# ---------------------------------------------------------------- önbellek ve eğitim

class _Onbellek:
    """Eğitilmiş modeller verinin parmak iziyle saklanır (en çok MODEL_SAYISI tane).

    Ziyaretçi demosunda her ziyaretçinin kendi veritabanı kopyası vardır (api.py). Verisi aynı olan
    kopyalar aynı modeli paylaşır; bir ziyaretçi çağrı kapatınca yalnız onun için yeniden eğitilir.
    """
    MODEL_SAYISI = 6

    def __init__(self):
        self.kilit = threading.RLock()
        self.modeller: OrderedDict = OrderedDict()       # anahtar → (Model, bilgi)
        self.degerlendirmeler: OrderedDict = OrderedDict()

    @staticmethod
    def koy(sozluk: OrderedDict, anahtar, deger, sinir: int) -> None:
        sozluk[anahtar] = deger
        sozluk.move_to_end(anahtar)
        while len(sozluk) > sinir:
            sozluk.popitem(last=False)


_ob = _Onbellek()


def _veri_anahtari(con: sqlite3.Connection, once: str | None = None):
    """Eğitim verisinin parmak izi. once verilirse yalnız o andan önce açılmış çağrılar (değerlendirme
    bugün açılan çağrılardan etkilenmesin: ziyaretçinin kapattığı bir çağrı 3 modeli yeniden eğitmesin)."""
    sart, arg = ("AND acilis<?", (once,)) if once else ("", ())
    r = con.execute("SELECT COUNT(*), COALESCE(MAX(kapanis),''), COALESCE(SUM(cozen_kisi_id),0), "
                    "COALESCE(SUM(kategori_id),0), COALESCE(SUM(LENGTH(metin)),0), COALESCE(SUM(sure_dk),0) "
                    f"FROM cagri WHERE kaynak='usta' AND durum='kapali' {sart}", arg).fetchone()
    g = con.execute("SELECT COUNT(*), COALESCE(MAX(id),0) FROM gecis WHERE tarih<=?",
                    (datetime.now().date().isoformat(),)).fetchone()
    k = con.execute("SELECT COUNT(*), COALESCE(SUM(id),0) FROM kisi WHERE aktif=1").fetchone()
    return (*tuple(r), *tuple(g), *tuple(k))


def model(con: sqlite3.Connection, zorla: bool = False) -> Model:
    """Güncel modeli döndürür. Kapalı çağrılar değiştiyse yeniden eğitir."""
    with _ob.kilit:
        anahtar = _veri_anahtari(con)
        if not zorla and anahtar in _ob.modeller:
            _ob.modeller.move_to_end(anahtar)
            return _ob.modeller[anahtar][0]
        t = time.perf_counter()
        satirlar = _egitim_verisi(con)
        m = Model(satirlar)
        b = dict(egitim_zamani=datetime.now().isoformat(timespec="seconds"),
                 egitim_suresi_sn=round(time.perf_counter() - t, 2), ornek=len(satirlar),
                 konu_sayisi=len(m.konu.classes_), kisi_sayisi=len(m.kisi.classes_),
                 cozum_notlu=sum(1 for s in satirlar if s["cozum_notu"]))
        _ob.koy(_ob.modeller, anahtar, (m, b), _ob.MODEL_SAYISI)
        return m


def bilgi(con: sqlite3.Connection) -> dict:
    model(con)
    with _ob.kilit:
        return dict(_ob.modeller[_veri_anahtari(con)][1])


# ---------------------------------------------------------------- değerlendirme

def _kural_konu(metin: str, kategoriler: list[dict], yedek: int) -> int:
    """Eski yöntem: konunun anahtar kelimelerinden ilki metinde geçiyorsa o konu."""
    k = kucult(metin)
    for kat in kategoriler:
        if any(a.strip() and kucult(a.strip()) in k for a in kat["anahtar_kelimeler"].split(",")):
            return kat["id"]
    return yedek


def degerlendir(con: sqlite3.Connection) -> dict:
    """Zaman bazlı test: en eski %80 ile eğit, en yeni %20'de ölç. Kural tabanlı yöntemle karşılaştır."""
    bugun = datetime.now().date().isoformat()
    anahtar = _veri_anahtari(con, once=bugun)
    with _ob.kilit:
        if anahtar in _ob.degerlendirmeler:
            return _ob.degerlendirmeler[anahtar]
    satirlar = [s for s in _egitim_verisi(con) if s["acilis"] < bugun] or _egitim_verisi(con)
    kes = int(len(satirlar) * (1 - TEST_PAYI))
    egitim, test = satirlar[:kes], satirlar[kes:]
    m = Model(egitim)
    kategoriler = [dict(r) for r in con.execute("SELECT id, ad, birim_id, anahtar_kelimeler FROM kategori WHERE kaynak='usta' ORDER BY id")]
    birim = {k["id"]: k["birim_id"] for k in kategoriler}
    kisi_birim = {r["id"]: r["birim_id"] for r in con.execute("SELECT id, birim_id FROM kisi")}
    kisi_vardiya = {r["id"]: r["vardiya"] for r in con.execute("SELECT id, vardiya FROM kisi")}
    en_sik = Counter(s["kategori_id"] for s in egitim).most_common(1)[0][0]

    # Kural yönteminin kişi seçimi: konuda (vardiyada) en çok çözen
    sayim = defaultdict(Counter)
    for s in egitim:
        sayim[s["kategori_id"]][s["cozen_kisi_id"]] += 1

    def kural_kisi(kat, vardiya):
        vd = [(p, n) for p, n in sayim[kat].most_common() if kisi_vardiya[p] == vardiya]
        return (vd or sayim[kat].most_common() or [(None, 0)])[0][0]

    sonuc = Counter()
    konu_dogru_guvenli = konu_guvenli = 0
    for s in test:
        olas = m.konu_olasiliklari(s["metin"])
        tahmin = olas[0][0]
        guvenli = olas[0][1] >= SORU_ESIGI and olas[0][1] - olas[1][1] >= FARK_ESIGI
        sonuc["konu_model"] += tahmin == s["kategori_id"]
        sonuc["konu_kural"] += _kural_konu(s["metin"], kategoriler, en_sik) == s["kategori_id"]
        if guvenli:
            konu_guvenli += 1
            konu_dogru_guvenli += tahmin == s["kategori_id"]
        # kişi: model, tahmin ettiği konunun biriminden (o vardiyada olanlar öne) sıralar
        pk = m.kisi_olasiliklari(s["metin"], tahmin, s["vardiya"], s["acan_birim"])
        aday = sorted((p for p in pk if kisi_birim.get(p) == birim[tahmin]), key=lambda p: -pk[p])
        sonuc["kisi_model"] += bool(aday) and aday[0] == s["cozen_kisi_id"]
        sonuc["kisi_model_ilk3"] += s["cozen_kisi_id"] in aday[:3]
        kk = kural_kisi(_kural_konu(s["metin"], kategoriler, en_sik), s["vardiya"])
        sonuc["kisi_kural"] += kk == s["cozen_kisi_id"]
        sirali = [p for p, _ in sayim[s["kategori_id"]].most_common(3)]
        sonuc["kisi_kural_ilk3"] += s["cozen_kisi_id"] in sirali
    n = len(test)
    politika = _politika_degerlendir(con, egitim, test, m, birim, kisi_birim, kisi_vardiya)
    d = dict(
        politika=politika,
        egitim=len(egitim), test=n,
        test_araligi=f"{test[0]['acilis'][:10]} – {test[-1]['acilis'][:10]}",
        konu=dict(model=round(sonuc["konu_model"] / n, 3), kural=round(sonuc["konu_kural"] / n, 3),
                  soru_orani=round(1 - konu_guvenli / n, 3),
                  emin_oldugunda=round(konu_dogru_guvenli / max(1, konu_guvenli), 3)),
        kisi=dict(model=round(sonuc["kisi_model"] / n, 3), model_ilk3=round(sonuc["kisi_model_ilk3"] / n, 3),
                  kural=round(sonuc["kisi_kural"] / n, 3), kural_ilk3=round(sonuc["kisi_kural_ilk3"] / n, 3)),
    )
    with _ob.kilit:
        _ob.koy(_ob.degerlendirmeler, anahtar, d, _ob.MODEL_SAYISI)
    return d


def _politika_degerlendir(con, egitim: list[dict], test: list[dict], m: Model, birim: dict, kisi_birim: dict,
                          kisi_vardiya: dict) -> dict:
    """Test çağrılarını üç yolla dağıtır ve karşılaştırır: gerçekte kim çözdü, model tek başına kimi
    seçerdi, model + paylaştırma kuralı kimi seçerdi. Ayrıca kalite ağırlığı olmayan modelle kıyaslar.

    Ölçüler:
      yetkin_oran   seçilen kişi eğitim döneminde o konuda en az 3 (seyrek konuda 2) çağrı çözmüş mü
      yogunlasma    her konuda en çok çağrı alan kişinin payı (çağrı sayısıyla ağırlıklı ortalama)
      tahmini_sure  seçilen kişinin o konudaki ortanca süresi (eğitim döneminden); konuda 2'den az
                    çözümü varsa konunun ortancasının 1,5 katı (alışık olmayan biri yavaş çözer)
    Model seçimleri gerçekte kimin çözdüğüyle karşılaştırılabilir; paylaştırma ise bilerek başka birini
    seçer, bu yüzden onun "isabet"i ölçü değildir.
    """
    from .risk import yetkin_esigi
    kritik = {r[0]: r[1] for r in con.execute("SELECT id, kritiklik FROM kategori")}
    son = egitim[-1]["acilis"]
    pencere = (datetime.fromisoformat(son) - __import__("datetime").timedelta(days=90)).isoformat(timespec="minutes")
    sayim = defaultdict(Counter)
    sureler = defaultdict(list)
    konu_sure = defaultdict(list)
    for s in egitim:
        if s["acilis"] >= pencere:
            sayim[s["kategori_id"]][s["cozen_kisi_id"]] += 1
        if s.get("sure_dk") and kisi_vardiya.get(s["cozen_kisi_id"]) == s["vardiya"]:
            sureler[(s["cozen_kisi_id"], s["kategori_id"])].append(s["sure_dk"])
            konu_sure[s["kategori_id"]].append(s["sure_dk"])

    def tahmini(kisi, kat):
        v = sureler.get((kisi, kat), [])
        if len(v) >= 2:
            return float(np.median(v))
        return float(np.median(konu_sure[kat])) * 1.5 if konu_sure[kat] else 60.0

    m0 = Model(egitim, kalite=False)
    yollar = {"gercek": [], "model": [], "model_agirliksiz": [], "politika": []}
    canli = defaultdict(Counter, {k: Counter(v) for k, v in sayim.items()})   # paylaştırma kendi kararlarıyla güncellenir
    for s in test:
        kat = s["kategori_id"]
        uygun = [p for p in kisi_birim if kisi_birim[p] == birim.get(kat)]
        vardiyada = [p for p in uygun if kisi_vardiya[p] == s["vardiya"]] or uygun
        for ad, mod in (("model", m), ("model_agirliksiz", m0)):
            pk = mod.kisi_olasiliklari(s["metin"], kat, s["vardiya"], s["acan_birim"])
            yollar[ad].append(max(vardiyada, key=lambda p: pk.get(p, 0.0)))
        pk = m.kisi_olasiliklari(s["metin"], kat, s["vardiya"], s["acan_birim"])
        esik = yetkin_esigi(sum(canli[kat].values()))
        sec = paylastirma_secimi([(p, pk.get(p, 0.0)) for p in vardiyada], canli[kat], esik,
                                 acil_kritik=(kritik.get(kat) == 3 and s.get("aciliyet") == 3))
        yollar["politika"].append(sec["kisi_id"])
        canli[kat][sec["kisi_id"]] += 1
        yollar["gercek"].append(s["cozen_kisi_id"])

    def olc(secimler):
        yetkin = sum(sayim[s["kategori_id"]].get(p, 0) >= yetkin_esigi(sum(sayim[s["kategori_id"]].values()))
                     for s, p in zip(test, secimler))
        konu = defaultdict(Counter)
        for s, p in zip(test, secimler):
            konu[s["kategori_id"]][p] += 1
        yog = sum(max(c.values()) for c in konu.values()) / len(test)
        sure = sum(tahmini(p, s["kategori_id"]) for s, p in zip(test, secimler)) / len(test)
        return dict(yetkin_oran=round(yetkin / len(test), 3), yogunlasma=round(yog, 3), tahmini_sure=round(sure, 1),
                    isabet=round(sum(p == s["cozen_kisi_id"] for s, p in zip(test, secimler)) / len(test), 3))
    sonuc = {ad: olc(v) for ad, v in yollar.items()}
    sonuc["paylastirilan"] = round(sum(a != b for a, b in zip(yollar["politika"], yollar["model"])) / len(test), 3)
    return sonuc


# ---------------------------------------------------------------- nasıl çözüldü

def nasil_cozuldu(con: sqlite3.Connection, metin: str, kategori_id: int | None = None, n: int = 3) -> dict:
    """En benzer geçmiş çağrıların çözüm notlarını gruplar: hangi yol, kaç kez, kaç dakikada, kim."""
    m = model(con)
    komsu = m.komsular(metin, kategori_id, n=KOMSU * 2)
    gruplar: dict[str, dict] = {}
    for s, b in komsu:
        if not s["cozum_notu"]:
            continue
        g = gruplar.setdefault(s["cozum_notu"], dict(adimlar=s["cozum_notu"].split("\n"), kac_kez=0, sureler=[],
                                                      kisiler=Counter(), benzerlik=0.0, ornek=s["metin"]))
        g["kac_kez"] += 1
        g["sureler"].append(s["sure_dk"])
        g["kisiler"][s["cozen"]] += 1
        g["benzerlik"] += b
        g["puan"] = g.get("puan", 0.0) + b * b
    # Sıralama: benzerliğin karesiyle toplam. Çok benzer tek bir çağrı, az benzer birkaç çağrıdan öne geçer.
    yollar = sorted(gruplar.values(), key=lambda g: -g["puan"])[:n]
    for g in yollar:
        sureler = [x for x in g.pop("sureler") if x]          # süresi bilinmeyen çağrılar (yerel veride) sayılmaz
        g["ort_sure_dk"] = round(sum(sureler) / len(sureler)) if sureler else None
        g["kisiler"] = [ad for ad, _ in g["kisiler"].most_common(3)]
        g["benzerlik"] = round(g["benzerlik"] / g["kac_kez"], 2)
        del g["puan"]
    notsuz = sum(1 for s, _ in komsu if not s["cozum_notu"])
    return dict(
        yollar=yollar, bakilan=len(komsu), notsuz=notsuz,
        cagrilar=[dict(id=s["id"], metin=s["metin"], cozen=s["cozen"], sure_dk=s["sure_dk"],
                       benzerlik=round(b, 2), cozum_notu=s["cozum_notu"]) for s, b in komsu[:5]],
    )
