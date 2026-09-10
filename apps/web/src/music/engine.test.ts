import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import {
  createMusicEngine,
  FADE_SECONDS,
  FIRST_FADE_IN_SECONDS,
  LOOKAHEAD_SECONDS,
  MASTER_GAIN,
  START_DELAY_SECONDS,
  TICK_MS,
  type MusicEngine,
} from "./engine";
import { midiToFrequency, noteToMidi, SCORE, stepSeconds } from "./score";

/*
  jsdom has no Web Audio, so the engine is driven against a fake context that records what
  would have been scheduled: which oscillators at which frequency and time, what the master
  level was told to do, and when the context was resumed, suspended or closed. Nothing here
  makes a sound; what is under test is the clock, the lifecycle and the wiring.
*/

type ParamCall = [method: string, value: number, time: number];

class FakeParam {
  value = 0;
  calls: ParamCall[] = [];
  setValueAtTime(value: number, time: number) {
    this.calls.push(["set", value, time]);
  }
  linearRampToValueAtTime(value: number, time: number) {
    this.calls.push(["linear", value, time]);
  }
  exponentialRampToValueAtTime(value: number, time: number) {
    this.calls.push(["exponential", value, time]);
  }
  cancelScheduledValues(time: number) {
    this.calls.push(["cancel", 0, time]);
  }
}

class FakeNode {
  connections: FakeNode[] = [];
  connect(node: FakeNode) {
    this.connections.push(node);
    return node;
  }
  disconnect() {}
}

class FakeGain extends FakeNode {
  gain = new FakeParam();
}

class FakeOscillator extends FakeNode {
  type = "sine";
  frequency = new FakeParam();
  wave: unknown = null;
  started: number | null = null;
  stopped: number | null = null;
  setPeriodicWave(wave: unknown) {
    this.wave = wave;
  }
  start(time: number) {
    this.started = time;
  }
  stop(time: number) {
    this.stopped = time;
  }
}

class FakeBufferSource extends FakeNode {
  buffer: unknown = null;
  started: number | null = null;
  stopped: number | null = null;
  start(time: number) {
    this.started = time;
  }
  stop(time: number) {
    this.stopped = time;
  }
}

class FakeFilter extends FakeNode {
  type = "lowpass";
  frequency = new FakeParam();
  Q = new FakeParam();
}

class FakeContext {
  state: AudioContextState = "suspended";
  currentTime = 0;
  sampleRate = 44100;
  destination = new FakeNode();
  gains: FakeGain[] = [];
  oscillators: FakeOscillator[] = [];
  sources: FakeBufferSource[] = [];
  resumes = 0;
  suspends = 0;
  closed = false;
  /** Whether `resume` is allowed to work — false while the browser is still waiting for a tap. */
  allowed = true;

  resume() {
    this.resumes += 1;
    if (this.allowed) this.state = "running";
    return Promise.resolve();
  }
  suspend() {
    this.suspends += 1;
    this.state = "suspended";
    return Promise.resolve();
  }
  close() {
    this.closed = true;
    this.state = "closed";
    return Promise.resolve();
  }
  createGain() {
    const gain = new FakeGain();
    this.gains.push(gain);
    return gain;
  }
  createOscillator() {
    const oscillator = new FakeOscillator();
    this.oscillators.push(oscillator);
    return oscillator;
  }
  /** The pulse tables, in the order the engine built them: the score's pulse parts in order. */
  waves: { real: Float32Array; imag: Float32Array }[] = [];
  createPeriodicWave(real: Float32Array, imag: Float32Array) {
    const wave = { real, imag };
    this.waves.push(wave);
    return wave;
  }
  createBuffer(channels: number, length: number, sampleRate: number) {
    const data = new Float32Array(length);
    return {
      numberOfChannels: channels,
      length,
      sampleRate,
      duration: length / sampleRate,
      getChannelData: () => data,
    };
  }
  createBufferSource() {
    const source = new FakeBufferSource();
    this.sources.push(source);
    return source;
  }
  createBiquadFilter() {
    return new FakeFilter();
  }

  /** The gain the engine put in front of the speakers. */
  get master(): FakeGain {
    const master = this.gains.find((gain) =>
      gain.connections.includes(this.destination),
    );
    if (master === undefined) throw new Error("no master gain");
    return master;
  }

  /** Every note that was scheduled: its pitch and when it starts and stops. */
  get notes() {
    return this.oscillators
      .filter((oscillator) => oscillator.started !== null)
      .map((oscillator) => ({
        frequency: oscillator.frequency.value,
        type: oscillator.type,
        wave: oscillator.wave,
        start: oscillator.started as number,
        stop: oscillator.stopped as number,
      }));
  }

  /** Moves the clock on, letting the engine's ticker run as it would have. */
  advance(seconds: number) {
    const target = this.currentTime + seconds;
    while (this.currentTime < target - 1e-9) {
      this.currentTime = Math.min(target, this.currentTime + TICK_MS / 1000);
      vi.advanceTimersByTime(TICK_MS);
    }
  }
}

const STEP = stepSeconds(SCORE);
const E5 = midiToFrequency(noteToMidi("E5"));
const A4 = midiToFrequency(noteToMidi("A4"));
const A2 = midiToFrequency(noteToMidi("A2"));

function setVisibility(state: DocumentVisibilityState) {
  vi.spyOn(document, "visibilityState", "get").mockReturnValue(state);
  document.dispatchEvent(new Event("visibilitychange"));
}

describe("createMusicEngine", () => {
  let contexts: FakeContext[];
  let engine: MusicEngine;

  beforeEach(() => {
    vi.useFakeTimers();
    contexts = [];
    engine = createMusicEngine({
      createContext: () => {
        const context = new FakeContext();
        contexts.push(context);
        return context as unknown as AudioContext;
      },
    });
  });

  afterEach(() => {
    engine.dispose();
    vi.useRealTimers();
  });

  it("creates one context on the first play, resumes it, and fades in from silence", () => {
    engine.play();
    engine.play();
    expect(contexts).toHaveLength(1);
    const [context] = contexts;
    expect(context.resumes).toBe(1);
    expect(context.master.gain.calls).toEqual([
      ["cancel", 0, 0],
      ["set", 0, 0],
      ["linear", MASTER_GAIN, FIRST_FADE_IN_SECONDS],
    ]);
  });

  it("schedules the opening notes of every part on the step clock", () => {
    engine.play();
    const [context] = contexts;
    const start = START_DELAY_SECONDS;
    const lead = context.notes.find((note) => note.frequency === E5);
    expect(lead).toMatchObject({ start, wave: expect.anything() });
    expect(lead?.stop).toBeCloseTo(start + 3 * STEP - SCORE.parts[0].gap, 6);
    expect(context.notes).toContainEqual(
      expect.objectContaining({
        frequency: A4,
        start,
        wave: expect.anything(),
      }),
    );
    expect(context.notes).toContainEqual(
      expect.objectContaining({ frequency: A2, start, type: "triangle" }),
    );
  });

  it("only schedules as far ahead as the lookahead, then keeps up with the clock", () => {
    engine.play();
    const [context] = contexts;
    const secondLeadNote = START_DELAY_SECONDS + 3 * STEP;
    expect(secondLeadNote).toBeGreaterThan(LOOKAHEAD_SECONDS);
    // The arpeggio plays an E5 of its own two steps in, so the lead is told by its wave.
    const leadStarts = () =>
      context.notes
        .filter((note) => note.wave === context.waves[0])
        .map((note) => note.start);
    expect(leadStarts()).toEqual([START_DELAY_SECONDS]);

    context.advance(secondLeadNote);
    const starts = leadStarts();
    expect(starts.length).toBeGreaterThanOrEqual(2);
    expect(starts[1]).toBeCloseTo(secondLeadNote, 9);
    expect(Math.max(...starts)).toBeLessThan(
      context.currentTime + LOOKAHEAD_SECONDS,
    );
  });

  it("loops back to the top when the score runs out", () => {
    engine.play();
    const [context] = contexts;
    const loopSeconds = SCORE.totalSteps * STEP;
    context.advance(loopSeconds + START_DELAY_SECONDS);
    const restart = context.notes.find(
      (note) =>
        note.frequency === E5 &&
        Math.abs(note.start - (START_DELAY_SECONDS + loopSeconds)) < 1e-6,
    );
    expect(restart).toBeDefined();
  });

  it("plays the drums: the snare on the second beat is a burst of noise", () => {
    engine.play();
    const [context] = contexts;
    context.advance(0.4);
    const snare = START_DELAY_SECONDS + 4 * STEP;
    expect(
      context.sources.some(
        (source) => Math.abs((source.started ?? -1) - snare) < 1e-6,
      ),
    ).toBe(true);
  });

  it("fades out on pause, suspends once the fade is done, and resumes the same context on play", () => {
    engine.play();
    const [context] = contexts;
    context.advance(1);
    const countBefore = context.notes.length;

    engine.pause();
    const now = context.currentTime;
    expect(context.master.gain.calls.slice(-3)).toEqual([
      ["cancel", 0, now],
      ["set", context.master.gain.value, now],
      ["linear", 0, now + FADE_SECONDS],
    ]);
    expect(context.suspends).toBe(0);
    vi.advanceTimersByTime(FADE_SECONDS * 1000);
    expect(context.suspends).toBe(1);

    // The clock stops with the music: nothing more is scheduled while paused.
    context.advance(1);
    expect(context.notes.length).toBe(countBefore);

    engine.play();
    expect(contexts).toHaveLength(1);
    expect(context.resumes).toBe(2);
    expect(context.master.gain.calls.at(-1)).toEqual([
      "linear",
      MASTER_GAIN,
      context.currentTime + FADE_SECONDS,
    ]);
    context.advance(1);
    expect(context.notes.length).toBeGreaterThan(countBefore);
  });

  it("does not suspend if play comes back during the fade", () => {
    engine.play();
    const [context] = contexts;
    engine.pause();
    vi.advanceTimersByTime(FADE_SECONDS * 500);
    engine.play();
    vi.advanceTimersByTime(FADE_SECONDS * 1000);
    expect(context.suspends).toBe(0);
  });

  it("keeps trying to resume on each play until the browser lets audio run", () => {
    const [blocked] = [new FakeContext()];
    blocked.allowed = false;
    const guarded = createMusicEngine({
      createContext: () => blocked as unknown as AudioContext,
    });
    guarded.play();
    guarded.play();
    expect(blocked.resumes).toBe(2);
    blocked.allowed = true;
    guarded.play();
    expect(blocked.resumes).toBe(3);
    guarded.play();
    expect(blocked.resumes).toBe(3);
    guarded.dispose();
  });

  it("suspends while the page is hidden and picks up again when it is shown", () => {
    engine.play();
    const [context] = contexts;
    context.advance(0.5);
    const countBefore = context.notes.length;

    setVisibility("hidden");
    expect(context.suspends).toBe(1);
    context.advance(1);
    expect(context.notes.length).toBe(countBefore);

    setVisibility("visible");
    expect(context.resumes).toBe(2);
    context.advance(1);
    expect(context.notes.length).toBeGreaterThan(countBefore);
  });

  it("stays quiet on return if it was paused before the page was hidden", () => {
    engine.play();
    const [context] = contexts;
    engine.pause();
    vi.advanceTimersByTime(FADE_SECONDS * 1000);
    setVisibility("hidden");
    setVisibility("visible");
    expect(context.resumes).toBe(1);
  });

  it("dispose closes the context and stops listening to the page", () => {
    engine.play();
    const [context] = contexts;
    engine.dispose();
    expect(context.closed).toBe(true);
    const countAfter = context.notes.length;
    context.advance(1);
    expect(context.notes.length).toBe(countAfter);
    setVisibility("hidden");
    expect(context.suspends).toBe(0);
    engine.play();
    expect(contexts).toHaveLength(1);
  });

  it("stays silent, without throwing, where there is no audio to be had", () => {
    let attempts = 0;
    const silent = createMusicEngine({
      createContext: () => {
        attempts += 1;
        throw new Error("AudioContext is not defined");
      },
    });
    expect(() => silent.play()).not.toThrow();
    expect(() => silent.play()).not.toThrow();
    expect(attempts).toBe(1);
    expect(() => silent.pause()).not.toThrow();
    silent.dispose();
  });
});
