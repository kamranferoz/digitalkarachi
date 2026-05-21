/* Digital Karachi — Editorial Minimal interactions */
(function () {
  'use strict';
  var root = document.documentElement;

  // -- Theme toggle (auto / light / dark) -------------------------
  function applyTheme(t) {
    root.setAttribute('data-theme', t);
    try { localStorage.setItem('dk-theme', t); } catch (e) {}
  }
  function currentTheme() {
    var stored;
    try { stored = localStorage.getItem('dk-theme'); } catch (e) {}
    return stored || 'auto';
  }
  function nextTheme(t) {
    // 3-state cycle: auto -> light -> dark -> auto
    if (t === 'auto') return matchMedia('(prefers-color-scheme: dark)').matches ? 'light' : 'dark';
    if (t === 'light') return 'dark';
    return 'light';
  }
  root.setAttribute('data-theme', currentTheme());
  document.addEventListener('click', function (e) {
    var btn = e.target.closest('.dk-theme-toggle');
    if (!btn) return;
    e.preventDefault();
    applyTheme(nextTheme(currentTheme()));
  });

  // -- Mobile menu overlay ----------------------------------------
  document.addEventListener('click', function (e) {
    var open = e.target.closest('.dk-mobile-menu-btn');
    var close = e.target.closest('.dk-mobile-overlay .dk-close, .dk-mobile-overlay a');
    var overlay = document.querySelector('.dk-mobile-overlay');
    if (!overlay) return;
    if (open) { overlay.setAttribute('data-open', 'true'); overlay.hidden = false; document.body.style.overflow = 'hidden'; }
    else if (close) { overlay.setAttribute('data-open', 'false'); document.body.style.overflow = ''; setTimeout(function(){ overlay.hidden = true; }, 250); }
  });
  document.addEventListener('keydown', function (e) {
    if (e.key !== 'Escape') return;
    var overlay = document.querySelector('.dk-mobile-overlay[data-open="true"]');
    if (overlay) { overlay.setAttribute('data-open', 'false'); document.body.style.overflow = ''; setTimeout(function(){ overlay.hidden = true; }, 250); }
  });

  // -- Active nav link --------------------------------------------
  function markActiveNav() {
    var path = location.pathname.replace(/\/index\.html$/, '/');
    if (path === '') path = '/';
    document.querySelectorAll('.dk-nav-links a, .dk-mobile-overlay a').forEach(function (a) {
      var href = a.getAttribute('href') || '';
      // normalize to a path segment
      var clean = href.replace(/^.*?(?:\/|^)([^/]*\/?)$/, '$1') || '/';
      if (clean === 'index.html' || clean === '' || clean === './') clean = '/';
      var p = path.split('/').filter(Boolean).slice(-1)[0] || '/';
      if ((p === '/' && (clean === '/' || clean === 'index.html')) ||
          (p !== '/' && clean.replace(/\/$/, '') === p)) {
        a.classList.add('is-active');
      }
    });
  }
  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', markActiveNav);
  } else { markActiveNav(); }

  // -- Reading-progress bar (article pages) -----------------------
  var progress = document.querySelector('.dk-progress');
  var article = document.querySelector('.dk-prose');
  if (progress && article) {
    progress.hidden = false;
    function update() {
      var rect = article.getBoundingClientRect();
      var total = article.offsetHeight - window.innerHeight;
      var read = Math.min(Math.max(-rect.top, 0), Math.max(total, 1));
      var pct = total > 0 ? (read / total) * 100 : 0;
      progress.style.width = pct + '%';
    }
    update();
    window.addEventListener('scroll', update, { passive: true });
    window.addEventListener('resize', update);
  }
})();
