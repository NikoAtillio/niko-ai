#!/usr/bin/env python3
import re

filepath = "/Users/niko/Documents/projects/niko-ai/phantom/mql5/mql5_v1_ftmo.mq5"

with open(filepath, 'r') as f:
    lines = f.readlines()

# Step 1: Remove lines 2-4 that contain the misplaced function
cleaned_lines = []
skip_count = 0
for i, line in enumerate(lines):
    if i == 1 and 'double GetEffectiveZoneTolerance()' in line:
        # Skip this line and the next 2 lines
        skip_count = 3
        continue
    if skip_count > 0:
        skip_count -= 1
        continue
    cleaned_lines.append(line)

# Write cleaned content
with open(filepath, 'w') as f:
    f.writelines(cleaned_lines)

# Step 2: Read again and fix closing braces
with open(filepath, 'r') as f:
    content = f.read()

# Ensure OnTester() is closed
if 'return score;' in content and not re.search(r'return score;\s*\}', content):
    content = content.replace('   return score;', '   return score;\n}')

# Add the function at the end
if 'double GetEffectiveZoneTolerance()' not in content:
    func = '''
//+------------------------------------------------------------------+
//| GetEffectiveZoneTolerance()                                       |
//+------------------------------------------------------------------+
double GetEffectiveZoneTolerance() {
   return InpZoneTolerance;
}
'''
    content = content.rstrip() + '\n' + func.strip() + '\n'

with open(filepath, 'w') as f:
    f.write(content)

print("File structure fixed successfully!")
