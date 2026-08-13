'use client';

import { useRouter } from 'next/navigation';
import { useEffect, useRef } from 'react';

/**
 * Keeps a server-rendered screen current without the person doing anything.
 *
 * These pages are server components: they fetch once, render, and then sit
 * still. That was fine while every message in Sangam was typed by the person
 * looking at the screen. With a real WhatsApp provider connected it stopped
 * being fine - a customer's message would arrive, be verified, be stored, and
 * the open conversation would keep showing the state it had on load. It only
 * appeared after something else forced a re-render, which is why it looked
 * intermittent rather than broken.
 *
 * `router.refresh()` re-runs the server component and reconciles the result into
 * the existing tree, so the scroll position and anything half-typed survive. It
 * is the smallest fix that matches how these pages already work: no socket, no
 * client-side store, no second copy of the data.
 *
 * Polling, not push. A websocket tier would be the right answer for a busy
 * shared inbox and the wrong answer for a pilot with one number and a handful of
 * threads - it would need its own auth, its own fan-out and its own failure
 * modes, all to save a request every few seconds.
 *
 * Two courtesies that stop this being a nuisance:
 *   - it pauses while the tab is hidden, so a laptop left open overnight is not
 *     quietly polling until morning;
 *   - it refreshes immediately when the tab is focused again, so coming back to
 *     the window shows the truth at once rather than after the next tick.
 */
export function AutoRefresh({
  intervalMs = 8000,
  enabled = true,
}: {
  intervalMs?: number;
  enabled?: boolean;
}): null {
  const router = useRouter();
  // Held in a ref so changing the interval cannot leak a timer, and so the
  // effect does not re-subscribe on every render.
  const timer = useRef<ReturnType<typeof setInterval> | null>(null);

  useEffect(() => {
    if (!enabled) return;

    function stop(): void {
      if (timer.current) {
        clearInterval(timer.current);
        timer.current = null;
      }
    }

    function start(): void {
      stop();
      timer.current = setInterval(() => {
        if (document.visibilityState === 'visible') router.refresh();
      }, intervalMs);
    }

    function onVisibility(): void {
      if (document.visibilityState === 'visible') {
        router.refresh();
        start();
      } else {
        stop();
      }
    }

    start();
    document.addEventListener('visibilitychange', onVisibility);
    return () => {
      stop();
      document.removeEventListener('visibilitychange', onVisibility);
    };
  }, [router, intervalMs, enabled]);

  return null;
}
