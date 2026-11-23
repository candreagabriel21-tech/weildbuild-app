#!/bin/bash
set -euo pipefail

SDK="${ANDROID_SDK_DIR:?set ANDROID_SDK_DIR to the folder holding android-14 (build-tools) and android-34 (platform)}"
BT="$SDK/android-14"
PLATFORM="$SDK/android-34/android.jar"
JAVAC="${JAVAC:-javac}"
SRC_DIR="$(cd "$(dirname "$0")" && pwd)"
OUT="$SRC_DIR/build"
rm -rf "$OUT"
mkdir -p "$OUT/gen" "$OUT/obj" "$OUT/apk"

"$BT/aapt2" compile --dir "$SRC_DIR/res" -o "$OUT/res.zip"
"$BT/aapt2" link -o "$OUT/apk/base.apk" -I "$PLATFORM" --manifest "$SRC_DIR/AndroidManifest.xml" -R "$OUT/res.zip" --java "$OUT/gen" --auto-add-overlay
"$JAVAC" -source 8 -target 8 -bootclasspath "$PLATFORM" -classpath "$OUT/gen" -d "$OUT/obj" "$SRC_DIR/java/com/weildbuild/app/MainActivity.java" 2>/dev/null || "$JAVAC" -source 8 -target 8 -classpath "$OUT/gen" -d "$OUT/obj" "$SRC_DIR/java/com/weildbuild/app/MainActivity.java"
python3 -c "
import zipfile, os
with zipfile.ZipFile('$OUT/classes.jar','w') as z:
    for root,_,files in os.walk('$OUT/obj'):
        for f in files:
            if f.endswith('.class'):
                p=os.path.join(root,f)
                z.write(p, os.path.relpath(p,'$OUT/obj'))
"
java -cp "$BT/lib/d8.jar" com.android.tools.r8.D8 --release --min-api 24 --lib "$PLATFORM" --output "$OUT/apk" "$OUT/classes.jar"
cd "$OUT/apk"
python3 -c "
import zipfile
with zipfile.ZipFile('base.apk','a') as z:
    z.write('classes.dex','classes.dex')
"
"$BT/zipalign" -f 4 base.apk aligned.apk
rm -f base.apk
if [ ! -f "$SRC_DIR/debug.keystore" ]; then
  keytool -genkeypair -keystore "$SRC_DIR/debug.keystore" -alias androiddebugkey \
    -storepass android -keypass android -keyalg RSA -keysize 2048 -validity 10000 \
    -dname "CN=Android Debug,O=Android,C=US" 2>/dev/null
fi
"$BT/apksigner" sign --ks "$SRC_DIR/debug.keystore" --ks-pass pass:android \
  --key-pass pass:android --out "$SRC_DIR/weildbuild-app.apk" aligned.apk
"$BT/apksigner" verify "$SRC_DIR/weildbuild-app.apk"
echo "APK OK: $SRC_DIR/weildbuild-app.apk"
