#!/bin/bash
set -e

PACKAGE="valve-controller"
VERSION="1.0.0"
ARCH="all"
BUILD_DIR="${PACKAGE}_${VERSION}_${ARCH}"

echo "Building ${PACKAGE} ${VERSION}..."

# Clean
rm -rf "$BUILD_DIR" "${BUILD_DIR}.deb"

# Create directory structure
mkdir -p "$BUILD_DIR/DEBIAN"
mkdir -p "$BUILD_DIR/usr/lib/${PACKAGE}/valve_controller"
mkdir -p "$BUILD_DIR/usr/lib/${PACKAGE}/web"
mkdir -p "$BUILD_DIR/usr/bin"
mkdir -p "$BUILD_DIR/lib/systemd/system"
mkdir -p "$BUILD_DIR/etc/${PACKAGE}"
mkdir -p "$BUILD_DIR/usr/share/doc/${PACKAGE}"

# Copy Python source
cp valve-controller-main.py "$BUILD_DIR/usr/lib/${PACKAGE}/"
cp valve_controller/*.py "$BUILD_DIR/usr/lib/${PACKAGE}/valve_controller/"

# Copy web UI
cp web/index.html "$BUILD_DIR/usr/lib/${PACKAGE}/web/"

# Copy systemd unit
cp debian/valve-controller.service "$BUILD_DIR/lib/systemd/system/"

# Copy docs
echo "$VERSION" > "$BUILD_DIR/usr/share/doc/${PACKAGE}/VERSION"

# Create CLI symlink
cp valve-controller-cli.py "$BUILD_DIR/usr/lib/${PACKAGE}/"
ln -sf "/usr/lib/${PACKAGE}/valve-controller-cli.py" "$BUILD_DIR/usr/bin/${PACKAGE}"

# DEBIAN/control
cat > "$BUILD_DIR/DEBIAN/control" << EOF
Package: ${PACKAGE}
Version: ${VERSION}
Section: utils
Priority: optional
Architecture: ${ARCH}
Depends: python3 (>= 3.7), systemd, python3-rpi.gpio
Maintainer: Matteo Galvagni <galvagni.matteo@protonmail.com>
Description: Valve Controller Service
 Controls solenoid valves via GeeekPi 4-relay board on Raspberry Pi.
 REST API with mutual exclusion, timed auto-close, and web dashboard.
EOF

# DEBIAN/postinst
cat > "$BUILD_DIR/DEBIAN/postinst" << 'EOF'
#!/bin/bash
set -e

CONFIG_DIR="/etc/valve-controller"
CONFIG_FILE="${CONFIG_DIR}/config.json"

# Create config only if missing (preserve on upgrade)
if [ ! -f "$CONFIG_FILE" ]; then
    mkdir -p "$CONFIG_DIR"
    cat > "$CONFIG_FILE" << 'CONF'
{
  "port": 8890,
  "relay_pins": {
    "1": 21,
    "2": 20,
    "3": 16,
    "4": 12
  },
  "active_low": true
}
CONF
    echo "Created default config at $CONFIG_FILE"
fi

systemctl daemon-reload
systemctl enable valve-controller
systemctl start valve-controller

echo "Valve Controller installed and started"
EOF
chmod 755 "$BUILD_DIR/DEBIAN/postinst"

# DEBIAN/prerm
cat > "$BUILD_DIR/DEBIAN/prerm" << 'EOF'
#!/bin/bash
set -e
systemctl stop valve-controller || true
systemctl disable valve-controller || true
EOF
chmod 755 "$BUILD_DIR/DEBIAN/prerm"

# DEBIAN/postrm
cat > "$BUILD_DIR/DEBIAN/postrm" << 'EOF'
#!/bin/bash
if [ "$1" = "purge" ]; then
    rm -rf /etc/valve-controller
fi
systemctl daemon-reload || true
EOF
chmod 755 "$BUILD_DIR/DEBIAN/postrm"

# Build the deb
dpkg-deb --build "$BUILD_DIR"

echo ""
echo "Built: ${BUILD_DIR}.deb"
ls -lh "${BUILD_DIR}.deb"
