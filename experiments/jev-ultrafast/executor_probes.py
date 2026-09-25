"""Deterministic executor probes on owned loopback fixtures; no model calls."""
import argparse
import json
from pathlib import Path
import browser_trial as trial


def run(source, cdp_url):
    conn, isolation = trial.connect_isolated(cdp_url)
    up, pin = trial.load_upstream(source)
    up.browser.ensure_daemon = lambda: None
    up.browser.cdp = lambda method, session_id=None, **params: conn.command(method, params, session_id)
    server, origin = trial.serve_fixtures()
    rows = []
    try:
        for probe in ('covered', 'disabled-after-observe', 'positive-click'):
            browser = up.browser.Browser(origin + '/pick-item.html')
            try:
                page = browser.observe(screenshot=False)
                labels = [a['label'] for a in page['actions']]
                excluded = all(not any(word in label for word in ('Condor', 'Falcon')) for label in labels)
                label = 'Sparrow' if probe == 'covered' else 'Kestrel'
                action = next(a for a in page['actions'] if a['kind'] == 'click' and label in a['label'])
                if probe == 'disabled-after-observe':
                    browser.evaluate('window.__jevFast.nodes.get(%d).disabled=true' % action['node'])
                refused = False
                try:
                    browser.act(action, page)
                except up.browser.StalePage:
                    refused = True
                state = browser.evaluate('window.__trial')
                expected = probe != 'positive-click'
                passed = excluded and refused == expected and not state['errors']
                passed = passed and (state['complete'] if not expected else not state['log'])
                rows.append({'probe': probe, 'passed': bool(passed), 'refused': refused,
                             'disabled_controls_excluded': excluded, 'fixture': state})
            finally:
                browser.close()
    finally:
        server.shutdown()
        server.server_close()
        conn.close()
    return {'source_pin': pin, 'isolation': isolation, 'model_calls': 0, 'probes': rows}


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--source', required=True)
    parser.add_argument('--cdp-url', required=True)
    parser.add_argument('--out', required=True)
    args = parser.parse_args()
    result = run(args.source, args.cdp_url)
    Path(args.out).write_text(json.dumps(result, indent=2))
    print(json.dumps(result, indent=2))
    raise SystemExit(0 if all(p['passed'] for p in result['probes']) else 1)
