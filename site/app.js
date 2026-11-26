/* Site de soutenance Novaria Core (SIT-02) : comportement. Le texte est dans contenu.js, la mise en page dans style.css.
 * Un défilement vertical pilote le film : chaque scène reçoit sa progression (--p, de 0 à 1) et révèle ses éléments au bon moment.
 * Touches : flèches gauche et droite (scène précédente, suivante), J (questions du jury), P (mode orateur), T (thème), Échap (fermer). */
(function () {
  "use strict";
  var C = window.CONTENU;
  var LEX = window.LEXIQUE || { themes: [], entrees: [] };  /* lexique : sigles, mots techniques, vocabulaire (lexique.js) */
  var DOCS = window.DOCS || {};  /* documents du dépôt convertis par scripts/dev/site_docs.py ; absent : le site marche sans lecteur */
  var $ = function (s, r) { return (r || document).querySelector(s); };
  var $$ = function (s, r) { return [].slice.call((r || document).querySelectorAll(s)); };
  var esc = function (t) { return String(t).replace(/[&<>"]/g, function (c) { return { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]; }); };
  var mmss = function (n) { n = Math.max(0, Math.round(n)); var m = Math.floor(n / 60), s = n % 60; return (m < 10 ? "0" : "") + m + ":" + (s < 10 ? "0" : "") + s; };
  var mobile = function () { return window.innerWidth <= 900; };
  var scene = function (id) { return C.scenes.filter(function (s) { return s.id === id; })[0]; };
  var startOf = function (i) { var a = 0; for (var k = 0; k < i; k++) a += C.scenes[k].secs; return a; };
  var cheminDe = function (ref) { return ref.split("#")[0]; };
  var existe = function (ref) { return !!DOCS[cheminDe(ref)]; };
  var chips = function (refs, grp) {
    return refs.filter(existe).map(function (r) { var p = cheminDe(r); return '<button type="button" class="chip" data-grp="' + grp + '" data-ref="' + esc(r) + '" title="' + esc(p) + '">' + esc(DOCS[p].titre) + "</button>"; }).join("");
  };
  var TOTAL = C.scenes.reduce(function (a, s) { return a + s.secs; }, 0);

  /* ---------- thème : système, sombre ou clair ---------- */
  var THEMES = ["auto", "dark", "light"], LABELS = { auto: "Thème : système", dark: "Thème : sombre", light: "Thème : clair" };
  var theme = "auto";
  try { var saved = localStorage.getItem("novaria-theme"); if (THEMES.indexOf(saved) >= 0) theme = saved; } catch (e) { /* stockage indisponible : on garde « auto » */ }
  function applyTheme() {
    if (theme === "auto") document.documentElement.removeAttribute("data-theme"); else document.documentElement.setAttribute("data-theme", theme);
    var b = $("#btnTheme"); if (b) b.textContent = LABELS[theme];
    try { localStorage.setItem("novaria-theme", theme); } catch (e) { /* sans importance */ }
  }

  /* ---------- décor : la ville et la rue (couleurs par jetons, donc dans les deux thèmes) ---------- */
  var CITY = '<svg class="city" viewBox="0 0 1200 850" preserveAspectRatio="xMidYMax slice" aria-hidden="true"><defs><linearGradient id="sk0" x2="0" y2="1"><stop style="stop-color:var(--c-sky1)"/><stop offset="1" style="stop-color:var(--c-sky2)"/></linearGradient><linearGradient id="rd0" x2="0" y2="1"><stop style="stop-color:var(--c-road1)"/><stop offset="1" style="stop-color:var(--c-road2)"/></linearGradient></defs>' +
    '<rect width="1200" height="850" fill="url(#sk0)"/><g style="fill:var(--c-bld);stroke:var(--c-bld-line)" stroke-opacity=".4"><path d="M0 430V250h100v-70h120v250z"/><path d="M190 430V160h90v-50h120v320z"/><path d="M390 430V240h100v-90h130v280z"/><path d="M640 430V190h110v-75h100v315z"/><path d="M840 430V260h100v-80h125v250z"/><path d="M1060 430V210h140v220z"/></g>' +
    '<g style="fill:var(--c-win)" opacity=".3"><path d="M35 285h16v28H35zm45 0h16v28H80zm140-70h18v24h-18zm47-55h18v24h-18zm52 0h18v24h-18zm102 125h18v25h-18zm60-60h18v25h-18zm140 25h18v25h-18zm150-105h18v25h-18zm55 0h18v25h-18zm150 110h18v25h-18zm62-55h18v25h-18zm90 0h18v25h-18z"/></g>' +
    '<path d="M0 470L1200 420V850H0Z" fill="url(#rd0)"/><path d="M450 850L580 450h90l250 400Z" style="fill:var(--c-road2)" stroke="#50717e" stroke-opacity=".5"/><path d="M600 850L625 465h12l15 385" stroke="#d4caa0" stroke-opacity=".5" stroke-width="5" stroke-dasharray="38 42" fill="none"/>' +
    '<g transform="translate(740 615)"><path d="M0 45l25-35h115l38 35 12 42H-10z" style="fill:var(--c-car)"/><path d="M38 17h87l24 28H18z" fill="#142e3b"/><circle cx="30" cy="86" r="15" fill="#081017" stroke="#8eb7c0" stroke-width="5"/><circle cx="153" cy="86" r="15" fill="#081017" stroke="#8eb7c0" stroke-width="5"/></g></svg>';
  var STREET = '<svg class="street" viewBox="0 0 1100 850" preserveAspectRatio="xMidYMax slice" aria-hidden="true"><defs><linearGradient id="sk2" x2="0" y2="1"><stop style="stop-color:var(--c-sky1)"/><stop offset="1" style="stop-color:var(--c-sky2)"/></linearGradient><linearGradient id="st2" x2="0" y2="1"><stop style="stop-color:var(--c-road1)"/><stop offset="1" style="stop-color:var(--c-road2)"/></linearGradient></defs>' +
    '<rect width="1100" height="850" fill="url(#sk2)"/><g style="fill:var(--c-bld)"><path d="M0 470V210h180v260z"/><path d="M170 470V110h160v360z"/><path d="M320 470V245h170v225z"/><path d="M480 470V160h170v310z"/><path d="M640 470V225h160v245z"/><path d="M790 470V130h180v340z"/><path d="M950 470V230h150v240z"/></g>' +
    '<path d="M0 490L1100 440V850H0z" fill="url(#st2)"/><path d="M430 850L550 470h60l260 380" style="fill:var(--c-road2)" stroke="#4e6e7a" stroke-opacity=".6"/><path d="M555 850l28-370h10l38 370" stroke="#d8cda5" stroke-opacity=".5" stroke-width="4" stroke-dasharray="35 34" fill="none"/>' +
    '<g transform="translate(560 480)"><path d="M0 0V-280" stroke="#a9c3c8" stroke-width="8"/><rect x="-38" y="-305" width="78" height="35" rx="7" fill="#132c37" stroke="#6df0d2" stroke-width="3"/><circle cx="0" cy="-288" r="5" fill="#6df0d2"/></g></svg>';

  /* ---------- une fabrique par scène ---------- */
  var li = function (arr) { return arr.map(function (x) { return "<li>" + esc(x) + "</li>"; }).join(""); };
  var at = function (v, extra) { return ' class="at' + (extra ? " " + extra : "") + '" data-at="' + v + '"'; };
  var B = {};

  B.prologue = function (s) {
    var m = C.titre.match(/^(.*? the) (.*)$/) || [0, C.titre, ""];
    return '<div class="stage bg-a">' + CITY + '<div class="shade"></div><div class="one"><div>' +
      '<div class="eyebrow at" data-at="0">' + esc(s.kicker) + "</div>" +
      '<h1 class="at" data-at="0">' + esc(m[1]) + '<br><span style="color:var(--accent)">' + esc(m[2]) + '.</span></h1>' +
      '<p class="lead at" data-at="0">' + esc(s.chapeau) + "</p>" +
      '<div class="facts at" data-at="0" style="transition-delay:.3s">' + s.faits.map(function (f) { return '<div class="fact"><b>' + esc(f.t) + "</b>" + esc(f.d) + "</div>"; }).join("") + "</div>" +
      '</div></div><div class="cue">Faites défiler ↓</div></div>';
  };

  B.citoyen = function (s) {
    return '<div class="stage bg-b"><div class="grid2"><div>' +
      '<div class="eyebrow at" data-at="0">' + esc(s.kicker) + "</div>" +
      '<h2 class="at" data-at="0">' + esc(s.titre) + "</h2>" +
      '<p class="lead at" data-at="0.08">' + esc(s.chapeau) + "</p>" +
      '<p class="at" data-at="0.16" style="margin-top:18px"><span class="tag sim">' + esc(s.etiquette) + "</span></p></div>" +
      '<div class="phone-stage at" data-at="0"><div class="phone"><img alt="' + esc(s.image.alt) + '" src="' + esc(s.image.src) + '"></div></div></div>' +
      '<div class="ask"><div class="at" data-at="0.62">' + esc(s.question).replace("ces informations ?", "<span>ces informations ?</span>") + "</div></div></div>";
  };

  B.capteur = function (s) {
    var m = s.mesure, p = s.photo;
    return '<div class="stage bg-d">' + STREET + '<div class="scan"></div><div class="grid2"><div>' +
      '<div class="eyebrow at" data-at="0.04">' + esc(s.kicker) + "</div>" +
      '<h2 class="at" data-at="0.08">' + esc(s.titre) + "</h2>" +
      '<p class="lead at" data-at="0.12">' + esc(s.chapeau) + "</p>" +
      '<figure class="sensor at" data-at="0.24"><img alt="' + esc(p.alt) + '" src="' + esc(p.src) + '"><ol>' + li(s.etapes) + "</ol>" +
      "<figcaption><b>" + esc(s.nomCapteur) + "</b> " + esc(p.legende) + " " + esc(p.credit) + ' <a href="' + esc(p.lien) + '" target="_blank" rel="noopener">Page de l\'image</a></figcaption></figure></div>' +
      '<div class="rcol"><div class="readout at" data-at="0.36"><div class="rt"><span>' + esc(m.titre) + '</span><span style="color:var(--accent)">' + esc(m.etat) + "</span></div>" +
      m.lignes.map(function (l) { return esc(l[0]) + " <strong>" + esc(l[1]) + "</strong><br>"; }).join("") + '<span style="color:var(--faint)">' + esc(m.pied) + "</span></div>" +
      '<div class="at" data-at="0.36"><span class="tag real">' + esc(s.etiquette) + '</span><p class="note" style="margin:8px 0 0">' + esc(s.noteVille) + "</p></div>" +
      '<div class="carr at" data-at="0.6" id="carr"></div></div></div></div>';
  };

  B.parcours = function (s) {
    return '<div class="stage bg-c"><div class="flow" id="flow3"><div class="head"><div class="eyebrow at" data-at="0">' + esc(s.kicker) + "</div>" +
      '<h2 class="at" data-at="0">' + esc(s.titre) + "</h2>" +
      '<p class="lead at" data-at="0.04">' + esc(s.chapeau) + "</p>" +
      '<div class="aitoggle at" data-at="0.04"><button type="button" class="aibtn" id="aiBtn" aria-pressed="false">' + esc(s.ia.bouton) + "</button></div></div>" +
      '<div class="rail-flow" id="rf"><div class="fill"></div><div class="packet"></div></div>' +
      '<div class="fdetail" id="fd" aria-live="polite"></div>' +
      '<div class="aiband" id="aiband" hidden>' + s.ia.puces.map(function (c) {
        return '<div class="chip ' + c.c + '"><b>' + esc(c.t) + "</b>" + esc(c.d) + (c.t2 ? '<br><b class="b2">' + esc(c.t2) + "</b>" + esc(c.d2) : "") + "</div>";
      }).join("") + "</div>" +
      '<div class="aicard" id="aicard" hidden>' + s.ia.carte.map(function (c) { return "<div><h3>" + esc(c.t) + "</h3><p>" + esc(c.d) + "</p></div>"; }).join("") + "</div></div></div>";
  };

  B.intelligence = function (s) {
    return '<div class="stage bg-d"><div class="flow" style="width:min(1100px,100%)"><div class="eyebrow">' + esc(s.kicker) + '</div><div class="tabs" id="tabs" role="tablist" aria-label="Étapes de l\'intelligence"></div><div id="panes"></div></div></div>';
  };

  B.reponse = function (s) {
    var a = s.alerte;
    return '<div class="stage bg-e"><div class="grid2"><div><div class="eyebrow at" data-at="0">' + esc(s.kicker) + "</div>" +
      '<h2 class="at" data-at="0">' + esc(s.titre) + '</h2><div class="chain">' +
      s.etapes.map(function (e, i) { return '<div class="step at" data-at="' + (0.15 + i * 0.2) + '"><i>' + (i + 1) + "</i><div><b>" + esc(e[0]) + "</b><span>" + esc(e[1]) + "</span></div></div>"; }).join("") +
      '</div></div><div class="at" data-at="0.78" style="justify-self:center"><div class="alertcard"><div class="ic">!</div><div class="k">' + esc(a.kicker) + "</div><h3>" + esc(a.titre) + "</h3>" +
      "<p>" + esc(a.delai) + '<b style="color:var(--ink)">' + esc(a.valeur) + "</b>" + esc(a.fin) + '</p><span class="tag sim">' + esc(a.etiquette) + "</span></div></div></div></div>";
  };

  B.retour = function (s) {
    return '<div class="stage bg-b"><div class="grid2"><div><div class="eyebrow at" data-at="0">' + esc(s.kicker) + "</div>" +
      '<h2 class="at" data-at="0">' + esc(s.titre) + "</h2>" +
      '<p class="lead at" data-at="0.1">' + esc(s.chapeau) + "</p>" +
      '<div class="finish at" data-at="0.45">' + esc(C.signature[0]) + "<br>" + esc(C.signature[1]) + "<br><span>" + esc(C.signature[2]) + "</span></div></div>" +
      '<div class="phone-stage at" data-at="0.05"><div class="phone"><img alt="' + esc(s.image.alt) + '" src="' + esc(s.image.src) + '"></div></div></div></div>';
  };

  function lireBloc(refs, grp) {
    var n = refs.filter(existe).length;
    if (!n) return "";
    return '<div class="lire"><h4>Lire dans le site</h4><div class="chips">' + chips(refs, grp) + "</div>" +
      (n > 1 ? '<button type="button" class="tout" data-grp="' + grp + '">Tout lire · ' + n + " documents</button>" : "") + "</div>";
  }

  function drawer(s) {
    return '<div class="drawer"><details><summary>Preuves et limites</summary><div class="dg"><div><h4>Preuves</h4><ul>' +
      s.preuves.map(function (x) { return "<li><code>" + esc(x) + "</code></li>"; }).join("") + "</ul></div><div><h4>À reconnaître</h4><ul>" +
      (s.limites.length ? li(s.limites) : "<li>Rien à ajouter.</li>") + "</ul></div></div>" + lireBloc(s.docs || [], "s:" + C.scenes.indexOf(s)) + "</details></div>";
  }

  /* ---------- construction de la page ---------- */
  var film = $("#film");
  film.innerHTML = C.scenes.map(function (s, i) {
    return '<section class="scene s-' + s.id + '" id="sc-' + s.id + '" data-i="' + i + '" style="--len:' + s.longueur + '" aria-label="' + esc(s.nav) + '">' + B[s.id](s) + "</section>" + drawer(s);
  }).join("");
  var scenesEl = $$(".scene");

  var rail = $("#rail");
  C.scenes.forEach(function (s, i) {
    var b = document.createElement("button");
    b.type = "button"; b.setAttribute("aria-label", (i ? "Scène " + i + " : " : "") + s.nav);
    b.onclick = function () { scenesEl[i].scrollIntoView(); };
    rail.appendChild(b);
  });

  /* démonstration */
  var D = C.demo, mat = C.matrice;
  var shot = 0;
  function renderDemo() {
    var c = D.captures[shot];
    $("#demoBody").innerHTML = '<div class="shot"><div class="frame"><img alt="' + esc(c.alt) + '" src="' + esc(c.src) + '"></div><div><h3>' + esc(c.nom) + "</h3><p>" + esc(c.legende) + '</p><p class="note">Données simulées.</p></div></div>';
    $$("#demoTabs button").forEach(function (b, i) { b.setAttribute("aria-pressed", i === shot); });
  }
  $("#demo").innerHTML = '<div class="in"><div class="eyebrow">Démonstration</div><h2>' + esc(D.titre) + "</h2><p class=\"lead\">" + esc(D.chapeau) + '</p><div class="demo-tabs" id="demoTabs" role="group" aria-label="Captures">' +
    D.captures.map(function (c, i) { return '<button type="button" data-i="' + i + '">' + esc(c.nom) + "</button>"; }).join("") + '</div><div id="demoBody"></div>' +
    "<h3 style=\"margin-top:34px\">" + esc(D.pile.titre) + '</h3><div class="scroll-x"><table class="cmd"><thead><tr><th>Étape</th><th>Linux (bash)</th><th>Windows (PowerShell)</th></tr></thead><tbody>' +
    D.pile.lignes.map(function (l) { return "<tr><td>" + esc(l[0]) + "</td><td><code>" + esc(l[1]) + "</code></td><td><code>" + esc(l[2]) + "</code></td></tr>"; }).join("") + "</tbody></table></div></div>";
  $$("#demoTabs button").forEach(function (b) { b.onclick = function () { shot = +b.dataset.i; renderDemo(); }; });
  renderDemo();

  /* matrice BC05 */
  $("#matrice").innerHTML = '<div class="in"><div class="eyebrow">BC05</div><h2>' + esc(mat.titre) + '</h2><p class="lead">' + esc(mat.chapeau) + '</p><div class="scroll-x"><table class="table"><thead><tr>' +
    mat.entete.map(function (h) { return "<th>" + esc(h) + "</th>"; }).join("") + "</tr></thead><tbody>" +
    mat.lignes.map(function (r) { return "<tr><td>" + esc(r[0]) + '</td><td class="' + (r[1] === "Implémenté" ? "yes" : "nope") + '">' + esc(r[1]) + "</td><td>" + esc(r[2]) + ((r[4] || []).filter(existe).length ? ' <button type="button" class="chip mini" data-grp="m:' + mat.lignes.indexOf(r) + '">Lire · ' + r[4].filter(existe).length + "</button>" : "") + "</td><td><code>" + esc(r[3]) + "</code></td></tr>"; }).join("") +
    '</tbody></table></div><p class="note">' + esc(mat.pied) + "</p></div>";

  $("#foot").innerHTML = '<div class="in"><div><b>' + esc(C.marque) + "</b> · " + esc(C.titre) + "</div><div>" + esc(C.simule) + "</div><div>" + esc(scene("capteur").photo.credit) +
    ' <a href="' + esc(scene("capteur").photo.lien) + '" target="_blank" rel="noopener">Wikimedia Commons</a></div><div>Site statique local : aucune ressource externe n\'est chargée, aucun service tiers.</div></div>';
  $("#chipsim").textContent = C.simule;

  /* ---------- scène 2 : carrefour ou pas ? ---------- */
  var cas = "mt";
  function renderCarr() {
    var k = scene("capteur").carrefour, box = $("#carr"), c = k.cas[cas];
    box.innerHTML = "<h3>" + esc(k.titre) + '</h3><div class="seg" role="group" aria-label="Type de réseau">' +
      Object.keys(k.cas).map(function (id) { return '<button type="button" data-c="' + id + '" aria-pressed="' + (id === cas) + '">' + esc(k.cas[id].nom) + "</button>"; }).join("") + "</div>" +
      '<div class="chainx">' + c.chaine.map(function (x, i) { return (i ? "<i>→</i>" : "") + '<span class="b ' + x[1] + '">' + esc(x[0]) + "</span>"; }).join("") + "</div><p>" + esc(c.texte) + "</p>";
    $$("button", box).forEach(function (b) { b.onclick = function () { cas = b.dataset.c; renderCarr(); }; });
  }
  renderCarr();

  /* ---------- scène 3 : le parcours, et où l'IA intervient ---------- */
  var S3 = scene("parcours"), rf = $("#rf"), sel = 0, auto = -1;
  S3.composants.forEach(function (c, i) {
    var b = document.createElement("button");
    b.type = "button"; b.className = "fnode";
    b.innerHTML = "<small>" + esc(c.n) + "</small><b>" + esc(c.k) + "</b><span>" + esc(c.s) + "</span>";
    b.onclick = function () { sel = i; flowDetail(); };
    rf.appendChild(b);
  });
  function flowDetail() {
    var c = S3.composants[sel];
    $$(".fnode", rf).forEach(function (n, i) { n.classList.toggle("sel", i === sel); });
    $("#fd").innerHTML = "<div><h3>" + esc(c.k) + "</h3><p>" + esc(c.p) + '</p></div><div><div class="lab">PREUVES</div><ul>' + li(c.l) + "</ul></div>";
  }
  flowDetail();
  var AI = false, aiManual = false;
  function setAI(v) {
    AI = v;
    $("#aiBtn").setAttribute("aria-pressed", v); $("#aiband").hidden = !v; $("#aicard").hidden = !v; $("#fd").hidden = v; $("#flow3").classList.toggle("ai", v);
  }
  $("#aiBtn").onclick = function () { aiManual = true; setAI(!AI); };
  function flowHook(p) {
    if (!aiManual && !mobile() && AI !== (p >= 0.88)) setAI(p >= 0.88);
    var a = -1;
    $$(".fnode", rf).forEach(function (n, i) { var on = p >= 0.08 + i * 0.17; n.classList.toggle("on", on); if (on) a = i; });
    if (a !== auto) { auto = a; if (a >= 0) { sel = a; flowDetail(); } }
  }

  /* ---------- scène 4 : l'intelligence ---------- */
  var S4 = scene("intelligence"), tabs = $("#tabs"), panes = $("#panes"), step = 0, HZ = 15, ratio = 0.5;
  S4.onglets.forEach(function (t, i) {
    var b = document.createElement("button");
    b.type = "button"; b.setAttribute("role", "tab"); b.textContent = (i + 1) + " · " + t;
    b.onclick = function () {
      if (mobile()) { step = i; showStep(); return; }
      var el = $("#sc-intelligence"), top = el.getBoundingClientRect().top + window.scrollY, span = el.offsetHeight - window.innerHeight;
      window.scrollTo({ top: top + (i + 0.5) / S4.onglets.length * span, behavior: "smooth" });
    };
    tabs.appendChild(b);
  });
  function nombre(v) { return v.toFixed(3).replace(".", ","); }
  function renderPanes() {
    var e = S4.etl, w = S4.entrepot, r = S4.regle, k = S4.classifieur, pv = S4.prevision, h = pv.horizons[HZ];
    panes.innerHTML =
      '<div class="pane" data-k="0"><div class="card"><h3>' + esc(e.t) + '</h3><p style="color:var(--muted)">' + esc(e.d) + '</p><div class="mini3">' + e.cases.map(function (c) { return "<div><b>" + esc(c[0]) + "</b>" + esc(c[1]) + "</div>"; }).join("") + '</div><p class="note" style="margin:0">' + esc(e.note) + "</p></div></div>" +
      '<div class="pane" data-k="1"><div class="card"><h3>' + esc(w.t) + '</h3><p style="color:var(--muted)">' + esc(w.d) + '</p><table class="table"><thead><tr>' + w.entete.map(function (x) { return "<th>" + esc(x) + "</th>"; }).join("") + "</tr></thead><tbody>" +
      w.lignes.map(function (l) { return "<tr><td><code>" + esc(l[0]) + "</code></td><td>" + esc(l[1]) + "</td></tr>"; }).join("") + "</tbody></table></div></div>" +
      '<div class="pane" data-k="2"><div class="card"><h3>' + esc(r.t) + '</h3><p style="color:var(--muted)">' + esc(r.d) + '</p><label for="rt" style="font:13px var(--mono);color:var(--muted)">' + esc(r.curseur) + ' : <b id="rtv" style="color:var(--ink)">' + ratio.toFixed(2) + '</b></label><input id="rt" class="slider" type="range" min="0" max="1" step="0.01" value="' + ratio + '" aria-describedby="rts"><div id="rts" style="margin-top:10px"></div><p class="note" style="margin:12px 0 0">' + esc(r.note) + "</p></div></div>" +
      '<div class="pane" data-k="3"><div class="card"><h3>' + esc(k.t) + '</h3><p style="color:var(--muted);margin-bottom:8px">' + esc(k.d) + '</p><table class="table"><thead><tr>' + k.entete.map(function (x) { return "<th>" + esc(x) + "</th>"; }).join("") + "</tr></thead><tbody>" +
      k.conditions.map(function (c) { return "<tr><td>" + esc(c[0]) + "</td><td>" + esc(c[1]) + "</td><td>" + esc(c[2]) + '</td><td class="' + (c[3] ? "yes" : "nope") + '">' + (c[3] ? "oui" : "non") + "</td></tr>"; }).join("") +
      '</tbody></table><div class="verdict"><b>' + esc(k.verdict) + "</b><span>" + esc(k.verdictTexte) + "</span></div></div></div>" +
      '<div class="pane" data-k="4"><div class="card"><h3>' + esc(pv.t) + '</h3><p style="color:var(--muted);margin-bottom:6px">' + esc(pv.d) + '</p><div class="hz" role="group" aria-label="Horizon de prévision">' +
      Object.keys(pv.horizons).map(function (x) { return '<button type="button" data-h="' + x + '" aria-pressed="' + (+x === HZ) + '">' + x + " min</button>"; }).join("") + "</div>" +
      '<div class="bars">' + h.mae.map(function (v, i) { var col = ["#6b8591", "var(--accent2)", "var(--accent)"][i]; return '<div class="brow"><span>' + esc(pv.series[i]) + '</span><div class="trk"><i style="width:' + (v / 4.4 * 100).toFixed(1) + "%;background:" + col + '"></i></div><span class="v">' + nombre(v) + "</span></div>"; }).join("") + "</div>" +
      '<p style="margin:0;font-size:15px">Gain sur la persistance : <b style="color:var(--accent)">' + h.gain + ' %</b> <span class="note">' + esc(pv.intervalle) + '</span></p><p class="note" style="margin:10px 0 0">' + esc(pv.note) + "</p></div></div>";
    $$(".hz button", panes).forEach(function (b) { b.onclick = function () { HZ = +b.dataset.h; renderPanes(); showStep(); }; });
    var rt = $("#rt");
    if (rt) {
      var f = function () {
        ratio = +rt.value; var kk = ratio < 0.35 ? "c" : ratio < 0.6 ? "s" : "f";
        $("#rtv").textContent = ratio.toFixed(2); $("#rts").innerHTML = '<span class="state ' + kk + '">' + esc(r.etats[kk]) + "</span>";
      };
      rt.oninput = f; f();
    }
  }
  function showStep() {
    $$(".pane", panes).forEach(function (p) { p.classList.toggle("on", +p.dataset.k === step); });
    $$("button", tabs).forEach(function (b, i) { b.classList.toggle("on", i === step); b.setAttribute("aria-selected", i === step); });
  }
  function intelHook(p) { if (mobile()) return; var i = Math.min(S4.onglets.length - 1, Math.floor(p * S4.onglets.length)); if (i !== step) { step = i; showStep(); } }
  renderPanes(); showStep();

  /* ---------- défilement : progression de chaque scène ---------- */
  var active = 0, other = "";
  function update() {
    var vh = window.innerHeight, mid = vh * 0.5;
    scenesEl.forEach(function (el, i) {
      var r = el.getBoundingClientRect(), span = r.height - vh, p = span > 0 ? Math.min(1, Math.max(0, -r.top / span)) : 0;
      el.style.setProperty("--p", p.toFixed(4));
      $$("[data-at]", el).forEach(function (x) { x.classList.toggle("on", p >= parseFloat(x.dataset.at)); });
      if (r.top < mid) active = i;
      if (C.scenes[i].id === "parcours") flowHook(p);
      if (C.scenes[i].id === "intelligence") intelHook(p);
    });
    var demoTop = $("#demo").getBoundingClientRect().top, matTop = $("#matrice").getBoundingClientRect().top;
    other = matTop < mid ? "COMPÉTENCES BC05" : demoTop < mid ? "DÉMONSTRATION" : "";
    var d = document.documentElement, max = d.scrollHeight - vh;
    $("#bar").style.width = (max > 0 ? window.scrollY / max * 100 : 0) + "%";
    $("#where").textContent = other || ((active ? "SCÈNE " + active + " · " : "") + C.scenes[active].nav.toUpperCase());
    $$("button", rail).forEach(function (b, i) { b.classList.toggle("on", !other && i === active); });
    if (shownScene !== active) { shownScene = active; renderOrateur(); }
  }
  window.addEventListener("scroll", update, { passive: true });
  window.addEventListener("resize", update);

  /* ---------- lecteur de documents : une page qui réunit les documents d'une question, d'une scène ou d'une compétence ---------- */
  var lecteur = document.createElement("div");
  lecteur.className = "lecteur"; lecteur.hidden = true;
  lecteur.innerHTML = '<div class="lec-box" role="dialog" aria-modal="true" aria-labelledby="lecTitre">' +
    '<header class="lec-top"><div><div class="lec-kicker" id="lecKicker"></div><h2 id="lecTitre"></h2></div><button type="button" id="lecFermer">Fermer · Échap</button></header>' +
    '<div class="lec-body"><nav class="lec-nav" id="lecNav" aria-label="Documents de cette page"></nav><article class="lec-doc" id="lecDoc" tabindex="-1"></article></div></div>';
  document.body.appendChild(lecteur);
  var L = { docs: [], cur: "", hist: [], opener: null };

  function groupe(code) {
    var k = code.split(":"), i = +k[1];
    if (k[0] === "s") return { titre: "Preuves · " + C.scenes[i].nav, kicker: i ? "Scène " + i : "Prologue", refs: C.scenes[i].docs || [] };
    if (k[0] === "q") return { titre: C.jury[i].q, kicker: "Question du jury", refs: C.jury[i].docs || [] };
    if (k[0] === "x") return { titre: LEX.entrees[i].t, kicker: "Lexique", refs: LEX.entrees[i].docs || [] };
    return { titre: C.matrice.lignes[i][0], kicker: "Compétence BC05", refs: C.matrice.lignes[i][4] || [] };
  }
  function ouvrir(code, ref, opener) {
    var g = groupe(code), refs = g.refs.filter(existe);
    if (!refs.length) return;
    L.docs = []; L.hist = []; L.opener = opener || document.activeElement;
    refs.forEach(function (r) { var p = cheminDe(r); if (L.docs.indexOf(p) < 0) L.docs.push(p); });
    $("#lecKicker").textContent = g.kicker + " · " + L.docs.length + (L.docs.length > 1 ? " documents" : " document");
    $("#lecTitre").textContent = g.titre;
    lecteur.hidden = false; document.body.classList.add("lec-actif");
    var choix = ref || refs[0], anc = choix.split("#")[1] || "";
    voir(cheminDe(choix), anc, false);
    $("#lecFermer").focus();
  }
  function fermer() {
    lecteur.hidden = true; document.body.classList.remove("lec-actif");
    if (L.opener && L.opener.focus) L.opener.focus();
  }
  function piege(e, racine) {
    var f = $$("button, a[href], input, [tabindex='0']", racine).filter(function (x) { return x.offsetParent !== null; });
    if (!f.length) return;
    var first = f[0], last = f[f.length - 1];
    if (e.shiftKey && (document.activeElement === first || !racine.contains(document.activeElement))) { e.preventDefault(); last.focus(); }
    else if (!e.shiftKey && (document.activeElement === last || !racine.contains(document.activeElement))) { e.preventDefault(); first.focus(); }
  }
  function nav() {
    var box = $("#lecNav");
    box.innerHTML = (L.docs.length > 1 ? '<p class="lec-hint">' + L.docs.length + " documents pour cette page</p>" : "") +
      L.docs.map(function (p, i) {
        var d = DOCS[p], cur = p === L.cur;
        return '<div class="lec-item' + (cur ? " cur" : "") + '"><button type="button" class="lec-open" data-p="' + esc(p) + '"' + (cur ? ' aria-current="true"' : "") + "><b>" + (i + 1) + ". " + esc(d.titre) + "</b><small>" + esc(p) + "</small></button>" +
          (cur && d.toc.length ? '<ul class="lec-toc">' + d.toc.map(function (x) { return '<li class="n' + x[0] + '"><button type="button" data-a="' + esc(x[1]) + '">' + esc(x[2]) + "</button></li>"; }).join("") + "</ul>" : "") + "</div>";
      }).join("");
  }
  function cible(id) { return id ? $('[id="' + id.replace(/"/g, "") + '"]', $("#lecDoc")) : null; }
  function defiler(id) {
    var art = $("#lecDoc"), el = cible(id);
    if (!el) { art.scrollTop = 0; return; }
    art.scrollTop += el.getBoundingClientRect().top - art.getBoundingClientRect().top - 12;
    el.classList.remove("flash"); void el.offsetWidth; el.classList.add("flash");
  }
  function voir(p, anc, empiler) {
    var art = $("#lecDoc"), d = DOCS[p];
    if (empiler && L.cur) L.hist.push({ p: L.cur, y: art.scrollTop });
    if (L.docs.indexOf(p) < 0) L.docs.push(p);  /* document ouvert par un lien : il rejoint la page */
    L.cur = p;
    art.innerHTML = '<div class="lec-meta"><button type="button" id="lecRetour"' + (L.hist.length ? "" : " hidden") + '>← Retour</button><code>' + esc(p) + "</code> · copie du dépôt, commit " + esc(d.commit) + (d.date ? ", " + esc(d.date) : "") + "</div>" + d.html;
    nav();
    defiler(anc);
    if (!anc) art.scrollTop = 0;
  }
  lecteur.addEventListener("click", function (e) {
    var a = e.target.closest ? e.target.closest("a.doc, .lec-open, .lec-toc button, #lecRetour, #lecFermer") : null;
    if (!a) return;
    e.preventDefault();
    if (a.id === "lecFermer") fermer();
    else if (a.id === "lecRetour") { var h = L.hist.pop(); if (h) { voir(h.p, "", false); $("#lecDoc").scrollTop = h.y; } }
    else if (a.classList.contains("doc")) { if (DOCS[a.dataset.doc]) voir(a.dataset.doc, a.dataset.anc, true); }
    else if (a.classList.contains("lec-open")) { if (a.dataset.p !== L.cur) voir(a.dataset.p, "", true); }
    else defiler(a.dataset.a);
  });
  lecteur.addEventListener("mousedown", function (e) { if (e.target === lecteur) fermer(); });
  document.addEventListener("click", function (e) {
    var b = e.target.closest ? e.target.closest("[data-grp]") : null;
    if (b && !lecteur.contains(b)) { toggleJury(false); ouvrir(b.dataset.grp, b.dataset.ref || null, b); }
  });

  /* ---------- lexique : sigles, mots techniques et vocabulaire du projet ---------- */
  var lexique = document.createElement("div");
  lexique.className = "lecteur lex"; lexique.hidden = true;
  var lexSans = function (s) { return String(s).normalize("NFD").replace(/[̀-ͯ]/g, "").toLowerCase(); };
  var lexFmt = function (s) { return esc(s).replace(/`([^`]+)`/g, "<code>$1</code>"); };
  var lexTri = LEX.entrees.map(function (e, i) { return { e: e, i: i }; }).sort(function (a, b) { return a.e.t.localeCompare(b.e.t, "fr", { sensitivity: "base" }); });
  var lexTheme = "", lexOpener = null;
  var lexNom = function (id) { var th = LEX.themes.filter(function (x) { return x.id === id; })[0]; return th ? th.nom : id; };
  var lexLettre = function (t) { var l = lexSans(t).charAt(0).toUpperCase(); return /[A-Z]/.test(l) ? l : "#"; };
  lexique.innerHTML = '<div class="lec-box" role="dialog" aria-modal="true" aria-labelledby="lexTitre">' +
    '<header class="lec-top"><div><div class="lec-kicker" id="lexKicker"></div><h2 id="lexTitre">Lexique : sigles, mots techniques et vocabulaire du projet</h2></div><button type="button" id="lexFermer">Fermer · Échap</button></header>' +
    '<div class="lec-body"><nav class="lec-nav" aria-label="Chercher dans le lexique"><label class="lex-q"><span>Chercher un sigle ou un mot</span><input type="search" id="lexQ" placeholder="ADR, hystérésis, PSI…" autocomplete="off"></label>' +
    '<p class="lec-hint">Thèmes</p><div id="lexThemes" class="lex-themes"></div><p class="lec-hint">Index</p><div id="lexLettres" class="lex-lettres"></div></nav>' +
    '<article class="lec-doc" id="lexListe" tabindex="-1" aria-live="polite"></article></div></div>';
  document.body.appendChild(lexique);

  function lexRendre() {
    var q = lexSans($("#lexQ").value.trim()), vus = 0, parLettre = {}, lettres = [];
    lexTri.forEach(function (x) {
      var e = x.e;
      if (lexTheme && e.c !== lexTheme) return;
      if (q && lexSans([e.t, e.l || "", (e.a || []).join(" "), e.d, e.p || ""].join(" ")).indexOf(q) < 0) return;
      var L = q ? "Résultats" : lexLettre(e.t); if (!parLettre[L]) { parLettre[L] = []; lettres.push(L); }
      parLettre[L].push(x); vus++;
    });
    if (q && parLettre["Résultats"]) {  /* une recherche classe d'abord le terme cherché, puis sa forme développée, puis les définitions */
      var rang = function (e) { var t = lexSans(e.t), l = lexSans(e.l || ""); return t.indexOf(q) === 0 ? 0 : t.indexOf(q) > 0 || l.indexOf(q) >= 0 ? 1 : 2; };
      parLettre["Résultats"].sort(function (a, b) { return rang(a.e) - rang(b.e) || a.e.t.localeCompare(b.e.t, "fr", { sensitivity: "base" }); });
    }
    $("#lexKicker").textContent = "Lexique · " + (q || lexTheme ? vus + " sur " + LEX.entrees.length : LEX.entrees.length) + " termes";
    $("#lexListe").innerHTML = vus ? lettres.map(function (L) {
      return '<section class="lex-groupe" id="lexL-' + (L === "#" ? "autre" : L) + '"><h3 class="lex-lettre">' + L + "</h3>" + parLettre[L].map(function (x) {
        var e = x.e, docs = (e.docs || []).filter(existe);
        return '<div class="lex-e" id="lex-' + x.i + '"><h4><span class="lex-t">' + esc(e.t) + "</span>" + (e.l ? ' <span class="lex-l">' + esc(e.l) + "</span>" : "") + ' <span class="lex-th">' + esc(lexNom(e.c)) + "</span></h4><p>" + lexFmt(e.d) + "</p>" +
          (e.p ? '<p class="lex-p"><b>Dans Novaria.</b> ' + lexFmt(e.p) + "</p>" : "") +
          (docs.length ? '<div class="chips">' + docs.map(function (r) { return '<button type="button" class="chip" data-grp="x:' + x.i + '" data-ref="' + esc(r) + '" title="' + esc(cheminDe(r)) + '">Lire · ' + esc(DOCS[cheminDe(r)].titre) + "</button>"; }).join("") + "</div>" : "") +
          (e.v && e.v.length ? '<p class="lex-v">Voir aussi : ' + e.v.map(function (v) { return '<button type="button" class="lex-voir" data-voir="' + esc(v) + '">' + esc(v) + "</button>"; }).join(" ") + "</p>" : "") + "</div>";
      }).join("") + "</section>";
    }).join("") : '<p class="lex-vide">Aucun terme ne correspond. Essayer un autre mot, ou « Tous » dans les thèmes.</p>';
    $("#lexLettres").innerHTML = q ? "" : lettres.map(function (L) { return '<button type="button" data-l="' + (L === "#" ? "autre" : L) + '">' + L + "</button>"; }).join("");
  }
  function lexThemes() {
    var n = {}; LEX.entrees.forEach(function (e) { n[e.c] = (n[e.c] || 0) + 1; });
    $("#lexThemes").innerHTML = ['<button type="button" data-th="" aria-pressed="' + (lexTheme === "") + '">Tous <small>' + LEX.entrees.length + "</small></button>"].concat(LEX.themes.map(function (th) {
      return '<button type="button" data-th="' + th.id + '" aria-pressed="' + (lexTheme === th.id) + '">' + esc(th.nom) + " <small>" + (n[th.id] || 0) + "</small></button>";
    })).join("");
  }
  function lexOuvrir(opener) {
    if (!LEX.entrees.length) return;
    lexOpener = opener || document.activeElement;
    lexique.hidden = false; document.body.classList.add("lec-actif");
    lexThemes(); lexRendre(); $("#lexQ").focus();
  }
  function lexFermer() {
    lexique.hidden = true; document.body.classList.remove("lec-actif");
    if (lexOpener && lexOpener.focus) lexOpener.focus();
  }
  function lexAller(sel) {
    var liste = $("#lexListe"), el = $(sel, liste);
    if (!el) return;
    liste.scrollTop += el.getBoundingClientRect().top - liste.getBoundingClientRect().top - 12;
    if (sel.indexOf("#lex-") === 0) { el.classList.remove("flash"); void el.offsetWidth; el.classList.add("flash"); }  /* une entrée clignote, pas une lettre entière */
  }
  lexique.addEventListener("click", function (e) {
    var b = e.target.closest ? e.target.closest("button") : null;
    if (!b || b.hasAttribute("data-grp")) return;
    if (b.id === "lexFermer") lexFermer();
    else if (b.hasAttribute("data-th")) { lexTheme = b.dataset.th; lexThemes(); lexRendre(); $("#lexListe").scrollTop = 0; }
    else if (b.hasAttribute("data-l")) lexAller("#lexL-" + b.dataset.l);
    else if (b.hasAttribute("data-voir")) {
      var cible = LEX.entrees.map(function (x, i) { return { x: x, i: i }; }).filter(function (o) { return o.x.t === b.dataset.voir; })[0];
      if (!cible) return;
      $("#lexQ").value = ""; lexTheme = ""; lexThemes(); lexRendre(); lexAller("#lex-" + cible.i);
    }
  });
  lexique.addEventListener("mousedown", function (e) { if (e.target === lexique) lexFermer(); });
  $("#lexQ").addEventListener("input", function () { lexRendre(); $("#lexListe").scrollTop = 0; });
  var btnLex = $("#btnLex"); if (btnLex) { btnLex.onclick = function () { lexOuvrir(btnLex); }; if (!LEX.entrees.length) btnLex.hidden = true; }

  /* ---------- questions du jury ---------- */
  var jury = $("#jury"), jbtn = $("#btnJury");
  jury.innerHTML = "<h3>Questions du jury</h3><p>Chaque question ouvre une page qui réunit les documents qui y répondent.</p>" +
    C.jury.map(function (q, i) {
      var n = (q.docs || []).filter(existe).length;
      return '<button type="button" class="q" data-i="' + i + '">' + esc(q.q) + "<small>→ " + (q.scene ? "Scène " + q.scene : "Prologue") + " · " + (n ? n + (n > 1 ? " documents" : " document") : esc(q.preuve)) + "</small></button>";
    }).join("");
  function toggleJury(v) { var open = typeof v === "boolean" ? v : jury.hidden; jury.hidden = !open; jbtn.setAttribute("aria-expanded", open); }
  jbtn.onclick = function () { toggleJury(); };
  $$("button.q", jury).forEach(function (b) {
    b.onclick = function () {
      var q = C.jury[+b.dataset.i], d = scenesEl[q.scene].nextElementSibling;
      toggleJury(false);
      if ((q.docs || []).filter(existe).length) { scenesEl[q.scene].scrollIntoView(); ouvrir("q:" + b.dataset.i, null, b); return; }
      $("details", d).open = true; d.scrollIntoView({ block: "center" });
    };
  });

  /* ---------- mode orateur : notes de la scène et chronomètre ---------- */
  var orat = $("#orateur"), obtn = $("#btnOrat"), shownScene = -1;
  var chrono = { run: false, t: 0, tick: null };
  function renderOrateur() {
    if (orat.hidden) return;
    var s = C.scenes[active], now = startOf(active), plan = C.scenes.map(function (x, i) {
      return '<div class="' + (i === active ? "cur" : "") + '">' + mmss(startOf(i)) + " – " + mmss(startOf(i) + x.secs) + " · " + esc(x.nav) + "</div>";
    }).join("");
    orat.innerHTML = '<div><h3>Notes · ' + (active ? "Scène " + active + " · " : "") + esc(s.nav) + "</h3><ul>" + li(s.orateur) + "</ul>" +
      ((s.docs || []).filter(existe).length ? '<button type="button" class="tout" data-grp="s:' + active + '">Documents de la scène · ' + s.docs.filter(existe).length + "</button>" : "") + "</div>" +
      '<div><h3>Temps</h3><div class="chrono' + (chrono.t > TOTAL ? " over" : "") + '" id="chr">' + mmss(chrono.t) + " <small>/ " + mmss(TOTAL) + '</small></div><div class="crow"><button type="button" id="cgo">' + (chrono.run ? "Pause" : "Démarrer") + '</button><button type="button" id="crz">Remettre à zéro</button></div><div class="plan">' + plan + "</div></div>";
    $("#cgo").onclick = function () { setChrono(!chrono.run); };
    $("#crz").onclick = function () { chrono.t = 0; setChrono(false); renderOrateur(); };
    void now;
  }
  function setChrono(run) {
    chrono.run = run; clearInterval(chrono.tick);
    if (run) chrono.tick = setInterval(function () { chrono.t++; var el = $("#chr"); if (el) { el.firstChild.nodeValue = mmss(chrono.t) + " "; el.classList.toggle("over", chrono.t > TOTAL); } }, 1000);
    var b = $("#cgo"); if (b) b.textContent = run ? "Pause" : "Démarrer";
  }
  function toggleOrateur(v) { var open = typeof v === "boolean" ? v : orat.hidden; orat.hidden = !open; obtn.setAttribute("aria-pressed", open); renderOrateur(); }
  obtn.onclick = function () { toggleOrateur(); };

  /* ---------- barre du haut, touches, impression ---------- */
  $("#btnTheme").onclick = function () { theme = THEMES[(THEMES.indexOf(theme) + 1) % THEMES.length]; applyTheme(); };
  function go(delta) { var i = Math.min(C.scenes.length - 1, Math.max(0, active + delta)); scenesEl[i].scrollIntoView(); }
  document.addEventListener("keydown", function (e) {
    if (e.ctrlKey || e.metaKey || e.altKey) return;
    if (!lecteur.hidden) { if (e.key === "Escape") { e.preventDefault(); fermer(); } else if (e.key === "Tab") piege(e, lecteur); return; }  /* le lecteur ouvert garde les touches */
    if (!lexique.hidden) { if (e.key === "Escape") { e.preventDefault(); lexFermer(); } else if (e.key === "Tab") piege(e, lexique); return; }
    var t = e.target && e.target.tagName; if (t === "INPUT" || t === "SELECT" || t === "TEXTAREA") return;
    if (e.key === "ArrowRight") { e.preventDefault(); go(1); }
    else if (e.key === "ArrowLeft") { e.preventDefault(); go(-1); }
    else if (e.key === "j" || e.key === "J") toggleJury();
    else if (e.key === "p" || e.key === "P") toggleOrateur();
    else if (e.key === "t" || e.key === "T") $("#btnTheme").click();
    else if (e.key === "l" || e.key === "L") lexOuvrir();
    else if (e.key === "Escape") { toggleJury(false); toggleOrateur(false); }
  });
  window.addEventListener("beforeprint", function () { $$("details").forEach(function (d) { d.open = true; }); });

  applyTheme(); update();
})();
