export class Agent {
  constructor(ctx, env) {
    this.ctx   = ctx || { waitUntil: () => {} };
    this.env   = env || {};
    this.state = {};
  }
  setState(s) { this.state = s; }
  async onStart() {}
  async scheduleEvery() {}
}
