/** Offline-only closed frames. Imported solely by the offline module graph. */
import type { AnySchemaObject } from "ajv/dist/2020.js";
import { validateArtifact } from "../schema-registry.js";

export const validateOfflineFrame = (value: unknown, schemas: readonly AnySchemaObject[]): void => {
  try {
    validateArtifact(value, "urn:betting-helper:offline-slice:frame:v1", schemas);
    const frame = value as { counter: string; message_type: string; body: {
      run_id: string; browser_run_id: string; stream_id: string; generation: string;
      first_sequence: string; last_sequence: string; observations: {
        discovery_run_id: string; context: { browser_run_id: string }; stream_id: string;
        generation: string; sequence: string;
      }[];
    } };
    const maximum = 9223372036854775807n;
    if (BigInt(frame.counter) > maximum) throw new Error();
    if (frame.message_type === "BATCH") {
      const body = frame.body;
      const first = BigInt(body.first_sequence), last = BigInt(body.last_sequence);
      if (first < 1n || last < first || last > maximum || BigInt(body.generation) > maximum ||
          last - first + 1n !== BigInt(body.observations.length)) throw new Error();
      for (const [index, raw] of body.observations.entries()) {
        if (raw.discovery_run_id !== body.run_id || raw.context.browser_run_id !== body.browser_run_id ||
            raw.stream_id !== body.stream_id || raw.generation !== body.generation ||
            raw.sequence !== String(first + BigInt(index)) ||
            new TextEncoder().encode(JSON.stringify(raw)).byteLength > 65536) throw new Error();
      }
    }
    if (new TextEncoder().encode(JSON.stringify(value)).byteLength > 262144) throw new Error();
  } catch { throw new Error("E_OFFLINE_SCHEMA"); }
};
