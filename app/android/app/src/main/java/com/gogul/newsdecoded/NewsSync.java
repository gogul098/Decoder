package com.gogul.newsdecoded;

import android.app.Notification;
import android.app.NotificationChannel;
import android.app.NotificationManager;
import android.app.PendingIntent;
import android.app.job.JobInfo;
import android.app.job.JobScheduler;
import android.content.ComponentName;
import android.content.Context;
import android.content.Intent;
import android.content.SharedPreferences;
import android.content.pm.PackageManager;
import android.net.Uri;
import android.os.Build;

import org.json.JSONArray;
import org.json.JSONObject;

import java.util.ArrayList;
import java.util.HashSet;
import java.util.List;
import java.util.Set;

/** Fetches the latest stories for the widget and posts "new stories" alerts. */
final class NewsSync {
    static final int JOB_PERIODIC = 4101;   // every 3–4 hours: refresh + alert
    static final int JOB_NOW = 4102;        // one-off: refresh the widget now
    static final String CHANNEL = "news_alerts";
    private static final long HOUR = 60L * 60L * 1000L;

    private NewsSync() {}

    /** Schedule the background check: once in every 3-hour period, in its last hour (so every 3–4 h). */
    static void schedule(Context c) {
        try {
            scheduleUnsafe(c);
        } catch (Exception e) {
            android.util.Log.w("Decoded", "could not schedule news alerts", e);
        }
    }

    private static void scheduleUnsafe(Context c) {
        JobScheduler js = (JobScheduler) c.getSystemService(Context.JOB_SCHEDULER_SERVICE);
        if (js == null) return;
        if (Build.VERSION.SDK_INT >= 24 && js.getPendingJob(JOB_PERIODIC) != null) return;
        JobInfo.Builder b = new JobInfo.Builder(JOB_PERIODIC, new ComponentName(c, NewsJobService.class))
                .setRequiredNetworkType(JobInfo.NETWORK_TYPE_ANY)
                .setPersisted(true);
        if (Build.VERSION.SDK_INT >= 24) b.setPeriodic(3 * HOUR, HOUR);
        else b.setPeriodic(3 * HOUR);
        js.schedule(b.build());
    }

    static void refreshNow(Context c) {
        try {
            JobScheduler js = (JobScheduler) c.getSystemService(Context.JOB_SCHEDULER_SERVICE);
            if (js == null) return;
            js.schedule(new JobInfo.Builder(JOB_NOW, new ComponentName(c, NewsJobService.class))
                    .setRequiredNetworkType(JobInfo.NETWORK_TYPE_ANY)
                    .build());
        } catch (Exception e) {
            // fall back to a plain background thread
            new Thread(() -> run(c.getApplicationContext(), false)).start();
        }
    }

    /** Runs on a background thread. */
    static synchronized void run(Context c, boolean alert) {
        SharedPreferences prefs = NewsStore.prefs(c);
        try {
            String api = NewsStore.apiBase(c);
            if (api.isEmpty()) return;
            // the free server may be asleep: allow time for it to wake and collect news
            JSONObject d = new JSONObject(NewsStore.httpGet(api + "/api/digest?per=3&lang=" + prefs.getString("lang", "en"), 110000));
            JSONArray items = d.getJSONArray("items");
            prefs.edit().putString("items", items.toString()).putLong("updated", System.currentTimeMillis()).apply();
            if (alert && prefs.getBoolean("alerts", true)) notifyNew(c, items);
            else markSeen(prefs, items);
        } catch (Throwable ignored) {
            // offline or server down: keep the last stories, try again next time
        } finally {
            prefs.edit().putBoolean("refreshing", false).apply();
            try { NewsWidget.updateAll(c); } catch (Throwable ignored) {}
        }
    }

    private static Set<String> seen(SharedPreferences prefs) {
        Set<String> out = new HashSet<>();
        try {
            JSONArray a = new JSONArray(prefs.getString("seen", "[]"));
            for (int i = 0; i < a.length(); i++) out.add(a.getString(i));
        } catch (Exception ignored) {}
        return out;
    }

    private static void markSeen(SharedPreferences prefs, JSONArray items) {
        try {
            JSONArray old = new JSONArray(prefs.getString("seen", "[]"));
            JSONArray merged = new JSONArray();
            Set<String> have = new HashSet<>();
            for (int i = 0; i < items.length(); i++) {
                String id = items.getJSONObject(i).getString("id");
                if (have.add(id)) merged.put(id);
            }
            for (int i = 0; i < old.length() && merged.length() < 300; i++) {
                String id = old.getString(i);
                if (have.add(id)) merged.put(id);
            }
            prefs.edit().putString("seen", merged.toString()).apply();
        } catch (Exception ignored) {}
    }

    private static void notifyNew(Context c, JSONArray items) throws Exception {
        SharedPreferences prefs = NewsStore.prefs(c);
        Set<String> seen = seen(prefs);
        boolean firstRun = seen.isEmpty();
        List<JSONObject> fresh = new ArrayList<>();
        for (int i = 0; i < items.length(); i++) {
            JSONObject it = items.getJSONObject(i);
            if (!seen.contains(it.getString("id"))) fresh.add(it);
        }
        markSeen(prefs, items);
        if (firstRun || fresh.isEmpty()) return;
        if (Build.VERSION.SDK_INT >= 33
                && c.checkSelfPermission("android.permission.POST_NOTIFICATIONS") != PackageManager.PERMISSION_GRANTED) return;

        NotificationManager nm = (NotificationManager) c.getSystemService(Context.NOTIFICATION_SERVICE);
        if (nm == null) return;
        if (Build.VERSION.SDK_INT >= 26) {
            NotificationChannel ch = new NotificationChannel(CHANNEL, "New stories", NotificationManager.IMPORTANCE_DEFAULT);
            ch.setDescription("A ring every 3–4 hours when fresh stories arrive");
            nm.createNotificationChannel(ch);
        }

        // One notification per new story (up to 4), grouped under a summary, so tapping any of
        // them opens that story decoded in the app. The group rings once.
        NewsStore.Palette p = NewsStore.palette(c);
        String lang = prefs.getString("lang", "en");
        String group = "decoded_news";
        int shown = Math.min(4, fresh.size());
        for (int i = 0; i < shown; i++) {
            JSONObject it = fresh.get(i);
            String id = it.getString("id");
            Intent open = new Intent(Intent.ACTION_VIEW, Uri.parse("decoded://s/" + id), c, MainActivity.class);
            PendingIntent pi = PendingIntent.getActivity(c, id.hashCode(), open,
                    PendingIntent.FLAG_IMMUTABLE | PendingIntent.FLAG_UPDATE_CURRENT);
            Notification.Builder nb = Build.VERSION.SDK_INT >= 26 ? new Notification.Builder(c, CHANNEL) : new Notification.Builder(c);
            nb.setSmallIcon(R.drawable.ic_stat_decoded)
              .setColor(NewsStore.categoryColor(p, it.optString("category")))
              .setContentTitle(it.getString("title"))
              .setContentText(it.optString("label"))
              .setStyle(new Notification.BigTextStyle().bigText(it.getString("title")))
              .setSubText(it.optString("label"))
              .setContentIntent(pi)
              .setAutoCancel(true)
              .setWhen(it.optLong("published", System.currentTimeMillis() / 1000) * 1000L)
              .setShowWhen(true);
            if (Build.VERSION.SDK_INT >= 24) nb.setGroup(group);
            if (Build.VERSION.SDK_INT >= 26) nb.setGroupAlertBehavior(Notification.GROUP_ALERT_SUMMARY);
            else if (i == 0) nb.setDefaults(Notification.DEFAULT_ALL);
            nm.notify(6000 + Math.abs(id.hashCode() % 900), nb.build());
        }

        if (Build.VERSION.SDK_INT >= 24) {
            Notification.InboxStyle inbox = new Notification.InboxStyle().setSummaryText("Decoded");
            for (int i = 0; i < shown; i++) {
                JSONObject it = fresh.get(i);
                inbox.addLine(it.optString("label") + " · " + it.getString("title"));
            }
            Intent home = new Intent(Intent.ACTION_VIEW, Uri.parse("decoded://home"), c, MainActivity.class);
            PendingIntent hp = PendingIntent.getActivity(c, 7, home, PendingIntent.FLAG_IMMUTABLE | PendingIntent.FLAG_UPDATE_CURRENT);
            Notification.Builder sb = Build.VERSION.SDK_INT >= 26 ? new Notification.Builder(c, CHANNEL) : new Notification.Builder(c);
            sb.setSmallIcon(R.drawable.ic_stat_decoded)
              .setColor(p.colors[0])
              .setContentTitle(newStories(lang, fresh.size()))
              .setContentText(fresh.get(0).getString("title"))
              .setStyle(inbox)
              .setGroup(group)
              .setGroupSummary(true)
              .setContentIntent(hp)
              .setAutoCancel(true)
              .setNumber(fresh.size());
            if (Build.VERSION.SDK_INT < 26) sb.setDefaults(Notification.DEFAULT_ALL);
            nm.notify(5150, sb.build());
        }
    }

    /** "N new stories" in the reader's language. */
    private static String newStories(String lang, int n) {
        switch (lang == null ? "en" : lang) {
            case "hi": return n + " नई ख़बरें";
            case "ta": return n + " புதிய செய்திகள்";
            case "te": return n + " కొత్త వార్తలు";
            case "kn": return n + " ಹೊಸ ಸುದ್ದಿಗಳು";
            case "ml": return n + " പുതിയ വാർത്തകൾ";
            case "mr": return n + " नवीन बातम्या";
            case "bn": return n + "টি নতুন খবর";
            case "gu": return n + " નવા સમાચાર";
            case "pa": return n + " ਨਵੀਆਂ ਖ਼ਬਰਾਂ";
            case "or": return n + "ଟି ନୂଆ ଖବର";
            case "ur": return n + " نئی خبریں";
            default: return n + " new stories, decoded";
        }
    }
}
