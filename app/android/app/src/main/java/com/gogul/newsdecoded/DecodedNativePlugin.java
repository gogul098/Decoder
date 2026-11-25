package com.gogul.newsdecoded;

import android.content.SharedPreferences;
import android.content.pm.PackageManager;
import android.os.Build;

import com.getcapacitor.JSObject;
import com.getcapacitor.Plugin;
import com.getcapacitor.PluginCall;
import com.getcapacitor.PluginMethod;
import com.getcapacitor.annotation.CapacitorPlugin;

/** Bridge from the web app: shares the server address, theme and alert setting with the
 *  widget and the background alerts, and asks for notification permission. */
@CapacitorPlugin(name = "DecodedNative")
public class DecodedNativePlugin extends Plugin {

    @PluginMethod
    public void sync(PluginCall call) {
        SharedPreferences.Editor e = NewsStore.prefs(getContext()).edit();
        String api = call.getString("api", "");
        if (api != null && !api.isEmpty()) e.putString("api", api);
        e.putString("theme", call.getString("theme", "classic"));
        e.putString("mode", call.getString("mode", "system"));
        String lang = call.getString("lang", "en");
        String oldLang = NewsStore.prefs(getContext()).getString("lang", "en");
        e.putString("lang", lang == null ? "en" : lang);
        Boolean alerts = call.getBoolean("alerts", true);
        e.putBoolean("alerts", alerts == null || alerts);
        e.apply();
        try {
            NewsSync.schedule(getContext());
            NewsWidget.updateAll(getContext());
            if (lang != null && !lang.equals(oldLang)) NewsSync.refreshNow(getContext());   // widget in the new language
        } catch (Throwable t) {
            android.util.Log.w("Decoded", "widget/alerts sync failed", t);
        }
        call.resolve();
    }

    @PluginMethod
    public void requestNotifications(PluginCall call) {
        try {
            if (Build.VERSION.SDK_INT >= 33 && getActivity() != null
                    && getContext().checkSelfPermission("android.permission.POST_NOTIFICATIONS") != PackageManager.PERMISSION_GRANTED) {
                getActivity().runOnUiThread(() -> {
                    try {
                        getActivity().requestPermissions(new String[]{"android.permission.POST_NOTIFICATIONS"}, 4711);
                    } catch (Throwable ignored) {}
                });
            }
        } catch (Throwable ignored) {}
        call.resolve();
    }

    @PluginMethod
    public void refreshWidget(PluginCall call) {
        NewsSync.refreshNow(getContext());
        call.resolve();
    }

    @PluginMethod
    public void lastCrash(PluginCall call) {
        JSObject ret = new JSObject();
        ret.put("report", NewsStore.prefs(getContext()).getString("last_crash", ""));
        call.resolve(ret);
    }

    @PluginMethod
    public void clearCrash(PluginCall call) {
        NewsStore.prefs(getContext()).edit().remove("last_crash").apply();
        call.resolve();
    }
}
