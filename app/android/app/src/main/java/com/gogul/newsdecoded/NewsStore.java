package com.gogul.newsdecoded;

import android.content.Context;
import android.content.SharedPreferences;
import android.content.res.Configuration;
import android.graphics.Color;

import org.json.JSONObject;

import java.io.ByteArrayOutputStream;
import java.io.IOException;
import java.io.InputStream;
import java.net.HttpURLConnection;
import java.net.URL;
import java.nio.charset.StandardCharsets;

/** Shared settings, colours and HTTP for the widget and the news alerts. */
final class NewsStore {
    static final String PREFS = "decoded_native";
    static final String CONFIG_URL = "https://raw.githubusercontent.com/gogul098/Decoder/main/config/app.json";

    private NewsStore() {}

    static SharedPreferences prefs(Context c) {
        return c.getSharedPreferences(PREFS, Context.MODE_PRIVATE);
    }

    static String httpGet(String url, int timeoutMs) throws IOException {
        HttpURLConnection con = (HttpURLConnection) new URL(url).openConnection();
        con.setConnectTimeout(timeoutMs);
        con.setReadTimeout(timeoutMs);
        con.setRequestProperty("Accept", "application/json");
        con.setRequestProperty("User-Agent", "DecodedApp/1.0 (Android)");
        try {
            int code = con.getResponseCode();
            if (code >= 400) throw new IOException("HTTP " + code);
            try (InputStream in = con.getInputStream(); ByteArrayOutputStream out = new ByteArrayOutputStream()) {
                byte[] buf = new byte[8192];
                int n;
                while ((n = in.read(buf)) > 0) out.write(buf, 0, n);
                return new String(out.toByteArray(), StandardCharsets.UTF_8);
            }
        } finally {
            con.disconnect();
        }
    }

    /** Server address: the one the app synced, else the one published on GitHub. */
    static String apiBase(Context c) {
        String api = prefs(c).getString("api", "");
        if (api == null || api.isEmpty()) {
            try {
                JSONObject cfg = new JSONObject(httpGet(CONFIG_URL + "?t=" + System.currentTimeMillis(), 15000));
                api = cfg.optString("api_base", "");
                if (!api.isEmpty()) prefs(c).edit().putString("api", api).apply();
            } catch (Exception ignored) {
                api = "";
            }
        }
        while (api.endsWith("/")) api = api.substring(0, api.length() - 1);
        return api;
    }

    // ---------- the same colour themes as the app ----------
    static final class Palette {
        int desk, paper, ink, mute, rule, edge;
        int[] colors; // yellow, pink, mint, blue, lilac, orange, red
    }

    private static final String[][] THEMES = {
        // id,        desk,     paper,    deskDark, paperDark, yellow,  pink,     mint,     blue,     lilac,    orange,   red
        {"classic",   "#f6f4ef", "#fffefb", "#141414", "#1d1d1c", "#ffd23f", "#ff7ab6", "#5ce1b6", "#6b95ff", "#b9a3ff", "#ff8a3d", "#ff6464"},
        {"newsprint", "#ece8de", "#faf7ef", "#1a1915", "#25231e", "#ecd896", "#e7b4aa", "#b5d2bd", "#b0c3dd", "#cabfdd", "#e9be93", "#d98a7e"},
        {"ocean",     "#e9f1f4", "#fafdfe", "#0d181d", "#142229", "#ffd166", "#90e0ef", "#2ec4b6", "#4d8dff", "#8ecae6", "#ffb703", "#fb6f92"},
        {"sunset",    "#fbefe7", "#fffaf6", "#1d1311", "#2a1b18", "#ffc857", "#ff6b9a", "#ffa69e", "#ff8c61", "#c38d9e", "#f9844a", "#e63946"},
        {"forest",    "#edf1e8", "#fbfdf8", "#111812", "#19221a", "#e9c46a", "#f4a261", "#8ac926", "#2a9d8f", "#a7c957", "#e76f51", "#d1495b"},
        {"grape",     "#f2eff8", "#fdfbff", "#16121e", "#211b2b", "#ffd6a5", "#ff8fc6", "#9bf6ff", "#a0c4ff", "#bdb2ff", "#ffadad", "#ff6b8b"},
    };

    static boolean isDark(Context c) {
        String mode = prefs(c).getString("mode", "system");
        if ("dark".equals(mode)) return true;
        if ("light".equals(mode)) return false;
        int night = c.getResources().getConfiguration().uiMode & Configuration.UI_MODE_NIGHT_MASK;
        return night == Configuration.UI_MODE_NIGHT_YES;
    }

    static Palette palette(Context c) {
        String id = prefs(c).getString("theme", "classic");
        String[] t = THEMES[0];
        for (String[] row : THEMES) if (row[0].equals(id)) t = row;
        boolean dark = isDark(c);
        Palette p = new Palette();
        p.desk = Color.parseColor(dark ? t[3] : t[1]);
        p.paper = Color.parseColor(dark ? t[4] : t[2]);
        p.ink = Color.parseColor(dark ? "#efede7" : "#161614");
        p.mute = Color.parseColor(dark ? "#8f8c83" : "#8a877d");
        p.rule = Color.parseColor(dark ? "#2d2c29" : "#e6e2d8");
        p.edge = p.ink;
        p.colors = new int[7];
        for (int i = 0; i < 7; i++) p.colors[i] = Color.parseColor(t[5 + i]);
        return p;
    }

    /** Category colour, same mapping as the app's tabs. */
    static int categoryColor(Palette p, String cat) {
        switch (cat == null ? "" : cat) {
            case "india": return p.colors[5];
            case "world": return p.colors[2];
            case "markets": return p.colors[4];
            case "oil": return p.colors[0];
            case "security": return p.colors[6];
            default: return p.colors[3]; // tech
        }
    }
}
