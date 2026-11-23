package com.weildbuild.app;

import android.app.Activity;
import android.graphics.Color;
import android.os.Bundle;
import android.os.StatFs;
import android.util.Base64;
import android.util.JsonReader;
import android.webkit.JavascriptInterface;
import android.webkit.WebSettings;
import android.webkit.WebView;
import android.webkit.WebViewClient;
import android.widget.FrameLayout;
import android.widget.TextView;

import java.io.ByteArrayInputStream;
import java.io.ByteArrayOutputStream;
import java.io.File;
import java.io.FileInputStream;
import java.io.FileOutputStream;
import java.io.InputStream;
import java.io.InputStreamReader;
import java.net.HttpURLConnection;
import java.net.URL;
import java.nio.charset.StandardCharsets;
import java.util.ArrayList;
import java.util.List;

class WbPaths {
    static final String REPO_RAW = "https://raw.githubusercontent.com/candreagabriel21-tech/weildbuild-browser/main";
    static final int CONNECT_TIMEOUT_MS = 20000;
    static final int READ_TIMEOUT_MS = 120000;

    static File appDir(MainActivity act) {
        return new File(act.getFilesDir(), "app");
    }

    static File stagingDir(MainActivity act) {
        return new File(act.getFilesDir(), "wb-staging");
    }

    static byte[] fetchBytes(String url) throws Exception {
        HttpURLConnection conn = (HttpURLConnection) new URL(url).openConnection();
        conn.setConnectTimeout(CONNECT_TIMEOUT_MS);
        conn.setReadTimeout(READ_TIMEOUT_MS);
        conn.setInstanceFollowRedirects(true);
        int code = conn.getResponseCode();
        if (code == 404) {
            throw new Exception("FIL-002 Files not found on the server.");
        }
        if (code < 200 || code >= 300) {
            throw new Exception("FIL-001 Couldn't fetch file (HTTP " + code + ").");
        }
        InputStream in = conn.getInputStream();
        ByteArrayOutputStream out = new ByteArrayOutputStream();
        byte[] buf = new byte[16384];
        int n;
        while ((n = in.read(buf)) > 0) {
            out.write(buf, 0, n);
        }
        in.close();
        return out.toByteArray();
    }

    static String parseVersion(String raw) {
        String line = raw.trim();
        if (line.startsWith("version")) {
            line = line.substring(7);
        }
        line = line.replaceFirst("^[=\\s\"']*", "").replaceFirst("[\"']\\s*$", "").trim();
        return line;
    }

    static List<String[]> parseManifest(String raw) {
        try {
            JsonReader reader = new JsonReader(new InputStreamReader(new ByteArrayInputStream(raw.getBytes(StandardCharsets.UTF_8)), StandardCharsets.UTF_8));
            List<String[]> files = new ArrayList<String[]>();
            reader.beginObject();
            while (reader.hasNext()) {
                String name = reader.nextName();
                if (name.equals("files")) {
                    reader.beginArray();
                    while (reader.hasNext()) {
                        String path = null;
                        String size = "0";
                        reader.beginObject();
                        while (reader.hasNext()) {
                            String key = reader.nextName();
                            if (key.equals("path")) {
                                path = reader.nextString();
                            } else if (key.equals("size")) {
                                size = String.valueOf(reader.nextLong());
                            } else {
                                reader.skipValue();
                            }
                        }
                        reader.endObject();
                        if (path != null) {
                            files.add(new String[]{path, size});
                        }
                    }
                    reader.endArray();
                } else {
                    reader.skipValue();
                }
            }
            reader.endObject();
            reader.close();
            return files;
        } catch (Exception e) {
            return null;
        }
    }

    static long parseLong(String s) {
        try {
            return Long.parseLong(s);
        } catch (Exception e) {
            return 0;
        }
    }

    static String human(long bytes) {
        String[] units = {"b", "kb", "mb", "gb", "tb", "pb"};
        double value = bytes;
        int unit = 0;
        while (value >= 1024.0 && unit < units.length - 1) {
            value /= 1024.0;
            unit++;
        }
        if (value >= 100.0) {
            return String.format("%.0f %s", value, units[unit]);
        }
        return String.format("%.1f %s", value, units[unit]);
    }

    static String mapNetworkError(Exception e) {
        String msg = String.valueOf(e.getMessage());
        if (msg.startsWith("FIL-") || msg.startsWith("UPD-")) {
            return msg;
        }
        if (msg.contains("Unable to resolve host")) {
            return "NET-001 No internet connection.";
        }
        if (msg.contains("timeout")) {
            return "NET-003 Server answered too late.";
        }
        return "NET-002 Unable to reach server.";
    }

    static void deleteRecursive(File f) {
        File[] kids = f.listFiles();
        if (kids != null) {
            for (File k : kids) {
                deleteRecursive(k);
            }
        }
        f.delete();
    }
}

class SetStatusTask implements Runnable {
    private final MainActivity act;
    private final String text;

    SetStatusTask(MainActivity act, String text) {
        this.act = act;
        this.text = text;
    }

    public void run() {
        act.status.setText(text);
    }
}

class FailTask implements Runnable {
    private final MainActivity act;
    private final String code;
    private final String reason;

    FailTask(MainActivity act, String code, String reason) {
        this.act = act;
        this.code = code;
        this.reason = reason;
    }

    public void run() {
        act.status.setText("Oh snap-\n\nThe app could not be installed. Error: " + code + "\n\n" + reason);
    }
}

class StartAppTask implements Runnable {
    private final MainActivity act;

    StartAppTask(MainActivity act) {
        this.act = act;
    }

    public void run() {
        act.web = new WebView(act);
        WebSettings s = act.web.getSettings();
        s.setJavaScriptEnabled(true);
        s.setDomStorageEnabled(true);
        s.setAllowFileAccess(true);
        s.setMediaPlaybackRequiresUserGesture(false);
        s.setDatabaseEnabled(true);
        act.web.setWebViewClient(new WebViewClient());
        act.web.addJavascriptInterface(new WBBridge(act), "WeildBuildMobile");
        act.web.loadUrl("file://" + new File(WbPaths.appDir(act), "index.html").getAbsolutePath());
        act.root.removeAllViews();
        act.root.addView(act.web);
    }
}

class InstallTask implements Runnable {
    private final MainActivity act;

    InstallTask(MainActivity act) {
        this.act = act;
    }

    public void run() {
        act.runOnUiThread(new SetStatusTask(act, "WeildBuild\n\nChecking the servers..."));
        try {
            byte[] versionBytes = WbPaths.fetchBytes(WbPaths.REPO_RAW + "/wb-version.json");
            String version = WbPaths.parseVersion(new String(versionBytes, StandardCharsets.UTF_8));
            act.runOnUiThread(new SetStatusTask(act, "WeildBuild " + version + "\n\nChecking how big the update is..."));
            byte[] manifestBytes = WbPaths.fetchBytes(WbPaths.REPO_RAW + "/wb-files.json");
            String manifest = new String(manifestBytes, StandardCharsets.UTF_8);
            List<String[]> files = WbPaths.parseManifest(manifest);
            if (files == null || files.isEmpty()) {
                act.fail("UPD-005", "Invalid update information.");
                return;
            }
            long total = 0;
            for (String[] f : files) {
                total += WbPaths.parseLong(f[1]);
            }
            act.runOnUiThread(new SetStatusTask(act, "WeildBuild " + version + "\n\nUpdate size: " + WbPaths.human(total)
                    + " (" + files.size() + " files)\n\nDon't close the app yet, please!"));
            int i = 0;
            File appDir = WbPaths.appDir(act);
            for (String[] f : files) {
                i++;
                String path = f[0];
                act.runOnUiThread(new SetStatusTask(act, "Installing " + i + "/" + files.size() + "\n" + path));
                File dest = new File(appDir, path);
                File parent = dest.getParentFile();
                if (parent != null && !parent.isDirectory() && !parent.mkdirs()) {
                    act.fail("FIL-007", "Couldn't write file: " + path);
                    return;
                }
                byte[] data = WbPaths.fetchBytes(WbPaths.REPO_RAW + "/" + path);
                FileOutputStream out = new FileOutputStream(dest);
                out.write(data);
                out.close();
            }
            FileOutputStream vout = new FileOutputStream(new File(appDir, "wb-version.json"));
            vout.write(("version = \"" + version + "\"").getBytes(StandardCharsets.UTF_8));
            vout.close();
            act.runOnUiThread(new StartAppTask(act));
        } catch (Exception e) {
            act.fail(WbPaths.mapNetworkError(e), String.valueOf(e.getMessage()));
        }
    }
}

class WBBridge {
    private final MainActivity act;

    WBBridge(MainActivity act) {
        this.act = act;
    }

    @JavascriptInterface
    public String estimateStorage() {
        StatFs stat = new StatFs(act.getFilesDir().getPath());
        return String.valueOf(stat.getAvailableBytes());
    }

    @JavascriptInterface
    public String getLocalVersion() {
        try {
            FileInputStream in = new FileInputStream(new File(WbPaths.appDir(act), "wb-version.json"));
            ByteArrayOutputStream out = new ByteArrayOutputStream();
            byte[] buf = new byte[4096];
            int n;
            while ((n = in.read(buf)) > 0) {
                out.write(buf, 0, n);
            }
            in.close();
            return WbPaths.parseVersion(new String(out.toByteArray(), StandardCharsets.UTF_8));
        } catch (Exception e) {
            return "";
        }
    }

    @JavascriptInterface
    public String stageFile(String path, String base64) {
        try {
            byte[] data = Base64.decode(base64, Base64.NO_WRAP);
            File dest = new File(WbPaths.stagingDir(act), path);
            File parent = dest.getParentFile();
            if (parent != null && !parent.isDirectory() && !parent.mkdirs()) {
                return "err";
            }
            FileOutputStream out = new FileOutputStream(dest);
            out.write(data);
            out.close();
            return "ok";
        } catch (Exception e) {
            return "err";
        }
    }

    @JavascriptInterface
    public String commitUpdate(String version) {
        try {
            File staging = WbPaths.stagingDir(act);
            File appDir = WbPaths.appDir(act);
            File[] staged = staging.listFiles();
            if (staged != null) {
                for (File f : staged) {
                    File dest = new File(appDir, f.getName());
                    File parent = dest.getParentFile();
                    if (parent != null && !parent.isDirectory() && !parent.mkdirs()) {
                        return "err";
                    }
                    if (dest.exists() && !dest.delete()) {
                        return "err";
                    }
                    if (!f.renameTo(dest)) {
                        return "err";
                    }
                }
            }
            WbPaths.deleteRecursive(staging);
            FileOutputStream vout = new FileOutputStream(new File(appDir, "wb-version.json"));
            vout.write(("version = \"" + version + "\"").getBytes(StandardCharsets.UTF_8));
            vout.close();
            return "ok";
        } catch (Exception e) {
            return "err";
        }
    }
}

public class MainActivity extends Activity {

    FrameLayout root;
    TextView status;
    WebView web;

    @Override
    protected void onCreate(Bundle savedInstanceState) {
        super.onCreate(savedInstanceState);
        root = new FrameLayout(this);
        status = new TextView(this);
        status.setTextColor(Color.WHITE);
        status.setBackgroundColor(Color.parseColor("#10131f"));
        status.setPadding(48, 48, 48, 48);
        status.setTextSize(16);
        root.addView(status);
        setContentView(root);
        if (!new File(WbPaths.appDir(this), "index.html").exists()) {
            new Thread(new InstallTask(this)).start();
        } else {
            runOnUiThread(new StartAppTask(this));
        }
    }

    void fail(String code, String reason) {
        runOnUiThread(new FailTask(this, code, reason));
    }

    @Override
    public void onBackPressed() {
        if (web != null && web.canGoBack()) {
            web.goBack();
        } else {
            super.onBackPressed();
        }
    }
}
