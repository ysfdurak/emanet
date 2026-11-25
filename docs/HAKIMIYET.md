# Hâkimiyet rehberi

Amaç: projeyi biri sorduğunda kodu açmadan anlatabilmek. Her bölümde önce "ne ve neden", sonra
kodda nereye bakılacağı, en sonda kendini sınama soruları var. Cevaplar belgenin sonunda.

## 30 saniyede proje

"Depoda iki tür destek çağrısı var: sistemsel (terminal, yazıcı, WMS, ERP) ve teknik (sorter,
forklift). Usta sistemsel çağrılara bakıyor: geçmiş çağrılardan öğrenen bir modelle konuyu tahmin
ediyor, vardiyada olan en uygun kişiyi seçiyor ve bu sorunun daha önce nasıl çözüldüğünü gösteriyor.
Emanet bu çağrılarla bakım sisteminin dökümünü birlikte okuyup hangi konunun tek kişiye kaldığını
puanlıyor, o kişi giderse ne olacağını hesaplıyor ve eğitim saatini en iyi nereye harcayacağını
çıkarıyor. Veri dışarı çıkmıyor; model sunucunun içinde çalışıyor."

## 1. Veri (db.py, katalog.py, veri_uret.py, ice_aktar.py)

**İki kaynak, tek tablo:** `cagri` tablosundaki `kaynak` sütunu kaydın nereden geldiğini söyler.
`usta` olanlar Usta'da açılıp kapanan çağrılardır: metni, vardiyası ve çoğunun çözüm notu vardır.
Diğerleri içe aktarılan dökümdür: yalnızca konu, çözen, tarih, süre.

**Neden teknik çağrılar ayrı:** sahada sistemsel çağrılar BT'ye, teknik arızalar bakım sistemine
gider. Usta'nın işi yönlendirmek; teknik arızayı yönlendirmek onun işi değil. Ama "kim neyi biliyor"
sorusu iki tarafta da geçerli, bu yüzden Emanet ikisini birlikte okur.

**Alt sorunlar:** her Usta konusu birkaç alt sorundan oluşur. Örneğin yazıcı konusunda "ribon
bitti", "yazıcı çevrimdışı" ve "baskı soluk" ayrı alt sorunlardır; her birinin kendi cümle kalıbı,
kendi çözüm yolu ve çoğu zaman kendi uzmanı var. Model kişiyi konudan değil, bu ayrıntıdan öğrenir.

**Gerçekçilik için eklenenler:** çağrıların %6'sı ayrıntısızdır ("Sistem hata veriyor"), %15'inde
yazım hatası vardır. Tek uzmanlı konularda (sipariş dalgası, ERP) uzman çözüm notunu az yazar.

**Döküm:** bakım verisi üreticide CSV olarak yazılır ve gerçek bir döküm gibi `ice_aktar.yukle()`
ile alınır. Yani içe aktarma yolu her gün kendi demo verisiyle sınanır.

Sorular:
1. Emanet neden kendi veri tablosuna ihtiyaç duymuyor?
2. Tohum (seed) ne işe yarıyor, neden sabit?
3. Teknik arızalar neden Usta'da değil de döküm olarak geliyor?

## 2. Usta: makine öğrenmesi (ogrenme.py)

Üç şey öğrenilir. Hepsi kapalı Usta çağrılarından.

**Konu modeli (metin → konu).**
1. Metin 3-5 harflik parçalara bölünür: "yazıcı" → "yaz", "azı", "zıc", "ıcı", "yazı"…
   Türkçe ekler ve yazım hataları böylece sorun olmaz: "terminali" ile "termnal" çoğu parçayı paylaşır.
2. **TF-IDF:** her parçaya ağırlık verilir. Az konuda geçen parça (örneğin "ribon"un parçaları) çok
   konuda geçenden ("çalışmıyor") daha değerlidir.
3. **Lojistik regresyon:** her konu için parçaların ağırlıklarını öğrenir ve yeni metin için her
   konuya bir olasılık üretir (toplamı 1).
4. En yüksek olasılık %45'in altındaysa ya da ikinci aday 12 puandan yakınsa sistem tahmin etmez,
   sorar.
5. **Belirleyici sözcükler:** her sözcük metinden tek tek çıkarılır; konunun puanı en çok düşenler
   ekranda "belirleyici" diye gösterilir.

**Kişi modeli (metin + konu + vardiya + açan birim → kim çözer).** İkinci bir lojistik regresyon.
Atama sırasında model önce herkese bir olasılık verir; sonra izindekiler ve vardiyada olmayanlar
elenir, kalanlar arasından en yüksek olasılıklı kişi seçilir. Modelin ilk sıradaki kişisi müsait
değilse ekranda "bu tür çağrıları en çok X çözüyor ama şu an vardiyada değil" notu çıkar.

**Nasıl çözüldü.** Aynı konudaki en benzer 30 geçmiş çağrı bulunur (benzerlik: iki metnin TF-IDF
vektörleri arasındaki kosinüs). Çözüm notu aynı olanlar gruplanır. Sıralama benzerliğin karesiyle
yapılır: çok benzer tek bir çağrı, az benzer birkaç çağrının önüne geçer.

**Öğrenme döngüsü.** Kapanan her çağrı modeli yeniden eğitir (bu veride bir saniyeden kısa).
Yanlış yönlenen çağrı düzeltilip kapanınca düzeltilmiş hâliyle öğrenmeye girer. Not yazılmazsa
çağrı konu ve kişi modeline katkı verir ama "nasıl çözüldü"ye girmez.

**Nasıl ölçülüyor.** Çağrılar tarihe göre sıralanır; en eski %80 ile eğitilir, en yeni %20'de
ölçülür. Rastgele bölmek yerine zamana göre bölmek, modelin geleceği tahmin etme gücünü ölçer.
Karşılaştırma için eski kural: "konunun anahtar kelimesi geçiyorsa o konu" ve "o vardiyada konuyu en
çok çözen kişi".

| Soru | Model | Eski kural |
| --- | --- | --- |
| Konu doğru mu? | %93 | %80 |
| Çözen kişi ilk sırada mı? | %62 | %53 |
| Çözen kişi ilk üçte mi? | %93 | %67 |

**Dürüst olman gereken iki nokta:** konu doğruluğu sentetik veride yüksek çıkıyor çünkü cümleler
sınırlı kalıplardan üretildi; gerçek veride düşer. Kişi tahmininde %100 beklenmez, çünkü aynı
türdeki çağrıyı o gün kim boştaysa o çözer.

Sorular:
4. "Sistem hata veriyor" yazınca sistem neden soru soruyor?
5. Harf parçaları yerine bütün sözcükler kullanılsaydı ne bozulurdu?
6. Test kümesi neden rastgele değil de tarihe göre ayrıldı?
7. Model bir kişiye %98 diyor ama çağrı başkasına gidiyor. Neden?

## 2b. Kişi modeli: "kime verilirdi" değil "kim iyi çözer" (ogrenme.py → kalite_agirliklari, paylastirma_secimi)

Kişi modelinin öğrendiği etiket "bu çağrıyı kim çözdü"dür. Ama geçmişte kimin çözdüğü, kimin iyi
çözdüğü değil, kime verildiğidir. İş hep aynı kişiye gittiyse model de onu önerir; Usta, Emanet'in
azaltmaya çalıştığı bağımlılığı besler. İki düzeltme yapıldı:

1. **Kalite ağırlığı.** Her eğitim çağrısı `konunun ortanca süresi / bu çağrının süresi` kadar
   ağırlık alır (0,5 ile 1,5 arası); açan kişi "çözüldü" dediyse ×1,1. Yavaş çözülenler az sayılır.
   Ortanca eğitim verisinin kendisinden hesaplanır, test çağrıları sızmaz.
2. **Model yetkinliği söyler, kural kime verileceğine karar verir.**
   - *İş yükü:* modelin seçtiği kişinin üzerinde 3 ya da daha fazla açık çağrı varsa, konuyu bilen
     ve daha boş biri seçilir. Olasılığı açık çağrı sayısıyla cezalandırmak işe yaramadı: geçmiş
     atamalar yüzünden olasılık uzmanda %80-90'a yığılıyor, ceza onu geçemiyor. Açık bir kural daha dürüst.
   - *Paylaştırma:* vardiyada konunun %60'ından fazlasını tek kişi çözüyorsa çağrı, konuyu bilen
     (son 90 günde en az 3 çözüm) başka birine verilir; uzman yedekte kalır. Böylece yedeklerin pratiği
     de körelmez. Acil ve kritik çağrıda yapılmaz. Paylaştırma kendini dengeler: pay %60'ın altına
     inince durur.
   - Önce çırak modu, sonra paylaştırma bakılır. Açılıp kapatılabilir (Öğrenme ekranı).

**Nasıl ölçüldü?** Paylaştırma bilerek başka birini seçtiği için "doğru kişiyi tahmin etti mi"
(isabet) onun ölçüsü değil. Test çağrıları dört yolla dağıtılıp üç ölçüyle karşılaştırıldı:
konuyu bilen kişiye gitme oranı, tek kişide toplanma (her konuda en çok alan kişinin payı) ve
tahmini çözüm süresi. Demo verisinde sonuç:

| Yol | Bilene | Toplanma | Süre | İsabet |
| --- | --- | --- | --- | --- |
| Gerçekte | %89 | %40 | 26,5 dk | - |
| Model, ağırlıksız | %89 | %41 | 26,9 dk | %62 |
| Model, kalite ağırlıklı | %88 | %42 | 26,7 dk | %63 |
| Model + paylaştırma | %87 | %41 | 26,8 dk | çağrıların %3'ü başka birine |

**Dürüst sonuç:** fark küçük ve bunun iki nedeni var. Sentetik veride hızlı çözen zaten en çok
çözen kişi; kalite ağırlığının ayıracağı bir şey az. Asıl bağımlılık da vardiyada hiç yedeği olmayan
konulardan geliyor (sipariş dalgası, ERP); paylaştırma ancak konuyu bilen ikinci biri varsa çalışır.
Oraya çare eğitim planı ve çırak modu. Bu düzeltmeler gerçek veride, işi alanla iyi çözenin
ayrıştığı durumlarda (yavaş ya da yeniden açılan çözümler) daha çok fark yaratır. Yöntem bu yüzden
kaldı ama sayılarla abartılmadı.

**Seçilmeyen yollar:** Derin öğrenme bu veri boyutunda (yüzlerce-binlerce çağrı) daha iyi sonuç
vermez, açıklanması zorlaşır. Büyük bir dil modeline sınıflandırma yaptırmak kolaydır ama şirket
verisinin dışarı gitmesi gerekir. Gerçek veri gelince eklenebilecek olan: sunucuda çalışan küçük çok
dilli bir cümle modeliyle (sentence-transformers) anlam benzerliği; "çıktı alamıyorum" ile
"yazdırmıyor"u aynı sorun olarak tanır. Mevcut yöntemin yerine değil, yanına.

Sorular:
33. Kişi modelinin isabeti neden "doğru atama" demek değil?
34. Paylaştırmayı ölçerken neden isabet kullanılmadı?
35. Paylaştırma neden sipariş dalgası konusunda hiç devreye girmiyor?

## 3. Usta: iş kuralları (usta.py)

Model tahmin eder, `usta.py` karar verir:
- Teknik bir arıza yazılmışsa (sorter, forklift, konveyör…) ve model emin değilse çağrı kapsam
  dışı sayılır; ekran bakım sistemine yönlendirir.
- Konu belirsizse çağrı açılmaz; kullanıcı konuyu seçmelidir.
- İzinde ya da vardiya dışında olan kişiye atama yapılmaz.

Sorular:
8. Model neden doğrudan "kişiyi" seçmiyor, araya `usta.py` neden giriyor?

## 3b. Otomasyon (otomasyon.py)

**Ana fikir:** makine öğrenmesi yalnızca "bu ne tür bir çağrı" sorusunu cevaplar. "Bunu otomatik
yapabilir miyiz" kararını her zaman yazılı kurallar verir. Bir yöneticiye anlatırken bu ayrımı öne çıkar.

**Reçete:** bir otomasyonun tarifi. İçinde hangi konuya uyduğu, hangi bilgilere ihtiyaç duyduğu,
yetki seviyesi, adımlar, her adımın kontrolü, geri alma yolu ve hangi araçla yapılacağı vardır.

**Yetki seviyeleri:**

| Seviye | Ne demek | Örnek |
| --- | --- | --- |
| Otomatik | Kendi başına yapar | Kilit açma, yazıcı onarımı, işe giriş paketi |
| Onaylı otomatik | Yöneticinin Teams onayından sonra yapar | Lisanslı yazılım, rol ekleme |
| Yalnızca insan | Önerir, yapmaz | Katalog dışı yazılım, taslak reçeteler |

**Altı akış:**
1. **Talep karşılama (kurulum, yetki, kilit):** metinden bilgi çıkarılır (yazılım adı, PC-1234 gibi
   cihaz kodu, rol). Eksik bilgi talep edene Teams'ten sorulur. Kontroller: katalogda mı, cihaz o
   kişiye mi kayıtlı, boş lisans var mı. Gerekiyorsa yöneticiye onay kartı gider. Sonra işlem, sonra
   doğrulama, sonra çağrı kendiliğinden kapanır. Bir kontrol takılırsa çağrı insana kalır ve nedeni yazılır.
2. **Bilinen çözümü deneme (yazıcı, rapor, terminal):** önce teşhis, sonra adımlar sırayla. Her
   adımdan sonra kontrol: tuttuysa dur, tutmadıysa sıradakine geç. Hiçbiri tutmazsa çağrı,
   denenenlerin listesiyle insana kalır; uzman aynı adımları tekrar denemez.
3. **Notlardan reçete adayı:** aynı çözüm notu 8 ve daha fazla kez yazılmışsa öneri çıkar. Çevrilen
   reçete taslaktır ve çalıştırılmaz. Sebep: "kuyruğu temizle" cümlesini bir programın çalıştırabilmesi
   için hangi sistemde hangi komutun çalışacağını birinin tanımlaması gerekir.
4. **Toplu arıza:** aynı konuda, aynı yerde, son 60 dakikada en az 3 farklı kişiden çağrı gelirse
   tek olayda birleşir. Talepler (kurulum, yetki, şifre) birleşmez; onlar arıza değil.
5. **Kapanış teyidi:** her kapanışta açan kişiye "çözüldü mü?" sorulur. "Hayır" derse çağrı yeniden
   açılır, o çözüm notu silinir (öğrenmeye girmez) ve reçetenin "tutmadı" sayacı artar.
6. **İşe giriş/çıkış:** İK kaydı yetki belgesi sayılır. Göreve göre roller, terminal, e-posta ve
   yazılımlar tek seferde açılır. Çıkışta hesaplar kapanır, lisanslar havuza döner; cihaz iadesi
   fiziksel iş olduğu için insana kalır.

**Potansiyel hesabı:** reçeteler son 180 günün çağrılarına uygulanır. Ayda kaç çağrıya uyduğu ×
beklenen başarı oranı × bir çalışanın o işe harcadığı süre = ayda kazanılan saat. Onarımlarda beklenen
başarı, adımların tutma olasılıklarından hesaplanır: 1 − (1 − p1)(1 − p2)… Taleplerde %85 varsayılır.

**Dürüst sınır:** Teams, kimlik sistemi ve kurulum aracı simüle. Gerçekte her adım bir API çağrısı
olur ve BT'nin bu bağlantıları açması gerekir. Projenin değeri entegrasyonda değil, neyin otomatik
yapılabileceğini belirleyen çerçevenin tasarımında.

**Bu işi yapan gerçek ürünler:** ServiceNow (Virtual Agent ve Teams entegrasyonu), Moveworks (Teams
ve Slack üzerinden talep karşılama), Jira Service Management (Playbooks). İşlemi yapan araçlar
Intune/SCCM, Active Directory/Entra ID, MDM ve betik çalıştırıcılardır.

Sorular:
19. Makine öğrenmesi neden "otomatik yap" kararını vermiyor?
20. Notlardan çıkan reçete neden hemen çalıştırılmıyor?
21. Kullanıcı "çözülmedi" derse sistemde neler değişir?
22. Üç kişi aynı anda kurulum istedi. Neden toplu arıza sayılmıyor?

## 4. Emanet: risk puanı (risk.py → puan_hesapla, risk_haritasi)

```
puan = 100 × (0,45 × yoğunlaşma + 0,35 × yedek riski + 0,20 × yazısızlık) × kritiklik çarpanı
```

| Bileşen | Tanım |
| --- | --- |
| Yoğunlaşma | Son 90 günde konuyu en çok çözen kişinin payı |
| Yedek riski | Konuyu en az 3 kez çözmüş kişi sayısı: 0-1 → 1,0 · 2 → 0,5 · 3 → 0,2 · 4+ → 0 |
| Yazısızlık | Çözüm kartı yoksa 1 |
| Kritiklik çarpanı | 1 → 0,6 · 2 → 0,8 · 3 → 1,0 |

60 ve üzeri kırmızı, 35-59 sarı, altı yeşil.

**Örnek (Sipariş dalgası):** yoğunlaşma 0,97, yetkin 1 kişi (yedek riski 1,0), kart yok (1),
kritiklik 3. 100 × (0,45×0,97 + 0,35 + 0,20) × 1,0 ≈ 99.

**Yazılı çözüm:** Usta konularında çözüm kartı, dökümde "talimat_var" işareti. Çağrılara düşülen
çözüm notları puanı değiştirmez (dağınık ve doğrulanmamış), ama not oranı düşükse nedenlere
"çözümlerin yalnızca %24'ine not düşülmüş" diye yazılır.

**İki ince nokta:**
- Seyrek konularda (90 günde 9'dan az çağrı) yetkin sayılma eşiği 2'ye iner; yoksa nadir ama
  kritik konularda hiç kimse yetkin görünmez.
- Ağırlıklar (0,45 / 0,35 / 0,20) bir tercihtir, veriyle kanıtlanmış bir gerçek değil. Sorulursa
  böyle söyle: "Önceliği bağımlılığa verdim; kurum isterse tek satırda değişir."

Sorular:
9. Bir konunun kartı var, 4 kişi düzenli çözüyor, kritikliği 3. Puanı kabaca kaç olur?
10. Kâğıtta 5 kişi yetkin, haritada 1. Bu farkı sistem nereden çıkarıyor?
10b. Çözüm notları neden puana dahil değil?

## 5. Emanet: ya giderse (risk.py → ya_giderse)

Kişinin çözümleri yok sayılıp harita yeniden hesaplanır. Sonra her konu için:

- Beklenen çağrı = günlük çağrı × gün × kişinin o konudaki payı
- Süre çarpanı = geride yetkin biri varsa 1,1 · yoksa ama kart varsa 1,5 · ikisi de yoksa 2,5
- Ek bekleme = beklenen çağrı × temel çözüm süresi × (çarpan − 1)
- TL etkisi = ek bekleme dakikası × kullanıcının girdiği dakika maliyeti

Çarpanlar varsayımdır ve ekranda açıkça yazar. Kural: bir kişinin gidişi hiçbir konunun puanını
düşürmez (yoğunlaşma, gidiş öncesi değerin altına inmez).

Sorular:
11. Çözüm kartı "ya giderse" sonucunu nasıl değiştiriyor?
12. TL rakamı neden varsayılan olarak kapalı?

## 6. Emanet: eğitim planı (risk.py → egitim_plani)

Her konu için seçenekler: kart yazdır (2 saat), 1 kişi eğit, 2 kişi eğit ve bunların birleşimi.
Her seçeneğin bir saati ve bir kazancı var.

- **Basit kural:** her adımda "saat başına en çok kazandıran" adımı seç, bütçe bitene kadar.
- **Optimizasyon:** çok seçenekli sırt çantası problemi. Her konudan en fazla bir seçenek
  alınır; toplam saat bütçeyi aşmadan toplam kazancı en büyük yapan birleşim dinamik
  programlamayla bulunur (`dp[b]` = b saatle ulaşılabilen en iyi kazanç).

**Kazanç tanımı:** önce yeşil sınırının (35) üzerindeki risk düşüşü, artı sınırın altındaki
düşüşün onda biri. Bu yüzden plan önce kırmızıları söndürür; yoksa ucuz ve önemsiz konulara
giderdi. (İlk denemede öyle oldu: sorter 120 saate kadar eğitim alamadı. Amaç fonksiyonu bu
yüzden değişti.)

**Kişi seçimi:** öğreten konuyu en çok çözen; öğrenen aynı birimden, önce o konuda bilen
sayısı en az olan vardiyadan, sonra planda en az saati olan kişi.

**Varsayım:** eğitilen kişi konuyu diğer yetkinlerle eşit paylaşır.

Sorular:
13. Basit kural neden her zaman en iyi sonucu vermez? Bir örnek düşün.
14. Amaç fonksiyonu yalnızca "toplam puan düşüşü" olsaydı ne olurdu?

## 6b. Emanet: görmekten ölçmeye (risk.py, takip.py)

İlk sürüm riski gösteriyordu. Bu bölümdeki altı ekleme döngüyü kapatır: riski gör → karar al → sonucu ölç.

| Ekleme | Ne yapar | Kodda |
| --- | --- | --- |
| Otomasyon riske bağlandı | Reçete (taslak dahil) "yazılı çözüm" sayılır. Otomasyonla kapanan pay kişiye bağlı olmadığı için yoğunlaşma ve yedek bileşenleri (1 − pay) ile çarpılır. Riskli konularda sık tekrar eden not varsa "reçeteye çevir" fırsatı çıkar. | `risk.puan_hesapla`, `otomasyon.otomasyon_paylari`, `takip.otomasyon_firsatlari` |
| İzin kontrolü | İzin onaylanmadan önce kişinin bildiği her konuda o tarihlerde geride kim kalıyor? Diğer izinler de hesaba girer. Sorunluysa önümüzdeki 60 günde daha uygun aralığı arar; hiç yedek yoksa "tarih kaydırmak çözmez" der. | `takip.izin_kontrol` |
| Plan takibi | Plan kaydedilince her satırın sonucu ölçülür: öğrenen plan tarihinden sonra o konuda 3 çağrı çözdü mü, kart yazıldı mı? Tutma oranı ve hedef puana inen konu sayısı. | `takip.plan_takibi` |
| Bilginin eskimesi | 91-365 gün önce en az 3 kez çözüp son 60 günde hiç çözmeyen kişi "pratiği kalmamış yedek". Puana girmez, nedenlerde yazar; plan bu kişileri öğrenme süresinin üçte biriyle tazeler. | `risk.pratigi_kalmayanlar`, `risk._ogrenme_maliyeti` |
| Devir dosyası | Ayrılan kişinin konuları, kritik olanlar, bildiği çözüm yolları, açık işleri ve her konu için önerilen devralan. Markdown olarak indirilir. | `takip.devir_dosyasi` |
| Risk seyri | Her iki haftada bir, o tarihten geriye 90 günle hesaplanan harita. Kararlar (plan, reçete, kart) grafikte işaretli. | `takip.risk_seyri` |

**İki dürüst not:**
- Plan takibindeki "30 gün sonrasını simüle et" bir demo aracıdır: planı 30 gün geriye tarihler ve o
  dönemin çağrılarını üretir. Satırların bir kısmı bilerek tutmaz (öğrenenlerin %25'i başlamaz, kartların
  %15'i yazılmaz); gerçek hayatta da plan her zaman tam uygulanmaz.
- Seyir grafiği yalnızca 90 günlük penceresi verinin tamamen içinde kalan tarihleri gösterir. Yoksa ilk
  noktalar eksik veriyle yapay olarak yüksek çıkar.

**Devralan önerisi sırası:** konuda yetkin başka biri → pratiği kalmamış eski yedek → kâğıtta yetkin
görünen biri → konuyu birkaç kez çözmüş biri → birimden biri (sıfırdan eğitim).

Sorular:
23. Otomasyon payı neden yazısızlık bileşenini değil de bağımlılık bileşenlerini azaltıyor?
24. İzin kontrolünde "tarih kaydırmak çözmez" mesajı ne zaman çıkar?
25. Pratiği kalmamış yedek neden puanı değiştirmiyor da planı değiştiriyor?
26. Seyir grafiğinde ilk tarih neden verinin başı değil?

## 6c. Değişimler (degisim.py, usta.py → çırak modu, otomasyon.py → sağlık)

Risk haritası geçmişe bakar. Üç durumda geçmiş yanıltır ya da hiç yoktur; bu bölüm onları kapatır.

**Sistem geçişi.** `gecis_kaydet` eski konuya kapanış tarihi (`emeklilik`), yeni konuya başlangıç
tarihi (`acilis`) yazar ve geçiş tablosuna bir satır ekler. Açık çağrılar yeni konuya taşınır.
- Harita o tarihte geçerli konulara bakar: geçiş gününden önceki bir tarih için eski konu görünür,
  sonrası için yeni konu. Risk seyri de böylece doğru kalır.
- Yeni konu ilk 60 gün (ya da 10 çağrıya kadar) "yeni"dir. Puanı **geçicidir**: kâğıtta yetkin
  olanlar ve anahtar kullanıcılar 3 çözümlü sayılır (`risk.etkin_sayim`).
- **Erken uyarı:** en az 5 çağrıda tek kişinin payı %60'ı geçerse geçici puan bırakılır, gerçek veriyle
  hesaplanır ve "bilgi tek kişide toplanıyor" yazılır. Geçişlerde bilgi genelde kurulumu yapan kişide
  kalır; bunu ilk haftalarda yakalamak, aylar sonra fark etmekten ucuzdur.
- **Geçiş adayları:** eski konuda geçiş gününden önceki 90 günde yetkin olanlar. Planda yeni sistemi
  öğrenme süreleri yarıdır (`GECIS_ORANI`).
- **Model:** eski konunun çağrıları konu modelinde yeni konunun etiketiyle öğrenilir (sorunlar aynı,
  sistem yeni). Kişi modelinde bu eski çağrıların ağırlığı 0,4'tür. Kapanan konu önerilmez; ona çağrı
  açmak istenirse yerine hangi konunun geldiği söylenir.
- Eski konuya bağlı reçeteler yeni sistemde çalışmaz ("eski sisteme bağlı") ve dikkat listesine düşer.

**Yeni personel ve çırak modu.** Yeni gelen kimse yedek sayılmaz. Ama model geçmişte kimin çözdüğüne
bakarak yönlendirdiği için yeni kişiye hiç çağrı gitmez, kişi pratik kazanamaz: kısır döngü.
`usta._cirak_sec` şu koşullarda çağrıyı öğrenene verir:
- konu kritik değil (kritiklik < 3) ve çağrı acil değil (aciliyet < 3),
- aynı vardiyada konuyu bilen bir usta var (takılırsa o destek olur),
- öğrenen son 90 günde işe girmiş ya da eğitim planında o konunun öğreneni,
- üzerinde 2'den az açık çağrı var.
`ise_alisma` her konuda kaç çözüm olduğunu ve yetkinliğe kaç kaldığını gösterir.

**Otomasyon sağlığı.** Reçetenin son 30 gündeki gerçek başarısı ölçülür. En az 5 denemede risk
hesabı beklenen yerine gerçek başarıyı kullanır; beklenenin 25 puan altı "düşüşte", en az 8 denemede
%40'ın altı **askıya alma**: reçete yeni çağrılarda çalışmaz, otomasyon indirimi riskten çıkar.
"Yeniden devreye al" ölçümü sıfırdan başlatır.

**Ayrılış.** `kisi_ayrildi` kişiyi pasif yapar, açık çağrılarını yeniden yönlendirir, plandaki
görevlerini siler, sahibi olduğu reçeteleri sahipsiz bırakır (dikkat listesine düşer).

**Denetimden çıkan eklemeler:**
- *Otomasyonun sahibi:* her reçetenin bakımını yapan biri var. "Ya giderse" ve devir dosyası artık
  kişinin çözdüğü konular yanında bakımını yaptığı otomasyonları da gösterir. Otomasyon riski
  azaltır ama yeni bir tek kişiye bağımlılık doğurabilir.
- *Veri tazeliği:* döküm 14 günden uzun süredir gelmiyorsa uyarı. Güncellenmeyen döküm son haftaların
  çözümlerini eksik bırakır; yetkinler azalmış görünür, risk yapay olarak yükselir.
- *Yanlış toplu arıza:* yer yazılmamış bir çağrı, farklı yerlerden gelen çağrılarla aynı arıza
  sayılıp birleştiriliyordu (üç ayrı rampadaki üç ayrı yazıcı). Artık yalnızca yer yazılmamış
  çağrılarla birleşir.
- *Dikkat listesi, süzme, CSV indirme, geri tuşu, Türkçe sayı ekleri* (`dil.py`).

Sorular:
27. Yeni konunun puanı neden ilk günlerde gerçek veriyle değil beyanla hesaplanıyor? Ne zaman bırakılıyor?
28. Çırak modunda neden kritik konular ve acil çağrılar öğrenene gitmiyor?
29. Askıya alma neden kendiliğinden, insan onayı beklemeden yapılıyor?
30. Eski konunun çağrılarıyla yeni konuyu öğrenmenin riski ne?
31. Otomasyon riski düşürüyorsa neden "sahip" ayrıca izleniyor?
32. Döküm güncellenmezse risk neden düşmez de yükselir?

## 6d. Kendi verinle yerelde (yerel.py)

Gerçek veriyle deneme sitede değil, kullanıcının kendi makinesinde yapılır. Bunun nedeni projenin
ilkesi: şirket verisi dışarı çıkmaz. Çağrı metinlerinde kişi, cihaz ve hesap bilgisi olur; bunları
kişisel bir siteye yüklemek ne ziyaretçi için doğru olur ne de site sahibi için. Risk dökümü (metinsiz)
ise sitede bellekte analiz edilebiliyor; o ayrı.

Akış:
1. `oku` CSV'yi okur. Ayraç kendiliğinden bulunur, sütun adları eşanlamlı listesiyle eşleşir
   ("Süre (dk)" → `sure_dk`). Hatalı satırlar atlanır ve listelenir.
2. `usta_yukle` boş veritabanına birimleri, kişileri, konuları ve çağrıları yazar.
   - Kişinin birimi ve vardiyası kayıtlarında en sık geçenden çıkar.
   - Konunun anahtar kelimeleri metinlerden çıkarılır: o konuda sık, diğerlerinde seyrek geçen
     sözcükler. Eski kural yöntemi ve modelin henüz görmediği yeni konular bunları kullanır.
3. `--takma-ad` adları "Kişi 01"… yapar ve metinlerin içindeki adları da değiştirir.
4. `kur` modeli eğitir, zaman bazlı testi çalıştırır ve sonucu rapora yazar. Veritabanına
   `mod=yerel` işareti konur; API bunu görünce gece sıfırlamasını ve demo senaryolarını kapatır.

Kurallar:
- En az 50 çağrı, iki konu ve iki kişi olmalı; anlamlı sonuç için 300'den fazla çağrı önerilir.
- 5'ten az çağrısı olan konular, notu az olan veri, kritiklik ya da süre sütunu eksikliği raporda
  uyarı olarak yazılır.
- Daha önce bu komutla kurulmamış bir veritabanının üzerine yazılmaz (demo verisi korunur).

Sorular:
36. Neden sitede çağrı yükleme yok da risk dökümü yükleme var?
37. Süre sütunu yoksa ne çalışmaz?
38. Sentetik veride %91 çıkan konu doğruluğu gerçek veride neden düşebilir, rapor bunu nasıl gösterir?

## 6e. Eğitim içeriği, devir süreci ve çağrı formu (egitim.py, devir.py, cagri_formu.py)

Üçü de aynı eleştiriden çıktı: ekran "ne" diyordu ama "nasıl" demiyordu ve sahada iş öyle yürümüyordu.

- **Eğitim içeriği:** kapanmış çağrıların çözüm notları ilk adımlarına göre gruplanır (çözüm yolları);
  her yoldan bilgi veren bir vaka seçilir. Gündem: kartı oku → vakalar → birlikte uygulama. Süreler
  kullanıcıdan gelir; girilmemişse "tahmini" yazılır (veriden çıkmayan sayı veri gibi gösterilmez).
- **Devir:** rapor değil süreç. Aşamalar beyanla değil devralanın devirden sonra kapattığı çağrılarla
  ilerler (1. çağrı "birlikte", 3. çağrı "tek başına"). Kart yoksa devralan taslağı yazar, ayrılan
  düzeltir; öğretmede vakalar tekrar edilmez. Ayrılanın ve devralanın haftalık saati ayrıdır; takvim
  çıkışa yetişmiyorsa sistem darboğaz kimse onun saatini önerir.
- **Çağrı formu:** önce metin (model konuyu tahmin eder), sonra konuya özel 2-3 soru. Öncelik
  sorulmaz: işin durumu (3/2/1) + kimi etkiliyor (1/2/3); 5-6 Yüksek, 4 Orta. Bekleyen araç varsa
  Yüksek. Cevaplar metne eklenmez (metin modelin öğrenme verisi), `ek_bilgi` sütununda durur.

Sorular:
39. Devralanın konuyu öğrendiğini neye bakarak söylüyorsun; neden "izledi" elle işaretleniyor?
40. Kartı neden ayrılan değil devralan yazıyor, bunun bedeli ne?
41. Takvim çıkışa yetişmiyorsa sistem hangi saati önerir, neden önce ayrılanınkine bakar?
42. Önceliği neden kullanıcıya seçtirmiyorsun?
43. Form cevaplarını neden çağrı metnine eklemiyorsun?
44. "Önce bunu dene" adımlarını neden çözüm notlarından türetmedin?
45. Cihaz numarasını neden ayrı sütunda tutup tek biçime getiriyorsun?
46. Çağrının neden iki durumu var (durum ve asama)? "Çözüldü" hangi tarafta sayılıyor?
47. Envanterde olmayan bir numara gelince sistem onu neden kendisi eklemiyor?

## 7. Arayüz ve API (api.py, web/index.html, web/app.js, web/stil.css)

Tarayıcı bir düğmeye basınca `/api/...` adresine istek gider; `api.py` içindeki fonksiyon
`usta.py` ya da `risk.py`'deki fonksiyonu çağırıp sonucu JSON olarak döndürür; sayfa bu JSON'u
ekrana çizer. `api.py` içinde iş kuralı yoktur.

Sayfa üç dosyadır: `index.html` iskelet, `app.js` bütün ekranlar, `stil.css` görünüm. Satır içi
betik yoktur; bu sayede içerik güvenlik politikası (CSP) `script-src 'self'` olabilir: araya sızmış
bir `<img onerror=…>` bile çalışmaz.

**Dış kat (`api.py` → `app`):** FastAPI'nin önünde düz bir ASGI fonksiyonu durur. Her istekte sırayla:
1. Gerçek IP: yalnız güvenilen vekilden (`gercek_ip.py`).
2. Gövde sınırı (413) ve hız sınırları (429): okuma 300, yazma 40, MCP 60 istek/dakika/IP.
3. Yazma isteğinde kaynak denetimi: `Origin` başka bir siteyse 403 (CSRF).
4. `/mcp` ise anahtar denetimi (401); anahtar yoksa MCP kapalı (404).
5. **Ziyaretçi seçimi:** çerez varsa o ziyaretçinin veritabanı kopyası, yoksa ve istek bir şey
   değiştiriyorsa yeni kopya açılır ve çerez yazılır; yalnız okuyan istek ortak demoya gider.
   Seçilen bağlantı bir `ContextVar`'a konur; uçlardaki `con` adı her istekte ona yönlenir
   (`_EtkinBaglanti`). Böylece 50'den fazla ucu tek tek değiştirmek gerekmedi.
6. Yanıta güvenlik başlıkları ve CSP eklenir; API yanıtları önbelleğe alınmaz (`no-store`).

**Model önbelleği:** Eğitilmiş modeller verinin parmak iziyle saklanır (en çok 6). Verisine dokunmamış
bütün ziyaretçiler aynı modeli paylaşır; biri çağrı kapatırsa yalnız onun için yeniden eğitilir.
Değerlendirme (3 model) bugünden önceki çağrılarla yapıldığı için ziyaretçinin bugün kapattığı
çağrı onu yeniden çalıştırmaz.

"Kendi Verinle Dene" ekranında iki yol var. Elle işaretleme hiç sunucuya gitmez. Döküm yükleme
sunucuda bellekte geçici bir veritabanı açar (`ice_aktar.analiz_et`), haritayı çıkarır ve bağlantıyı
kapatır; hiçbir şey diske yazılmaz. Analiz, dökümün son gününe göre yapılır; yoksa eski bir döküm
"son 90 gün" penceresinin dışında kalırdı.

Sorular:
15. "Çağrıyı aç" düğmesine basınca arkada hangi adımlar sırayla olur?
15b. İki ziyaretçi neden birbirinin çağrısını görmez, ama ikisi de aynı modeli kullanabilir?

## 8. MCP (mcp_sunucu.py)

MCP, Claude gibi bir yapay zekânın bir programın fonksiyonlarını araç olarak çağırmasını sağlayan
protokol. Dosyadaki her `@arac` bir araç; fonksiyonun açıklama metni Claude'un o aracı ne zaman
kullanacağını anlamasını sağlar. Araçlar web ile aynı çekirdek fonksiyonlarını çağırır.

Araçların bir kısmı veri değiştirdiği için (çağrı açma, kapatma, geçiş kaydı) `/mcp` anahtar ister:
`Authorization: Bearer <anahtar>` (Claude'un özel bağlayıcısında "İstek başlıkları" bölümü; önerilen). `…/mcp/<anahtar>` da kabul edilir ama anahtar adreste görünür, ekran görüntüsüyle sızabilir.
Anahtar bellekte yalnız SHA-256 özeti olarak durur ve `hmac.compare_digest` ile sabit sürede
karşılaştırılır (karşılaştırma süresinden anahtar tahmin edilemesin). MCP ortak demo verisiyle
çalışır, ziyaretçi kopyalarını görmez.

Sorular:
16. Web arayüzü ile MCP sunucusu aynı sonucu vermek zorunda mı, neden?
16b. MCP'yi herkese açık bırakmanın riski neydi?

## 9. Yayın (Dockerfile, deploy/docker-compose.ortak.yml, ysfdurak.com/sunucu/kurulum-emanet.sh)

- **İmaj:** sabit `python:3.13.18-slim-trixie`; bağımlılıklar sürüm ve özetle sabit
  (`pip install --require-hashes`); root olmayan kullanıcı; `HEALTHCHECK` `/healthz`.
  `OMP_NUM_THREADS=1`: numpy'nin her çekirdek için iş parçacığı açıp süreç sınırını doldurmasın.
- **Konteyner:** salt okunur kök, yazma yalnız `/veri` birimine ve 64 MB `/tmp`'ye; `cap_drop: ALL`,
  `no-new-privileges`, 768 MB bellek, 128 süreç, kayıt sınırı. Port açılmaz; Caddy ortak `web`
  ağından `emanet:8000`'e iletir.
- **Başlatma:** `python -m emanet` (uvicorn, tek işçi, vekil başlıklarını yorumlamaz).
- **Veri:** `/veri/emanet.db` her gün ilk istekte yeniden üretilir, ziyaretçi kopyaları
  `/veri/ziyaretci/` altında 24 saat yaşar. Yedek yok (demo). Kendi verinle kurulumda yedeğe eklenir.

Sorular:
17. Bu proje neden GitHub Pages ya da Cloudflare Workers'ta değil de VPS'te?
18. Sunucu yeniden başlarsa veri kaybolur mu, önemli mi?

## Mülakatta gelebilecek üç soru

**"Bunu neden yaptın?"** İK kilit kişi riskine organizasyon şemasından bakar. Ben operasyon
verisinden baktım: işi fiilen kim yapıyor. İki farklı cevap çıkıyor ve aradaki fark riskin
kendisi.

**"Gerçek veriyle çalışır mı?"** Emanet için rapor düzeyinde bir döküm yeter: tarih, birim, konu,
çözen, süre. Sitede kendi dökümünü yükleyip görebilirsin. Usta'nın öğrenmesi için ayrıca çağrı metni
ve mümkünse çözüm notu gerekir.

**"Bu yapay zekâ mı?"** Makine öğrenmesi, ama dış bir yapay zekâ servisi değil. Model sunucunun
içinde, birkaç yüz kilobayt. Şirket verisi dışarı çıkmıyor. Her tahminin yanında olasılığı ve
belirleyici sözcükleri yazıyor; emin olmadığında soruyor. Risk puanı ise tamamen açık bir formül.

## Cevaplar

1. Her şey kapalı çağrılardaki "kim çözdü" bilgisinden türetiliyor.
2. Rastgele seçimleri tekrarlanabilir yapar; aynı veri çıktığı için testler ve demo tutarlı kalır.
3. Gerçekte teknik arızalar bakım sisteminde tutulur ve Usta'nın yönlendirme işi değildir; ama bilgi
   riski orada da var, bu yüzden Emanet onları döküm olarak okur.
4. Metinde ayırt edici bir ifade yok; en yüksek olasılık %45'in altında kalıyor.
5. "terminali", "terminalde", "termnal" üç ayrı sözcük olurdu; model birinden öğrendiğini
   diğerine aktaramazdı.
6. Gerçek kullanımda model hep geçmişle eğitilip gelecekte kullanılır. Rastgele bölmek, aynı
   dönemin benzer çağrılarını hem eğitime hem teste koyup başarıyı şişirir.
7. O kişi izinde ya da vardiyada değil; atama yalnızca müsait olanlar arasından yapılır.
8. Model "geçmişte kim çözerdi" der; "şu an kim müsait" bilgisi modelde yok. İzin ve vardiya kesin
   kurallar, öğrenilecek şeyler değil.
9. Yoğunlaşma 0,3 civarıysa 100 × 0,45 × 0,3 ≈ 14.
10. Beyan `yetkinlik_beyan` tablosundan, gerçek sayı son 90 günde en az 3 çözümü olanlardan.
10b. Notlar dağınık ve kimse onaylamamış; kart ise üzerinde anlaşılmış yazılı yoldur. Not oranı
   yine de neden olarak gösterilir.
11. Geride bilen yoksa çarpan yazılı çözümle 1,5, onsuz 2,5; ayrıca yazısızlık puana 20 ekler.
12. Bekleme maliyeti kuruma göre değişir; uydurma bir rakam göstermektense kullanıcıya bırakıldı.
13. Oranı iyi küçük adımlar bütçeyi yer, kalan saat büyük ve değerli bir adıma yetmez.
14. Plan ucuz, düşük riskli konulara dağılır; kırmızı konular kırmızı kalırdı.
15. Konu modeli çalışır, kişi modeli ve kurallarla atama yapılır, çağrı ve olay kayıtları yazılır.
16. Evet; ikisi aynı fonksiyonu çağırdığı için. Kural tek yerde yazılı.
17. Kalıcı veri, her kapanışta yeniden eğitilen model ve sürekli açık bir MCP sunucusu gerekiyor.
18. Veri birimde durur, kaybolmaz; kaybolsa da ilk istekte aynı tohumla yeniden üretilir.
15b. Her ziyaretçi ilk değişikliğinde ortak demonun bir kopyasını alır ve çerezle o kopyaya yönlendirilir.
    Model önbelleği veritabanına değil verinin parmak izine bağlıdır: verisine dokunmamış kopyalar
    aynı parmak izini verir, aynı modeli kullanır.
16b. Herkes Claude'dan (ya da bir betikle) çağrı açıp kapatabilir, geçiş kaydedebilir, ortak demoyu
    bozabilirdi; ayrıca sınırsız araç çağrısı sunucuyu yorardı.
19. Model yanılabilir; yanlış bir otomatik işlem geri alınması zor bir sonuç doğurabilir. Kurallar
    açık ve denetlenebilir; model yalnızca hangi kuralın devreye gireceğini önerir.
20. Not insan için yazılmış bir cümle; bir programın çalıştırabilmesi için her adımın hangi sistemde
    hangi işlemle ve nasıl doğrulanacağı tanımlanmalı. Bu tanım BT'nin onayıyla yapılır.
21. Çağrı yeniden açılır, çözüm notu silinir (öğrenmeye girmez), otomasyonsa reçetenin "tutmadı"
    sayacı artar ve çalışma "tutmadı" durumuna geçer.
22. Talepler kişiye özgüdür, aynı arızanın belirtisi değildir; ayrıca aynı kişinin çağrıları sayılmaz.
23. Yazısızlık "çözüm yazıya geçmiş mi" sorusu; otomasyon ise o işin bir kısmını kişiye muhtaç olmaktan
    çıkarır. Otomasyonla kapanan çağrı uzmanı beklemez, bu yüzden bağımlılık bileşenleri küçülür.
24. Kritik bir konunun, izinli kişi dışında hiç yetkin yedeği yoksa: hangi tarih seçilse sonuç aynıdır.
25. Pratiği kalmamış kişi bugün işi çözemeyebilir, yedek sayılmaz; ama onu yeniden yetiştirmek sıfırdan
    birini yetiştirmekten ucuzdur. Bu yüzden riski değil, planın maliyetini değiştirir.
26. İlk noktanın 90 günlük penceresinin tamamı veride olmalı; veri 180 gün olduğu için ilk nokta 90. günde başlar.
27. Birkaç çağrıyla hesaplanan yoğunlaşma gürültüdür: ilk çağrıyı kim alırsa %100 çıkar. Beyan zayıf
    ama elde olan tek bilgi. En az 5 çağrıda tek kişinin payı %60'ı geçince veri konuşmuş sayılır ve
    gerçek puan kullanılır; 60 gün ya da 10 çağrı dolunca konu normal hesaplanır.
28. Yanlış çözümün bedeli orada yüksek. Öğrenme, işi durdurmayacak çağrılarda ve yanında usta
    varken yapılmalı.
29. Bozuk otomasyon her çağrıda zaman kaybettirir ve kullanıcıya yanlış "çözüldü" diyebilir. Durdurmak
    güvenli tarafa düşmektir: çağrı zaten insana gider. Yeniden açmak ise bilinçli bir karardır.
30. Yeni sistemde sorunlar değişmiş olabilir; model eski kalıpla yanlış konu önerebilir. Bu yüzden
    kişi modelinde eski çağrıların ağırlığı düşük ve her yeni çağrı modeli güncelliyor.
31. Reçete bozulduğunda onu düzeltebilen tek kişi giderse otomasyon askıya düşer ve o konunun riski
    birden geri gelir. Bağımlılık ortadan kalkmaz, yer değiştirir.
32. Puan "son 90 günde kim çözdü"ye bakar. Son haftaların kayıtları gelmezse kişilerin çözüm sayısı
    eşiğin altına düşer, yetkin sayısı azalır.
33. Etiket "kim çözdü"; bu da kime verildiğini yansıtır. Model geçmiş atama alışkanlığını tekrar etmekte
    başarılı olabilir, ama o alışkanlık bağımlılığın kendisi olabilir.
34. Paylaştırma bilerek modelin (ve geçmişin) seçmediği kişiyi seçer; isabeti düşük çıkması amacına
    ulaştığını gösterir. Doğru soru "konuyu bilen birine mi gitti, iş ne kadar sürdü, bilgi dağıldı mı?"
35. Vardiyada konuyu bilen ikinci kimse yok; paylaştırma yetkinliği olmayan birine çağrı vermez.
    Orada çözüm, eğitim planıyla yeni bir yedek yetiştirmek.
36. Risk dökümünde metin yok, yalnızca "kim, hangi konu, ne zaman"; bellekte işlenip silinir. Çağrı
    metni ise kişisel ve teknik bilgi taşır; onu kişisel bir siteye istemek projenin veri ilkesiyle çelişir.
37. Kalite ağırlığı (süreye bakar), "ya giderse" ek bekleme süresi ve tahmini süre ölçüsü. Konu ve kişi
    tahmini, nasıl çözüldü ve risk haritası çalışır.
38. Sentetik cümleler sınırlı kalıplardan üretildi. Gerçek çağrılar dağınık, kısa ve yanlış konuya
    atanmış olabilir. Rapor, modelin kullanıcının kendi verisinde, eğitimde görmediği en yeni
    çağrılardaki başarısını ve eski kurala göre farkını yazar.
39. Devralanın devir başladıktan sonra o konuda kendi kapattığı çağrı sayısına. İzlemek kayıt bırakmaz;
    sistemin göremediğini uydurmak yerine elle işaretletiyorum.
40. Devralan eski vakaları tek tek açıp yazarken öğrenir; ayrılanın saati düşer (Murat'ta 15 → 9) ve devir
    ilk hafta başlar. Bedeli devralanın yükünün artması (11 → 13 saat); ama bu saat onun gelecekteki işi.
41. Önce ayrılanınkine: genelde darboğaz odur ve bıraktığı işin yükü azalır. O yetmezse devralanınkine,
    o da yetmezse ikisine birden; 20 saati aşan öneri yapmaz, konuyu bölmeyi ya da çıkışı ertelemeyi söyler.
42. Seçtirilen öncelik herkesin "yüksek" dediği alan olur. Kişinin bildiğini soruyorum (iş durdu mu, kaç
    kişi, araç bekliyor mu); önceliği kuralla hesaplayıp gerekçesini gösteriyorum. Sunucu kendi hesaplar.
43. Metin modelin öğrenme verisi. "Yazıcı numarası: YZ-07" gibi form cümleleri her çağrıda tekrar
    ederek modelin belirleyici sözcüklerini bozar.
44. Notlar uzmanın uzmana yazdığı adımlar ("entegrasyon günlüğünde belgeyi bul"); çağrıyı açan depo
    çalışanı bunları yapamaz. Yalnız kullanıcının güvenle yapabileceği adımları elle yazdım.
45. Tekrarlayan arızayı saymak için: "yz 7" ile "YZ-07" aynı cihaz olmalı, yoksa geçmiş bölünür ve 30 günde
    3 çağrı eşiği hiç tutmaz. Ayrı sütun indekslenir; JSON içinde aramak hem yavaş hem kırılgan olurdu.
46. Kaba durum (açık/kapalı) modelin ve risk hesabının dili: çözen ve çözüm notu belli mi? İnce durum iş
    akışının dili: kim ne bekliyor? "Çözüldü" kaba durumda kapalı (çözen belli, öğrenmeye girer), ince
    durumda onay bekliyor; açan "devam ediyor" derse not öğrenmeden çıkarılır ve çağrı yeniden açılır.
47. Envanterin sahibi demirbaş sistemi. Yazım hatası ("YZ-70") kendiliğinden eklenirse sahte cihaz doğar ve
    geçmiş bölünür. Bu yüzden ayrı listelenir; düzeltme ya da envanter güncellemesi insanın kararı.
