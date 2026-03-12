/* ================================================================
   ShutdownTimer — Landing Page JavaScript
   ================================================================ */

'use strict';

/* ── Cursor glow ─────────────────────────────────────────────── */
const cursorGlow = document.getElementById('cursorGlow');
let mouseX = 0, mouseY = 0;
let glowX = 0, glowY = 0;

document.addEventListener('mousemove', e => {
  mouseX = e.clientX;
  mouseY = e.clientY;
});

(function animateCursor() {
  glowX += (mouseX - glowX) * 0.08;
  glowY += (mouseY - glowY) * 0.08;
  cursorGlow.style.left = glowX + 'px';
  cursorGlow.style.top  = glowY + 'px';
  requestAnimationFrame(animateCursor);
})();

// Restore default cursor on interactive elements
document.querySelectorAll('a, button, input, [role="button"]').forEach(el => {
  el.style.cursor = 'pointer';
});


/* ── Canvas background — circuit grid + particles ───────────── */
const canvas = document.getElementById('bgCanvas');
const ctx    = canvas.getContext('2d');
let W, H;

function resizeCanvas() {
  W = canvas.width  = window.innerWidth;
  H = canvas.height = window.innerHeight;
}
resizeCanvas();
window.addEventListener('resize', resizeCanvas);

// Particles
const PARTICLE_COUNT = 55;
const particles = Array.from({ length: PARTICLE_COUNT }, () => ({
  x:  Math.random() * window.innerWidth,
  y:  Math.random() * window.innerHeight,
  vx: (Math.random() - 0.5) * 0.3,
  vy: (Math.random() - 0.5) * 0.3,
  r:  Math.random() * 1.5 + 0.5,
  a:  Math.random()
}));

function drawBg() {
  ctx.clearRect(0, 0, W, H);

  // Update particles
  particles.forEach(p => {
    p.x += p.vx; p.y += p.vy;
    if (p.x < 0) p.x = W; if (p.x > W) p.x = 0;
    if (p.y < 0) p.y = H; if (p.y > H) p.y = 0;
  });

  // Draw connections
  for (let i = 0; i < particles.length; i++) {
    for (let j = i + 1; j < particles.length; j++) {
      const dx   = particles[i].x - particles[j].x;
      const dy   = particles[i].y - particles[j].y;
      const dist = Math.sqrt(dx * dx + dy * dy);
      if (dist < 130) {
        const alpha = (1 - dist / 130) * 0.12;
        ctx.beginPath();
        ctx.strokeStyle = `rgba(79, 142, 247, ${alpha})`;
        ctx.lineWidth   = 0.8;
        ctx.moveTo(particles[i].x, particles[i].y);
        ctx.lineTo(particles[j].x, particles[j].y);
        ctx.stroke();
      }
    }
  }

  // Draw particles
  particles.forEach(p => {
    ctx.beginPath();
    ctx.arc(p.x, p.y, p.r, 0, Math.PI * 2);
    ctx.fillStyle = `rgba(79, 142, 247, ${p.a * 0.5})`;
    ctx.fill();
  });

  requestAnimationFrame(drawBg);
}
drawBg();


/* ── Navbar scroll behavior ─────────────────────────────────── */
const navbar = document.getElementById('navbar');

function updateNavbar() {
  if (window.scrollY > 60) {
    navbar.classList.add('scrolled');
  } else {
    navbar.classList.remove('scrolled');
  }
}
window.addEventListener('scroll', updateNavbar, { passive: true });
updateNavbar();


/* ── Mobile menu ─────────────────────────────────────────────── */
const navBurger = document.getElementById('navBurger');
const navMobile = document.getElementById('navMobile');

navBurger.addEventListener('click', () => {
  navMobile.classList.toggle('open');
  const spans = navBurger.querySelectorAll('span');
  const isOpen = navMobile.classList.contains('open');
  spans[0].style.transform = isOpen ? 'rotate(45deg) translate(5px, 5px)' : '';
  spans[1].style.opacity   = isOpen ? '0' : '1';
  spans[2].style.transform = isOpen ? 'rotate(-45deg) translate(5px, -5px)' : '';
});

navMobile.querySelectorAll('a').forEach(a => {
  a.addEventListener('click', () => {
    navMobile.classList.remove('open');
    navBurger.querySelectorAll('span').forEach(s => {
      s.style.transform = ''; s.style.opacity = '';
    });
  });
});


/* ── Smooth scroll for anchor links ─────────────────────────── */
document.querySelectorAll('a[href^="#"]').forEach(a => {
  a.addEventListener('click', e => {
    const target = document.querySelector(a.getAttribute('href'));
    if (!target) return;
    e.preventDefault();
    const navH = parseInt(getComputedStyle(document.documentElement)
      .getPropertyValue('--nav-h')) || 64;
    window.scrollTo({
      top: target.getBoundingClientRect().top + window.scrollY - navH - 8,
      behavior: 'smooth'
    });
  });
});


/* ── Intersection Observer — reveal animations ───────────────── */
const observerOpts = {
  threshold: 0.12,
  rootMargin: '0px 0px -60px 0px'
};

// Feat cards
const featObserver = new IntersectionObserver(entries => {
  entries.forEach(entry => {
    if (entry.isIntersecting) {
      const delay = parseInt(entry.target.dataset.delay || '0');
      setTimeout(() => entry.target.classList.add('visible'), delay);
      featObserver.unobserve(entry.target);
    }
  });
}, observerOpts);
document.querySelectorAll('.feat-card').forEach(el => featObserver.observe(el));

// Steps
const stepObserver = new IntersectionObserver(entries => {
  entries.forEach(entry => {
    if (entry.isIntersecting) {
      const index = [...document.querySelectorAll('.step-item')].indexOf(entry.target);
      setTimeout(() => entry.target.classList.add('visible'), index * 120);
      stepObserver.unobserve(entry.target);
    }
  });
}, observerOpts);
document.querySelectorAll('.step-item').forEach(el => stepObserver.observe(el));

// Mockup windows
const mockupObserver = new IntersectionObserver(entries => {
  entries.forEach((entry, i) => {
    if (entry.isIntersecting) {
      setTimeout(() => entry.target.classList.add('visible'), i * 100);
      mockupObserver.unobserve(entry.target);
    }
  });
}, observerOpts);
document.querySelectorAll('.mockup-window[data-reveal]').forEach(el => mockupObserver.observe(el));

// Security list items
const secObserver = new IntersectionObserver(entries => {
  entries.forEach(entry => {
    if (entry.isIntersecting) {
      const items = entry.target.querySelectorAll('li');
      items.forEach((li, i) => {
        setTimeout(() => li.classList.add('visible'), i * 120);
      });
      secObserver.unobserve(entry.target);
    }
  });
}, observerOpts);
document.querySelectorAll('.security-list').forEach(el => secObserver.observe(el));

// Security card
const secCardObserver = new IntersectionObserver(entries => {
  entries.forEach(entry => {
    if (entry.isIntersecting) {
      entry.target.classList.add('visible');
      secCardObserver.unobserve(entry.target);
    }
  });
}, observerOpts);
document.querySelectorAll('.security-card-wrap').forEach(el => secCardObserver.observe(el));


/* ── Hero timer demo ─────────────────────────────────────────── */
const timerDigits  = document.getElementById('timerDigits');
const ringFill     = document.getElementById('ringFill');
const demoStart    = document.getElementById('demoStart');
const demoCancel   = document.getElementById('demoCancel');

const RING_CIRCUM = 2 * Math.PI * 52; // ≈ 326.7
let demoInterval  = null;
let demoRunning   = false;
let demoTotal     = 30 * 60; // 30 min in seconds
let demoRemaining = demoTotal;

function updateDemoRing() {
  const pct    = demoRemaining / demoTotal;
  const offset = RING_CIRCUM * (1 - pct);
  ringFill.style.strokeDashoffset = offset;

  // Color shift near end
  if (demoRemaining <= 30) {
    ringFill.style.stroke = '#f75a5a';
  } else if (demoRemaining <= 300) {
    ringFill.style.stroke = '#f7a94f';
  } else {
    ringFill.style.stroke = '';
  }
}

function formatDemo(s) {
  const m = Math.floor(s / 60);
  const sec = s % 60;
  return `${String(m).padStart(2, '0')}:${String(sec).padStart(2, '0')}`;
}

// Inject SVG gradient
ringFill.style.stroke = 'url(#ringGrad)';
const svgEl = ringFill.closest('svg');
const defs  = document.createElementNS('http://www.w3.org/2000/svg', 'defs');
defs.innerHTML = `
  <linearGradient id="ringGrad" x1="0%" y1="0%" x2="100%" y2="100%">
    <stop offset="0%"   stop-color="#4f8ef7"/>
    <stop offset="100%" stop-color="#7c5cf7"/>
  </linearGradient>`;
svgEl.prepend(defs);

function startDemo() {
  if (demoRunning) return;
  demoRunning = true;
  demoStart.textContent = '⏸ Pausar';

  demoInterval = setInterval(() => {
    if (demoRemaining <= 0) {
      stopDemo(true);
      return;
    }
    demoRemaining--;
    timerDigits.textContent = formatDemo(demoRemaining);
    updateDemoRing();
  }, 1000);
}

function pauseDemo() {
  clearInterval(demoInterval);
  demoRunning = false;
  demoStart.textContent = '▶ Retomar';
}

function stopDemo(finished = false) {
  clearInterval(demoInterval);
  demoRunning   = false;
  demoRemaining = demoTotal;
  timerDigits.textContent = formatDemo(demoRemaining);
  updateDemoRing();
  demoStart.textContent = '▶ Iniciar';
  if (finished) {
    timerDigits.textContent = '00:00';
    setTimeout(() => {
      demoRemaining = demoTotal;
      timerDigits.textContent = formatDemo(demoRemaining);
      updateDemoRing();
    }, 1500);
  }
}

demoStart.addEventListener('click', () => {
  if (demoRunning) pauseDemo(); else startDemo();
});
demoCancel.addEventListener('click', () => stopDemo());

// Initialize ring
updateDemoRing();


/* ── Screenshots live timers ─────────────────────────────────── */
let screenshotSeconds = 28 * 60 + 43;
const appTimerDisplay = document.getElementById('appTimerDisplay');
const widgetTime      = document.getElementById('widgetTime');

function fmtSS(s) {
  const m = Math.floor(s / 60);
  const sec = s % 60;
  return `${String(m).padStart(2,'0')}:${String(sec).padStart(2,'0')}`;
}

setInterval(() => {
  if (screenshotSeconds > 0) screenshotSeconds--;
  const t = fmtSS(screenshotSeconds);
  if (appTimerDisplay) appTimerDisplay.textContent = t;
  if (widgetTime)      widgetTime.textContent      = t;
}, 1000);


/* ── Dialog countdown demo ───────────────────────────────────── */
const dlgCountdown = document.getElementById('dlgCountdown');
const dlgBarFill   = document.getElementById('dlgBarFill');
let dlgSecs = 15;
let dlgDirection = -1; // counting down then reset

setInterval(() => {
  dlgSecs += dlgDirection;
  if (dlgSecs <= 0) {
    dlgDirection = 1;
    dlgSecs = 0;
    setTimeout(() => { dlgSecs = 15; dlgDirection = -1; }, 1200);
  }
  if (dlgCountdown) {
    dlgCountdown.textContent = dlgSecs;
    const pct = dlgSecs / 15 * 100;
    dlgCountdown.style.color = dlgSecs <= 5 ? 'var(--danger)' : 'var(--warning)';
    if (dlgBarFill) {
      dlgBarFill.style.animation = 'none';
      dlgBarFill.style.width = pct + '%';
    }
  }
}, 1000);


/* ── Download button interaction ─────────────────────────────── */
const downloadBtn = document.getElementById('downloadBtn');
if (downloadBtn) {
  downloadBtn.addEventListener('click', function (e) {
    e.preventDefault();
    const originalHTML = this.innerHTML;

    // Simulate download start
    const icon = this.querySelector('.btn-dl-main');
    const sub  = this.querySelector('.btn-dl-sub');
    if (icon) icon.textContent = 'Preparando download...';
    if (sub)  sub.textContent  = 'Aguarde um momento';

    this.style.opacity = '0.8';
    this.style.pointerEvents = 'none';

    setTimeout(() => {
      if (icon) icon.textContent = '✓ Download iniciado!';
      if (sub)  sub.textContent  = 'shutdown_timer.exe';
    }, 900);

    setTimeout(() => {
      this.innerHTML = originalHTML;
      this.style.opacity = '1';
      this.style.pointerEvents = 'auto';
    }, 3200);
  });
}


/* ── Scroll progress indicator ──────────────────────────────── */
const progressBar = document.createElement('div');
progressBar.style.cssText = `
  position: fixed;
  top: 0; left: 0;
  height: 2px;
  width: 0%;
  background: linear-gradient(90deg, #4f8ef7, #7c5cf7);
  z-index: 200;
  transition: width 0.1s linear;
  pointer-events: none;
`;
document.body.appendChild(progressBar);

window.addEventListener('scroll', () => {
  const scrollTop  = window.scrollY;
  const docHeight  = document.documentElement.scrollHeight - window.innerHeight;
  const pct        = docHeight > 0 ? (scrollTop / docHeight) * 100 : 0;
  progressBar.style.width = pct + '%';
}, { passive: true });


/* ── Tray timer sync ─────────────────────────────────────────── */
const trayTimerText = document.querySelector('.tray-timer-text');
setInterval(() => {
  if (trayTimerText) trayTimerText.textContent = fmtSS(screenshotSeconds);
}, 1000);


/* ── Feature card tilt effect ───────────────────────────────── */
document.querySelectorAll('.feat-card').forEach(card => {
  card.addEventListener('mousemove', e => {
    const rect = card.getBoundingClientRect();
    const cx   = rect.left + rect.width  / 2;
    const cy   = rect.top  + rect.height / 2;
    const dx   = (e.clientX - cx) / rect.width  * 10;
    const dy   = (e.clientY - cy) / rect.height * 10;
    card.style.transform = `
      translateY(-3px)
      perspective(600px)
      rotateY(${dx}deg)
      rotateX(${-dy}deg)
    `;
  });
  card.addEventListener('mouseleave', () => {
    card.style.transform = '';
  });
});


/* ── Stats counter animation ─────────────────────────────────── */
function animateCounter(el, from, to, duration = 1200, suffix = '') {
  let start = null;
  function step(ts) {
    if (!start) start = ts;
    const progress = Math.min((ts - start) / duration, 1);
    const eased    = 1 - Math.pow(1 - progress, 3); // ease-out cubic
    el.textContent = Math.round(from + (to - from) * eased) + suffix;
    if (progress < 1) requestAnimationFrame(step);
  }
  requestAnimationFrame(step);
}

const statsObserver = new IntersectionObserver(entries => {
  entries.forEach(entry => {
    if (entry.isIntersecting) {
      statsObserver.unobserve(entry.target);
      // No real counters in this design, but hook is here for future use
    }
  });
});
document.querySelectorAll('.stat-num').forEach(el => statsObserver.observe(el));


/* ── Active nav link highlight on scroll ─────────────────────── */
const sections  = document.querySelectorAll('section[id]');
const navAnchors = document.querySelectorAll('.nav-links a[href^="#"]');

const navObserver = new IntersectionObserver(entries => {
  entries.forEach(entry => {
    if (entry.isIntersecting) {
      navAnchors.forEach(a => {
        a.style.color = '';
        if (a.getAttribute('href') === '#' + entry.target.id) {
          a.style.color = 'var(--accent)';
        }
      });
    }
  });
}, { threshold: 0.4 });

sections.forEach(s => navObserver.observe(s));


/* ── Keyboard shortcut easter egg ────────────────────────────── */
let konamiBuffer = [];
const SHUTDOWN_KEY = ['s', 'h', 'u', 't'];
document.addEventListener('keydown', e => {
  konamiBuffer.push(e.key.toLowerCase());
  konamiBuffer = konamiBuffer.slice(-4);
  if (konamiBuffer.join('') === SHUTDOWN_KEY.join('')) {
    const msg = document.createElement('div');
    msg.textContent = '⏻ Shutdown Timer says hi 👋';
    msg.style.cssText = `
      position: fixed; bottom: 24px; right: 24px;
      background: var(--surface2);
      color: var(--accent);
      font-family: 'Oxanium', monospace;
      font-size: 0.9rem;
      padding: 14px 22px;
      border-radius: 10px;
      border: 1px solid var(--border2);
      z-index: 9000;
      box-shadow: 0 0 24px rgba(79,142,247,0.3);
      animation: fadeDown 0.4s ease;
    `;
    document.body.appendChild(msg);
    setTimeout(() => msg.remove(), 3000);
  }
});


/* ── Init ────────────────────────────────────────────────────── */
console.log('%c⏻ ShutdownTimer', 'color:#4f8ef7;font-family:monospace;font-size:1.4rem;font-weight:bold;');
console.log('%cOpen source. Zero telemetria. MIT License.', 'color:#7b82a8;font-family:monospace;');