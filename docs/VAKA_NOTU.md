# Vaka notu: Emanet + Usta

## Sorun

Bir işi bilen kişi izne çıktığında ya da ayrıldığında iş durur. Kurumlar bunu çoğu zaman olay
yaşandıktan sonra fark eder, çünkü "kim neyi yapabilir" listeleri beyana dayanır. Aynı kurumda
destek çağrıları da birikir: çağrı yanlış birime gider, bilen kişi yokken bekler.

Bu iki sorun aynı verinin iki yüzü. Her çözülen çağrı, kimin neyi bildiğinin kaydıdır.

## Karar: iki fikir, tek proje, iki kaynak

Başta iki ayrı fikir vardı: çağrıları yönlendiren ve geçmiş çözümlerden öğrenen bir sistem ile
kişiye bağımlılığı gösteren bir risk haritası. Birleştirildi, çünkü risk haritasının en zor
kısmı olan "gerçeğe yakın veri" çağrı sisteminden kendiliğinden çıkıyor.

İlk sürümde Usta bütün çağrılara bakıyordu. Gözden geçirmede netleşti: çağrı merkezi yalnızca
sistemsel çağrılara (BT, depo sistemleri) bakar, teknik arızalar başka bir sistemde tutulur. Usta
buna göre daraltıldı; teknik arızalar Emanet'e döküm olarak (CSV) girer. Böylece Emanet'in tek bir
sisteme bağlı olmadığı da gösterilmiş oldu.

## İzlenen yol

1. **Kapsam.** İki modül, dokuz ekran, sekiz MCP aracı, sürüm planı bir dokümanda yazıldı.
2. **Veri.** Yıldız Ev & Yaşam için 5 birim, 28 kişi, 28 konu tanımlandı. Üretici 1.000 kapalı
   ve 12 açık çağrı yazıyor. Üç konuya tek kişi bağımlılığı, bir konuya gece vardiyası boşluğu,
   birkaç konuya "kâğıtta yetkin, fiilen değil" farkı gömüldü.
3. **Usta.** İlk sürüm elle yazılmış benzerlik kurallarıyla çalışıyordu. İkinci sürümde makine
   öğrenmesine geçildi: geçmiş çağrılardan konu, çözen kişi ve çözüm yolu öğreniliyor. En yeni 180
   çağrıda (eğitimde görülmeden) konu %93 (eski kural %80), çözen kişi ilk sırada %62 (kural %53),
   ilk üçte %93 (kural %67).
4. **Emanet.** Risk puanı dört bileşenli açık bir formül. "Ya giderse" haritayı o kişi olmadan
   yeniden hesaplıyor. Eğitim planı çok seçenekli sırt çantası olarak çözülüyor.
5. **Arayüz ve MCP.** İkisi de aynı çekirdek fonksiyonları çağırıyor.

## Üçüncü adım: otomasyon

Çağrıların bir kısmı aslında iştir, sorun değil: kurulum, yetki, kilit açma. Bir kısmının ise çözüm
yolu bellidir: yazıcı kuyruğu, gece rapor işi, terminal ağı. Bunlar için bir otomasyon katmanı
eklendi. Temel karar, yetkinin üç seviyeye ayrılması oldu: otomatik, onaylı otomatik ve yalnızca
insan. Makine öğrenmesi yalnızca konuyu tanıyor; yapılıp yapılmayacağına yazılı kurallar karar veriyor.
Son 180 günün çağrılarına uygulandığında çağrıların yaklaşık %22'sinin insansız kapanabileceği,
bunun da ayda yaklaşık 13 saatlik iş olduğu görüldü (demo verisinde).

## Dördüncü adım: riski görmekten sonucu ölçmeye

Risk haritası ilk hâliyle "ne kötü" sorusuna cevap veriyordu, "ne yaptık, işe yaradı mı" sorusuna
değil. Altı ekleme yapıldı: otomasyonun ve yazılı reçetelerin riski düşürmesi, izin onayından önce
kontrol, kaydedilen eğitim planının takibi, pratiği kalmamış yedeklerin tespiti ve ucuza tazelenmesi,
ayrılan kişi için devir dosyası ve riskin zaman içindeki seyri. Demo verisinde, uzmanın notlarından
taslak reçete çıkarmak sipariş dalgası riskini 99'dan 79'a, 60 saatlik planın 30 günlük simülasyonu
ortalama riski 26'dan 17'ye indiriyor.

## Beşinci adım: değişimler ve denetim

Harita geçmişe baktığı için üç durumda yanılıyordu: sistem değişince (eski konu sahte risk üretir,
yeni konu hiç görünmez), yeni biri gelince (model ona hiç çağrı vermez, kişi hiç yetkin olamaz) ve
otomasyon bozulunca (risk indirimi devam eder). Sistem geçişi kaydı, geçici puan ve erken uyarı,
çırak modu, işe alışma görünümü ve otomasyon sağlığı (kendiliğinden askıya alma) eklendi. Demo
verisinde rapor küpünden Power BI'a geçişte, ilk 40 günde çağrıların üçte ikisini tek kişinin çözdüğü
erken uyarıyla yakalanıyor; yazıcı otomasyonu bozulunca reçete sekizinci denemede askıya düşüyor.

Ardından program kullanıcı gözüyle denetlendi. Bulunan iki gizli risk: otomasyonun da bir sahibi var
(otomasyon bağımlılığı ortadan kaldırmıyor, yer değiştiriyor) ve güncellenmeyen döküm riski yapay
olarak yükseltiyor. Kullanılabilirlik tarafında "Bugün neye bakmalı?" listesi, haritada süzme ve
Excel'e indirme, telefonda geri tuşu ve Türkçe sayı ekleri (%67'sini) düzeltildi.

## Altıncı adım: kişi modeli neyi öğreniyor?

Kişi modeli "bu çağrıyı kim çözdü"den öğreniyordu; bu kime verildiğini yansıtır, kimin iyi çözdüğünü
değil. İş hep aynı kişiye gittiyse model de onu önerir ve Usta, Emanet'in azaltmaya çalıştığı
bağımlılığı besler. Eğitim çağrılarına çözüm kalitesine göre ağırlık verildi ve kime verileceği
kurala bırakıldı (iş yükü ve paylaştırma). Ölçüm isabetle değil, "bilene gitti mi, bilgi dağıldı mı,
iş ne kadar sürdü" ile yapıldı. Demo verisinde fark küçük çıktı: asıl bağımlılık hiç yedeği olmayan
konulardan geliyor ve oraya çare eğitim. Sonuç olduğu gibi yazıldı.

## Yedinci adım: gerçek veriyle, ama dışarı çıkarmadan

Siteye gelen birinin kendi çağrılarını yükleyip Usta'yı denemesi düşünüldü ve bilinçli olarak
yapılmadı: çağrı metni kişisel ve teknik bilgi taşır, projenin ilkesi verinin dışarı çıkmaması.
Onun yerine tek komutluk bir yerel kurulum eklendi (`python -m emanet.yerel cagrilar.csv --takma-ad`).
Esnek sütun adları, takma ad, tarih kaydırma ve modelin kullanıcının kendi verisindeki başarısını
yazan bir rapor içeriyor. Böylece sentetik verinin şişirdiği başarı, gerçek sayılarla sınanabiliyor.

## Sekizinci adım: yayına hazırlık

Portföyün ortak güvenlik temeli uygulandı. En büyük değişiklik ziyaretçi demosu: önceden herkes aynı
veriyi değiştiriyordu, şimdi her ziyaretçi ilk değişikliğinde kendi kopyasını alıyor. Sayfa satır
içi betikten arındırılıp sıkı CSP'ye geçti, MCP anahtara bağlandı, bağımlılıklar özetle sabitlendi.
Tarama temiz; yayın deponun açılmasını bekliyor.

## Yolda değişen dört şey

**Kurallardan öğrenmeye.** Kural tabanlı yönlendirme "konuyu en çok çözen" kişiye bakıyordu. Oysa
aynı konunun içinde farklı alt sorunların farklı uzmanı var: yazıcının ağ sorununu başka, ribon
sorununu başka kişiler çözüyor. Model bunu metinden öğrendi; kişi tahmininde ilk üçte isabet %67'den
%93'e çıktı. Çağrı kapanırken "nasıl çözdün?" notu istenmeye başlandı; bir sonraki benzer çağrıda bu
notlar gruplanıp yol olarak gösteriliyor.

**Eğitim planının amacı.** İlk sürüm "toplam puan düşüşünü" en büyük yapıyordu. Sonuç: plan ucuz
ve önemsiz konulara dağıldı, sorter 120 saatlik bütçeye kadar eğitim alamadı. Amaç, yeşil
sınırının üzerindeki riski düşürmeye öncelik verecek şekilde değiştirildi. Şimdi 60 saatle
kırmızı konu kalmıyor.

**Giden kişi riski düşürüyordu.** En çok çözen kişi çıkarılınca kalanlar arasında pay daha dengeli
göründüğü için puan düşüyordu. İki düzeltme yapıldı: konuyu düzenli çözen kimse kalmadıysa
yoğunlaşma 1 sayılıyor, ve bir kişinin gidişi yoğunlaşmayı gidiş öncesi değerin altına
indiremiyor. Bunu bir test koruyor.

**Yetkinlik eşiği.** "En az 3 çözüm" kuralı seyrek ama kritik konularda (yangın alarmı, raf
hasarı) herkesi yetkinsiz gösteriyordu. Seyrek konularda eşik 2'ye indirildi.

## Sonuç (demo verisinde)

| Ölçü | Değer |
| --- | --- |
| Yüksek riskli konu | 26 konunun 4'ü (2'si Usta, 2'si bakım dökümünden) |
| En riskli konu | Sipariş dalgası (99): çağrıların %97'sini tek kişi çözüyor, notların %24'ü yazılmış |
| Dalga uzmanı 21 gün yoksa | Konu yedeksiz kalıyor, yaklaşık 8 saat ek bekleme |
| 60 saatlik planla | Yüksek riskli konu 4'ten 0'a |
| Model (en yeni 180 çağrı) | Konu %93, kişi ilk üçte %93 |

Bu rakamlar kurgusal veriye aittir; yöntemi gösterir, gerçek bir kurum hakkında bir şey söylemez.

## Bu sürümde olmayanlar

- Bakım sistemiyle canlı bağlantı (döküm elle yüklenir)
- Gerçek Teams, kimlik ve kurulum sistemlerine bağlantı (otomasyon bunları simüle ediyor)
- Gerçek çağrı metinleriyle model denemesi
- İngilizce arayüz
- Soru sorup öneri veren agent katmanı
- Kullanıcı hesapları

## Kod listesi

| Dosya | İçerik |
| --- | --- |
| emanet/katalog.py | Kurgusal şirket: kişiler, 12 sistemsel konu (alt sorunlarıyla), 14 teknik konu |
| emanet/db.py | Şema ve bağlantı |
| emanet/veri_uret.py | Sentetik veri üreticisi, bakım dökümü CSV'si |
| emanet/ice_aktar.py | Döküm içe aktarma, kaydetmeden analiz |
| emanet/ogrenme.py | Konu ve kişi modelleri, nasıl çözüldü, zaman bazlı test |
| emanet/usta.py | Modeller + iş kuralları, çağrı yaşam döngüsü |
| emanet/otomasyon.py | Reçeteler, yetki çerçevesi, Teams simülasyonu, altı otomasyon akışı |
| emanet/takip.py | İzin kontrolü, plan takibi, devir dosyası, risk seyri, reçete fırsatları, dikkat listesi |
| emanet/degisim.py | Sistem geçişi, yeni personel ve işe alışma, gerçek ayrılış |
| emanet/dil.py | Türkçe sayı ekleri |
| emanet/yerel.py | Kendi çağrı verinle yerel kurulum ve rapor |
| emanet/gercek_ip.py | Gerçek IP yalnız güvenilen vekilden |
| emanet/__main__.py | Sunucuyu başlatır (python -m emanet) |
| web/app.js, web/stil.css | Ekranlar ve görünüm (satır içi betik yok) |
| docs/PROJE.md | Yaşayan proje dokümanı |
| emanet/risk.py | Risk puanı, ya giderse, eğitim planı |
| emanet/api.py | Web API |
| emanet/mcp_sunucu.py | 19 MCP aracı |
| web/index.html | Arayüz |
| tests/ | 83 test |
