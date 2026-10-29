// Paste into the developer console of the visible tab while the animation or
// video is playing. Returns a 15-second snapshot; it does not change settings.
// Browser privacy extensions and background throttling can affect the result.
(async () => {
  const duration = 15000;
  const video = document.querySelector('video');
  const startVideo = video?.getVideoPlaybackQuality?.();
  const startTime = video?.currentTime;
  const times = [];
  const longTasks = [];
  let observer;
  try {
    observer = new PerformanceObserver(list => {
      for (const e of list.getEntries()) longTasks.push(e.duration);
    });
    observer.observe({entryTypes: ['longtask']});
  } catch (_) { observer = null; }
  const start = performance.now();
  let hiddenMs = 0;
  let last = start;
  let wasHidden = document.hidden;
  function visibility() {
    const now = performance.now();
    if (wasHidden) hiddenMs += now - last;
    last = now;
    wasHidden = document.hidden;
  }
  document.addEventListener('visibilitychange', visibility);
  await new Promise(resolve => {
    function frame(t) {
      times.push(t);
      if (performance.now() - start < duration) requestAnimationFrame(frame);
      else resolve();
    }
    requestAnimationFrame(frame);
    // A hidden tab may stop rAF entirely; never leave the probe hanging.
    setTimeout(resolve, duration + 1000);
  });
  visibility();
  document.removeEventListener('visibilitychange', visibility);
  if (observer) observer.disconnect();
  const elapsed = performance.now() - start;
  const gaps = times.slice(1).map((t, i) => t - times[i]);
  const sorted = [...gaps].sort((a, b) => a - b);
  const endVideo = video?.getVideoPlaybackQuality?.();
  const result = {
    elapsedMs: Math.round(elapsed), hiddenMs: Math.round(hiddenMs),
    animation: {frames: times.length, fps: +(times.length * 1000 / elapsed).toFixed(1),
      gapP95Ms: sorted.length ? +sorted[Math.floor((sorted.length - 1) * .95)].toFixed(1) : null,
      gapsOver50Ms: gaps.filter(x => x > 50).length},
    longTasks: observer ? {count: longTasks.length, totalMs: Math.round(longTasks.reduce((a, b) => a + b, 0)),
      maxMs: Math.round(Math.max(0, ...longTasks))} : null,
    video: video ? {paused: video.paused, width: video.videoWidth, height: video.videoHeight,
      secondsAdvanced: +(video.currentTime - startTime).toFixed(1),
      totalFrames: startVideo && endVideo ? endVideo.totalVideoFrames - startVideo.totalVideoFrames : null,
      droppedFrames: startVideo && endVideo ? endVideo.droppedVideoFrames - startVideo.droppedVideoFrames : null} : null,
    note: 'Frame timing and dropped-frame counters do not identify the active GPU or hardware decoder.'
  };
  console.log('Navi44 frame probe:', JSON.stringify(result, null, 2));
  return result;
})()
