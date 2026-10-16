"""Preview dashboard/index.html locally: the page with a stand-in for the dashboard runtime (dash.calc,
dash.data, dash.onData, dash.colors) fed from data/*.csv, in a dark theme close to the published one.

    python3 dashboard/preview.py [out.html]     default: build/dashboard-preview.html

Open the result in a browser, or screenshot it headless (agent-browser open file://...; screenshot --full).
Fonts and theme colours are approximations of the published page's."""
import csv, json, os, sys
root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
page, d = os.path.join(root, 'dashboard', 'index.html'), os.path.join(root, 'data')
out = sys.argv[1] if len(sys.argv) > 1 else os.path.join(root, 'build', 'dashboard-preview.html')
names = ['launches', 'steps', 'gpu_frame', 'gaming_mode', 'headroom', 'vram', 'static_scene', 'chase']
data = {n: list(csv.DictReader(open(f'{d}/{n}.csv'))) for n in names}
mock = """
<script src="https://cdnjs.cloudflare.com/ajax/libs/d3/7.9.0/d3.min.js"></script>
<style>
:root { --font-anthropic-sans: system-ui, sans-serif; --font-anthropic-serif: Georgia, serif;
 --cds-gap-xs: 4px; --cds-gap-sm: 8px; --cds-gap-md: 16px; --cds-gap-xl: 40px;
 --cds-font-size-title: 26px; --cds-font-size-heading: 17px; --cds-font-size-body: 15px; --cds-font-size-caption: 12.5px;
 --cds-font-weight-medium: 500; --cds-radius: 10px; --cds-pad-xs: 4px; --cds-pad-sm: 8px; --cds-pad-md: 14px; --cds-pad-lg: 18px;
 --color-bg: #1a1a19; --color-panel: #232321; --color-border-line: #3a3a37; --color-fg: #ece9e1; --color-fg-muted: #a6a39a;
 --color-ok: #4caf50; --color-bad: #e5534b; --cds-chart-muted: #5f5d58; --cds-chart-axis: #4a4946; --cds-chart-grid: #2e2e2c;
 --cds-surface-popover: #2b2b29; --cds-border: #3a3a37; --cds-shadow-popover: 0 4px 12px rgba(0,0,0,.4); --cds-text-secondary: #a6a39a; --cds-dur-slow: .3s; }
body { background: var(--color-bg); color: var(--color-fg); margin: 0; padding: 24px 48px; }
</style>
<script>
window.__DATA = %s;
window.dash = { colors: ['#3b87e6', '#d9822b', '#2fa57a', '#b45fc8', '#c9a227'], _c: {}, _cb: [],
  calc(id, o) { this._c[id] = o; },
  data(id) { return this._d && id in this._d ? { status: 'ok', data: this._d[id] } : { status: 'missing' }; },
  onData(cb) { this._cb.push(cb); setTimeout(() => this._run(), 0); },
  _run() { if (this._d) { this._cb.forEach((f) => f()); return; } const d = this._d = Object.assign({}, window.__DATA); let left = Object.keys(this._c);
    while (left.length) { const r = left.filter((id) => this._c[id].inputs.every((i) => i in d)); if (!r.length) throw new Error('calc ' + left);
      r.forEach((id) => { d[id] = this._c[id].fn(...this._c[id].inputs.map((i) => d[i])); }); left = left.filter((id) => !r.includes(id)); }
    this._cb.forEach((f) => f()); } };
</script>
""" % json.dumps(data)
os.makedirs(os.path.dirname(os.path.abspath(out)), exist_ok=True)
open(out, 'w').write('<!doctype html><html><head><meta charset="utf-8"></head><body>' + mock + open(page).read() + '</body></html>')
print(out)
