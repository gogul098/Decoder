package com.gogul.newsdecoded;

import android.app.job.JobParameters;
import android.app.job.JobService;

/** Runs the news check off the main thread for both the periodic alert job and refresh-now. */
public class NewsJobService extends JobService {
    @Override
    public boolean onStartJob(final JobParameters params) {
        final boolean alert = params.getJobId() == NewsSync.JOB_PERIODIC;
        new Thread(() -> {
            NewsSync.run(getApplicationContext(), alert);
            jobFinished(params, false);
        }).start();
        return true;
    }

    @Override
    public boolean onStopJob(JobParameters params) {
        return true; // try again later
    }
}
