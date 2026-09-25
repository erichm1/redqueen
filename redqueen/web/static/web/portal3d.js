/* The hellgate: a full-screen fire vortex drawn by a fragment shader (three.js). Embers rise, the vortex spirals into a black abyss,
 * and in the last moments the gate grows until it fills the screen. Purely decorative; portal.js handles the timing. */
import * as THREE from 'three';

const vertexShader = 'varying vec2 vUv; void main() { vUv = uv; gl_Position = vec4(position.xy, 0.0, 1.0); }';

const fragmentShader = `
precision highp float;
uniform float uTime; uniform float uZoom; uniform vec2 uRes;
varying vec2 vUv;
float hash(vec2 p) { p = fract(p * vec2(123.34, 456.21)); p += dot(p, p + 45.32); return fract(p.x * p.y); }
float noise(vec2 p) {
  vec2 i = floor(p), f = fract(p); f = f * f * (3.0 - 2.0 * f);
  return mix(mix(hash(i), hash(i + vec2(1, 0)), f.x), mix(hash(i + vec2(0, 1)), hash(i + vec2(1, 1)), f.x), f.y);
}
float fbm(vec2 p) {
  float v = 0.0, a = 0.5;
  for (int i = 0; i < 5; i++) { v += a * noise(p); p = mat2(1.6, 1.2, -1.2, 1.6) * p + 7.3; a *= 0.5; }
  return v;
}
vec3 embers(vec2 p, float t) {
  vec3 acc = vec3(0.0);
  for (int i = 0; i < 3; i++) {
    float fi = float(i);
    vec2 q = p * (7.0 + fi * 5.0);
    q.y -= t * (0.5 + fi * 0.25);
    q.x += sin(t * 0.7 + fi * 2.0 + q.y * 0.6) * 0.4;
    vec2 id = floor(q), f = fract(q) - 0.5;
    float h = hash(id + fi * 17.0);
    vec2 off = (vec2(hash(id * 1.3 + fi), hash(id * 2.1 + fi)) - 0.5) * 0.55;
    float d = length(f - off);
    float flick = 0.6 + 0.4 * sin(t * 6.0 + h * 40.0);
    acc += vec3(1.0, 0.45, 0.1) * smoothstep(0.09, 0.0, d) * step(0.72, h) * flick * (0.7 - fi * 0.15);
  }
  return acc;
}
void main() {
  float m = min(uRes.x, uRes.y);
  vec2 p = (vUv - vec2(0.5, 0.54)) * uRes / m;   // the gate's centre: 46% from the top, as in portal.css
  float R = 0.278 * (1.0 + uZoom * 7.0);
  float r = length(p), a = atan(p.y, p.x), t = uTime;

  vec3 col = vec3(0.02, 0.0, 0.01) + vec3(0.25, 0.02, 0.02) * pow(fbm(p * 2.5 + vec2(0.0, -t * 0.15)), 2.0) * exp(-r * 1.6);

  float swirl = a + 3.2 / (r + 0.10) - t * 1.5;
  vec2 q = vec2(cos(swirl), sin(swirl)) * r * 6.0;
  float n = fbm(q + fbm(q * 1.7 - t * 0.3) * 1.5 + t * 0.25);
  float inside = smoothstep(R, R - 0.015, r);
  float edge = smoothstep(0.0, R, r);
  vec3 fire = mix(vec3(0.03, 0.0, 0.0), vec3(0.6, 0.04, 0.02), smoothstep(0.2, 0.7, n));
  fire = mix(fire, vec3(1.0, 0.4, 0.05), smoothstep(0.55, 0.9, n) * edge);
  fire += vec3(1.0, 0.75, 0.35) * pow(edge, 3.0) * n * 0.9;
  fire *= 1.0 - 0.94 * pow(smoothstep(R * 0.62, 0.0, r), 1.3);   // the black abyss in the middle
  col = mix(col, fire, inside);

  float rim = exp(-pow((r - R) / 0.014, 2.0));
  col += vec3(1.0, 0.3, 0.06) * rim * (1.4 + 0.5 * sin(t * 9.0 + a * 6.0));
  col += vec3(0.8, 0.07, 0.02) * exp(-max(r - R, 0.0) * 4.5) * (0.5 + 0.5 * fbm(vec2(a * 2.5, t * 0.5) + r * 3.0)) * (1.0 - inside) * 0.6;
  col += embers(p, t) * exp(-r * 0.7);

  col *= 1.0 - 0.6 * smoothstep(0.5, 1.2, length(p));
  col = mix(col, vec3(1.0, 0.32, 0.06), smoothstep(0.55, 1.0, uZoom) * 0.85);   // the flood as the gate opens
  col = 1.0 - exp(-col * 1.25);
  gl_FragColor = vec4(col, 1.0);
}`;

const smooth = (x) => x * x * (3 - 2 * x);

/** Draw the gate into `canvas`. delay (ms) is when the page moves on: the gate swallows the screen in the last 0.9 s. */
export function startGate(canvas, { delay = 5000, reduced = false } = {}) {
  const renderer = new THREE.WebGLRenderer({ canvas, antialias: false, alpha: false });
  renderer.setPixelRatio(Math.min(window.devicePixelRatio || 1, 1));   // the shader is per-pixel heavy: one sample per CSS pixel is plenty
  const scene = new THREE.Scene();
  const camera = new THREE.OrthographicCamera(-1, 1, 1, -1, 0, 1);
  const material = new THREE.ShaderMaterial({
    uniforms: { uTime: { value: 0 }, uZoom: { value: 0 }, uRes: { value: new THREE.Vector2(1, 1) } },
    vertexShader, fragmentShader,
  });
  scene.add(new THREE.Mesh(new THREE.PlaneGeometry(2, 2), material));

  function resize() {
    const w = canvas.clientWidth || window.innerWidth, h = canvas.clientHeight || window.innerHeight;
    renderer.setSize(w, h, false);
    material.uniforms.uRes.value.set(w, h);
  }
  window.addEventListener('resize', resize);
  resize();

  const start = performance.now();
  let stopped = false;
  function draw(now) {
    const t = (now - start) / 1000;
    material.uniforms.uTime.value = reduced ? 1.5 : t;
    const zoomFrom = delay / 1000 - 0.9;
    material.uniforms.uZoom.value = reduced ? 0 : smooth(Math.min(Math.max((t - zoomFrom) / 0.9, 0), 1));
    renderer.render(scene, camera);
    if (!stopped && !reduced) requestAnimationFrame(draw);
  }
  requestAnimationFrame(draw);
  return { stop() { stopped = true; window.removeEventListener('resize', resize); renderer.dispose(); } };
}
