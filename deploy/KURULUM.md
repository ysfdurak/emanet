# Sunucuya kurulum (ysfdurak.com ortak altyapısı)

Emanet kalıcı veri (ziyaretçi kopyaları, gece sıfırlanan demo) tutar ve MCP sunucusu sürekli açık
durur; bu yüzden VPS'te, diğer projelerle aynı ortak altyapıda (Caddy + `web` ağı) çalışır.
Uygulama portu dışarı açılmaz; dışarıya yalnız Caddy açar.

## 1. Cloudflare
`emanet` için sunucunun IP'sine **A kaydı**, proxy açık (turuncu bulut). 80/443 yalnız Cloudflare'den
kabul edildiği için (`sunucu/cloudflare-kaynak.sh`) gri bulutta site açılmaz.

## 2. Kurulum betiği
```bash
ssh yusuf@SUNUCU
cd ~/ysfdurak.com && git pull
bash sunucu/kurulum-emanet.sh
```
Betik: kodu `~/emanet` klasörüne alır, `.env`'i (`umask 077`) oluşturur ve bir MCP anahtarı üretir,
`deploy/docker-compose.ortak.yml` ile derleyip başlatır, sağlık denetimini bekler ve Caddy'yi
yeniden yükler. Tekrar çalıştırmak güvenlidir (güncelleme de budur).

## 3. Kontrol
- https://emanet.ysfdurak.com açılıyor; tarayıcı konsolunda CSP uyarısı yok.
- `curl -sI https://emanet.ysfdurak.com | grep -i content-security` başlığı gösteriyor.
- İki ayrı tarayıcıda çağrı aç: biri ötekinin çağrısını görmemeli (ziyaretçi demosu).
- Claude'da özel bağlayıcı: `https://emanet.ysfdurak.com/mcp/<anahtar>` (anahtar `~/emanet/.env`
  içindeki `EMANET_MCP_ANAHTARLARI`). Anahtarsız `/mcp` 401 döner.

## Notlar
- Veri SQLite'tır (`emanet_veri` birimi: `/veri/emanet.db` ve `/veri/ziyaretci/`). Demo her gece
  yeniden üretildiği için yedeğe alınmaz. Kendi verinle kurulumda (`EMANET_DB=/veri/yerel.db`) yedek
  betiğine eklenmelidir.
- Tek işçi (`python -m emanet`): kilit, model önbelleği ve MCP oturumları süreç içindedir.
- Bellek sınırı 768 MB: scikit-learn ve en çok 6 eğitilmiş model.
- Tek başına (ortak altyapı olmadan) kurulum: kök klasördeki `docker-compose.yml`, önüne kendi ters
  vekilini koyarak.
