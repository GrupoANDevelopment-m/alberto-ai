// Alberto AI — lightweight native-canvas background.
// No CDN/import-map dependency: a failed third-party module must never prevent
// the application UI from booting, especially in restricted/offline deployments.
export class Background3D {
  constructor(canvas) {
    this.canvas = canvas;
    this.ctx = canvas?.getContext?.('2d') || null;
    this.particles = [];
    this.frame = 0;
    this.pointer = { x: 0, y: 0 };
    this.running = Boolean(this.ctx);
    if (!this.running) return;
    this.resize();
    const count = Math.min(90, Math.max(36, Math.floor((window.innerWidth * window.innerHeight) / 18000)));
    for (let i = 0; i < count; i++) {
      this.particles.push({
        x: Math.random() * this.width,
        y: Math.random() * this.height,
        vx: (Math.random() - 0.5) * 0.22,
        vy: (Math.random() - 0.5) * 0.22,
        r: Math.random() * 1.5 + 0.5,
      });
    }
    window.addEventListener('resize', () => this.resize(), { passive: true });
    window.addEventListener('pointermove', (event) => {
      this.pointer.x = event.clientX;
      this.pointer.y = event.clientY;
    }, { passive: true });
    this.animate();
  }

  resize() {
    this.width = window.innerWidth;
    this.height = window.innerHeight;
    const ratio = Math.min(window.devicePixelRatio || 1, 1.5);
    this.canvas.width = Math.floor(this.width * ratio);
    this.canvas.height = Math.floor(this.height * ratio);
    this.canvas.style.width = this.width + 'px';
    this.canvas.style.height = this.height + 'px';
    this.ctx.setTransform(ratio, 0, 0, ratio, 0, 0);
  }

  animate() {
    if (!this.running) return;
    this.frame = requestAnimationFrame(() => this.animate());
    const ctx = this.ctx;
    ctx.clearRect(0, 0, this.width, this.height);
    for (let i = 0; i < this.particles.length; i++) {
      const p = this.particles[i];
      p.x += p.vx;
      p.y += p.vy;
      if (p.x < 0 || p.x > this.width) p.vx *= -1;
      if (p.y < 0 || p.y > this.height) p.vy *= -1;
      const dx = p.x - this.pointer.x;
      const dy = p.y - this.pointer.y;
      const distance = Math.hypot(dx, dy);
      if (distance < 180) {
        ctx.beginPath();
        ctx.moveTo(p.x, p.y);
        ctx.lineTo(this.pointer.x, this.pointer.y);
        ctx.strokeStyle = `rgba(124,58,237,${(1 - distance / 180) * 0.12})`;
        ctx.lineWidth = 0.7;
        ctx.stroke();
      }
      for (let j = i + 1; j < this.particles.length; j++) {
        const q = this.particles[j];
        const d = Math.hypot(p.x - q.x, p.y - q.y);
        if (d < 105) {
          ctx.beginPath();
          ctx.moveTo(p.x, p.y);
          ctx.lineTo(q.x, q.y);
          ctx.strokeStyle = `rgba(103,232,249,${(1 - d / 105) * 0.12})`;
          ctx.lineWidth = 0.6;
          ctx.stroke();
        }
      }
      ctx.beginPath();
      ctx.arc(p.x, p.y, p.r, 0, Math.PI * 2);
      ctx.fillStyle = 'rgba(167,139,250,0.62)';
      ctx.fill();
    }
  }

  destroy() {
    this.running = false;
    if (this.frame) cancelAnimationFrame(this.frame);
  }
}
