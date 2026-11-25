# Emanet + Usta. Bağımlılıklar requirements.txt'te sürüm VE özet (hash) ile sabit: pip başka bir dosya indirirse kurulum durur.
#   docker build -t emanet .
FROM python:3.15.1-slim-trixie
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1 PIP_DISABLE_PIP_VERSION_CHECK=1 PORT=8000 \
    EMANET_DB=/veri/emanet.db OMP_NUM_THREADS=1 OPENBLAS_NUM_THREADS=1 MKL_NUM_THREADS=1
WORKDIR /app
COPY requirements.txt ./
RUN pip install --require-hashes --no-deps -r requirements.txt
COPY emanet ./emanet
COPY web ./web
# Kalıcı veri /veri biriminde; adlandırılmış birim ilk açılışta bu klasörün sahipliğini alır (root olmayan kullanıcı yazabilsin)
RUN useradd --system --uid 10001 --no-create-home emanet && mkdir /veri && chown emanet:emanet /veri
USER emanet
VOLUME /veri
EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=5s --start-period=40s \
  CMD python -c "import urllib.request,os,sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:'+os.environ.get('PORT','8000')+'/healthz', timeout=4).status==200 else 1)"
CMD ["python", "-m", "emanet"]
