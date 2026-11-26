import {
  User,
  AuthResponse,
  Agent,
  AgentCreateInput,
  AgentUpdateInput,
  ApiKeyItem,
  KnowledgeDocument,
  RagQueryResponse,
} from '@/types';

const API_BASE_URL = process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8000/api/v1';

class ApiClient {
  public getToken(): string | null {
    if (typeof window === 'undefined') return null;
    return localStorage.getItem('voiceagent_token');
  }

  setToken(token: string): void {
    if (typeof window !== 'undefined') {
      localStorage.setItem('voiceagent_token', token);
    }
  }

  removeToken(): void {
    if (typeof window !== 'undefined') {
      localStorage.removeItem('voiceagent_token');
      localStorage.removeItem('voiceagent_user');
    }
  }

  setUser(user: User): void {
    if (typeof window !== 'undefined') {
      localStorage.setItem('voiceagent_user', JSON.stringify(user));
    }
  }

  getUser(): User | null {
    if (typeof window === 'undefined') return null;
    const data = localStorage.getItem('voiceagent_user');
    return data ? JSON.parse(data) : null;
  }

  private async request<T>(endpoint: string, options: RequestInit = {}): Promise<T> {
    const token = this.getToken();
    const headers: Record<string, string> = {
      'Content-Type': 'application/json',
      ...(options.headers as Record<string, string>),
    };

    if (token) {
      headers['Authorization'] = `Bearer ${token}`;
    }

    const response = await fetch(`${API_BASE_URL}${endpoint}`, {
      ...options,
      headers,
    });

    if (response.status === 204) {
      return {} as T;
    }

    const data = await response.json();
    if (!response.ok) {
      throw new Error(data.detail || 'An unexpected API error occurred');
    }
    return data as T;
  }

  // Auth Endpoints
  async register(data: { email: string; password: string; full_name?: string }): Promise<AuthResponse> {
    const res = await this.request<AuthResponse>('/auth/register', {
      method: 'POST',
      body: JSON.stringify(data),
    });
    this.setToken(res.access_token);
    this.setUser(res.user);
    return res;
  }

  async login(data: { email: string; password: string }): Promise<AuthResponse> {
    const res = await this.request<AuthResponse>('/auth/login', {
      method: 'POST',
      body: JSON.stringify(data),
    });
    this.setToken(res.access_token);
    this.setUser(res.user);
    return res;
  }

  async getMe(): Promise<User> {
    return this.request<User>('/auth/me');
  }

  // Agent Endpoints
  async listAgents(): Promise<Agent[]> {
    return this.request<Agent[]>('/agents');
  }

  async createAgent(data: AgentCreateInput): Promise<Agent> {
    return this.request<Agent>('/agents', {
      method: 'POST',
      body: JSON.stringify(data),
    });
  }

  async getAgent(id: string): Promise<Agent> {
    return this.request<Agent>(`/agents/${id}`);
  }

  async updateAgent(id: string, data: AgentUpdateInput): Promise<Agent> {
    return this.request<Agent>(`/agents/${id}`, {
      method: 'PUT',
      body: JSON.stringify(data),
    });
  }

  async deleteAgent(id: string): Promise<void> {
    await this.request<void>(`/agents/${id}`, {
      method: 'DELETE',
    });
  }

  async publishAgent(id: string, data: { is_published: boolean; slug?: string }): Promise<Agent> {
    return this.request<Agent>(`/agents/${id}/publish`, {
      method: 'POST',
      body: JSON.stringify(data),
    });
  }

  async getPublicAgent(slug: string): Promise<any> {
    return this.request<any>(`/agents/public/${slug}`);
  }

  // Secrets Vault Endpoints
  async listKeys(): Promise<ApiKeyItem[]> {
    return this.request<ApiKeyItem[]>('/auth/secrets');
  }

  async saveKey(provider: string, apiKey: string): Promise<ApiKeyItem> {
    return this.request<ApiKeyItem>('/auth/secrets', {
      method: 'POST',
      body: JSON.stringify({ provider, api_key: apiKey }),
    });
  }

  async deleteKey(provider: string): Promise<void> {
    await this.request<void>(`/auth/secrets/${provider}`, {
      method: 'DELETE',
    });
  }

  // Streaming Text Chat SSE Client
  async streamChat(
    agentId: string,
    message: string,
    sessionId?: string,
    callbacks?: {
      onToken?: (token: string) => void;
      onFirstToken?: (latencyMs: number) => void;
      onDone?: (data: { session_id: string; first_token_latency_ms: number; total_latency_ms: number; content: string }) => void;
      onError?: (error: { error: string; code?: string }) => void;
    }
  ): Promise<void> {
    const token = this.getToken();
    const response = await fetch(`${API_BASE_URL}/chat/${agentId}`, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        ...(token ? { Authorization: `Bearer ${token}` } : {}),
      },
      body: JSON.stringify({ message, session_id: sessionId }),
    });

    if (!response.ok) {
      const err = await response.json().catch(() => ({ detail: 'Chat request failed' }));
      throw new Error(err.detail || 'Chat request failed');
    }

    if (!response.body) {
      throw new Error('ReadableStream not supported by browser.');
    }

    const reader = response.body.getReader();
    const decoder = new TextDecoder('utf-8');
    let buffer = '';

    while (true) {
      const { done, value } = await reader.read();
      if (done) break;

      buffer += decoder.decode(value, { stream: true });
      const events = buffer.split('\n\n');
      buffer = events.pop() || '';

      for (const eventBlock of events) {
        if (!eventBlock.trim()) continue;

        let eventType = 'message';
        let dataStr = '';

        const lines = eventBlock.split('\n');
        for (const line of lines) {
          if (line.startsWith('event:')) {
            eventType = line.slice(6).trim();
          } else if (line.startsWith('data:')) {
            dataStr = line.slice(5).trim();
          }
        }

        if (!dataStr) continue;

        try {
          const parsed = JSON.parse(dataStr);
          if (eventType === 'first_token') {
            callbacks?.onFirstToken?.(parsed.latency_ms);
          } else if (eventType === 'token') {
            callbacks?.onToken?.(parsed.token);
          } else if (eventType === 'done') {
            callbacks?.onDone?.(parsed);
          } else if (eventType === 'error') {
            callbacks?.onError?.(parsed);
          }
        } catch {
          // ignore non-json chunk
        }
      }
    }
  }

  // Knowledge Base & RAG Endpoints
  async listKnowledge(agentId?: string): Promise<KnowledgeDocument[]> {
    const query = agentId ? `?agent_id=${encodeURIComponent(agentId)}` : '';
    return this.request<KnowledgeDocument[]>(`/knowledge${query}`);
  }

  async uploadKnowledge(agentId: string, file: File): Promise<KnowledgeDocument> {
    const token = this.getToken();
    const formData = new FormData();
    formData.append('agent_id', agentId);
    formData.append('file', file);

    const response = await fetch(`${API_BASE_URL}/knowledge/upload`, {
      method: 'POST',
      headers: {
        ...(token ? { Authorization: `Bearer ${token}` } : {}),
      },
      body: formData,
    });

    const data = await response.json();
    if (!response.ok) {
      throw new Error(data.detail || 'Document upload failed');
    }
    return data as KnowledgeDocument;
  }

  async deleteKnowledge(documentId: string): Promise<void> {
    await this.request<void>(`/knowledge/${documentId}`, {
      method: 'DELETE',
    });
  }

  async queryTestKnowledge(
    agentId: string,
    query: string,
    topK = 4,
    similarityThreshold = 0.35
  ): Promise<RagQueryResponse> {
    return this.request<RagQueryResponse>('/knowledge/query-test', {
      method: 'POST',
      body: JSON.stringify({
        agent_id: agentId,
        query,
        top_k: topK,
        similarity_threshold: similarityThreshold,
      }),
    });
  }
}

export const api = new ApiClient();
