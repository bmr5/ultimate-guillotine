import {
  indexByStep,
  midiToFrequency,
  pulseWave,
  SCORE,
  stepSeconds,
  type DrumKind,
  type NoteEvent,
  type Part,
  type Score,
} from "./score";

/**
 * Plays the score through the Web Audio API: a pulse-wave lead and arpeggio, a triangle bass
 * and a noise kit, the way an NES did it, scheduled a fraction of a second ahead of the audio
 * clock so the tune never depends on the main thread being on time.
 *
 * The engine knows nothing about the page's preference for music; `useMusic` does. What it
 * does know is the browser's autoplay rule: a context started outside a user gesture stays
 * suspended, so `play` is safe to call from every gesture until one of them takes, and it keeps
 * no state that a blocked resume would leave wrong. And it knows the tab can be hidden — it
 * suspends itself then, because a page a member has switched away from should not go on
 * playing, and because a background tab's timers are throttled past what the lookahead covers.
 */
export interface MusicEngine {
  /** Start the tune, or pick it up again after a pause. Call it from a user gesture. */
  play(): void;
  /** Fade the tune out and, once it is silent, suspend the context. */
  pause(): void;
  /** Close the context and stop listening to the page. */
  dispose(): void;
}

export interface MusicEngineOptions {
  score?: Score;
  /** How a context is made; the tests hand in a fake. */
  createContext?: () => AudioContext;
}

/**
 * The whole tune's level. Two pulse waves and a triangle sum to well over full scale, and this
 * is background music on a page a member reads for a while, so it sits low.
 */
export const MASTER_GAIN = 0.14;

/** The tune's first entrance is a slow rise; a mute or an unmute is a quick one. */
export const FIRST_FADE_IN_SECONDS = 0.8;
export const FADE_SECONDS = 0.25;

/**
 * How far ahead of the audio clock notes are scheduled, and how often the scheduler runs. The
 * lookahead has to outlast the longest gap between two runs — a busy main thread can hold a
 * fifty-millisecond timer for a hundred or more — or the tune stutters.
 */
export const LOOKAHEAD_SECONDS = 0.2;
export const TICK_MS = 50;

/** A breath between the gesture and the first note, so the first note is never late. */
export const START_DELAY_SECONDS = 0.05;

/** A note's shape: a fast attack, a short fall to the sustain, and a fast release at the end. */
const ATTACK_SECONDS = 0.004;
const DECAY_SECONDS = 0.12;
const SUSTAIN = 0.8;
const RELEASE_SECONDS = 0.008;

const DRUM_GAIN = 0.6;
/** The kick is a triangle that falls from a low note to a thud. */
const KICK_START_HZ = 160;
const KICK_END_HZ = 45;
const KICK_SECONDS = 0.12;
const SNARE = {
  type: "bandpass",
  frequency: 1800,
  seconds: 0.1,
  level: 0.8,
} as const;
const HAT = {
  type: "highpass",
  frequency: 7000,
  seconds: 0.03,
  level: 0.3,
} as const;
/** One second of white noise, played from a different point for every hit. */
const NOISE_SECONDS = 1;
/** Exponential ramps cannot reach zero; this is as good as silent. */
const SILENT = 0.001;

interface PartNodes {
  gain: GainNode;
  /** The pulse wave's table, or null for a part that uses a built-in waveform. */
  wave: PeriodicWave | null;
}

/** Everything built once per context. */
interface Graph {
  master: GainNode;
  drums: GainNode;
  parts: Map<Part, PartNodes>;
  noise: AudioBuffer;
}

function ignore() {}

export function createMusicEngine({
  score = SCORE,
  createContext = () => new AudioContext(),
}: MusicEngineOptions = {}): MusicEngine {
  const index = indexByStep(score);
  const secondsPerStep = stepSeconds(score);

  let context: AudioContext | null = null;
  let graph: Graph | null = null;
  /** True once creating a context has thrown: an old browser, and the tune stays a no-op. */
  let unavailable = false;
  /** Whether the music should be playing — set by play and pause, not by the tab's visibility. */
  let wanted = false;
  let disposed = false;
  let ticker: number | null = null;
  let suspendTimer: number | null = null;
  /** When step zero played, on the context's clock; every step's time is measured from it. */
  let startTime = 0;
  let nextStep = 0;

  function build(): Graph {
    const ctx = createContext();
    const master = ctx.createGain();
    master.gain.value = 0;
    master.connect(ctx.destination);

    const drums = ctx.createGain();
    drums.gain.value = DRUM_GAIN;
    drums.connect(master);

    const parts = new Map<Part, PartNodes>();
    for (const part of score.parts) {
      const gain = ctx.createGain();
      gain.gain.value = part.gain;
      gain.connect(master);
      let wave: PeriodicWave | null = null;
      if (part.timbre.kind === "pulse") {
        const { real, imag } = pulseWave(part.timbre.duty);
        wave = ctx.createPeriodicWave(real, imag);
      }
      parts.set(part, { gain, wave });
    }

    const noise = ctx.createBuffer(
      1,
      Math.round(ctx.sampleRate * NOISE_SECONDS),
      ctx.sampleRate,
    );
    const samples = noise.getChannelData(0);
    for (let i = 0; i < samples.length; i += 1) {
      samples[i] = Math.random() * 2 - 1;
    }

    context = ctx;
    return { master, drums, parts, noise };
  }

  function fade(param: AudioParam, target: number, seconds: number) {
    if (context === null) return;
    const now = context.currentTime;
    param.cancelScheduledValues(now);
    param.setValueAtTime(param.value, now);
    param.linearRampToValueAtTime(target, now + seconds);
  }

  function scheduleNote(
    ctx: AudioContext,
    nodes: Graph,
    part: Part,
    event: NoteEvent,
    time: number,
  ) {
    const partNodes = nodes.parts.get(part);
    if (partNodes === undefined) return;
    const end = Math.max(
      time + ATTACK_SECONDS + RELEASE_SECONDS,
      time + event.steps * secondsPerStep - part.gap,
    );
    const releaseStart = end - RELEASE_SECONDS;
    const decayEnd = Math.min(time + DECAY_SECONDS, releaseStart);

    const oscillator = ctx.createOscillator();
    if (partNodes.wave !== null) {
      oscillator.setPeriodicWave(partNodes.wave);
    } else {
      oscillator.type = "triangle";
    }
    oscillator.frequency.value = midiToFrequency(event.midi);

    const envelope = ctx.createGain();
    envelope.gain.setValueAtTime(0, time);
    envelope.gain.linearRampToValueAtTime(1, time + ATTACK_SECONDS);
    envelope.gain.linearRampToValueAtTime(SUSTAIN, decayEnd);
    if (releaseStart > decayEnd) {
      envelope.gain.setValueAtTime(SUSTAIN, releaseStart);
    }
    envelope.gain.linearRampToValueAtTime(0, end);

    oscillator.connect(envelope);
    envelope.connect(partNodes.gain);
    oscillator.start(time);
    oscillator.stop(end);
  }

  function scheduleNoise(
    ctx: AudioContext,
    nodes: Graph,
    time: number,
    { type, frequency, seconds, level }: typeof SNARE | typeof HAT,
  ) {
    const source = ctx.createBufferSource();
    source.buffer = nodes.noise;
    const filter = ctx.createBiquadFilter();
    filter.type = type;
    filter.frequency.value = frequency;
    const envelope = ctx.createGain();
    envelope.gain.setValueAtTime(level, time);
    envelope.gain.exponentialRampToValueAtTime(SILENT, time + seconds);
    source.connect(filter);
    filter.connect(envelope);
    envelope.connect(nodes.drums);
    source.start(time, Math.random() * (NOISE_SECONDS - seconds));
    source.stop(time + seconds);
  }

  function scheduleDrum(
    ctx: AudioContext,
    nodes: Graph,
    kind: DrumKind,
    time: number,
  ) {
    switch (kind) {
      case "kick": {
        const oscillator = ctx.createOscillator();
        oscillator.type = "triangle";
        oscillator.frequency.setValueAtTime(KICK_START_HZ, time);
        oscillator.frequency.exponentialRampToValueAtTime(
          KICK_END_HZ,
          time + KICK_SECONDS * 0.75,
        );
        const envelope = ctx.createGain();
        envelope.gain.setValueAtTime(1, time);
        envelope.gain.exponentialRampToValueAtTime(SILENT, time + KICK_SECONDS);
        oscillator.connect(envelope);
        envelope.connect(nodes.drums);
        oscillator.start(time);
        oscillator.stop(time + KICK_SECONDS);
        return;
      }
      case "snare":
        scheduleNoise(ctx, nodes, time, SNARE);
        return;
      case "hat":
        scheduleNoise(ctx, nodes, time, HAT);
        return;
    }
  }

  /**
   * The scheduler: everything that starts before the lookahead horizon is handed to the audio
   * thread now, and the step clock advances. A suspended context's clock stands still, so a
   * tick while the tab is hidden or the browser is still waiting for a gesture schedules nothing
   * new; when the clock moves again the tune carries on from where it stopped.
   */
  function tick() {
    if (context === null || graph === null) return;
    const horizon = context.currentTime + LOOKAHEAD_SECONDS;
    for (
      let time = startTime + nextStep * secondsPerStep;
      time < horizon;
      nextStep += 1, time = startTime + nextStep * secondsPerStep
    ) {
      const events = index.get(nextStep % score.totalSteps);
      if (events === undefined) continue;
      for (const { part, event } of events.notes) {
        scheduleNote(context, graph, part, event, time);
      }
      for (const kind of events.drums) {
        scheduleDrum(context, graph, kind, time);
      }
    }
  }

  function startTicking() {
    if (ticker !== null) return;
    tick();
    ticker = window.setInterval(tick, TICK_MS);
  }

  function stopTicking() {
    if (ticker === null) return;
    window.clearInterval(ticker);
    ticker = null;
  }

  function cancelSuspend() {
    if (suspendTimer === null) return;
    window.clearTimeout(suspendTimer);
    suspendTimer = null;
  }

  function resume() {
    if (context !== null && context.state !== "running") {
      context.resume().catch(ignore);
    }
  }

  /**
   * Idempotent on purpose: while the music is wanted, every gesture on the page calls this,
   * and only the first one that the browser honours has anything to do. A call that finds the
   * tune already wanted and the context running is a no-op; one that finds the context still
   * suspended asks it to resume again, which is the retry the autoplay rule needs.
   */
  function play() {
    if (disposed || unavailable) return;
    cancelSuspend();
    const first = graph === null;
    if (first) {
      try {
        graph = build();
      } catch {
        unavailable = true;
        return;
      }
    }
    if (context === null || graph === null) return;
    if (first) {
      startTime = context.currentTime + START_DELAY_SECONDS;
      nextStep = 0;
    }
    if (!wanted) {
      wanted = true;
      fade(
        graph.master.gain,
        MASTER_GAIN,
        first ? FIRST_FADE_IN_SECONDS : FADE_SECONDS,
      );
    }
    resume();
    startTicking();
  }

  function pause() {
    if (disposed || !wanted) return;
    wanted = false;
    stopTicking();
    if (context === null || graph === null) return;
    const ctx = context;
    fade(graph.master.gain, 0, FADE_SECONDS);
    suspendTimer = window.setTimeout(() => {
      suspendTimer = null;
      if (!wanted) ctx.suspend().catch(ignore);
    }, FADE_SECONDS * 1000);
  }

  function onVisibilityChange() {
    if (context === null || !wanted) return;
    if (document.visibilityState === "hidden") {
      stopTicking();
      context.suspend().catch(ignore);
    } else {
      resume();
      startTicking();
    }
  }

  function dispose() {
    if (disposed) return;
    disposed = true;
    wanted = false;
    stopTicking();
    cancelSuspend();
    document.removeEventListener("visibilitychange", onVisibilityChange);
    context?.close().catch(ignore);
    context = null;
    graph = null;
  }

  document.addEventListener("visibilitychange", onVisibilityChange);

  return { play, pause, dispose };
}
