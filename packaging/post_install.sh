#!/bin/bash
# Runs after the env is laid down. $PREFIX is the final install location.
set -euo pipefail

# 1. Install the NBEAST package offline (its deps are already in the env).
"$PREFIX/bin/python" -m pip install --no-index --no-deps \
    "$PREFIX/nbeast-0.0.1-py3-none-any.whl"

# 2. Unpack the curated cross-section data (relative-path cross_sections.xml).
mkdir -p "$PREFIX/share/nbeast"
tar -xzf "$PREFIX/nbeast_data.tar.gz" -C "$PREFIX/share/nbeast"

# 3. Write a launcher that points OpenMC at the bundled data and starts the GUI.
cat > "$PREFIX/bin/nbeast" <<EOF
#!/bin/bash
export OPENMC_CROSS_SECTIONS="$PREFIX/share/nbeast/data/cross_sections.xml"
export FI_PROVIDER=tcp
exec "$PREFIX/bin/python" -m nbeast.gui.app "\$@"
EOF
chmod +x "$PREFIX/bin/nbeast"

# 4. Drop the bundled archives now that they're installed.
rm -f "$PREFIX/nbeast-0.0.1-py3-none-any.whl" "$PREFIX/nbeast_data.tar.gz"
