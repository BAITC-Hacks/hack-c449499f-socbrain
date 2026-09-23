// SOCBrain — применение внешнего вида до отрисовки страницы (без «вспышки» темы).
// Значения по умолчанию задаёт администратор в Настройки → «Тема и плотность»;
// api.js подтягивает их с сервера и кладёт сюда в localStorage.
(function () {
  var a = {};
  try { a = JSON.parse(localStorage.getItem("socbrain.appearance") || "{}"); } catch (e) { a = {}; }
  window.applyAppearance = function (a) {
    var r = document.documentElement;
    if (a.theme && a.theme !== "system") r.setAttribute("data-theme", a.theme); else r.removeAttribute("data-theme");
    r.setAttribute("data-density", a.density || "normal");
    r.setAttribute("data-font", a.font_scale || "100");
    if (a.high_contrast) r.setAttribute("data-contrast", "high"); else r.removeAttribute("data-contrast");
    if (a.reduce_motion) r.setAttribute("data-motion", "reduce"); else r.removeAttribute("data-motion");
  };
  window.applyAppearance(a);
})();
