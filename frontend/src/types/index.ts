export interface User {
  id: string;
  email: string;
  full_name?: string;
  is_active: boolean;
  created_at: string;
}

export interface AuthResponse {
  access_token: string;
  token_type: string;
  user: User;
}

export interface Agent {
  id: string;
  user_id: string;
  name: string;
  slug: string;
  description?: string;
  personality?: string;
  system_prompt: string;
  llm_provider: 'gemini' | 'openai';
  llm_model: string;
  temperature: number;
  stt_provider: string;
  stt_language: string;
  tts_provider: string;
  tts_voice: string;
  is_published: boolean;
  is_active: boolean;
  created_at: string;
  updated_at: string;
}

export interface AgentCreateInput {
  name: string;
  slug?: string;
  description?: string;
  personality?: string;
  system_prompt: string;
  llm_provider: string;
  llm_model: string;
  temperature: number;
  stt_provider: string;
  stt_language: string;
  tts_provider: string;
  tts_voice: string;
}

export interface AgentUpdateInput {
  name?: string;
  slug?: string;
  description?: string;
  personality?: string;
  system_prompt?: string;
  llm_provider?: string;
  llm_model?: string;
  temperature?: number;
  stt_provider?: string;
  stt_language?: string;
  tts_provider?: string;
  tts_voice?: string;
  is_published?: boolean;
  is_active?: boolean;
}

export interface ApiKeyItem {
  id: string;
  provider: string;
  masked_key: string;
  created_at: string;
  updated_at: string;
}

export interface KnowledgeDocument {
  id: string;
  user_id: string;
  agent_id?: string | null;
  filename: string;
  file_type: string;
  file_size: number;
  status: 'processing' | 'indexed' | 'failed' | string;
  chunk_count: number;
  created_at: string;
}

export interface RagChunkResult {
  document_id: string;
  filename: string;
  chunk_index: number;
  content: string;
  score: number;
}

export interface RagQueryResponse {
  agent_id: string;
  query: string;
  results: RagChunkResult[];
}

export interface ToolItem {
  id: string;
  user_id: string;
  name: string;
  description: string;
  parameters_schema: string;
  is_sensitive: boolean;
  execution_type: 'mock' | 'webhook' | 'built_in';
  webhook_url?: string | null;
  webhook_method?: string;
  webhook_headers?: string;
  webhook_body_template?: string | null;
  agent_ids: string[];
  created_at: string;
  updated_at: string;
}

export interface BuiltinToolPreset {
  name: string;
  description: string;
  parameters_schema: string;
  is_sensitive: boolean;
  execution_type: 'built_in';
}

export interface ToolCreateInput {
  name: string;
  description: string;
  parameters_schema: string;
  is_sensitive: boolean;
  execution_type: 'mock' | 'webhook' | 'built_in';
  webhook_url?: string;
  webhook_method?: string;
  webhook_headers?: string;
  webhook_body_template?: string;
}

export interface AnalyticsOverview {
  total_sessions: number;
  total_minutes: number;
  error_count: number;
  avg_stt_latency_ms: number;
  avg_llm_first_token_ms: number;
  avg_tts_first_audio_ms: number;
  avg_e2e_latency_ms: number;
  sessions_per_day: Array<{ date: string; sessions: number; errors: number }>;
  top_agents: Array<{ agent_id: string; agent_name: string; sessions: number; avg_e2e_ms: number }>;
}

export interface AnalyticsSessionSummary {
  id: string;
  agent_id: string;
  agent_name: string;
  is_public: boolean;
  started_at: string | null;
  ended_at: string | null;
  duration_seconds: number;
  status: string;
  total_turns: number;
  avg_latency_ms: number;
}

export interface AnalyticsMessageDetail {
  id: string;
  role: string;
  content: string;
  audio_duration_ms: number;
  stt_latency_ms: number;
  llm_first_token_ms: number;
  llm_latency_ms: number;
  tts_first_audio_ms: number;
  tts_latency_ms: number;
  e2e_latency_ms: number;
  tool_calls?: Array<{ name: string; arguments: Record<string, unknown> }> | null;
  tool_results?: Array<{ name: string; result: Record<string, unknown>; duration_ms: number }> | null;
  rag_sources?: Array<{ file: string; score: number; chunk_index: number }> | null;
  interrupted: boolean;
  created_at: string | null;
}

export interface AnalyticsSessionDetail extends AnalyticsSessionSummary {
  messages: AnalyticsMessageDetail[];
}
