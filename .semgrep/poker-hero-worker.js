export function unsafeWorkerHandler(source) {
  // ruleid: poker-hero-worker-no-dynamic-code-execution
  return eval(source);
}

export function unsafeWorkerFactory(source) {
  // ruleid: poker-hero-worker-no-dynamic-code-execution
  return new Function(source);
}

export function safeWorkerHandler(source) {
  // ok: poker-hero-worker-no-dynamic-code-execution
  return JSON.parse(source);
}
