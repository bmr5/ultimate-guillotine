/**
 * The tune is data, and these are the tests that keep the data honest: a part that is a step
 * short would drift against the others on every loop, and a typo in the notation would throw
 * on the first tap rather than in CI.
 *
 * @vitest-environment node
 */
import { describe, expect, it } from "vitest";

import {
  arpeggioVoice,
  bassVoice,
  drumTrack,
  indexByStep,
  midiToFrequency,
  noteToMidi,
  parseVoice,
  pulseWave,
  SCORE,
  STEPS_PER_BAR,
  stepSeconds,
  type Part,
  type Score,
} from "./score";

describe("noteToMidi", () => {
  it("reads scientific pitch names, sharps and flats", () => {
    expect(noteToMidi("A4")).toBe(69);
    expect(noteToMidi("C4")).toBe(60);
    expect(noteToMidi("G#5")).toBe(80);
    expect(noteToMidi("Bb3")).toBe(58);
    expect(noteToMidi("E2")).toBe(40);
  });

  it("rejects anything that is not a pitch, naming it", () => {
    expect(() => noteToMidi("H4")).toThrow('"H4"');
    expect(() => noteToMidi("A")).toThrow('"A"');
  });
});

describe("midiToFrequency", () => {
  it("tunes A4 to 440 and halves per octave down", () => {
    expect(midiToFrequency(69)).toBe(440);
    expect(midiToFrequency(57)).toBe(220);
    expect(midiToFrequency(60)).toBeCloseTo(261.63, 2);
  });
});

describe("parseVoice", () => {
  it("places each note at the step where the ones before it end", () => {
    expect(parseVoice("E5:3 E5:1 A5:2")).toEqual({
      events: [
        { midi: 76, startStep: 0, steps: 3 },
        { midi: 76, startStep: 3, steps: 1 },
        { midi: 81, startStep: 4, steps: 2 },
      ],
      steps: 6,
    });
  });

  it("advances past a rest without a note, and ignores bar lines", () => {
    expect(parseVoice("E5:2 | -:2 A5:1 |")).toEqual({
      events: [
        { midi: 76, startStep: 0, steps: 2 },
        { midi: 81, startStep: 4, steps: 1 },
      ],
      steps: 5,
    });
  });

  it("reads a bare note as one step", () => {
    expect(parseVoice("E5").steps).toBe(1);
  });

  it("rejects a malformed token, naming it", () => {
    expect(() => parseVoice("E5:3 E5:x")).toThrow('"E5:x"');
    expect(() => parseVoice("E5:0")).toThrow('"E5:0"');
  });
});

describe("pulseWave", () => {
  it("carries no DC term and nothing on the sine side", () => {
    const { real, imag } = pulseWave(0.25, 8);
    expect(real).toHaveLength(9);
    expect(real[0]).toBe(0);
    expect(Array.from(imag)).toEqual(new Array(9).fill(0));
  });

  it("at half duty is a square wave: odd harmonics only, falling as 1/n", () => {
    const { real } = pulseWave(0.5, 8);
    expect(real[1]).toBeCloseTo(2 / Math.PI, 6);
    expect(real[2]).toBeCloseTo(0, 6);
    expect(Math.abs(real[3])).toBeCloseTo(2 / (3 * Math.PI), 6);
    expect(real[4]).toBeCloseTo(0, 6);
  });

  it("at quarter duty drops every fourth harmonic and keeps the rest", () => {
    const { real } = pulseWave(0.25, 8);
    expect(real[2]).not.toBeCloseTo(0, 6);
    expect(real[4]).toBeCloseTo(0, 6);
    expect(real[8]).toBeCloseTo(0, 6);
  });
});

describe("arpeggioVoice", () => {
  it("cycles each bar's chord tones in sixteenths", () => {
    const voice = arpeggioVoice(
      [{ tones: ["A4", "C5", "E5", "A5"], bass: "A2" }],
      16,
    );
    expect(voice.steps).toBe(16);
    expect(voice.events).toHaveLength(16);
    expect(voice.events.map((event) => event.midi)).toEqual([
      69, 72, 76, 81, 69, 72, 76, 81, 69, 72, 76, 81, 69, 72, 76, 81,
    ]);
    expect(voice.events.map((event) => event.startStep)).toEqual(
      Array.from({ length: 16 }, (_, index) => index),
    );
    expect(voice.events.every((event) => event.steps === 1)).toBe(true);
  });
});

describe("bassVoice", () => {
  it("bounces between the root and its octave in eighths", () => {
    const voice = bassVoice([{ tones: ["A4"], bass: "A2" }], 16);
    expect(voice.steps).toBe(16);
    expect(voice.events.map((event) => event.midi)).toEqual([
      45, 57, 45, 57, 45, 57, 45, 57,
    ]);
    expect(voice.events.map((event) => event.startStep)).toEqual([
      0, 2, 4, 6, 8, 10, 12, 14,
    ]);
    expect(voice.events.every((event) => event.steps === 2)).toBe(true);
  });

  it("walks up through the given notes at the end of a bar that has them", () => {
    const voice = bassVoice(
      [{ tones: ["E4"], bass: "E2", walkUp: ["F2", "G#2"] }],
      16,
    );
    expect(voice.events.map((event) => event.midi)).toEqual([
      40, 52, 40, 52, 40, 52, 41, 44,
    ]);
    expect(voice.steps).toBe(16);
  });
});

describe("drumTrack", () => {
  it("repeats the pattern every bar and adds the fills to the bars that have them", () => {
    const hits = drumTrack({
      bars: 2,
      stepsPerBar: 16,
      pattern: { kick: [0, 8], snare: [4], hat: [0, 2] },
      fills: { 1: { snare: [14, 15] } },
    });
    const steps = (kind: string) =>
      hits.filter((hit) => hit.kind === kind).map((hit) => hit.step);
    expect(steps("kick")).toEqual([0, 8, 16, 24]);
    expect(steps("snare")).toEqual([4, 20, 30, 31]);
    expect(steps("hat")).toEqual([0, 2, 16, 18]);
  });
});

describe("indexByStep", () => {
  it("groups the notes and drums that start on each step", () => {
    const lead: Omit<Part, "events"> = {
      name: "lead",
      timbre: { kind: "pulse", duty: 0.25 },
      gain: 1,
      gap: 0,
      steps: 4,
    };
    const score: Score = {
      bpm: 120,
      stepsPerBeat: 4,
      totalSteps: 4,
      parts: [
        {
          ...lead,
          events: [
            { midi: 60, startStep: 0, steps: 2 },
            { midi: 62, startStep: 2, steps: 2 },
          ],
        },
        {
          ...lead,
          name: "bass",
          events: [{ midi: 48, startStep: 0, steps: 4 }],
        },
      ],
      drums: [
        { kind: "kick", step: 0 },
        { kind: "hat", step: 2 },
      ],
    };
    const index = indexByStep(score);
    expect(index.get(0)).toEqual({
      notes: [
        { part: score.parts[0], event: { midi: 60, startStep: 0, steps: 2 } },
        { part: score.parts[1], event: { midi: 48, startStep: 0, steps: 4 } },
      ],
      drums: ["kick"],
    });
    expect(index.get(2)).toEqual({
      notes: [
        { part: score.parts[0], event: { midi: 62, startStep: 2, steps: 2 } },
      ],
      drums: ["hat"],
    });
    expect(index.has(1)).toBe(false);
  });
});

describe("SCORE", () => {
  it("is a whole number of bars, sixteen steps each", () => {
    expect(STEPS_PER_BAR).toBe(16);
    expect(SCORE.totalSteps).toBeGreaterThan(0);
    expect(SCORE.totalSteps % STEPS_PER_BAR).toBe(0);
  });

  it("has every part spanning the whole loop, so nothing drifts", () => {
    expect(SCORE.parts.map((part) => part.name)).toEqual([
      "lead",
      "arp",
      "bass",
    ]);
    for (const part of SCORE.parts) {
      const last = part.events[part.events.length - 1];
      expect(last.startStep + last.steps).toBeLessThanOrEqual(SCORE.totalSteps);
      expect(part.steps).toBe(SCORE.totalSteps);
    }
  });

  it("keeps every note inside a playable range", () => {
    for (const part of SCORE.parts) {
      for (const event of part.events) {
        expect(event.midi).toBeGreaterThanOrEqual(noteToMidi("C2"));
        expect(event.midi).toBeLessThanOrEqual(noteToMidi("C7"));
        expect(event.steps).toBeGreaterThan(0);
      }
    }
  });

  it("keeps every drum hit inside the loop", () => {
    expect(SCORE.drums.length).toBeGreaterThan(0);
    for (const hit of SCORE.drums) {
      expect(Number.isInteger(hit.step)).toBe(true);
      expect(hit.step).toBeGreaterThanOrEqual(0);
      expect(hit.step).toBeLessThan(SCORE.totalSteps);
    }
  });

  it("closes every four-bar phrase with a snare fill", () => {
    const snares = new Set(
      SCORE.drums.filter((hit) => hit.kind === "snare").map((hit) => hit.step),
    );
    for (let bar = 4; bar <= SCORE.totalSteps / STEPS_PER_BAR; bar += 4) {
      expect(snares.has(bar * STEPS_PER_BAR - 1)).toBe(true);
    }
  });

  it("runs at a tempo where a step is a tenth of a second", () => {
    expect(stepSeconds(SCORE)).toBeCloseTo(0.1, 10);
  });
});
