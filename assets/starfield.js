// SSTool+ · animated crimson starfall background.
// A fixed canvas behind the interface: deep-red nebulae, layered parallax stars,
// twinkling four-point flares, a steady drizzle of falling stars and brighter
// shooting stars with sparks. Safe Mode gets a static field; the background is
// intentionally always animated otherwise, even when Windows reports
// "prefers-reduced-motion" (that setting stays respected by the UI itself).
(() => {
  'use strict';
  if (window.__sstoolStarfield) return;
  window.__sstoolStarfield = true;

  const html = document.documentElement;
  const motionOff = () => html.classList.contains('low-effects')
    || window.SSToolLowEffects === true;

  const canvas = document.createElement('canvas');
  canvas.id = 'sstool-stars';
  canvas.setAttribute('aria-hidden', 'true');
  const ctx = canvas.getContext('2d', { alpha: true });
  if (!ctx) return;

  const st = canvas.style;
  st.position = 'fixed';
  st.inset = '0';
  st.width = '100%';
  st.height = '100%';
  st.display = 'block';
  st.pointerEvents = 'none';
  st.zIndex = '-1';
  st.opacity = '0';
  st.transition = 'opacity 1s ease';
  document.body.insertBefore(canvas, document.body.firstChild);

  const TAU = Math.PI * 2;
  const rand = (min, max) => min + Math.random() * (max - min);
  const viewport = () => [
    Math.max(1, window.innerWidth || document.documentElement.clientWidth || 1),
    Math.max(1, window.innerHeight || document.documentElement.clientHeight || 1)
  ];

  // White-hot cores with progressively redder halos. Most stars stay pale so the
  // crimson nebula supplies the colour, with a few deep-red giants for contrast.
  const PALETTE = [
    '255,255,255',
    '255,244,248',
    '255,226,236',
    '255,196,212',
    '255,154,177',
    '255,102,131',
    '255,62,96',
    '255,36,70'
  ];

  const colourIndex = () => {
    const r = Math.random();
    if (r < 0.24) return 0;
    if (r < 0.50) return 1;
    if (r < 0.70) return 2;
    if (r < 0.84) return 3;
    if (r < 0.92) return 4;
    if (r < 0.96) return 5;
    if (r < 0.99) return 6;
    return 7;
  };

  function glowSprite(rgb) {
    const c = document.createElement('canvas');
    c.width = c.height = 64;
    const g = c.getContext('2d');
    const gradient = g.createRadialGradient(32, 32, 0, 32, 32, 32);
    gradient.addColorStop(0, 'rgba(' + rgb + ',1)');
    gradient.addColorStop(0.12, 'rgba(' + rgb + ',.98)');
    gradient.addColorStop(0.28, 'rgba(' + rgb + ',.38)');
    gradient.addColorStop(0.52, 'rgba(' + rgb + ',.11)');
    gradient.addColorStop(0.8, 'rgba(' + rgb + ',.025)');
    gradient.addColorStop(1, 'rgba(' + rgb + ',0)');
    g.fillStyle = gradient;
    g.fillRect(0, 0, 64, 64);
    return c;
  }

  function cloudSprite(rgb, phase) {
    const S = 512;
    const c = document.createElement('canvas');
    c.width = c.height = S;
    const g = c.getContext('2d');
    g.globalCompositeOperation = 'lighter';

    // Several soft lobes per cloud keep the silhouette organic instead of a
    // perfect circle. The sprite is scaled up, so smooth falloffs matter more
    // than detail here.
    const lobes = [
      { x: 0.50 + Math.cos(phase) * 0.17, y: 0.50 + Math.sin(phase) * 0.13, r: 0.40 },
      { x: 0.36 + Math.sin(phase * 1.7) * 0.12, y: 0.44 + Math.cos(phase * 0.8) * 0.16, r: 0.32 },
      { x: 0.63 + Math.cos(phase * 1.3) * 0.10, y: 0.60 + Math.sin(phase * 1.9) * 0.12, r: 0.36 },
      { x: 0.44 + Math.sin(phase * 2.1) * 0.09, y: 0.62 + Math.cos(phase * 2.3) * 0.09, r: 0.26 }
    ];
    for (const lobe of lobes) {
      const cx = S * lobe.x;
      const cy = S * lobe.y;
      const radius = S * lobe.r;
      const gradient = g.createRadialGradient(cx, cy, 0, cx, cy, radius);
      gradient.addColorStop(0, 'rgba(' + rgb + ',.34)');
      gradient.addColorStop(0.18, 'rgba(' + rgb + ',.24)');
      gradient.addColorStop(0.42, 'rgba(' + rgb + ',.10)');
      gradient.addColorStop(0.68, 'rgba(' + rgb + ',.028)');
      gradient.addColorStop(0.86, 'rgba(' + rgb + ',.006)');
      gradient.addColorStop(1, 'rgba(' + rgb + ',0)');
      g.fillStyle = gradient;
      g.beginPath();
      g.arc(cx, cy, radius, 0, TAU);
      g.fill();
    }

    // A touch of alpha dithering breaks the 8-bit rings that appear when a low
    // alpha cloud is scaled across the full window.
    const image = g.getImageData(0, 0, S, S);
    const data = image.data;
    for (let i = 0; i < data.length; i += 4) {
      const value = data[i + 3] + (Math.random() - 0.5) * 8;
      data[i + 3] = value < 0 ? 0 : value > 255 ? 255 : value;
    }
    g.putImageData(image, 0, 0);
    return c;
  }

  const GLOWS = PALETTE.map(glowSprite);
  const CLOUDS = [
    cloudSprite('255,42,78', 0.4),
    cloudSprite('176,0,58', 2.1),
    cloudSprite('112,0,36', 4.2),
    cloudSprite('255,86,118', 1.3)
  ];
  const HEAD = glowSprite('255,238,244');

  const NEBULA = [
    { fx: 0.14, fy: 0.22, size: 0.78, cloud: 1, speed: 0.045, phase: 0.4, alpha: 0.30 },
    { fx: 0.86, fy: 0.76, size: 0.86, cloud: 0, speed: 0.037, phase: 2.2, alpha: 0.26 },
    { fx: 0.62, fy: 0.12, size: 0.54, cloud: 3, speed: 0.055, phase: 4.5, alpha: 0.16 },
    { fx: 0.30, fy: 0.88, size: 0.58, cloud: 2, speed: 0.028, phase: 1.3, alpha: 0.34 },
    { fx: 0.50, fy: 0.50, size: 1.10, cloud: 1, speed: 0.019, phase: 3.4, alpha: 0.12 }
  ];

  const pointer = { x: 0, y: 0, tx: 0, ty: 0 };
  let W = 1;
  let H = 1;
  let DPR = 1;
  let stars = [];
  let meteors = [];
  let sparks = [];
  let raf = 0;
  let last = 0;
  let nextDrizzleAt = 0;
  let nextMeteorAt = 0;
  let resizeTimer = 0;
  let visible = !document.hidden;
  let introGone = !document.getElementById('intro-frame');

  function buildStars() {
    const count = Math.round(Math.min(400, Math.max(210, (W * H) / 4200)));
    stars = new Array(count);
    for (let i = 0; i < count; i++) {
      const depth = Math.pow(Math.random(), 0.7);
      const ci = colourIndex();
      stars[i] = {
        x: rand(0, W),
        y: rand(0, H),
        d: depth,
        r: 0.38 + depth * 1.55 + (Math.random() < 0.045 ? rand(0.6, 1.2) : 0),
        vx: rand(-4, 4) + 1.5 + depth * 2.5,
        vy: 4 + depth * 28,
        base: 0.28 + depth * 0.58,
        phase: rand(0, TAU),
        twinkle: rand(0.55, 2.3),
        glow: GLOWS[ci],
        rgb: PALETTE[ci],
        flare: depth > 0.82 && Math.random() < 0.58,
        hero: depth > 0.955 && Math.random() < 0.3
      };
    }
  }

  function drawNebula(now, animate) {
    const t = animate ? now * 0.001 : 0;
    const base = Math.max(W, H);
    ctx.globalCompositeOperation = 'lighter';
    for (const n of NEBULA) {
      const pulse = animate ? 1 + 0.075 * Math.sin(t * n.speed * 7 + n.phase) : 1;
      const size = base * n.size * pulse;
      const x = W * n.fx + (animate ? Math.sin(t * n.speed + n.phase) * W * 0.045 : 0) + pointer.x * 16;
      const y = H * n.fy + (animate ? Math.cos(t * n.speed * 0.82 + n.phase * 1.7) * H * 0.038 : 0) + pointer.y * 11;
      ctx.globalAlpha = n.alpha * (animate ? 0.78 + 0.22 * Math.sin(t * n.speed * 2.4 + n.phase) : 1);
      ctx.drawImage(CLOUDS[n.cloud], x - size / 2, y - size / 2, size, size);
    }
    ctx.globalAlpha = 1;
  }

  function drawStars(now, animate) {
    const t = now * 0.001;
    ctx.globalCompositeOperation = 'lighter';
    for (const s of stars) {
      let alpha = s.base;
      if (animate) alpha *= 0.58 + 0.42 * Math.sin(t * s.twinkle + s.phase);
      if (alpha < 0.025) continue;

      const x = s.x + pointer.x * s.d * 11;
      const y = s.y + pointer.y * s.d * 8;
      const size = s.r * (s.hero ? 13 : 8.4) + (s.hero ? 5 : 0);
      ctx.globalAlpha = Math.min(1, alpha);
      ctx.drawImage(s.glow, x - size / 2, y - size / 2, size, size);

      // Crisp core on the near stars keeps the field from looking like blobs.
      if (s.r > 1.18 || s.hero) {
        ctx.globalAlpha = Math.min(1, alpha * 1.25);
        ctx.fillStyle = 'rgba(255,250,252,.96)';
        ctx.beginPath();
        ctx.arc(x, y, Math.max(0.34, s.r * 0.42), 0, TAU);
        ctx.fill();
      }

      // Four-point diffraction flare on the brightest near stars.
      if (s.flare) {
        const wave = animate ? 0.7 + 0.3 * Math.sin(t * 1.15 * s.twinkle + s.phase) : 0.85;
        const arm = s.r * (5.4 + 2.2 * wave);
        ctx.globalAlpha = Math.min(1, alpha * (s.hero ? 0.5 : 0.3));
        ctx.strokeStyle = 'rgba(' + s.rgb + ',.95)';
        ctx.lineWidth = Math.max(0.45, s.r * 0.3);
        ctx.lineCap = 'round';
        ctx.beginPath();
        ctx.moveTo(x - arm, y);
        ctx.lineTo(x + arm, y);
        ctx.moveTo(x, y - arm);
        ctx.lineTo(x, y + arm);
        ctx.stroke();
      }
    }
    ctx.globalAlpha = 1;
  }

  function spawnMeteor(big) {
    if (big) {
      let bigCount = 0;
      for (const m of meteors) if (m.big) bigCount++;
      if (bigCount >= 3) return;
    } else if (meteors.length >= 12) {
      return;
    }
    const dir = Math.random() < 0.5 ? -1 : 1;
    const angle = rand(0.36, 0.68);
    const speed = big ? rand(520, 880) : rand(330, 520);
    meteors.push({
      x: rand(W * 0.04, W * 0.96),
      y: rand(-190, -25),
      vx: Math.sin(angle) * speed * dir,
      vy: Math.cos(angle) * speed,
      len: big ? rand(120, 230) : rand(65, 120),
      w: big ? rand(1.2, 2.1) : rand(0.7, 1.2),
      big,
      alpha: big ? 1 : rand(0.55, 0.85),
      age: 0
    });
  }

  function addSpark(m) {
    if (sparks.length > 160) return;
    const mag = Math.hypot(m.vx, m.vy) || 1;
    const back = rand(0.05, 0.42) * m.len;
    sparks.push({
      x: m.x - (m.vx / mag) * back + rand(-2.5, 2.5),
      y: m.y - (m.vy / mag) * back + rand(-2.5, 2.5),
      vx: -(m.vx / mag) * rand(12, 46) + rand(-18, 18),
      vy: -(m.vy / mag) * rand(12, 46) + rand(-18, 18),
      age: 0,
      life: rand(0.32, 0.75),
      size: rand(0.55, 1.5)
    });
  }

  function update(dt) {
    for (const s of stars) {
      s.y += s.vy * dt;
      s.x += s.vx * dt;
      if (s.y > H + 14) {
        s.y = -14;
        s.x = Math.random() * W;
      }
      if (s.x < -14) s.x = W + 14;
      else if (s.x > W + 14) s.x = -14;
    }

    for (let i = meteors.length - 1; i >= 0; i--) {
      const m = meteors[i];
      m.age += dt;
      m.x += m.vx * dt;
      m.y += m.vy * dt;
      if (m.big && Math.random() < dt * 26) addSpark(m);
      if (m.age > 5 || m.y - m.len > H + 30 || m.x < -m.len * 2 || m.x > W + m.len * 2) {
        meteors.splice(i, 1);
      }
    }

    for (let i = sparks.length - 1; i >= 0; i--) {
      const p = sparks[i];
      p.age += dt;
      if (p.age >= p.life) {
        sparks.splice(i, 1);
        continue;
      }
      p.x += p.vx * dt;
      p.y += p.vy * dt;
      p.vx *= 1 - 1.4 * dt;
      p.vy = p.vy * (1 - 1.4 * dt) + 26 * dt;
    }
  }

  function drawSparks() {
    ctx.globalCompositeOperation = 'lighter';
    ctx.strokeStyle = 'rgba(255,176,190,.92)';
    ctx.lineCap = 'round';
    for (const p of sparks) {
      const a = 1 - p.age / p.life;
      ctx.globalAlpha = a * 0.85;
      ctx.lineWidth = p.size;
      ctx.beginPath();
      ctx.moveTo(p.x, p.y);
      ctx.lineTo(p.x - p.vx * 0.015, p.y - p.vy * 0.015);
      ctx.stroke();
    }
    ctx.globalAlpha = 1;
  }

  function drawMeteor(m) {
    const mag = Math.hypot(m.vx, m.vy) || 1;
    const ux = m.vx / mag;
    const uy = m.vy / mag;
    const tx = m.x - ux * m.len;
    const ty = m.y - uy * m.len;
    const trail = ctx.createLinearGradient(tx, ty, m.x, m.y);
    trail.addColorStop(0, 'rgba(255,36,72,0)');
    trail.addColorStop(0.42, 'rgba(255,46,82,' + (0.20 * m.alpha).toFixed(3) + ')');
    trail.addColorStop(0.78, 'rgba(255,122,146,' + (0.68 * m.alpha).toFixed(3) + ')');
    trail.addColorStop(1, 'rgba(255,246,250,' + m.alpha.toFixed(3) + ')');

    ctx.globalCompositeOperation = 'lighter';
    ctx.strokeStyle = trail;
    ctx.lineCap = 'round';

    // Wide soft bloom under the sharp core.
    ctx.globalAlpha = 0.24 * m.alpha;
    ctx.lineWidth = m.w * 4.2;
    ctx.beginPath();
    ctx.moveTo(tx, ty);
    ctx.lineTo(m.x, m.y);
    ctx.stroke();

    ctx.globalAlpha = m.alpha;
    ctx.lineWidth = m.w;
    ctx.beginPath();
    ctx.moveTo(tx, ty);
    ctx.lineTo(m.x, m.y);
    ctx.stroke();

    const head = (m.big ? 30 : 16) * m.w;
    ctx.globalAlpha = m.alpha * 0.92;
    ctx.drawImage(HEAD, m.x - head / 2, m.y - head / 2, head, head);
    ctx.globalAlpha = 1;
  }

  function paint(now, animate) {
    ctx.setTransform(DPR, 0, 0, DPR, 0, 0);
    ctx.clearRect(0, 0, W, H);
    drawNebula(now, animate);
    drawStars(now, animate);
    if (animate) {
      drawSparks();
      for (const m of meteors) drawMeteor(m);
    }
    ctx.globalCompositeOperation = 'source-over';
    ctx.globalAlpha = 1;
  }

  function schedule() {
    if (raf || !visible || motionOff() || !introGone) return;
    raf = requestAnimationFrame(step);
  }

  function step(now) {
    raf = 0;
    if (!visible || motionOff() || !introGone) return;
    const dims = viewport();
    if (dims[0] !== W || dims[1] !== H) {
      resize();
      schedule();
      return;
    }
    const dt = Math.min(0.05, last ? (now - last) / 1000 : 0.016);
    last = now;

    const k = 1 - Math.exp(-dt * 3.4);
    pointer.x += (pointer.tx - pointer.x) * k;
    pointer.y += (pointer.ty - pointer.y) * k;

    update(dt);

    if (!nextDrizzleAt) nextDrizzleAt = now + rand(160, 620);
    if (now >= nextDrizzleAt) {
      spawnMeteor(false);
      nextDrizzleAt = now + rand(420, 1250);
    }
    if (!nextMeteorAt) nextMeteorAt = now + rand(1600, 3600);
    if (now >= nextMeteorAt) {
      spawnMeteor(true);
      nextMeteorAt = now + rand(2400, 5600);
    }

    paint(now, true);
    schedule();
  }

  function sync() {
    const dims = viewport();
    if (dims[0] !== W || dims[1] !== H) resize();
    if (!visible || motionOff() || !introGone) {
      if (raf) {
        cancelAnimationFrame(raf);
        raf = 0;
      }
      last = 0;
      meteors.length = 0;
      sparks.length = 0;
      nextDrizzleAt = 0;
      nextMeteorAt = 0;
      paint(performance.now(), false);
      canvas.style.opacity = introGone ? '1' : '0';
      return;
    }
    canvas.style.opacity = '1';
    last = 0;
    schedule();
  }

  function resize() {
    DPR = Math.min(1.5, window.devicePixelRatio || 1);
    const dims = viewport();
    W = dims[0];
    H = dims[1];
    canvas.width = Math.round(W * DPR);
    canvas.height = Math.round(H * DPR);
    canvas.style.width = W + 'px';
    canvas.style.height = H + 'px';
    ctx.setTransform(DPR, 0, 0, DPR, 0, 0);
    buildStars();
    meteors.length = 0;
    sparks.length = 0;
    nextDrizzleAt = 0;
    nextMeteorAt = 0;
    pointer.x = pointer.tx;
    pointer.y = pointer.ty;
    paint(performance.now(), !motionOff() && introGone && visible);
  }

  window.addEventListener('resize', () => {
    clearTimeout(resizeTimer);
    resizeTimer = setTimeout(resize, 160);
  }, { passive: true });

  document.addEventListener('visibilitychange', () => {
    visible = !document.hidden;
    sync();
  });

  // Safe Mode / Settings > Animations can add .low-effects after this script starts.
  new MutationObserver(sync).observe(html, { attributes: true, attributeFilter: ['class'] });

  window.addEventListener('pointermove', (event) => {
    if (event.pointerType === 'touch') return;
    pointer.tx = (event.clientX / W) * 2 - 1;
    pointer.ty = (event.clientY / H) * 2 - 1;
  }, { passive: true });
  window.addEventListener('pointerleave', () => {
    pointer.tx = 0;
    pointer.ty = 0;
  }, { passive: true });

  // The intro owns the screen until it is removed; then the starfield fades in.
  if (!introGone) {
    const introObserver = new MutationObserver(() => {
      if (document.getElementById('intro-frame')) return;
      introGone = true;
      introObserver.disconnect();
      sync();
    });
    introObserver.observe(document.body, { childList: true });
  }

  resize();
  sync();
})();
