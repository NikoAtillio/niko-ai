#!/usr/bin/env python3
"""
Run P2 full validation matrix: 3 instruments (BTC, XAU, US100) x 3 scenarios (A, B, C)
Reports before/after metrics comparing the new P2 (with all 10 fixes) vs baseline.
"""

import subprocess
import sys
import os
from datetime import datetime

# Use venv Python
PYTHON_BIN = '/Users/niko/Documents/projects/niko-ai/.venv/bin/python3'

# Configuration for each instrument
INSTRUMENTS = {
    'BTC': {
        'label': 'Bitcoin',
        'data_dir': '/Users/niko/Documents/projects/niko-ai/data/BTCUSD',
        'files': {
            'm1':    'BTCUSD_M1_2024.04.06-2026.03.31',
            'm5':    'BTCUSD_M5_2017.01.16-2026.03.31',
            'm15':   'BTCUSD_M15_2017.01.16-2026.03.31',
            'h1':    'BTCUSD_H1_2017.01.16-2026.03.31',
            'h4':    'BTCUSD_H4_2017.01.16-2026.03.31',
            'daily': 'BTCUSD_Daily_2017.01.16-2026.03.31',
        }
    },
    'XAU': {
        'label': 'Gold',
        'data_dir': '/Users/niko/Documents/projects/niko-ai/data/XAUUSD',
        'files': {
            'm1':    'XAUUSD_M1_2023.03.13-2026.03.31',
            'm5':    'XAUUSD_M5_2011.09.08-2026.03.31',
            'm15':   'XAUUSD_M15_2010.01.04-2026.03.31',
            'h1':    'XAUUSD_H1_2010.01.04-2026.03.31',
            'h4':    'XAUUSD_H4_2010.01.04-2026.03.31',
            'daily': 'XAUUSD_Daily_2010.01.04-2026.03.31',
        }
    },
    'US100': {
        'label': 'Nasdaq 100',
        'data_dir': '/Users/niko/Documents/projects/niko-ai/data/US100',
        'start_date': '2022-01-01',
        'files': {
            'm1':    'US100.cash_M1_2023.05.24-2026.03.31',
            'm5':    'US100.cash_M5_2021.01.21-2026.03.31',
            'm15':   'US100.cash_M15_2021.01.21-2026.03.31',
            'h1':    'US100.cash_H1_2021.01.21-2026.03.31',
            'h4':    'US100.cash_H4_2021.01.21-2026.03.31',
            'daily': 'US100.cash_Daily_2021.01.21-2026.03.31',
        }
    },
}

def run_scenario(instrument, scenario, output_dir):
    """Run a single scenario for an instrument."""
    inst_config = INSTRUMENTS[instrument]
    
    # Build file paths
    m1_path = os.path.join(inst_config['data_dir'], inst_config['files']['m1'])
    m5_path = os.path.join(inst_config['data_dir'], inst_config['files']['m5'])
    m15_path = os.path.join(inst_config['data_dir'], inst_config['files']['m15'])
    h1_path = os.path.join(inst_config['data_dir'], inst_config['files']['h1'])
    h4_path = os.path.join(inst_config['data_dir'], inst_config['files']['h4'])
    daily_path = os.path.join(inst_config['data_dir'], inst_config['files']['daily'])
    
    # Verify files exist
    for path in [m1_path, m5_path, m15_path, h1_path, h4_path, daily_path]:
        if not os.path.exists(path):
            print(f"  ❌ Missing data file: {path}")
            return False
    
    # Build command
    cmd = [
        PYTHON_BIN,
        '/Users/niko/Documents/projects/niko-ai/phantom/v2/phantom_p2.py',
        '--instrument', instrument,
        '--m1', m1_path,
        '--m5', m5_path,
        '--m15', m15_path,
        '--h1', h1_path,
        '--h4', h4_path,
        '--daily', daily_path,
        '--scenario', f'p2{scenario}',
        '--output-dir', output_dir,
    ]

    start_date = inst_config.get('start_date')
    if start_date:
        cmd.extend(['--start-date', start_date])
    
    try:
        print(f"  🔄 Running {instrument} Scenario {scenario}...")
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=300)
        
        if result.returncode != 0:
            print(f"  ❌ Error: {result.stderr}")
            return False
        
        print(result.stdout)
        return True
    except subprocess.TimeoutExpired:
        print(f"  ⏱️ Timeout after 5 minutes")
        return False
    except Exception as e:
        print(f"  ❌ Exception: {e}")
        return False

def main():
    # Create output directory with timestamp
    timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
    output_base = f'/Users/niko/Documents/projects/niko-ai/backtest_artifacts/phantom-p2-fixed-{timestamp}'
    os.makedirs(output_base, exist_ok=True)
    
    print(f"\n{'='*70}")
    print(f"  PHANTOM P2 VALIDATION MATRIX (WITH 10 FIXES)")
    print(f"{'='*70}")
    print(f"\n  Output directory: {output_base}")
    print(f"  Running 3 instruments × 3 scenarios = 9 validation runs\n")
    
    results = {}
    total_runs = 0
    successful_runs = 0
    
    for instrument in ['BTC', 'XAU', 'US100']:
        print(f"\n📊 {INSTRUMENTS[instrument]['label']} ({instrument})")
        print(f"  {'-'*60}")
        results[instrument] = {}
        
        for scenario in ['A', 'B', 'C']:
            total_runs += 1
            scenario_output = os.path.join(output_base, f'{instrument}_P2{scenario}')
            os.makedirs(scenario_output, exist_ok=True)
            
            if run_scenario(instrument, scenario, scenario_output):
                results[instrument][scenario] = 'PASS'
                successful_runs += 1
            else:
                results[instrument][scenario] = 'FAIL'
    
    # Summary
    print(f"\n\n{'='*70}")
    print(f"  VALIDATION MATRIX SUMMARY")
    print(f"{'='*70}")
    print(f"\n  Total runs: {total_runs}")
    print(f"  Successful: {successful_runs}")
    print(f"  Failed: {total_runs - successful_runs}")
    print(f"\n  Results by instrument:")
    
    for instrument in ['BTC', 'XAU', 'US100']:
        status_line = f"    {instrument}: "
        for scenario in ['A', 'B', 'C']:
            result = results[instrument][scenario]
            emoji = '✅' if result == 'PASS' else '❌'
            status_line += f"{emoji} P2{scenario} "
        print(status_line)
    
    print(f"\n  Artifacts saved to: {output_base}")
    print(f"\n{'='*70}\n")
    
    if successful_runs == total_runs:
        print("✅ All validations completed successfully!")
        return 0
    else:
        print(f"⚠️ {total_runs - successful_runs} validation(s) failed.")
        return 1

if __name__ == '__main__':
    sys.exit(main())
