import json
from pathlib import Path

base = Path('backtest_artifacts/branch-competition-us100-20260416/dashboard_2021_10k')
src = base / 'dashboard_data_2021_10k.json'
data = json.loads(src.read_text())

branch_map = {
    'p2_filter_test1': ('phantom_p1', 'Phantom P1 (from p2_filter_test1)'),
    'p2_filter_test2': ('phantom_p2', 'Phantom P2 (from p2_filter_test2)'),
    'p2_filter_test3': ('phantom_p3', 'Phantom P3 (from p2_filter_test3)'),
}

for branch, (slug, label) in branch_map.items():
    out = {
        'meta': {
            **data.get('meta', {}),
            'strategyLabel': label,
            'sourceBranch': branch,
        },
        'windows': data.get('windows', []),
        'summary': [],
        'highlights': [],
        'monthly': {},
    }

    for row in data.get('summary', []):
        if row.get('branch') == branch:
            copy_row = dict(row)
            copy_row['branch'] = slug
            out['summary'].append(copy_row)

    for row in data.get('highlights', []):
        if row.get('branch') == branch:
            copy_row = dict(row)
            copy_row['branch'] = slug
            out['highlights'].append(copy_row)

    for mode, mode_map in data.get('monthly', {}).items():
        mode_rows = []
        if isinstance(mode_map, dict):
            mode_rows = mode_map.get(branch, [])
        out['monthly'][mode] = {slug: mode_rows}

    target = base / f'dashboard_data_{slug}.json'
    target.write_text(json.dumps(out, indent=2) + '\n')
    print(f'wrote {target}')
