// Alberto AI — 3D background
// Subtle, performant: animated particle network + floating geometry

import * as THREE from 'three';

export class Background3D {
  constructor(canvas) {
    this.canvas = canvas;
    this.mouse = { x: 0, y: 0, target: { x: 0, y: 0 } };
    this.init();
    this.animate();
  }

  init() {
    const renderer = new THREE.WebGLRenderer({
      canvas: this.canvas,
      alpha: true,
      antialias: true,
    });
    renderer.setPixelRatio(Math.min(window.devicePixelRatio, 2));
    renderer.setSize(window.innerWidth, window.innerHeight);

    this.renderer = renderer;

    const scene = new THREE.Scene();
    scene.fog = new THREE.FogExp2(0x050510, 0.04);
    this.scene = scene;

    const camera = new THREE.PerspectiveCamera(60, window.innerWidth / window.innerHeight, 0.1, 1000);
    camera.position.z = 30;
    this.camera = camera;

    // Particle network
    this.particles = this.createParticleNetwork();
    scene.add(this.particles.mesh);

    // Floating geometry
    this.geometries = this.createFloatingGeometry();
    scene.add(this.geometries.group);

    // Lights
    const ambient = new THREE.AmbientLight(0x7c3aed, 0.4);
    scene.add(ambient);
    const point1 = new THREE.PointLight(0x7c3aed, 2, 60);
    point1.position.set(15, 15, 20);
    scene.add(point1);
    const point2 = new THREE.PointLight(0x06b6d4, 2, 60);
    point2.position.set(-15, -15, 15);
    scene.add(point2);

    this.lights = { point1, point2 };

    window.addEventListener('resize', () => this.onResize());
    window.addEventListener('mousemove', (e) => this.onMouseMove(e));
  }

  createParticleNetwork() {
    const count = 180;
    const positions = new Float32Array(count * 3);
    const colors = new Float32Array(count * 3);

    for (let i = 0; i < count; i++) {
      positions[i * 3 + 0] = (Math.random() - 0.5) * 60;
      positions[i * 3 + 1] = (Math.random() - 0.5) * 40;
      positions[i * 3 + 2] = (Math.random() - 0.5) * 30;

      const t = Math.random();
      // Gradient purple -> cyan
      colors[i * 3 + 0] = 0.486 + t * (0.024 - 0.486);
      colors[i * 3 + 1] = 0.227 + t * (0.714 - 0.227);
      colors[i * 3 + 2] = 0.929 + t * (0.831 - 0.929);
    }

    const geo = new THREE.BufferGeometry();
    geo.setAttribute('position', new THREE.BufferAttribute(positions, 3));
    geo.setAttribute('color', new THREE.BufferAttribute(colors, 3));

    const mat = new THREE.PointsMaterial({
      size: 0.15,
      vertexColors: true,
      transparent: true,
      opacity: 0.85,
      blending: THREE.AdditiveBlending,
    });

    return { mesh: new THREE.Points(geo, mat), count };
  }

  createFloatingGeometry() {
    const group = new THREE.Group();

    // Icosahedron wireframe
    const ico1 = new THREE.Mesh(
      new THREE.IcosahedronGeometry(4, 1),
      new THREE.MeshBasicMaterial({
        color: 0x7c3aed,
        wireframe: true,
        transparent: true,
        opacity: 0.25,
      })
    );
    ico1.position.set(15, 5, -10);
    group.add(ico1);

    // Octahedron wireframe
    const oct1 = new THREE.Mesh(
      new THREE.OctahedronGeometry(3, 0),
      new THREE.MeshBasicMaterial({
        color: 0x06b6d4,
        wireframe: true,
        transparent: true,
        opacity: 0.3,
      })
    );
    oct1.position.set(-12, -4, -8);
    group.add(oct1);

    // Torus knot
    const torus = new THREE.Mesh(
      new THREE.TorusKnotGeometry(2.5, 0.4, 64, 16),
      new THREE.MeshBasicMaterial({
        color: 0xa78bfa,
        wireframe: true,
        transparent: true,
        opacity: 0.2,
      })
    );
    torus.position.set(0, 0, -15);
    group.add(torus);

    return { group, items: [ico1, oct1, torus] };
  }

  onResize() {
    this.renderer.setSize(window.innerWidth, window.innerHeight);
    this.camera.aspect = window.innerWidth / window.innerHeight;
    this.camera.updateProjectionMatrix();
  }

  onMouseMove(e) {
    this.mouse.target.x = (e.clientX / window.innerWidth - 0.5) * 2;
    this.mouse.target.y = -(e.clientY / window.innerHeight - 0.5) * 2;
  }

  animate() {
    requestAnimationFrame(() => this.animate());

    // Smooth mouse follow
    this.mouse.x += (this.mouse.target.x - this.mouse.x) * 0.05;
    this.mouse.y += (this.mouse.target.y - this.mouse.y) * 0.05;

    const t = performance.now() * 0.001;

    // Camera parallax
    this.camera.position.x = this.mouse.x * 1.5;
    this.camera.position.y = this.mouse.y * 1.5;
    this.camera.lookAt(0, 0, 0);

    // Particle drift
    const positions = this.particles.mesh.geometry.attributes.position;
    const count = this.particles.count;
    for (let i = 0; i < count; i++) {
      const i3 = i * 3;
      positions.array[i3 + 1] += Math.sin(t + i * 0.1) * 0.005;
    }
    positions.needsUpdate = true;
    this.particles.mesh.rotation.y = t * 0.05;

    // Geometry rotation
    this.geometries.items.forEach((g, i) => {
      g.rotation.x = t * (0.1 + i * 0.05);
      g.rotation.y = t * (0.15 + i * 0.04);
      g.position.y += Math.sin(t * 0.5 + i) * 0.003;
    });

    // Lights follow camera slightly
    this.lights.point1.position.x = 15 + this.mouse.x * 4;
    this.lights.point2.position.y = -15 + this.mouse.y * 4;

    this.renderer.render(this.scene, this.camera);
  }
}