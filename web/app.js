// Anonim kullanım ölçümü ve geri bildirim düğmesi (ortak servis: olcum.ysfdurak.com; kaynak: ysfdurak.com → sunucu/olcum).
// Yalnız resmî demo adresinde yüklenir: kendi sunucusuna kurulan kopyalar dışarıya hiç istek atmaz.
// Gönderilenler: ekran adı, aktif süre, cihaz türü, dil. Çağrı metni, kişi adı, IP gönderilmez; çerez yok; DNT/GPC'ye uyar.
const OLCUM_ACIK = location.hostname === "emanet.ysfdurak.com";
if (OLCUM_ACIK) {
  const s = document.createElement("script");
  s.src = "https://olcum.ysfdurak.com/olcum.js";
  s.defer = true;
  s.dataset.proje = "emanet";
  document.head.appendChild(s);
}
function olc(tur, ad) {
  if (!OLCUM_ACIK) return;
  if (window.olcum && window.olcum[tur]) window.olcum[tur](ad);
  else (window.olcumKuyruk ||= []).push([tur, ad]);
}

"use strict";
const $ = (s, k = document) => k.querySelector(s);
const kac = s => String(s ?? "").replace(/[&<>"']/g, c => ({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"}[c]));
const sy = x => Number(x).toLocaleString("tr-TR");
const yuzde = x => "%" + Math.round(x * 100);
/* Türkçe sayı eki: ek(67, "ini") → "sini" (altmış yedi → yedi). Bkz. emanet/dil.py */
function ek(n, tur) {
  n = Math.abs(Math.round(n));
  const bir = ["", "bir", "iki", "üç", "dört", "beş", "altı", "yedi", "sekiz", "dokuz"];
  const on = ["", "on", "yirmi", "otuz", "kırk", "elli", "altmış", "yetmiş", "seksen", "doksan"];
  const s = n === 0 ? "sıfır" : n % 10 ? bir[n % 10] : n % 100 ? on[(n % 100) / 10] : n % 1000 ? "yüz" : "bin";
  const u = [...s].reverse().find(c => "aeıioöuü".includes(c));
  const d = {a: "ı", ı: "ı", o: "u", u: "u", e: "i", i: "i", ö: "ü", ü: "ü"}[u], i2 = "aıou".includes(u) ? "a" : "e";
  const v = "aeıioöuü".includes(s.at(-1));
  return {i: (v ? "y" : "") + d, in: (v ? "n" : "") + d + "n", ini: (v ? "s" : "") + d + "n" + d, ine: (v ? "s" : "") + d + "n" + i2,
          inde: (v ? "s" : "") + d + "nd" + i2, inden: (v ? "s" : "") + d + "nd" + i2 + "n", de: ("fstkçşhp".includes(s.at(-1)) ? "t" : "d") + i2, den: ("fstkçşhp".includes(s.at(-1)) ? "t" : "d") + i2 + "n", e: (v ? "y" : "") + i2}[tur];
}
// Sayı + ek; ondalıkta ek virgülden sonraki kısma göre seçilir (25,2 → "yirmi beş virgül iki" → 25,2'den)
const sek = (x, tur) => { const m = sy(x); return m + "’" + ek(+(m.split(",")[1] ?? m.replace(/\./g, "")), tur); };
const yek = (x, tur) => yuzde(x) + "’" + ek(Math.round(x * 100), tur);
const SEVIYE = {kirmizi: "Yüksek", sari: "Orta", yesil: "Düşük"};
const VARDIYA = {gunduz: "Gündüz", aksam: "Akşam", gece: "Gece"};
const tarih = s => s ? s.replace("T", " ").slice(5, 16) : "";
const sure = dk => dk >= 120 ? sy(Math.round(dk / 6) / 10) + " saat" : dk + " dk";
const sev = p => p >= 60 ? "kirmizi" : p >= 35 ? "sari" : "yesil";
let T = null;
const durum = {sayfa: "genel"};

async function api(yol, govde) {
  const y = await fetch("/api/" + yol, govde ? {method: "POST", headers: {"content-type": "application/json"}, body: JSON.stringify(govde)} : undefined);
  const v = await y.json().catch(() => ({}));
  if (!y.ok) {
    const m = typeof v.detail === "string" ? v.detail : Array.isArray(v.detail) ? "Girdi geçersiz: " + v.detail.map(d => d.loc.at(-1)).join(", ") : "İstek tamamlanamadı.";
    bildir(m); throw new Error(m);
  }
  return v;
}
let _zaman;
function bildir(m) { const d = $("#durum"); d.textContent = m; d.classList.remove("gizli"); clearTimeout(_zaman); _zaman = setTimeout(() => d.classList.add("gizli"), 4000); }
const puanKutu = r => `<span class="puan ${r.seviye}" title="Risk puanı">${r.puan}</span>`;
const rozet = (s, m) => `<span class="rozet ${s}">${kac(m)}</span>`;
const adimlar = a => `<ol class="adim">${(Array.isArray(a) ? a : a.split("\n")).map(x => `<li>${kac(x)}</li>`).join("")}</ol>`;

// Menü kullanıcının sorusuna göre dört alan + "Daha fazla". Sayfa kimlikleri (#risk, #plan…) değişmedi:
// eski bağlantılar ve MCP/doküman adresleri çalışmaya devam eder.
const ALANLAR = [
  ["bugun", "Bugün", ["genel"]],
  ["cagrilar", "Çağrılar", ["cagri", "kuyruk", "kartlar", "otomasyon"]],
  ["riskler", "Riskler", ["risk", "giderse"]],
  ["egitim", "Eğitim", ["plan"]],
  ["fazla", "Daha fazla", ["degisim", "ekibim", "nasil", "ogrenme"]]];
const ALT_AD = {cagri: "Çağrı aç", kuyruk: "Kuyruk", kartlar: "Çözüm notları", otomasyon: "Otomatik çözümler",
  risk: "Risk haritası", giderse: "Biri yoksa", degisim: "Değişimler", ekibim: "Kendi verinle dene",
  nasil: "Nasıl çalışır", ogrenme: "Model nasıl öğreniyor"};
// Alt sekmesi olmayan sayfalar hangi alt sekmeye sayılır
const ESDEGER = {izin: "giderse", detay: "kuyruk"};
const sonSayfa = {};
const alanBul = sayfa => (ALANLAR.find(([, , ss]) => ss.includes(ESDEGER[sayfa] || sayfa)) || ALANLAR[0]);
function navCiz() {
  const [etkinAlan, , sayfalar] = alanBul(durum.sayfa);
  sonSayfa[etkinAlan] = durum.sayfa;
  $("#nav").innerHTML = ALANLAR.map(([k, a, ss]) => `<button data-alan="${k}" ${k === etkinAlan ? 'aria-current="page"' : ""}>${a}</button>`).join("");
  const alt = sayfalar.length > 1 ? sayfalar : [];
  const secili = ESDEGER[durum.sayfa] || durum.sayfa;
  $("#altnav").innerHTML = alt.map(sf => `<button data-sayfa="${sf}" ${sf === secili ? 'aria-current="page"' : ""}>${ALT_AD[sf]}</button>`).join("");
  $("#altnav").hidden = !alt.length;
}
let _geri = false;
window.addEventListener("popstate", e => { const s = (e.state && e.state.sayfa) || location.hash.slice(1) || "genel"; if (!CIZ[s]) return; _geri = true; git(s, e.state && e.state.veri && !SENARYO[e.state.veri] ? e.state.veri : undefined).finally(() => { _geri = false; }); });
async function git(sayfa, veri) {
  const ayni = durum.sayfa === sayfa;
  durum.sayfa = sayfa; durum.veri = veri; navCiz();
  olc("ekran", sayfa);
  // Telefonda geri tuşu uygulamadan çıkmasın: her sayfa geçmişe eklenir (aynı sayfanın yenilenmesi eklenmez)
  if (!_geri && !ayni) history.pushState({sayfa, veri}, "", "#" + sayfa); else if (!_geri) history.replaceState({sayfa, veri}, "", "#" + sayfa);
  const ana = $("#ana"); ana.onclick = ana.onchange = ana.oninput = null;
  ana.innerHTML = '<p class="kucuk">Yükleniyor…</p>';
  try { await CIZ[sayfa](veri); } catch (e) { ana.innerHTML = `<div class="kart">Bu bölüm yüklenemedi: ${kac(e.message)}</div>`; }
  window.scrollTo(0, 0);
  const b = $(`#altnav [aria-current=page]`); if (b) b.scrollIntoView({inline: "nearest", block: "nearest"});
}
document.addEventListener("click", e => {
  const al = e.target.closest("[data-alan]");
  if (al) { const [k, , ss] = ALANLAR.find(([x]) => x === al.dataset.alan); git(sonSayfa[k] || ss[0]); return; }
  const s = e.target.closest("[data-sayfa]"); if (s) { git(s.dataset.sayfa, s.dataset.veri); return; }
  const c = e.target.closest("[data-cagri]"); if (c) { e.preventDefault(); git("detay", c.dataset.cagri); return; }
  const m = e.target.closest("[data-mesaj]");
  if (m) {
    const cevap = m.dataset.cevap ?? ($("#serbest-" + m.dataset.mesaj) || {}).value;
    m.disabled = true;
    api(`mesaj/${m.dataset.mesaj}/cevap`, {cevap}).then(() => { bildir("Cevap iletildi."); git(durum.sayfa, durum.sayfa === "otomasyon" ? "yenile" : durum.veri); }).catch(() => { m.disabled = false; });
  }
});

/* ---- otomasyon parçaları */
const OTO_DURUM = {basladi: ["gri", "Başladı"], bilgi_bekliyor: ["sari", "Bilgi bekleniyor"], onay_bekliyor: ["sari", "Onay bekleniyor"],
  basarili: ["yesil", "Otomatik çözüldü"], insana_devredildi: ["kirmizi", "İnsana devredildi"], reddedildi: ["gri", "Reddedildi"],
  tutmadi: ["kirmizi", "Kullanıcı çözülmedi dedi"], kismi: ["sari", "Kısmen tamamlandı"]};
const SEVIYE_R = {otomatik: ["yesil", "Otomatik"], onayli: ["sari", "Onaylı otomatik"], insan: ["gri", "Yalnızca insan"]};
const ROL = {talep_eden: "talep eden", yonetici: "yönetici"};
function mesajKart(m) {
  const bekliyor = m.cevap == null && m.tur !== "bilgi";
  return `<div class="teams"><div class="ust-satir">Teams · ${kac(m.kime)} (${ROL[m.rol] || m.rol})${m.tur === "onay" ? " · onay kartı" : m.tur === "teyit" ? " · kapanış teyidi" : ""}</div>
    <div>${kac(m.metin)}</div>
    ${bekliyor ? `<div style="margin-top:.45rem">${m.secenekler.map(x => `<button class="dugme kucuk ${x === "Reddet" || x.startsWith("Hayır") ? "ikincil" : ""}" style="margin:.15rem .25rem .15rem 0" data-mesaj="${kac(m.id)}" data-cevap="${kac(x)}">${kac(x)}</button>`).join("")}
      ${m.serbest ? `<div class="sira" style="margin-top:.3rem"><input id="serbest-${kac(m.id)}" maxlength="200" placeholder="ya da kendin yaz"><div style="flex:0 0 auto"><button class="dugme kucuk ikincil" data-mesaj="${kac(m.id)}">Gönder</button></div></div>` : ""}
      <div class="kucuk" style="margin-top:.25rem">Demoda ${kac(m.kime)} yerine sen cevaplıyorsun.</div></div>`
      : m.cevap != null ? `<div class="cevap">Cevap: <b>${kac(m.cevap)}</b></div>` : ""}</div>`;
}
function otoKart(o, baslik = true) {
  if (!o) return "";
  const [r, d] = OTO_DURUM[o.durum] || ["gri", o.durum];
  const ik = {ok: ["ok", "✓"], hata: ["hata", "✕"], bekliyor: ["bekliyor", "…"]};
  return `<div class="kart">${baslik ? `<h3>Otomasyon: ${kac(o.recete)}</h3>` : ""}
    <p>${rozet(r, d)} ${rozet(SEVIYE_R[o.seviye][0], SEVIYE_R[o.seviye][1])} <span class="kucuk">${o.kisi ? kac(o.kisi) : ""}${o.cagri_id ? ` · <a href="#detay" data-cagri="${kac(o.cagri_id)}">çağrı #${o.cagri_id}</a>` : ""}</span></p>
    <ul class="akis">${o.gunluk.map(g => { const [c, i] = ik[g.sonuc] || ["yok", "•"]; return `<li><span class="ik ${c}">${i}</span><div><span class="kucuk">${kac(g.kim)}</span><br>${kac(g.metin)}</div></li>`; }).join("")}</ul>
    ${o.mesajlar.filter(m => m.cevap == null && m.tur !== "bilgi").map(mesajKart).join("")}</div>`;
}

/* ---- ortak parçalar: atama ve yol gösterme */
function atamaKart(a, baslik = "Kime gidecek?") {
  if (!a) return "";
  return `<div class="kart"><h3>${baslik}</h3>
    <p style="font-size:1.1rem;margin:.3rem 0"><b>${kac(a.ad || "Atanacak kimse yok")}</b> <span class="kucuk">· ${kac(a.birim)} · ${VARDIYA[a.vardiya]} vardiyası</span></p>
    ${a.cirak ? `<p>${rozet("mor", "Yanında öğrenme")} ${rozet("gri", "Destek: " + kac(a.cirak.usta))}</p>` : ""}
    ${a.paylastirma ? `<p>${rozet("mavi", a.paylastirma.tur === "yuk" ? "İş yükü dengelendi" : "Paylaştırma")} ${rozet("gri", "Yedekte: " + kac(a.paylastirma.baskin))}</p>` : ""}
    <p class="kucuk">${kac(a.neden)}</p>
    ${a.uzman_notu ? `<div class="not uyari">${kac(a.uzman_notu)} Aşağıdaki çözüm yolları büyük ölçüde onun çağrılarından çıkarıldı.</div>` : ""}
    <details><summary class="kucuk">Modelin kişi sıralaması</summary>
    <ul class="liste">${a.siralama.map(s => `<li><span class="rozet ${s.durum === "vardiyada" ? "yesil" : "gri"}" style="min-width:5.5rem;text-align:center">${kac(s.durum)}</span>
      <div class="govde">${kac(s.ad)}<div class="cubuk" style="margin-top:.25rem"><i style="width:${Math.max(1, s.olasilik * 100)}%"></i></div></div><span class="kucuk">${yuzde(s.olasilik)}</span></li>`).join("")}</ul>
    <p class="kucuk">Olasılık: modelin “bu çağrıyı bu kişi çözer” tahmini. İzindekiler ve vardiyada olmayanlar atanmaz.</p></details></div>`;
}
function yolKart(y) {
  if (!y) return "";
  const kart = y.kartlar.map(k => `<div class="kart"><span class="rozet yesil">Çözüm kartı</span> <b>${kac(k.baslik)}</b>${adimlar(k.adimlar)}
    <div class="kucuk">Kök neden: ${kac(k.kok_neden || "-")} · Yazan: ${kac(k.yazan || "-")}</div></div>`).join("");
  const yollar = y.yollar.length ? y.yollar.map((g, i) => `<div class="${i ? "" : ""}" style="border-top:${i ? "1px solid var(--cizgi)" : "0"};padding-top:${i ? ".6rem" : 0};margin-top:${i ? ".6rem" : 0}">
      <div><b>${g.kac_kez} benzer çağrıda</b> <span class="kucuk">${g.ort_sure_dk != null ? `· ortalama ${sure(g.ort_sure_dk)}da kapanmış ` : ""}· ${kac(g.kisiler.join(", "))}</span></div>${adimlar(g.adimlar)}</div>`).join("")
    : '<p class="kucuk">Benzer çağrılarda çözüm notu yok.</p>';
  return `${kart}<div class="kart"><h3>Geçmişte nasıl çözüldü?</h3>
    <p class="kucuk">En benzer ${y.bakilan} çağrının çözüm notları gruplandı${y.notsuz ? `; ${y.notsuz} tanesine not düşülmemiş` : ""}.</p>${yollar}</div>`;
}

const CIZ = {};

/* ---------------------------------------------------------------- Genel */
CIZ.genel = async () => {
  const [o, tk] = await Promise.all([api("ozet"), api("tek-kisiye-kalanlar?gun_sayisi=7")]);
  const u = o.usta, m = u.model, e = o.emanet;
  $("#ana").innerHTML = `
  <h2>Bugün</h2>
  <p class="alt">Bilen kişi yokken iş durmasın. Aşağıda bugün dikkat isteyen işler var; her satırdaki düğme doğrudan yapılacak işi açar.</p>
  <div class="hizli">
    <button class="dugme" data-sayfa="cagri">Çağrı aç</button>
    <button class="dugme ikincil" data-sayfa="risk">Kim neye bağlı?</button>
    <button class="dugme ikincil" data-sayfa="plan">Eğitim planı</button>
  </div>
  <div class="kart"><h3>Bugün neye bakmalı?</h3>
    ${o.dikkat.length ? `<ul class="liste">${o.dikkat.map(d => `<li>${rozet(d.seviye, {kirmizi: "Acil", sari: "Dikkat", mavi: "Bilgi"}[d.seviye])}<div class="govde">${kac(d.metin)}</div>
    <button class="dugme kucuk${d.seviye === "kirmizi" ? "" : " ikincil"}" data-sayfa="${d.sayfa}" ${d.veri ? `data-veri="${kac(d.veri)}"` : ""}>${d.veri === "sureler" ? "Süreleri gir" : DIKKAT_EYLEM[d.sayfa] || "Aç"}</button></li>`).join("")}</ul>`
      : '<p class="kucuk">Bugün acil bir iş yok. Riskleri haftada bir gözden geçirmek yeter.</p>'}
  </div>
  ${T.mod === "yerel" ? `<div class="not">Bu uygulama kendi verinle çalışıyor (yerel kurulum). Demo senaryoları ve otomasyon örnekleri kapalı; veri bu makineden çıkmaz.</div>` : `<details class="kart" ${sessionStorageAl("tur") ? "" : "open"} id="tur">
    <summary><b>İlk kez mi geliyorsun? 30 saniyelik tur</b></summary>
    <ol class="adim">
      <li>Gece vardiyasında sipariş dalgası açılmıyor; bu işi bilen tek kişi gündüz çalışıyor. <button class="dugme kucuk ikincil" data-sayfa="cagri" data-veri="senaryo">Çağrıyı aç</button></li>
      <li>O kişi üç hafta yoksa ne olur? <button class="dugme kucuk ikincil" data-sayfa="giderse" data-veri="Elif Kaya">Simülasyonu gör</button></li>
      <li>60 saat eğitimle risk ne kadar düşer? <button class="dugme kucuk ikincil" data-sayfa="plan" data-veri="60">Planı çıkar</button></li>
      <li>Bir kurulum talebi: eksik bilgi Teams’ten sorulur, yönetici onaylar, kurulum kendiliğinden yapılır. <button class="dugme kucuk ikincil" data-sayfa="otomasyon" data-veri="kurulum_eksik">Dene</button></li>
    </ol>
    <p class="kucuk">İki parça birlikte çalışır: <b>Usta</b> sistem çağrılarını geçmişten öğrenerek doğru kişiye yollar ve çözümü gösterir; <b>Emanet</b> aynı çağrılardan “kim giderse ne durur” haritasını çıkarır.</p>
  </details>`}
  <details class="kart"><summary><b>Sayılarla durum</b> <span class="kucuk">· model başarısı, risk dağılımı, bu haftanın izinleri</span></summary>
  <h3 style="margin:.8rem 0 .5rem">Usta · öğrenen yönlendirme</h3>
  <div class="izgara">
    <div class="olcu"><b>${yuzde(m.konu.model)}</b><span>Konu tahmini (eski kural ${yuzde(m.konu.kural)})</span></div>
    <div class="olcu"><b>${yuzde(m.kisi.model)}</b><span>Doğru kişi ilk sırada (kural ${yuzde(m.kisi.kural)})</span></div>
    <div class="olcu"><b>${yuzde(m.kisi.model_ilk3)}</b><span>Doğru kişi ilk üçte</span></div>
    <div class="olcu"><b>${yuzde(u.cozum_notu_orani)}</b><span>Çözüm notu yazılan çağrı</span></div>
    ${T.mod === "yerel" ? "" : `<div class="olcu"><b>${yuzde(o.otomasyon.insansiz_oran)}</b><span>Otomasyonla insansız kapanabilecek çağrı (ayda ~${sy(o.otomasyon.kazanc_saat_ay)} saat)</span></div>`}
  </div>
  <p class="kucuk" style="margin-top:-.4rem">Başarı, modelin hiç görmediği en yeni ${m.test} çağrıda ölçüldü. <a href="#ogrenme" data-sayfa="ogrenme">Ayrıntı</a></p>
  <h3 style="margin:.8rem 0 .5rem">Emanet · kişiye bağımlılık</h3>
  <div class="izgara">
    <div class="olcu"><b style="color:var(--kirmizi)">${e.kirmizi}</b><span>Yüksek riskli konu</span></div>
    <div class="olcu"><b style="color:var(--sari)">${e.sari}</b><span>Orta riskli konu</span></div>
    <div class="olcu"><b style="color:var(--yesil)">${e.yesil}</b><span>Düşük riskli konu</span></div>
    <div class="olcu"><b>${sy(e.ortalama)}</b><span>Ortalama risk puanı (0-100)</span></div>
  </div>
  <div class="iki">
    <div class="kart"><h3>En riskli üç konu</h3>
      <ul class="liste">${o.en_riskli.map(r => `<li><span class="puan kirmizi">${r.puan}</span><div class="govde">${kac(r.ad)}</div></li>`).join("")}</ul>
      <button class="dugme kucuk ikincil" data-sayfa="risk">Haritanın tamamı</button></div>
    <div class="kart"><h3>Bu hafta izinler yüzünden</h3>
      ${tk.konular.length ? `<ul class="liste">${tk.konular.map(k => `<li>${rozet(k.durum === "yedeksiz" ? "kirmizi" : "sari", k.durum === "yedeksiz" ? "Yedeksiz" : "Tek kişi")}
        <div class="govde"><b>${kac(k.ad)}</b><div class="kucuk">İzinde: ${kac(k.izindeki_yetkinler.join(", "))}${k.kalan_yetkinler.length ? " · Kalan: " + kac(k.kalan_yetkinler.join(", ")) : ""}${k.kart_var ? "" : " · yazılı çözüm yok"}</div></div></li>`).join("")}</ul>`
        : '<p class="kucuk">Bu hafta izin kaynaklı yedeksiz konu yok.</p>'}
    </div>
  </div></details>`;
  const tur = $("#tur"); if (tur) tur.ontoggle = () => sessionStorageYaz("tur", !tur.open);
};
const DIKKAT_EYLEM = {otomasyon: "Otomasyona bak", degisim: "İncele", giderse: "Ne olur, gör", izin: "İzinlere bak", risk: "Haritada gör", plan: "Plana bak", kuyruk: "Çağrılara bak"};
// Tur bir kez kapatılınca o oturumda kapalı kalsın (tarayıcı depolaması yoksa sessizce geç)
function sessionStorageAl(k) { try { return sessionStorage.getItem("emanet_" + k) === "1"; } catch { return false; } }
function sessionStorageYaz(k, v) { try { sessionStorage.setItem("emanet_" + k, v ? "1" : "0"); } catch { /* yok */ } }

/* ---------------------------------------------------------------- Çağrı Aç */
const ORNEKLER = ["Sipariş dalgası açılmıyor, toplama görevleri düşmedi", "Yazıcı çevrimdışı görünüyor, etiket basmıyor", "Yazıcı etiketleri boş çıkarıyor, ribon bitmiş olabilir",
  "Mezanin katına hiç yerleştirme önerilmiyor", "Sistem hata veriyor, devam edemiyorum", "Sorter durdu, koliler şutlara gitmiyor"];
CIZ.cagri = async (veri) => {
  $("#ana").innerHTML = `
  <h2>Çağrı aç</h2>
  <p class="alt">Sorunu kendi cümlenle yaz. Usta geçmiş çağrılardan öğrendiğiyle konuyu tahmin eder, emin değilse sorar; vardiyada olan en uygun kişiyi seçer ve bu sorunun daha önce nasıl çözüldüğünü gösterir. ${T.mod === "yerel" ? "Konular ve kişiler içe aktardığın çağrılardan öğrenildi: " + kac(T.usta_birimleri.join(", ")) + "." : "Yalnızca sistemsel çağrılar (BT ve depo sistemleri) içindir."}</p>
  <div class="iki genis">
    <div>
      <div class="kart">
        <label for="metin">Sorun</label>
        <textarea id="metin" maxlength="600" placeholder="Örn. Yazıcı çevrimdışı görünüyor, etiket basmıyor"></textarea>
        <div>${(T.mod === "yerel" && T.ornek_metinler.length ? T.ornek_metinler : ORNEKLER).map(o => `<button class="cip" data-ornek="${kac(o)}">${kac(o)}</button>`).join("")}</div>
        <div class="sira">
          <div><label for="acan">Açan birim</label><select id="acan">${T.acan_birimler.map(b => `<option>${kac(b)}</option>`).join("")}</select></div>
          <div><label for="acil">Aciliyet</label><select id="acil"><option value="1">Düşük</option><option value="2" selected>Orta</option><option value="3">Yüksek</option></select></div>
          <div><label for="vard">Vardiya</label><select id="vard">${Object.entries(T.vardiyalar).map(([k, a]) => `<option value="${k}" ${k === T.simdiki_vardiya ? "selected" : ""}>${kac(a)}</option>`).join("")}</select></div>
        </div>
        <div id="oneri" style="margin-top:.8rem"></div>
        <p style="margin-top:.9rem"><button class="dugme" id="ac" disabled>Çağrıyı aç</button></p>
      </div>
      <div id="atama"></div>
    </div>
    <div id="yan"><div class="kart kucuk">Metni yazınca kime gideceği ve geçmişte nasıl çözüldüğü burada görünür.</div></div>
  </div>`;
  let secili = null, sayac = 0, manuel = false;   // manuel: konuyu kullanıcı seçti
  const metin = $("#metin");
  const parametre = () => ({metin: metin.value.trim(), acan_birim: $("#acan").value, vardiya: $("#vard").value, aciliyet: +$("#acil").value});
  async function oner() {
    const p = parametre(), no = ++sayac;
    if (p.metin.length < 5) { $("#oneri").innerHTML = $("#atama").innerHTML = ""; $("#ac").disabled = true; return; }
    const o = await api("cagri/oneri", p); if (no !== sayac) return;
    secili = o.soru_gerekli ? null : o.oneriler[0].kategori_id;
    const ilk = o.oneriler[0];
    if (o.kapsam_disi) {
      $("#oneri").innerHTML = `<div class="not uyari"><b>Bu bir teknik arıza gibi görünüyor (${kac(o.kapsam_disi.ad)} · ${kac(o.kapsam_disi.birim)}).</b> Usta yalnızca sistemsel çağrılara bakar; teknik arızalar bakım sistemine bildirilir ve Emanet’e oradan döküm olarak gelir.</div>
        <p class="kucuk">Yine de sistemsel bir sorunsa konuyu seç:</p>${konuSecici(o)}`;
    } else if (o.soru_gerekli) {
      $("#oneri").innerHTML = `<div class="not uyari"><b>Emin değilim (en yüksek olasılık ${yuzde(o.guven)}).</b> ${kac(o.soru)}</div>${konuSecici(o)}`;
    } else {
      $("#oneri").innerHTML = `<div class="not"><b>${kac(ilk.ad)}</b> · ${kac(ilk.birim)} ${rozet("mavi", "olasılık " + yuzde(o.guven))}
        <div class="kucuk">${kac(o.neden)}</div>
        <div class="kucuk">Sonraki adaylar: ${o.oneriler.slice(1).map(a => kac(a.ad) + " " + yuzde(a.puan)).join(", ")}</div></div>`;
    }
    $("#ac").disabled = !secili;
    $("#atama").innerHTML = atamaKart(o.atama);
    $("#yan").innerHTML = o.yol ? yolKart(o.yol) : '<div class="kart kucuk">Konu seçilince kime gideceği ve geçmişte nasıl çözüldüğü burada görünür.</div>';
  }
  function konuSecici(o) {
    return `${o.oneriler.filter(a => a.puan > 0.01).map(a => `<button class="secenek" aria-pressed="false" data-kat="${kac(a.kategori_id)}"><b>${kac(a.ad)}</b> <span class="kucuk">· ${kac(a.birim)} · ${yuzde(a.puan)}</span><br><span class="kucuk">${kac(a.aciklama)}</span></button>`).join("")}
      <label for="diger">Hiçbiri değilse konuyu seç</label>
      <select id="diger"><option value="">Seç…</option>${T.kategoriler.map(k => `<option value="${kac(k.id)}">${kac(k.birim)} · ${kac(k.ad)}</option>`).join("")}</select>`;
  }
  async function konuSec(id) {
    secili = id; manuel = true; $("#ac").disabled = false;
    const o = await api("cagri/onizle", {...parametre(), kategori_id: id});
    $("#atama").innerHTML = atamaKart(o.atama); $("#yan").innerHTML = yolKart(o.yol);
  }
  let bekle;
  const tetik = () => { clearTimeout(bekle); bekle = setTimeout(oner, 350); };
  metin.oninput = () => { manuel = false; tetik(); };
  $("#acan").onchange = $("#vard").onchange = () => manuel && secili ? konuSec(secili) : oner();
  $("#ana").onclick = async e => {
    const or = e.target.closest("[data-ornek]"); if (or) { metin.value = or.dataset.ornek; manuel = false; oner(); return; }
    const k = e.target.closest("[data-kat]");
    if (k) { document.querySelectorAll("[data-kat]").forEach(b => b.setAttribute("aria-pressed", b === k)); if ($("#diger")) $("#diger").value = ""; konuSec(+k.dataset.kat); return; }
    if (e.target.id === "ac") {
      e.target.disabled = true;
      const c = await api("cagri", {...parametre(), kategori_id: secili});
      $("#ana").innerHTML = `
        <h2>Çağrı #${c.id} açıldı</h2>
        <div class="iki genis"><div>
          <div class="kart"><p>${kac(c.metin)}</p><p>${rozet("mavi", c.kategori)} ${rozet("gri", c.birim)}</p>
            <p><button class="dugme" data-cagri="${kac(c.id)}">Çağrı detayı</button> <button class="dugme ikincil" data-sayfa="cagri">Yeni çağrı</button>
            ${c.atama.uzman ? `<button class="dugme ikincil" data-sayfa="giderse" data-veri="${kac(c.atama.uzman.ad)}">${kac(c.atama.uzman.ad)} giderse?</button>` : ""}</p></div>
          ${atamaKart(c.atama, "Atanan kişi")}</div>
          <div>${c.toplu ? `<div class="not uyari"><b>Toplu arıza.</b> Aynı sorun son 60 dakikada ${c.toplu.cagri_sayisi} kişi tarafından bildirildi${c.toplu.yer ? " (" + kac(c.toplu.yer) + ")" : ""}; tek olayda (#${c.toplu.olay_id}) birleştirildi.</div>` : ""}
          ${otoKart(c.otomasyon)}${yolKart(c.yol)}</div></div>`;
    }
  };
  $("#ana").onchange = e => { if (e.target.id === "diger" && e.target.value) { document.querySelectorAll("[data-kat]").forEach(b => b.setAttribute("aria-pressed", false)); konuSec(+e.target.value); } };
  if (veri === "senaryo") { metin.value = ORNEKLER[0]; $("#vard").value = "gece"; $("#acil").value = "3"; $("#acan").value = "Sevkiyat"; oner(); }
};

/* ---------------------------------------------------------------- Kuyruk */
CIZ.kuyruk = async () => {
  $("#ana").innerHTML = `
  <h2>Çağrı kuyruğu</h2>
  <p class="alt">Açık çağrılar, en acil olan üstte. Bir çağrıya dokununca kime gittiğini, nedenini ve bu sorunun daha önce nasıl çözüldüğünü görürsün.</p>
  <div class="kart"><div class="sira">
    <div><label for="fd">Durum</label><select id="fd"><option value="acik">Açık</option><option value="kapali">Kapalı (son 50)</option></select></div>
    <div><label for="fb">Birim</label><select id="fb"><option value="">Hepsi</option>${T.birimler.filter(b => T.usta_birimleri.includes(b.ad)).map(b => `<option value="${kac(b.id)}">${kac(b.ad)}</option>`).join("")}</select></div>
  </div><div id="kl"></div></div>`;
  async function yukle() {
    const l = await api(`cagri?durum=${$("#fd").value}${$("#fb").value ? "&birim_id=" + $("#fb").value : ""}`);
    $("#kl").innerHTML = l.length ? `<ul class="liste">${l.map(c => `<li>
      ${rozet(c.aciliyet === 3 ? "kirmizi" : c.aciliyet === 2 ? "sari" : "gri", ["", "Düşük", "Orta", "Yüksek"][c.aciliyet])}
      <div class="govde"><a href="#detay" data-cagri="${kac(c.id)}">#${c.id} ${kac(c.metin)}</a>
      <div class="kucuk">${kac(c.kategori)} · ${c.durum === "acik" ? "Atanan: " + kac(c.atanan || "-") : "Çözen: " + kac(c.cozen || "-") + " · " + c.sure_dk + " dk" + (c.cozum_notu ? " · notlu" : "")} · ${tarih(c.acilis)}</div></div></li>`).join("")}</ul>`
      : '<p class="kucuk">Bu süzgeçte çağrı yok.</p>';
  }
  $("#fd").onchange = $("#fb").onchange = yukle; yukle();
};

CIZ.detay = async (id) => {
  const c = await api("cagri/" + id);
  const acik = c.durum === "acik";
  $("#ana").innerHTML = `
  <p><button class="dugme kucuk ikincil" data-sayfa="kuyruk">← Kuyruk</button></p>
  <h2>Çağrı #${c.id} ${rozet(acik ? "sari" : "yesil", acik ? "Açık" : "Kapalı")}</h2>
  <div class="iki genis">
    <div>
      <div class="kart"><p>${kac(c.metin)}</p>
        <p>${rozet("mavi", c.kategori)} ${rozet("gri", c.birim)} <span class="kucuk">Açan: ${kac(c.acan_birim)}${c.vardiya ? " · " + VARDIYA[c.vardiya] + " vardiyası" : ""}${c.guven != null ? " · konu olasılığı " + yuzde(c.guven) : ""}</span></p>
        <p><b>${acik ? "Atanan" : "Çözen"}:</b> ${kac((acik ? c.atanan : c.cozen) || (c.otomatik ? "Otomasyon" : "-"))}${c.sure_dk ? ` · ${c.sure_dk} dk` : ""}${c.acan_kisi ? ` <span class="kucuk">· Açan: ${kac(c.acan_kisi)}</span>` : ""}${c.teyit === 1 ? " " + rozet("yesil", "Açan kişi teyit etti") : c.teyit === 0 ? " " + rozet("kirmizi", "Açan kişi çözülmedi dedi") : ""}</p>
        ${c.cozum_notu ? `<h3 style="margin-top:.6rem">Nasıl çözüldü</h3>${adimlar(c.cozum_notu)}` : ""}
        <h3 style="margin-top:.7rem">Geçmiş</h3>
        <ul class="liste">${c.olaylar.map(o => `<li><span class="kucuk" style="min-width:5.5rem">${tarih(o.zaman)}</span><div class="govde">${{acildi: "Açıldı", atandi: "Atandı", yeniden_atandi: "Yeniden atandı", kapandi: "Kapandı"}[o.tur] || o.tur}${o.kisi ? ": " + kac(o.kisi) : ""}${o.aciklama ? `<div class="kucuk">${kac(o.aciklama)}</div>` : ""}</div></li>`).join("")}</ul>
      </div>
      ${acik ? `<div class="kart"><h3>Yanlış mı yönlendi?</h3>
        <p class="kucuk">Konuyu düzelt; çağrı yeni konunun en uygun kişisine gider. Çağrı kapanınca düzeltilmiş hâliyle modelin öğrenme verisine girer.</p>
        <div class="sira"><div><label for="yk">Doğru konu</label><select id="yk">${T.kategoriler.map(k => `<option value="${kac(k.id)}" ${k.id === c.kategori_id ? "selected" : ""}>${kac(k.birim)} · ${kac(k.ad)}</option>`).join("")}</select></div>
        <div style="flex:0 0 auto"><button class="dugme ikincil" id="ya">Yeniden yönlendir</button></div></div></div>
      <div class="kart"><h3>Çağrıyı kapat</h3>
        <label for="ka">Nasıl çözdün? (her satıra bir adım)</label><textarea id="ka" maxlength="2000" placeholder="Örn. Kilitli dalgayı iptal ettim&#10;Siparişleri yeni dalgada serbest bıraktım"></textarea>
        <p class="kucuk">Yazdığın adımlar bir sonraki benzer çağrıda “geçmişte nasıl çözüldü” bölümünde çıkar. Model her kapanan çağrıyla yeniden eğitilir.</p>
        <div class="sira"><div><label for="ks">Süre (dk)</label><input id="ks" type="number" min="1" value="${Math.max(5, Math.round((Date.now() - new Date(c.acilis)) / 60000) % 240 || 20)}"></div></div>
        <label style="display:flex;gap:.5rem;align-items:center;color:inherit;font-size:.9rem;margin-top:.7rem"><input type="checkbox" id="kk" style="width:auto"> Bunu konunun yazılı çözüm kartı yap</label>
        <div id="kalan" class="gizli"><label for="kb">Kart başlığı</label><input id="kb" maxlength="120"><label for="kn">Kök neden</label><input id="kn" maxlength="300"></div>
        <p style="margin-top:.7rem"><button class="dugme" id="kp">Kapat</button></p></div>` : ""}
    </div>
    <div>${c.toplu_olay ? `<div class="kart"><h3>Toplu arıza #${c.toplu_olay.olay_id}</h3><p class="kucuk">Bu çağrı aynı sorunu bildiren diğerleriyle birleşti. Biri kapanınca hepsi kapanır.</p>
        <ul class="liste">${c.toplu_olay.cagrilar.map(x => `<li>${rozet(x.durum === "acik" ? "sari" : "yesil", x.durum === "acik" ? "Açık" : "Kapalı")}<div class="govde"><a href="#detay" data-cagri="${kac(x.id)}">#${x.id}</a> ${kac(x.metin)}<div class="kucuk">${kac(x.acan_kisi || "")}</div></div></li>`).join("")}</ul></div>` : ""}
      ${otoKart(c.otomasyon)}
      ${c.mesajlar.length ? `<div class="kart"><h3>Teams mesajları</h3>${c.mesajlar.map(mesajKart).join("")}</div>` : ""}
      ${yolKart(c.yol)}
      ${c.yol.cagrilar.length ? `<div class="kart"><h3>En benzer çağrılar</h3><ul class="liste">${c.yol.cagrilar.map(b => `<li><div class="govde">${kac(b.metin)}<div class="kucuk">${kac(b.cozen || "-")} · ${b.sure_dk} dk · benzerlik ${yuzde(b.benzerlik)}${b.cozum_notu ? "" : " · not yok"}</div></div></li>`).join("")}</ul></div>` : ""}
    </div>
  </div>`;
  if (!acik) return;
  $("#kk").onchange = e => $("#kalan").classList.toggle("gizli", !e.target.checked);
  $("#ya").onclick = async () => { await api(`cagri/${id}/yeniden-ata`, {kategori_id: +$("#yk").value, aciklama: "Konu düzeltildi"}); bildir("Çağrı yeniden yönlendirildi."); git("detay", id); };
  $("#kp").onclick = async () => {
    await api(`cagri/${id}/kapat`, {sure_dk: +$("#ks").value || null, cozum_notu: $("#ka").value || null, karta_donustur: $("#kk").checked, baslik: $("#kb").value || null, kok_neden: $("#kn").value || null});
    bildir($("#ka").value.trim() ? "Çağrı kapandı; çözüm yolu öğrenildi." : "Çağrı kapandı. Not yazılmadığı için çözüm yolu öğrenilmedi."); git("detay", id);
  };
};

/* ---------------------------------------------------------------- Otomasyon */
const SENARYO = {
  kurulum_eksik: ["Kurulum, eksik bilgiyle", "BarTender isteniyor ama cihaz yazılmamış. Cihaz Teams’ten sorulur; lisanslı olduğu için yönetici onayı istenir."],
  kurulum_hizli: ["Kurulum, onaysız", "Power BI ücretsiz ve onay gerektirmiyor: kontroller geçer, kurulum hemen yapılır."],
  kurulum_lisanssiz: ["Lisans yok", "Acrobat’ın boş lisansı yok: otomasyon durur, çağrıyı insana devreder."],
  kurulum_katalog_disi: ["Katalog dışı yazılım", "AutoCAD onaylı katalogda yok: satın alma gerekir, insana kalır."],
  yetki: ["Yetki talebi", "Rol katalogdan bulunur, gerekçe sorulur, yönetici onaylar ya da reddeder."],
  sifre: ["Hesap kilidi", "Kimlik sicil numarasıyla doğrulanır; yanlış cevapta güvenlik gereği insana kalır."],
  yazici: ["Yazıcı: bilinen çözümü dene", "Kuyruğu temizle → sürücüyü yükle → yeniden başlat; her adımdan sonra test etiketi."],
  rapor: ["Rapor gelmedi", "Yükleme işi yeniden başlatılır, küp kontrol edilir, abonelik yeniden gönderilir."],
  terminal: ["Terminal ağa bağlanmıyor", "Ağ profili yeniden gönderilir, gerekirse cihaz uzaktan yeniden başlatılır."],
  toplu: ["Toplu arıza", "Üç kişi aynı anda B koridorunda Wi-Fi sorunu bildirir; çağrılar tek olayda birleşir."],
  bozulma: ["Otomasyon bozuldu", "Yazdırma sunucusu güncellendi, yazıcı otomatik çözümünün adımları artık pek tutmuyor. Sekiz çağrı gelir; başarı düşünce otomatik çözüm kendiliğinden askıya alınır."],
};
const SAGLIK_R = {eski_sistem: ["gri", "Eski sisteme bağlı"], iyi: ["yesil", "Sağlıklı"], dususte: ["sari", "Başarısı düşüyor"], askida: ["kirmizi", "Askıda"], yetersiz_veri: ["gri", "Ölçüm için az deneme"]};
let OTO_SON = null;
function sonKart(s) {
  if (!s) return "";
  if (s.recete_kod) return `<h3 style="margin:.2rem 0 .5rem">Son çalışma</h3>${otoKart(s)}`;
  const c = s;
  return `<h3 style="margin:.2rem 0 .5rem">Son çalışma</h3>
    <div class="kart"><p><a href="#detay" data-cagri="${kac(c.id)}">#${c.id}</a> ${kac(c.metin)}</p>
      <p>${rozet("mavi", c.kategori)} ${rozet(c.durum === "acik" ? "sari" : "yesil", c.durum === "acik" ? "Açık" : "Kapalı")} <span class="kucuk">Açan: ${kac(c.acan_kisi || "-")} · ${c.durum === "acik" ? "Atanan: " + kac(c.atanan || "-") : (c.otomatik ? "Otomasyonla kapandı" : "Çözen: " + kac(c.cozen || "-"))}</span></p>
      ${c.otomasyon ? "" : c.toplu_olay ? "" : '<p class="kucuk">Bu çağrıya uyan bir otomatik çözüm yok; normal yönlendirmeyle kişiye gitti.</p>'}
      ${c.cozum_notu ? `<div class="kucuk">Kapanış notu:</div>${adimlar(c.cozum_notu)}` : ""}</div>
    ${c.toplu_olay ? `<div class="kart"><h3>Toplu arıza #${c.toplu_olay.olay_id}</h3><ul class="liste">${c.toplu_olay.cagrilar.map(x => `<li>${rozet(x.durum === "acik" ? "sari" : "yesil", x.durum === "acik" ? "Açık" : "Kapalı")}<div class="govde"><a href="#detay" data-cagri="${kac(x.id)}">#${x.id}</a> ${kac(x.metin)}<div class="kucuk">${kac(x.acan_kisi || "")}</div></div></li>`).join("")}</ul>
      <p class="kucuk">Ana çağrıyı kapatınca diğerleri de kapanır ve herkese teyit sorusu gider. <a href="#detay" data-cagri="${kac(c.toplu_olay.cagrilar[0].id)}">Ana çağrıya git</a></p></div>` : ""}
    ${otoKart(c.otomasyon)}
    ${c.mesajlar.length ? `<div class="kart"><h3>Diğer Teams mesajları</h3>${c.mesajlar.map(mesajKart).join("")}</div>` : ""}`;
}
CIZ.otomasyon = async (veri) => {
  if (veri && SENARYO[veri]) { const r = await api("otomasyon/senaryo", {ad: veri}); OTO_SON = {cagri_id: r.cagri_id}; }
  const [d, son] = await Promise.all([api("otomasyon"),
    OTO_SON ? (OTO_SON.cagri_id ? api("cagri/" + OTO_SON.cagri_id) : api("otomasyon/" + OTO_SON.oto_id)) : null]);
  const o = d.ozet, p = d.potansiyel;
  const aktif = T.hesaplar.filter(h => h.durum === "aktif");
  $("#ana").innerHTML = `
  <h2>Otomatik çözümler</h2>
  <p class="alt">Şifre, yazıcı, kurulum gibi tekrar eden basit çağrılar, kuralların izin verdiği ölçüde insansız çözülür; gerekirse yöneticiden Teams'te onay istenir. Aşağıdan bir senaryo seçip baştan sona izleyebilirsin.</p>
  <details class="kart"><summary><b>Ne kendiliğinden, ne onayla yapılır?</b> <span class="kucuk">· ne kendiliğinden, ne onayla, ne yalnızca insanla yapılır</span></summary>
    <ul class="liste">
      <li>${rozet("yesil", "Otomatik")}<div class="govde">Kendi başına yapar: kilit açma, yazıcı/rapor/terminal onarım adımları, İK kaydıyla işe giriş ve çıkış paketi.</div></li>
      <li>${rozet("sari", "Onaylı otomatik")}<div class="govde">Yöneticinin Teams onayından sonra yapar: lisanslı yazılım kurulumu, rol ekleme.</div></li>
      <li>${rozet("gri", "Yalnızca insan")}<div class="govde">Önerir ama yapmaz: katalog dışı yazılım, notlardan türetilmiş taslak otomatik çözümler, parasal ya da geri alınamaz işler.</div></li></ul>
    <p class="kucuk">Bu demoda Teams, kimlik sistemi ve kurulum aracı simüle edilir. Gerçek kullanımda her adım ilgili sisteme (Intune, Active Directory, MDM…) bağlanır ve otomasyon, yalnızca kendi işine yetecek kadar yetkili bir servis hesabıyla çalışır; her adım kayda geçer.</p></details>
  ${(() => { const kotu = d.receteler.filter(r => r.saglik && ["askida", "dususte"].includes(r.saglik.durum)); return kotu.length ? `<div class="kart" style="border-color:var(--kirmizi)"><h3>Otomasyon sağlığı</h3>
    <p class="kucuk">Her otomatik çözümün son 30 gündeki gerçek başarısı izlenir. Beklenenin çok altına inerse uyarı verilir; %40’ın altına inerse otomatik çözüm kendiliğinden askıya alınır, çağrılar doğrudan insana gider ve risk haritasındaki otomasyon indirimi geri alınır.</p>
    <ul class="liste">${kotu.map(r => `<li>${rozet(...SAGLIK_R[r.saglik.durum])}<div class="govde"><b>${kac(r.ad)}</b><div class="kucuk">${kac(r.saglik.metin)}</div>
      ${r.saglik.durum === "askida" ? `<button class="dugme kucuk ikincil" style="margin-top:.3rem" data-devreye="${kac(r.kod)}">Düzeltildi, yeniden devreye al</button>` : ""}</div></li>`).join("")}</ul></div>` : ""; })()}
  <div class="iki genis">
    <div>
      ${son ? sonKart(son) : ""}
      ${T.mod === "yerel" ? `<div class="kart"><h3>Yerel veri</h3><p class="kucuk">Otomatik çözümler demo şirketin sistemlerine (kimlik, kurulum, yazdırma sunucusu) bağlı simülasyonlardır; kendi verinle kurulumda çalıştırılmaz. Sağdaki öneriler ve “notlardan otomatik çözüm adayları” kendi çağrı notlarından çıkar.</p></div>` : `<div class="kart"><h3>Senaryo dene <span class="demo-etiket" title="Gösterim içindir; gerçek kullanımda bu düğme yok">Demo</span></h3><p class="kucuk">Her düğme, hesabı olan kurgusal bir çalışanın ağzından gerçek bir çağrı açar. Teams sorularını ve onay kartlarını sen cevaplarsın. Onarım senaryolarında hangi adımın tutacağı her denemede değişebilir.</p>
        <ul class="liste">${Object.entries(SENARYO).map(([k, [ad, ac]]) => `<li><div class="govde"><b>${ad}</b><div class="kucuk">${ac}</div></div><button class="dugme kucuk ikincil" data-senaryo="${k}">Çalıştır</button></li>`).join("")}</ul></div>`}
    </div>
    <div>
      <div class="kart"><h3>Teams kutusu</h3><p class="kucuk">Cevap bekleyen sorular, onay kartları ve kapanış teyitleri.</p>
        ${d.bekleyen.length ? d.bekleyen.map(m => `${m.cagri_id ? `<div class="kucuk" style="margin-top:.5rem"><a href="#detay" data-cagri="${kac(m.cagri_id)}">Çağrı #${m.cagri_id}</a></div>` : ""}${mesajKart(m)}`).join("") : '<p class="kucuk">Bekleyen mesaj yok.</p>'}</div>
      ${T.mod === "yerel" ? "" : `<div class="kart"><h3>İK kaydıyla işe giriş ve çıkış</h3>
        <div class="sira"><div style="flex:2 1 180px"><label for="gad">Yeni çalışanın adı soyadı</label><input id="gad" maxlength="60" placeholder="Örn. Ece Yalın"></div>
          <div><label for="gbi">Birim</label><select id="gbi">${T.acan_birimler.map(b => `<option>${kac(b)}</option>`).join("")}</select></div>
          <div><label for="ggo">Görev</label><select id="ggo">${T.gorevler.map(g => `<option>${kac(g)}</option>`).join("")}</select></div></div>
        <p style="margin-top:.6rem"><button class="dugme" id="giris">İşe giriş paketini çalıştır</button></p>
        <div class="sira" style="margin-top:.6rem"><div style="flex:2 1 180px"><label for="cad">Ayrılan çalışan</label><select id="cad">${aktif.map(h => `<option>${kac(h.ad)}</option>`).join("")}</select></div>
          <div style="flex:0 0 auto"><button class="dugme ikincil" id="cikis">İşten çıkış paketini çalıştır</button></div></div></div>`}
    </div>
  </div>
  <h3 style="margin:.4rem 0 .5rem">Sayılarla</h3>
  <div class="izgara">
    <div class="olcu"><b>${o.calisma}</b><span>Otomasyon çalışması</span></div>
    <div class="olcu"><b style="color:var(--yesil)">${o.basarili}</b><span>İnsansız çözüldü</span></div>
    <div class="olcu"><b style="color:var(--kirmizi)">${o.insana}</b><span>İnsana devredildi</span></div>
    <div class="olcu"><b style="color:var(--sari)">${o.bekleyen_mesaj}</b><span>Cevap bekleyen Teams mesajı</span></div>
    <div class="olcu"><b>${o.toplu_olay}</b><span>Açık toplu arıza</span></div>
  </div>
  <div class="kart"><h3>Geçmişe uygulansaydı</h3>
    <p>Son ${p.gun} günün ${sy(p.toplam_cagri)} sistemsel çağrısının <b>${yek(p.kapsanan_oran, "i")}</b> bu otomatik çözümlere uyuyor. Beklenen başarı oranlarıyla yaklaşık <b>${yek(p.insansiz_oran, "i")}</b> insansız kapanırdı; bu ayda yaklaşık <b>${sy(p.kazanc_saat_ay)} saat</b> iş demek.</p>
    <div class="tablo-sar"><table><thead><tr><th>Otomatik çözüm</th><th>Seviye</th><th class="sayi">Ayda çağrı</th><th class="sayi">Bugünkü kapanma</th><th class="sayi">Beklenen başarı</th><th class="sayi">Kazanç (saat/ay)</th></tr></thead><tbody>
      ${p.satirlar.map(r => `<tr><td>${kac(r.ad)}</td><td>${rozet(SEVIYE_R[r.seviye][0], r.seviye_adi)}</td><td class="sayi">${sy(r.ayda)}</td><td class="sayi">${r.ort_kapanma_dk} dk</td><td class="sayi">${yuzde(r.basari_beklentisi)}</td><td class="sayi"><b>${sy(r.kazanc_saat_ay)}</b></td></tr>`).join("")}</tbody></table></div>
    <p class="kucuk">Kazanç, bir çalışanın bu işe harcadığı süreden hesaplanır; çağrının beklediği süre ayrıca kısalır. Beklenen başarı: onarımlarda adımların geçmiş tutma oranlarından, taleplerde %85 varsayımıyla (lisanssız, katalog dışı ve reddedilen talepler insana kalır).</p></div>
  <div class="kart"><h3>Notlardan otomatik çözüm adayları</h3>
    <p class="kucuk">Aynı çözüm yolu ${8} ve daha fazla kez yazılmışsa burada çıkar. Çevrilen otomatik çözüm <b>taslaktır</b>: çalıştırılmaz, adım adım rehber olarak gösterilir. Adımları gerçek sistemlere bağlamak BT’nin işidir; bağlanınca seviyesi yükseltilir.</p>
    ${d.adaylar.length ? `<ul class="liste">${d.adaylar.slice(0, 4).map((a, i) => `<li><div class="govde"><b>${kac(a.kategori)}</b> ${a.konuda_recete_var ? rozet("gri", "Konuda otomatik çözüm var") : rozet("mor", "Otomatik çözümü yok")}
      ${adimlar(a.adimlar)}<div class="kucuk">${a.tekrar} kez yazılmış (ayda ~${sy(a.ayda)}) · ${kac(a.kisiler.join(", "))} · tahmini ${sy(a.tahmini_saat_ay)} saat/ay</div></div>
      <button class="dugme kucuk ikincil" data-aday="${i}">Taslak otomatik çözüme çevir</button></li>`).join("")}</ul>` : '<p class="kucuk">Şu an eşiği geçen tekrar yok.</p>'}</div>
  <details class="kart"><summary><b>Otomatik çözüm kütüphanesi (${d.receteler.length})</b> <span class="kucuk">· adımlar, araçlar, sağlık, sayaçlar</span></summary>
    <ul class="liste" style="margin-top:.5rem">${d.receteler.map(r => `<li>${rozet(SEVIYE_R[r.seviye][0], r.seviye_adi)}<div class="govde"><b>${kac(r.ad)}</b> <span class="kucuk">· ${{talep: "Talep karşılama", onarim: "Bilinen çözümü dene", paket: "İK paketi", taslak: "Taslak"}[r.tur]} · ${kac(r.tanim.arac)}</span>
      <div class="kucuk">Sahibi: ${r.sahip ? kac(r.sahip) : '<b style="color:var(--kirmizi)">yok</b> (bozulursa düzeltecek kişi belli değil)'}</div>
      ${r.saglik ? `<div>${rozet(...SAGLIK_R[r.saglik.durum])} <span class="kucuk">${kac(r.saglik.metin)}</span>${r.saglik.durum === "askida" ? ` <button class="dugme kucuk ikincil" data-devreye="${kac(r.kod)}">Düzeltildi, yeniden devreye al</button>` : ""}</div>` : ""}
      <div class="kucuk">${kac(r.tanim.aciklama)}</div>
      <details><summary class="kucuk">Adımlar ve sayaçlar</summary>
        ${r.tanim.teshis ? `<p class="kucuk">Teşhis: ${kac(r.tanim.teshis)}</p>` : ""}
        ${adimlar(r.tanim.denemeler ? r.tanim.denemeler.map(x => x[0] + " → kontrol: " + x[1]) : r.tanim.adimlar)}
        <p class="kucuk">Geri alma: ${kac(r.tanim.geri_alma)}${r.tanim.bekleyen_is ? " · Bekleyen iş: " + kac(r.tanim.bekleyen_is) : ""}</p>
        <p class="kucuk">Çalıştı ${r.deneme} · başardı ${r.basari} · kullanıcı “çözülmedi” dedi ${r.teyit_hayir}</p></details></div></li>`).join("")}</ul></details>
  <div class="kart"><h3>Son çalışmalar</h3>
    ${d.calismalar.length ? `<ul class="liste">${d.calismalar.slice(0, 6).map(c => { const [r, t] = OTO_DURUM[c.durum] || ["gri", c.durum]; return `<li>${rozet(r, t)}<div class="govde"><b>${kac(c.recete)}</b> <span class="kucuk">· ${kac(c.kisi || "")}${c.cagri_id ? ` · <a href="#detay" data-cagri="${kac(c.cagri_id)}">#${c.cagri_id}</a>` : ""}</span>
      <details><summary class="kucuk">${kac((c.gunluk.at(-1) || {}).metin || "")}</summary>${otoKart(c, false)}</details></div></li>`; }).join("")}</ul>` : '<p class="kucuk">Henüz çalışma yok. Bir senaryo çalıştır.</p>'}</div>
  ${d.toplu.length ? `<div class="kart"><h3>Toplu arızalar</h3><ul class="liste">${d.toplu.map(t => `<li>${rozet(t.durum === "acik" ? "sari" : "yesil", t.durum === "acik" ? "Açık" : "Kapalı")}<div class="govde">#${t.id} ${kac(t.kategori)}${t.yer ? " · " + kac(t.yer) : ""}<div class="kucuk">${t.cagri} çağrı · başlangıç ${tarih(t.baslangic)}</div></div></li>`).join("")}</ul></div>` : ""}`;
  const ana = $("#ana");
  ana.onclick = async e => {
    const sn = e.target.closest("[data-senaryo]");
    if (sn) { sn.disabled = true; const r = await api("otomasyon/senaryo", {ad: sn.dataset.senaryo}).catch(() => null); if (r) { OTO_SON = {cagri_id: r.cagri_id}; await git("otomasyon", "yenile"); } return; }
    const dv = e.target.closest("[data-devreye]");
    if (dv) { dv.disabled = true; await api(`otomasyon/recete/${dv.dataset.devreye}/devreye-al`, {}); bildir("Otomatik çözüm yeniden devrede; başarı ölçümü sıfırdan başladı."); git("otomasyon", "yenile"); return; }
    const ad = e.target.closest("[data-aday]");
    if (ad) { const a = d.adaylar[+ad.dataset.aday]; await api("otomasyon/recete", {kategori_id: a.kategori_id, not_metni: a.not_metni}); bildir("Taslak otomatik çözüm oluşturuldu."); git("otomasyon", "yenile"); return; }
    if (e.target.id === "giris") { const r = await api("otomasyon/ise-giris", {ad: $("#gad").value, birim: $("#gbi").value, gorev: $("#ggo").value}); OTO_SON = {oto_id: r.id}; T = await api("tanimlar"); git("otomasyon", "yenile"); return; }
    if (e.target.id === "cikis") { const r = await api("otomasyon/isten-cikis", {ad: $("#cad").value}); OTO_SON = {oto_id: r.id}; T = await api("tanimlar"); git("otomasyon", "yenile"); }
  };
};

/* ---------------------------------------------------------------- Kartlar */
CIZ.kartlar = async () => {
  $("#ana").innerHTML = `<h2>Çözüm kütüphanesi</h2><p class="alt">Yazılı çözüm kartları. Kartı olmayan konularda Usta, çağrılara düşülen notlardan yol gösterir; not da yoksa bilgi yalnızca kişilerde durur.</p>
    <div class="kart"><label for="q">Kartlarda ara</label><input id="q" placeholder="Örn. ribon, adres, şifre"></div><div id="kk"></div>`;
  async function yukle() {
    const k = await api("kartlar" + ($("#q").value ? "?q=" + encodeURIComponent($("#q").value) : ""));
    $("#kk").innerHTML = `<div class="iki genis"><div>${k.kartlar.map(c => `<div class="kart"><b>${kac(c.baslik)}</b> ${rozet("mavi", c.kategori)}${adimlar(c.adimlar)}
      <div class="kucuk">Kök neden: ${kac(c.kok_neden || "-")} · Yazan: ${kac(c.yazan || "-")} · ${c.kullanim} çağrıda kullanıldı</div></div>`).join("") || '<div class="kart kucuk">Eşleşen kart yok.</div>'}</div>
      <div class="kart"><h3>Kartı olmayan konular</h3><ul class="liste">${k.kartsiz_kategoriler.map(c => `<li>${rozet(c.kritiklik === 3 ? "kirmizi" : c.kritiklik === 2 ? "sari" : "gri", "Kritiklik " + c.kritiklik)}<div class="govde">${kac(c.ad)}<div class="kucuk">${kac(c.birim)} · ${c.toplam} çağrının ${c.notlu} tanesinde çözüm notu var</div></div></li>`).join("")}</ul></div></div>`;
  }
  let b; $("#q").oninput = () => { clearTimeout(b); b = setTimeout(yukle, 300); }; yukle();
};

/* ---------------------------------------------------------------- Öğrenme */
CIZ.ogrenme = async () => {
  const m = await api("model"), d = m.degerlendirme, b = m.bilgi;
  const satir = (ad, model, kural, not) => `<tr><td>${ad}<div class="kucuk">${not}</div></td><td class="sayi"><b>${yuzde(model)}</b></td><td class="sayi">${yuzde(kural)}</td></tr>`;
  $("#ana").innerHTML = `
  <h2>Usta nasıl öğreniyor?</h2>
  <p class="alt">Usta’nın kuralları elle yazılmadı. Model, kapanan her çağrıdan konuyu, kimin çözdüğünü ve nasıl çözüldüğünü öğreniyor. Aşağıdaki başarı, modelin eğitimde hiç görmediği en yeni çağrılarda ölçüldü.</p>
  <div class="izgara">
    <div class="olcu"><b>${sy(b.ornek)}</b><span>Öğrenilen kapalı çağrı</span></div>
    <div class="olcu"><b>${sy(b.cozum_notlu)}</b><span>Çözüm notu olan çağrı</span></div>
    <div class="olcu"><b>${b.konu_sayisi} / ${b.kisi_sayisi}</b><span>Konu / kişi</span></div>
    <div class="olcu"><b>${sy(b.egitim_suresi_sn)} sn</b><span>Son eğitim · ${tarih(b.egitim_zamani)}</span></div>
  </div>
  <div class="kart"><h3>Test sonucu: model ve eski kural</h3>
    <p class="kucuk">Eğitim: en eski ${sy(d.egitim)} çağrı. Test: en yeni ${sy(d.test)} çağrı (${kac(d.test_araligi)}). Zamana göre ayırmak, modelin geleceği tahmin etme gücünü ölçer.</p>
    <div class="tablo-sar"><table><thead><tr><th>Soru</th><th class="sayi">Model</th><th class="sayi">Eski kural</th></tr></thead><tbody>
      ${satir("Konu doğru tahmin edildi mi?", d.konu.model, d.konu.kural, "Kural: konunun anahtar kelimelerinden biri metinde geçiyor mu?")}
      ${satir("Çözen kişi ilk sırada mı?", d.kisi.model, d.kisi.kural, "Kural: o vardiyada konuyu en çok çözmüş kişi")}
      ${satir("Çözen kişi ilk üçte mi?", d.kisi.model_ilk3, d.kisi.kural_ilk3, "Kural: konuyu en çok çözen üç kişi")}
    </tbody></table></div>
    <p class="kucuk">Model test çağrılarının ${yek(d.konu.soru_orani, "inde")} emin olamayıp soru sordu; emin olduğu çağrılarda konu doğruluğu ${yuzde(d.konu.emin_oldugunda)}.</p>
    <div class="not uyari">Dürüst not: veri sentetik olduğu için çağrı cümleleri sınırlı kalıplardan üretildi. Gerçek çağrılarda konu doğruluğu daha düşük çıkar. Kişi tahmininde %100 beklenmez; aynı türdeki çağrıyı o gün kim boştaysa o çözer.</div></div>
  ${(() => { const p = d.politika; if (!p) return ""; const r = (ad, x, not) => `<tr><td>${ad}<div class="kucuk">${not}</div></td><td class="sayi">${yuzde(x.yetkin_oran)}</td><td class="sayi">${yuzde(x.yogunlasma)}</td><td class="sayi">${sy(x.tahmini_sure)} dk</td></tr>`;
    return `<div class="kart"><h3>Kime verilmeli? Model ve paylaştırma</h3>
    <p class="kucuk">Kişi modeli geçmişte kimin çözdüğünden öğrenir; geçmişte işi hep aynı kişi aldıysa model de onu önerir ve tek kişiye bağımlılığı besler. Bu yüzden model yalnızca <b>kim biliyor</b> sorusuna cevap verir; <b>kime verilsin</b> sorusuna kural karar verir:</p>
    <ul class="kucuk" style="margin:.2rem 0 .5rem 1rem;padding:0"><li><b>İş yükü:</b> seçilen kişinin üzerinde ${m.esikler.yuk} ya da daha fazla açık çağrı varsa, konuyu bilen ve daha boş biri seçilir.</li>
      <li><b>Paylaştırma:</b> bir kişi vardiyada konunun ${yek(m.esikler.pay, "inden")} fazlasını tek başına çözüyorsa çağrı, konuyu bilen (son 90 günde en az 3 çözümü olan) başka birine verilir; uzman yedekte kalır. Acil ve kritik çağrıda bu yapılmaz.</li></ul>
    <div class="tablo-sar"><table><thead><tr><th>Test çağrıları kime giderdi?</th><th class="sayi">Bilene</th><th class="sayi">Toplanma</th><th class="sayi">Süre</th></tr></thead><tbody>
      ${r("Gerçekte", p.gercek, "o dönem kim çözdüyse")}
      ${r("Model, kalite ağırlığı olmadan", p.model_agirliksiz, `isabet ${yuzde(p.model_agirliksiz.isabet)}`)}
      ${r("Model, kalite ağırlığıyla", p.model, `isabet ${yuzde(p.model.isabet)}`)}
      ${r("Model + paylaştırma", p.politika, `çağrıların ${yek(p.paylastirilan, "i")} başka birine verildi`)}</tbody></table></div>
    <p class="kucuk">Bilene: konuyu son 90 günde en az 3 kez çözmüş birine gitme oranı. Toplanma: her konuda en çok çağrı alan kişinin payı (ortalama). Süre: seçilen kişinin o konudaki geçmiş ortanca süresi; konuda deneyimi yoksa 1,5 katı.</p>
    <div class="not">Dürüst not: bu demo verisinde fark küçük. Asıl bağımlılık, vardiyada hiç yedeği olmayan konulardan geliyor (sipariş dalgası, ERP entegrasyonu); oraya paylaştırma değil eğitim planı ve yanında öğrenme çare. Kalite ağırlığının etkisi de küçük, çünkü sentetik veride hızlı çözen zaten en çok çözen kişi. Gerçek veride ikisinin ayrıştığı durumlar (işi alan ama yavaş ya da yeniden açılan çözümler) daha çok olur.</div>
    <p style="display:flex;align-items:center;gap:.5rem;margin:.4rem 0 0"><input type="checkbox" id="pmod" ${m.paylastirma ? "checked" : ""} style="width:auto;margin:0"><label for="pmod" style="margin:0">Canlı yönlendirmede paylaştırma açık</label></p></div>`; })()}
  <div class="iki">
    <div class="kart"><h3>Üç öğrenme</h3>
      <ol class="adim">
        <li><b>Konu:</b> metin 3-5 harflik parçalara bölünür (“yazıcı” → “yaz”, “azı”, “zıc”…). Böylece “terminali”, “terminalde”, “termnal” gibi ekli ya da yanlış yazılmış sözcükler birbirine benzer. Her parçaya ağırlık verilir, lojistik regresyon her konuya bir olasılık atar.</li>
        <li><b>Kişi:</b> aynı metin, konu, vardiya ve açan birimle birlikte ikinci bir modele girer. Model, yazıcının <i>ağ</i> sorunlarını Tolga ile Onur’un, <i>ribon</i> sorunlarını Burak ile Selin’in çözdüğünü metinden öğrenir. Her geçmiş çağrı çözüm kalitesine göre ağırlık alır: olağandan hızlı çözülen ve “çözüldü” teyidi alan çağrılar daha çok sayılır.</li>
        <li><b>Nasıl çözüldü:</b> aynı konudaki en benzer ${m.esikler.komsu * 2} geçmiş çağrının çözüm notları aynı adımlara göre gruplanır; en benzer ve en sık yol önce gösterilir.</li></ol></div>
    <div class="kart"><h3>Ne zaman soruyor, nasıl düzeliyor?</h3>
      <ul><li>En yüksek konu olasılığı ${yek(m.esikler.soru, "in")} altındaysa ya da ikinci aday ${Math.round(m.esikler.fark * 100)} puandan yakınsa sistem tahmin etmez, sorar.</li>
      <li>Teknik bir arıza yazılırsa (sorter, forklift…) Usta bunu kendi konusu saymaz, bakım sistemine yönlendirir.</li>
      <li>Yanlış yönlenen çağrı düzeltilip kapatılınca model düzeltilmiş hâlini öğrenir. Model her kapanan çağrıdan sonra yeniden eğitilir; bu demo verisinde bir saniyeden kısa sürer.</li>
      <li>Hiçbir veri dışarıdaki bir yapay zekâ servisine gitmez; model bu sunucuda çalışır.</li></ul>
      <p><button class="dugme ikincil" id="egit">Şimdi yeniden eğit</button></p></div>
  </div>`;
  if ($("#pmod")) $("#pmod").onchange = async e => { await api("paylastirma", {acik: e.target.checked}); bildir(e.target.checked ? "Paylaştırma açıldı." : "Paylaştırma kapatıldı; çağrılar modelin ilk seçtiği kişiye gider."); };
  $("#egit").onclick = async () => { const r = await api("model/egit", {}); bildir(`Model ${sy(r.ornek)} çağrıyla ${sy(r.egitim_suresi_sn)} saniyede yeniden eğitildi.`); git("ogrenme"); };
};

/* ---------------------------------------------------------------- Risk */
function formulKutu(f) {
  return `<details class="kart"><summary><b>Puan nasıl hesaplanıyor?</b></summary>
  <p>Puan = 100 × ((${sy(f.yogunlasma)} × yoğunlaşma + ${sy(f.yedek)} × yedek riski) × (1 − otomasyon payı) + ${sy(f.kart)} × yazısızlık) × kritiklik çarpanı</p>
  <ul><li><b>Yoğunlaşma:</b> son ${f.pencere_gun} günde konuyu en çok çözen kişinin payı.</li>
  <li><b>Yedek riski:</b> konuyu en az ${f.yetkin_esigi} kez çözmüş kişi sayısına göre. 0-1 kişi → 1 · 2 kişi → 0,5 · 3 kişi → 0,2 · 4 ve üzeri → 0.</li>
  <li><b>Yazısızlık:</b> çözüm kartı, otomatik çözüm (taslak dahil) ya da dökümde yazılı talimat yoksa 1.</li>
  <li><b>Otomasyon payı:</b> konunun çağrılarından otomasyonla insansız kapanması beklenen pay. Bu pay kişiye bağlı olmadığı için yoğunlaşma ve yedek bileşenleri (1 − pay) ile çarpılır.</li>
  <li><b>Pratiği kalmamış yedek:</b> 91-365 gün önce konuyu en az 3 kez çözmüş, son 60 günde hiç çözmemiş kişi. Puana girmez ama nedenlerde yazar; eğitim planı bu kişileri üçte bir süreyle “tazeler”.</li>
  <li><b>Kritiklik çarpanı:</b> 1 → ${sy(f.kritiklik[1])} · 2 → ${sy(f.kritiklik[2])} · 3 → ${sy(f.kritiklik[3])}.</li></ul>
  <p class="kucuk">${f.kirmizi} ve üzeri yüksek, ${f.sari}-${f.kirmizi - 1} orta, altı düşük. Ağırlıklar bir tercihtir; kod içinde tek satırda değiştirilebilir.</p></details>`;
}
function isiTablo(b) {
  return `<div class="kart"><h3>${kac(b.birim)}</h3><p class="kucuk">Hücre: kişinin son 90 günde o konuda çözdüğü çağrı sayısı. Koyuluk payı gösterir. <b>○</b> kâğıtta biliyor görünüyor ama fiilen çözmüyor. <b>↺</b> eskiden çözüyordu, pratiği kalmamış.</p>
  <div class="tablo-sar"><table class="isi"><thead><tr><th>Konu</th><th class="sayi">Risk</th>${b.kisiler.map(p => `<th class="kisi">${kac(p.ad)} <span style="opacity:.6">(${VARDIYA[p.vardiya][0]})</span></th>`).join("")}<th>Kâğıtta / fiilen</th></tr></thead>
  <tbody>${b.satirlar.map(s => `<tr><td class="ad">${kac(s.ad)}</td><td class="sayi">${puanKutu(s)}</td>
    ${s.hucreler.map(h => `<td class="h" style="background:rgba(20,80,107,${(h.pay * .85).toFixed(2)});color:${h.pay > .5 ? "#fff" : "inherit"}" ${h.eski ? 'title="Pratiği kalmamış: eskiden çözüyordu"' : ""}>${h.n || (h.eski ? "↺" : h.beyan ? "○" : "")}</td>`).join("")}
    <td class="kucuk" style="white-space:nowrap">${s.beyan_sayisi} / <b>${s.gercek_sayisi}</b></td></tr>`).join("")}</tbody></table></div></div>`;
}
function riskListe(konular, dugmeler = true) {
  return `<ul class="liste">${konular.map(k => `<li>${puanKutu(k)}<div class="govde"><b>${kac(k.ad)}</b> <span class="kucuk">· ${kac(k.birim)} · ${SEVIYE[k.seviye]} risk</span> ${rozet(k.kaynak === "Usta" ? "mavi" : "gri", k.kaynak)}
    ${k.yeni_konu ? (k.yeni_konu.erken_uyari ? rozet("kirmizi", "Yeni sistem · erken uyarı") : rozet("mor", "Yeni konu · geçici puan")) : ""}
    <div class="kucuk">${k.nedenler.length ? kac(k.nedenler.join(" · ")) : "Belirgin bir bağımlılık yok"}</div>
    ${k.azaltanlar && k.azaltanlar.length ? `<div class="kucuk" style="color:var(--yesil)">Azaltan: ${kac(k.azaltanlar.join(" · "))}</div>` : ""}
    ${k.beyan_sayisi > k.gercek_sayisi ? `<div class="kucuk">Kâğıtta ${k.beyan_sayisi} kişi yapabilir görünüyor, fiilen ${k.gercek_sayisi} kişi yapıyor.</div>` : ""}
    ${dugmeler && k.gecis ? `<button class="dugme kucuk ikincil" style="margin-top:.35rem" data-sayfa="degisim">Geçiş durumu</button> ` : ""}
    ${dugmeler && k.en_cok_cozen && k.seviye === "kirmizi" ? `<button class="dugme kucuk ikincil" style="margin-top:.35rem" data-sayfa="giderse" data-veri="${kac(k.en_cok_cozen.ad)}">${kac(k.en_cok_cozen.ad)} giderse?</button>` : ""}</div></li>`).join("")}</ul>`;
}
CIZ.risk = async () => {
  const r = await api("risk");
  $("#ana").innerHTML = `
  <h2>Risk haritası</h2>
  <p class="alt">Hangi iş tek kişiye bağlı? Harita, son 90 günde işi gerçekte kimin çözdüğüne bakar; kâğıttaki yetkinliğe değil. En riskli işler en üstte; her satırdan doğrudan “o kişi yoksa ne olur” ya da eğitim planına geçebilirsin.</p>
  <div class="izgara"><div class="olcu"><b style="color:var(--kirmizi)">${r.ozet.kirmizi}</b><span>Yüksek</span></div><div class="olcu"><b style="color:var(--sari)">${r.ozet.sari}</b><span>Orta</span></div><div class="olcu"><b style="color:var(--yesil)">${r.ozet.yesil}</b><span>Düşük</span></div><div class="olcu"><b>${sy(r.ozet.ortalama)}</b><span>Ortalama puan</span></div></div>
  ${r.kaynaklar.filter(k => k.eski).map(k => `<div class="not uyari">${kac(k.kaynak)} ${k.gun} gündür güncellenmedi. Bu kaynağın konuları eksik veriyle hesaplanıyor; son haftaların çözümleri sayılmadığı için risk yapay olarak yüksek görünebilir. Dökümün güncelini içe aktarın.</div>`).join("")}
  <div class="kart"><h3>En riskli işler</h3>
    <div id="rliste">${riskListe(r.konular.slice(0, 5))}</div>
    <p style="margin:.6rem 0 0"><button class="dugme kucuk ikincil" id="rhepsi">Bütün işler (${r.konular.length}) ve süzgeçler</button>
      <button class="dugme kucuk ikincil" data-sayfa="plan">Bu riskleri düşürecek planı çıkar</button></p>
    <div id="rsuzgec" hidden>
    <div class="sira" style="margin:.8rem 0 .4rem"><div><label for="rsev">Seviye</label><select id="rsev"><option value="">Hepsi</option><option value="kirmizi">Yüksek</option><option value="sari">Orta</option><option value="yesil">Düşük</option></select></div>
      <div><label for="rbir">Birim</label><select id="rbir"><option value="">Hepsi</option>${[...new Set(r.konular.map(k => k.birim))].map(b => `<option>${kac(b)}</option>`).join("")}</select></div>
      <div style="flex:0 0 auto;align-self:flex-end"><a class="dugme ikincil" style="text-decoration:none;display:inline-block" href="/api/risk.csv">Excel için indir (CSV)</a></div></div>
    <p class="kucuk" style="margin:.2rem 0 0">Kaynaklar: ${r.kaynaklar.map(k => `${kac(k.kaynak)} (son kayıt ${tarih(k.son_kayit)}, son 90 günde ${k.pencerede})`).join(" · ")}</p>
    </div></div>
  <details class="kart acilir"><summary><b>Kim hangi işi biliyor?</b> <span class="kucuk">· iş × kişi tablosu</span></summary>${r.matris.map(isiTablo).join("")}</details>
  <details class="kart acilir"><summary><b>Risk zaman içinde nasıl değişti?</b></summary><div id="seyir"><p class="kucuk">Hesaplanıyor…</p></div></details>
  <details class="kart acilir"><summary><b>Otomatikleştirilebilecek riskli işler</b></summary><div id="firsat"><p class="kucuk">Hesaplanıyor…</p></div></details>
  ${formulKutu(r.formul)}`;
  const suz = () => { const sv = $("#rsev").value, bi = $("#rbir").value; $("#rliste").innerHTML = riskListe(r.konular.filter(k => (!sv || k.seviye === sv) && (!bi || k.birim === bi))) || '<p class="kucuk">Bu süzgeçle konu yok.</p>'; };
  $("#rsev").onchange = $("#rbir").onchange = suz;
  $("#rhepsi").onclick = () => { $("#rsuzgec").hidden = false; $("#rhepsi").hidden = true; suz(); };
  riskEkleri();
};

/* ---------------------------------------------------------------- Emanet: seyir, fırsat, izin, devir, plan takibi */
function seyirKart(r) {
  const n = r.noktalar;
  if (n.length < 2) return '<div class="kart kucuk">Seyir için yeterli geçmiş yok.</div>';
  const W = 520, H = 170, sol = 34, alt = 26, ust = 12, sag = 10, gw = W - sol - sag, gh = H - ust - alt;
  const ic = 18;   // çubukların eksene ve kenara taşmaması için iç boşluk
  const x = i => sol + ic + (n.length === 1 ? (gw - 2 * ic) / 2 : i * (gw - 2 * ic) / (n.length - 1));
  const ay = t => { const d = new Date(t); return d.getDate() + " " + ["Oca", "Şub", "Mar", "Nis", "May", "Haz", "Tem", "Ağu", "Eyl", "Eki", "Kas", "Ara"][d.getMonth()]; };
  const ymax1 = Math.max(40, Math.ceil(Math.max(...n.map(p => p.ortalama)) / 10) * 10);
  const y1 = v => ust + gh - v / ymax1 * gh;
  const ymax2 = Math.max(4, Math.max(...n.map(p => p.kirmizi)));
  const y2 = v => ust + gh - v / ymax2 * gh;
  const t0 = new Date(n[0].tarih).getTime(), t1 = new Date(n.at(-1).tarih).getTime();
  const xt = t => sol + ic + (new Date(t).getTime() - t0) / Math.max(1, t1 - t0) * (gw - 2 * ic);
  const olay = r.olaylar.filter(o => !o.metin.startsWith("Çözüm kartı"));
  const izgara = (ymax, y, adim) => { let s = ""; for (let v = 0; v <= ymax; v += adim) s += `<line x1="${sol}" x2="${W - sag}" y1="${y(v)}" y2="${y(v)}" stroke="#e7e4dc"/><text x="${sol - 6}" y="${y(v) + 4}" text-anchor="end" font-size="11" fill="#5d6875">${v}</text>`; return s; };
  const eksen = n.map((p, i) => i % 2 === 0 || i === n.length - 1 ? `<text x="${x(i)}" y="${H - 8}" text-anchor="${i === n.length - 1 ? "end" : i === 0 ? "start" : "middle"}" font-size="11" fill="#5d6875">${ay(p.tarih)}</text>` : "").join("");
  const olayCiz = olay.map((o, i) => `<g><title>${kac(o.tarih)}: ${kac(o.metin)}</title><line x1="${xt(o.tarih)}" x2="${xt(o.tarih)}" y1="${ust}" y2="${ust + gh}" stroke="#8a5a00" stroke-dasharray="3 3"/><circle cx="${xt(o.tarih)}" cy="${ust + 6}" r="7" fill="#fdf1d3" stroke="#8a5a00"/><text x="${xt(o.tarih)}" y="${ust + 10}" text-anchor="middle" font-size="10" fill="#8a5a00" font-weight="600">${i + 1}</text></g>`).join("");
  const cizgi = `<svg viewBox="0 0 ${W} ${H}" width="100%" role="img" aria-label="Ortalama risk puanının seyri">${izgara(ymax1, y1, ymax1 / 4)}${olayCiz}
    <polyline fill="none" stroke="#14506b" stroke-width="2" points="${n.map((p, i) => `${x(i)},${y1(p.ortalama)}`).join(" ")}"/>
    ${n.map((p, i) => `<g><title>${ay(p.tarih)}: ortalama ${sy(p.ortalama)}</title><circle cx="${x(i)}" cy="${y1(p.ortalama)}" r="9" fill="transparent"/><circle cx="${x(i)}" cy="${y1(p.ortalama)}" r="4" fill="#14506b" stroke="#fff" stroke-width="2"/></g>`).join("")}${eksen}
    <text x="${x(n.length - 1)}" y="${y1(n.at(-1).ortalama) - 10}" text-anchor="end" font-size="12" font-weight="600" fill="#1c2430">${sy(n.at(-1).ortalama)}</text></svg>`;
  const bw = Math.min(26, (gw - 2 * ic) / n.length - 8);
  const bar = `<svg viewBox="0 0 ${W} ${H}" width="100%" role="img" aria-label="Yüksek riskli konu sayısının seyri">${izgara(ymax2, y2, Math.max(1, Math.ceil(ymax2 / 4)))}${olayCiz}
    ${n.map((p, i) => `<g><title>${ay(p.tarih)}: ${p.kirmizi} yüksek riskli konu</title><rect x="${x(i) - bw / 2}" y="${y2(p.kirmizi)}" width="${bw}" height="${Math.max(0, ust + gh - y2(p.kirmizi))}" rx="3" fill="#b3261e" fill-opacity=".8"/>${p.kirmizi ? `<text x="${x(i)}" y="${y2(p.kirmizi) - 4}" text-anchor="middle" font-size="11" fill="#1c2430">${p.kirmizi}</text>` : ""}</g>`).join("")}${eksen}</svg>`;
  // Konu o tarihte yoksa (yeni sistem) o noktalar çizilmez
  const spark = s => { const w = 130, h = 28; return `<svg viewBox="0 0 ${w} ${h}" width="${w}" height="${h}" aria-hidden="true"><line x1="0" x2="${w}" y1="${h - 2 - 60 / 100 * (h - 4)}" y2="${h - 2 - 60 / 100 * (h - 4)}" stroke="#fbe9e7"/><polyline fill="none" stroke="#14506b" stroke-width="2" points="${s.map((z, i) => z == null ? "" : `${i * w / (s.length - 1)},${h - 2 - z / 100 * (h - 4)}`).join(" ")}"/>${s.filter(z => z != null).length === 1 ? s.map((z, i) => z == null ? "" : `<circle cx="${i * w / (s.length - 1)}" cy="${h - 2 - z / 100 * (h - 4)}" r="3" fill="#14506b"/>`).join("") : ""}</svg>`; };
  return `<div class="kart"><h3>Risk zaman içinde</h3>
    <p class="kucuk">Her nokta o tarihten geriye 90 günün çağrılarıyla hesaplandı (iki haftada bir). Numaralı çizgiler alınan kararlardır.</p>
    <div class="iki"><div><div class="kucuk"><b>Ortalama risk puanı</b></div>${cizgi}</div><div><div class="kucuk"><b>Yüksek riskli konu sayısı</b></div>${bar}</div></div>
    ${olay.length ? `<ol class="kucuk" style="margin:.4rem 0 .6rem 1.1rem;padding:0">${olay.map(o => `<li>${tarih(o.tarih + "T00:00").slice(0, 5)} · ${kac(o.metin)}</li>`).join("")}</ol>` : ""}
    <div class="tablo-sar"><table><thead><tr><th>Konu</th><th>Seyir</th><th class="sayi">İlk</th><th class="sayi">Bugün</th></tr></thead><tbody>
    ${r.izlenen.map(z => `<tr><td>${kac(z.ad)}</td><td>${spark(z.seri)}</td><td class="sayi">${z.seri.find(v => v != null) ?? "-"}</td><td class="sayi"><span class="puan ${sev(z.seri.at(-1) ?? 0)}" style="height:1.7rem;min-width:2.2rem">${z.seri.at(-1) ?? "-"}</span></td></tr>`).join("")}</tbody></table></div>
    <details><summary class="kucuk">Tablo olarak</summary><div class="tablo-sar"><table><thead><tr><th>Tarih</th><th class="sayi">Ortalama</th><th class="sayi">Yüksek</th><th class="sayi">Orta</th><th class="sayi">Düşük</th></tr></thead><tbody>
      ${n.map(p => `<tr><td>${kac(p.tarih)}</td><td class="sayi">${sy(p.ortalama)}</td><td class="sayi">${p.kirmizi}</td><td class="sayi">${p.sari}</td><td class="sayi">${p.yesil}</td></tr>`).join("")}</tbody></table></div></details></div>`;
}
function firsatKart(f) {
  if (!f.length) return "";
  return `<div class="kart"><h3>Riskli işlerde otomatik çözüm fırsatı</h3>
    <p class="kucuk">Bu konuların yazılı çözümü yok ama uzmanın çağrılara düştüğü notlarda aynı çözüm yolu tekrar ediyor. Not taslak otomatik çözüme çevrilirse “yazılı çözüm yok” bileşeni kalkar.</p>
    <ul class="liste">${f.map((x, i) => `<li><span style="white-space:nowrap"><span class="puan ${x.seviye_once}">${x.puan_once}</span><span class="ok">→</span><span class="puan ${x.seviye_sonra}">${x.puan_sonra}</span></span>
      <div class="govde"><b>${kac(x.kategori)}</b> <span class="kucuk">· uzman ${kac(x.uzman || "-")} · bu yol ${x.tekrar} kez yazılmış</span>${adimlar(x.adimlar)}
      <button class="dugme kucuk ikincil" data-firsat="${i}">Taslak otomatik çözüme çevir</button></div></li>`).join("")}</ul></div>`;
}
async function riskEkleri() {
  const [s, f] = await Promise.all([api("risk/seyri"), api("risk/firsatlar")]);
  if (durum.sayfa !== "risk") return;
  $("#seyir").innerHTML = seyirKart(s);
  $("#firsat").innerHTML = firsatKart(f) || '<p class="kucuk">Şu an otomatikleştirilebilecek riskli iş yok.</p>';
  $("#firsat").onclick = async e => {
    const b = e.target.closest("[data-firsat]"); if (!b) return;
    const x = f[+b.dataset.firsat]; b.disabled = true;
    await api("otomasyon/recete", {kategori_id: x.kategori_id, not_metni: x.not_metni});
    bildir(`${x.kategori}: taslak otomatik çözüm oluşturuldu, risk yeniden hesaplandı.`); git("risk");
  };
}

function devirKart(d) {
  const o = d.ozet;
  return `<div class="kart"><h3>Devir dosyası: ${kac(d.kisi.ad)}</h3>
    <p class="kucuk">${kac(d.kisi.birim)} · ${kac(d.kisi.rol)} · ${VARDIYA[d.kisi.vardiya]} vardiyası</p>
    <div class="izgara"><div class="olcu"><b>${o.konu}</b><span>Çözdüğü konu</span></div><div class="olcu"><b style="color:var(--kirmizi)">${o.kritik}</b><span>Kritik devir</span></div>
      <div class="olcu"><b>${o.acik_is}</b><span>Açık iş</span></div><div class="olcu"><b>${o.tahmini_devir_saati} sa</b><span>Kritik devirlerin süresi</span></div></div>
    <ul class="liste">${d.konular.map(k => `<li>${rozet(k.kritik ? "kirmizi" : "gri", k.kritik ? "Kritik" : "Normal")}<div class="govde"><b>${kac(k.ad)}</b>
      <div class="kucuk">Çağrıların ${yek(k.pay, "ini")} çözüyor · geride ${k.kalan_yetkinler.length ? kac(k.kalan_yetkinler.join(", ")) : "bilen yok"} · yazılı çözüm ${k.kart_var ? "var" : "yok"} · notlu çözüm ${yuzde(k.not_orani)}</div>
      <div class="kucuk">Önerilen devralan: <b>${kac(k.devralan || "-")}</b> (${kac(k.devralan_neden)})</div>
      ${k.adimlar.length ? `<ul class="kucuk" style="margin:.2rem 0 0 1rem;padding:0">${k.adimlar.map(a => `<li>${kac(a)}</li>`).join("")}</ul>` : ""}
      ${k.cozum_yollari.length ? `<details><summary class="kucuk">Bildiği çözüm yolları (${k.cozum_yollari.length})</summary>${k.cozum_yollari.map(y => `<div class="kucuk" style="margin-top:.3rem">${y.kez} kez:</div>${adimlar(y.adimlar)}`).join("")}</details>` : ""}</div></li>`).join("")}</ul>
    ${d.otomasyonlar.length ? `<h3 style="margin-top:.6rem">Bakımını yaptığı otomasyonlar</h3><p class="kucuk">Bunlar bozulursa düzeltecek kişi o. Betikler, servis hesabı ve doğrulama adımları yeni sahibine devredilmeli.</p><ul class="liste">${d.otomasyonlar.map(a => `<li>${rozet("mor", {talep: "Talep", onarim: "Onarım", paket: "İK paketi", taslak: "Taslak"}[a.tur])}<div class="govde">${kac(a.ad)}</div></li>`).join("")}</ul>` : ""}
    ${d.acik_isler.length ? `<h3 style="margin-top:.6rem">Açık işleri</h3><ul class="liste">${d.acik_isler.map(a => `<li><div class="govde"><a href="#detay" data-cagri="${kac(a.id)}">#${a.id}</a> ${kac(a.metin)}<div class="kucuk">${kac(a.kategori)}</div></div></li>`).join("")}</ul>` : ""}
    <p><a class="dugme ikincil" style="text-decoration:none;display:inline-block" href="/api/devir/${d.kisi.id}/indir">Markdown olarak indir</a></p></div>`;
}

// "Biri yoksa": aynı soru iki durumda. Üstteki seçim iki ekran arasında geçirir.
function yoksaBasligi(etkin) {
  return `<h2>Biri yoksa</h2>
  <div class="secim" role="group" aria-label="Durum">
    <button class="dugme kucuk${etkin === "izin" ? "" : " ikincil"}" data-sayfa="izin" aria-pressed="${etkin === "izin"}">Tarihli izin</button>
    <button class="dugme kucuk${etkin === "giderse" ? "" : " ikincil"}" data-sayfa="giderse" aria-pressed="${etkin === "giderse"}">Ayrılık ya da uzun süre yok</button>
  </div>`;
}
CIZ.izin = async () => {
  const [izl] = await Promise.all([api("izinler")]);
  const bugun = new Date(), g = d => new Date(bugun.getTime() + d * 864e5).toISOString().slice(0, 10);
  const gruplar = T.birimler.map(b => `<optgroup label="${kac(b.ad)}">${T.kisiler.filter(p => p.birim_id === b.id).map(p => `<option value="${kac(p.id)}" ${p.ad === "Elif Kaya" ? "selected" : ""}>${kac(p.ad)} · ${VARDIYA[p.vardiya]}</option>`).join("")}</optgroup>`).join("");
  $("#ana").innerHTML = `
  ${yoksaBasligi("izin")}
  <p class="alt">İzni onaylamadan önce bak: bu kişi o tarihlerde yokken hangi işler sahipsiz kalır? Karar senin; araç etkiyi ve varsa daha uygun bir tarihi gösterir.</p>
  <div class="kart"><div class="sira">
    <div style="flex:2 1 220px"><label for="ik">Kişi</label><select id="ik">${gruplar}</select></div>
    <div><label for="ib">Başlangıç</label><input id="ib" type="date" value="${g(5)}"></div>
    <div><label for="ie">Bitiş</label><input id="ie" type="date" value="${g(14)}"></div>
    <div style="flex:0 0 auto"><button class="dugme" id="ih">Kontrol et</button></div></div></div>
  <div id="is"></div>
  <div class="kart"><h3>Kayıtlı izinler</h3>${izl.length ? `<ul class="liste">${izl.map(i => `<li>${rozet(i.tur === "rapor" ? "sari" : "gri", i.tur === "rapor" ? "Rapor" : "İzin")}<div class="govde">${kac(i.ad)}<div class="kucuk">${kac(i.baslangic)} – ${kac(i.bitis)}</div></div></li>`).join("")}</ul>` : '<p class="kucuk">Önümüzde kayıtlı izin yok.</p>'}</div>`;
  async function kontrol() {
    const k = await api("izin/kontrol", {kisi_id: +$("#ik").value, baslangic: $("#ib").value, bitis: $("#ie").value});
    const renk = {dikkat: "kirmizi", uyari: "sari", uygun: "yesil"}[k.karar];
    $("#is").innerHTML = `<div class="not ${k.karar === "uygun" ? "" : "uyari"}">${rozet(renk, {dikkat: "Dikkat", uyari: "Uyarı", uygun: "Uygun"}[k.karar])} <b>${kac(k.kisi.ad)}, ${kac(k.baslangic)} – ${kac(k.bitis)} (${k.gun} gün).</b> ${kac(k.mesaj)}</div>
      ${k.alternatif ? `<div class="kart"><b>Daha uygun tarih:</b> ${kac(k.alternatif.baslangic)} – ${kac(k.alternatif.bitis)} <span class="kucuk">(${k.alternatif.fark_gun > 0 ? k.alternatif.fark_gun + " gün sonra" : -k.alternatif.fark_gun + " gün önce"}; sorun puanı ${k.sorun_puani} → ${k.alternatif.sorun_puani})</span>
        <p><button class="dugme kucuk ikincil" id="ia">Bu tarihleri dene</button></p></div>` : ""}
      <div class="kart"><h3>Bildiği konular</h3>${k.konular.length ? `<ul class="liste">${k.konular.map(x => `<li>${rozet(x.durum === "yedeksiz" ? "kirmizi" : x.durum === "tek kişi" ? "sari" : "yesil", x.durum === "güvenli" ? "Yedekli" : x.durum === "yedeksiz" ? "Yedeksiz" : "Tek kişi")}
        <div class="govde"><b>${kac(x.ad)}</b> <span class="kucuk">· kritiklik ${x.kritiklik} · günde ${sy(x.gunluk_cagri)} çağrı</span>
        <div class="kucuk">Geride: ${x.kalan.length ? kac(x.kalan.join(", ")) : "kimse"}${x.izindeki_yedekler.length ? " · aynı dönemde izinde: " + kac(x.izindeki_yedekler.join(", ")) : ""}${x.vardiya_bosalir ? " · kendi vardiyasında bilen kalmıyor" : ""}${x.kart_var ? " · yazılı çözüm var" : ""}</div></div></li>`).join("")}</ul>` : '<p class="kucuk">Bu kişi son 90 günde düzenli çağrı çözmemiş; izni haritayı etkilemiyor.</p>'}
        ${k.cakisan_izinler.length ? `<p class="kucuk">Aynı dönemde izinde olanlar: ${k.cakisan_izinler.map(i => kac(i.ad) + " (" + kac(i.baslangic) + " – " + kac(i.bitis) + ")").join(", ")}</p>` : ""}
        <p><button class="dugme ${k.karar === "uygun" ? "" : "ikincil"}" id="ikay">İzni kaydet</button> <span class="kucuk">Kaydedilen izin atamaları, risk haritasını ve diğer kontrolleri etkiler.</span></p></div>`;
    if ($("#ia")) $("#ia").onclick = () => { $("#ib").value = k.alternatif.baslangic; $("#ie").value = k.alternatif.bitis; kontrol(); };
    $("#ikay").onclick = async () => { await api("izin/kaydet", {kisi_id: +$("#ik").value, baslangic: $("#ib").value, bitis: $("#ie").value}); bildir("İzin kaydedildi."); T = await api("tanimlar"); git("izin"); };
  }
  $("#ih").onclick = kontrol; kontrol();
};

function takipKart(t) {
  if (!t.var) return `<div class="kart"><h3>Kayıtlı plan</h3><p class="kucuk">Henüz kaydedilmiş bir plan yok. Planı çıkarıp “Bu planı kaydet” dersen, uygulanıp uygulanmadığını buradan takip edebilirsin.</p></div>`;
  const etiket = {"yetkin oldu": "yesil", "başladı": "sari", "henüz çözmedi": "kirmizi", "yazıldı": "yesil", "yazılmadı": "kirmizi"};
  return `<div class="kart"><h3>Kayıtlı planın takibi</h3>
    <p class="kucuk">Plan tarihi ${tarih(t.plan_tarihi)}. Eğitimde ölçü: öğrenen kişi plan tarihinden sonra o konuda en az 3 çağrı çözdü mü? Kartta: konu için kart ya da otomatik çözüm yazıldı mı?</p>
    <div class="izgara"><div class="olcu"><b>${yuzde(t.tutma_orani)}</b><span>Planın tutma oranı (${t.tamamlanan}/${t.toplam})</span></div>
      <div class="olcu"><b>${t.konular.filter(k => k.hedefe_ulasti).length}/${t.konular.length}</b><span>Hedef puana inen konu</span></div></div>
    <ul class="liste">${t.satirlar.map(s => `<li>${rozet(etiket[s.sonuc], s.sonuc)}<div class="govde"><b>${kac(s.kategori)}</b> <span class="kucuk">· ${s.tur === "kart" ? "kart: " + kac(s.ogreten || "-") : (s.tur === "tazeleme" ? "tazeleme: " : s.tur === "gecis" ? "geçiş eğitimi: " : "eğitim: ") + kac(s.ogreten || "-") + " → " + kac(s.ogrenen)}</span>
      ${s.tur !== "kart" ? `<div class="kucuk">Plandan sonra ${s.cozulen} çağrı çözdü${s.ort_sure ? ", ortalama " + s.ort_sure + " dk" : ""}</div>` : ""}</div>
      <span style="white-space:nowrap" title="Plan anı → hedef → bugün"><span class="puan ${sev(s.puan_once)}">${s.puan_once}</span><span class="ok">→</span><span class="puan ${sev(s.puan_simdi)}">${s.puan_simdi}</span></span></li>`).join("")}</ul>
    <p class="kucuk">Sağdaki sayılar: plan anındaki puan → bugünkü puan. Hedefe inemeyen konularda hangi satırın tutmadığına bak.</p>
    ${t.simule ? "" : `<div class="not uyari">Plan yeni kaydedildi; henüz sonucu yok. Demo için planın 30 gün önce kaydedildiğini ve uygulandığını varsayarak o dönemin çağrılarını üretebilirsin. Bazı satırlar bilerek tutmaz.</div><p><span class="demo-etiket" title="Gösterim içindir; gerçek kullanımda bu düğme yok">Demo</span> <button class="dugme ikincil" id="psim">30 gün sonrasını simüle et</button></p>`}</div>`;
}

/* Hesap düğmesi geri bildirimi: sonuç aynı çıksa bile basıldığı belli olsun */
async function dugmeyleHesapla(dugme, is, ileti, hedef) {
  const eski = dugme.textContent;
  dugme.disabled = true; dugme.textContent = "Hesaplanıyor…";
  try {
    await is(); bildir(ileti());
    if (hedef) { const h = $(hedef); h.classList.remove("yenilendi"); void h.offsetWidth; h.classList.add("yenilendi"); h.scrollIntoView({behavior: "smooth", block: "start"}); }
  }
  finally { dugme.disabled = false; dugme.textContent = eski; }
}

/* ---------------------------------------------------------------- Ya giderse */
CIZ.giderse = async (ad) => {
  // Doğrudan sekmeden gelinirse boş sayfa yerine en riskli konunun ustasıyla başla
  let varsayilan = false;
  if (!ad) {
    try { ad = (await api("risk")).konular.find(k => k.en_cok_cozen)?.en_cok_cozen.ad; varsayilan = !!ad; } catch { /* boş kalır */ }
  }
  const gruplar = T.birimler.map(b => `<optgroup label="${kac(b.ad)}">${T.kisiler.filter(p => p.birim_id === b.id).map(p => `<option value="${kac(p.id)}" ${p.ad === ad ? "selected" : ""}>${kac(p.ad)} · ${kac(p.rol)}</option>`).join("")}</optgroup>`).join("");
  $("#ana").innerHTML = `
  ${yoksaBasligi("giderse")}
  <p class="alt">Bu kişi bir süre hiç olmazsa (ayrılık, uzun rapor) hangi işler sahipsiz kalır, çağrılar ne kadar fazla bekler?</p>
  <div class="kart"><div class="sira">
    <div style="flex:2 1 220px"><label for="gk">Kişi</label><select id="gk">${gruplar}</select></div>
    <div><label for="gg">Kaç gün yok?</label><input id="gg" type="number" min="1" max="365" value="21"></div>
    <div><label for="gm">Bekleme maliyeti (TL/dk)</label><input id="gm" type="number" min="0" value="0"></div>
    <div style="flex:0 0 auto"><button class="dugme" id="gh">Hesapla</button></div></div>
    <p class="kucuk">Maliyet isteğe bağlıdır; bir çağrının beklediği her dakikanın işe maliyetini sen girersin.</p>
    ${varsayilan ? `<p class="kucuk">Örnek olarak en riskli konunun ustası seçildi; başka birini seçip <b>Hesapla</b>'ya bas.</p>` : ""}</div>
  <div id="gs"></div>`;
  async function hesapla() {
    const y = await api("ya-giderse", {kisi_id: +$("#gk").value, gun: +$("#gg").value || 21, dakika_maliyeti: +$("#gm").value || 0});
    $("#gs").innerHTML = `
    <div class="not ${y.yedeksiz_kalan.length ? "uyari" : ""}"><b>${kac(y.ozet)}</b></div>
    <div class="izgara">
      <div class="olcu"><b style="color:var(--kirmizi)">${y.yedeksiz_kalan.length}</b><span>Yedeksiz kalan konu</span></div>
      <div class="olcu"><b>${sy(y.beklenen_cagri)}</b><span>Bu sürede ona düşecek çağrı</span></div>
      <div class="olcu"><b>${sy(y.ek_saat)} sa</b><span>Beklenen ek bekleme</span></div>
      ${y.dakika_maliyeti ? `<div class="olcu"><b>${y.tl_etkisi.toLocaleString("tr-TR")} ₺</b><span>Ek beklemenin maliyeti</span></div>` : ""}
      <div class="olcu"><b>${y.ozet_once.kirmizi}<span class="ok">→</span>${y.ozet_sonra.kirmizi}</b><span>Yüksek riskli konu sayısı</span></div>
    </div>
    <div class="kart"><h3>Etkilenen konular</h3>
      ${y.etkilenen.length ? `<ul class="liste">${y.etkilenen.map(e => `<li>
        <span style="white-space:nowrap"><span class="puan ${e.seviye_once}">${e.puan_once}</span><span class="ok">→</span><span class="puan ${e.seviye_sonra}">${e.puan_sonra}</span></span>
        <div class="govde"><b>${kac(e.ad)}</b> ${e.yedeksiz ? rozet("kirmizi", "Yedeksiz") : ""} ${e.kart_var ? "" : rozet("gri", "Yazılı çözüm yok")}
        <div class="kucuk">Bu konunun ${yek(e.pay, "ini")} çözüyor · geride ${e.kalan_yetkin ? kac(e.kalan_yetkinler.join(", ")) : "bilen yok"} · ${sy(e.beklenen_cagri)} çağrı, süre ×${sy(e.sure_carpani)} → +${e.ek_dakika} dk</div></div></li>`).join("")}</ul>`
        : '<p class="kucuk">Bu kişi son 90 günde çağrı çözmemiş; gidişi haritayı değiştirmiyor.</p>'}
    </div>
    ${y.otomasyonlar.length ? `<div class="kart"><h3>Bakımını yaptığı otomasyonlar</h3><p class="kucuk">Çağrı çözmek dışında da ona bağlı işler var: bu otomatik çözümler bozulursa (sistem güncellemesi, şifre değişikliği…) düzeltecek kişi o. Yokken bozulan otomatik çözüm askıya düşer ve çağrılar insana döner.</p>
      <ul class="liste">${y.otomasyonlar.map(a => `<li>${rozet("mor", {talep: "Talep", onarim: "Onarım", paket: "İK paketi", taslak: "Taslak"}[a.tur])}<div class="govde">${kac(a.ad)}</div></li>`).join("")}</ul></div>` : ""}
    <details class="kart"><summary><b>Hesabın varsayımları</b></summary>
      <ul><li>Beklenen çağrı = konunun günlük çağrı sayısı × gün × kişinin o konudaki payı.</li>
      <li>Çözüm süresi çarpanı: geride bilen biri varsa 1,1 · yoksa ama yazılı çözüm varsa 1,5 · ikisi de yoksa 2,5.</li>
      <li>Ek bekleme = beklenen çağrı × konunun temel çözüm süresi × (çarpan − 1).</li></ul></details>
    <p><button class="dugme" data-sayfa="plan" data-veri="60">Bu riski düşürecek planı çıkar</button> <button class="dugme ikincil" id="gdv">Devir dosyası hazırla</button></p>
    <div id="gdd"></div>`;
    $("#gdv").onclick = async () => { $("#gdd").innerHTML = devirKart(await api("devir/" + $("#gk").value)); $("#gdd").scrollIntoView({behavior: "smooth"}); };
  }
  $("#gh").onclick = () => dugmeyleHesapla($("#gh"), hesapla,
    () => `${$("#gk").selectedOptions[0].textContent.split(" · ")[0]} için yeniden hesaplandı.`, "#gs");
  if (ad) hesapla();
};

/* ---------------------------------------------------------------- Plan */
function sonrakiPazartesi() {
  const d = new Date(); d.setDate(d.getDate() + ((8 - d.getDay()) % 7 || 7));
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`;
}
// Takvimde elle yapılan değişiklikler: haftaya özel sınır (0 = ötelendi) ve o hafta olmayan kişiler.
// Sayfa yenilenince sıfırlanır; kalıcı hali Excel çıktısıdır.
const planDeg = {hafta_sinir: {}, kisi_yok: []};
let planGor = "takvim", sonTakvim = null;
function planIstegi() {
  return {butce_saat: +$("#pb").value || 0, yontem: $("#py").value, haftalik_sinir: +$("#tsin").value || 2,
          oturum_saat: +$("#tot").value, gunluk_oturum: +$("#tgo").value, calisma_gunu: +$("#tcg").value,
          baslangic: $("#tbas").value || null, hafta_sinir: planDeg.hafta_sinir, kisi_yok: planDeg.kisi_yok};
}
function csvAdresi() {
  const {hafta_sinir, kisi_yok, ...r} = planIstegi();
  const q = new URLSearchParams(Object.entries(r).filter(([, v]) => v !== null));
  if (Object.keys(hafta_sinir).length || kisi_yok.length) q.set("degisiklik", JSON.stringify({hafta_sinir, kisi_yok}));
  return "/api/egitim-plani/takvim.csv?" + q.toString();
}
function degisiklikSeridi(t) {
  const adi = id => (t.kisiler.find(k => k.kisi_id === id) || T.kisiler.find(k => k.id === id) || {ad: "#" + id}).ad;
  const bitisGunu = h => { const d = new Date(haftaTarihi(t, h) + "T12:00:00"); d.setDate(d.getDate() + t.ayarlar.calisma_gunu - 1); return d.toISOString().slice(0, 10); };
  const metin = ([a, b]) => (a === b ? `${a}. hafta` : `${a}.–${b}. hafta`) + ` (${kisaTarih(haftaTarihi(t, a))} – ${kisaTarih(bitisGunu(b))})`;
  const durdu = araliklar(Object.entries(planDeg.hafta_sinir).filter(([, v]) => +v === 0).map(([h]) => +h));
  const saatler = Object.entries(planDeg.hafta_sinir).filter(([, v]) => +v > 0);
  const kisiler = [...new Set(planDeg.kisi_yok.map(([k]) => k))];
  const p = [
    ...durdu.map(r => `<button class="cip" data-dsil="hr:${r[0]}:${r[1]}" title="Geri al">Eğitim durdu: ${metin(r)} ✕</button>`),
    ...saatler.map(([h, v]) => `<button class="cip" data-dsil="h:${kac(h)}" title="Geri al">${kac(h)}. hafta kişi başı ${sy(+v)} sa ✕</button>`),
    ...kisiler.flatMap(k => araliklar(planDeg.kisi_yok.filter(([kk]) => kk === k).map(([, h]) => h))
      .map(r => `<button class="cip" data-dsil="kr:${kac(k)}:${r[0]}:${r[1]}" title="Geri al">${kac(adi(k))} yok: ${metin(r)} ✕</button>`))];
  return p.length ? `<div class="not degisiklik"><b>Elle değişiklikler:</b> ${p.join(" ")} <button class="dugme kucuk ikincil" data-dsil="hepsi">Hepsini geri al</button></div>` : "";
}
const kisaTarih = iso => new Date(iso + "T12:00:00").toLocaleDateString("tr-TR", {day: "numeric", month: "long"});
const gunAy = iso => new Date(iso + "T12:00:00").toLocaleDateString("tr-TR", {weekday: "short", day: "numeric", month: "short"});
function takvimOzeti(t) {
  if (!t.oturumlar.length) return "";
  const d = t.darbogaz;
  return `Takvim ${t.hafta_sayisi} hafta sürer, ${kisaTarih(t.bitis)} tarihinde biter. `
    + `Süreyi <b>${kac(d.ad)}</b> belirliyor: toplam ${sy(d.toplam)} saat eğitimde (${d.verdigi ? sy(d.verdigi) + " saat veriyor" : ""}${d.verdigi && d.aldigi ? ", " : ""}${d.aldigi ? sy(d.aldigi) + " saat alıyor" : ""}). `
    + `Haftalık sınırı artırmak ya da onun öğreteceği konuyu başka biriyle paylaştırmak takvimi kısaltır.`;
}
function haftaKontrolleri(t, h, os) {
  const sinir = planDeg.hafta_sinir[h] ?? t.ayarlar.haftalik_sinir;
  return `<div class="hafta-ayar">
    <span class="saat-ayar"><span class="kucuk">Bu hafta kişi başı</span>
      <button class="dugme kucuk ikincil" data-hsaat="${h}" data-fark="-${t.ayarlar.oturum_saat}" aria-label="${h}. hafta saati azalt" ${sinir <= t.ayarlar.oturum_saat ? "disabled" : ""}>−</button>
      <b>${sy(sinir)} sa</b>
      <button class="dugme kucuk ikincil" data-hsaat="${h}" data-fark="${t.ayarlar.oturum_saat}" aria-label="${h}. hafta saati artır" ${sinir >= 40 ? "disabled" : ""}>+</button></span>
    <details class="degistir"><summary>Durdur ya da izin ekle…</summary>
      <div class="sira">
        <div><label for="dk${h}">Kim</label><select id="dk${h}" data-dk="kim"><option value="">Herkes: eğitimi durdur</option>${t.kisiler.map(k => `<option value="${kac(k.kisi_id)}">${kac(k.ad)} izinde / yok</option>`).join("")}</select></div>
        <div><label for="ds${h}">Ne kadar</label><select id="ds${h}" data-dk="sure"><option value="1">Yalnız bu hafta</option><option value="2">2 hafta</option><option value="3">3 hafta</option><option value="4">4 hafta</option><option value="tarih">Şu tarihte yeniden başla…</option></select></div>
        <div data-dk-tarih hidden><label for="dt${h}">Yeniden başlama tarihi</label><input id="dt${h}" type="date" data-dk="tarih" min="${haftaTarihi(t, h + 1)}"></div>
        <div style="flex:0 0 auto"><button class="dugme kucuk" data-uygula="${h}">Uygula</button></div>
      </div>
      <p class="kucuk">${h}. haftadan başlar. Takvim hafta hafta çalışır: seçilen tarihin düştüğü hafta yeniden başlama haftasıdır.</p></details>
  </div>`;
}
// Takvimin h. haftasının pazartesisi (ISO) ve bir tarihin düştüğü hafta numarası
function haftaTarihi(t, h) { const d = new Date(t.ayarlar.baslangic + "T12:00:00"); d.setDate(d.getDate() + (h - 1) * 7); return d.toISOString().slice(0, 10); }
function tarihHaftasi(t, iso) { return Math.floor((new Date(iso + "T12:00:00") - new Date(t.ayarlar.baslangic + "T12:00:00")) / 864e5 / 7) + 1; }
// Ardışık haftaları aralığa topla: [2,3,4,7] → [[2,4],[7,7]]
function araliklar(haftalar) {
  const a = [...new Set(haftalar)].sort((x, y) => x - y), r = [];
  for (const h of a) { const son = r.at(-1); if (son && son[1] === h - 1) son[1] = h; else r.push([h, h]); }
  return r;
}
function takvimGorunumu(t) {
  const haftalar = new Map();
  const son = Math.max(t.hafta_sayisi, ...Object.keys(planDeg.hafta_sinir).map(Number).filter(h => h <= t.hafta_sayisi + 1), ...planDeg.kisi_yok.map(([, h]) => h).filter(h => h <= t.hafta_sayisi));
  for (let h = 1; h <= son; h++) haftalar.set(h, []);
  for (const o of t.oturumlar) haftalar.get(o.hafta).push(o);
  const biten = h => t.konular.filter(k => k.bitis_haftasi === h);
  return [...haftalar].map(([h, os]) => {
    if (!os.length) {
      const otelendi = +planDeg.hafta_sinir[h] === 0;
      return `<div class="kart hafta bos"><h3>${h}. hafta <span class="kucuk">· ${otelendi ? "ötelendi, eğitim yok" : "oturum yok"}</span></h3>
        ${otelendi ? `<button class="dugme kucuk ikincil" data-dsil="h:${h}">Geri al</button>` : `<p class="kucuk">Bu haftaya sığan oturum kalmadı (sınır ya da izin).</p>`}</div>`;
    }
    const gunler = new Map();
    for (const o of os) { if (!gunler.has(o.tarih)) gunler.set(o.tarih, []); gunler.get(o.tarih).push(o); }
    const pzt = new Date(t.ayarlar.baslangic + "T12:00:00"); pzt.setDate(pzt.getDate() + (h - 1) * 7);
    const son = new Date(pzt); son.setDate(son.getDate() + t.ayarlar.calisma_gunu - 1);
    const iso = d => d.toISOString().slice(0, 10);
    return `<div class="kart hafta"><h3>${h}. hafta <span class="kucuk">· ${kisaTarih(iso(pzt))} – ${kisaTarih(iso(son))} · ${os.length} oturum, ${sy(os.reduce((a, o) => a + o.saat, 0))} saat</span></h3>
      ${[...gunler].map(([g, gos]) => `<div class="gun"><div class="gun-ad">${gunAy(g)}</div><ul class="oturumlar">${gos.map(o => `<li>
        <b>${kac(o.kategori)}</b> <span class="kucuk">${sy(o.saat)} sa${o.parca_sayisi > 1 ? ` · ${o.parca}/${o.parca_sayisi}` : ""}</span><br>
        ${planCumlesi(o)}${(o.gundem || []).length ? `<ul class="gundem">${o.gundem.map(m => `<li>${kac(m)}</li>`).join("")}</ul>` : ""}</li>`).join("")}</ul></div>`).join("")}
      ${haftaKontrolleri(t, h, os)}
      ${biten(h).length ? `<p class="kucuk tamam">Bu hafta tamamlanır: ${biten(h).map(k => `<b>${kac(k.kategori)}</b> (${k.puan_once} → ${k.puan_sonra})`).join(", ")}</p>` : ""}
    </div>`;
  }).join("");
}
function kisiGorunumu(t) {
  return `<div class="kart"><h3>Kimin ne kadar saati gidiyor?</h3>
    <p class="kucuk">Eğitim veren de alan da o saatte işinin başında değildir. Üst sıradakiler takvimi uzatan kişilerdir.</p>
    <div class="tablo-sar"><table><thead><tr><th>Kişi</th><th class="sayi">Veriyor</th><th class="sayi">Alıyor</th><th class="sayi">Toplam</th><th class="sayi">Hafta</th></tr></thead><tbody>
    ${t.kisiler.map(k => `<tr><td>${kac(k.ad)}</td><td class="sayi">${k.verdigi ? sy(k.verdigi) : "-"}</td><td class="sayi">${k.aldigi ? sy(k.aldigi) : "-"}</td><td class="sayi"><b>${sy(k.toplam)}</b></td><td class="sayi">${k.hafta_sayisi}</td></tr>`).join("")}
    </tbody></table></div></div>`;
}

// Plan satırları adım adımdır; aynı konu birkaç satırda geçer. Ekranda konu konu toplanır.
function planKonulari(satirlar) {
  const m = new Map();
  for (const s of satirlar) {
    if (!m.has(s.kategori_id)) m.set(s.kategori_id, {kategori_id: s.kategori_id, kategori: s.kategori, once: s.puan_once, sonra: s.puan_sonra, saat: 0, adimlar: []});
    const g = m.get(s.kategori_id); g.saat += s.saat; g.adimlar.push(s);
  }
  return [...m.values()];
}
function planCumlesi(s) {
  const o = `<b>${kac(s.ogreten || "-")}</b>`, l = `<b>${kac(s.ogrenen || "-")}</b>`;
  return {kart: `${o} çözümü adım adım karta yazar; herkes okuyabilir.`,
          egitim: `${o}, ${l} kişisine bu konuyu öğretir.`,
          tazeleme: `${o}, eskiden bu işi yapan ${l} kişisinin bilgisini tazeler.`,
          gecis: `${o}, ${l} kişisini yeni sisteme geçirir.`}[s.tur] || kac(s.neden);
}
function planOzeti(p) {
  if (!p.satirlar.length) return "Bu bütçeyle yapılabilecek bir adım yok; bütçeyi artırın.";
  const say = t => p.satirlar.filter(s => s.tur === t).length, konu = planKonulari(p.satirlar).length;
  const parca = [say("kart") && `${say("kart")} konunun çözümü karta yazılır`, say("egitim") && `${say("egitim")} kişi yeni bir konu öğrenir`,
    say("tazeleme") && `${say("tazeleme")} kişinin eski bilgisi tazelenir`, say("gecis") && `${say("gecis")} kişi yeni sisteme geçirilir`].filter(Boolean);
  return `${p.kullanilan_saat} saatlik eğitimle ${konu} konuda iş yapılır: ${parca.join(", ")}. `
    + `Sonuçta yüksek riskli (kırmızı) konu sayısı ${sek(p.ozet_once.kirmizi, "den")} ${sek(p.ozet_sonra.kirmizi, "e")}, ortalama risk ${sek(p.ozet_once.ortalama, "den")} ${sek(p.ozet_sonra.ortalama, "e")} iner. `
    + `Önce en riskli konular ele alınır; en ucuz adım genelde çözümü karta yazmaktır (2 saat).`;
}
CIZ.plan = async (butce) => {
  $("#ana").innerHTML = `
  <h2>Eğitim planı</h2>
  <p class="alt">Elindeki eğitim saatiyle, tek kişiye bağlı işleri en çok azaltacak adımları seçer: kim, neyi, kime öğretecek ve sonunda ne değişecek.</p>
  <details class="kart"><summary><b>Plan hangi adımları kullanır?</b></summary>
    <ul><li><b>Karta yaz</b>: işi bilen kişi, eski çağrılardaki çözüm yollarını adım adım yazıya döker (kart = konunun yazılı çözüm talimatı). Süresini sen girersin.</li>
    <li><b>Öğret</b>: usta ile öğrenen önce kartı okur, sonra konunun eski çağrılarının üzerinden geçer (belirti → teşhis → çözüm), sonra sıradaki gerçek çağrıyı öğrenen usta yanındayken çözer. Öğrenen 3 çağrıyı tek başına kapatınca konuyu “biliyor” sayılır. Süresini sen girersin.</li>
    <li><b>Tazele</b> (öğretmenin üçte biri): eskiden bu işi yapan ama uzun süredir yapmayan birinin bilgisi tazelenir.</li>
    <li><b>Yeni sisteme geçir</b> (öğretmenin yarısı): sistem değiştiyse, eski sistemde bu işi yapan yenisine alıştırılır.</li></ul></details>
  <div class="kart"><div class="sira">
    <div><label for="pb">Eğitim bütçesi (saat)</label><input id="pb" type="number" min="0" max="500" value="${+butce || 60}"></div>
    <div><label for="py">Yöntem</label><select id="py"><option value="optimum">Optimizasyon</option><option value="kural">Basit kural</option></select></div>
    <div style="flex:0 0 auto"><button class="dugme" id="ph">Planı çıkar</button></div></div>
    <details class="ayarlar" open><summary>Takvim ayarları <span class="kucuk" id="pozet"></span></summary>
      <p class="kucuk">Depoda personel iş varken uzun süre eğitime çekilemez. Takvim adımları kısa oturumlara böler ve kişi başı sınırı aşmadan haftalara yayar. Sınır, eğitim veren ve alan için ayrı ayrı geçerlidir.</p>
      <div class="sira">
        <div><label for="tsin">Kişi başı haftada en fazla (saat)</label><input id="tsin" type="number" min="0.5" max="40" step="0.5" value="2"></div>
        <div><label for="tot">Oturum süresi</label><select id="tot"><option value="0.5">30 dakika</option><option value="1" selected>1 saat</option><option value="1.5">1,5 saat</option><option value="2">2 saat</option><option value="3">3 saat</option><option value="4">4 saat</option></select></div>
        <div><label for="tgo">Kişi başı günde en fazla</label><select id="tgo"><option value="1" selected>1 oturum</option><option value="2">2 oturum</option><option value="3">3 oturum</option><option value="4">4 oturum</option></select></div>
        <div><label for="tcg">Çalışma günleri</label><select id="tcg"><option value="5" selected>Pazartesi–Cuma</option><option value="6">Pazartesi–Cumartesi</option></select></div>
        <div><label for="tbas">Başlangıç haftası</label><input id="tbas" type="date" value="${sonrakiPazartesi()}"></div>
      </div></details></div>
  <details class="kart" id="psure" ${butce === "sureler" ? "open" : ""}><summary><b>Konu süreleri</b> <span class="kucuk" id="psozet">· kart yazma ve öğretme saatleri; sen girersin</span></summary>
    <p class="kucuk">Plan bu süreleri kullanır. Girmediğin konularda tahmini süre kullanılır ve planda “tahmini süre” diye işaretlenir; yeni açılan bir konunun süresi de girilene kadar tahminidir. Tazeleme öğretmenin üçte biri, yeni sisteme geçiş yarısı sayılır.</p>
    <div id="pstablo"><p class="kucuk">Yükleniyor…</p></div></details>
  <div id="ps"></div><div id="ptk"></div>`;
  async function hesapla() {
    const p = await api("egitim-plani", planIstegi());
    const t = p.takvim; sonTakvim = t;
    $("#pozet").textContent = `· haftada ${sy(t.ayarlar.haftalik_sinir)} sa, ${sy(t.ayarlar.oturum_saat)} saatlik oturum, ${t.ayarlar.calisma_gunu === 6 ? "Pzt–Cmt" : "Pzt–Cum"}`;
    const k = p.karsilastirma, once = p.ozet_once, sonra = p.ozet_sonra;
    $("#ps").innerHTML = `
    <div class="izgara">
      <div class="olcu"><b>${once.kirmizi}<span class="ok">→</span><span style="color:var(--yesil)">${sonra.kirmizi}</span></b><span>Yüksek riskli konu</span></div>
      <div class="olcu"><b>${sy(once.ortalama)}<span class="ok">→</span>${sy(sonra.ortalama)}</b><span>Ortalama risk puanı</span></div>
      <div class="olcu"><b>${t.hafta_sayisi ? t.hafta_sayisi + " hafta" : "-"}</b><span>${t.bitis ? kisaTarih(t.bitis) + " biter" : "Takvim"}</span></div>
      <div class="olcu"><b>${p.kullanilan_saat} / ${p.butce_saat}</b><span>Kullanılan saat</span></div>
    </div>
    <div class="not"><b>Bu plan ne diyor?</b> ${planOzeti(p)}${t.oturumlar.length ? `<p style="margin:.5rem 0 0"><b>Ne zaman?</b> ${takvimOzeti(t)}</p>` : ""} <span class="kucuk">Hesaplandı: ${new Date().toLocaleTimeString("tr-TR")}</span></div>
    ${t.oturumlar.length ? `<div class="gorunum" role="group" aria-label="Görünüm">
      ${[["takvim", "Takvim"], ["kisi", "Kişi kişi"], ["konu", "Konu konu"]].map(([g, a]) => `<button class="dugme kucuk${planGor === g ? "" : " ikincil"}" data-gor="${g}" aria-pressed="${planGor === g}">${a}</button>`).join("")}
      <a class="dugme kucuk ikincil" href="${kac(csvAdresi())}" download>Excel'e indir</a></div>
    <div data-gorunum="takvim" ${planGor === "takvim" ? "" : "hidden"}>${degisiklikSeridi(t)}${takvimGorunumu(t)}</div>
    <div data-gorunum="kisi" ${planGor === "kisi" ? "" : "hidden"}>${kisiGorunumu(t)}</div>
    <div data-gorunum="konu" ${planGor === "konu" ? "" : "hidden"}>` : `<div>`}
    <div class="kart"><h3>Konu konu ne yapılacak?</h3>
      <p class="kucuk">Her konuda soldaki puan bugünkü risk, sağdaki bu konunun bütün adımları bitince beklenen risk. Altındaki adımlar o düşüşü birlikte sağlar.</p>
      ${p.satirlar.length ? `<ul class="liste">${planKonulari(p.satirlar).map(g => `<li>
        <span style="white-space:nowrap"><span class="puan ${sev(g.once)}">${g.once}</span><span class="ok">→</span><span class="puan ${sev(g.sonra)}">${g.sonra}</span></span>
        <div class="govde"><b>${kac(g.kategori)}</b> ${rozet("gri", g.saat + " saat")} ${(t.konular.find(k => k.kategori_id === g.kategori_id) || {}).bitis_haftasi ? rozet("mavi", t.konular.find(k => k.kategori_id === g.kategori_id).bitis_haftasi + ". haftada biter") : ""}
          <ol class="adim">${g.adimlar.map(s => `<li>${planCumlesi(s)} <span class="kucuk">(${sy(s.saat)} sa · ${kac(s.neden)})</span>
            ${s.sure_tahmini ? `<button class="cip uyari-cip" data-sure-ac="${kac(s.kategori_id)}" title="Bu konunun süresini sen gir">tahmini süre · düzelt</button>` : ""}
            <details class="icerik"><summary>Ne yapılacak?</summary>
              <ul class="gundem">${(s.gundem || []).map(m => `<li>${kac(m)}</li>`).join("")}</ul>
              ${s.tur !== "kart" && (s.vakalar || []).length ? `<p class="kucuk">Üzerinden geçilecek eski çağrılar:</p><ul class="vakalar">${s.vakalar.map(v => `<li><a href="#detay" data-cagri="${kac(v.cagri_id)}">#${kac(v.cagri_id)}</a> ${kac(v.belirti)}<div class="kucuk">${kac(v.cozen || "")} · ${kac(v.tarih)} · bu yol ${v.adet} çağrıda kullanıldı</div><ol class="adim">${v.adimlar.map(a => `<li>${kac(a)}</li>`).join("")}</ol></li>`).join("")}</ul>` : ""}
              <p class="kucuk"><b>Tamamlanınca:</b> ${kac(s.olcut || "")}</p></details></li>`).join("")}</ol></div></li>`).join("")}</ul>`
      : '<p class="kucuk">Bu bütçeyle yapılabilecek bir adım yok.</p>'}
    </div>
    </div>
    <details class="kart"><summary><b>Nasıl hesaplandı?</b> <span class="kucuk">(teknik ayrıntı)</span></summary>
      <p class="kucuk">Bütçeye sığan adımlar arasından riski en çok düşüren birleşim seçilir. Aynı soru iki yolla çözülür ve karşılaştırılır:</p>
      <ul class="liste">${[["Basit kural", "saat başına en iyi adımı sırayla seçer", k.kural], ["Optimizasyon", "tüm birleşimleri tarar (sırt çantası)", k.optimum]].map(([ad, ac, v]) => `<li><div class="govde"><b>${ad}</b> <span class="kucuk">· ${ac}</span>
        <div>Risk düşüşü <b>${sy(v.risk_dususu)}</b> · amaç puanı ${sy(v.amac_puani)} · ${v.saat} saat</div></div></li>`).join("")}</ul>
      <p class="kucuk">Amaç puanı, önce yeşil sınırının (35) üzerindeki riski düşürmeyi ödüllendirir; plan bu yüzden önce kırmızı konulara gider. Optimizasyon <b>amaç puanında</b> hiçbir zaman basit kuraldan kötü çıkmaz; fark bütçe dar olduğunda büyür. Toplam risk düşüşü kuralda daha yüksek görünebilir: kural zaten yeşil olan konuları da düşürür, bu da toplamı şişirir ama riski azaltmaz.</p></details>
    <p><button class="dugme" id="pkay">Bu planı kaydet</button> <span class="kucuk">Kaydedilen plan aşağıda takip edilir: kim öğrenmeye başladı, hangi kart yazıldı, risk hedefe indi mi?</span></p>
    <div class="kart"><h3>Plan sonrası harita</h3><ul class="liste">${p.harita_sonra.slice(0, 10).map(r => `<li>${puanKutu(r)}<div class="govde">${kac(r.ad)} <span class="kucuk">· ${kac(r.birim)}</span></div></li>`).join("")}</ul>
      <p class="kucuk">Varsayım: eğitilen kişi konuyu işi bilen diğer kişilerle eşit paylaşır. İlk 10 konu gösteriliyor.</p></div>`;
  }
  async function takipYukle() {
    const t = await api("plan/takip");
    $("#ptk").innerHTML = takipKart(t);
    if ($("#psim")) $("#psim").onclick = async () => { $("#psim").disabled = true; const r = await api("plan/simule", {}); bildir(`30 gün simüle edildi: ${r.uretilen_cagri} çağrı, ${r.yazilan_kart} kart.`); takipYukle(); };
  }
  $("#ana").onclick = async e => {
    const sa = e.target.closest("[data-sure-ac]");
    if (sa) { $("#psure").open = true; const tr = $("#sure-" + sa.dataset.sureAc); if (tr) { tr.scrollIntoView({behavior: "smooth", block: "center"}); tr.classList.add("yenilendi"); tr.querySelector("input").focus({preventScroll: true}); } return; }
    const gor = e.target.closest("[data-gor]");
    if (gor) {
      planGor = gor.dataset.gor;
      document.querySelectorAll("[data-gor]").forEach(b => { const on = b === gor; b.setAttribute("aria-pressed", on); b.classList.toggle("ikincil", !on); });
      document.querySelectorAll("[data-gorunum]").forEach(d => { d.hidden = d.dataset.gorunum !== gor.dataset.gor; });
      return;
    }
    const ot = e.target.closest("[data-hotele]"), hs = e.target.closest("[data-hsaat]"), ds = e.target.closest("[data-dsil]");
    if (ot) { planDeg.hafta_sinir[ot.dataset.hotele] = 0; return degistir(`${ot.dataset.hotele}. hafta ötelendi; oturumlar sonraki haftalara kaydı.`); }
    const uy = e.target.closest("[data-uygula]");
    if (uy) {
      const kutu = uy.closest("details"), h = +uy.dataset.uygula, t = sonTakvim;
      const kim = kutu.querySelector('[data-dk="kim"]').value, sure = kutu.querySelector('[data-dk="sure"]').value;
      let n = +sure;
      if (sure === "tarih") {
        const tr = kutu.querySelector('[data-dk="tarih"]').value;
        if (!tr) return bildir("Yeniden başlama tarihini seçin.");
        n = tarihHaftasi(t, tr) - h;
        if (n < 1) return bildir(`Tarih ${h}. haftadan sonra olmalı (en erken ${kisaTarih(haftaTarihi(t, h + 1))}).`);
        if (n > 52) return bildir("En fazla 52 hafta ötelenebilir.");
      }
      for (let w = h; w < h + n; w++) {
        if (kim) { if (!planDeg.kisi_yok.some(([k, hh]) => k === +kim && hh === w)) planDeg.kisi_yok.push([+kim, w]); }
        else planDeg.hafta_sinir[w] = 0;
      }
      const ad = kim ? kutu.querySelector('[data-dk="kim"]').selectedOptions[0].textContent.replace(" izinde / yok", "") : "Eğitim";
      return degistir(`${ad} ${n === 1 ? h + ". hafta" : h + "." + "–" + (h + n - 1) + ". haftalar"} dışarıda; ${kisaTarih(haftaTarihi(t, h + n))} haftası yeniden başlar.`);
    }
    if (hs) {
      const h = hs.dataset.hsaat, v = Math.max(0, Math.min(40, (planDeg.hafta_sinir[h] ?? +$("#tsin").value) + +hs.dataset.fark));
      if (v === +$("#tsin").value) delete planDeg.hafta_sinir[h]; else planDeg.hafta_sinir[h] = v;
      return degistir(`${h}. hafta kişi başı ${sy(v)} saat.`);
    }
    if (ds) {
      const [tur, a, b] = ds.dataset.dsil.split(":");
      if (tur === "hepsi") { planDeg.hafta_sinir = {}; planDeg.kisi_yok = []; }
      else if (tur === "h") delete planDeg.hafta_sinir[a];
      else if (tur === "hr") { for (let h = +a; h <= +b; h++) delete planDeg.hafta_sinir[h]; }
      else if (tur === "kr") { const [, k, h1, h2] = ds.dataset.dsil.split(":").map(Number); planDeg.kisi_yok = planDeg.kisi_yok.filter(([kk, h]) => !(kk === k && h >= h1 && h <= h2)); }
      else planDeg.kisi_yok = planDeg.kisi_yok.filter(([k, h]) => !(k === +a && h === +b));
      return degistir("Değişiklik geri alındı.");
    }
    if (e.target.id === "pkay") { await api("egitim-plani", {...planIstegi(), kaydet: true}); bildir("Plan kaydedildi."); takipYukle(); $("#ptk").scrollIntoView({behavior: "smooth"}); }
  };
  $("#ph").onclick = () => dugmeyleHesapla($("#ph"), hesapla,
    () => `Plan hesaplandı: ${$("#pb").value || 0} saat, ${$("#py").selectedOptions[0].textContent.toLowerCase()}.`, "#ps");
  // Elle değişiklik: yeniden hesapla, kaydırma yerini koru, kısa bildirim
  async function degistir(ileti) {
    const y = scrollY; await hesapla(); scrollTo(0, y); bildir(ileti);
  }
  $("#ana").onchange = e => {
    if (e.target.dataset.dk === "sure") { e.target.closest(".sira").querySelector("[data-dk-tarih]").hidden = e.target.value !== "tarih"; return; }
    const s = e.target.closest("select.kisi-yok");
    if (!s || !s.value) return;
    planDeg.kisi_yok.push([+s.value, +s.dataset.hafta]);
    degistir(`${s.selectedOptions[0].textContent} ${s.dataset.hafta}. hafta eğitimden çıkarıldı.`);
  };
  // Takvim ayarı değişince plan yeniden hesaplanır (aynı plan, yeni takvim)
  ["#tsin", "#tot", "#tgo", "#tcg", "#tbas"].forEach(id => { $(id).onchange = () => $("#ph").click(); });
  async function sureYukle() {
    const L = await api("konu-sureleri");
    const girilen = L.filter(k => k.sure_onay).length;
    $("#psozet").textContent = `· ${L.length} konudan ${girilen} tanesinin süresini girdin`;
    $("#pstablo").innerHTML = `<div class="tablo-sar"><table><thead><tr><th>Konu</th><th class="sayi">Kartı yazmak (saat)</th><th class="sayi">Öğretmek (saat)</th><th></th></tr></thead><tbody>
      ${L.map(k => `<tr id="sure-${k.kategori_id}"><td>${kac(k.ad)}<div class="kucuk">${kac(k.birim)}${k.acilis ? " · yeni konu" : ""}</div></td>
        <td class="sayi"><input type="number" min="0.5" max="200" step="0.5" value="${k.kart_saat_etkin}" data-sk="kart" aria-label="${kac(k.ad)} kart yazma saati"></td>
        <td class="sayi"><input type="number" min="0.5" max="200" step="0.5" value="${k.ogrenme_saati}" data-sk="ogr" aria-label="${kac(k.ad)} öğretme saati"></td>
        <td>${k.sure_onay ? rozet("yesil", "Senin girdiğin") : rozet("sari", "Tahmini")} <button class="dugme kucuk ikincil" data-sure-kaydet="${kac(k.kategori_id)}">Kaydet</button></td></tr>`).join("")}
      </tbody></table></div>`;
  }
  $("#psure").addEventListener("click", async e => {
    const b = e.target.closest("[data-sure-kaydet]"); if (!b) return;
    const tr = b.closest("tr"), kart = +tr.querySelector('[data-sk="kart"]').value, ogr = +tr.querySelector('[data-sk="ogr"]').value;
    try { await api("konu-sureleri/" + b.dataset.sureKaydet, {kart_saat: kart, ogrenme_saati: ogr}); }
    catch (err) { bildir(err.message); return; }
    await sureYukle(); bildir("Süre kaydedildi; plan yeniden hesaplanıyor."); await hesapla();
  });
  hesapla(); takipYukle(); sureYukle().then(() => { if (butce === "sureler") $("#psure").scrollIntoView({behavior: "smooth"}); });
};

/* ---------------------------------------------------------------- Değişimler */
const DURUM_R = {yetkin: ["yesil", "Biliyor"], ogreniyor: ["sari", "Öğreniyor"], baslamadi: ["gri", "Başlamadı"]};
function gecisKart(g) {
  const yk = g.yeni_konu;
  return `<div class="kart"><h3>${g.eski_ad ? kac(g.eski_ad) + ' <span class="ok">→</span> ' : ""}${kac(g.yeni_ad)}</h3>
    <p class="kucuk">${kac(g.birim)} · geçiş ${kac(g.tarih)} (${g.gun >= 0 ? g.gun + " gün önce" : -g.gun + " gün sonra"})${g.aciklama ? " · " + kac(g.aciklama) : ""}${g.anahtar.length ? " · anahtar kullanıcı: " + kac(g.anahtar.join(", ")) : ""}</p>
    ${g.puan != null ? `<p>${puanKutu(g)} ${yk ? (yk.erken_uyari ? rozet("kirmizi", "Erken uyarı: bilgi tek kişide") : rozet("mor", "Geçici puan (veri az)")) : rozet("gri", "İzleme dönemi bitti")}
      <span class="kucuk">${g.cagri} çağrı kapandı · ${g.acik_cagri} açık</span></p>` : ""}
    ${g.cozenler.length ? `<div class="kucuk"><b>Yeni sistemde kim çözüyor?</b></div><ul class="liste">${g.cozenler.map(c => `<li><div class="govde">${kac(c.ad)}<div class="cubuk" style="margin-top:.25rem"><i style="width:${Math.max(2, c.pay * 100)}%;${c.pay >= .6 ? "background:var(--kirmizi)" : ""}"></i></div></div><span class="kucuk">${c.adet} · ${yuzde(c.pay)}</span></li>`).join("")}</ul>` : '<p class="kucuk">Yeni sistemde henüz kapanan çağrı yok.</p>'}
    ${g.nedenler.length ? `<div class="kucuk" style="margin-top:.4rem">${kac(g.nedenler.join(" · "))}</div>` : ""}
    ${g.yapilacak.length ? `<div class="not"><b>Yapılacaklar</b><ul style="margin:.3rem 0 0 1rem;padding:0">${g.yapilacak.map(y => `<li>${kac(y)}</li>`).join("")}</ul></div>` : ""}
    <p><button class="dugme kucuk ikincil" data-sayfa="plan" data-veri="40">Geçişi içeren eğitim planı</button></p></div>`;
}
function alismaKart(a) {
  const k = a.kisi;
  return `<div class="kart"><h3>${kac(k.ad)} <span class="kucuk">· ${kac(k.birim)} · ${VARDIYA[k.vardiya]} vardiyası${k.ise_giris ? " · işe giriş " + kac(k.ise_giris) : ""}</span></h3>
    <div class="izgara"><div class="olcu"><b>${a.yetkin} / ${a.toplam_konu}</b><span>Bildiği konu</span></div><div class="olcu"><b>${a.toplam_cozum}</b><span>Çözdüğü çağrı</span></div>
      <div class="olcu"><b>${a.konular.filter(x => x.durum === "ogreniyor").length}</b><span>Öğrendiği konu</span></div></div>
    <ul class="liste">${a.konular.map(x => `<li>${rozet(...DURUM_R[x.durum])}<div class="govde"><b>${kac(x.ad)}</b> ${x.planli ? rozet("mavi", "Eğitim planında") : ""} ${x.beyan ? rozet("gri", "Kâğıtta biliyor") : ""}
      <div class="cubuk" style="margin:.3rem 0"><i style="width:${Math.min(100, x.cozum / x.esik * 100)}%"></i></div>
      <div class="kucuk">${x.cozum} çözüm${x.kalan ? ` · bilen sayılmasına ${x.kalan} çağrı kaldı` : ""}${x.ustalar.length ? " · usta: " + kac(x.ustalar.join(", ")) : " · bu konuyu bilen başka kimse yok"}${x.durum !== "yetkin" ? (x.cirak_uygun ? " · yanında öğrenerek çağrı alabilir" : x.kritiklik >= 3 ? " · kritik iş: yanında öğrenmeye uygun değil, eğitimle öğrenmeli" : "") : ""}</div></div></li>`).join("")}</ul></div>`;
}
CIZ.degisim = async () => {
  const d = await api("degisim");
  const kat = T.kategoriler, bugun = new Date().toISOString().slice(0, 10);
  const kisiSec = (id, coklu) => `<select id="${kac(id)}" ${coklu ? 'multiple size="5"' : ""}>${T.birimler.filter(b => T.kisiler.some(p => p.birim_id === b.id)).map(b => `<optgroup label="${kac(b.ad)}">${T.kisiler.filter(p => p.birim_id === b.id).map(p => `<option value="${kac(p.id)}">${kac(p.ad)}</option>`).join("")}</optgroup>`).join("")}</select>`;
  const kotu = d.receteler.filter(r => ["askida", "dususte"].includes(r.saglik.durum));
  $("#ana").innerHTML = `
  <h2>Değişimler</h2>
  <p class="alt">Yeni bir sisteme geçtiysen, ekibe biri katıldıysa ya da ayrıldıysa burada kaydet. Harita geçmişten beslendiği için bu değişimleri kendisi bilemez; kaydedince risk, plan ve çağrı yönlendirmesi buna göre düzelir.</p>

  <h3 style="margin:1rem 0 .5rem">1. Sistem geçişi</h3>
  <div class="kart"><p class="kucuk">Eski konu geçiş günü haritadan çıkar, yeni konu o gün başlar. İlk 60 gün (ya da 10 çağrıya kadar) yeni konunun puanı <b>geçicidir</b>: kâğıtta biliyor görünenler ve anahtar kullanıcılar bilen sayılır. Ama çağrıların %60’ından fazlasını tek kişi çözüyorsa <b>erken uyarı</b> verilir: bilgi daha ilk haftalarda bir kişide toplanıyordur. Eski sistemde bu işi yapanlar geçiş adayıdır; yeni sistemi öğrenme süreleri yarıya iner. Usta’nın modeli eski çağrılardan yeni konuyu tanımayı öğrenir.</p>
    ${d.simule.gecis || T.mod === "yerel" ? "" : `<p><span class="demo-etiket" title="Gösterim içindir; gerçek kullanımda bu düğme yok">Demo</span> <button class="dugme ikincil" id="gsim">Örnek: 40 gün önce rapor küpünden Power BI’a geçildi</button></p>`}</div>
  ${d.gecisler.map(gecisKart).join("")}
  <details class="kart"><summary><b>Yeni geçiş kaydet</b></summary>
    <div class="sira" style="margin-top:.5rem">
      <div style="flex:2 1 200px"><label for="geski">Kapanan eski konu</label><select id="geski"><option value="">Yok (yepyeni bir sistem)</option>${kat.map(k => `<option value="${kac(k.id)}">${kac(k.ad)} · ${kac(k.birim)}</option>`).join("")}</select></div>
      <div style="flex:2 1 200px"><label for="gyeni">Yeni konunun adı</label><input id="gyeni" maxlength="80" placeholder="Örn. Yeni WMS dalga hatası"></div>
      <div><label for="gtar">Geçiş günü</label><input id="gtar" type="date" value="${bugun}"></div>
      <div id="gbirimk" class="gizli"><label for="gbirim">Birim</label><select id="gbirim">${T.birimler.filter(b => T.usta_birimleri.includes(b.ad)).map(b => `<option value="${kac(b.id)}">${kac(b.ad)}</option>`).join("")}</select></div></div>
    <div class="sira" style="margin-top:.5rem"><div style="flex:2 1 200px"><label for="ganah">Anahtar kullanıcılar <span class="kucuk">(kurulumu yapan / eğitimi alan; birden fazla seçilebilir)</span></label>${kisiSec("ganah", true)}</div>
      <div style="flex:2 1 200px"><label for="gkel">Yeni sistemin anahtar kelimeleri <span class="kucuk">(virgülle)</span></label><input id="gkel" maxlength="300" placeholder="örn. yeni wms, dalga, görev"></div></div>
    <p style="margin-top:.6rem"><button class="dugme" id="gkay">Geçişi kaydet</button> <span class="kucuk">Açık çağrılar yeni konuya taşınır. Eski konuya bağlı otomasyonlar yeni sisteme uyarlanana kadar çalışmaz.</span></p></details>

  <h3 style="margin:1rem 0 .5rem">2. Yeni personel</h3>
  <div class="kart"><p class="kucuk">Yeni gelen kimse yedek sayılmaz; bir konuda son 90 günde 3 çağrı çözünce bilen sayılır. Ama Usta çağrıları geçmişte kimin çözdüğüne bakarak yönlendirdiği için yeni kişiye hiç çağrı gitmez. <b>Yanında öğrenme</b> bu döngüyü kırar: kritik ve acil olmayan çağrılar, aynı vardiyada konuyu bilen bir usta varken yeni kişiye ya da eğitim planında o konuyu öğrenene verilir; usta takılırsa destek olur.</p>
    <p style="display:flex;align-items:center;gap:.5rem;margin:.4rem 0 0"><input type="checkbox" id="cmod" ${d.cirak_modu ? "checked" : ""} style="width:auto;margin:0"><label for="cmod" style="margin:0">Yanında öğrenme açık</label></p>
    ${d.simule.personel || T.mod === "yerel" ? "" : `<p><span class="demo-etiket" title="Gösterim içindir; gerçek kullanımda bu düğme yok">Demo</span> <button class="dugme ikincil" id="psim2">Örnek: 35 gün önce Depo Sistemleri’ne giren Can Arslan</button></p>`}</div>
  ${d.yeni_personel.length ? d.yeni_personel.map(alismaKart).join("") : '<div class="kart kucuk">Son 90 günde işe giren kimse yok.</div>'}
  <details class="kart"><summary><b>Yeni personel ekle</b></summary>
    <div class="sira" style="margin-top:.5rem">
      <div style="flex:2 1 180px"><label for="yad">Adı soyadı</label><input id="yad" maxlength="60"></div>
      <div><label for="ybi">Birim</label><select id="ybi">${T.birimler.map(b => `<option value="${kac(b.id)}">${kac(b.ad)}</option>`).join("")}</select></div>
      <div><label for="yva">Vardiya</label><select id="yva"><option value="gunduz">Gündüz</option><option value="aksam">Akşam</option><option value="gece">Gece</option></select></div>
      <div><label for="ytar">İşe giriş</label><input id="ytar" type="date" value="${bugun}"></div></div>
    <p style="margin-top:.6rem"><button class="dugme" id="ykay">Ekle</button></p></details>

  <h3 style="margin:1rem 0 .5rem">3. Otomasyon sağlığı</h3>
  <div class="kart"><p class="kucuk">Otomatik çözümlerin son 30 gündeki gerçek başarısı. Risk hesabı, yeterli deneme varsa beklenen değil gerçek başarıyı kullanır. Başarı %40’ın altına inerse otomatik çözüm kendiliğinden askıya alınır.</p>
    <ul class="liste">${d.receteler.filter(r => r.saglik.durum !== "yetersiz_veri").map(r => `<li>${rozet(...SAGLIK_R[r.saglik.durum])}<div class="govde"><b>${kac(r.ad)}</b><div class="kucuk">${kac(r.saglik.metin)}</div>
      ${r.saglik.durum === "askida" ? `<button class="dugme kucuk ikincil" style="margin-top:.3rem" data-devreye="${kac(r.kod)}">Düzeltildi, yeniden devreye al</button>` : ""}</div></li>`).join("")}</ul>
    ${(() => { const az = d.receteler.filter(r => r.saglik.durum === "yetersiz_veri"); return az.length ? `<p class="kucuk">${az.length} otomatik çözümde son 30 günde ölçüm için yeterli deneme yok (en az 5 gerekir); bunlarda risk hesabı beklenen başarıyı kullanır: ${kac(az.map(r => r.ad).join(", "))}.</p>` : ""; })()}
    ${kotu.length || T.mod === "yerel" ? "" : `<p><button class="dugme ikincil" data-sayfa="otomasyon" data-veri="bozulma">Örnek: yazdırma sunucusu güncellendi, yazıcı otomasyonu bozuldu</button></p>`}</div>

  <h3 style="margin:1rem 0 .5rem">4. Ayrılan personel</h3>
  <div class="kart"><p class="kucuk">“Ya giderse?” bir tahmindir; bu kayıttır. Kişi pasif olur, risk haritası onsuz hesaplanır, açık çağrıları yeniden yönlendirilir, eğitim planındaki görevleri düşer. Önce devir dosyasını hazırlayın.</p>
    <div class="sira"><div style="flex:2 1 200px"><label for="aki">Ayrılan kişi</label>${kisiSec("aki", false)}</div>
      <div><label for="atar">Son gün</label><input id="atar" type="date" value="${bugun}"></div>
      <div style="flex:0 0 auto"><button class="dugme ikincil" id="adv">Devir dosyası</button> <button class="dugme" id="akay">Ayrıldı olarak kaydet</button></div></div>
    <div id="asonuc"></div>
    ${d.ayrilanlar.length ? `<ul class="liste" style="margin-top:.5rem">${d.ayrilanlar.map(a => `<li>${rozet("gri", "Ayrıldı")}<div class="govde">${kac(a.ad)} <span class="kucuk">· ${kac(a.birim)} · ${kac(a.cikis || "")}</span></div></li>`).join("")}</ul>` : ""}</div>`;
  $("#geski").onchange = () => $("#gbirimk").classList.toggle("gizli", !!$("#geski").value);
  const ana = $("#ana");
  ana.onclick = async e => {
    const b = e.target;
    if (b.id === "gsim") { b.disabled = true; const r = await api("gecis/simule", {}); bildir(`Geçiş kaydedildi: ${r.tasinan_cagri} çağrı yeni konuya taşındı.`); T = await api("tanimlar"); git("degisim"); return; }
    if (b.id === "psim2") { b.disabled = true; const r = await api("personel/simule", {}); bildir(`${r.kisi.ad} eklendi; yanında öğrenme ona ${r.cagri} çağrı vermiş.`); T = await api("tanimlar"); git("degisim"); return; }
    if (b.id === "gkay") {
      const anah = [...$("#ganah").selectedOptions].map(o => +o.value);
      const r = await api("gecis", {yeni_ad: $("#gyeni").value, tarih: $("#gtar").value, eski_kategori_id: +$("#geski").value || null,
        birim_id: +$("#gbirim").value || null, anahtar_kisiler: anah, anahtar_kelimeler: $("#gkel").value});
      bildir(`Geçiş kaydedildi${r.tasinan_cagri ? `; ${r.tasinan_cagri} çağrı taşındı` : ""}.`); T = await api("tanimlar"); git("degisim"); return;
    }
    if (b.id === "ykay") { await api("personel", {ad: $("#yad").value, birim_id: +$("#ybi").value, vardiya: $("#yva").value, ise_giris: $("#ytar").value}); bildir("Yeni personel eklendi."); T = await api("tanimlar"); git("degisim"); return; }
    if (b.id === "adv") { git("giderse", $("#aki").selectedOptions[0].textContent); return; }
    if (b.id === "akay") {
      if (b.dataset.onay !== "1") { b.dataset.onay = "1"; b.textContent = "Emin misiniz? Yeniden tıklayın"; return; }
      b.disabled = true;
      const r = await api(`personel/${$("#aki").value}/ayrildi`, {tarih: $("#atar").value});
      T = await api("tanimlar");
      $("#asonuc").innerHTML = `<div class="not">${kac(r.kisi.ad)} ayrıldı olarak kaydedildi. Yüksek riskli konu ${r.ozet_once.kirmizi} → <b>${r.ozet_sonra.kirmizi}</b>, ortalama puan ${sy(r.ozet_once.ortalama)} → <b>${sy(r.ozet_sonra.ortalama)}</b>.${r.yeniden_atanan.length ? ` ${r.yeniden_atanan.length} açık çağrısı yeniden yönlendirildi.` : ""}</div>`;
      b.textContent = "Kaydedildi"; return;
    }
    const dv = b.closest("[data-devreye]");
    if (dv) { dv.disabled = true; await api(`otomasyon/recete/${dv.dataset.devreye}/devreye-al`, {}); bildir("Otomatik çözüm yeniden devrede."); git("degisim"); }
  };
  $("#cmod").onchange = async e => { await api("cirak-modu", {acik: e.target.checked}); bildir(e.target.checked ? "Yanında öğrenme açıldı." : "Yanında öğrenme kapatıldı."); };
};

/* ---------------------------------------------------------------- Kendi verinle dene */
const EKIP = {kisiler: ["Ayşe", "Mehmet", "Zeynep", "Can", "Elif"], isler: ["Sevkiyat planı", "İade kabul", "Sayım", "Vardiya raporu", "Etiket basımı"], m: {}};
CIZ.ekibim = async () => {
  if (!Object.keys(EKIP.m).length) [[0, 0], [0, 3], [1, 0], [1, 1], [2, 2], [2, 4], [3, 4], [4, 1], [4, 4], [0, 4]].forEach(([p, i]) => EKIP.m[p + ":" + i] = true);
  $("#ana").innerHTML = `
    <h2>Kendi verinle dene</h2>
    <p class="alt">İki yol var: ekibini elle işaretle ya da elindeki çağrı/arıza dökümünü yükle. İkisinde de verin kaydedilmez; elle işaretleme tarayıcında, döküm analizi sunucuda geçici bellekte yapılır ve sonuç dönünce silinir.</p>
    <div id="ekipalan"></div>
    <div class="kart"><h3>Gerçek çağrılarınla Usta’yı denemek</h3>
      <p class="kucuk">Usta’nın öğrenmesi için çağrı metinleri gerekir; metinlerde kişi, cihaz ve bazen hesap bilgileri olur. Bu yüzden çağrı metni bu siteye yüklenmez. Uygulamayı kendi bilgisayarında ya da sunucunda kurup verini orada içe aktarırsın; veri makineden çıkmaz.</p>
      <ol class="adim"><li>Çağrı sisteminden bir CSV al. Gerekenler: <b>tarih, metin, konu, birim, çözen</b>. Varsa süre, çözüm notu, öncelik, kritiklik de alınır. Sütun adları esnek: “Açıklama”, “Kategori”, “Destek grubu”, “Çözen kişi”, “Çözüm” tanınır.</li>
        <li><code>python -m emanet.yerel cagrilar.csv --takma-ad</code> komutunu çalıştır. Kişi adları “Kişi 01”… olarak saklanır; eşleşme listesi yalnızca senin makinende kalır.</li>
        <li>Komut, modelin <b>senin verindeki</b> başarısını (eğitimde görülmemiş en yeni çağrılarda) ve risk haritasını bir rapora yazar.</li>
        <li><code>EMANET_DB=veri/yerel.db python -m emanet</code> ile aç; bu uygulamanın aynısı kendi verinle çalışır.</li></ol>
      <p class="kucuk"><a href="/api/dokum/usta-ornek.csv">Örnek çağrı dosyasını indir</a> (biçimi görmek için, kurgusal veri) · Kurulum ayrıntısı: README, “Kendi verinle”.</p></div>
    <div class="kart" id="dokumalan"><h3>Çağrı dökümünü yükle</h3>
      <p class="kucuk">Rapor düzeyinde bir döküm yeter (Excel’den CSV olarak kaydet). Zorunlu sütunlar: <b>tarih, birim, konu, cozen, sure_dk</b>. İsteğe bağlı: vardiya, kritiklik, ogrenme_saati, talimat_var. <a href="/api/dokum/ornek.csv">Örnek dökümü indir</a></p>
      <input type="file" id="df" accept=".csv,.txt,text/csv" aria-label="CSV dosyası seç">
      <label for="dt">ya da buraya yapıştır</label><textarea id="dt" style="min-height:4rem" placeholder="tarih;birim;konu;cozen;sure_dk&#10;2026-11-02 09:15;Bakım;Konveyör durması;Ali;35"></textarea>
      <p style="margin-top:.6rem"><button class="dugme" id="da">Analiz et</button> <button class="dugme ikincil" id="do">Örnek dökümle dene</button></p>
      <div id="ds"></div></div>`;
  const ciz = () => {
    const P = EKIP.kisiler, I = EKIP.isler, yapan = i => P.map((_, p) => p).filter(p => EKIP.m[p + ":" + i]);
    const sevi = n => n <= 1 ? "kirmizi" : n === 2 ? "sari" : "yesil";
    const tek = P.map((_, p) => I.filter((_, i) => { const y = yapan(i); return y.length === 1 && y[0] === p; }));
    const kimse = I.filter((_, i) => !yapan(i).length);
    const yuk = P.map((_, p) => I.filter((_, i) => EKIP.m[p + ":" + i]).length);
    const oneri = I.map((is, i) => ({is, i, y: yapan(i)})).filter(x => x.y.length <= 1).map(x => {
      const aday = P.map((_, p) => p).filter(p => !x.y.includes(p)).sort((a, b) => yuk[a] - yuk[b])[0];
      if (aday == null) return ""; yuk[aday]++;
      return `<li><div class="govde"><b>${kac(x.is)}</b>: ${x.y.length ? kac(P[x.y[0]]) + " → " : ""}<b>${kac(P[aday])}</b> öğrensin <span class="kucuk">(şu an en az iş bilen kişi)</span></div></li>`; }).join("");
    $("#ekipalan").innerHTML = `
    <div class="kart"><h3>Ekibini elle işaretle</h3><div class="iki">
      <div><label for="ek">Kişiler (virgülle ayır)</label><input id="ek" value="${kac(P.join(", "))}"></div>
      <div><label for="ei">İşler (virgülle ayır)</label><input id="ei" value="${kac(I.join(", "))}"></div></div>
      <div class="tablo-sar" style="margin-top:.8rem"><table class="mat"><thead><tr><th>İş</th>${P.map(p => `<th>${kac(p)}</th>`).join("")}<th>Durum</th></tr></thead><tbody>
      ${I.map((is, i) => { const n = yapan(i).length; return `<tr><td>${kac(is)}</td>${P.map((_, p) => `<td><input type="checkbox" aria-label="${kac(P[p])} ${kac(is)} yapabilir" data-h="${p}:${i}" ${EKIP.m[p + ":" + i] ? "checked" : ""}></td>`).join("")}<td>${rozet(sevi(n), n === 0 ? "Yapan yok" : n === 1 ? "Tek kişi" : n === 2 ? "Bir yedek" : n + " kişi")}</td></tr>`; }).join("")}</tbody></table></div>
      <div class="iki" style="margin-top:.8rem">
        <div><h3>Kim giderse ne durur?</h3><ul class="liste">${P.map((p, pi) => `<li>${rozet(tek[pi].length ? "kirmizi" : "yesil", tek[pi].length + " iş")}<div class="govde"><b>${kac(p)}</b><div class="kucuk">${tek[pi].length ? "Yalnızca o yapıyor: " + kac(tek[pi].join(", ")) : "Yaptığı her işin yedeği var"}</div></div></li>`).join("")}</ul>
          ${kimse.length ? `<p class="kucuk">Kimsenin yapamadığı işler: ${kac(kimse.join(", "))}</p>` : ""}</div>
        <div><h3>İlk adım önerisi</h3>${oneri ? `<ul class="liste">${oneri}</ul>` : '<p class="kucuk">Her işin en az bir yedeği var.</p>'}</div></div></div>`;
    const oku = (id, hedef) => $("#" + id).onchange = e => { const y = e.target.value.split(",").map(s => s.trim()).filter(Boolean).slice(0, 12); if (y.length) { EKIP[hedef] = y; ciz(); } };
    oku("ek", "kisiler"); oku("ei", "isler");
    $("#ekipalan").querySelectorAll("[data-h]").forEach(c => c.onchange = () => { EKIP.m[c.dataset.h] = c.checked; ciz(); });
  };
  ciz();
  async function analiz(csv) {
    const r = await api("dokum/analiz", {csv});
    const y = r.yukleme;
    $("#ds").innerHTML = `
      <div class="not">${y.satir.toLocaleString("tr-TR")} kayıt okundu${y.hatali ? `, ${y.hatali} satır atlandı` : ""} · ${y.yeni_konu} konu, ${y.yeni_kisi} kişi · analiz aralığı ${kac(r.pencere)}</div>
      ${y.hatalar.length ? `<p class="kucuk">${y.hatalar.map(kac).join("<br>")}</p>` : ""}
      <div class="izgara"><div class="olcu"><b style="color:var(--kirmizi)">${r.ozet.kirmizi}</b><span>Yüksek</span></div><div class="olcu"><b style="color:var(--sari)">${r.ozet.sari}</b><span>Orta</span></div><div class="olcu"><b style="color:var(--yesil)">${r.ozet.yesil}</b><span>Düşük</span></div></div>
      ${riskListe(r.konular.slice(0, 12), false)}`;
  }
  $("#df").onchange = async e => { const f = e.target.files[0]; if (!f) return; if (f.size > 2e6) { bildir("Dosya 2 MB’tan büyük."); return; } $("#dt").value = (await f.text()).slice(0, 2e6); };
  $("#da").onclick = () => { const v = $("#dt").value.trim(); if (v.length < 10) { bildir("Önce bir döküm seç ya da yapıştır."); return; } analiz(v); };
  $("#do").onclick = async () => { const t = await (await fetch("/api/dokum/ornek.csv")).text(); $("#dt").value = t.replace(/^﻿/, ""); analiz($("#dt").value); };
};

/* ---------------------------------------------------------------- Nasıl çalışır */
CIZ.nasil = async () => {
  $("#ana").innerHTML = `
  <h2>Nasıl çalışır</h2>
  <div class="kart"><h3>İki modül, iki kaynak</h3>
    <p><b>Usta</b> yalnızca sistemsel çağrılara bakar: BT Destek ve Depo Sistemleri (el terminali, yazıcı, WMS, ERP, rapor…). Her kapanan çağrı “ne yazıldı, kim çözdü, nasıl çözdü” kaydını bırakır ve model bunlardan öğrenir.</p>
    <p><b>Emanet</b> bu kayıtlarla, bakım sisteminden içe aktarılan teknik arıza dökümünü (sorter, konveyör, forklift, İSG…) birlikte okur. Hangi konunun kimin elinde kaldığını puanlar; o kişi giderse ne olacağını ve eğitim saatini nereye harcamak gerektiğini hesaplar.</p></div>
  <div class="iki">
    <div class="kart"><h3>Usta’nın öğrenmesi</h3>
      <ol class="adim"><li>Konu modeli metinden konuyu tahmin eder; emin değilse sorar.</li>
      <li>Kişi modeli metin, konu ve vardiyadan “bunu kim çözer” olasılığını verir. İzindekiler ve vardiyada olmayanlar elenir.</li>
      <li>En benzer geçmiş çağrıların çözüm notları gruplanıp yol olarak gösterilir.</li>
      <li>Çağrı kapanınca model yeniden eğitilir.</li></ol>
      <p><button class="dugme kucuk ikincil" data-sayfa="ogrenme">Test sonuçları</button></p></div>
    <div class="kart"><h3>Emanet’in hesabı</h3>
      <ol class="adim"><li>Son 90 günde her konuyu kim kaç kez çözmüş?</li><li>Yoğunlaşma, yedek sayısı, yazılı çözüm, otomasyon payı ve kritiklikten risk puanı.</li><li>Bir kişi çıkarılınca harita yeniden hesaplanır; ayrılırken devir dosyası çıkar.</li><li>İzin onaylanmadan önce o tarihlerde yedeksiz kalan konular gösterilir.</li><li>Eğitim planı sırt çantası problemi olarak çözülür; pratiği kalmamış yedekler daha ucuza tazelenir.</li><li>Kaydedilen plan takip edilir: öğrenen çağrı çözmeye başladı mı, risk hedefe indi mi? Seyir grafiği kararların etkisini gösterir.</li><li>Değişimler: sistem geçişinde yeni konunun puanı ilk haftalarda geçicidir, bilgi tek kişide toplanırsa erken uyarı verilir; yeni personele yanında öğrenme kolay çağrılar verir; başarısı düşen otomasyon kendiliğinden askıya alınır.</li></ol></div>
  </div>
  <div class="kart"><h3>Otomasyon</h3>
    <p>Bazı çağrılar belirli yetkiler dahilinde insansız çözülür: kurulum ve yetki talepleri (eksik bilgi Teams’ten sorulur, gerekiyorsa yönetici onaylar), kilit açma, bilinen onarım adımları (yazıcı, rapor işi, terminal ağı), toplu arıza birleştirme, kapanış teyidi ve İK kaydıyla işe giriş/çıkış. Karar her zaman yazılı kurallardadır; makine öğrenmesi yalnızca konuyu tanır. Sık tekrar eden çözüm notları “otomatik çözüm adayı” olarak önerilir.</p>
    <p><button class="dugme kucuk ikincil" data-sayfa="otomasyon">Otomasyon ekranı</button></p></div>
  <div class="kart"><h3>Claude ile konuşma (MCP)</h3>
    <p>Aynı çekirdek bir MCP sunucusu olarak da açıktır: <code>${kac(location.origin)}/mcp</code>. Araçların bir kısmı veri değiştirdiği için erişim anahtar ister (Claude'da bağlayıcı adresi <code>…/mcp</code>, anahtar <code>Authorization: Bearer</code> başlığında); anahtar sunucuda <code>EMANET_MCP_ANAHTARLARI</code> ile tanımlanır. Demo sitesinde herkese açık değildir.</p>
    <p class="kucuk">Örnek sorular: “Sipariş dalgası açılmıyor; bu daha önce nasıl çözüldü?” · “Bu hafta izinde olanlar yüzünden hangi konular tek kişiye kaldı?” · “40 saatlik eğitimle riski en çok nerede düşürürüm?”</p></div>
  ${T.mod === "yerel" ? `<div class="kart"><h3>Veri</h3><p>Bu kurulum kendi çağrı dökümünle yapıldı (python -m emanet.yerel). Veri bu makinede durur; yenilemek için içe aktarmayı yeniden çalıştır.</p></div>` : `<div class="kart"><h3>Veri</h3>
    <p>Yıldız Ev &amp; Yaşam kurgusal bir şirkettir. 28 kişi, 5 birim, 14 sistemsel ve 14 teknik konu; yaklaşık 900 Usta çağrısı ve 650 kayıtlık bir bakım dökümü üretilir. İçine bilerek birkaç bağımlılık örüntüsü gömülmüştür. Veri her gece ve aşağıdaki düğmeyle başlangıç hâline döner.</p>
    <p>Demoyu deneyen her ziyaretçinin kendi alanı vardır: açtığın çağrılar, kaydettiğin planlar yalnız sana görünür. Alan 24 saat ya da gece sıfırlamasına kadar durur.</p>
    <p><button class="dugme ikincil" id="sf">Kendi demo alanımı sıfırla</button></p></div>`}`;
  if ($("#sf")) $("#sf").onclick = async () => { await api("sifirla", {}); T = await api("tanimlar"); bildir("Kendi demo alanın başlangıç hâline döndü."); };
};

(async () => {
  T = await api("tanimlar");
  if (T.mod === "yerel") $(".demo").textContent = "Yerel veri · bu makinede";
  const s = location.hash.slice(1);
  git(CIZ[s] && s !== "detay" ? s : "genel");
})();
