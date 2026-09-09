/* Concrete isolated Chrome pipe owner. No oracle and no graceful crash substitute. */
const fs = require("node:fs");
const path = require("node:path");
const { spawn } = require("node:child_process");
const config = JSON.parse(fs.readFileSync(process.argv[2], "utf8"));
const directory = config.workspace;
const save = (name, value) => {
  const target = path.join(directory, name);
  fs.writeFileSync(target + ".tmp", JSON.stringify(value));
  fs.renameSync(target + ".tmp", target);
};
const child = spawn(config.command[0], config.command.slice(1), {
  stdio: ["ignore", "pipe", "pipe", "pipe", "pipe"], windowsHide: true,
});
child.stdout.pipe(fs.createWriteStream(path.join(directory, "chrome.stdout")));
child.stderr.pipe(fs.createWriteStream(path.join(directory, "chrome.stderr")));
const transcript = path.join(directory, "pipe.ndjson");
const record = value => fs.appendFileSync(transcript, JSON.stringify(value) + "\n");
let sequence = 0, buffer = "";
const pending = new Map();
child.stdio[4].on("data", chunk => {
  buffer += chunk.toString();
  let end;
  while ((end = buffer.indexOf("\0")) >= 0) {
    const raw = buffer.slice(0, end); buffer = buffer.slice(end + 1);
    try {
      const value = JSON.parse(raw), waiter = pending.get(value.id);
      record(waiter?.private ? {direction: "receive", id: value.id, private: true} : { direction: "receive", raw });
      if (waiter) {
        clearTimeout(waiter.timer); pending.delete(value.id);
        if (value.error) waiter.reject(new Error(waiter.private ? "E_PIPE_PRIVATE_API" : "E_PIPE_API:" + raw));
        else waiter.resolve(value.result);
      }
    } catch (error) { fail(error); }
  }
});
const call = (method, params = {}, sessionId, privateCall = false) => new Promise((resolve, reject) => {
  const id = ++sequence;
  const request = { id, method, params, ...(sessionId ? { sessionId } : {}) };
  const timer = setTimeout(() => {
    pending.delete(id); reject(new Error("E_PIPE_TIMEOUT:" + method));
  }, privateCall ? 125000 : 15000);
  pending.set(id, { resolve, reject, timer, private: privateCall });
  record(privateCall ? {direction: "send", id, method, private: true} : { direction: "send", request });
  child.stdio[3].write(JSON.stringify(request) + "\0");
});
const evaluate = async (sessionId, expression, privateCall = false) => {
  const response = await call("Runtime.evaluate", {
    expression, awaitPromise: true, returnByValue: true,
  }, sessionId, privateCall);
  if (response.exceptionDetails || !response.result || !("value" in response.result)) {
    throw new Error(privateCall ? "E_PIPE_PRIVATE_EVALUATE" : "E_PIPE_EVALUATE:" + JSON.stringify(response));
  }
  return response.result.value;
};
let failed = false;
function fail(error) {
  if (failed) return;
  failed = true;
  save("pipe-error.json", { error: String(error), pid: child.pid, node_pid: process.pid });
  process.stderr.write(String(error));
  if (config.offline) setInterval(() => {}, 1000); // Keep ownership alive for verified group cleanup.
  else process.exit(1);
}
child.on("error", fail);
child.on("exit", code => fail(new Error("E_PIPE_BROWSER_EXIT:" + code)));
(async () => {
  save("pipe-ready.json", { pid: child.pid, node_pid: process.pid });
  const start = path.join(directory, "start.json");
  const deadline = Date.now() + 20000;
  while (!fs.existsSync(start)) {
    if (Date.now() > deadline) throw new Error("E_PIPE_CONTROLLER_MISSING");
    await new Promise(resolve => setTimeout(resolve, 20));
  }
  const work = JSON.parse(fs.readFileSync(start, "utf8"));
  const version = await call("Browser.getVersion");
  const loaded = await call("Extensions.loadUnpacked", { path: config.extension });
  if (!loaded || config.origin !== "chrome-extension://" + loaded.id) {
    throw new Error("E_PIPE_EXTENSION_ID");
  }
  const target = await call("Target.createTarget", { url: config.origin + (config.offline ? "/src/offline/page.html" : "/repair-probe.html") });
  const attached = await call("Target.attachToTarget", { targetId: target.targetId, flatten: true });
  let document;
  const documentExpression = `({origin:location.origin,protocol:location.protocol,probe:Boolean(globalThis.${config.offline ? "offlineProbe" : "repairProbe"}),extensionId:globalThis.chrome?.runtime?.id??null})`;
  for (let attempt = 0; attempt < 100; attempt++) {
    document = await evaluate(attached.sessionId, documentExpression);
    if (document.origin === config.origin && document.extensionId === loaded.id && document.probe === true) break;
    await new Promise(resolve => setTimeout(resolve, 50));
  }
  if (document.origin !== config.origin || document.protocol !== "chrome-extension:" || document.probe !== true) {
    throw new Error("E_PIPE_EXTENSION_ORIGIN");
  }
  if (config.offline) {
    save("offline-ready.json", {pid: child.pid, node_pid: process.pid, version, loaded, document});
    const lines = require("node:readline").createInterface({input: process.stdin});
    let index = 0;
    const running = new Set();
    for await (const line of lines) {
      if (line.length > 4194304) throw new Error("E_OFFLINE_CONTROL_SIZE");
      const request = JSON.parse(line);
      if (request.operation === "FINISH") break;
      const expression = request.operation === "RESTART_WORKER"
        ? "globalThis.offlineProbe.restartWorker()"
        : request.operation === "READ_CHECKPOINTS" ? "({checkpoints:globalThis.offlineProbe.checkpoints})"
        : `globalThis.offlineProbe.command(${JSON.stringify(request)})`;
      if (running.size >= 2) throw new Error("E_OFFLINE_CONTROL_CAPACITY");
      const resultIndex = ++index;
      const task = evaluate(attached.sessionId, expression, true).then(result => {
        save(`offline-result-${resultIndex}.json`, {pid: child.pid, node_pid: process.pid, result});
      }).catch(() => {
        save(`offline-result-${resultIndex}.json`, {pid: child.pid, node_pid: process.pid,
          result: {status: "REJECTED", code: "E_OFFLINE_PRIVATE_COMMAND"}});
      }).finally(() => running.delete(task));
      running.add(task);
    }
    setInterval(() => {}, 1000);
    return;
  }
  const sentinel = await evaluate(attached.sessionId, work.sentinel_expression);
  const worker = work.worker_expression === null ? null : await evaluate(attached.sessionId, work.worker_expression);
  save("pipe-result.json", { pid: child.pid, node_pid: process.pid, version, loaded, document, sentinel, worker });
  setInterval(() => {}, 1000); // Deliberately alive at the real process/job crash boundary.
})().catch(fail);
