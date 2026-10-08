import type { ExamConfig, ExamPlan } from './types';
function stable(value: unknown): string {
  return JSON.stringify(value, (_key, item) =>
    item && typeof item === 'object' && !Array.isArray(item)
      ? Object.fromEntries(Object.entries(item).sort(([a], [b]) => a.localeCompare(b)))
      : item,
  );
}
export function planSettings(config: ExamConfig) {
  return stable([
    config.course_id,
    config.ranges.map((r) => ({ ...r, role: r.role || 'auto' })),
    config.rules
      .filter((r) => r.count > 0)
      .slice()
      .sort((a, b) => a.type.localeCompare(b.type)),
    config.mode,
    config.reading_mode || 'study',
    config.review_mode || 'full',
    config.random_count,
    config.difficulty,
    config.focus,
    config.style || '适度变式',
    config.instructions || '',
    config.answer_detail || 'concise',
  ]);
}
export function needsPlanning(plan: ExamPlan | null, config: ExamConfig) {
  return (
    !plan ||
    plan.status !== 'ready' ||
    plan.source_changes.length > 0 ||
    planSettings(plan.basis_config) !== planSettings(config)
  );
}
export const localDraftKey = (id: string) => `zhixi-plan-draft:${id}`;
export function readLocalDraft(id: string): {
  config: ExamConfig;
  blueprint: ExamPlan['blueprint'];
  revision: number;
  status?: ExamPlan['status'];
} | null {
  try {
    return JSON.parse(localStorage.getItem(localDraftKey(id)) || 'null');
  } catch {
    return null;
  }
}
export function draftSnapshot(config: ExamConfig, blueprint: ExamPlan['blueprint']) {
  return stable([
    config.title,
    config.duration,
    planSettings(config),
    config.token_budget ?? 0,
    config.max_attempts ?? 2,
    config.batch_generation ?? false,
    blueprint,
  ]);
}

// getRandomValues also works on the HTTP LAN address used by phones.
export function newSubmissionId() {
  return Array.from(crypto.getRandomValues(new Uint8Array(16)), (n) =>
    n.toString(16).padStart(2, '0'),
  ).join('');
}
