import {readFileSync} from 'node:fs';
import {describe, expect, it} from 'vitest';

const html = readFileSync('public/production.html', 'utf8');
const runtime = readFileSync('public/live-runtime.js', 'utf8');

describe('Tugas Tim Kerjakan + workflow focus', () => {
  it('uses official verb instead of Panel V3 when official tasks live', () => {
    expect(html).toContain('function taskActionLabel');
    expect(html).toContain('isOfficialTasksLive()&&x&&x.t&&x.t.verb');
    expect(html).toContain('data-task-action="kerjakan"');
    expect(html).toMatch(/taskKind:type/);
  });

  it('opens workflow with taskKind focus map for sample/loading/driver', () => {
    expect(runtime).toContain('window.__v3TaskFocus');
    expect(runtime).toContain('sample_approve: "v3-sample-file"');
    expect(runtime).toContain('loading: "v3-sj-id"');
    expect(runtime).toContain('delivery: "v3-pod-qty"');
    expect(runtime).toContain('inFlight.has(lockKey)');
  });
});
