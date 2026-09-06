import test from "node:test";
import { ClosedCdpBroker } from "../../src/security/cdp-broker.js";

void test("SEC0-T02 is intentionally unimplemented", () => {
  new ClosedCdpBroker();
});

