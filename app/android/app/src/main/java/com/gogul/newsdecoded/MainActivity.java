package com.gogul.newsdecoded;

import android.os.Build;
import android.os.Bundle;

import com.getcapacitor.BridgeActivity;

import java.io.PrintWriter;
import java.io.StringWriter;

public class MainActivity extends BridgeActivity {
    @Override
    public void onCreate(Bundle savedInstanceState) {
        installCrashRecorder();
        registerPlugin(DecodedNativePlugin.class);
        super.onCreate(savedInstanceState);
    }

    /** If the app ever crashes, keep the error so Settings can show it next time (then crash as usual). */
    private void installCrashRecorder() {
        final Thread.UncaughtExceptionHandler previous = Thread.getDefaultUncaughtExceptionHandler();
        if (previous instanceof Recorder) return;
        Thread.setDefaultUncaughtExceptionHandler(new Recorder(previous));
    }

    private final class Recorder implements Thread.UncaughtExceptionHandler {
        private final Thread.UncaughtExceptionHandler next;

        Recorder(Thread.UncaughtExceptionHandler next) { this.next = next; }

        @Override
        public void uncaughtException(Thread t, Throwable e) {
            try {
                StringWriter sw = new StringWriter();
                e.printStackTrace(new PrintWriter(sw));
                String report = "Decoded " + BuildConfig.VERSION_NAME + " · Android " + Build.VERSION.RELEASE
                        + " (API " + Build.VERSION.SDK_INT + ") · " + Build.MANUFACTURER + " " + Build.MODEL
                        + "\nThread: " + t.getName() + "\n\n" + sw;
                NewsStore.prefs(getApplicationContext()).edit()
                        .putString("last_crash", report.length() > 12000 ? report.substring(0, 12000) : report).commit();
            } catch (Throwable ignored) {}
            if (next != null) next.uncaughtException(t, e);
        }
    }
}
