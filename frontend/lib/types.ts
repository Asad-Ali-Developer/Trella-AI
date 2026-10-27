export interface User {
  id: string;
  email: string;
  name: string;
  is_active: boolean;
  is_verified: boolean;
  created_at: string;
}

export interface AuthResponse {
  user: User;
}

export type MembershipRole = "owner" | "admin" | "member";

export interface Workspace {
  id: string;
  name: string;
  description: string | null;
  client_name: string | null;
  slug: string;
  owner_id: string;
  role: MembershipRole;
  created_at: string;
}

export interface TrelloConnectionStatus {
  connected: boolean;
  username: string | null;
  account_id?: string | null;
}

export interface TrelloProviderAccount {
  id: string;
  username: string;
}

export interface GithubConnectionStatus {
  connected: boolean;
  username: string | null;
  account_id?: string | null;
}

export interface GithubProviderAccount {
  id: string;
  username: string;
}

export interface JiraConnectionStatus {
  connected: boolean;
  username: string | null;
  account_id?: string | null;
  site_name?: string | null;
  site_url?: string | null;
}

export interface JiraProviderAccount {
  id: string;
  username: string;
}

export interface JiraProject {
  id: string;
  key: string;
  name: string;
  cloud_id: string;
  jira_project_id: string;
  avatar_url: string | null;
  included: boolean;
  client_id: string | null;
  sync_status: string;
  last_synced_at: string | null;
  sync_error: string | null;
}

export interface GithubRepository {
  id: string;
  full_name: string;
  description: string | null;
  url: string;
  default_branch: string;
  private: boolean;
  included: boolean;
  client_id: string | null;
  sync_status: "not_started" | "running" | "completed" | "failed" | string;
  last_synced_at: string | null;
  sync_error: string | null;
}

export interface TrelloBoard {
  id: string;
  name: string;
  url: string;
  excluded: boolean;
  sync_status: "not_started" | "running" | "completed" | "failed" | string;
  last_synced_at: string | null;
  sync_error: string | null;
}

export type TrelloMappingType = "board" | "label" | "list";

export interface TrelloClientMapping {
  board_id: string;
  board_name: string;
  mapping_type: TrelloMappingType;
  external_ref: string;
  client_name: string;
}

export interface WorkspaceContextSnapshot {
  workspace_id: string;
  workspace_name: string;
  generated_at: string;
  token_budget: number;
  estimated_tokens: number;
  connected_accounts: Array<{
    id: string;
    provider: string;
    account_name: string;
  }>;
  sources: Array<{
    id: string;
    provider: string;
    name: string;
    url: string;
    account_name: string;
    sync_status: string;
    last_synced_at: string | null;
    sync_error?: string | null;
  }>;
  clients: Array<{ id: string; name: string }>;
  members: Array<{
    id: string;
    external_id: string;
    name: string;
    username: string;
    role_tag: "unknown" | "client" | "internal";
  }>;
  item_count: number;
  chunks: Array<{
    index: number;
    estimated_tokens: number;
    items: Array<{
      item_type: "source" | "card" | "comment" | "person" | "commit";
      source_id: string | null;
      source_name: string | null;
      client_id: string | null;
      client_name: string | null;
      card_id: string | null;
      external_id: string | null;
      title: string | null;
      text: string;
      summary: string | null;
      url: string | null;
      occurred_at: string | null;
      metadata: Record<string, unknown>;
    }>;
  }>;
}

export interface ContextSummaryResult {
  card_id: string;
  trello_card_id: string;
  title: string;
  summary: string;
  content_hash: string;
  cached: boolean;
}

export interface SimilarContextCard {
  card_id: string;
  trello_card_id: string;
  title: string;
  description: string;
  url: string;
  client_id: string | null;
  client_name: string | null;
  similarity: number;
}

export interface CitedSource {
  source_id: string;
  source_type: "card" | "comment" | "commit" | "project";
  title?: string | null;
  url?: string | null;
  valid: boolean;
}

export interface NeedInsight {
  text: string;
  priority: "high" | "medium" | "low";
  sources: CitedSource[];
}

export interface PatternInsight {
  text: string;
  sources: CitedSource[];
}

export interface StakeholderInsight {
  name: string;
  role: string;
  sources: CitedSource[];
}

export interface RiskInsight {
  text: string;
  severity: "high" | "medium" | "low";
  sources: CitedSource[];
}

export interface ClientNeedsReport {
  client_name: string;
  executive_summary: string;
  needs: NeedInsight[];
  patterns: PatternInsight[];
  stakeholders: StakeholderInsight[];
  risks: RiskInsight[];
}

export interface Skill {
  id: string;
  workspace_id: string | null;
  name: string;
  slug: string;
  version: number;
  description: string;
  prompt_template: string;
  scope_json: Record<string, unknown>;
  output_schema_json: Record<string, unknown>;
  model_config_json: Record<string, unknown>;
  is_active: boolean;
  created_at: string;
  updated_at: string;
}

export interface Insight {
  id: string;
  run_id: string;
  workspace_id: string;
  client_id: string | null;
  category: "need" | "pattern" | "stakeholder" | "risk";
  title: string;
  detail: string;
  severity_or_priority: string | null;
  confidence: number;
  source_refs: CitedSource[];
  feedback: "thumbs_up" | "thumbs_down" | null;
  feedback_notes: string | null;
  created_at: string;
}

export interface Run {
  id: string;
  skill_id: string;
  workspace_id: string;
  user_id: string | null;
  client_id: string | null;
  skill_name?: string | null;
  client_name?: string | null;
  status: "pending" | "running" | "completed" | "failed";
  trigger: "manual" | "scheduled" | "webhook";
  tokens_in: number;
  tokens_out: number;
  cost_usd: number;
  citations_valid: boolean;
  error: string | null;
  started_at: string | null;
  completed_at: string | null;
  created_at: string;
}

export interface RunDetail extends Run {
  output_json: ClientNeedsReport | null;
  insights: Insight[];
}

export interface ClientSummary {
  id: string;
  workspace_id: string;
  name: string;
  cards_count: number;
  insights_count: number;
  needs_count: number;
  risks_count: number;
  last_run_at: string | null;
  created_at: string;
  updated_at: string;
}

export interface TimelineEvent {
  id: string;
  event_type: "card_activity" | "commit" | "skill_run" | "risk_identified" | "need_extracted";
  title: string;
  detail: string | null;
  timestamp: string;
  source: string;
  source_url: string | null;
  severity_or_priority: string | null;
  metadata: Record<string, unknown>;
}

export interface ClientProfile {
  client: ClientSummary;
  total_cards: number;
  total_insights: number;
  needs: Insight[];
  patterns: Insight[];
  stakeholders: Insight[];
  risks: Insight[];
  timeline: TimelineEvent[];
  recent_runs: Run[];
}


