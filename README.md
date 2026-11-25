# Emanet + Usta

**Bilgi kişide kalmasın.** Usta, sistemsel destek çağrılarını (BT ve depo sistemleri) geçmiş
çağrılardan öğrenen bir makine öğrenmesi modeliyle yönlendirir: konuyu tahmin eder, vardiyada olan
en uygun kişiyi seçer ve sorunun daha önce nasıl çözüldüğünü gösterir. Emanet, bu çağrılarla bakım
sisteminden içe aktarılan teknik arıza dökümünü birlikte okuyup "kim giderse ne kırılır" haritasını
çıkarır ve çapraz eğitim planı önerir.

Veriler kurgusaldır: Yıldız Ev & Yaşam adlı hayali bir deponun 28 kişisi, 14 sistemsel ve 14 teknik
konusu, yaklaşık 900 Usta çağrısı ve 650 kayıtlık bir bakım dökümü bir üreticiyle oluşturulur.

## Ne yapar

| Modül | Soru | Cevap |
| --- | --- | --- |
| Usta | Bu çağrı hangi konu, kime gitmeli, daha önce nasıl çözülmüştü? | İki aşamalı form (konuya özel sorular, cevaplardan hesaplanan öncelik, "zaten bildirildi" uyarısı, "önce bunu dene"), konu modeli (emin değilse sorar), kişi modeli (izin ve vardiyaya göre), benzer çağrıların çözüm yolları |
| Otomasyon | Hangi çağrılar insansız çözülebilir? | Talep karşılama (Teams'ten soru ve onay), bilinen çözümü deneme, toplu arıza, kapanış teyidi, işe giriş/çıkış, notlardan reçete önerisi |
| Emanet | Hangi konu kimin elinde, o giderse ne olur, aldığımız önlem işe yaradı mı? | Risk haritası ve seyri, "ya giderse", devir süreci (aşamalar gerçek çağrıyla ölçülür, kartı devralan yazar, çıkışa yetişme kontrolü, tutanak), izin kontrolü, bütçeli eğitim planı, eski çağrılardan eğitim içeriği, haftalara yayılmış eğitim takvimi (Excel) ve takibi, kendi dökümünü yükleme |
| Değişimler | Sistem değişti, yeni biri geldi, otomasyon bozuldu: risk bunu nasıl görür? | Sistem geçişi (yeni konu, geçici puan, erken uyarı, geçiş adayları), çırak modu ve işe alışma, otomasyon sağlığı (otomatik askıya alma), gerçek ayrılış kaydı |

**Genel bakış** "Bugün neye bakmalı?" listesiyle açılır: yedeksiz kritik konular, askıdaki otomasyon,
yeni sistemde tek kişide toplanan bilgi, güncellenmeyen döküm, sahipsiz otomasyon. Her madde ilgili
ekrana götürür. Risk haritası birime ve seviyeye göre süzülür, Excel için indirilir.

**Otomasyon.** Yetki üç seviyelidir: otomatik (kilit açma, onarım adımları, işe giriş paketi), onaylı
otomatik (lisanslı yazılım, rol ekleme) ve yalnızca insan (katalog dışı talepler, taslak reçeteler).
Karar yazılı kurallardadır. Teams, kimlik sistemi ve kurulum aracı bu demoda simüle edilir; gerçek
kullanımda Intune/SCCM, Active Directory/Entra ID, MDM gibi araçlara bağlanır.

Usta yalnızca sistemsel çağrılara bakar; teknik arıza yazılırsa (sorter, forklift…) bakım sistemine
yönlendirir. Emanet'in haritası beyana değil, işi fiilen kimin çözdüğüne dayanır.

**Model başarısı** (en yeni 180 çağrıda, eğitimde görülmeden): konu %91 (eski anahtar kelime
kuralı %64), çözen kişi ilk sırada %63 (kural %52), ilk üçte %92 (kural %69). Veri sentetik
olduğu için gerçek çağrılarda konu doğruluğu daha düşük çıkar.

**Kime verilir?** Kişi modeli geçmişte kimin çözdüğünden öğrenir; bu "kime verilirdi"dir, "kim iyi
çözer" değil. Bu yüzden eğitim çağrıları çözüm kalitesine (süre, kapanış teyidi) göre ağırlık alır ve
son kararı açık bir kural verir: uzmanın üzerinde 3+ açık çağrı varsa ya da vardiyada konunun
%60'ından fazlasını tek başına çözüyorsa, çağrı konuyu bilen başka birine gider. Ölçümler ve dürüst
sonuç (demo verisinde fark küçük) `docs/HAKIMIYET.md` 2b bölümünde.

## Çalıştırma

```bash
python3 -m venv .venv && .venv/bin/pip install --require-hashes -r requirements-dev.txt
.venv/bin/python -m emanet           # http://localhost:8000
.venv/bin/python -m pytest -q        # testler
```

İlk açılışta demo verisi kendiliğinden üretilir. Bağımlılıklar sürüm ve özetle (hash) sabittir;
`requirements.in` değişince `pip-compile --generate-hashes --allow-unsafe` ile yeniden üretilir.

Docker ile tek başına: `docker compose up -d --build` → http://127.0.0.1:8090.
ysfdurak.com sunucusunda: [deploy/KURULUM.md](deploy/KURULUM.md).

## Güvenlik

Portföyün ortak güvenlik temeline göre kuruldu (ysfdurak.com → `docs/GUVENLIK_TEMELI.md`, Python: 3b).

- **Ziyaretçi demosu:** Her ziyaretçi ilk değişikliğinde ortak demonun kendine ait bir kopyasını alır
  (`HttpOnly`, `Secure`, `SameSite=Lax` çerezle). Ziyaretçiler birbirinin çağrılarını ve notlarını
  görmez. Kopya 24 saat yaşar, gece sıfırlamasında silinir; en çok 300 kopya, IP başına günde 20.
- **Tarayıcı:** Sayfa satır içi betik içermez; CSP `script-src 'self'`, `frame-ancestors 'none'`;
  nosniff, HSTS, Referrer-Policy, Permissions-Policy, X-Frame-Options, COOP. Kayıttan gelen her
  değer kaçışlanır (içe aktarılan dökümdeki betikli adlarla denendi). CSV dışa aktarımında formül
  enjeksiyonu önlenir.
- **Sunucu:** Yazma isteklerinde kaynak (Origin) denetimi, gövde sınırı (413), IP başına hız sınırı
  (429). Gerçek IP yalnız güvenilen vekilden alınır (`gercek_ip.py`; uvicorn vekil başlıklarını
  yorumlamaz). `/docs` ve OpenAPI kapalı. Beklenmeyen hatada genel ileti.
- **MCP:** Araçların bir kısmı veri değiştirdiği için anahtar ister (`EMANET_MCP_ANAHTARLARI`;
  bellekte SHA-256 özeti, sabit sürede karşılaştırma). Anahtar yoksa `/mcp` kapalıdır.
- **Konteyner:** Sabit Python imajı, root olmayan kullanıcı, `read_only`, `cap_drop: ALL`,
  `no-new-privileges`, bellek/süreç/kayıt sınırı, port açmadan ortak `web` ağı.
- **Depo:** Dependabot (pip, Docker, Actions), CI'da `permissions: contents: read`, testler ve
  `pip-audit`. Tarama: `python3 araclar/guvenlik/tara.py --audit ../emanet` (ysfdurak.com deposunda).

## Kendi verinle (yerelde)

Sitedeki demo kurgusal veriyle çalışır. Gerçek çağrılarla denemek için çağrı metinleri siteye
yüklenmez: metinlerde kişi, cihaz ve hesap bilgileri olur. Uygulama kendi bilgisayarında ya da
sunucunda kurulur, veri orada içe aktarılır ve makineden çıkmaz.

```bash
python -m emanet.yerel --ornek ornek.csv                 # biçimi görmek için örnek dosya
python -m emanet.yerel cagrilar.csv --takma-ad           # veri/yerel.db kurulur, rapor yazılır
python -m emanet.yerel cagrilar.csv --dokum bakim.csv    # teknik arıza dökümü de eklenir
EMANET_DB=veri/yerel.db python -m emanet          # http://localhost:8000
```

- **Sütunlar:** zorunlu olanlar tarih, metin, konu, birim, çözen. İsteğe bağlı olanlar süre (ya da
  kapanış), çözüm notu, vardiya, öncelik, kritiklik, açan birim, ilk atanan. Sütun adları esnektir:
  "Açıklama", "Kategori", "Destek grubu", "Çözen kişi", "Çözüm" tanınır.
- **`--takma-ad`:** Kişi adları (metinlerin içindekiler de) "Kişi 01"… olarak saklanır. Eşleşme
  listesi `veri/yerel_takma_adlar.csv` dosyasında, yalnızca bu makinede kalır.
- **`--bugune-kaydir`:** Eski bir dökümün tarihlerini, son kayıt bugün olacak şekilde kaydırır
  (risk haritası bugünden geriye 90 güne bakar).
- **Rapor:** Komut, modelin senin verindeki başarısını (eğitimde görülmemiş en yeni %20 çağrıda),
  risk özetini ve uyarıları (az çağrılı konular, çözüm notu oranı, eksik sütunlar)
  `veri/yerel_rapor.md` dosyasına yazar.
- **Yerel modda:** Demo verisi üretilmez ve sıfırlama kapalıdır. Demo senaryoları ve otomasyon
  örnekleri gizlenir; çağrı ekranındaki örnek cümleler kendi çağrılarından gelir.
- **Docker'da:** `docker compose run --rm -v $PWD:/girdi emanet python -m emanet.yerel /girdi/cagrilar.csv --db /veri/yerel.db`
  komutundan sonra `EMANET_DB=/veri/yerel.db` ile başlat.

## Yapı

Tek çekirdek, iki kapı. Web arayüzü ve MCP sunucusu aynı fonksiyonları çağırır; hiçbir kural iki
yerde yazılmaz.

```
emanet/
  katalog.py      Kurgusal şirketin tanımları: birimler, kişiler, konular, çağrı kalıpları
  db.py           SQLite şeması ve bağlantı (eski veritabanına eksik sütunları ekler)
  veri_uret.py    Sentetik veri üreticisi (aynı tohum → aynı veri); bakım dökümünü CSV olarak üretip içe aktarır
  ogrenme.py      Makine öğrenmesi: konu ve kişi modeli, kalite ağırlığı, paylaştırma, zaman bazlı test
  usta.py         Modelleri iş kurallarıyla birleştirir: kapsam, izin/vardiya, çırak, çağrı açma/kapama
  ice_aktar.py    Döküm (CSV) içe aktarma ve kaydetmeden analiz
  otomasyon.py    Reçeteler, yetki çerçevesi, Teams benzeri mesajlaşma, altı otomasyon akışı, sağlık
  risk.py         Risk puanı, ısı haritası, ya giderse, eğitim planı (kural + optimizasyon)
  takvim.py       Eğitim planını kişi başı haftalık sınırla haftalara ve günlere yerleştirir
  egitim.py       Eğitim içeriği eski çağrılardan (çözüm yolları, vakalar, oturum gündemi); konu süreleri
  devir.py        Devir süreci: aşamalar, kontrol listesi, görüşme, devir takvimi, tutanak
  cagri_formu.py  İki aşamalı çağrı formu: konuya özel sorular, öncelik hesabı, aynı sorun, kendin dene
  takip.py        İzin kontrolü, plan takibi, devir dosyası, risk seyri, reçete fırsatları, dikkat listesi
  degisim.py      Sistem geçişi, yeni personel ve işe alışma, gerçek ayrılış
  yerel.py        Kendi çağrı verinle yerel kurulum: içe aktarma, takma ad, rapor
  dil.py          Türkçe sayı ekleri (%67'sini, 3'ü)
  gercek_ip.py    Gerçek IP yalnız güvenilen vekilden
  api.py          Dış güvenlik katı, ziyaretçi demosu, web API (FastAPI)
  mcp_sunucu.py   MCP araçları (anahtarla)
  __main__.py     Başlatma: python -m emanet
web/              index.html (iskelet), app.js (ekranlar), stil.css
tests/            Çekirdek, API, güvenlik ve yerel kurulum testleri
deploy/           Ortak altyapı compose dosyası ve kurulum rehberi
docs/             PROJE.md (yaşayan doküman), HAKIMIYET.md (derin anlatım + sorular), VAKA_NOTU.md
```

## MCP

Sunucu çalışırken MCP adresi `/mcp` olur (Streamable HTTP) ve anahtar ister: Claude'da özel
bağlayıcı adresi `https://<alan>/mcp`, anahtar istek başlığında `Authorization: Bearer <anahtar>` (önerilen; `…/mcp/<anahtar>` da çalışır ama anahtar adreste görünür). Anahtarlar
`.env` içinde `EMANET_MCP_ANAHTARLARI` (virgülle, her biri en az 24 karakter; `openssl rand -hex 32`).
MCP ortak demo verisiyle çalışır, ziyaretçi kopyalarını görmez. 25 araç:

| Araç | Ne yapar |
| --- | --- |
| `cagri_ac` | Sistemsel çağrı açar; konu, atama ve çözüm yolunu döndürür. Etki ve kapsam verilirse öncelik hesaplanır; sorulmayan konu sorularını döndürür |
| `cihaz_gecmisi` | Bir yazıcı ya da terminalin kaydı ve son çağrıları; boşsa tekrar tekrar arızalanan cihazlar |
| `cagrilari_listele` | Birime, kişiye, duruma göre çağrılar |
| `nasil_cozuldu` | Bir sorun geçmişte nasıl çözülmüş, kaç kez, kim çözmüş |
| `cagriyi_kapat` | Çağrıyı çözüm notuyla kapatır (istenirse karta dönüştürür) |
| `model_basarimi` | Modellerin test sonucu ve kuralla karşılaştırması |
| `otomasyon_durumu` | Bekleyen Teams mesajları ve son otomasyon çalışmaları |
| `mesaja_cevap_ver` | Bir soruya ya da onay kartına cevap verir; otomasyon devam eder |
| `izin_kontrolu` | İzin onaylanmadan önce yedeksiz kalacak konular ve daha uygun tarih |
| `devir_dosyasi` | Ayrılan kişinin konuları, çözüm yolları, devralanlar (Markdown) |
| `plan_takibi` | Kayıtlı eğitim planı tuttu mu |
| `risk_seyri` | Riskin iki haftalık seyri ve alınan kararlar |
| `otomasyon_potansiyeli` | Reçeteler geçmişe uygulansaydı ayda kaç saat kazanılırdı, reçete adayları |
| `risk_haritasi` | Konu bazında risk puanları ve nedenleri |
| `tek_kisiye_kalanlar` | İzinler yüzünden yedeksiz kalan konular |
| `ya_giderse` | Bir kişi yoksa etki özeti |
| `egitim_plani_oner` | Saat bütçesiyle eğitim eşleşmeleri ve haftalık takvim |
| `egitim_icerigi` | Bir konunun eğitiminde ne gösterilir: çözüm yolları, örnek vakalar, gündem |
| `konu_sureleri` | Konuların kart yazma ve öğrenme süreleri (girilmemişse "tahmini") |
| `konu_suresi_ayarla` | Bir konunun sürelerini girer |
| `devir_baslat` | Ayrılan kişi için devir sürecini başlatır |
| `devir_durumu` | Devrin aşamaları, kontrol listesi, takvimi ve çıkışa yetişip yetişmediği |
| `degisimler` | Sistem geçişleri, yeni personelin işe alışması, otomasyon sağlığı |
| `ise_alisma` | Bir kişinin konu konu ilerlemesi, yetkinliğe ne kaldı |
| `gecis_kaydet` | Sistem geçişini kaydeder (eski konu kapanır, yeni konu açılır) |

Yerelde stdio ile: `python -m emanet.mcp_sunucu`

## Yapay zekâ kullanımı

Usta'daki öğrenme, sunucuda çalışan küçük modellerle (scikit-learn, lojistik regresyon) yapılır;
hiçbir veri dışarıdaki bir yapay zekâ servisine gitmez. Risk puanı açık bir formülle, eğitim planı
dinamik programlamayla hesaplanır. Her önerinin nedeni ekranda yazar. Büyük dil modeli yalnızca MCP
üzerinden soru soran taraftadır.

## Kapsam dışı

Gerçek şirket verisi, kullanıcı hesapları, bakım sistemiyle canlı bağlantı (döküm elle yüklenir) ve
gerçek Teams/kimlik/kurulum sistemlerine bağlantı bu sürümde yoktur; otomasyon bunları simüle eder.

## Lisans

Bu proje [PolyForm Shield 1.0.0](LICENSE.md) lisansıyla yayınlanır. Kaynak kodu açıktır, ancak resmi anlamda bir "açık kaynak" lisansı değildir.

- **Serbest:** Kişiler, okullar ve şirketler kendi işlerinde ücretsiz kullanabilir, değiştirebilir ve kendi bilgisayarlarına ya da sunucularına kurabilir. İzin almak gerekmez.
- **Yazılı izin gerekir:** Yazılımı satmak, adını değiştirip ürün gibi sunmak ya da bununla (ücretsiz olsa bile) rakip bir ürün veya hizmet sunmak.
- **Garanti yok:** Yazılım olduğu gibi sunulur. Bağlayıcı olan İngilizce lisans metnidir.
- Üçüncü taraf bileşenler kendi lisanslarına tabidir.
- Demo verisi (Yıldız Ev & Yaşam, kişi adları, çağrı metinleri) kurgudur ve aynı lisansla kullanılır.

Kurumunuzda kullanıyorsanız haber verirseniz sevinirim: kurulumda yardımcı olabilir, kurumunuza özel ihtiyaçları birlikte değerlendirebiliriz. Kurum içi kurulum, kendi çağrı verinizle (veri makineden çıkmaz) [Kendi verinle](#kendi-verinle-yerelde) bölümünde anlatılır. İletişim: iletisim@ysfdurak.com

### License (English)

Released under [PolyForm Shield 1.0.0](LICENSE.md). The source is available, but this is not an OSI "open source" licence.

- **Free:** individuals, schools and companies may use it in their own work, change it and run it on their own computers or servers. No permission needed.
- **Needs written permission:** selling it, rebranding it as a product, or providing a product or service that competes with it (even free of charge).
- **No warranty:** provided as is. The English licence text is binding.
- Third-party components keep their own licences.
- The demo data (Yıldız Ev & Yaşam, people's names, call texts) is fictional and covered by the same licence.

Using it in your organisation? I'd be glad to hear from you: I can help with setup and look at your organisation's needs together. An in-house setup with your own call data (the data never leaves your machine) is described under "Kendi verinle". Contact: contact@ysfdurak.com
