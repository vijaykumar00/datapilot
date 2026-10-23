// Applies the saved theme before first paint (external file: CSP forbids inline scripts).
// "system" (or nothing saved) follows prefers-color-scheme.
(function () {
  try {
    var pref = localStorage.getItem('dp_theme') || 'system';
    var dark = pref === 'dark' || (pref === 'system' && window.matchMedia('(prefers-color-scheme: dark)').matches);
    document.documentElement.classList.toggle('dark', dark);
  } catch (e) { /* storage blocked: stay on the light default */ }
})();
