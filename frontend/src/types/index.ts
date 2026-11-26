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
