#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "$0")" && pwd)"
APP_NAME="Substack Studio SwiftUI"
BUILD_DIR="$ROOT_DIR/.build/arm64-apple-macosx/debug"
APP_DIR="$ROOT_DIR/dist/$APP_NAME.app"
CONTENTS_DIR="$APP_DIR/Contents"
MACOS_DIR="$CONTENTS_DIR/MacOS"
RESOURCES_DIR="$CONTENTS_DIR/Resources"
BACKEND_DIR="$RESOURCES_DIR/backend"
EXECUTABLE="$BUILD_DIR/SubstackStudio"
ICONSET_DIR="$ROOT_DIR/.icon_build/AppIcon.iconset"
ICON_ICNS="$ROOT_DIR/.icon_build/AppIcon.icns"

HOME=/tmp SWIFTPM_MODULECACHE_OVERRIDE=/tmp/swiftpm-module-cache CLANG_MODULE_CACHE_PATH=/tmp/clang-module-cache swift build
python3 "$ROOT_DIR/generate_app_icon.py"
iconutil -c icns "$ICONSET_DIR" -o "$ICON_ICNS"

rm -rf "$APP_DIR"
mkdir -p "$MACOS_DIR" "$RESOURCES_DIR" "$BACKEND_DIR"

cp "$EXECUTABLE" "$MACOS_DIR/$APP_NAME"
cp "$ICON_ICNS" "$RESOURCES_DIR/AppIcon.icns"

cp -R "$ROOT_DIR/.venv" "$BACKEND_DIR/"
cp "$ROOT_DIR/substack_scraper.py" "$BACKEND_DIR/"
cp "$ROOT_DIR/substack_toolkit.py" "$BACKEND_DIR/"
cp "$ROOT_DIR/config.py" "$BACKEND_DIR/"
cp "$ROOT_DIR/author_template.html" "$BACKEND_DIR/"
cp -R "$ROOT_DIR/assets" "$BACKEND_DIR/"

cat > "$CONTENTS_DIR/Info.plist" <<'EOF'
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>CFBundleDevelopmentRegion</key>
    <string>zh_CN</string>
    <key>CFBundleDisplayName</key>
    <string>Substack Studio SwiftUI</string>
    <key>CFBundleExecutable</key>
    <string>Substack Studio SwiftUI</string>
    <key>CFBundleIdentifier</key>
    <string>com.zxh.substackstudio.swiftui</string>
    <key>CFBundleIconFile</key>
    <string>AppIcon</string>
    <key>CFBundleInfoDictionaryVersion</key>
    <string>6.0</string>
    <key>CFBundleName</key>
    <string>Substack Studio SwiftUI</string>
    <key>CFBundlePackageType</key>
    <string>APPL</string>
    <key>CFBundleShortVersionString</key>
    <string>1.0</string>
    <key>CFBundleVersion</key>
    <string>1</string>
    <key>LSMinimumSystemVersion</key>
    <string>13.0</string>
    <key>NSHighResolutionCapable</key>
    <true/>
</dict>
</plist>
EOF

xattr -cr "$APP_DIR" || true
codesign --force --deep --sign - "$APP_DIR"

echo "Packaged app at: $APP_DIR"
