import {projectBeforePersistence, type ProjectionContext} from "../security/redaction.js";
import type {AuthenticatedLoopback} from "../security/loopback.js";
import type {Spool} from "../spool.js";

/** Synthetic inputs already carry validated sequence/content hashes; never relabel them. */
export class OfflineSession {
  private queue: Promise<void> = Promise.resolve();
  private stopped = false;
  constructor(private readonly spool: Spool, private readonly client: AuthenticatedLoopback,
    private readonly context: ProjectionContext) {}
  append(input: unknown): Promise<void> {
    const result = this.queue.then(async () => {
      if (this.stopped) throw new Error("E_OFFLINE_STOPPED");
      try {
        await this.spool.append(await projectBeforePersistence(input, this.context));
        await this.client.flushPending();
      } catch (error) {this.stopped = true; throw error;}
    });
    this.queue = result.catch(() => undefined);
    return result;
  }
  async close(): Promise<void> {this.stopped = true; await this.queue; await this.client.close();}
}
