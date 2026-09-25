"""Renders the 3D logo from web/static/web/queen3d.js with headless Chrome. A dev-time tool: the site itself
only ships the resulting images, so it needs neither Playwright nor WebGL for the top bar.

    pip install playwright            # once; uses the system Google Chrome, no browser download
    python web/art/render_logo.py     # writes web/static/web/logo.png, favicon.png and web/art/queen.glb

queen.glb is the character as a glTF binary: in Blender use File > Import > glTF 2.0 to keep working on it.
"""
import base64
import sys
from pathlib import Path

from playwright.sync_api import sync_playwright

HERE = Path(__file__).resolve().parent
STATIC = HERE.parent / 'static' / 'web'
CHROME = '/usr/bin/google-chrome'

PAGE = '''<!doctype html><body style="margin:0;background:transparent">
<script type="importmap">{"imports":{"three":"/static/web/vendor/three/three.module.min.js","three/addons/":"/static/web/vendor/three/addons/"}}</script>
<div style="width:%(size)dpx;height:%(size)dpx;border-radius:50%%;padding:%(ring)dpx;box-sizing:border-box;background:linear-gradient(135deg,#fff0b0,#f2b73f 45%%,#9a5f10)">
  <div style="width:100%%;height:100%%;border-radius:50%%;overflow:hidden;position:relative;background:radial-gradient(circle at 50%% 36%%,#8a1a2c,#1b0910 78%%)">
    <div style="position:absolute;left:12%%;top:6%%;width:46%%;height:18%%;border-radius:50%%;background:linear-gradient(rgba(255,255,255,.28),rgba(255,255,255,0));transform:rotate(-24deg)"></div>
    <canvas id="c" style="width:100%%;height:100%%;display:block;position:relative"></canvas>
  </div>
</div>
<script type="module">
import {createQueen} from '/static/web/queen3d.js';
try {
  const q = createQueen(document.getElementById('c'), {pixelRatio: 1, framing: 'bust', still: true});
  q.setView(-0.38, 0);
  for (let i = 0; i < 12; i++) q.renderAt(0.5);
  window.done = true;
  window.exportGlb = async () => {
    const buf = await q.exportGLB();
    return new Promise((resolve) => { const r = new FileReader(); r.onload = () => resolve(r.result.split(',')[1]); r.readAsDataURL(new Blob([buf])); });
  };
} catch (e) { window.err = String(e && e.stack || e); }
</script>'''


def serve(route):
    url = route.request.url
    if url.endswith('/badge'):
        return route.fulfill(body=route.request.headers.get('x-page', ''), content_type='text/html')
    path = STATIC / url.split('/static/web/')[1]
    kind = 'application/javascript' if path.suffix == '.js' else 'application/octet-stream'
    route.fulfill(body=path.read_bytes(), content_type=kind)


def render(browser, size, out, glb=None):
    ring = max(2, round(size * 0.028))
    html = PAGE % {'size': size, 'ring': ring}
    page = browser.new_page(viewport={'width': size, 'height': size})
    page.on('pageerror', lambda e: print('page error:', e))
    page.route('http://queen.local/static/**', serve)
    page.route('http://queen.local/badge', lambda r: r.fulfill(body=html, content_type='text/html'))
    page.goto('http://queen.local/badge')
    page.wait_for_function('window.done || window.err', timeout=60000)
    err = page.evaluate('window.err || null')
    if err:
        sys.exit(f'render failed: {err}')
    page.screenshot(path=str(out), omit_background=True)
    if glb:
        glb.write_bytes(base64.b64decode(page.evaluate('window.exportGlb()')))
    page.close()


def main():
    with sync_playwright() as p:
        browser = p.chromium.launch(executable_path=CHROME, headless=True, args=[
            '--no-sandbox', '--use-angle=swiftshader', '--enable-unsafe-swiftshader', '--ignore-gpu-blocklist'])
        render(browser, 256, STATIC / 'logo.png', glb=HERE / 'queen.glb')
        render(browser, 64, STATIC / 'favicon.png')
        browser.close()
    print('wrote', STATIC / 'logo.png', STATIC / 'favicon.png', HERE / 'queen.glb')


if __name__ == '__main__':
    main()
