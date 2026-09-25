/* RedQueen: a real-time 3D devil-queen fighter (three.js, no external assets).
 *
 * Everything is procedural: tapered tubes (horns, wings, tail), lathe surfaces (dress), sculpted limbs and boots,
 * physically based materials (clear-coated horns, satin dress, gold metal), a studio environment for reflections,
 * soft shadows and a red rim light. The pose is driven by joint positions, so one function of time gives the idle
 * guard-stance bounce while she sweeps a glowing circle on the floor with her scepter; the same function renders still frames for the logo.
 *
 *   const queen = createQueen(canvas);
 *   queen.start();  queen.setPointer(x, y);  queen.renderAt(seconds);  queen.exportGLB()  // open in Blender
 */
import * as THREE from 'three';
import { RoomEnvironment } from 'three/addons/environments/RoomEnvironment.js';
import { canvasTexture, taperedTube } from './glkit.js';

const TAU = Math.PI * 2;
const V = (x, y, z) => new THREE.Vector3(x, y, z);
const lerp = (a, b, t) => a + (b - a) * t;
const smooth = (t) => t * t * (3 - 2 * t);

/* ------------------------------------------------------------------ geometry helpers */

/** Unit-length tapered cylinder along +Y from the origin; place() stretches it between two joints. */
function limbGeometry(rStart, rEnd) {
  const g = new THREE.CylinderGeometry(rEnd, rStart, 1, 24, 1);
  g.translate(0, 0.5, 0);
  return g;
}
const UP = V(0, 1, 0);
const _dir = new THREE.Vector3();
function place(mesh, a, b) {
  _dir.subVectors(b, a);
  const length = Math.max(_dir.length(), 1e-4);
  mesh.position.copy(a);
  mesh.quaternion.setFromUnitVectors(UP, _dir.multiplyScalar(1 / length));
  mesh.scale.set(1, length, 1);
}

function heartShape(size = 1) {
  const s = new THREE.Shape();
  s.moveTo(0, -0.9 * size);
  s.bezierCurveTo(-1.5 * size, 0.1 * size, -0.9 * size, 1.0 * size, 0, 0.35 * size);
  s.bezierCurveTo(0.9 * size, 1.0 * size, 1.5 * size, 0.1 * size, 0, -0.9 * size);
  return s;
}

/* ------------------------------------------------------------------ wing geometry and vein textures */

const WING_GEOMETRY = (() => {
  const P0 = V(0, 0, 0), E = V(0.4, 0.42, -0.04), W = V(0.8, 0.82, -0.08);
  const tips = [V(1.38, 0.6, -0.16), V(1.34, 0.06, -0.19), V(1.0, -0.3, -0.17)];
  const B = V(0.14, -0.44, -0.05);
  const scallop = (a, b) => V((a.x + b.x) / 2 * 0.86 + W.x * 0.14, (a.y + b.y) / 2 * 0.86 + W.y * 0.14, (a.z + b.z) / 2);
  const outline = [P0, W, tips[0], scallop(tips[0], tips[1]), tips[1], scallop(tips[1], tips[2]), tips[2], scallop(tips[2], B), B];
  return { P0, E, W, tips, B, outline, box: { minx: -0.02, maxx: 1.42, miny: -0.48, maxy: 0.86 } };
})();

function seeded(seed) {   // small deterministic random generator so the veins are the same on every load
  return () => { seed = (seed + 0x6D2B79F5) | 0; let t = Math.imul(seed ^ (seed >>> 15), 1 | seed); t = (t + Math.imul(t ^ (t >>> 7), 61 | t)) ^ t; return ((t ^ (t >>> 14)) >>> 0) / 4294967296; };
}

/** Colour, bump and emissive maps: leathery membrane, thick bone veins and a branching web of capillaries. */
function wingTextures() {
  const S = 1024, { P0, E, W, tips, B, outline, box } = WING_GEOMETRY;
  const cv = (v) => [((v.x - box.minx) / (box.maxx - box.minx)) * S, (1 - (v.y - box.miny) / (box.maxy - box.miny)) * S];
  const bones = [[P0, E, W], ...tips.map((t) => [W, W.clone().lerp(t, 0.5), t]), [P0, B], [E, tips[2]], [W, outline[3]], [W, outline[5]], [E, outline[7]]].map((b) => b.map(cv));
  const clipTo = (g) => { g.beginPath(); outline.map(cv).forEach(([x, y], i) => (i ? g.lineTo(x, y) : g.moveTo(x, y))); g.closePath(); g.clip(); };
  const draw = (fill, paint) => {
    const c = document.createElement('canvas'); c.width = c.height = S;
    const g = c.getContext('2d'); g.fillStyle = fill; g.fillRect(0, 0, S, S);
    g.save(); clipTo(g); paint(g); g.restore();
    const t = new THREE.CanvasTexture(c); t.anisotropy = 8; return t;
  };
  const branch = (g, rnd, x, y, angle, length, width, depth) => {
    const steps = 7; let px = x, py = y, a = angle;
    for (let i = 0; i < steps; i++) {
      a += (rnd() - 0.5) * 0.4;
      const nx = px + (Math.cos(a) * length) / steps, ny = py + (Math.sin(a) * length) / steps;
      g.lineWidth = Math.max(width * (1 - (i / steps) * 0.7), 0.6);
      g.beginPath(); g.moveTo(px, py); g.lineTo(nx, ny); g.stroke();
      if (depth > 0 && (i === 2 || i === 4) && rnd() < 0.85) branch(g, rnd, nx, ny, a + (rnd() < 0.5 ? -1 : 1) * (0.45 + rnd() * 0.5), length * 0.55, width * 0.6, depth - 1);
      px = nx; py = ny;
    }
  };
  const veins = (g, colour, scale, seed) => {
    const rnd = seeded(seed);
    g.strokeStyle = colour; g.lineCap = 'round';
    bones.forEach((bone, bi) => {
      const main = bi < 4;
      for (let s = 0; s < bone.length - 1; s++) {
        const [x0, y0] = bone[s], [x1, y1] = bone[s + 1];
        const len = Math.hypot(x1 - x0, y1 - y0), ang = Math.atan2(y1 - y0, x1 - x0);
        g.lineWidth = (main ? 13 : 6) * scale; g.beginPath(); g.moveTo(x0, y0); g.lineTo(x1, y1); g.stroke();
        for (let d = 34; d < len - 10; d += main ? 42 : 58) {
          const px = x0 + Math.cos(ang) * d, py = y0 + Math.sin(ang) * d;
          for (const sign of [-1, 1]) if (rnd() < 0.9) branch(g, rnd, px, py, ang + sign * (0.5 + rnd() * 0.35), 70 + rnd() * 90, (main ? 5.5 : 3.2) * scale, 2);
        }
      }
    });
  };
  const map = draw('#3b0714', (g) => {
    const base = g.createRadialGradient(...cv(W), 10, ...cv(W), 620);
    base.addColorStop(0, '#5a0d1e'); base.addColorStop(0.55, '#8c1830'); base.addColorStop(1, '#b02440');
    g.fillStyle = base; g.fillRect(0, 0, S, S);
    const rnd = seeded(3);
    for (let i = 0; i < 520; i++) {   // mottled, leathery patches
      const x = rnd() * S, y = rnd() * S, r = 10 + rnd() * 46;
      const blot = g.createRadialGradient(x, y, 0, x, y, r);
      const c = rnd() < 0.5 ? '255,90,110' : '40,0,10';
      blot.addColorStop(0, `rgba(${c},${0.05 + rnd() * 0.09})`); blot.addColorStop(1, `rgba(${c},0)`);
      g.fillStyle = blot; g.fillRect(x - r, y - r, r * 2, r * 2);
    }
    veins(g, 'rgba(255,120,130,0.22)', 1.7, 11);    // soft glow around the veins
    veins(g, 'rgba(38,3,12,0.85)', 1, 11);           // the veins themselves
  });
  const bump = draw('#5a5a5a', (g) => veins(g, '#ffffff', 1.05, 11));
  const glow = draw('#000000', (g) => veins(g, 'rgba(255,50,64,0.55)', 0.8, 11));
  map.colorSpace = THREE.SRGBColorSpace; glow.colorSpace = THREE.SRGBColorSpace;
  return { map, bump, glow };
}

/* ------------------------------------------------------------------ materials */

function makeMaterials() {
  // totally red eyes: red sclera, a brighter red iris and a black slit pupil
  const eyeMap = canvasTexture(512, 256, (g, w, h) => {
    g.fillStyle = '#e01a22'; g.fillRect(0, 0, w, h);
    const cx = w * 0.25, cy = h / 2;
    const iris = g.createRadialGradient(cx, cy - 10, 4, cx, cy, 54);
    iris.addColorStop(0, '#ff8a80'); iris.addColorStop(0.5, '#ff1f2b'); iris.addColorStop(1, '#8a0410');
    g.fillStyle = iris; g.beginPath(); g.arc(cx, cy, 52, 0, TAU); g.fill();
    g.fillStyle = '#1a0206'; g.beginPath(); g.ellipse(cx, cy, 9, 42, 0, 0, TAU); g.fill();   // slit pupil
    g.fillStyle = 'rgba(255,255,255,.9)'; g.beginPath(); g.arc(cx + 16, cy - 20, 8, 0, TAU); g.fill();
  });
  const eyeGlow = canvasTexture(512, 256, (g, w, h) => {
    g.fillStyle = '#7a0810'; g.fillRect(0, 0, w, h);
    const cx = w * 0.25, cy = h / 2;
    const iris = g.createRadialGradient(cx, cy, 2, cx, cy, 54);
    iris.addColorStop(0, '#ff6a5a'); iris.addColorStop(0.6, '#ff1a1a'); iris.addColorStop(1, '#6a0208');
    g.fillStyle = iris; g.beginPath(); g.arc(cx, cy, 52, 0, TAU); g.fill();
  });
  const wingMaps = wingTextures();
  return {
    skin: new THREE.MeshPhysicalMaterial({ color: 0x9fd2f0, roughness: 0.55, sheen: 0.9, sheenColor: new THREE.Color(0xdff2ff), sheenRoughness: 0.5, envMapIntensity: 0.55 }),
    dress: new THREE.MeshPhysicalMaterial({ color: 0xd4102c, roughness: 0.4, clearcoat: 0.5, clearcoatRoughness: 0.35, sheen: 0.4, sheenColor: new THREE.Color(0xff2a3c), envMapIntensity: 0.55, side: THREE.DoubleSide }),
    dressDark: new THREE.MeshPhysicalMaterial({ color: 0x7a0a20, roughness: 0.45, clearcoat: 0.4, clearcoatRoughness: 0.4, envMapIntensity: 0.5, side: THREE.DoubleSide }),
    leg: new THREE.MeshPhysicalMaterial({ color: 0x5c0b1e, roughness: 0.42, clearcoat: 0.3 }),
    boot: new THREE.MeshPhysicalMaterial({ color: 0x4a0a1c, roughness: 0.3, clearcoat: 0.8, clearcoatRoughness: 0.2 }),
    glove: new THREE.MeshPhysicalMaterial({ color: 0x7a0f24, roughness: 0.35, clearcoat: 0.7 }),
    gold: new THREE.MeshStandardMaterial({ color: 0xf2b73f, metalness: 1, roughness: 0.26 }),
    horn: new THREE.MeshPhysicalMaterial({ color: 0xb01a32, roughness: 0.34, clearcoat: 0.7, clearcoatRoughness: 0.18, envMapIntensity: 0.45 }),
    hornRidge: new THREE.MeshPhysicalMaterial({ color: 0x4a0a18, roughness: 0.45, envMapIntensity: 0.3 }),
    hair: new THREE.MeshPhysicalMaterial({ color: 0x2c1020, roughness: 0.45, sheen: 0.6, sheenColor: new THREE.Color(0x6a2a48), sheenRoughness: 0.5, envMapIntensity: 0.5 }),
    wing: new THREE.MeshPhysicalMaterial({ map: wingMaps.map, bumpMap: wingMaps.bump, bumpScale: 2.2, emissiveMap: wingMaps.glow, emissive: 0xffffff, emissiveIntensity: 0.55, roughness: 0.55, sheen: 0.5, sheenColor: new THREE.Color(0xff4a60), side: THREE.DoubleSide }),
    wingBone: new THREE.MeshPhysicalMaterial({ color: 0x3a0814, roughness: 0.4, clearcoat: 0.5 }),
    gem: new THREE.MeshPhysicalMaterial({ color: 0xff2a48, roughness: 0.08, transmission: 0, clearcoat: 1, emissive: 0xff1a3a, emissiveIntensity: 0.75 }),
    eye: new THREE.MeshStandardMaterial({ map: eyeMap, emissiveMap: eyeGlow, emissive: 0xffffff, emissiveIntensity: 1.35, roughness: 0.15 }),
    lip: new THREE.MeshPhysicalMaterial({ color: 0xc3132a, roughness: 0.3, clearcoat: 0.9 }),
    mouth: new THREE.MeshStandardMaterial({ color: 0x5a0714, roughness: 0.6 }),
    fang: new THREE.MeshPhysicalMaterial({ color: 0xffffff, roughness: 0.2, clearcoat: 1 }),
    liner: new THREE.MeshStandardMaterial({ color: 0x12050b, roughness: 0.5 }),
    blush: new THREE.MeshBasicMaterial({ color: 0xff7fb0, transparent: true, opacity: 0.3, depthWrite: false, polygonOffset: true, polygonOffsetFactor: -2 }),
  };
}

/* ------------------------------------------------------------------ the character */

/** The scepter's tip circles this spot on the floor (figure space): centre, radius, seconds per lap, hand height/orbit. */
const SWEEP = { cx: 0.28, cz: 0.66, radius: 0.38, lap: 3.0, handHeight: 1.0, handOrbit: 0.05 };
const LEAN = 0.34;   // the torso leans forward from the hips so the arm can reach the circle
const HEAD_R = 0.31, HEAD_SY = 1.07, HEAD_SZ = 0.96;
/** z of the head surface at (x, y) in head space, so face details sit on it. */
const headZ = (x, y) => HEAD_SZ * HEAD_R * Math.sqrt(Math.max(0, 1 - (x / HEAD_R) ** 2 - (y / (HEAD_R * HEAD_SY)) ** 2));

function buildHead(m) {
  const head = new THREE.Group();
  const skull = new THREE.Mesh(new THREE.SphereGeometry(HEAD_R, 64, 48), m.skin);
  skull.scale.set(1, HEAD_SY, HEAD_SZ);
  head.add(skull);
  // chin: a soft wedge so the face reads as a heart shape rather than an egg
  const chin = new THREE.Mesh(new THREE.SphereGeometry(0.12, 32, 24), m.skin);
  chin.scale.set(0.95, 0.85, 0.8); chin.position.set(0, -0.255, 0.1);
  head.add(chin);

  for (const s of [-1, 1]) {
    const x = s * 0.115, y = 0.01;
    const eye = new THREE.Mesh(new THREE.SphereGeometry(0.076, 48, 32), m.eye);
    eye.position.set(x, y, 0.215); eye.castShadow = false;
    head.add(eye);
    // upper lid line and outer flick
    const lid = new THREE.Mesh(new THREE.TorusGeometry(0.079, 0.0095, 10, 32, Math.PI * 1.05), m.liner);
    lid.position.set(x, y, 0.262); lid.rotation.z = -0.03;
    head.add(lid);
    const flick = new THREE.Mesh(new THREE.ConeGeometry(0.011, 0.055, 8), m.liner);
    flick.position.set(x + s * 0.078, y + 0.022, 0.26); flick.rotation.z = -s * 1.15;
    head.add(flick);
    // devil brow: low at the nose, sharply raised at the outer end
    const brow = taperedTube([V(s * 0.05, 0.112, headZ(0.05, 0.112) + 0.004), V(s * 0.115, 0.138, headZ(0.115, 0.138) + 0.004),
      V(s * 0.19, 0.178, headZ(0.19, 0.178) + 0.004)], 0.011, 0.006, { radial: 8, segments: 12 });
    head.add(new THREE.Mesh(brow.geometry, m.liner));
    // blush
    const blush = new THREE.Mesh(new THREE.CircleGeometry(0.05, 24), m.blush);
    const bx = s * 0.15, by = -0.075;
    blush.position.set(bx, by, headZ(bx, by) + 0.003);
    blush.lookAt(blush.position.clone().multiplyScalar(2).add(V(0, 0, 0.2)));
    head.add(blush);
    // pointed ear
    const ear = new THREE.Mesh(new THREE.ConeGeometry(0.062, 0.24, 16), m.skin);
    ear.position.set(s * 0.335, 0.045, -0.01); ear.rotation.z = -s * (Math.PI / 2 - 0.3);
    ear.rotation.y = s * 0.25;
    head.add(ear);
    const inner = new THREE.Mesh(new THREE.ConeGeometry(0.03, 0.15, 12), m.dressDark);
    inner.position.set(s * 0.325, 0.045, 0.012); inner.rotation.copy(ear.rotation);
    head.add(inner);
  }

  const nose = new THREE.Mesh(new THREE.SphereGeometry(0.022, 16, 12), m.skin);
  nose.scale.set(0.9, 1.1, 1.3); nose.position.set(0, -0.045, headZ(0, -0.045) + 0.008);
  head.add(nose);

  // smirk: open mouth, lips, one fang
  const mouth = new THREE.Mesh(new THREE.SphereGeometry(0.05, 24, 16), m.mouth);
  mouth.scale.set(1.35, 0.55, 0.3); mouth.position.set(0.012, -0.135, headZ(0.012, -0.135) + 0.002);
  mouth.rotation.z = 0.12;
  head.add(mouth);
  const lipPts = [V(-0.075, -0.125, headZ(-0.075, -0.125) + 0.006), V(-0.02, -0.148, headZ(-0.02, -0.148) + 0.008),
    V(0.045, -0.142, headZ(0.045, -0.142) + 0.008), V(0.1, -0.108, headZ(0.1, -0.108) + 0.006)];
  head.add(new THREE.Mesh(taperedTube(lipPts, 0.008, 0.006, { radial: 8, segments: 16 }).geometry, m.lip));
  const fang = new THREE.Mesh(new THREE.ConeGeometry(0.011, 0.038, 10), m.fang);
  fang.position.set(0.05, -0.155, headZ(0.05, -0.155) + 0.006); fang.rotation.x = Math.PI;
  head.add(fang);
  return head;
}

function buildHair(m) {
  const hair = new THREE.Group();
  const cap = new THREE.Mesh(new THREE.SphereGeometry(HEAD_R * 1.07, 56, 36, 0, TAU, 0, 1.85), m.hair);
  cap.scale.set(1.02, 1.1, 1.02); cap.rotation.x = -0.52; cap.position.set(0, 0.012, -0.02);
  hair.add(cap);
  // fringe locks over the forehead
  const fringe = [[-0.19, 0.2, 0.2, -0.5], [-0.1, 0.235, 0.24, -0.2], [0, 0.245, 0.25, 0.05], [0.1, 0.235, 0.24, 0.25], [0.19, 0.2, 0.2, 0.55]];
  for (const [x, y, z, tilt] of fringe) {
    const lock = new THREE.Mesh(new THREE.ConeGeometry(0.06, 0.2, 14), m.hair);
    lock.position.set(x, y - 0.02, z * 0.98); lock.rotation.z = tilt; lock.rotation.x = 0.35;
    hair.add(lock);
  }
  // long back hair and front locks
  const back = new THREE.Mesh(new THREE.SphereGeometry(0.3, 40, 32), m.hair);
  back.scale.set(1.22, 1.85, 0.55); back.position.set(0, -0.42, -0.22);
  hair.add(back);
  for (const s of [-1, 1]) {
    const lock = taperedTube([V(s * 0.3, 0.06, 0.06), V(s * 0.345, -0.14, 0.11), V(s * 0.33, -0.38, 0.13), V(s * 0.3, -0.62, 0.1)], 0.052, 0.012);
    hair.add(new THREE.Mesh(lock.geometry, m.hair));
  }
  return hair;
}

function buildHorns(m) {
  const horns = new THREE.Group();
  const centre = [V(0.14, 0.24, 0.05), V(0.25, 0.32, 0.03), V(0.37, 0.45, 0.0), V(0.41, 0.6, -0.04), V(0.37, 0.75, -0.07)];
  for (const s of [-1, 1]) {
    const pts = centre.map((p) => V(p.x * s, p.y, p.z));
    const { geometry, curve } = taperedTube(pts, 0.082, 0.0, { radial: 24, segments: 64 });
    const horn = new THREE.Mesh(geometry, m.horn);
    horns.add(horn);
    for (const t of [0.2, 0.36, 0.52, 0.68]) {   // ridges
      const ring = new THREE.Mesh(new THREE.TorusGeometry(lerp(0.082, 0, Math.pow(t, 0.85)) * 1.02, 0.008, 8, 24), m.hornRidge);
      ring.position.copy(curve.getPointAt(t));
      ring.quaternion.setFromUnitVectors(V(0, 0, 1), curve.getTangentAt(t));
      horns.add(ring);
    }
  }
  // gold circlet with a gem, following the forehead
  const band = [];
  for (let a = -74; a <= 74; a += 12) {
    const r = (a * Math.PI) / 180;
    const x = Math.sin(r) * HEAD_R * 1.005, z = Math.cos(r) * HEAD_R * HEAD_SZ * 1.005;
    band.push(V(x, 0.185 - 0.045 * (1 - Math.cos(r)) * 0.0 + 0.02 * Math.cos(r), z));
  }
  horns.add(new THREE.Mesh(taperedTube(band, 0.0125, 0.0125, { radial: 10, segments: 40 }).geometry, m.gold));
  const gem = new THREE.Mesh(new THREE.OctahedronGeometry(0.05), m.gem);
  gem.scale.set(0.8, 1.4, 0.7); gem.position.set(0, 0.165, HEAD_R * HEAD_SZ * 1.03);
  horns.add(gem);
  return horns;
}

function buildWing(m, side) {
  const wing = new THREE.Group();
  const { P0, E, W, tips, B, outline, box } = WING_GEOMETRY;
  const centroid = outline.reduce((sum, p) => sum.add(p), V(0, 0, 0)).multiplyScalar(1 / outline.length);
  const verts = [centroid, ...outline], idx = [];
  for (let i = 1; i <= outline.length; i++) idx.push(0, i, i === outline.length ? 1 : i + 1);
  const g = new THREE.BufferGeometry();
  g.setAttribute('position', new THREE.Float32BufferAttribute(verts.flatMap((v) => [v.x, v.y, v.z]), 3));
  // planar UVs so the vein texture lines up with the bones
  g.setAttribute('uv', new THREE.Float32BufferAttribute(verts.flatMap((v) => [(v.x - box.minx) / (box.maxx - box.minx), (v.y - box.miny) / (box.maxy - box.miny)]), 2));
  g.setIndex(idx); g.computeVertexNormals();
  wing.add(new THREE.Mesh(g, m.wing));
  wing.add(new THREE.Mesh(taperedTube([P0, E, W], 0.036, 0.02, { radial: 12, segments: 20 }).geometry, m.wingBone));
  for (const t of tips) {
    const mid = W.clone().lerp(t, 0.5).add(V(0, 0.02, 0));
    wing.add(new THREE.Mesh(taperedTube([W, mid, t], 0.019, 0.004, { radial: 8, segments: 14 }).geometry, m.wingBone));
    const claw = new THREE.Mesh(new THREE.ConeGeometry(0.012, 0.06, 8), m.wingBone);
    claw.position.copy(t); claw.quaternion.setFromUnitVectors(UP, t.clone().sub(mid).normalize());
    wing.add(claw);
  }
  // secondary struts from the arm bone into the membrane, raised slightly like real wing ribs
  for (const [from, to] of [[0.3, B], [0.55, tips[2]], [0.75, tips[1]]]) {
    const start = P0.clone().lerp(E, from > 0.5 ? 1 : from * 2).lerp(W, from > 0.5 ? (from - 0.5) * 2 : 0);
    wing.add(new THREE.Mesh(taperedTube([start, start.clone().lerp(to, 0.5).add(V(0, 0, 0.012)), to.clone().lerp(start, 0.25)], 0.012, 0.004, { radial: 6, segments: 12 }).geometry, m.wingBone));
  }
  const claw = new THREE.Mesh(new THREE.ConeGeometry(0.03, 0.12, 10), m.wingBone);
  claw.position.copy(W).add(V(0.02, 0.06, 0)); claw.rotation.z = -0.4;
  wing.add(claw);
  wing.scale.set(side * 1.12, 1.12, 1.12);   // mirror for the left wing
  return wing;
}

function buildTail(m) {
  const tail = new THREE.Group();
  const pts = [V(0, 0.9, -0.16), V(0.16, 0.78, -0.42), V(0.55, 0.7, -0.55), V(0.86, 0.9, -0.42), V(0.92, 1.12, -0.3)];
  const { geometry, curve } = taperedTube(pts, 0.04, 0.014, { radial: 14, segments: 56 });
  tail.add(new THREE.Mesh(geometry, m.leg));
  const spade = new THREE.Mesh(new THREE.ExtrudeGeometry(heartShape(0.075), { depth: 0.024, bevelEnabled: true, bevelSize: 0.008, bevelThickness: 0.008, bevelSegments: 3 }), m.gem);
  spade.position.copy(curve.getPointAt(1)).add(V(0, 0.07, 0)); spade.rotation.z = Math.PI;
  tail.add(spade);
  return tail;
}

/** The dress: a fitted bodice, an open battle skirt with slits, and a short cape. Ellipse cross-sections. */
function buildDress(m) {
  const dress = new THREE.Group();
  const torso = new THREE.Group();
  const bodice = new THREE.LatheGeometry([[0.001, 0.86], [0.165, 0.88], [0.185, 0.97], [0.205, 1.12], [0.226, 1.23], [0.205, 1.31], [0.16, 1.335]].map(([r, y]) => new THREE.Vector2(r, y)), 56);
  const bodyMesh = new THREE.Mesh(bodice, m.dress); bodyMesh.scale.set(1.08, 1, 0.7);
  torso.add(bodyMesh);
  const chest = new THREE.Mesh(new THREE.SphereGeometry(0.2, 40, 24), m.skin);
  chest.scale.set(1.12, 0.42, 0.66); chest.position.set(0, 1.335, 0.005);
  torso.add(chest);
  const neckline = taperedTube([V(-0.235, 1.31, 0.06), V(-0.1, 1.27, 0.15), V(0, 1.245, 0.16), V(0.1, 1.27, 0.15), V(0.235, 1.31, 0.06)], 0.011, 0.011, { radial: 8, segments: 24 });
  torso.add(new THREE.Mesh(neckline.geometry, m.gold));

  const skirtProfile = (top, hem, flare) => [[top, 0.9], [top + (flare - top) * 0.35, (0.9 + hem) / 2 + (0.9 - hem) * 0.18], [flare, hem]].map(([r, y]) => new THREE.Vector2(r, y));
  const sector = (profile, centre, span, material, segs = 36) => {
    const mesh = new THREE.Mesh(new THREE.LatheGeometry(profile, segs, centre - span / 2, span), material);
    mesh.scale.set(1.12, 1, 0.72);
    return mesh;
  };
  const front = sector(skirtProfile(0.185, 0.36, 0.3), 0, 0.72, m.dressDark);
  const flapL = sector(skirtProfile(0.19, 0.58, 0.34), -1.45, 0.55, m.dress);
  const flapR = sector(skirtProfile(0.19, 0.58, 0.34), 1.45, 0.55, m.dress);
  const cape = sector(skirtProfile(0.19, 0.34, 0.46), Math.PI, 2.0, m.dressDark, 48);
  dress.add(front, flapL, flapR, cape);
  const hem = (centre, span, r, y, sx = 1.12, sz = 0.72) => {
    const pts = [];
    for (let i = 0; i <= 20; i++) { const a = centre - span / 2 + (span * i) / 20; pts.push(V(Math.sin(a) * r * sx, y, Math.cos(a) * r * sz)); }
    return new THREE.Mesh(taperedTube(pts, 0.011, 0.011, { radial: 8, segments: 40 }).geometry, m.gold);
  };
  dress.add(hem(0, 0.72, 0.3, 0.36), hem(-1.45, 0.55, 0.34, 0.58), hem(1.45, 0.55, 0.34, 0.58), hem(Math.PI, 2.0, 0.46, 0.34));

  const belt = new THREE.Mesh(new THREE.TorusGeometry(0.19, 0.03, 14, 48), m.gold);
  belt.rotation.x = Math.PI / 2; belt.scale.set(1.08, 0.7, 1); belt.position.y = 0.9;
  torso.add(belt);
  const heart = new THREE.Mesh(new THREE.ExtrudeGeometry(heartShape(0.05), { depth: 0.02, bevelEnabled: true, bevelSize: 0.006, bevelThickness: 0.006, bevelSegments: 3 }), m.gem);
  heart.position.set(0, 0.9, 0.14);
  torso.add(heart);
  for (const s of [-1, 1]) {    // shoulder puffs
    const puff = new THREE.Mesh(new THREE.SphereGeometry(0.088, 32, 24), m.dress);
    puff.position.set(s * 0.245, 1.33, 0); puff.scale.set(1, 0.92, 1);
    torso.add(puff);
  }
  return { dress, torso, front, flapL, flapR, cape };
}

/** Build the character (the same one as the logo) into `scene` and return what a host needs to drive her:
 *   root/figure (place and turn her), pose(t) (a pure function of time, plus the eyelid state), setEyesClosed(),
 *   and the optional arena floor/ring/disc (arena: false leaves them out, for a host that has its own floor).
 *  The host provides the renderer (with localClippingEnabled = true, used by the eyelids) and the lights. */
export function buildQueen(scene, { arena = true } = {}) {
  const m = makeMaterials();
  const root = new THREE.Group();     // yaw/pitch follow the pointer
  const figure = new THREE.Group();   // faces the camera, turned a little for a 3/4 fighter look
  figure.rotation.y = 0.58;
  root.add(figure);
  scene.add(root);

  // arena floor: shadow catcher + glowing ring (the portal room has its own floor, so it can leave these out)
  let floor = null, ring = null, disc = null;
  if (arena) {
    floor = new THREE.Mesh(new THREE.CircleGeometry(2.6, 64), new THREE.ShadowMaterial({ opacity: 0.5 }));
    floor.rotation.x = -Math.PI / 2; floor.receiveShadow = true; root.add(floor);
    ring = new THREE.Mesh(new THREE.RingGeometry(1.3, 1.37, 96), new THREE.MeshBasicMaterial({ color: 0xff2a48, transparent: true, opacity: 0.55, blending: THREE.AdditiveBlending, depthWrite: false }));
    ring.rotation.x = -Math.PI / 2; ring.position.y = 0.004; root.add(ring);
    disc = new THREE.Mesh(new THREE.CircleGeometry(1.3, 64), new THREE.MeshBasicMaterial({ color: 0x8a1228, transparent: true, opacity: 0.16, depthWrite: false }));
    disc.rotation.x = -Math.PI / 2; disc.position.y = 0.002; root.add(disc);
  }

  // ---- body parts
  const upper = new THREE.Group();     // torso + head + wings: bobs and twists
  const lower = new THREE.Group();     // pelvis-level dress and tail
  figure.add(upper, lower);

  const { dress, torso, front, flapL, flapR, cape } = buildDress(m);
  lower.add(dress);
  upper.add(torso);
  const tail = buildTail(m); lower.add(tail);
  const neck = new THREE.Mesh(new THREE.CylinderGeometry(0.072, 0.086, 0.2, 24), m.skin);
  neck.position.y = 1.44; upper.add(neck);

  const headGroup = new THREE.Group();
  headGroup.position.set(0, 1.7, 0.02);
  const head = buildHead(m), hair = buildHair(m), horns = buildHorns(m);

  // eyelids: skin-coloured shells over the eyes. A clipping plane reveals them from the top, so they slide down like real
  // lids. Closed (privacy while a password is typed) shows a lash line; an idle blink uses the same lids.
  const LID_R = 0.086, EYE_Y = 0.01, EYE_Z = 0.215;
  const lidPlane = new THREE.Plane(V(0, 1, 0), 0);
  const lidMaterial = m.skin.clone(); lidMaterial.clippingPlanes = [lidPlane]; lidMaterial.side = THREE.DoubleSide;
  const lashMaterial = m.liner.clone(); lashMaterial.transparent = true; lashMaterial.opacity = 0;
  const lids = [-1, 1].map((sd) => {
    const lid = new THREE.Mesh(new THREE.SphereGeometry(LID_R, 40, 28, 0, Math.PI, 0, Math.PI), lidMaterial);
    lid.position.set(sd * 0.115, EYE_Y, EYE_Z); lid.castShadow = false; head.add(lid);
    const lash = new THREE.Mesh(new THREE.TorusGeometry(0.066, 0.0085, 8, 28, Math.PI), lashMaterial);   // the curved line of a closed eye
    lash.rotation.z = Math.PI; lash.position.set(sd * 0.115, EYE_Y - 0.004, EYE_Z + LID_R + 0.003); lash.visible = false; head.add(lash);
    return { lid, lash };
  });
  let closedAmount = 0, closedTarget = 0, lastPoseTime = null;
  const eyeWorld = V();
  headGroup.add(head, hair, horns);
  upper.add(headGroup);

  const wings = [buildWing(m, 1), buildWing(m, -1)];
  wings[0].position.set(0.09, 1.26, -0.17); wings[1].position.set(-0.09, 1.26, -0.17);
  wings.forEach((w) => upper.add(w));

  // limbs are stretched between joint positions every frame
  const limbs = [];
  const joint = (radius, material) => { const j = new THREE.Mesh(new THREE.SphereGeometry(radius, 24, 18), material); return j; };
  const addLimb = (rA, rB, material, from, to) => {
    const mesh = new THREE.Mesh(limbGeometry(rA, rB), material);
    limbs.push({ mesh, from, to });
    return mesh;
  };
  const J = {};   // joint name -> Vector3 (rewritten by pose())
  ['hipL', 'kneeL', 'ankleL', 'hipR', 'kneeR', 'ankleR', 'shL', 'elL', 'fiL', 'shR', 'elR', 'fiR'].forEach((k) => { J[k] = V(); });
  const legs = new THREE.Group(), arms = new THREE.Group();
  figure.add(legs, arms);
  const add = (group, ...meshes) => meshes.forEach((x) => group.add(x));

  const kneePads = [], gloves = [], bracers = [], boots = [];
  for (const s of ['L', 'R']) {
    add(legs, addLimb(0.092, 0.072, m.leg, 'hip' + s, 'knee' + s), addLimb(0.074, 0.056, m.leg, 'knee' + s, 'ankle' + s));
    const knee = joint(0.082, m.leg); legs.add(knee);
    const pad = new THREE.Mesh(new THREE.SphereGeometry(0.086, 28, 20), m.boot); pad.scale.set(1, 1.1, 0.55);
    const padRim = new THREE.Mesh(new THREE.TorusGeometry(0.078, 0.011, 10, 32), m.gold);
    legs.add(pad, padRim); kneePads.push({ knee, pad, padRim, s });
    const boot = new THREE.Group();
    const foot = new THREE.Mesh(new THREE.CapsuleGeometry(0.066, 0.17, 10, 20), m.boot); foot.rotation.x = Math.PI / 2; foot.position.set(0, 0.066, 0.075); foot.scale.set(1.05, 1, 0.9);
    const shaft = new THREE.Mesh(new THREE.CylinderGeometry(0.062, 0.078, 0.17, 24), m.boot); shaft.position.y = 0.17;
    const cuff = new THREE.Mesh(new THREE.CylinderGeometry(0.084, 0.084, 0.05, 28), m.gold); cuff.position.y = 0.265;
    const heel = new THREE.Mesh(new THREE.BoxGeometry(0.11, 0.03, 0.09), m.leg); heel.position.set(0, 0.018, -0.03);
    boot.add(foot, shaft, cuff, heel); legs.add(boot); boots.push({ boot, s });
  }
  for (const s of ['L', 'R']) {
    arms.add(addLimb(0.064, 0.053, m.skin, 'sh' + s, 'el' + s), addLimb(0.054, 0.046, m.skin, 'el' + s, 'fi' + s));
    const elbow = joint(0.055, m.skin); arms.add(elbow);
    const glove = new THREE.Mesh(new THREE.SphereGeometry(0.085, 28, 22), m.glove);
    const knuckle = new THREE.Mesh(new THREE.TorusGeometry(0.076, 0.012, 10, 32), m.gold);
    arms.add(glove, knuckle);
    const bracer = new THREE.Mesh(limbGeometry(0.066, 0.06), m.gold); arms.add(bracer);
    gloves.push({ glove, knuckle, s }); bracers.push({ bracer, s, elbow });
  }

  // the scepter: a gold staff with a heart gem and trident head, held in the lead hand; its tip drags a glowing circle
  const STAFF_TO_HAND = 1.05, STAFF_ABOVE_HAND = 0.4, STAFF_LEN = STAFF_TO_HAND + STAFF_ABOVE_HAND;
  const staff = new THREE.Group();
  const shaft = new THREE.Mesh(new THREE.CylinderGeometry(0.02, 0.026, STAFF_LEN, 20), m.gold); shaft.position.y = STAFF_LEN / 2; staff.add(shaft);
  for (const y of [0.35, STAFF_TO_HAND - 0.12, STAFF_TO_HAND + 0.12]) {
    const band = new THREE.Mesh(new THREE.TorusGeometry(0.03, 0.009, 8, 20), m.gem); band.rotation.x = Math.PI / 2; band.position.y = y; staff.add(band);
  }
  const spike = new THREE.Mesh(new THREE.ConeGeometry(0.03, 0.09, 16), m.gem); spike.rotation.x = Math.PI; spike.position.y = 0.0; staff.add(spike);
  const staffGem = new THREE.Mesh(new THREE.ExtrudeGeometry(heartShape(0.09), { depth: 0.04, bevelEnabled: true, bevelSize: 0.012, bevelThickness: 0.012, bevelSegments: 4 }), m.gem);
  staffGem.position.set(0, STAFF_LEN + 0.08, -0.02); staff.add(staffGem);
  for (const sd of [-1, 1]) {
    const prong = taperedTube([V(0, STAFF_LEN - 0.02, 0), V(sd * 0.09, STAFF_LEN + 0.03, 0), V(sd * 0.1, STAFF_LEN + 0.14, 0)], 0.016, 0.005, { radial: 10, segments: 16 });
    staff.add(new THREE.Mesh(prong.geometry, m.gold));
  }
  figure.add(staff);

  const TRAIL_POINTS = 140, TRAIL_SECONDS = 2.7, TRAIL_WIDTH = 0.075;
  const trailGeometry = new THREE.BufferGeometry();
  trailGeometry.setAttribute('position', new THREE.BufferAttribute(new Float32Array(TRAIL_POINTS * 2 * 3), 3));
  trailGeometry.setAttribute('color', new THREE.BufferAttribute(new Float32Array(TRAIL_POINTS * 2 * 3), 3));
  const triangles = [];
  for (let i = 0; i < TRAIL_POINTS - 1; i++) { const a = i * 2; triangles.push(a, a + 1, a + 2, a + 1, a + 3, a + 2); }
  trailGeometry.setIndex(triangles);
  const trail = new THREE.Mesh(trailGeometry, new THREE.MeshBasicMaterial({ vertexColors: true, blending: THREE.AdditiveBlending, transparent: true, depthWrite: false, side: THREE.DoubleSide }));
  trail.frustumCulled = false; figure.add(trail);
  const guide = new THREE.Mesh(new THREE.RingGeometry(SWEEP.radius - 0.008, SWEEP.radius + 0.008, 128), new THREE.MeshBasicMaterial({ color: 0xff2a48, transparent: true, opacity: 0.3, blending: THREE.AdditiveBlending, depthWrite: false }));
  guide.rotation.x = -Math.PI / 2; guide.position.set(SWEEP.cx, 0.004, SWEEP.cz); figure.add(guide);
  // "RQ" in the wordmark's font, written in blood red inside the circle: a wedge follows the scepter's tip around the lap
  const RUNE_SIZE = 512;
  const runeCanvas = document.createElement('canvas'); runeCanvas.width = runeCanvas.height = RUNE_SIZE;
  const runeTexture = new THREE.CanvasTexture(runeCanvas); runeTexture.colorSpace = THREE.SRGBColorSpace; runeTexture.anisotropy = 8;
  const runeSpan = (SWEEP.radius + 0.03) * 2;
  const runePlane = new THREE.Mesh(new THREE.PlaneGeometry(runeSpan, runeSpan), new THREE.MeshBasicMaterial({ map: runeTexture, transparent: true, depthWrite: false }));
  runePlane.rotation.x = -Math.PI / 2; runePlane.position.set(SWEEP.cx, 0.006, SWEEP.cz); runePlane.renderOrder = 2;
  figure.add(runePlane);
  const RUNE_FONT = '700 270px system-ui, -apple-system, "Segoe UI", Roboto, "Helvetica Neue", Arial, sans-serif';   // same stack as the RED QUEEN wordmark
  function paintRunes(progress) {
    const g = runeCanvas.getContext('2d'), c = RUNE_SIZE / 2;
    g.clearRect(0, 0, RUNE_SIZE, RUNE_SIZE);
    const fade = progress < 0.9 ? 1 : Math.max((1 - progress) / 0.1, 0);
    if (fade <= 0 || progress <= 0) return;
    g.save();
    g.globalAlpha = fade;
    g.beginPath(); g.moveTo(c, c); g.arc(c, c, c * 1.5, 0, TAU * progress); g.closePath(); g.clip();   // the tip's angle is the canvas angle
    g.translate(c, c); g.rotate(figure.rotation.y);                                                    // keep the letters upright for the camera
    g.font = RUNE_FONT; g.textBaseline = 'middle'; g.textAlign = 'left';
    const gap = 34, wR = g.measureText('R').width, wQ = g.measureText('Q').width, x0 = -(wR + gap + wQ) / 2;
    for (const [blur, colour, width] of [[42, '#ff1010', 0], [16, '#c40a12', 0], [0, '#8b0206', 0], [0, '#3a0004', 5]]) {
      g.shadowColor = '#ff2020'; g.shadowBlur = blur;
      if (width) { g.lineWidth = width; g.strokeStyle = colour; g.strokeText('R', x0, 6); g.strokeText('Q', x0 + wR + gap, 6); }
      else { g.fillStyle = colour; g.fillText('R', x0, 6); g.fillText('Q', x0 + wR + gap, 6); }
    }
    g.restore();
    runeTexture.needsUpdate = true;
  }

  const tipGlowTexture = canvasTexture(128, 128, (g, w, h) => {
    const r = g.createRadialGradient(w / 2, h / 2, 0, w / 2, h / 2, w / 2);
    r.addColorStop(0, 'rgba(255,255,255,1)'); r.addColorStop(0.25, 'rgba(255,90,110,.8)'); r.addColorStop(1, 'rgba(255,30,60,0)');
    g.fillStyle = r; g.fillRect(0, 0, w, h);
  });
  const tipGlow = new THREE.Sprite(new THREE.SpriteMaterial({ map: tipGlowTexture, transparent: true, depthWrite: false, blending: THREE.AdditiveBlending }));
  figure.add(tipGlow);
  const glowTexture = canvasTexture(128, 128, (g, w, h) => {
    const r = g.createRadialGradient(w / 2, h / 2, 0, w / 2, h / 2, w / 2);
    r.addColorStop(0, 'rgba(255,50,50,.9)'); r.addColorStop(1, 'rgba(255,20,20,0)'); g.fillStyle = r; g.fillRect(0, 0, w, h);
  });
  const eyeGlows = [-1, 1].map((s) => {
    const sprite = new THREE.Sprite(new THREE.SpriteMaterial({ map: glowTexture, transparent: true, depthWrite: false, blending: THREE.AdditiveBlending }));
    sprite.scale.setScalar(0.15); sprite.position.set(s * 0.115, 0.01, 0.31); headGroup.add(sprite);
    return sprite;
  });

  root.traverse((o) => { if (o.isMesh && o !== floor && o.material !== m.blush) { o.castShadow = true; o.receiveShadow = true; } });
  if (arena) { floor.castShadow = false; ring.castShadow = disc.castShadow = false; ring.receiveShadow = disc.receiveShadow = false; }

  /* ---------------------------------------------------------------- pose (a pure function of time) */
  const tmp = V(0, 0, 0);
  const GUARD = { elR: V(-0.42, 1.07, 0.1), fiR: V(-0.2, 1.33, 0.27) };   // rear hand stays in guard
    const ANGLE = (t) => (TAU * t) / SWEEP.lap;
  const tipAt = (t, out) => out.set(SWEEP.cx + SWEEP.radius * Math.cos(ANGLE(t)), 0.012, SWEEP.cz + SWEEP.radius * Math.sin(ANGLE(t)));
  const handAt = (t, out) => out.set(SWEEP.cx + SWEEP.handOrbit * Math.cos(ANGLE(t)), SWEEP.handHeight, SWEEP.cz + SWEEP.handOrbit * Math.sin(ANGLE(t)));
  const tip = V(), hand = V(), grip = V(), pole = V(), mid = V(), axis = V(), sidewards = V();

  /** Two-bone IK: the elbow position for a shoulder, a hand, two bone lengths and a preferred bend direction. */
  function elbowFor(shoulder, wrist, l1, l2, bend, out) {
    axis.subVectors(wrist, shoulder);
    const d = Math.min(axis.length(), l1 + l2 - 0.005);
    axis.normalize();
    const a = (l1 * l1 - l2 * l2 + d * d) / (2 * d);
    const h = Math.sqrt(Math.max(l1 * l1 - a * a, 0));
    sidewards.copy(bend).addScaledVector(axis, -bend.dot(axis)).normalize();
    return out.copy(shoulder).addScaledVector(axis, a).addScaledVector(sidewards, h);
  }

  function pose(t) {
    const bob = 0.5 - 0.5 * Math.cos((TAU * t) / 1.0);
    const dip = bob * 0.03;
    const sweepAngle = ANGLE(t);
    const twist = 0.1 * Math.cos(sweepAngle - 0.6);           // the torso follows the sweep a little

    const lean = LEAN + 0.03 * Math.sin(sweepAngle);
    upper.rotation.set(lean, twist, 0);
    upper.position.set(0, 0.85 - 0.85 * Math.cos(lean) - dip, -0.85 * Math.sin(lean));   // pivot about the hips (y = 0.85)
    upper.updateMatrix();
    lower.position.y = -dip * 0.9;
    headGroup.rotation.set(-lean * 0.32 + 0.015 * Math.sin(TAU * t), -twist * 0.5, 0.02 * Math.sin((TAU * t) / 2));   // eyes stay on the circle

    // legs: ankles are planted, hips and knees dip with the bob
    const L = -1, R = 1;
    J.hipL.set(L * 0.115, 0.8 - dip, 0); J.hipR.set(R * 0.115, 0.8 - dip, 0);
    J.kneeL.set(L * (0.345 + 0.012 * bob), 0.445 - dip * 0.4, 0.07 + 0.02 * bob); J.kneeR.set(R * (0.355 + 0.012 * bob), 0.44 - dip * 0.4, 0.09 + 0.02 * bob);
    J.ankleL.set(L * 0.43, 0.13, 0.0); J.ankleR.set(R * 0.45, 0.13, 0.04);

    // arms: the rear hand guards; the lead hand orbits while holding the scepter
    const sway = Math.sin(TAU * t) * 0.012;
    J.shL.set(0.245, 1.3, 0).applyMatrix4(upper.matrix); J.shR.set(-0.245, 1.3, 0).applyMatrix4(upper.matrix);
    J.elR.copy(GUARD.elR).add(V(0, sway, 0)).applyMatrix4(upper.matrix); J.fiR.copy(GUARD.fiR).add(V(0, -sway, 0)).applyMatrix4(upper.matrix);
    handAt(t, hand); hand.y -= dip * 0.5;
    J.fiL.copy(hand);
    elbowFor(J.shL, J.fiL, 0.36, 0.38, pole.set(0.7, -0.55, -0.3), J.elL);

    // the scepter: tip on the floor, shaft through the fist
    tipAt(t, tip);
    grip.copy(hand);
    axis.subVectors(grip, tip).normalize();
    staff.position.copy(tip).addScaledVector(axis, -(STAFF_TO_HAND - grip.distanceTo(tip)));   // keep the grip at the hand
    staff.quaternion.setFromUnitVectors(UP, axis);
    tipGlow.position.copy(tip).add(V(0, 0.03, 0)); tipGlow.scale.setScalar(0.2 + 0.04 * Math.sin(TAU * t * 2));

    paintRunes((((t % SWEEP.lap) + SWEEP.lap) % SWEEP.lap) / SWEEP.lap);   // the same clock as the scepter

    // the glowing circle: the tip's path over the last few seconds, fading with age
    const pos = trailGeometry.attributes.position.array, col = trailGeometry.attributes.color.array;
    for (let i = 0; i < TRAIL_POINTS; i++) {
      const age = (i / (TRAIL_POINTS - 1)) * TRAIL_SECONDS;
      const a = ANGLE(t - age);
      const fade = Math.pow(1 - i / (TRAIL_POINTS - 1), 1.6);
      const width = TRAIL_WIDTH * (0.35 + 0.65 * fade);
      for (let k = 0; k < 2; k++) {
        const r = SWEEP.radius + (k ? width : -width) / 2;
        const o = (i * 2 + k) * 3;
        pos[o] = SWEEP.cx + r * Math.cos(a); pos[o + 1] = 0.008; pos[o + 2] = SWEEP.cz + r * Math.sin(a);
        col[o] = 1.9 * fade; col[o + 1] = 0.35 * fade; col[o + 2] = 0.5 * fade;
      }
    }
    trailGeometry.attributes.position.needsUpdate = true; trailGeometry.attributes.color.needsUpdate = true;

    // wings flap, dress and tail sway
    const flap = Math.sin((TAU * t) / 2.4) * 0.12;
    wings[0].rotation.set(0, -0.22 + flap * 0.5, -flap - 0.05); wings[1].rotation.set(0, 0.22 - flap * 0.5, flap + 0.05);
    front.rotation.x = Math.sin(TAU * t) * 0.02; flapL.rotation.z = Math.sin(TAU * t + 1) * 0.02; flapR.rotation.z = -Math.sin(TAU * t + 1) * 0.02;
    cape.rotation.x = Math.sin((TAU * t) / 1.4) * 0.03;
    tail.rotation.set(0, Math.sin((TAU * t) / 1.6) * 0.16, Math.sin((TAU * t) / 1.6 + 1) * 0.05);
    tail.position.y = -dip * 0.9;
    hair.rotation.z = Math.sin((TAU * t) / 2) * 0.018;
    // eyelids: ease toward the requested state, plus a short idle blink every few seconds
    const dt = lastPoseTime === null ? 1 : Math.min(Math.abs(t - lastPoseTime), 0.1); lastPoseTime = t;
    closedAmount += (closedTarget - closedAmount) * (1 - Math.exp(-dt / (closedTarget > closedAmount ? 0.07 : 0.12)));
    if (Math.abs(closedTarget - closedAmount) < 0.002) closedAmount = closedTarget;
    const blinkPhase = ((t % 3.7) + 3.7) % 3.7;
    const blink = blinkPhase < 0.16 ? Math.sin((Math.PI * blinkPhase) / 0.16) : 0;
    const shut = Math.max(closedAmount, blink);
    root.updateMatrixWorld(true);
    eyeWorld.set(0.115, EYE_Y, EYE_Z); head.localToWorld(eyeWorld);
    const lidTop = eyeWorld.y + LID_R + 0.004, lidBottom = eyeWorld.y - LID_R - 0.004;
    lidPlane.constant = -(lidTop - shut * (lidTop - lidBottom));               // keep what is above this height: the lid
    const lashOn = smooth(Math.min(Math.max((shut - 0.85) / 0.15, 0), 1));
    lashMaterial.opacity = lashOn; lids.forEach(({ lid, lash }) => { lid.visible = shut > 0.001; lash.visible = lashOn > 0.01; });
    eyeGlows.forEach((g) => { g.material.opacity = (0.25 + 0.15 * Math.sin((TAU * t) / 1.2)) * (1 - shut); });

    // place limbs and joints
    for (const l of limbs) place(l.mesh, J[l.from], J[l.to]);
    for (const k of kneePads) {
      const j = k.s === 'L' ? J.kneeL : J.kneeR;
      k.knee.position.copy(j);
      k.pad.position.copy(j).add(V(0, 0.005, 0.062)); k.padRim.position.copy(j).add(V(0, 0.005, 0.078)); k.padRim.scale.set(1, 1.1, 1);
    }
    for (const b of boots) {
      const a = b.s === 'L' ? J.ankleL : J.ankleR;
      b.boot.position.set(a.x, 0, a.z); b.boot.rotation.y = (b.s === 'L' ? -1 : 1) * 0.5;
    }
    for (const g of gloves) {
      const f = g.s === 'L' ? J.fiL : J.fiR;
      g.glove.position.copy(f); g.knuckle.position.copy(f).add(V(0, 0.0, 0.0));
      g.knuckle.quaternion.copy(g.s === 'L' ? staff.quaternion : g.knuckle.quaternion);
      if (g.s === 'L') g.knuckle.rotateX(Math.PI / 2); else { g.knuckle.position.add(V(0, 0, 0.05)); g.knuckle.rotation.y = 0.2; }
    }
    for (const b of bracers) {
      const e = b.s === 'L' ? J.elL : J.elR, f = b.s === 'L' ? J.fiL : J.fiR;
      b.elbow.position.copy(e);
      place(b.bracer, mid.copy(e).lerp(f, 0.42), tmp.copy(e).lerp(f, 0.78));
    }
  }

  return {
    root, figure, floor, ring, disc, pose,
    /** Close (or open) her eyes; immediate skips the easing (used for reduced motion and still renders). */
    setEyesClosed(closed, immediate = false) { closedTarget = closed ? 1 : 0; if (immediate) closedAmount = closedTarget; },
  };
}

/** framing: 'figure' (whole body, wings included) or 'bust' (head and shoulders, for the logo).
 *  offsetX shifts the figure sideways as a fraction of the canvas width (positive = right). */
export function createQueen(canvas, { transparent = true, pixelRatio, framing = 'figure', offsetX = 0 } = {}) {
  const renderer = new THREE.WebGLRenderer({ canvas, antialias: true, alpha: transparent, preserveDrawingBuffer: true, powerPreference: 'high-performance' });
  renderer.setPixelRatio(pixelRatio || Math.min(window.devicePixelRatio || 1, 2));
  renderer.outputColorSpace = THREE.SRGBColorSpace;
  renderer.toneMapping = THREE.ACESFilmicToneMapping;
  renderer.toneMappingExposure = 1.05;
  renderer.localClippingEnabled = true;   // the eyelids are revealed from the top by a clipping plane
  renderer.shadowMap.enabled = true;
  renderer.shadowMap.type = THREE.PCFSoftShadowMap;
  renderer.setClearColor(0x000000, 0);

  const scene = new THREE.Scene();
  const pmrem = new THREE.PMREMGenerator(renderer);
  scene.environment = pmrem.fromScene(new RoomEnvironment(), 0.04).texture;
  scene.environmentIntensity = 0.55;

  const camera = new THREE.PerspectiveCamera(28, 1, 0.1, 50);
  camera.position.set(0, 1.45, 6.4);
  camera.lookAt(0, 1.2, 0);

  // lights: warm key, red rim from behind, cool fill
  const key = new THREE.DirectionalLight(0xfff0e0, 2.6);
  key.position.set(-2.4, 4.2, 3.6); key.castShadow = true;
  key.shadow.mapSize.set(1024, 1024); key.shadow.radius = 5; key.shadow.bias = -0.0004;
  Object.assign(key.shadow.camera, { left: -2, right: 2, top: 3, bottom: -1, near: 0.5, far: 12 });
  scene.add(key);
  const rim = new THREE.DirectionalLight(0xff2a48, 3.2); rim.position.set(3, 2.4, -3.5); scene.add(rim);
  const fill = new THREE.DirectionalLight(0x6a8cff, 0.55); fill.position.set(3.5, 1.2, 2.5); scene.add(fill);
  scene.add(new THREE.HemisphereLight(0xffe0e6, 0x2a0a14, 0.5));

  const { root, figure, floor, ring, disc, pose, setEyesClosed } = buildQueen(scene);

  /* ---------------------------------------------------------------- render loop and controls */
  const target = { yaw: 0, pitch: 0 };
  let frame = 0, clock = 0, last = 0, running = false, fitted = false;

  function resize() {
    const w = canvas.clientWidth || canvas.width, h = canvas.clientHeight || canvas.height;
    if (!w || !h) return;
    renderer.setSize(w, h, false);
    camera.aspect = w / h;
    const bust = framing === 'bust';
    // world units that must fit vertically: the whole figure is ~2.6 tall and ~2.9 wide with the wings; the bust ~1.75
    const need = bust ? Math.max(1.75, 1.9 / camera.aspect) : Math.max(3.05, 3.9 / camera.aspect);
    const lookY = bust ? 1.68 : 1.2;
    camera.position.set(0, lookY + (bust ? 0.05 : 0.95), (need / 2) / Math.tan((camera.fov * Math.PI) / 360) + 0.6);   // looking down a little so the floor circle reads
    camera.lookAt(0, bust ? lookY : lookY - 0.1, 0);
    if (offsetX) camera.setViewOffset(w, h, -offsetX * w, 0, w, h); else camera.clearViewOffset();
    camera.updateProjectionMatrix();
    floor.visible = ring.visible = disc.visible = !bust;
    fitted = true;
  }

  function renderAt(t) {
    if (!fitted) resize();
    pose(t);
    root.rotation.y += (target.yaw - root.rotation.y) * 0.12;
    root.rotation.x += (target.pitch - root.rotation.x) * 0.12;
    renderer.render(scene, camera);
  }

  function loop(now) {
    if (!running) return;
    frame = requestAnimationFrame(loop);
    if (!last) last = now;
    clock += (now - last) / 1000; last = now;
    renderAt(clock);
  }
  const observer = typeof ResizeObserver !== 'undefined' ? new ResizeObserver(resize) : null;
  if (observer) observer.observe(canvas);
  resize();

  return {
    renderAt,
    resize,
    start() { if (!running) { running = true; last = 0; frame = requestAnimationFrame(loop); } },
    stop() { running = false; cancelAnimationFrame(frame); },
    setPointer(x, y) { target.yaw = x * 0.75; target.pitch = -y * 0.18; },
    setEyesClosed,
    setView(yawValue, pitchValue = 0) { target.yaw = root.rotation.y = yawValue; target.pitch = root.rotation.x = pitchValue; },
    dispose() { running = false; observer && observer.disconnect(); renderer.dispose(); },
    /** Export the current pose as a binary glTF that opens in Blender (File > Import > glTF 2.0). */
    async exportGLB() {
      const { GLTFExporter } = await import('three/addons/exporters/GLTFExporter.js');
      pose(0.3);
      const exportScene = new THREE.Scene();
      exportScene.add(figure.clone(true));
      return new Promise((resolve, reject) => new GLTFExporter().parse(exportScene, resolve, reject, { binary: true, onlyVisible: true }));
    },
    THREE,
  };
}
