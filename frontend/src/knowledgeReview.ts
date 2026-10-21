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
  const response = await fetch(`/api/knowledge-review${path}`, { cache: 'no-store', ...init });
  if (!response.ok) {
    const body = await response.json().catch(() => null);
    throw new Error(typeof body?.detail === 'string' ? body.detail : `Review request failed (${response.status}). Try refreshing the workspace.`);
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
