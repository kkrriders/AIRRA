/**
 * Type definitions matching the backend API schemas.
 *
 * Senior Engineering Note:
 * These types are derived from the backend Pydantic schemas
 * to ensure type safety across the full stack.
 */

export type IncidentStatus =
  | "detected"
  | "analyzing"
  | "pending_approval"
  | "approved"
  | "executing"
  | "resolved"
  | "failed"
  | "escalated";

export type IncidentSeverity = "critical" | "high" | "medium" | "low";

export type ActionType =
  | "restart_pod"
  | "scale_up"
  | "scale_down"
  | "rollback_deployment"
  | "toggle_feature_flag"
  | "clear_cache"
  | "drain_node"
  | "custom";

export type ActionStatus =
  | "proposed"
  | "pending_approval"
  | "approved"
  | "rejected"
  | "executing"
  | "succeeded"
  | "failed"
  | "rolled_back";

export type RiskLevel = "low" | "medium" | "high" | "critical";

export interface Incident {
  id: string;
  title: string;
  description: string;
  status: IncidentStatus;
  severity: IncidentSeverity;
  affected_service: string;
  affected_components: string[];
  detected_at: string;
  resolved_at: string | null;
  resolution_time_seconds: number | null;
  detection_source: string;
  metrics_snapshot: Record<string, any>;
  context: Record<string, any>;
  created_at: string;
  updated_at: string;
}

export interface Hypothesis {
  id: string;
  incident_id: string;
  description: string;
  category: string;
  confidence_score: number;
  rank: number;
  evidence: Record<string, any>;
  supporting_signals: string[];
  llm_model: string;
  validated: boolean;
  validation_feedback: string | null;
  created_at: string;
}

export interface Action {
  id: string;
  incident_id: string;
  action_type: ActionType;
  name: string;
  description: string;
  target_service: string;
  target_resource: string | null;
  risk_level: RiskLevel;
  risk_score: number;
  blast_radius: string;
  status: ActionStatus;
  requires_approval: boolean;
  approved_by: string | null;
  approved_at: string | null;
  rejection_reason: string | null;
  execution_mode: string;
  executed_at: string | null;
  execution_duration_seconds: number | null;
  execution_result: Record<string, any> | null;
  parameters: Record<string, any>;
  created_at: string;
  updated_at: string;
}

export interface IncidentWithRelations extends Incident {
  hypotheses: Hypothesis[];
  actions: Action[];
}

export interface IncidentListResponse {
  items: Incident[];
  total: number;
  page: number;
  page_size: number;
  pages: number;
}

export interface CreateIncidentRequest {
  title: string;
  description: string;
  severity: IncidentSeverity;
  affected_service: string;
  affected_components?: string[];
  detected_at?: string;
  detection_source?: string;
  metrics_snapshot?: Record<string, any>;
  context?: Record<string, any>;
}

export interface ApprovalRequest {
  approved_by: string;
  execution_mode?: string;
}

export interface RejectionRequest {
  rejected_by: string;
  rejection_reason: string;
}

export interface AnalyzeResponse {
  status: string;
  hypotheses_generated: number;
  action_recommended: boolean;
  tokens_used: number;
}

export interface QuickIncidentRequest {
  service_name: string;
  title?: string;
  description?: string;
  severity?: IncidentSeverity;
  metrics_snapshot?: Record<string, any>;
  context?: Record<string, any>;
}

export interface Insights {
  period_days: number;
  total_incidents: number;
  resolved_incidents: number;
  resolution_rate: number;
  avg_resolution_time_seconds: number;
  avg_resolution_time_minutes: number;
  hypothesis_accuracy: number;
  total_hypotheses: number;
  correct_hypotheses: number;
  successful_actions: number;
  patterns_learned: number;
}

export interface Pattern {
  pattern_id: string;
  name: string;
  category: string;
  occurrence_count: number;
  success_rate: number;
  confidence_adjustment: number;
}

export interface PatternsResponse {
  total_patterns: number;
  patterns: Pattern[];
}
