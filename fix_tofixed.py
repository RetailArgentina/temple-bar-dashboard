import re
import sys

filepath = r"C:\Users\Darwin Salinas\Mi unidad\Claude_Cowork\templates\destileria.html"

with open(filepath, encoding='utf-8') as f:
    original = f.read()

content = original
total = 0

# --- Pattern 1: .toFixed(1) + '% ...
before = content
content = re.sub(
    r"\.toFixed\(1\)(\s*\+\s*'%)",
    r".toLocaleString('es-AR',{minimumFractionDigits:1,maximumFractionDigits:1})\1",
    content
)
n1 = len(re.findall(r"\.toFixed\(1\)(\s*\+\s*'%)", original))
print(f"  .toFixed(1) + '%  replacements: {n1}")
total += n1

# --- Pattern 2: .toFixed(0) + '% ...
n2 = len(re.findall(r"\.toFixed\(0\)(\s*\+\s*'%)", original))
content = re.sub(
    r"\.toFixed\(0\)(\s*\+\s*'%)",
    r".toLocaleString('es-AR',{maximumFractionDigits:0})\1",
    content
)
print(f"  .toFixed(0) + '%  replacements: {n2}")
total += n2

# --- Pattern 3: .toFixed(1)}% (template literals)
n3 = len(re.findall(r"\.toFixed\(1\)\}%", original))
content = re.sub(
    r"\.toFixed\(1\)\}%",
    ".toLocaleString('es-AR',{minimumFractionDigits:1,maximumFractionDigits:1})}%",
    content
)
print(f"  .toFixed(1)}}%    replacements: {n3}")
total += n3

# --- Pattern 4: .toFixed(0)}% (template literals)
n4 = len(re.findall(r"\.toFixed\(0\)\}%", original))
content = re.sub(
    r"\.toFixed\(0\)\}%",
    ".toLocaleString('es-AR',{maximumFractionDigits:0})}%",
    content
)
print(f"  .toFixed(0)}}%    replacements: {n4}")
total += n4

print(f"\nTotal replacements: {total}")

with open(filepath, 'w', encoding='utf-8') as f:
    f.write(content)
print("File written successfully.")

# --- Verification: check no .toFixed(0/.toFixed(1) remain near '%'
print("\n--- Verification: remaining .toFixed near '%' ---")
issues = []
for m in re.finditer(r"\.toFixed\([01]\)", content):
    start = max(0, m.start() - 5)
    end = min(len(content), m.end() + 60)
    snippet = content[start:end].replace('\n', ' ')
    if '%' in content[m.end():m.end()+60]:
        issues.append(f"  Line ~{content[:m.start()].count(chr(10))+1}: {snippet}")

if issues:
    print(f"WARNING: {len(issues)} potential remaining occurrence(s):")
    for i in issues:
        print(i)
else:
    print("OK - no .toFixed(0) or .toFixed(1) found within 60 chars of '%'")

# Show all remaining toFixed(0) and toFixed(1) for reference
remaining = [(content[:m.start()].count('\n')+1, content[max(0,m.start()-10):m.end()+50].replace('\n',' '))
             for m in re.finditer(r"\.toFixed\([01]\)", content)]
if remaining:
    print(f"\nAll remaining .toFixed(0/.toFixed(1) occurrences ({len(remaining)} total):")
    for line, snippet in remaining:
        print(f"  L{line}: ...{snippet}...")
else:
    print("\nNo .toFixed(0) or .toFixed(1) remain anywhere.")
