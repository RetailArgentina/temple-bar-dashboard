import re

filepath = r"C:\Users\Darwin Salinas\Mi unidad\Claude_Cowork\templates\destileria.html"

with open(filepath, "r", encoding="utf-8") as f:
    content = f.read()

replacements = [
    # Pattern 1: .toFixed(1)+'%'
    (
        ".toFixed(1)+'%'",
        ".toLocaleString('es-AR',{minimumFractionDigits:1,maximumFractionDigits:1})+'%'"
    ),
    # Pattern 2: .toFixed(1) + '%'  (with spaces)
    (
        ".toFixed(1) + '%'",
        ".toLocaleString('es-AR',{minimumFractionDigits:1,maximumFractionDigits:1}) + '%'"
    ),
    # Pattern 3: .toFixed(1)}%  (template literal close)
    (
        ".toFixed(1)}%",
        ".toLocaleString('es-AR',{minimumFractionDigits:1,maximumFractionDigits:1})}%"
    ),
    # Pattern 4: .toFixed(0)+'%'
    (
        ".toFixed(0)+'%'",
        ".toLocaleString('es-AR',{maximumFractionDigits:0})+'%'"
    ),
    # Pattern 5: .toFixed(0) + '%'  (with spaces)
    (
        ".toFixed(0) + '%'",
        ".toLocaleString('es-AR',{maximumFractionDigits:0}) + '%'"
    ),
    # Pattern 6: .toFixed(0)}%  (template literal close)
    (
        ".toFixed(0)}%",
        ".toLocaleString('es-AR',{maximumFractionDigits:0})}%"
    ),
]

total = 0
for old, new in replacements:
    count = content.count(old)
    if count > 0:
        content = content.replace(old, new)
        print(f"  [{count}x] replaced: {old!r}")
    else:
        print(f"  [0x] not found:  {old!r}")
    total += count

print(f"\nTotal replacements: {total}")

with open(filepath, "w", encoding="utf-8") as f:
    f.write(content)

print("\nFile written successfully.")

# Verification: check for any remaining .toFixed(1)+'%' or .toFixed(0)+'%' patterns
print("\n--- Verification: remaining .toFixed(%)'%' occurrences ---")
lines = content.splitlines()
found_any = False
for i, line in enumerate(lines, 1):
    # Check for toFixed(0) or toFixed(1) followed by something with %
    if re.search(r'\.toFixed\([01]\)[^k]', line) and '%' in line:
        print(f"  Line {i}: {line.strip()}")
        found_any = True
if not found_any:
    print("  None found. All .toFixed(0/%1) with '%' have been replaced.")

# Also verify we did NOT touch toFixed(2), toFixed(0)+'k', toFixed(1)+'M'
print("\n--- Verification: preserved patterns ---")
for pattern, label in [
    (r'\.toFixed\(2\)', '.toFixed(2)'),
    (r"\.toFixed\(0\)\+'k'", ".toFixed(0)+'k'"),
    (r"\.toFixed\(1\)\+'M'", ".toFixed(1)+'M'"),
]:
    matches = [(i+1, line.strip()) for i, line in enumerate(lines) if re.search(pattern, line)]
    print(f"  {label}: {len(matches)} occurrence(s) preserved")
    for lineno, text in matches[:5]:
        print(f"    Line {lineno}: {text}")
