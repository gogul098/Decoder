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
        JobScheduler js = (JobScheduler) c.getSystemService(Context.JOB_SCHEDULER_SERVICE);
        if (js == null) return;
        js.schedule(new JobInfo.Builder(JOB_NOW, new ComponentName(c, NewsJobService.class))
                .setRequiredNetworkType(JobInfo.NETWORK_TYPE_ANY)
                .build());
    }

    /** Runs on a background thread. */
    static synchronized void run(Context c, boolean alert) {
        SharedPreferences prefs = NewsStore.prefs(c);
        try {
            String api = NewsStore.apiBase(c);
            if (api.isEmpty()) return;
            // the free server may be asleep: allow time for it to wake and collect news
            JSONObject d = new JSONObject(NewsStore.httpGet(api + "/api/digest?per=3", 110000));
            JSONArray items = d.getJSONArray("items");
            prefs.edit().putString("items", items.toString()).putLong("updated", System.currentTimeMillis()).apply();
            if (alert && prefs.getBoolean("alerts", true)) notifyNew(c, items);
            else markSeen(prefs, items);
        } catch (Exception ignored) {
            // offline or server down: keep the last stories, try again next time
        } finally {
            prefs.edit().putBoolean("refreshing", false).apply();
            NewsWidget.updateAll(c);
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

        JSONObject first = fresh.get(0);
        String title = fresh.size() == 1 ? first.getString("title") : fresh.size() + " new stories, decoded";
        String text = fresh.size() == 1 ? first.optString("label") + " · tap to read why it happened"
                : first.optString("label") + ": " + first.getString("title");

        Notification.InboxStyle inbox = new Notification.InboxStyle().setSummaryText("Decoded");
        for (int i = 0; i < Math.min(5, fresh.size()); i++) {
            JSONObject it = fresh.get(i);
            inbox.addLine(it.optString("label") + " · " + it.getString("title"));
        }

        Uri link = Uri.parse(fresh.size() == 1 ? "decoded://s/" + first.getString("id") : "decoded://home");
        Intent open = new Intent(Intent.ACTION_VIEW, link, c, MainActivity.class);
        PendingIntent pi = PendingIntent.getActivity(c, 7, open, PendingIntent.FLAG_IMMUTABLE | PendingIntent.FLAG_UPDATE_CURRENT);

        NewsStore.Palette p = NewsStore.palette(c);
        Notification.Builder nb = Build.VERSION.SDK_INT >= 26 ? new Notification.Builder(c, CHANNEL) : new Notification.Builder(c);
        nb.setSmallIcon(R.drawable.ic_stat_decoded)
          .setColor(NewsStore.categoryColor(p, first.optString("category")))
          .setContentTitle(title)
          .setContentText(text)
          .setStyle(fresh.size() > 1 ? inbox : new Notification.BigTextStyle().bigText(text))
          .setContentIntent(pi)
          .setAutoCancel(true)
          .setNumber(fresh.size());
        if (Build.VERSION.SDK_INT < 26) nb.setDefaults(Notification.DEFAULT_ALL);
        nm.notify(5150, nb.build());
    }
}
