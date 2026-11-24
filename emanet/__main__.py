"""Sunucuyu başlatır: python -m emanet  (Docker'daki komut da budur).

uvicorn'un vekil başlıklarını yorumlaması kapalıdır (proxy_headers=False): istemcinin gerçek IP'sini
yalnız güvenilen vekilden (Caddy/Cloudflare) gelen başlıkla gercek_ip.py belirler. Tek işçi: veritabanı
kilidi, model önbelleği ve MCP oturum yöneticisi süreç içinde tutulur.
"""
import os

import uvicorn


def main() -> None:
    uvicorn.run("emanet.api:app", host=os.environ.get("HOST", "0.0.0.0"), port=int(os.environ.get("PORT", "8000")),
                workers=1, proxy_headers=False, server_header=False, date_header=False, log_level="info")


if __name__ == "__main__":
    main()
