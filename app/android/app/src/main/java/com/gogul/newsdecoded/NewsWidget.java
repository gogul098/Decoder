package com.gogul.newsdecoded;

import android.app.PendingIntent;
import android.appwidget.AppWidgetManager;
import android.appwidget.AppWidgetProvider;
import android.content.ComponentName;
import android.content.Context;
import android.content.Intent;
import android.content.res.ColorStateList;
import android.net.Uri;
import android.os.Build;
import android.widget.RemoteViews;

import java.text.DateFormat;
import java.util.Date;

/** Home-screen widget: today's top stories from every topic, drawn like the app's paper cards. */
public class NewsWidget extends AppWidgetProvider {
    static final String ACTION_REFRESH = "com.gogul.newsdecoded.WIDGET_REFRESH";

    @Override
    public void onUpdate(Context c, AppWidgetManager m, int[] ids) {
        for (int id : ids) m.updateAppWidget(id, build(c, id));
        m.notifyAppWidgetViewDataChanged(ids, R.id.widget_list);
        NewsSync.schedule(c);
        if (NewsStore.prefs(c).getString("items", "").isEmpty()) NewsSync.refreshNow(c);
    }

    @Override
    public void onEnabled(Context c) {
        NewsSync.schedule(c);
        NewsSync.refreshNow(c);
    }

    @Override
    public void onReceive(Context c, Intent intent) {
        super.onReceive(c, intent);
        if (ACTION_REFRESH.equals(intent.getAction())) {
            NewsStore.prefs(c).edit().putBoolean("refreshing", true).apply();
            updateAll(c);
            NewsSync.refreshNow(c);
        }
    }

    static void updateAll(Context c) {
        AppWidgetManager m = AppWidgetManager.getInstance(c);
        int[] ids = m.getAppWidgetIds(new ComponentName(c, NewsWidget.class));
        if (ids == null || ids.length == 0) return;
        for (int id : ids) m.updateAppWidget(id, build(c, id));
        m.notifyAppWidgetViewDataChanged(ids, R.id.widget_list);
    }

    private static void tint(RemoteViews v, int viewId, int color) {
        if (Build.VERSION.SDK_INT >= 31) {
            v.setColorStateList(viewId, "setBackgroundTintList", ColorStateList.valueOf(color));
        }
    }

    static RemoteViews build(Context c, int widgetId) {
        NewsStore.Palette p = NewsStore.palette(c);
        RemoteViews v = new RemoteViews(c.getPackageName(), R.layout.widget_news);

        // theme: hard shadow in the accent colour, ink outline, paper card
        tint(v, R.id.widget_shadow, NewsStore.isDark(c) ? p.colors[0] : p.edge);
        tint(v, R.id.widget_border, p.edge);
        tint(v, R.id.widget_card, p.paper);
        tint(v, R.id.widget_mark_bar, p.colors[0]);
        v.setTextColor(R.id.widget_title, p.ink);
        v.setTextColor(R.id.widget_sub, p.mute);
        v.setTextColor(R.id.widget_empty, p.mute);
        v.setInt(R.id.widget_rule, "setBackgroundColor", p.edge);
        v.setInt(R.id.widget_refresh, "setColorFilter", p.ink);

        long updated = NewsStore.prefs(c).getLong("updated", 0);
        boolean refreshing = NewsStore.prefs(c).getBoolean("refreshing", false);
        String sub = refreshing ? "Fetching fresh news…"
                : updated > 0 ? "Top stories · " + DateFormat.getTimeInstance(DateFormat.SHORT).format(new Date(updated))
                : "Top stories";
        v.setTextViewText(R.id.widget_sub, sub);

        // open the app from the header
        Intent open = new Intent(c, MainActivity.class);
        v.setOnClickPendingIntent(R.id.widget_header, PendingIntent.getActivity(c, 11, open,
                PendingIntent.FLAG_IMMUTABLE | PendingIntent.FLAG_UPDATE_CURRENT));

        // refresh button
        Intent refresh = new Intent(c, NewsWidget.class).setAction(ACTION_REFRESH);
        v.setOnClickPendingIntent(R.id.widget_refresh, PendingIntent.getBroadcast(c, 12, refresh,
                PendingIntent.FLAG_IMMUTABLE | PendingIntent.FLAG_UPDATE_CURRENT));

        // the scrolling list of stories
        Intent svc = new Intent(c, NewsWidgetService.class);
        svc.putExtra(AppWidgetManager.EXTRA_APPWIDGET_ID, widgetId);
        svc.setData(Uri.parse(svc.toUri(Intent.URI_INTENT_SCHEME)));
        v.setRemoteAdapter(R.id.widget_list, svc);
        v.setEmptyView(R.id.widget_list, R.id.widget_empty);

        int flags = PendingIntent.FLAG_UPDATE_CURRENT | (Build.VERSION.SDK_INT >= 31 ? PendingIntent.FLAG_MUTABLE : 0);
        Intent tap = new Intent(Intent.ACTION_VIEW);
        tap.setClass(c, MainActivity.class);
        v.setPendingIntentTemplate(R.id.widget_list, PendingIntent.getActivity(c, 13, tap, flags));
        return v;
    }
}
