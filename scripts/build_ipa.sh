#!/usr/bin/env bash
# Builds an UNSIGNED .ipa (build/RenkoScalper.ipa). Needs macOS + Xcode + xcodegen (brew install xcodegen).
# Sideloaders (Sideloadly / AltStore / TrollStore) re-sign it with your own Apple ID.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
BUILD="$ROOT/build"
rm -rf "$BUILD"; mkdir -p "$BUILD"

cd "$ROOT/ios"
xcodegen generate

set -o pipefail
xcodebuild \
  -project RenkoScalper.xcodeproj \
  -scheme RenkoScalper \
  -configuration Release \
  -sdk iphoneos \
  -destination 'generic/platform=iOS' \
  -derivedDataPath "$BUILD/DerivedData" \
  CODE_SIGNING_ALLOWED=NO CODE_SIGNING_REQUIRED=NO CODE_SIGN_IDENTITY="" \
  build 2>&1 | tee "$BUILD/xcodebuild.log" | tail -n 40

APP="$(find "$BUILD/DerivedData/Build/Products/Release-iphoneos" -maxdepth 1 -name '*.app' | head -n1)"
[ -n "$APP" ] || { echo "no .app produced - see build/xcodebuild.log"; exit 1; }

mkdir -p "$BUILD/Payload"
cp -R "$APP" "$BUILD/Payload/"
(cd "$BUILD" && zip -qry RenkoScalper.ipa Payload)
echo "IPA: $BUILD/RenkoScalper.ipa"
