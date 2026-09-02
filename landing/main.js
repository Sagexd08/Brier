/* ==========================================================================
   Brier landing page
   ========================================================================== */
(function () {
  "use strict";

  var reduceMotion = window.matchMedia("(prefers-reduced-motion: reduce)").matches;

  /* ------------------------------------------------------------------
     Stat count-up.

     Runs once, driven by IntersectionObserver so the numbers animate when
     the row is actually on screen rather than on a blind timer. easeOutCubic
     lands the value softly instead of stopping dead.
     ------------------------------------------------------------------ */
  var stats = Array.prototype.slice.call(document.querySelectorAll(".stat-value"));

  function format(value, decimals, suffix) {
    return value.toFixed(decimals) + suffix;
  }

  function countUp(el, index) {
    var target = parseFloat(el.dataset.target);
    var decimals = parseInt(el.dataset.decimals, 10) || 0;
    var suffix = el.dataset.suffix || "";

    if (reduceMotion || !isFinite(target)) {
      el.textContent = format(target, decimals, suffix);
      return;
    }

    var duration = 1500 + index * 80;
    var startDelay = 480 + index * 90;

    window.setTimeout(function () {
      var start = null;

      function frame(now) {
        if (start === null) start = now;
        var elapsed = now - start;
        var t = Math.min(elapsed / duration, 1);
        var eased = 1 - Math.pow(1 - t, 3); // easeOutCubic
        el.textContent = format(target * eased, decimals, suffix);
        if (t < 1) window.requestAnimationFrame(frame);
        else el.textContent = format(target, decimals, suffix);
      }

      window.requestAnimationFrame(frame);
    }, startDelay);
  }

  if (stats.length) {
    if (typeof IntersectionObserver === "function") {
      var io = new IntersectionObserver(
        function (entries) {
          entries.forEach(function (entry) {
            if (!entry.isIntersecting) return;
            countUp(entry.target, stats.indexOf(entry.target));
            io.unobserve(entry.target);
          });
        },
        { threshold: 0.25 }
      );
      stats.forEach(function (el) {
        io.observe(el);
      });
    } else {
      stats.forEach(countUp);
    }
  }

  /* ------------------------------------------------------------------
     Mobile menu
     ------------------------------------------------------------------ */
  var burger = document.querySelector(".burger");
  var overlay = document.querySelector(".menu-overlay");
  var menu = document.getElementById("mobile-menu");
  var body = document.body;

  function setMenu(open) {
    if (!burger || !overlay || !menu) return;
    body.classList.toggle("menu-open", open);
    burger.setAttribute("aria-expanded", open ? "true" : "false");
    burger.setAttribute("aria-label", open ? "Close menu" : "Open menu");
    overlay.hidden = !open;
    menu.hidden = !open;
  }

  if (burger) {
    burger.addEventListener("click", function () {
      setMenu(!body.classList.contains("menu-open"));
    });
  }

  if (overlay) {
    overlay.addEventListener("click", function () {
      setMenu(false);
    });
  }

  if (menu) {
    menu.addEventListener("click", function (e) {
      if (e.target.closest("a")) setMenu(false);
    });
  }

  document.addEventListener("keydown", function (e) {
    if (e.key === "Escape") setMenu(false);
  });

  window.addEventListener("resize", function () {
    if (window.innerWidth > 720) setMenu(false);
  });

  /* ------------------------------------------------------------------
     Background video.

     Autoplay is refused in some contexts even when muted. Retry once on
     the first user gesture, and if the video still cannot start, leave the
     black ground rather than a broken frame.
     ------------------------------------------------------------------ */
  var video = document.querySelector(".bg-video");

  if (video) {
    if (reduceMotion) {
      video.pause();
    } else {
      var attempt = video.play();
      if (attempt && typeof attempt.catch === "function") {
        attempt.catch(function () {
          var resume = function () {
            video.play().catch(function () {});
            document.removeEventListener("pointerdown", resume);
          };
          document.addEventListener("pointerdown", resume, { once: true });
        });
      }
    }
  }
})();
