#!/usr/bin/env python3
"""Exercise a WebGL 2 cubemap framebuffer in an isolated Brave profile."""

import json
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
import subprocess
import sys
import tempfile
import threading

# Reproduces the context loss seen with Metal 39. The readback forces the clear
# to complete through ANGLE, and the renderer check rules out a software pass.
PAGE = b"""<!doctype html>
<meta charset="utf-8">
<title>Navi44 WebGL 2 cubemap test</title>
<canvas width="16" height="16"></canvas>
<script>
const gl = document.querySelector("canvas").getContext("webgl2");
if (gl) {
    const debug = gl.getExtension("WEBGL_debug_renderer_info");
    const renderer = debug && gl.getParameter(debug.UNMASKED_RENDERER_WEBGL);
    const cube = gl.createTexture();
    gl.bindTexture(gl.TEXTURE_CUBE_MAP, cube);
    for (let face = 0; face < 6; face++) {
        gl.texImage2D(gl.TEXTURE_CUBE_MAP_POSITIVE_X + face, 0,
            gl.RGBA, 1, 1, 0, gl.RGBA, gl.UNSIGNED_BYTE, new Uint8Array([0, 0, 0, 255]));
    }
    const fb = gl.createFramebuffer();
    gl.bindFramebuffer(gl.FRAMEBUFFER, fb);
    gl.framebufferTexture2D(gl.FRAMEBUFFER, gl.COLOR_ATTACHMENT0,
        gl.TEXTURE_CUBE_MAP_POSITIVE_X, cube, 0);
    const status = gl.checkFramebufferStatus(gl.FRAMEBUFFER);
    const pixel = new Uint8Array(4);
    if (status === gl.FRAMEBUFFER_COMPLETE) {
        gl.clearColor(1, 0, 0, 1);
        gl.clear(gl.COLOR_BUFFER_BIT);
        gl.readPixels(0, 0, 1, 1, gl.RGBA, gl.UNSIGNED_BYTE, pixel);
    }
    fetch("/result", {method:"POST",
        body: JSON.stringify({renderer, status, pixel: [...pixel], error: gl.getError()})});
}
</script>
"""


class CubemapHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path != '/':
            self.send_error(404)
            return
        self.send_response(200)
        self.send_header('Content-Type', 'text/html; charset=utf-8')
        self.send_header('Content-Length', str(len(PAGE)))
        self.end_headers()
        self.wfile.write(PAGE)

    def do_POST(self):
        if self.path != '/result':
            self.send_error(404)
            return
        try:
            length = int(self.headers.get('Content-Length', '0'))
            if not 0 < length <= 2048:
                raise ValueError('invalid result size')
            result = json.loads(self.rfile.read(length))
            if not isinstance(result, dict):
                raise ValueError('invalid result')
        except ValueError:
            self.send_error(400)
            return
        self.server.cubemap_result = result
        self.send_response(204)
        self.end_headers()

    def log_message(self, *_):
        pass


def main():
    probe = Path(__file__).with_name('brave-probe.py')
    with tempfile.TemporaryDirectory(prefix='navi44-brave-cubemap-') as scratch:
        output = Path(scratch) / 'probe.json'
        with ThreadingHTTPServer(('127.0.0.1', 0), CubemapHandler) as server:
            server.cubemap_result = {}
            thread = threading.Thread(target=server.serve_forever)
            thread.start()
            try:
                url = f'http://127.0.0.1:{server.server_port}/'
                subprocess.run([sys.executable, '-B', str(probe), '--watch-webgl', '--url', url,
                                '--output', str(output)], stdout=subprocess.DEVNULL, check=True)
            finally:
                server.shutdown()
                thread.join()
            cube = server.cubemap_result
        probe_result = json.loads(output.read_text())
    webgl = probe_result['webgl_probe']
    contexts = webgl['main_document_contexts']
    before = webgl['gpu_processes_before_navigation']
    after = webgl['gpu_processes_after_sample']
    renderer = cube.get('renderer') or ''
    success = (cube.get('pixel') == [255, 0, 0, 255] and cube.get('status') == 0x8CD5
               and cube.get('error') == 0 and 'ANGLE Metal Renderer: AMD Radeon RX 9060 XT' in renderer
               and probe_result['gpu_feature_status_after'].get('webgl') == 'enabled'
               and contexts['accepted'] == 1 and not contexts['creationErrors'] and not contexts['losses']
               and bool(before) and before == after)
    print(json.dumps({'passed': success, 'cubemap': cube, 'webgl': webgl}, indent=2))
    return 0 if success else 1


if __name__ == '__main__':
    sys.exit(main())
