export type DocumentRecord = Record<string, unknown>;

export interface KnowledgeRule extends DocumentRecord {
  rule_id: string;
  guideline?: string;
  section?: string;
  url?: string;
  verbatim_quote?: string;
  notes?: string;
  priority?: number;
  conditions?: DocumentRecord[];
  actions?: DocumentRecord[];
}

export interface ReviewDraft {
  draft_id: string;
  revision: number;
  author: string;
  rules_hash: string;
  dishes_hash: string;
  validation: DocumentRecord;
  provenance: DocumentRecord;
  release_id: string | null;
  review: { actor: string; decision: string; note: string; created_at: string } | null;
}

export interface ReviewStatus {
  deployment_mode: 'review';
  clinical_workflows_enabled: false;
  draft: ReviewDraft;
  current_draft: ReviewDraft;
  technical_review: DocumentRecord | null;
  review_enabled: boolean;
  csrf_token: string;
}

export interface KnowledgeWorkspace {
  deployment_mode: 'review';
  clinical_workflows_enabled: false;
  csrf_token: string;
  drafts: ReviewDraft[];
  discovery_available: boolean;
  instructions: string;
}

export interface DraftSnapshot {
  draft: ReviewDraft;
  revision: number;
  documents: ReviewDocuments;
  events: ReviewEvent[];
}

export interface ReviewDocuments {
  rules: DocumentRecord & { rules: KnowledgeRule[] };
  dishes: (DocumentRecord & { dish_id: string; name: string })[];
}

export interface ReviewEvent {
  event_id: number;
  revision: number;
  actor: string;
  action: string;
  created_at: string;
  detail_json: string;
}

export async function reviewRequest<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(`/api/knowledge${path}`, { cache: 'no-store', ...init });
  if (!response.ok) {
    const body = await response.json().catch(() => null);
    const detail = typeof body?.detail === 'string' ? body.detail
      : Array.isArray(body?.detail) ? body.detail.map((item: { msg?: string }) => item.msg || 'Invalid field').join('; ')
      : `Knowledge request failed (${response.status}). Try refreshing the workspace.`;
    throw new Error(detail);
  }
  return response.json();
}

export function safeSourceUrl(value: unknown): string | undefined {
  if (typeof value !== 'string') return undefined;
  try {
    const url = new URL(value);
    return ['http:', 'https:'].includes(url.protocol) ? url.href : undefined;
  } catch {
    return undefined;
  }
}
