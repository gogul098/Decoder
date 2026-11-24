package com.gogul.newsdecoded;

import android.content.Context;
import android.content.Intent;
import android.net.Uri;
import android.text.format.DateUtils;
import android.widget.RemoteViews;
import android.widget.RemoteViewsService;

import org.json.JSONArray;
import org.json.JSONObject;

/** Supplies the widget's story rows from the stories saved by NewsSync. */
public class NewsWidgetService extends RemoteViewsService {
    @Override
    public RemoteViewsFactory onGetViewFactory(Intent intent) {
        return new Factory(getApplicationContext());
    }

    static final class Factory implements RemoteViewsFactory {
        private final Context c;
        private JSONArray items = new JSONArray();
        private NewsStore.Palette p;

        Factory(Context c) { this.c = c; }

        @Override public void onCreate() {}
        @Override public void onDestroy() {}

        @Override
        public void onDataSetChanged() {
            p = NewsStore.palette(c);
            try {
                items = new JSONArray(NewsStore.prefs(c).getString("items", "[]"));
            } catch (Exception e) {
                items = new JSONArray();
            }
        }

        @Override public int getCount() { return items.length(); }

        @Override
        public RemoteViews getViewAt(int position) {
            RemoteViews row = new RemoteViews(c.getPackageName(), R.layout.widget_row);
            try {
                JSONObject it = items.getJSONObject(position);
                if (p == null) p = NewsStore.palette(c);
                String ago = DateUtils.getRelativeTimeSpanString(it.optLong("published") * 1000L,
                        System.currentTimeMillis(), DateUtils.MINUTE_IN_MILLIS, DateUtils.FORMAT_ABBREV_RELATIVE).toString();
                row.setTextViewText(R.id.row_rank, String.valueOf(it.optInt("rank", position + 1)));
                row.setTextViewText(R.id.row_topic, it.optString("label") + "  ·  " + ago);
                row.setTextViewText(R.id.row_title, it.optString("title"));
                row.setInt(R.id.row_rank_frame, "setBackgroundColor", p.edge);
                row.setInt(R.id.row_rank, "setBackgroundColor", NewsStore.categoryColor(p, it.optString("category")));
                row.setTextColor(R.id.row_topic, p.mute);
                row.setTextColor(R.id.row_title, p.ink);
                row.setInt(R.id.row_divider, "setBackgroundColor", p.rule);
                Intent fill = new Intent();
                fill.setData(Uri.parse("decoded://s/" + it.optString("id")));
                row.setOnClickFillInIntent(R.id.row_root, fill);
            } catch (Exception ignored) {}
            return row;
        }

        @Override public RemoteViews getLoadingView() { return null; }
        @Override public int getViewTypeCount() { return 1; }
        @Override public long getItemId(int position) { return position; }
        @Override public boolean hasStableIds() { return false; }
    }
}
